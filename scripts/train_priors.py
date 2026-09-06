"""How much should last season's rate count against this season's, when predicting next?

`projections.py` blends a player's prior-season attacking rate with his current-season
evidence, weighting the prior as a flat 900 minutes for everybody. The GW4 input audit
showed that constant is doing something indefensible: 140 players carry under 900 minutes
of prior evidence and are still weighted as 900, while 123 carry over 2,000 and are also
weighted as only 900. Bruno Fernandes has 3,065 prior minutes at 0.298 xG/90, and 180
current minutes at 1.05 move his blend to 0.424 — a 42% swing off two matches, on the most
captained player in the game.

Unlike most open questions here, this one does not need frozen archives. It only involves
player xG rates, and two complete seasons of those are cached. So it can be answered now,
walk-forward, rather than assumed.

Method. Walk 2025/26 gameweek by gameweek. At each cutoff, a player's prior is his 2024/25
rate shrunk toward his position, and his current evidence is 2025/26 up to but excluding
the cutoff. The target is what he actually did over the next six gameweeks — the same
horizon the projection forecasts. Candidate weighting schemes are scored on how well the
blend predicts that.

Primary metric is minutes-weighted squared error against future xG per 90, because an xG
rate is the quantity the model is actually estimating and it carries far less noise than
realized goals. Poisson error on future goals is reported alongside as corroboration.

Standard errors cluster on the player: one player contributes a row at every cutoff, and
those rows share overlapping future windows, so treating them as independent would
overstate significance exactly as it did in the ratings work.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
OUT_PATH = MODELS_DIR / "prior_weight_params.json"

HORIZON = 6
# Mirrored from projections.py so the incumbent is scored on its own terms.
POSITION_PRIOR_MINUTES = 450.0
INCUMBENT_PRIOR_MINUTES = 900.0
MIN_FUTURE_MINUTES = 90
METRICS = ("expected_goals", "expected_assists")


def load_season(gw_path: Path, raw_path: Path) -> tuple[list[dict], dict[int, int]]:
    with raw_path.open() as handle:
        id_to_code = {int(row["id"]): int(row["code"]) for row in csv.DictReader(handle)}
    rows = []
    with gw_path.open() as handle:
        for row in csv.DictReader(handle):
            element = int(row["element"])
            if element not in id_to_code:
                continue
            rows.append({
                "code": id_to_code[element],
                "position": row["position"],
                "round": int(row["round"]),
                "minutes": int(row["minutes"] or 0),
                "expected_goals": float(row["expected_goals"] or 0),
                "expected_assists": float(row["expected_assists"] or 0),
                "goals_scored": int(row["goals_scored"] or 0),
                "assists": int(row["assists"] or 0),
            })
    return rows, id_to_code


def season_totals(rows: list[dict], metric: str) -> dict[int, dict]:
    totals: dict[int, dict] = defaultdict(lambda: {"value": 0.0, "minutes": 0, "position": None})
    for row in rows:
        entry = totals[row["code"]]
        entry["value"] += row[metric]
        entry["minutes"] += row["minutes"]
        entry["position"] = row["position"]
    return totals


def position_rates(totals: dict[int, dict]) -> dict[str, float]:
    buckets: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for entry in totals.values():
        if entry["minutes"] <= 0:
            continue
        bucket = buckets[entry["position"]]
        bucket[0] += entry["value"]
        bucket[1] += entry["minutes"]
    return {
        position: (value / minutes * 90) if minutes else 0.0
        for position, (value, minutes) in buckets.items()
    }


def shrunk_prior(entry: dict, position_rate: float) -> float:
    """Prior-season rate pulled toward the position average, as projections.py does."""
    minutes = entry["minutes"]
    return ((entry["value"] + POSITION_PRIOR_MINUTES / 90 * position_rate)
            / ((minutes + POSITION_PRIOR_MINUTES) / 90))


def weight_schemes() -> dict[str, callable]:
    """Candidate rules for how many minutes the prior is worth."""
    schemes: dict[str, callable] = {
        "flat_900_incumbent": lambda prior_minutes: INCUMBENT_PRIOR_MINUTES,
    }
    for flat in (450.0, 1350.0, 1800.0, 2700.0):
        schemes[f"flat_{flat:g}"] = (lambda f: (lambda prior_minutes: f))(flat)
    schemes["evidence_uncapped"] = (
        lambda prior_minutes: prior_minutes + POSITION_PRIOR_MINUTES
    )
    for cap in (900.0, 1350.0, 1800.0, 2700.0):
        schemes[f"evidence_capped_{cap:g}"] = (
            lambda c: (lambda prior_minutes: min(prior_minutes + POSITION_PRIOR_MINUTES, c))
        )(cap)
    for alpha in (0.25, 0.5, 0.75):
        schemes[f"evidence_scaled_{alpha:g}"] = (
            lambda a: (lambda prior_minutes: a * (prior_minutes + POSITION_PRIOR_MINUTES))
        )(alpha)
    return schemes


def clustered(pairs: list[tuple]) -> dict:
    """Weighted mean with a player-clustered standard error."""
    if len(pairs) < 2:
        return {"n": 0, "clusters": 0, "value": None, "se": None}
    total_weight = sum(weight for _, weight, _ in pairs)
    mean = sum(value * weight for value, weight, _ in pairs) / total_weight
    residual: dict[object, float] = defaultdict(float)
    for value, weight, cluster in pairs:
        residual[cluster] += weight * (value - mean)
    se = math.sqrt(sum(r * r for r in residual.values())) / total_weight
    return {"n": len(pairs), "clusters": len(residual),
            "value": round(mean, 6), "se": round(se, 6)}


def evaluate(metric: str) -> dict:
    prior_rows, _ = load_season(
        DATA_DIR / "2024-25_merged_gw.csv", DATA_DIR / "2024-25_players_raw.csv")
    current_rows, _ = load_season(
        DATA_DIR / "2025-26_merged_gw.csv", DATA_DIR / "2025-26_players_raw.csv")

    prior_totals = season_totals(prior_rows, metric)
    prior_positions = position_rates(prior_totals)

    by_round: dict[int, list[dict]] = defaultdict(list)
    for row in current_rows:
        by_round[row["round"]].append(row)
    max_round = max(by_round)

    schemes = weight_schemes()
    errors: dict[str, list[tuple]] = {name: [] for name in schemes}
    goal_field = "goals_scored" if metric == "expected_goals" else "assists"
    goal_errors: dict[str, list[tuple]] = {name: [] for name in schemes}
    samples = 0

    for cutoff in range(2, max_round - HORIZON + 2):
        seen: dict[int, dict] = defaultdict(
            lambda: {"value": 0.0, "minutes": 0, "position": None})
        for round_number in range(1, cutoff):
            for row in by_round[round_number]:
                entry = seen[row["code"]]
                entry["value"] += row[metric]
                entry["minutes"] += row["minutes"]
                entry["position"] = row["position"]
        future: dict[int, dict] = defaultdict(
            lambda: {"value": 0.0, "minutes": 0, "goals": 0})
        for round_number in range(cutoff, min(cutoff + HORIZON, max_round + 1)):
            for row in by_round[round_number]:
                entry = future[row["code"]]
                entry["value"] += row[metric]
                entry["minutes"] += row["minutes"]
                entry["goals"] += row[goal_field]

        for code, ahead in future.items():
            if ahead["minutes"] < MIN_FUTURE_MINUTES:
                continue
            prior = prior_totals.get(code)
            current = seen.get(code)
            if not prior or prior["minutes"] <= 0 or not current or current["minutes"] <= 0:
                continue
            position = current["position"] or prior["position"]
            prior_rate = shrunk_prior(prior, prior_positions.get(position, 0.0))
            current_rate = current["value"] / current["minutes"] * 90
            target = ahead["value"] / ahead["minutes"] * 90
            samples += 1
            for name, rule in schemes.items():
                weight = rule(prior["minutes"])
                blended = ((prior_rate * weight + current_rate * current["minutes"])
                           / (weight + current["minutes"]))
                errors[name].append(((blended - target) ** 2, ahead["minutes"], code))
                expected = max(blended * ahead["minutes"] / 90, 1e-6)
                goal_errors[name].append((
                    expected - ahead["goals"] * math.log(expected), 1.0, code))

    results = {}
    for name in schemes:
        squared = clustered(errors[name])
        poisson = clustered(goal_errors[name])
        results[name] = {
            "weighted_mse": squared["value"],
            "mse_se": squared["se"],
            "poisson_nll_on_realized": poisson["value"],
            "n": squared["n"],
            "clusters": squared["clusters"],
        }
    return {"metric": metric, "samples": samples, "schemes": results}


def paired_against_incumbent(metric: str, challenger: str) -> dict:
    """Paired, player-clustered test of one scheme against flat 900.

    Comparing two independently computed mean errors wastes the pairing: both schemes
    score the identical player-cutoff rows, so the per-row difference is far less noisy
    than either level. This is the number that decides the question.
    """
    prior_rows, _ = load_season(
        DATA_DIR / "2024-25_merged_gw.csv", DATA_DIR / "2024-25_players_raw.csv")
    current_rows, _ = load_season(
        DATA_DIR / "2025-26_merged_gw.csv", DATA_DIR / "2025-26_players_raw.csv")
    prior_totals = season_totals(prior_rows, metric)
    prior_positions = position_rates(prior_totals)
    by_round: dict[int, list[dict]] = defaultdict(list)
    for row in current_rows:
        by_round[row["round"]].append(row)
    max_round = max(by_round)
    schemes = weight_schemes()
    incumbent, candidate = schemes["flat_900_incumbent"], schemes[challenger]

    pairs = []
    for cutoff in range(2, max_round - HORIZON + 2):
        seen: dict[int, dict] = defaultdict(
            lambda: {"value": 0.0, "minutes": 0, "position": None})
        for round_number in range(1, cutoff):
            for row in by_round[round_number]:
                entry = seen[row["code"]]
                entry["value"] += row[metric]
                entry["minutes"] += row["minutes"]
                entry["position"] = row["position"]
        future: dict[int, dict] = defaultdict(lambda: {"value": 0.0, "minutes": 0})
        for round_number in range(cutoff, min(cutoff + HORIZON, max_round + 1)):
            for row in by_round[round_number]:
                entry = future[row["code"]]
                entry["value"] += row[metric]
                entry["minutes"] += row["minutes"]
        for code, ahead in future.items():
            if ahead["minutes"] < MIN_FUTURE_MINUTES:
                continue
            prior, current = prior_totals.get(code), seen.get(code)
            if not prior or prior["minutes"] <= 0 or not current or current["minutes"] <= 0:
                continue
            position = current["position"] or prior["position"]
            prior_rate = shrunk_prior(prior, prior_positions.get(position, 0.0))
            current_rate = current["value"] / current["minutes"] * 90
            target = ahead["value"] / ahead["minutes"] * 90

            def blended(weight: float) -> float:
                return ((prior_rate * weight + current_rate * current["minutes"])
                        / (weight + current["minutes"]))

            delta = ((blended(candidate(prior["minutes"])) - target) ** 2
                     - (blended(incumbent(prior["minutes"])) - target) ** 2)
            pairs.append((delta, ahead["minutes"], code))

    result = clustered(pairs)
    result["challenger"] = challenger
    result["t"] = round(result["value"] / result["se"], 2) if result["se"] else None
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metric", choices=METRICS + ("both",), default="both")
    args = parser.parse_args()

    metrics = METRICS if args.metric == "both" else (args.metric,)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": "how many minutes should the prior season's rate be worth",
        "incumbent": "flat 900 minutes for every player",
        "horizon_gameweeks": HORIZON,
        "primary_metric": "minutes-weighted squared error against future xG/xA per 90",
        "results": {},
    }
    for metric in metrics:
        result = evaluate(metric)
        best = min(
            (name for name in result["schemes"] if name != "flat_900_incumbent"),
            key=lambda name: result["schemes"][name]["weighted_mse"],
        )
        result["paired_vs_incumbent"] = paired_against_incumbent(metric, best)
        payload["results"][metric] = result
        ranked = sorted(result["schemes"].items(), key=lambda kv: kv[1]["weighted_mse"])
        incumbent = result["schemes"]["flat_900_incumbent"]
        print(f"\n{metric} — {result['samples']} player-cutoff samples, "
              f"{incumbent['clusters']} players")
        print(f"{'scheme':26s} {'wMSE':>10s} {'vs incumbent':>13s} {'PoisNLL':>9s}")
        for name, row in ranked:
            delta = (row["weighted_mse"] - incumbent["weighted_mse"])
            mark = "  <- incumbent" if name == "flat_900_incumbent" else ""
            print(f"{name:26s} {row['weighted_mse']:10.5f} {delta:+13.5f} "
                  f"{row['poisson_nll_on_realized']:9.5f}{mark}")
        paired = result["paired_vs_incumbent"]
        print(f"  paired vs incumbent ({paired['challenger']}): "
              f"mean {paired['value']:+.6f}, clustered t {paired['t']:+.2f} "
              f"over {paired['clusters']} players")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
