"""Evaluate frozen xP forecasts by lead, population, model version and component."""
from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OBSERVATIONS = ROOT / "observations" / "player_fixtures.jsonl"
FORECASTS = ROOT / "projections"
OUT = DATA / "evaluation.json"

FORECAST_COMPONENTS = (
    "appearance", "goals", "assists", "clean_sheet", "goals_conceded",
    "yellow", "red", "defcon", "bonus", "saves",
)
UNMODELED_COMPONENTS = ("own_goals", "penalties_saved", "penalties_missed")


def latest_observations() -> dict[tuple[str, int, int], list[dict]]:
    """Latest player-fixture revisions, grouped to player-gameweek for doubles."""
    latest = {}
    if not OBSERVATIONS.exists():
        return {}
    for line in OBSERVATIONS.read_text().splitlines():
        row = json.loads(line)
        latest[(row["season"], row["fixture_id"], row["element"])] = row
    grouped: dict[tuple[str, int, int], list[dict]] = defaultdict(list)
    for row in latest.values():
        grouped[(row["season"], row["gw"], row["element"])].append(row)
    return dict(grouped)


def observation_components(row: dict, scoring: dict) -> dict[str, float]:
    """Reconstruct one official player-fixture score from recorded stat fields."""
    position = row["position"]
    played = int(row.get("minutes") or 0)
    components = {
        "appearance": 0 if played == 0 else (2 if played >= 60 else 1),
        "goals": (row.get("goals_scored") or 0) * scoring["goals_scored"][position],
        "assists": (row.get("assists") or 0) * scoring["assists"],
        "clean_sheet": (row.get("clean_sheets") or 0) * scoring["clean_sheets"][position],
        "goals_conceded": (
            ((row.get("goals_conceded") or 0) // 2)
            * scoring["goals_conceded"][position]
        ),
        "yellow": (row.get("yellow_cards") or 0) * scoring["yellow_cards"],
        "red": (row.get("red_cards") or 0) * scoring["red_cards"],
        "defcon": (
            int(bool(row.get("defcon_hit")))
            * scoring["defensive_contribution"][position]
        ),
        "bonus": (row.get("bonus") or 0) * scoring["bonus"],
        "saves": ((row.get("saves") or 0) // 3) * scoring["saves"],
        "own_goals": (row.get("own_goals") or 0) * scoring["own_goals"],
        "penalties_saved": (
            (row.get("penalties_saved") or 0) * scoring["penalties_saved"]
        ),
        "penalties_missed": (
            (row.get("penalties_missed") or 0) * scoring["penalties_missed"]
        ),
    }
    components["unexplained"] = (row.get("total_points") or 0) - sum(components.values())
    return components


def aggregate_actual(rows: list[dict], scoring: dict) -> dict:
    components = {key: 0.0 for key in FORECAST_COMPONENTS + UNMODELED_COMPONENTS}
    components["unexplained"] = 0.0
    official_total = 0.0
    for row in rows:
        fixture = observation_components(row, scoring)
        for key, value in fixture.items():
            components[key] += value
        official_total += row.get("total_points") or 0
    modeled_total = sum(components[key] for key in FORECAST_COMPONENTS)
    residual = sum(components[key] for key in UNMODELED_COMPONENTS) + components["unexplained"]
    return {
        "components": components,
        "modeled_total": modeled_total,
        "residual": residual,
        "official_total": official_total,
        "reconstructed_total": modeled_total + residual,
        "fixtures": len(rows),
    }


def scoring_for(payload: dict) -> tuple[dict, str]:
    frozen = payload["meta"].get("scoring_rules")
    if frozen:
        return frozen, "frozen_in_projection_archive"
    bootstrap_path = DATA / "bootstrap.json"
    config_path = ROOT / "config.json"
    if bootstrap_path.exists() and config_path.exists():
        config = json.loads(config_path.read_text())
        if config.get("season") == payload["meta"].get("season"):
            bootstrap = json.loads(bootstrap_path.read_text())
            return bootstrap["game_config"]["scoring"], "live_same_season_fallback"
    raise ValueError("archive lacks frozen scoring rules and no same-season fallback exists")


def forecast_components(forecast: dict, meta: dict) -> dict | None:
    if forecast.get("components") is not None:
        return forecast["components"]
    values = forecast.get("component_values")
    order = meta.get("component_order")
    if values is not None and order and len(values) == len(order):
        return dict(zip(order, values))
    return None


def metric(rows: list[dict], predicted, actual, weighted: bool) -> dict | None:
    if not rows:
        return None
    weights = [row["calibration_weight"] if weighted else 1.0 for row in rows]
    total_weight = sum(weights)
    if total_weight <= 0:
        return None
    predictions = [float(predicted(row)) for row in rows]
    actuals = [float(actual(row)) for row in rows]
    errors = [forecast - observed for forecast, observed in zip(predictions, actuals)]
    return {
        "n": len(rows),
        "weight": total_weight,
        "mae": sum(weight * abs(error) for weight, error in zip(weights, errors)) / total_weight,
        "rmse": math.sqrt(
            sum(weight * error * error for weight, error in zip(weights, errors)) / total_weight
        ),
        "bias": sum(weight * error for weight, error in zip(weights, errors)) / total_weight,
        "predicted_mean": sum(
            weight * value for weight, value in zip(weights, predictions)
        ) / total_weight,
        "actual_mean": sum(weight * value for weight, value in zip(weights, actuals)) / total_weight,
    }


def population_metrics(rows: list[dict], contender: bool) -> dict:
    selected = [row for row in rows if not contender or row["calibration_weight"] > 0]
    weighted = contender
    component_rows = [row for row in selected if row["forecast_components"] is not None]
    result = {
        "total": metric(
            selected, lambda row: row["forecast_total"],
            lambda row: row["actual"]["official_total"], weighted,
        ),
        "modeled_total": metric(
            component_rows,
            lambda row: sum(
                row["forecast_components"].get(key, 0) for key in FORECAST_COMPONENTS
            ),
            lambda row: row["actual"]["modeled_total"], weighted,
        ),
        "components": {
            component: metric(
                component_rows,
                lambda row, key=component: row["forecast_components"].get(key, 0),
                lambda row, key=component: row["actual"]["components"][key],
                weighted,
            )
            for component in FORECAST_COMPONENTS
        },
        "residual": metric(
            component_rows, lambda row: 0.0,
            lambda row: row["actual"]["residual"], weighted,
        ),
        "component_coverage": {
            "forecasts": len(component_rows),
            "total_forecasts": len(selected),
        },
        "residual_components": {},
    }
    for component in UNMODELED_COMPONENTS + ("unexplained",):
        values = [
            (
                row["actual"]["components"][component],
                row["calibration_weight"] if weighted else 1.0,
            )
            for row in component_rows
        ]
        weight = sum(item[1] for item in values)
        result["residual_components"][component] = {
            "n": len(values),
            "nonzero": sum(value != 0 for value, _ in values),
            "actual_mean": (
                sum(value * row_weight for value, row_weight in values) / weight
                if weight else None
            ),
            "actual_total": sum(value for value, _ in values),
        }
    return result


def grouped_metrics(rows: list[dict]) -> dict:
    return {
        "all": population_metrics(rows, contender=False),
        "contenders": population_metrics(rows, contender=True),
    }


def build_evaluation(window: int) -> dict:
    observations = latest_observations()
    archives = sorted(FORECASTS.glob("gw*.json"))[-window:]
    samples = []
    archive_audit = []
    for path in archives:
        payload = json.loads(path.read_text())
        scoring, scoring_source = scoring_for(payload)
        base_gw = payload["meta"]["gw"]
        season = payload["meta"]["season"]
        resolved = component_ready = 0
        for player in payload["players"].values():
            for forecast in player["gameweeks"]:
                observed = observations.get((season, forecast["gw"], player["element"]))
                if observed is None:
                    continue
                actual = aggregate_actual(observed, scoring)
                if actual["official_total"] != actual["reconstructed_total"]:
                    raise ValueError(
                        f"actual component reconstruction failed for {season} "
                        f"GW{forecast['gw']} element {player['element']}"
                    )
                components = forecast_components(forecast, payload["meta"])
                samples.append({
                    "archive": path.name,
                    "model_version": payload["meta"].get("model_version", "unknown"),
                    "base_gw": base_gw,
                    "forecast_gw": forecast["gw"],
                    "lead": forecast["gw"] - base_gw + 1,
                    "element": player["element"],
                    "web_name": player["web_name"],
                    "calibration_weight": float(player.get("calibration_weight", 0)),
                    "forecast_total": forecast["xP"],
                    "forecast_components": components,
                    "actual": actual,
                })
                resolved += 1
                component_ready += components is not None
        archive_audit.append({
            "path": str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path),
            "base_gw": base_gw,
            "model_version": payload["meta"].get("model_version", "unknown"),
            "scoring_source": scoring_source,
            "resolved_forecasts": resolved,
            "component_forecasts": component_ready,
        })

    by_lead: dict[int, list[dict]] = defaultdict(list)
    by_version: dict[str, list[dict]] = defaultdict(list)
    for row in samples:
        by_lead[row["lead"]].append(row)
        by_version[row["model_version"]].append(row)
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "window": window,
            "archives_found": len(archives),
            "resolved_forecasts": len(samples),
            "forecast_components": list(FORECAST_COMPONENTS),
            "unmodeled_components": list(UNMODELED_COMPONENTS),
            "error_sign": "forecast minus actual; positive bias means overprediction",
            "population_policy": (
                "all-player diagnostics are unweighted; contender metrics use frozen "
                "pre-deadline calibration weights"
            ),
        },
        "archives": archive_audit,
        "overall": grouped_metrics(samples),
        "by_lead": {
            str(lead): grouped_metrics(rows) for lead, rows in sorted(by_lead.items())
        },
        "by_model_version": {
            version: {
                "overall": grouped_metrics(rows),
                "by_lead": {
                    str(lead): grouped_metrics([
                        row for row in rows if row["lead"] == lead
                    ])
                    for lead in sorted({row["lead"] for row in rows})
                },
            }
            for version, rows in sorted(by_version.items())
        },
    }


def print_report(payload: dict) -> None:
    meta = payload["meta"]
    if not meta["archives_found"]:
        print("no frozen projection archives yet — component evaluator is ready")
        return
    if not meta["resolved_forecasts"]:
        print(f"{meta['archives_found']} archive(s), but no forecast gameweeks are finalized yet")
        return
    print(
        f"component evaluation — {meta['archives_found']} archive(s), "
        f"{meta['resolved_forecasts']} resolved forecasts"
    )
    print(f"{'lead':<7}{'n all':>7}{'MAE all':>11}{'bias all':>11}{'n fit':>8}{'MAE fit':>11}{'bias fit':>11}")
    for lead, populations in payload["by_lead"].items():
        all_total = populations["all"]["total"]
        fit_total = populations["contenders"]["total"]
        fit_n = fit_total["n"] if fit_total else 0
        fit_mae = f"{fit_total['mae']:.2f}" if fit_total else "-"
        fit_bias = f"{fit_total['bias']:.2f}" if fit_total else "-"
        print(
            f"GW+{lead:<3}{all_total['n']:>7}{all_total['mae']:>11.2f}{all_total['bias']:>11.2f}"
            f"{fit_n:>8}{fit_mae:>11}{fit_bias:>11}"
        )
    print("\ncontender component error (forecast - actual):")
    print(f"{'lead':<7}{'component':<18}{'n':>6}{'MAE':>10}{'RMSE':>10}{'bias':>10}")
    for lead, populations in payload["by_lead"].items():
        fit = populations["contenders"]
        for component in FORECAST_COMPONENTS + ("residual",):
            row = fit["residual"] if component == "residual" else fit["components"][component]
            if row:
                print(
                    f"GW+{lead:<3}{component:<18}{row['n']:>6}"
                    f"{row['mae']:>10.3f}{row['rmse']:>10.3f}{row['bias']:>+10.3f}"
                )


def evaluate(window: int) -> dict:
    payload = build_evaluation(window)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print_report(payload)
    print(f"full audit: {OUT.relative_to(ROOT)}")
    return payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=6, help="most recent forecast archives")
    args = parser.parse_args()
    evaluate(args.window)
