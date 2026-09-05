"""Runtime defensive-contribution probability from actions and minutes states."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import train_defcon

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "defcon_params.json"
LEDGER = ROOT / "observations" / "player_fixtures.jsonl"


def load_context(bootstrap: dict, season: str) -> dict | None:
    required = (MODEL, train_defcon.GWS, train_defcon.PLAYERS)
    if not all(path.exists() for path in required):
        return None
    model_bytes = MODEL.read_bytes()
    model = json.loads(model_bytes)
    model["_artifact_sha256"] = hashlib.sha256(model_bytes).hexdigest()
    params = model["selected"]

    # Put prior-season rows on one continuous gameweek axis. At current GW4, prior GW38
    # is age 8: current GW + the fitted four-GW offseason gap.
    history = []
    for row in train_defcon.load_action_rows():
        converted = dict(row)
        converted["gw"] = row["gw"] - 38 - params["offseason_gap_gws"]
        converted["prior_season"] = True
        history.append(converted)

    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    current_rows = []
    if LEDGER.exists():
        latest = {}
        for line in LEDGER.read_text().splitlines():
            row = json.loads(line)
            if row["season"] == season:
                latest[(row["season"], row["fixture_id"], row["element"])] = row
        for row in latest.values():
            if row["position"] not in train_defcon.POSITIONS:
                continue
            current_rows.append({
                "element": row["element_code"],
                "name": row["web_name"],
                "position": row["position"],
                "team": team_names[row["team"]],
                "opponent": team_names[row["opponent_team"]],
                "minutes": row["minutes"],
                "starts": row["starts"],
                "gw": row["gw"],
                "home": row["was_home"],
                "fixture": row["fixture_id"],
                "actions": row["defcon_actions"],
                "hit": row["defcon_hit"],
                "prior_season": False,
            })
    history.extend(current_rows)
    by_code = defaultdict(list)
    for row in history:
        by_code[row["element"]].append(row)
    for rows in by_code.values():
        rows.sort(key=lambda row: row["gw"])
    return {
        "model": model,
        "history": history,
        "by_code": by_code,
        "current_rows": len(current_rows),
        "summaries": {},
    }


def minutes_scenarios(minutes_record: dict) -> tuple[dict, dict, str]:
    """Return an override-consistent state distribution for DefCon exposure."""
    source = minutes_record["source"]
    if source in {"override_out", "insufficient_evidence"}:
        return ({"unused": 1.0}, {"unused": 0.0}, source)
    if source == "override_doubtful":
        chance = (minutes_record.get("chance_of_playing_next_round") or 0) / 100
        return (
            {"unused": 1 - chance, "cameo_30_59": chance},
            {"unused": 0.0, "cameo_30_59": 30.0},
            "doubtful: chance of playing x 30-minute cameo",
        )
    states = minutes_record.get("role_states")
    conditional = minutes_record.get("conditional_minutes_by_state")
    if states and conditional:
        return states, conditional, "minutes role-state distribution"

    # This path is only for the legacy minutes fallback. It preserves its expected
    # minutes without pretending to know a richer role shape.
    expected = minutes_record["exp_minutes"]
    probability = min(max(expected / 90, 0.0), 1.0)
    return (
        {"unused": 1 - probability, "starter_90_plus": probability},
        {"unused": 0.0, "starter_90_plus": 90.0},
        "legacy two-state approximation",
    )


def predict(
    player: dict,
    position: str,
    team: str,
    opponent: str,
    home: bool,
    target_gw: int,
    minutes_record: dict,
    context: dict | None,
) -> dict:
    if position == "GKP":
        return {"probability": 0.0, "source": "ineligible_goalkeeper"}
    if context is None:
        return {"probability": None, "source": "model_unavailable"}
    states, conditional, minutes_source = minutes_scenarios(minutes_record)
    if states == {"unused": 1.0}:
        return {
            "probability": 0.0,
            "source": "minutes_override_zero",
            "minutes_scenario_source": minutes_source,
        }
    params = context["model"]["selected"]
    if target_gw not in context["summaries"]:
        pool = [row for row in context["history"] if row["gw"] < target_gw]
        context["summaries"][target_gw] = (
            pool,
            train_defcon.weighted_position_rates(
                pool, target_gw, params["decay_halflife_gws"]
            ),
            train_defcon.fixture_factors(
                pool, target_gw, params["decay_halflife_gws"],
                params["opponent_prior_minutes"],
            ),
        )
    pool, position_rates, fixture_tables = context["summaries"][target_gw]
    target = {
        "element": player["code"],
        "position": position,
        "team": team,
        "opponent": opponent,
        "home": home,
        "gw": target_gw,
    }
    player_history = [
        row for row in context["by_code"].get(player["code"], []) if row["gw"] < target_gw
    ]
    probability, audit = train_defcon.predict_probability(
        target,
        player_history,
        {"role_states": states, "conditional_minutes_by_state": conditional},
        pool,
        halflife=params["decay_halflife_gws"],
        player_prior_minutes=params["player_prior_minutes"],
        dispersion=params["dispersion"],
        fixture_mode=params["fixture_mode"],
        opponent_prior_minutes=params["opponent_prior_minutes"],
        position_rates=position_rates,
        fixture_tables=fixture_tables,
    )
    prior_rows = [row for row in player_history if row["prior_season"]]
    current_rows = [row for row in player_history if not row["prior_season"]]
    audit.update({
        "as_of_gw": target_gw,
        "prior_matches": len(prior_rows),
        "prior_raw_actions": sum(row["actions"] for row in prior_rows),
        "prior_raw_minutes": sum(row["minutes"] for row in prior_rows),
        "current_matches": len(current_rows),
        "current_raw_actions": sum(row["actions"] for row in current_rows),
        "current_raw_minutes": sum(row["minutes"] for row in current_rows),
    })
    return {
        "probability": probability,
        "source": context["model"]["model_version"],
        "threshold": train_defcon.THRESHOLDS[position],
        "eligible_actions": (
            "tackles + clearances/blocks/interceptions"
            + (" + recoveries" if position in {"MID", "FWD"} else "")
        ),
        "minutes_scenario_source": minutes_source,
        "audit": audit,
    }
