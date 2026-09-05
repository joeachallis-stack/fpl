"""Hierarchical minutes model: a distribution over next gameweek's minutes, per player.

Why a distribution and not an average: FPL points don't scale smoothly with minutes.
There is a cliff at 60 (1 appearance point below it, 2 at or above) and DefCon triggers
on a fixed count of defensive actions, which a 45-minute outing almost never reaches.
Two players averaging 60 minutes — one steady on 60/60, one lumpy on 75/45 — score
differently, and an average cannot tell them apart.

So: role buckets in, scoring-aligned bands out.

    role buckets   started_finished / started_withdrawn / benched_used / unused
                   — how the minutes were earned. Role is what persists week to week,
                     so it is what carries predictive signal.
    bands          p_zero / p_1_59 / p_60_plus
                   — what the scoring rules actually care about. Nothing downstream
                     needs to know whether 70 minutes came from the bench.

The trained path blends completed current-season roles, code-matched prior-season match
rows, and a position/price peer prior. The original empirical rules remain the automatic
fallback when the historical cache or fitted artifact is unavailable.

Usage:
    python scripts/minutes.py                    # write data/minutes.json, print a summary
    python scripts/minutes.py --show 20          # also print the top 20 by expected minutes
    python scripts/minutes.py archive            # freeze this GW's predictions to minutes/
    python scripts/minutes.py resolve --gw 3     # fill in what actually happened
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import train_minutes

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "minutes.json"
ARCHIVE_DIR = ROOT / "minutes"

MODEL_VERSION = "hierarchical-v2"
TRAINED_MODEL = ROOT / "models" / "minutes_params.json"

# Fewest gameweeks that counts as real evidence. Two is deliberate: this season is all
# the per-gameweek history the FPL API exposes (history_past is season totals only), so
# a higher bar would put the entire pool on fallback until roughly GW5.
MIN_OBS = 2

# Recency half-life in gameweeks — how fast an old observation stops counting. Squad
# roles shift within a season, not just between them, so this weights recent gameweeks
# harder rather than blending season against season.
#
# NOT the 0.85^(t-1) horizon discount, which prices *future* gameweeks. Different
# question, different number; don't collapse them.
#
# Parked at 5 rather than fitted: with two gameweeks of data every weight is within 15%
# of every other, so nothing measurable turns on it yet. Revisit once there's enough
# history for it to bite.
DECAY_HALFLIFE_GWS = 5.0

# Two observations can't establish certainty, so no band is ever allowed to be 0 or 1.
# This is not smoothing a thin sample toward a prior — it's declining to claim a player
# is guaranteed to do anything on the strength of two games.
BAND_FLOOR = 0.05

# Minutes assumed for a player carrying a fitness flag who does play: eased back in off
# the bench rather than starting. See rule 2 in docs/IDEAS.md.
DOUBTFUL_MINUTES = 30.0

# Minutes floor for an owned player with too little evidence. You can't decline to
# recommend someone already in the squad — projecting the team needs a number.
OWNED_FLOOR_MINUTES = 60.0

# A player with no minutes at all this season is not in the team, whatever their price
# or fitness says. Halves whatever the rules above produced.
NEVER_PLAYED_FACTOR = 0.5

OUT_STATUSES = {"i", "s", "u"}  # injured, suspended, unavailable — hard zero


def load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def completed_fixture_ids(fixtures: list[dict]) -> set[int]:
    """Fixtures whose player rows are safe to use as historical evidence.

    The element-summary endpoint creates an all-zero history row before a fixture has
    finished. Round number alone therefore cannot distinguish evidence from a placeholder.
    `finished_provisional` is sufficient for forecasting; official corrections are handled
    separately by the finalized observations ledger.
    """
    return {
        fixture["id"]
        for fixture in fixtures
        if fixture.get("finished") or fixture.get("finished_provisional")
    }


def completed_history(history: list[dict], fixtures: list[dict]) -> list[dict]:
    completed = completed_fixture_ids(fixtures)
    return [row for row in history if row.get("fixture") in completed]


def load_trained_context() -> tuple[dict, dict[int, list[dict]]] | None:
    """Load the fitted parameters and safely code-matched prior-season match rows."""
    if not TRAINED_MODEL.exists() or not train_minutes.GWS.exists() or not train_minutes.PLAYERS.exists():
        return None
    model_bytes = TRAINED_MODEL.read_bytes()
    model = json.loads(model_bytes)
    model["_artifact_sha256"] = hashlib.sha256(model_bytes).hexdigest()
    prior_rows, _ = train_minutes.load_season(
        train_minutes.GWS, train_minutes.PLAYERS, True
    )
    by_code = defaultdict(list)
    for row in prior_rows:
        by_code[row["element"]].append(row)
    return model, by_code


def role_bucket(row: dict) -> str:
    minutes, started = row["minutes"], row["starts"]
    if started and minutes >= 90:
        return "started_finished"
    if started:
        return "started_withdrawn"
    if minutes > 0:
        return "benched_used"
    return "unused"


def band(minutes: int) -> str:
    if minutes == 0:
        return "p_zero"
    return "p_1_59" if minutes < 60 else "p_60_plus"


def apply_floor(bands: dict[str, float]) -> dict[str, float]:
    """Keep every band off 0 and 1, then renormalise so they still sum to 1."""
    floored = {k: max(v, BAND_FLOOR) for k, v in bands.items()}
    total = sum(floored.values())
    return {k: v / total for k, v in floored.items()}


def bands_from_minutes(expected: float) -> dict[str, float]:
    """Collapse a single expected-minutes figure into bands.

    Used only by the fallback rules, which produce a point estimate rather than a
    distribution. Deliberately crude: it splits the mass either side of the 60 cliff in
    proportion to where the estimate sits, so a 30-minute estimate reads as "probably a
    sub", not "definitely under 60".
    """
    if expected <= 0:
        return apply_floor({"p_zero": 1.0, "p_1_59": 0.0, "p_60_plus": 0.0})
    p_60 = min(expected / 90.0, 1.0)
    p_play = min(expected / 45.0, 1.0)
    raw = {
        "p_zero": max(1.0 - p_play, 0.0),
        "p_1_59": max(p_play - p_60, 0.0),
        "p_60_plus": p_60,
    }
    total = sum(raw.values()) or 1.0
    return apply_floor({k: v / total for k, v in raw.items()})


def weighted(history: list[dict], current_gw: int) -> tuple[dict, dict, float, float]:
    """Recency-weighted role buckets, bands, expected minutes, and effective sample size."""
    roles = {k: 0.0 for k in
             ("started_finished", "started_withdrawn", "benched_used", "unused")}
    bands = {"p_zero": 0.0, "p_1_59": 0.0, "p_60_plus": 0.0}
    total_w = exp_mins = 0.0
    for row in history:
        age = max(current_gw - row["round"], 0)
        w = 0.5 ** (age / DECAY_HALFLIFE_GWS)
        roles[role_bucket(row)] += w
        bands[band(row["minutes"])] += w
        exp_mins += w * row["minutes"]
        total_w += w
    if not total_w:
        return roles, bands, 0.0, 0.0
    roles = {k: v / total_w for k, v in roles.items()}
    bands = {k: v / total_w for k, v in bands.items()}
    return roles, apply_floor(bands), exp_mins / total_w, total_w


def trained_prediction(
    player: dict,
    history: list[dict],
    current_gw: int,
    team_name: str,
    position: str,
    context: tuple[dict, dict[int, list[dict]]],
) -> dict:
    """Hierarchical bands/minutes using current rows, stable-code history and peer prior."""
    model, prior_by_code = context
    params = model["selected"]
    group = f"{position}_{player['now_cost'] // 10}"
    peer = (
        model["peer_priors"]["group"].get(group)
        or model["peer_priors"]["position"][position]
    )
    peer_weight = params["peer_prior_weight"]
    band_counts = {key: peer_weight * peer["bands"][key] for key in peer["bands"]}
    state_counts = {
        key: peer_weight * peer["role_states"][key] for key in train_minutes.ROLE_STATES
    }
    state_minutes = {
        key: state_counts[key] * peer["conditional_minutes_by_state"][key]
        for key in train_minutes.ROLE_STATES
    }
    minute_total = peer_weight * peer["exp_minutes"]
    current_weight = prior_weight = 0.0
    prior_rows = prior_by_code.get(player["code"], [])

    observations = [
        ({"minutes": row["minutes"], "starts": row["starts"]},
         current_gw - row["round"], False, row.get("team_name", team_name))
        for row in history
    ] + [
        (row, current_gw + params["offseason_gap_gws"] + 38 - row["gw"], True, row["team"])
        for row in prior_rows
    ]
    for row, age, is_prior, observed_team in observations:
        weight = 0.5 ** (age / params["decay_halflife_gws"])
        if observed_team != team_name:
            weight *= params["club_change_retention"]
        band_counts[band(row["minutes"])] += weight
        state = train_minutes.role(row)
        state_counts[state] += weight
        state_minutes[state] += weight * row["minutes"]
        minute_total += weight * row["minutes"]
        if is_prior:
            prior_weight += weight
        else:
            current_weight += weight
    total_weight = peer_weight + current_weight + prior_weight
    states = train_minutes.normalize(
        state_counts, train_minutes.ROLE_STATES, params["state_probability_floor"]
    )
    conditional = {
        key: (
            state_minutes[key] / state_counts[key]
            if state_counts[key] else train_minutes.STATE_DEFAULT_MINUTES[key]
        )
        for key in train_minutes.ROLE_STATES
    }
    state_bands = {
        "p_zero": states["unused"],
        "p_1_59": states["cameo_1_29"] + states["cameo_30_59"] + states["starter_1_59"],
        "p_60_plus": states["cameo_60_plus"] + states["starter_60_74"]
        + states["starter_75_89"] + states["starter_90_plus"],
    }
    bands = train_minutes.normalize(
        state_bands if params["state_driven_outputs"] else band_counts,
        train_minutes.BANDS,
        params["probability_floor"],
    )
    exp_minutes = (
        sum(states[key] * conditional[key] for key in train_minutes.ROLE_STATES)
        if params["state_driven_outputs"] else minute_total / total_weight
    )
    start_states = [key for key in train_minutes.ROLE_STATES if key.startswith("starter_")]
    cameo_states = [key for key in train_minutes.ROLE_STATES if key.startswith("cameo_")]
    p_start = sum(states[key] for key in start_states)
    p_cameo = sum(states[key] for key in cameo_states)
    return {
        "bands": bands,
        "role_states": states,
        "conditional_minutes_by_state": conditional,
        "p_start": p_start,
        "p_cameo": p_cameo,
        "exp_minutes_given_start": (
            sum(states[key] * conditional[key] for key in start_states) / p_start
            if p_start else 0.0
        ),
        "exp_minutes_given_cameo": (
            sum(states[key] * conditional[key] for key in cameo_states) / p_cameo
            if p_cameo else 0.0
        ),
        "exp_minutes": exp_minutes,
        "prior_n_obs": len(prior_rows),
        "audit": {
            "training_model_version": model["model_version"],
            "training_season": model["training_season"],
            "gameweeks_sha256": model["gameweeks_sha256"],
            "model_artifact_sha256": model["_artifact_sha256"],
            "stable_player_code": player["code"],
            "peer_group": group if group in model["peer_priors"]["group"] else position,
            "peer_effective_weight": round(peer_weight, 4),
            "current_effective_weight": round(current_weight, 4),
            "prior_season_effective_weight": round(prior_weight, 4),
            "parameters": params,
        },
    }


def predict(
    player: dict,
    history: list[dict],
    current_gw: int,
    owned: bool,
    trained: dict | None = None,
) -> dict:
    """The fallback stack from docs/IDEAS.md, in order. Rules are numbered to match."""
    status = player["status"]
    chance = player.get("chance_of_playing_next_round")
    played_this_season = player["minutes"] > 0

    roles, emp_bands, emp_mins, eff_n = weighted(history, current_gw)
    if trained:
        emp_bands = trained["bands"]
        emp_mins = trained["exp_minutes"]
        eff_n = (
            trained["audit"]["peer_effective_weight"]
            + trained["audit"]["current_effective_weight"]
            + trained["audit"]["prior_season_effective_weight"]
        )
    record = {
        "element": player["id"],
        "web_name": player["web_name"],
        "team": player["team"],
        "element_type": player["element_type"],
        "gw": current_gw,
        "role_buckets": {k: round(v, 4) for k, v in roles.items()},
        "role_states": (
            {k: round(v, 4) for k, v in trained["role_states"].items()}
            if trained else None
        ),
        "conditional_minutes_by_state": (
            {k: round(v, 1) for k, v in trained["conditional_minutes_by_state"].items()}
            if trained else None
        ),
        "p_start": round(trained["p_start"], 4) if trained else None,
        "p_cameo": round(trained["p_cameo"], 4) if trained else None,
        "exp_minutes_given_start": (
            round(trained["exp_minutes_given_start"], 1) if trained else None
        ),
        "exp_minutes_given_cameo": (
            round(trained["exp_minutes_given_cameo"], 1) if trained else None
        ),
        "n_obs": len(history),
        "effective_n": round(eff_n, 3),
        "status": status,
        "chance_of_playing_next_round": chance,
        # Inputs the rules read, frozen alongside the prediction. Without these the
        # archive can score the model but can't retire the constants inside it.
        "season_minutes": player["minutes"],
        "now_cost": player["now_cost"],
        "insufficient_evidence": False,
        "override": None,
        "prior_n_obs": trained["prior_n_obs"] if trained else 0,
        "training_audit": trained["audit"] if trained else None,
    }

    # Rule 1 — injured, suspended or unavailable. Hard zero, not a blended signal.
    if status in OUT_STATUSES:
        record["override"] = f"status={status}"
        record["source"] = "override_out"
        exp = 0.0
        bands = {"p_zero": 1.0, "p_1_59": 0.0, "p_60_plus": 0.0}

    # Rule 2 — doubtful. Scale by the API's own fitness percentage. Note the direction:
    # chance_of_playing is the chance of PLAYING, so 75 means nearly fit.
    elif status == "d":
        record["override"] = f"doubtful={chance}%"
        record["source"] = "override_doubtful"
        exp = (chance or 0) / 100.0 * DOUBTFUL_MINUTES
        bands = bands_from_minutes(exp)

    # Rule 5 — enough evidence. The empirical distribution, no fallback needed.
    elif trained:
        record["source"] = "hierarchical_trained"
        exp, bands = emp_mins, emp_bands

    # Legacy fallback when the historical training cache is unavailable.
    elif len(history) >= MIN_OBS:
        record["source"] = "empirical_fallback"
        exp, bands = emp_mins, emp_bands

    # Rule 3 — thin evidence but owned. Can't decline to recommend someone in the squad.
    elif owned:
        record["source"] = "fallback_owned_floor"
        exp = OWNED_FLOOR_MINUTES
        bands = bands_from_minutes(exp)

    # Rule 4 — thin evidence, not owned. Refuse rather than guess.
    else:
        record["source"] = "insufficient_evidence"
        record["insufficient_evidence"] = True
        exp, bands = 0.0, {"p_zero": 1.0, "p_1_59": 0.0, "p_60_plus": 0.0}

    # Rule 6 — never played this season. Whatever the rules above said, halve it: a
    # player with no minutes is not in the team, whatever price or fitness implies.
    # Skipped where the answer is already zero, and where refusing to guess is the
    # answer — halving a refusal means nothing.
    if not trained and not played_this_season and exp > 0 and not record["insufficient_evidence"]:
        exp *= NEVER_PLAYED_FACTOR
        bands = bands_from_minutes(exp)
        record["never_played_penalty"] = True

    record["bands"] = {k: round(v, 4) for k, v in bands.items()}
    record["exp_minutes"] = round(exp, 1)
    return record


def archive_path(gw: int) -> Path:
    return ARCHIVE_DIR / f"gw{gw:02d}.jsonl"


def cmd_archive(payload: dict) -> None:
    """Freeze this gameweek's predictions, inputs included, before the deadline.

    The inputs matter as much as the prediction. A row that records only "we said 22
    minutes" can score the model; a row that also records "he was flagged 75% fit with 0
    minutes played" can go on to replace the constants the rule is built from.
    """
    gw = payload["meta"]["gw"]
    path = archive_path(gw)
    if path.exists():
        print(f"{path.relative_to(ROOT)} already exists — not overwriting a frozen prediction")
        print("  delete it by hand if you really mean to re-freeze")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for record in payload["players"].values():
            row = dict(record)
            row["model_version"] = payload["meta"]["model_version"]
            row["generated_at"] = payload["meta"]["generated_at"]
            row["actual_minutes"] = None
            row["actual_band"] = None
            f.write(json.dumps(row) + "\n")
    print(f"froze {len(payload['players'])} predictions to {path.relative_to(ROOT)}")


def cmd_resolve(gw: int) -> None:
    """Fill in what actually happened, from the cached per-player histories."""
    path = archive_path(gw)
    if not path.exists():
        raise SystemExit(f"no archive for GW{gw} — run `minutes.py archive` before the deadline")

    with open(path) as f:
        rows = [json.loads(line) for line in f if line.strip()]

    resolved = missing = 0
    for row in rows:
        summary = DATA_DIR / f"element_summary/{row['element']}.json"
        if not summary.exists():
            missing += 1
            continue
        with open(summary) as f:
            played = [h for h in json.load(f)["history"] if h["round"] == gw]
        if not played:
            missing += 1
            continue
        # A player can appear twice in a double gameweek; minutes are the season's total
        # for that round, so sum them.
        actual = sum(h["minutes"] for h in played)
        row["actual_minutes"] = actual
        row["actual_band"] = band(actual)
        resolved += 1

    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    scored = [r for r in rows if r["actual_minutes"] is not None]
    if scored:
        mae = sum(abs(r["actual_minutes"] - r["exp_minutes"]) for r in scored) / len(scored)
        hit = sum(1 for r in scored if r["actual_band"] == max(r["bands"], key=r["bands"].get))
        print(f"GW{gw}: resolved {resolved}, unresolved {missing}")
        print(f"  mean absolute error   {mae:.1f} minutes")
        print(f"  modal band correct    {hit}/{len(scored)} ({hit / len(scored):.0%})")
    else:
        print(f"GW{gw}: nothing resolved — has the gameweek been played and fetched?")


def build(show: int = 0) -> dict:
    bootstrap = load("bootstrap.json")
    fixtures = load("fixtures.json")
    trained_context = load_trained_context()
    current_gw = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), None)
    if current_gw is None:
        raise SystemExit("no upcoming gameweek in bootstrap.json — season over?")

    entry = load("entry.json")
    owned: set[int] = set()
    picks_path = DATA_DIR / f"picks_gw{entry.get('current_event')}.json"
    if picks_path.exists():
        with open(picks_path) as f:
            owned = {p["element"] for p in json.load(f)["picks"]}

    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    fixtures_by_id = {fixture["id"]: fixture for fixture in fixtures}
    positions = {
        row["id"]: row["singular_name_short"] for row in bootstrap["element_types"]
    }
    records = {}
    for player in bootstrap["elements"]:
        path = DATA_DIR / f"element_summary/{player['id']}.json"
        if not path.exists():
            continue
        with open(path) as f:
            all_history = json.load(f)["history"]
        history = completed_history(all_history, fixtures)
        for row in history:
            fixture = fixtures_by_id[row["fixture"]]
            historical_team = fixture["team_h"] if row["was_home"] else fixture["team_a"]
            row["team_name"] = team_names[historical_team]
        trained = trained_prediction(
            player,
            history,
            current_gw,
            team_names[player["team"]],
            positions[player["element_type"]],
            trained_context,
        ) if trained_context else None
        records[str(player["id"])] = predict(
            player, history, current_gw, player["id"] in owned, trained
        )

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "gw": current_gw,
            "decay_halflife_gws": (
                trained_context[0]["selected"]["decay_halflife_gws"]
                if trained_context else DECAY_HALFLIFE_GWS
            ),
            "legacy_decay_halflife_gws": DECAY_HALFLIFE_GWS,
            "min_obs": MIN_OBS,
            "band_floor": BAND_FLOOR,
            "history_policy": "fixture finished or finished_provisional",
            "completed_fixtures": len(completed_fixture_ids(fixtures)),
            "trained_model": (
                trained_context[0]["model_version"] if trained_context else None
            ),
            "trained_model_sha256": (
                trained_context[0]["_artifact_sha256"] if trained_context else None
            ),
            "training_fallback": trained_context is None,
            "players": len(records),
        },
        "players": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, indent=1)

    by_source: dict[str, int] = {}
    for r in records.values():
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"wrote {OUT.relative_to(ROOT)} — {len(records)} players, GW{current_gw}")
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"  {src:<24} {n:>4}")

    if show:
        ranked = sorted(records.values(), key=lambda r: -r["exp_minutes"])[:show]
        print(f"\n{'player':<16}{'mins':>6}{'p(0)':>7}{'p(start)':>10}{'p(1-59)':>9}{'p(60+)':>8}  source")
        for r in ranked:
            b = r["bands"]
            print(f"{r['web_name']:<16}{r['exp_minutes']:>6.0f}{b['p_zero']:>7.0%}"
                  f"{(r['p_start'] or 0):>10.0%}{b['p_1_59']:>9.0%}"
                  f"{b['p_60_plus']:>8.0%}  {r['source']}")

    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--show", type=int, default=0, help="Print the top N by expected minutes")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("archive", help="freeze this gameweek's predictions to minutes/")
    p_resolve = sub.add_parser("resolve", help="fill in what actually happened for a settled GW")
    p_resolve.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()

    if args.command == "resolve":
        cmd_resolve(args.gw)
        return

    payload = build(show=args.show)
    if args.command == "archive":
        cmd_archive(payload)


if __name__ == "__main__":
    main()
