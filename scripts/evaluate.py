"""Walk-forward evaluation of frozen xP forecasts against finalized observations."""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OBSERVATIONS = ROOT / "observations" / "player_fixtures.jsonl"
FORECASTS = ROOT / "projections"


def actual_points() -> dict[tuple[str, int, int], int]:
    latest = {}
    if not OBSERVATIONS.exists():
        return {}
    for line in OBSERVATIONS.read_text().splitlines():
        row = json.loads(line)
        latest[(row["season"], row["fixture_id"], row["element"])] = row
    totals = defaultdict(int)
    for row in latest.values():
        totals[(row["season"], row["gw"], row["element"])] += row["total_points"]
    return dict(totals)


def evaluate(window: int) -> None:
    actual = actual_points()
    archives = sorted(FORECASTS.glob("gw*.json"))[-window:]
    samples = defaultdict(list)
    for path in archives:
        payload = json.loads(path.read_text())
        base_gw = payload["meta"]["gw"]
        season = payload["meta"]["season"]
        for player in payload["players"].values():
            for forecast in player["gameweeks"]:
                observed = actual.get((season, forecast["gw"], player["element"]))
                if observed is None:
                    continue
                lead = forecast["gw"] - base_gw + 1
                samples[lead].append((forecast["xP"], observed, player["calibration_weight"]))
    if not samples:
        print("no resolved forecast horizons yet")
        return
    print(f"walk-forward evaluation: last {len(archives)} archived forecast gameweeks")
    print(f"{'lead':<7}{'n':>6}{'MAE all':>12}{'bias all':>12}{'n fit':>9}{'MAE fit':>12}{'bias fit':>12}")
    for lead in sorted(samples):
        rows = samples[lead]
        fit = [row for row in rows if row[2] > 0]
        mae = sum(abs(predicted - observed) for predicted, observed, _ in rows) / len(rows)
        bias = sum(predicted - observed for predicted, observed, _ in rows) / len(rows)
        if fit:
            weight = sum(row[2] for row in fit)
            fit_mae = sum(abs(p - a) * w for p, a, w in fit) / weight
            fit_bias = sum((p - a) * w for p, a, w in fit) / weight
            fit_text = f"{len(fit):>9}{fit_mae:>12.2f}{fit_bias:>12.2f}"
        else:
            fit_text = f"{0:>9}{'-':>12}{'-':>12}"
        print(f"GW+{lead:<3}{len(rows):>6}{mae:>12.2f}{bias:>12.2f}{fit_text}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window", type=int, default=6, help="most recent forecast archives")
    args = parser.parse_args()
    evaluate(args.window)
