"""Walk-forward training for goalkeeper save-point expectation.

FPL awards one point at 3, 6, 9, ... saves. This models the save count inside each
predicted minutes state and uses the tail-sum identity for E[floor(saves / 3)].
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import counts
import train_minutes

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODEL = ROOT / "models" / "save_params.json"
GWS = train_minutes.GWS
PLAYERS = train_minutes.PLAYERS
PRIOR_GWS = train_minutes.PRIOR_GWS
PRIOR_PLAYERS = train_minutes.PRIOR_PLAYERS

HALFLIVES = (3.0, 6.0, 12.0)
PLAYER_PRIOR_MINUTES = (450.0, 900.0, 1800.0)
DISPERSIONS = (0.0, 0.1, 0.25, 0.5, 1.0)
CONTEXT_PRIOR_MINUTES = (450.0, 900.0, 1800.0)
CONTEXT_MODES = ("none", "opponent", "team", "opponent_team", "opponent_team_venue")
CLUB_CHANGE_RETENTION = 0.5
OFFSEASON_GAP_GWS = 4


def load_keeper_rows(gws: Path, players: Path, prior_season: bool) -> list[dict]:
    with players.open(newline="") as handle:
        id_to_code = {int(row["id"]): int(row["code"]) for row in csv.DictReader(handle)}
    with gws.open(newline="") as handle:
        raw = list(csv.DictReader(handle))
    fixture_teams: dict[int, set[str]] = defaultdict(set)
    for row in raw:
        fixture_teams[int(row["fixture"])].add(row["team"])
    result = []
    for row in raw:
        if row["position"] != "GK":
            continue
        fixture = int(row["fixture"])
        opponents = fixture_teams[fixture] - {row["team"]}
        if len(opponents) != 1:
            raise SystemExit(f"fixture {fixture} has ambiguous teams: {fixture_teams[fixture]}")
        saves = int(row.get("saves") or 0)
        result.append({
            "element": id_to_code[int(row["element"])],
            "name": row["name"],
            "team": row["team"],
            "opponent": next(iter(opponents)),
            "minutes": int(row["minutes"]),
            "starts": int(row["starts"]),
            "value": int(row["value"]),
            "gw": int(row["GW"]),
            "home": row["was_home"].lower() == "true",
            "fixture": fixture,
            "saves": saves,
            "save_points": saves // 3,
            "prior_season": prior_season,
        })
    return result


def row_age(target_gw: int, row: dict) -> int:
    if row["prior_season"]:
        return target_gw + OFFSEASON_GAP_GWS + 38 - row["gw"]
    return target_gw - row["gw"]


def weighted_rate(rows: list[dict], gw: int, halflife: float) -> float:
    saves = minutes = 0.0
    for row in rows:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** (row_age(gw, row) / halflife)
        saves += weight * row["saves"]
        minutes += weight * row["minutes"]
    return saves * 90 / minutes if minutes else 0.0


def player_rate(
    history: list[dict], target: dict, peer_rate: float, gw: int,
    halflife: float, prior_minutes: float,
) -> tuple[float, dict]:
    saves = minutes = 0.0
    for row in history:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** (row_age(gw, row) / halflife)
        if row["team"] != target["team"]:
            weight *= CLUB_CHANGE_RETENTION
        saves += weight * row["saves"]
        minutes += weight * row["minutes"]
    rate = (saves * 90 + peer_rate * prior_minutes) / (minutes + prior_minutes)
    return rate, {
        "effective_saves": saves,
        "effective_minutes": minutes,
        "goalkeeper_peer_rate_per_90": peer_rate,
        "player_prior_minutes": prior_minutes,
    }


def context_factors(
    rows: list[dict], gw: int, halflife: float, prior_minutes: float,
) -> tuple[dict[str, float], dict[str, float], dict[bool, float]]:
    base = weighted_rate(rows, gw, halflife)
    opponents: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    teams: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    venues: dict[bool, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** (row_age(gw, row) / halflife)
        for key, table in (
            (row["opponent"], opponents), (row["team"], teams), (row["home"], venues)
        ):
            table[key][0] += weight * row["saves"]
            table[key][1] += weight * row["minutes"]

    def factors(table: dict) -> dict:
        result = {}
        for key, (saves, minutes) in table.items():
            rate = (saves * 90 + base * prior_minutes) / (minutes + prior_minutes)
            result[key] = min(max(rate / base if base else 1.0, 0.6), 1.4)
        return result

    return factors(opponents), factors(teams), factors(venues)


def predict(
    target: dict, history: list[dict], minutes_forecast: dict, pool: list[dict], *,
    halflife: float, player_prior_minutes: float, dispersion: float,
    context_mode: str, context_prior_minutes: float,
    peer_rate: float | None = None, factor_tables: tuple[dict, dict, dict] | None = None,
) -> tuple[float, dict]:
    peer_rate = peer_rate if peer_rate is not None else weighted_rate(pool, target["gw"], halflife)
    rate, audit = player_rate(
        history, target, peer_rate, target["gw"], halflife, player_prior_minutes
    )
    opponents, teams, venues = factor_tables or context_factors(
        pool, target["gw"], halflife, context_prior_minutes
    )
    opponent_factor = opponents.get(target["opponent"], 1.0) if "opponent" in context_mode else 1.0
    team_factor = teams.get(target["team"], 1.0) if "team" in context_mode else 1.0
    venue_factor = venues.get(target["home"], 1.0) if "venue" in context_mode else 1.0
    factor = opponent_factor * team_factor * venue_factor

    expected_points = expected_saves = 0.0
    threshold_probabilities = {threshold: 0.0 for threshold in (3, 6, 9, 12)}
    state_points = {}
    for state, state_weight in minutes_forecast["role_states"].items():
        state_minutes = minutes_forecast["conditional_minutes_by_state"][state]
        mean = rate * state_minutes / 90 * factor
        points, tails = counts.expected_points_at_intervals(mean, dispersion, 3)
        if state == "unused":
            mean = points = 0.0
            tails = {threshold: 0.0 for threshold in tails}
        expected_saves += state_weight * mean
        expected_points += state_weight * points
        state_points[state] = points
        for threshold in threshold_probabilities:
            threshold_probabilities[threshold] += state_weight * tails[threshold]
    audit.update({
        "save_rate_per_90": rate,
        "opponent_factor": opponent_factor,
        "team_factor": team_factor,
        "venue_factor": venue_factor,
        "fixture_factor": factor,
        "expected_saves": expected_saves,
        "threshold_probabilities": threshold_probabilities,
        "expected_points_by_state": state_points,
    })
    return expected_points, audit


def precompute_minutes(target_rows: list[dict]) -> dict[tuple[int, int], dict]:
    rows, prior_rows, _ = train_minutes.load_rows()
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    target_keys = {(row["element"], row["gw"]) for row in target_rows}
    histories: dict[int, list[dict]] = defaultdict(list)
    for row in prior_rows:
        histories[row["element"]].append(row)
    pool = list(prior_rows)
    artifact = json.loads(train_minutes.MODEL.read_text())
    params = artifact["selected"]
    result = {}
    for gw in range(1, 39):
        peers = train_minutes.peer_tables(pool, gw, params["decay_halflife_gws"])
        for target in by_gw[gw]:
            key = (target["element"], gw)
            if key in target_keys:
                result[key] = train_minutes.predict(
                    histories[target["element"]], target, peers,
                    params["decay_halflife_gws"], params["peer_prior_weight"],
                    params["state_driven_outputs"],
                )
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
            pool.append(row)
    return result


def summary(scored: list[dict]) -> dict:
    def one(rows: list[dict]) -> dict:
        if not rows:
            return {"n": 0, "mae": None, "rmse": None, "bias": None}
        errors = [row["prediction"] - row["actual"] for row in rows]
        return {
            "n": len(rows),
            "mae": sum(abs(error) for error in errors) / len(errors),
            "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
            "bias": sum(errors) / len(errors),
            "actual_mean": sum(row["actual"] for row in rows) / len(rows),
            "predicted_mean": sum(row["prediction"] for row in rows) / len(rows),
        }
    return {
        "all": one(scored),
        "contenders": one([row for row in scored if row["contender"]]),
        "early_contenders": one([row for row in scored if row["contender"] and row["gw"] <= 5]),
        "later_contenders": one([row for row in scored if row["contender"] and row["gw"] > 5]),
    }


def evaluate(
    rows: list[dict], prior_rows: list[dict], minute_forecasts: dict, *,
    halflife: float, player_prior_minutes: float, dispersion: float,
    context_mode: str, context_prior_minutes: float, collapse_minutes: bool = False,
) -> dict:
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    histories: dict[int, list[dict]] = defaultdict(list)
    for row in prior_rows:
        histories[row["element"]].append(row)
    pool = list(prior_rows)
    scored = []
    for gw in range(1, 39):
        peer = weighted_rate(pool, gw, halflife)
        tables = context_factors(pool, gw, halflife, context_prior_minutes)
        for target in by_gw[gw]:
            recent = histories[target["element"]][-3:]
            contender = bool(recent) and sum(row["minutes"] for row in recent) / len(recent) >= 30
            minute = minute_forecasts[(target["element"], gw)]
            if collapse_minutes:
                minute = {
                    "role_states": {"expected_minutes": 1.0},
                    "conditional_minutes_by_state": {"expected_minutes": minute["exp_minutes"]},
                }
            prediction, _ = predict(
                target, histories[target["element"]], minute, pool,
                halflife=halflife, player_prior_minutes=player_prior_minutes,
                dispersion=dispersion, context_mode=context_mode,
                context_prior_minutes=context_prior_minutes,
                peer_rate=peer, factor_tables=tables,
            )
            scored.append({
                "prediction": prediction, "actual": target["save_points"],
                "contender": contender, "gw": gw,
            })
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
            pool.append(row)
    return summary(scored)


def baseline(rows: list[dict], prior_rows: list[dict], minute_forecasts: dict) -> dict:
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    previous: dict[int, list[dict]] = defaultdict(list)
    for row in prior_rows:
        previous[row["element"]].append(row)
    current: dict[int, list[dict]] = defaultdict(list)
    pool = []
    scored = []
    for gw in range(1, 39):
        position_rate = (
            sum(row["saves"] for row in pool) * 90 / sum(row["minutes"] for row in pool)
            if sum(row["minutes"] for row in pool) else weighted_rate(prior_rows, gw, 12)
        )
        for target in by_gw[gw]:
            old = [row for row in previous[target["element"]] if row["minutes"] > 0]
            old_saves = sum(row["saves"] for row in old)
            old_minutes = sum(row["minutes"] for row in old)
            prior_rate = (old_saves * 90 + position_rate * 450) / (old_minutes + 450)
            new = [row for row in current[target["element"]] if row["minutes"] > 0]
            new_saves = sum(row["saves"] for row in new)
            new_minutes = sum(row["minutes"] for row in new)
            rate = (new_saves * 90 + prior_rate * 900) / (new_minutes + 900)
            prediction = rate * minute_forecasts[(target["element"], gw)]["exp_minutes"] / 90 / 3
            recent = (previous[target["element"]] + current[target["element"]])[-3:]
            contender = bool(recent) and sum(row["minutes"] for row in recent) / len(recent) >= 30
            scored.append({
                "prediction": prediction, "actual": target["save_points"],
                "contender": contender, "gw": gw,
            })
        for row in by_gw[gw]:
            current[row["element"]].append(row)
            pool.append(row)
    return summary(scored)


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    required = (GWS, PLAYERS, PRIOR_GWS, PRIOR_PLAYERS, train_minutes.MODEL)
    if not all(path.exists() for path in required):
        raise SystemExit("historical caches/model missing; run train_minutes.py --fetch first")
    rows = load_keeper_rows(GWS, PLAYERS, False)
    prior_rows = load_keeper_rows(PRIOR_GWS, PRIOR_PLAYERS, True)
    minute_forecasts = precompute_minutes(rows)
    old = baseline(rows, prior_rows, minute_forecasts)

    grid = []
    print("base save-count model:")
    for halflife, prior_minutes, dispersion in itertools.product(
        HALFLIVES, PLAYER_PRIOR_MINUTES, DISPERSIONS
    ):
        metrics = evaluate(
            rows, prior_rows, minute_forecasts, halflife=halflife,
            player_prior_minutes=prior_minutes, dispersion=dispersion,
            context_mode="none", context_prior_minutes=900,
        )
        score = metrics["contenders"]["rmse"]
        grid.append((score, halflife, prior_minutes, dispersion, metrics))
        print(f"  half-life {halflife:>2g} prior {prior_minutes:>4g} alpha {dispersion:>4g}  {score:.5f}")
    _, halflife, prior_minutes, dispersion, _ = min(grid, key=lambda row: row[0])

    contexts = []
    print("fixture ablations:")
    for mode, context_prior in itertools.product(CONTEXT_MODES, CONTEXT_PRIOR_MINUTES):
        metrics = evaluate(
            rows, prior_rows, minute_forecasts, halflife=halflife,
            player_prior_minutes=prior_minutes, dispersion=dispersion,
            context_mode=mode, context_prior_minutes=context_prior,
        )
        score = metrics["contenders"]["rmse"]
        contexts.append((score, mode, context_prior, metrics))
        print(f"  {mode:<22} prior {context_prior:>4g}  {score:.5f}")
    _, mode, context_prior, selected_metrics = min(contexts, key=lambda row: row[0])
    collapsed = evaluate(
        rows, prior_rows, minute_forecasts, halflife=halflife,
        player_prior_minutes=prior_minutes, dispersion=dispersion,
        context_mode=mode, context_prior_minutes=context_prior, collapse_minutes=True,
    )
    payload = {
        "model_version": "goalkeeper-saves-v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_season": "2025/26",
        "training_rows": len(rows),
        "prior_season": "2024/25",
        "prior_rows": len(prior_rows),
        "source": {
            "training_gameweeks": train_minutes.GWS_URL,
            "training_players": train_minutes.PLAYERS_URL,
            "prior_gameweeks": train_minutes.PRIOR_GWS_URL,
            "prior_players": train_minutes.PRIOR_PLAYERS_URL,
        },
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (GWS, PLAYERS, PRIOR_GWS, PRIOR_PLAYERS)
        },
        "minutes_model_sha256": hashlib.sha256(train_minutes.MODEL.read_bytes()).hexdigest(),
        "selected": {
            "decay_halflife_gws": halflife,
            "player_prior_minutes": prior_minutes,
            "dispersion": dispersion,
            "context_mode": mode,
            "context_prior_minutes": context_prior,
            "club_change_retention": CLUB_CHANGE_RETENTION,
            "offseason_gap_gws": OFFSEASON_GAP_GWS,
        },
        "selection_policy": (
            "minimize save-point RMSE on keepers averaging >=30 minutes over their prior "
            "three matches; predict 2025/26 forward using only older match rows"
        ),
        "target": "E[floor(saves / 3)] from a role-state mixture of save-count distributions",
        "baseline_linear_saves_over_three": old,
        "metrics": selected_metrics,
        "minutes_ablation": {
            "role_state_mixture": selected_metrics,
            "single_expected_minutes": collapsed,
        },
        "base_grid": [
            {"decay_halflife_gws": h, "player_prior_minutes": p, "dispersion": d,
             "metrics": metrics}
            for _, h, p, d, metrics in grid
        ],
        "context_ablations": [
            {"context_mode": candidate_mode, "context_prior_minutes": prior,
             "metrics": metrics}
            for _, candidate_mode, prior, metrics in contexts
        ],
        "known_limits": [
            "historical bookmaker probabilities are unavailable and were not replaced with results",
            "save volume is modeled from keeper/team/opponent history, not shots on target",
            "minutes probabilities inherit uncertainty from the separate minutes model",
            "penalty-save points are a separate rare event and remain unmodeled",
        ],
    }
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"selected half-life {halflife:g}, prior {prior_minutes:g}, alpha {dispersion:g}, "
        f"context {mode}/{context_prior:g}"
    )
    print(f"wrote {MODEL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
