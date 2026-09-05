"""Runtime goalkeeper save-point expectation from count and minutes distributions."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path

import minutes
import train_saves

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "models" / "save_params.json"
LEDGER = ROOT / "observations" / "player_fixtures.jsonl"


def load_context(bootstrap: dict, season: str) -> dict | None:
    required = (
        MODEL, train_saves.GWS, train_saves.PLAYERS,
    )
    if not all(path.exists() for path in required):
        return None
    model_bytes = MODEL.read_bytes()
    model = json.loads(model_bytes)
    model["_artifact_sha256"] = hashlib.sha256(model_bytes).hexdigest()
    gap = model["selected"]["offseason_gap_gws"]
    history = []
    # Runtime uses one complete prior season, matching the tested 2025/26 fold design
    # (which used 2024/25 as its one prehistory season).
    for source_season, rows, offset in ((
        "2025/26",
        train_saves.load_keeper_rows(train_saves.GWS, train_saves.PLAYERS, False),
        38 + gap,
    ),):
        for row in rows:
            converted = dict(row)
            converted["gw"] = row["gw"] - offset
            converted["source_season"] = source_season
            history.append(converted)

    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    current_rows = []
    if LEDGER.exists():
        latest = {}
        for line in LEDGER.read_text().splitlines():
            row = json.loads(line)
            if row["season"] == season and row["position"] == "GKP":
                latest[(row["season"], row["fixture_id"], row["element"])] = row
        for row in latest.values():
            saves = int(row.get("saves") or 0)
            current_rows.append({
                "element": row["element_code"],
                "name": row["web_name"],
                "team": team_names[row["team"]],
                "opponent": team_names[row["opponent_team"]],
                "minutes": row["minutes"],
                "starts": row["starts"],
                "gw": row["gw"],
                "home": row["was_home"],
                "fixture": row["fixture_id"],
                "saves": saves,
                "save_points": saves // 3,
                "prior_season": False,
                "source_season": season,
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


def predict(
    player: dict, position: str, team: str, opponent: str, home: bool,
    target_gw: int, minutes_record: dict, context: dict | None,
) -> dict:
    if position != "GKP":
        return {"expected_points": 0.0, "source": "ineligible_outfielder"}
    if context is None:
        return {"expected_points": None, "source": "model_unavailable"}
    states, conditional, minutes_source = minutes.projection_scenarios(minutes_record)
    if states == {"unused": 1.0}:
        return {
            "expected_points": 0.0,
            "source": "minutes_override_zero",
            "minutes_scenario_source": minutes_source,
        }
    params = context["model"]["selected"]
    if target_gw not in context["summaries"]:
        pool = [row for row in context["history"] if row["gw"] < target_gw]
        context["summaries"][target_gw] = (
            pool,
            train_saves.weighted_rate(pool, target_gw, params["decay_halflife_gws"]),
            train_saves.context_factors(
                pool, target_gw, params["decay_halflife_gws"],
                params["context_prior_minutes"],
            ),
        )
    pool, peer_rate, factor_tables = context["summaries"][target_gw]
    history = [
        row for row in context["by_code"].get(player["code"], []) if row["gw"] < target_gw
    ]
    expected_points, audit = train_saves.predict(
        {"element": player["code"], "team": team, "opponent": opponent,
         "home": home, "gw": target_gw},
        history,
        {"role_states": states, "conditional_minutes_by_state": conditional},
        pool,
        halflife=params["decay_halflife_gws"],
        player_prior_minutes=params["player_prior_minutes"],
        dispersion=params["dispersion"],
        context_mode=params["context_mode"],
        context_prior_minutes=params["context_prior_minutes"],
        peer_rate=peer_rate,
        factor_tables=factor_tables,
    )
    by_season = {}
    for source_season in sorted({row["source_season"] for row in history}):
        rows = [row for row in history if row["source_season"] == source_season]
        by_season[source_season] = {
            "matches": len(rows),
            "raw_saves": sum(row["saves"] for row in rows),
            "raw_minutes": sum(row["minutes"] for row in rows),
        }
    audit.update({"as_of_gw": target_gw, "raw_history_by_season": by_season})
    return {
        "expected_points": expected_points,
        "expected_saves": audit["expected_saves"],
        "threshold_probabilities": audit["threshold_probabilities"],
        "source": context["model"]["model_version"],
        "minutes_scenario_source": minutes_source,
        "audit": audit,
    }
