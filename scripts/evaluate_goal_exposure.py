"""Compare role-state goal exposure with the former expected-minutes shortcut."""
from __future__ import annotations

import csv
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import goal_exposure
import train_minutes

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "models" / "goal_exposure_validation.json"
SCORING = {
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
}


def load_rows(path: Path, players_path: Path) -> list[dict]:
    with players_path.open(newline="") as handle:
        codes = {int(row["id"]): int(row["code"]) for row in csv.DictReader(handle)}
    with path.open(newline="") as handle:
        return [{
            "element": codes[int(row["element"])],
            "position": "GKP" if row["position"] == "GK" else row["position"],
            "minutes": int(row["minutes"]),
            "gw": int(row["GW"]),
            "clean_sheets": int(row["clean_sheets"]),
            "goals_conceded": int(row["goals_conceded"]),
            "fixture": int(row["fixture"]),
            "home_goals": int(row["team_h_score"]),
            "away_goals": int(row["team_a_score"]),
        } for row in csv.DictReader(handle)]


def prior_goal_rate(rows: list[dict]) -> tuple[float, int]:
    fixtures = {
        row["fixture"]: (row["home_goals"], row["away_goals"]) for row in rows
    }
    return (
        sum(home + away for home, away in fixtures.values()) / (2 * len(fixtures)),
        len(fixtures),
    )


def metrics(rows: list[dict]) -> dict:
    def summarize(values: list[tuple[float, float]]) -> dict:
        errors = [predicted - actual for predicted, actual in values]
        return {
            "n": len(values),
            "mae": sum(abs(error) for error in errors) / len(errors),
            "rmse": math.sqrt(sum(error * error for error in errors) / len(errors)),
            "bias": sum(errors) / len(errors),
            "predicted_mean": sum(predicted for predicted, _ in values) / len(values),
            "actual_mean": sum(actual for _, actual in values) / len(values),
        }

    result = {}
    for population in ("all", "contenders"):
        selected = [row for row in rows if population == "all" or row["contender"]]
        result[population] = {
            model: {
                component: summarize([
                    (row[model][component], row["actual"][component]) for row in selected
                ])
                for component in ("clean_sheet", "goals_conceded", "combined")
            }
            for model in ("shortcut", "role_state")
        }
    return result


def main() -> None:
    rows = load_rows(train_minutes.GWS, train_minutes.PLAYERS)
    prior_rows = load_rows(train_minutes.PRIOR_GWS, train_minutes.PRIOR_PLAYERS)
    opponent_lam, prior_fixtures = prior_goal_rate(prior_rows)
    forecasts = train_minutes.walk_forward_predictions(rows)
    by_gw: dict[int, list[dict]] = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    histories: dict[int, list[dict]] = defaultdict(list)
    scored = []
    for gw in range(1, 39):
        for row in by_gw[gw]:
            forecast = forecasts[(row["element"], gw)]
            recent = histories[row["element"]][-3:]
            contender = bool(recent) and sum(item["minutes"] for item in recent) / len(recent) >= 30
            shortcut = goal_exposure.shortcut(
                SCORING, row["position"], opponent_lam,
                forecast["bands"]["p_60_plus"], forecast["exp_minutes"],
            )
            role_state = goal_exposure.predict(
                SCORING, row["position"], opponent_lam,
                {"source": "historical_walk_forward", **forecast},
            )
            actual_clean = SCORING["clean_sheets"][row["position"]] * row["clean_sheets"]
            actual_conceded = (
                SCORING["goals_conceded"][row["position"]]
                * (row["goals_conceded"] // 2)
            )
            scored.append({
                "contender": contender,
                "shortcut": {
                    "clean_sheet": shortcut["clean_sheet_points"],
                    "goals_conceded": shortcut["goals_conceded_points"],
                    "combined": shortcut["clean_sheet_points"] + shortcut["goals_conceded_points"],
                },
                "role_state": {
                    "clean_sheet": role_state["clean_sheet_points"],
                    "goals_conceded": role_state["goals_conceded_points"],
                    "combined": role_state["clean_sheet_points"] + role_state["goals_conceded_points"],
                },
                "actual": {
                    "clean_sheet": actual_clean,
                    "goals_conceded": actual_conceded,
                    "combined": actual_clean + actual_conceded,
                },
            })
        for row in by_gw[gw]:
            histories[row["element"]].append(row)

    payload = {
        "model_version": goal_exposure.MODEL_VERSION,
        "evaluation_season": "2025/26",
        "pre_match_goal_rate": {
            "source_season": "2024/25",
            "goals_per_team_fixture": opponent_lam,
            "fixtures": prior_fixtures,
            "policy": "fixed before 2025/26; deliberately no final-score or in-season fixture-strength input",
        },
        "source_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                train_minutes.GWS, train_minutes.PLAYERS,
                train_minutes.PRIOR_GWS, train_minutes.PRIOR_PLAYERS,
            )
        },
        "minutes_model_sha256": hashlib.sha256(train_minutes.MODEL.read_bytes()).hexdigest(),
        "population_policy": (
            "all-player diagnostics; contender means at least one prior appearance and "
            "at least 30 average minutes over up to three prior matches"
        ),
        "metrics": metrics(scored),
        "interpretation": (
            "This isolates the scoring transform under one deliberately weak pre-match goal rate. "
            "It does not validate the separate bookmaker/FDR opponent-goal forecast."
        ),
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    contender = payload["metrics"]["contenders"]
    for model in ("shortcut", "role_state"):
        row = contender[model]["combined"]
        print(f"{model:<10} n={row['n']} MAE={row['mae']:.5f} RMSE={row['rmse']:.5f} bias={row['bias']:+.5f}")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
