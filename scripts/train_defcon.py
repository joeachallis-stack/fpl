"""Walk-forward training for the defensive-contribution threshold model.

The target is the official eligible-action count crossing the live positional threshold,
not points per 90 and not a raw hit rate multiplied by p(60+). Minutes are exposure:
the probability is calculated inside every predicted role/minutes state and then mixed.

Only 2025/26 contains the required match-level action fields. Every forecast in the
backtest uses only older 2025/26 action rows, while its minutes distribution may use the
already-verified 2024/25 minutes prehistory.
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

import train_minutes

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODEL = ROOT / "models" / "defcon_params.json"
GWS = DATA / "2025-26_merged_gw.csv"
PLAYERS = DATA / "2025-26_players_raw.csv"

POSITIONS = ("DEF", "MID", "FWD")
THRESHOLDS = {"DEF": 10, "MID": 12, "FWD": 12}
HALFLIVES = (3.0, 6.0, 12.0)
PLAYER_PRIOR_MINUTES = (450.0, 900.0, 1800.0)
DISPERSIONS = (0.0, 0.1, 0.25, 0.5, 1.0)
OPPONENT_PRIOR_MINUTES = (900.0, 1800.0, 3600.0)
PROBABILITY_FLOOR = 0.001
CLUB_CHANGE_RETENTION = 0.5
OFFSEASON_GAP_GWS = 4


def eligible_actions(row: dict, position: str) -> int:
    actions = int(row.get("tackles") or 0) + int(
        row.get("clearances_blocks_interceptions") or 0
    )
    if position in {"MID", "FWD"}:
        actions += int(row.get("recoveries") or 0)
    return actions


def load_action_rows() -> list[dict]:
    with PLAYERS.open(newline="") as handle:
        id_to_code = {int(row["id"]): int(row["code"]) for row in csv.DictReader(handle)}
    with GWS.open(newline="") as handle:
        raw = list(csv.DictReader(handle))
    fixture_teams: dict[int, set[str]] = defaultdict(set)
    for row in raw:
        fixture_teams[int(row["fixture"])].add(row["team"])
    rows = []
    for row in raw:
        position = "GKP" if row["position"] == "GK" else row["position"]
        if position not in POSITIONS:
            continue
        fixture = int(row["fixture"])
        opponents = fixture_teams[fixture] - {row["team"]}
        if len(opponents) != 1:
            raise SystemExit(f"fixture {fixture} has ambiguous teams: {fixture_teams[fixture]}")
        parsed = {
            "element": id_to_code[int(row["element"])],
            "name": row["name"],
            "position": position,
            "team": row["team"],
            "opponent": next(iter(opponents)),
            "minutes": int(row["minutes"]),
            "starts": int(row["starts"]),
            "value": int(row["value"]),
            "gw": int(row["GW"]),
            "home": row["was_home"].lower() == "true",
            "fixture": fixture,
            "prior_season": False,
        }
        parsed["actions"] = eligible_actions(row, position)
        parsed["hit"] = parsed["actions"] >= THRESHOLDS[position]
        rows.append(parsed)
    return rows


def probability_tail(mean: float, dispersion: float, threshold: int) -> float:
    if mean <= 0:
        return 0.0
    if dispersion <= 0:
        term = math.exp(-mean)
        cumulative = term
        for count in range(1, threshold):
            term *= mean / count
            cumulative += term
        return min(max(1 - cumulative, 0.0), 1.0)
    size = 1.0 / dispersion
    probability = size / (size + mean)
    term = probability**size
    cumulative = term
    for count in range(1, threshold):
        term *= (count - 1 + size) / count * (1 - probability)
        cumulative += term
    return min(max(1 - cumulative, 0.0), 1.0)


def weighted_position_rates(rows: list[dict], gw: int, halflife: float) -> dict[str, float]:
    totals = {position: [0.0, 0.0] for position in POSITIONS}
    for row in rows:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** ((gw - row["gw"]) / halflife)
        totals[row["position"]][0] += weight * row["actions"]
        totals[row["position"]][1] += weight * row["minutes"]
    return {
        position: actions * 90 / minutes if minutes else 0.0
        for position, (actions, minutes) in totals.items()
    }


def player_rate(
    history: list[dict], target: dict, position_rate: float, gw: int,
    halflife: float, prior_minutes: float,
) -> tuple[float, dict]:
    actions = minutes = 0.0
    for row in history:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** ((gw - row["gw"]) / halflife)
        if row["team"] != target["team"]:
            weight *= CLUB_CHANGE_RETENTION
        actions += weight * row["actions"]
        minutes += weight * row["minutes"]
    rate = (actions * 90 + position_rate * prior_minutes) / (minutes + prior_minutes)
    return rate, {
        "observed_actions": actions,
        "observed_minutes": minutes,
        "position_rate_per_90": position_rate,
        "prior_minutes": prior_minutes,
    }


def fixture_factors(
    rows: list[dict], gw: int, halflife: float, opponent_prior_minutes: float,
) -> tuple[dict[tuple[str, str], float], dict[tuple[str, bool], float]]:
    """Position-specific opponent and venue action-rate ratios from older rows."""
    position = weighted_position_rates(rows, gw, halflife)
    opponents: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0.0])
    venues: dict[tuple[str, bool], list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        if row["minutes"] <= 0:
            continue
        weight = 0.5 ** ((gw - row["gw"]) / halflife)
        for key, table in (
            ((row["position"], row["opponent"]), opponents),
            ((row["position"], row["home"]), venues),
        ):
            table[key][0] += weight * row["actions"]
            table[key][1] += weight * row["minutes"]
    opponent_result = {}
    for key, (actions, minutes) in opponents.items():
        base = position[key[0]]
        shrunk = (actions * 90 + base * opponent_prior_minutes) / (
            minutes + opponent_prior_minutes
        )
        opponent_result[key] = min(max(shrunk / base if base else 1.0, 0.6), 1.4)
    venue_result = {}
    for key, (actions, minutes) in venues.items():
        base = position[key[0]]
        # Venue is a population effect, but shrink it by the same exposure so the first
        # few gameweeks cannot create a large multiplier.
        shrunk = (actions * 90 + base * opponent_prior_minutes) / (
            minutes + opponent_prior_minutes
        )
        venue_result[key] = min(max(shrunk / base if base else 1.0, 0.8), 1.2)
    return opponent_result, venue_result


def predict_probability(
    target: dict,
    history: list[dict],
    minutes_forecast: dict,
    prior_rows: list[dict],
    *,
    halflife: float,
    player_prior_minutes: float,
    dispersion: float,
    fixture_mode: str,
    opponent_prior_minutes: float,
    position_rates: dict[str, float] | None = None,
    fixture_tables: tuple[dict, dict] | None = None,
) -> tuple[float, dict]:
    position_rates = position_rates or weighted_position_rates(
        prior_rows, target["gw"], halflife
    )
    rate, audit = player_rate(
        history, target, position_rates[target["position"]], target["gw"],
        halflife, player_prior_minutes,
    )
    opponent, venue = fixture_tables or fixture_factors(
        prior_rows, target["gw"], halflife, opponent_prior_minutes
    )
    opponent_factor = (
        opponent.get((target["position"], target["opponent"]), 1.0)
        if fixture_mode in {"opponent", "opponent_venue"} else 1.0
    )
    venue_factor = (
        venue.get((target["position"], target["home"]), 1.0)
        if fixture_mode == "opponent_venue" else 1.0
    )
    factor = opponent_factor * venue_factor
    threshold = THRESHOLDS[target["position"]]
    states = minutes_forecast["role_states"]
    conditional = minutes_forecast["conditional_minutes_by_state"]
    state_probabilities = {}
    probability = 0.0
    for state, state_weight in states.items():
        state_minutes = conditional[state]
        mean = rate * state_minutes / 90 * factor
        hit = 0.0 if state == "unused" else probability_tail(mean, dispersion, threshold)
        state_probabilities[state] = hit
        probability += state_weight * hit
    probability = min(max(probability, PROBABILITY_FLOOR), 1 - PROBABILITY_FLOOR)
    audit.update({
        "player_rate_per_90": rate,
        "opponent_factor": opponent_factor,
        "venue_factor": venue_factor,
        "fixture_factor": factor,
        "state_hit_probabilities": state_probabilities,
    })
    return probability, audit


def precompute_minutes(rows: list[dict]) -> dict[tuple[int, int], dict]:
    minute_rows, prior_minutes, _ = train_minutes.load_rows()
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in minute_rows:
        by_gw[row["gw"]].append(row)
    action_keys = {(row["element"], row["gw"]) for row in rows}
    histories: dict[int, list[dict]] = defaultdict(list)
    for row in prior_minutes:
        histories[row["element"]].append(row)
    pool = list(prior_minutes)
    artifact = json.loads(train_minutes.MODEL.read_text())
    params = artifact["selected"]
    result = {}
    for gw in range(1, 39):
        peers = train_minutes.peer_tables(pool, gw, params["decay_halflife_gws"])
        for target in by_gw[gw]:
            key = (target["element"], gw)
            if key not in action_keys:
                continue
            result[key] = train_minutes.predict(
                histories[target["element"]], target, peers,
                params["decay_halflife_gws"], params["peer_prior_weight"],
                params["state_driven_outputs"],
            )
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
            pool.append(row)
    return result


def calibration_bins(rows: list[tuple[float, bool]]) -> dict:
    bins: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0, 0])
    for probability, actual in rows:
        bucket = min(int(probability * 10), 9)
        bins[bucket][0] += probability
        bins[bucket][1] += actual
        bins[bucket][2] += 1
    output = [
        {
            "range": f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}",
            "n": values[2],
            "mean_predicted": values[0] / values[2],
            "actual_rate": values[1] / values[2],
        }
        for bucket, values in sorted(bins.items())
    ]
    count = sum(row["n"] for row in output) or 1
    return {
        "expected_calibration_error": sum(
            abs(row["mean_predicted"] - row["actual_rate"]) * row["n"] for row in output
        ) / count,
        "bins": output,
    }


def summarize(scored: list[dict]) -> dict:
    def one(rows: list[dict]) -> dict:
        n = len(rows)
        if not n:
            return {"n": 0, "log_loss": None, "brier": None, "calibration": None}
        pairs = [(row["probability"], row["actual"]) for row in rows]
        return {
            "n": n,
            "log_loss": sum(
                -(actual * math.log(probability) + (1 - actual) * math.log(1 - probability))
                for probability, actual in pairs
            ) / n,
            "brier": sum((probability - actual) ** 2 for probability, actual in pairs) / n,
            "actual_rate": sum(actual for _, actual in pairs) / n,
            "mean_probability": sum(probability for probability, _ in pairs) / n,
            "calibration": calibration_bins(pairs),
        }

    result = {
        "all": one(scored),
        "contenders": one([row for row in scored if row["contender"]]),
        "by_position_contenders": {
            position: one([
                row for row in scored if row["contender"] and row["position"] == position
            ]) for position in POSITIONS
        },
    }
    return result


def evaluate(
    rows: list[dict], minute_forecasts: dict, *, halflife: float,
    player_prior_minutes: float, dispersion: float, fixture_mode: str,
    opponent_prior_minutes: float, collapse_minutes: bool = False,
) -> dict:
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    histories: dict[int, list[dict]] = defaultdict(list)
    pool: list[dict] = []
    scored = []
    for gw in range(1, 39):
        # GW1 has no defensible action prior: 2024/25 lacks these fields.
        if pool:
            position_rates = weighted_position_rates(pool, gw, halflife)
            fixture_tables = fixture_factors(
                pool, gw, halflife, opponent_prior_minutes
            )
            for target in by_gw[gw]:
                recent = histories[target["element"]][-3:]
                contender = bool(recent) and sum(row["minutes"] for row in recent) / len(recent) >= 30
                minutes_forecast = minute_forecasts[(target["element"], gw)]
                if collapse_minutes:
                    minutes_forecast = {
                        "role_states": {"expected_minutes": 1.0},
                        "conditional_minutes_by_state": {
                            "expected_minutes": minutes_forecast["exp_minutes"]
                        },
                    }
                probability, _ = predict_probability(
                    target, histories[target["element"]],
                    minutes_forecast, pool,
                    halflife=halflife,
                    player_prior_minutes=player_prior_minutes,
                    dispersion=dispersion,
                    fixture_mode=fixture_mode,
                    opponent_prior_minutes=opponent_prior_minutes,
                    position_rates=position_rates,
                    fixture_tables=fixture_tables,
                )
                scored.append({
                    "probability": probability,
                    "actual": target["hit"],
                    "contender": contender,
                    "position": target["position"],
                })
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
            pool.append(row)
    return summarize(scored)


def baseline_metrics(rows: list[dict], minute_forecasts: dict, multiply_p60: bool) -> dict:
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    histories: dict[int, list[dict]] = defaultdict(list)
    pool: list[dict] = []
    scored = []
    for gw in range(1, 39):
        if pool:
            position_hits = defaultdict(float)
            position_plays = defaultdict(float)
            for row in pool:
                if row["minutes"] > 0:
                    position_hits[row["position"]] += row["hit"]
                    position_plays[row["position"]] += 1
            for target in by_gw[gw]:
                history = [row for row in histories[target["element"]] if row["minutes"] > 0]
                position = target["position"]
                prior = position_hits[position] / (position_plays[position] or 1)
                probability = (sum(row["hit"] for row in history) + 5 * prior) / (len(history) + 5)
                if multiply_p60:
                    probability *= minute_forecasts[(target["element"], gw)]["bands"]["p_60_plus"]
                probability = min(max(probability, PROBABILITY_FLOOR), 1 - PROBABILITY_FLOOR)
                recent = histories[target["element"]][-3:]
                contender = bool(recent) and sum(row["minutes"] for row in recent) / len(recent) >= 30
                scored.append({
                    "probability": probability,
                    "actual": target["hit"],
                    "contender": contender,
                    "position": position,
                })
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
            pool.append(row)
    return summarize(scored)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    required = (GWS, PLAYERS, train_minutes.PRIOR_GWS, train_minutes.PRIOR_PLAYERS, train_minutes.MODEL)
    if not all(path.exists() for path in required):
        raise SystemExit("historical caches/model missing; run train_minutes.py --fetch first")
    rows = load_action_rows()
    minute_forecasts = precompute_minutes(rows)
    baselines = {
        "current_hit_rate_times_p60": baseline_metrics(rows, minute_forecasts, True),
        "corrected_hit_rate": baseline_metrics(rows, minute_forecasts, False),
    }
    base_grid = []
    print("base role-state count model:")
    for halflife, prior_minutes, dispersion in itertools.product(
        HALFLIVES, PLAYER_PRIOR_MINUTES, DISPERSIONS
    ):
        metrics = evaluate(
            rows, minute_forecasts, halflife=halflife,
            player_prior_minutes=prior_minutes, dispersion=dispersion,
            fixture_mode="none", opponent_prior_minutes=1800.0,
        )
        score = metrics["contenders"]["log_loss"]
        base_grid.append((score, halflife, prior_minutes, dispersion, metrics))
        print(f"  half-life {halflife:>2g} prior {prior_minutes:>4g} alpha {dispersion:>4g}  {score:.5f}")
    base_best = min(base_grid, key=lambda row: row[0])
    _, halflife, prior_minutes, dispersion, _ = base_best

    fixture_grid = []
    print("fixture ablations:")
    for mode, opponent_minutes in itertools.product(
        ("none", "opponent", "opponent_venue"), OPPONENT_PRIOR_MINUTES
    ):
        metrics = evaluate(
            rows, minute_forecasts, halflife=halflife,
            player_prior_minutes=prior_minutes, dispersion=dispersion,
            fixture_mode=mode, opponent_prior_minutes=opponent_minutes,
        )
        score = metrics["contenders"]["log_loss"]
        fixture_grid.append((score, mode, opponent_minutes, metrics))
        print(f"  {mode:<16} opponent prior {opponent_minutes:>4g}  {score:.5f}")
    selected = min(fixture_grid, key=lambda row: row[0])
    _, fixture_mode, opponent_minutes, selected_metrics = selected
    collapsed_metrics = evaluate(
        rows, minute_forecasts, halflife=halflife,
        player_prior_minutes=prior_minutes, dispersion=dispersion,
        fixture_mode=fixture_mode, opponent_prior_minutes=opponent_minutes,
        collapse_minutes=True,
    )
    payload = {
        "model_version": "defcon-threshold-v1",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_season": "2025/26",
        "training_rows": len(rows),
        "training_source": {
            "gameweeks": train_minutes.GWS_URL,
            "players": train_minutes.PLAYERS_URL,
        },
        "gameweeks_sha256": hashlib.sha256(GWS.read_bytes()).hexdigest(),
        "players_sha256": hashlib.sha256(PLAYERS.read_bytes()).hexdigest(),
        "minutes_model_sha256": hashlib.sha256(train_minutes.MODEL.read_bytes()).hexdigest(),
        "selected": {
            "decay_halflife_gws": halflife,
            "player_prior_minutes": prior_minutes,
            "dispersion": dispersion,
            "fixture_mode": fixture_mode,
            "opponent_prior_minutes": opponent_minutes,
            "probability_floor": PROBABILITY_FLOOR,
            "club_change_retention": CLUB_CHANGE_RETENTION,
            "offseason_gap_gws": OFFSEASON_GAP_GWS,
            "thresholds": THRESHOLDS,
        },
        "selection_policy": (
            "walk-forward 2025/26 contender log loss; contender averages >=30 minutes "
            "over the prior three matches; all action features use only older rows"
        ),
        "target": (
            "P(tackles+CBI >=10) for DEF; P(tackles+CBI+recoveries >=12) for MID/FWD; "
            "no 60-minute requirement"
        ),
        "baselines": baselines,
        "metrics": selected_metrics,
        "minutes_ablation": {
            "role_state_mixture": selected_metrics,
            "single_expected_minutes": collapsed_metrics,
        },
        "base_grid": [
            {
                "decay_halflife_gws": h,
                "player_prior_minutes": p,
                "dispersion": d,
                "contender_log_loss": metrics["contenders"]["log_loss"],
                "contender_brier": metrics["contenders"]["brier"],
            }
            for _, h, p, d, metrics in base_grid
        ],
        "fixture_ablations": [
            {
                "fixture_mode": mode,
                "opponent_prior_minutes": prior,
                "metrics": metrics,
            }
            for _, mode, prior, metrics in fixture_grid
        ],
        "known_limits": [
            "only one completed season contains the required action fields",
            "season-to-season transport cannot yet be scored",
            "historical bookmaker probabilities are unavailable and were not approximated from results",
            "minutes probabilities inherit uncertainty from the separate minutes model",
        ],
    }
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_text(json.dumps(payload, indent=2) + "\n")
    print(
        f"selected half-life {halflife:g}, prior {prior_minutes:g}, alpha {dispersion:g}, "
        f"fixture {fixture_mode}/{opponent_minutes:g}"
    )
    print(f"wrote {MODEL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
