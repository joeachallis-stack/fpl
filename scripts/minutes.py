"""Empirical minutes model: a distribution over next gameweek's minutes, per player.

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

The fallback stack for thin or absent evidence is specified in docs/IDEAS.md
("Settled 2026-09-03 — the fallback stack") and implemented in predict() below.

Usage:
    python scripts/minutes.py            # write data/minutes.json, print a summary
    python scripts/minutes.py --show 20  # also print the top 20 by expected minutes
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "minutes.json"

MODEL_VERSION = "empirical-v1"

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


def predict(player: dict, history: list[dict], current_gw: int, owned: bool) -> dict:
    """The fallback stack from docs/IDEAS.md, in order. Rules are numbered to match."""
    status = player["status"]
    chance = player.get("chance_of_playing_next_round")
    played_this_season = player["minutes"] > 0

    roles, emp_bands, emp_mins, eff_n = weighted(history, current_gw)
    record = {
        "element": player["id"],
        "web_name": player["web_name"],
        "team": player["team"],
        "element_type": player["element_type"],
        "gw": current_gw,
        "role_buckets": {k: round(v, 4) for k, v in roles.items()},
        "n_obs": len(history),
        "effective_n": round(eff_n, 3),
        "status": status,
        "chance_of_playing_next_round": chance,
        "insufficient_evidence": False,
        "override": None,
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
    elif len(history) >= MIN_OBS:
        record["source"] = "empirical"
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
    if not played_this_season and exp > 0 and not record["insufficient_evidence"]:
        exp *= NEVER_PLAYED_FACTOR
        bands = bands_from_minutes(exp)
        record["never_played_penalty"] = True

    record["bands"] = {k: round(v, 4) for k, v in bands.items()}
    record["exp_minutes"] = round(exp, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--show", type=int, default=0, help="Print the top N by expected minutes")
    args = parser.parse_args()

    bootstrap = load("bootstrap.json")
    current_gw = next((e["id"] for e in bootstrap["events"] if e.get("is_next")), None)
    if current_gw is None:
        raise SystemExit("no upcoming gameweek in bootstrap.json — season over?")

    entry = load("entry.json")
    owned: set[int] = set()
    picks_path = DATA_DIR / f"picks_gw{entry.get('current_event')}.json"
    if picks_path.exists():
        with open(picks_path) as f:
            owned = {p["element"] for p in json.load(f)["picks"]}

    records = {}
    for player in bootstrap["elements"]:
        path = DATA_DIR / f"element_summary/{player['id']}.json"
        if not path.exists():
            continue
        with open(path) as f:
            history = json.load(f)["history"]
        records[str(player["id"])] = predict(player, history, current_gw, player["id"] in owned)

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "gw": current_gw,
            "decay_halflife_gws": DECAY_HALFLIFE_GWS,
            "min_obs": MIN_OBS,
            "band_floor": BAND_FLOOR,
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

    if args.show:
        ranked = sorted(records.values(), key=lambda r: -r["exp_minutes"])[: args.show]
        print(f"\n{'player':<16}{'mins':>6}{'p(0)':>7}{'p(1-59)':>9}{'p(60+)':>8}  source")
        for r in ranked:
            b = r["bands"]
            print(f"{r['web_name']:<16}{r['exp_minutes']:>6.0f}{b['p_zero']:>7.0%}"
                  f"{b['p_1_59']:>9.0%}{b['p_60_plus']:>8.0%}  {r['source']}")


if __name__ == "__main__":
    main()
