"""Walk-forward training for the hierarchical minutes model.

Uses only information available before each historical gameweek. The fitted artifact is
small and tracked; the source CSVs remain reproducible, gitignored cache files.
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

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
MODEL = ROOT / "models" / "minutes_params.json"
GWS = DATA / "2025-26_merged_gw.csv"
PLAYERS = DATA / "2025-26_players_raw.csv"
PRIOR_GWS = DATA / "2024-25_merged_gw.csv"
PRIOR_PLAYERS = DATA / "2024-25_players_raw.csv"
GWS_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2025-26/gws/merged_gw.csv"
PLAYERS_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2025-26/players_raw.csv"
PRIOR_GWS_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2024-25/gws/merged_gw.csv"
PRIOR_PLAYERS_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data/2024-25/players_raw.csv"

HALFLIVES = (3.0, 5.0, 8.0, 12.0)
PEER_WEIGHTS = (0.5, 1.0, 2.0, 4.0)
PROBABILITY_FLOOR = 0.01
STATE_PROBABILITY_FLOOR = 0.001
CLUB_CHANGE_RETENTION = 0.5  # explicit assumption; too few transitions to fit honestly
OFFSEASON_GAP_GWS = 4
FIRST_TEST_GW = 1

ROLE_STATES = (
    "unused",
    "cameo_1_29",
    "cameo_30_59",
    "cameo_60_plus",
    "starter_1_59",
    "starter_60_74",
    "starter_75_89",
    "starter_90_plus",
)
BANDS = ("p_zero", "p_1_59", "p_60_plus")
STATE_DEFAULT_MINUTES = {
    "unused": 0.0,
    "cameo_1_29": 15.0,
    "cameo_30_59": 42.0,
    "cameo_60_plus": 65.0,
    "starter_1_59": 50.0,
    "starter_60_74": 67.0,
    "starter_75_89": 82.0,
    "starter_90_plus": 90.0,
}


def fetch_if_needed() -> None:
    DATA.mkdir(exist_ok=True)
    for path, url in (
        (GWS, GWS_URL), (PLAYERS, PLAYERS_URL),
        (PRIOR_GWS, PRIOR_GWS_URL), (PRIOR_PLAYERS, PRIOR_PLAYERS_URL),
    ):
        if path.exists():
            continue
        response = requests.get(url, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
        print(f"downloaded {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def role(row: dict) -> str:
    minutes = row["minutes"]
    if minutes == 0:
        return "unused"
    if not row["starts"]:
        if minutes < 30:
            return "cameo_1_29"
        return "cameo_30_59" if minutes < 60 else "cameo_60_plus"
    if minutes < 60:
        return "starter_1_59"
    if minutes < 75:
        return "starter_60_74"
    if minutes < 90:
        return "starter_75_89"
    return "starter_90_plus"


def band(row: dict) -> str:
    if row["minutes"] == 0:
        return "p_zero"
    return "p_1_59" if row["minutes"] < 60 else "p_60_plus"


def price_band(value: int) -> int:
    return value // 10


def load_season(gws_path: Path, players_path: Path, prior: bool) -> tuple[list[dict], dict[int, int]]:
    required = {"element", "position", "team", "minutes", "starts", "value", "GW"}
    with players_path.open(newline="") as handle:
        id_to_code = {int(row["id"]): int(row["code"]) for row in csv.DictReader(handle)}
    with gws_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"historical gameweeks missing columns: {sorted(missing)}")
        rows = [{
            "element": id_to_code[int(row["element"])],
            "position": "GKP" if row["position"] == "GK" else row["position"],
            "team": row["team"],
            "minutes": int(row["minutes"]),
            "starts": int(row["starts"]),
            "value": int(row["value"]),
            "gw": int(row["GW"]),
            "prior_season": prior,
        } for row in reader]
    return rows, id_to_code


def load_rows() -> tuple[list[dict], list[dict], dict[int, int]]:
    rows, id_to_code = load_season(GWS, PLAYERS, False)
    prior_rows, _ = load_season(PRIOR_GWS, PRIOR_PLAYERS, True)
    return rows, prior_rows, id_to_code


def age(target_gw: int, row: dict) -> int:
    if row["prior_season"]:
        return target_gw + OFFSEASON_GAP_GWS + 38 - row["gw"]
    return target_gw - row["gw"]


def normalize(counts: dict[str, float], keys: tuple[str, ...], floor: float) -> dict[str, float]:
    total = sum(counts.get(key, 0.0) for key in keys) or 1.0
    values = {key: max(counts.get(key, 0.0) / total, floor) for key in keys}
    scale = sum(values.values())
    return {key: value / scale for key, value in values.items()}


def peer_tables(rows: list[dict], before_gw: int, halflife: float) -> dict:
    tables = {"group": defaultdict(lambda: defaultdict(float)),
              "position": defaultdict(lambda: defaultdict(float))}
    for row in rows:
        row_age = age(before_gw, row)
        if row_age <= 0:
            continue
        weight = 0.5 ** (row_age / halflife)
        for key in ((row["position"], price_band(row["value"])), row["position"]):
            table = tables["group"] if isinstance(key, tuple) else tables["position"]
            stats = table[key]
            stats[band(row)] += weight
            state = role(row)
            stats[f"role:{state}"] += weight
            stats[f"role_minutes:{state}"] += weight * row["minutes"]
            stats["minutes"] += weight * row["minutes"]
            stats["weight"] += weight
    return tables


def predict(
    history: list[dict],
    target: dict,
    peers: dict,
    halflife: float,
    prior_weight: float,
    state_driven: bool = True,
) -> dict:
    group = (target["position"], price_band(target["value"]))
    peer = peers["group"].get(group) or peers["position"].get(target["position"]) or {}
    peer_bands = normalize(peer, BANDS, PROBABILITY_FLOOR)
    peer_roles = normalize(
        {key: peer.get(f"role:{key}", 0.0) for key in ROLE_STATES},
        ROLE_STATES,
        PROBABILITY_FLOOR,
    )
    peer_state_minutes = {
        key: (
            peer.get(f"role_minutes:{key}", 0.0) / peer[f"role:{key}"]
            if peer.get(f"role:{key}", 0.0) else STATE_DEFAULT_MINUTES[key]
        )
        for key in ROLE_STATES
    }
    peer_minutes = peer.get("minutes", 0.0) / (peer.get("weight", 0.0) or 1.0)

    band_counts = {key: prior_weight * peer_bands[key] for key in BANDS}
    role_counts = {key: prior_weight * peer_roles[key] for key in ROLE_STATES}
    role_minutes = {
        key: role_counts[key] * peer_state_minutes[key] for key in ROLE_STATES
    }
    minute_total = prior_weight * peer_minutes
    total_weight = prior_weight
    for row in history:
        weight = 0.5 ** (age(target["gw"], row) / halflife)
        if row["team"] != target["team"]:
            weight *= CLUB_CHANGE_RETENTION
        band_counts[band(row)] += weight
        state = role(row)
        role_counts[state] += weight
        role_minutes[state] += weight * row["minutes"]
        minute_total += weight * row["minutes"]
        total_weight += weight
    states = normalize(role_counts, ROLE_STATES, STATE_PROBABILITY_FLOOR)
    conditional = {
        key: role_minutes[key] / role_counts[key] if role_counts[key] else STATE_DEFAULT_MINUTES[key]
        for key in ROLE_STATES
    }
    state_bands = {
        "p_zero": states["unused"],
        "p_1_59": states["cameo_1_29"] + states["cameo_30_59"] + states["starter_1_59"],
        "p_60_plus": states["cameo_60_plus"] + states["starter_60_74"]
        + states["starter_75_89"] + states["starter_90_plus"],
    }
    bands = (
        normalize(state_bands, BANDS, PROBABILITY_FLOOR)
        if state_driven else normalize(band_counts, BANDS, PROBABILITY_FLOOR)
    )
    exp_minutes = (
        sum(states[key] * conditional[key] for key in ROLE_STATES)
        if state_driven else minute_total / total_weight
    )
    return {
        "bands": bands,
        "role_states": states,
        "conditional_minutes_by_state": conditional,
        "exp_minutes": exp_minutes,
        "personal_weight": total_weight - prior_weight,
        "peer_group": f"{group[0]}_{group[1]}m",
    }


def metrics(
    rows: list[dict],
    prior_rows: list[dict],
    halflife: float,
    prior_weight: float,
    state_driven: bool = True,
) -> dict:
    by_gw = defaultdict(list)
    for row in rows:
        by_gw[row["gw"]].append(row)
    histories = defaultdict(list)
    for row in prior_rows:
        histories[row["element"]].append(row)
    for history in histories.values():
        history.sort(key=lambda row: row["gw"])
    totals = {name: [0.0, 0.0, 0.0, 0] for name in (
        "all", "contenders", "early_contenders", "later_contenders",
        "benchmark_eligible_later_contenders",
    )}
    calibration = {
        target: defaultdict(lambda: [0.0, 0.0, 0]) for target in ("p_zero", "p_60_plus")
    }
    history_pool = list(prior_rows)
    for gw in range(1, 39):
        targets = by_gw[gw]
        if gw >= FIRST_TEST_GW:
            peers = peer_tables(history_pool, gw, halflife)
            for target in targets:
                history = histories[target["element"]]
                forecast = predict(
                    history, target, peers, halflife, prior_weight, state_driven
                )
                actual_band = band(target)
                actual_probability = max(forecast["bands"][actual_band], 1e-9)
                brier = sum(
                    (forecast["bands"][key] - (key == actual_band)) ** 2 for key in BANDS
                )
                mae = abs(forecast["exp_minutes"] - target["minutes"])
                recent = history[-3:]
                contender = bool(recent) and sum(row["minutes"] for row in recent) / len(recent) >= 30
                populations = ["all"]
                if contender:
                    populations.append("contenders")
                    if gw <= 5:
                        populations.append("early_contenders")
                    else:
                        populations.append("later_contenders")
                        if sum(not row["prior_season"] for row in history) >= 2:
                            populations.append("benchmark_eligible_later_contenders")
                    for key in calibration:
                        calibration_probability = forecast["bands"][key]
                        bucket = min(int(calibration_probability * 10), 9)
                        cell = calibration[key][bucket]
                        cell[0] += calibration_probability
                        cell[1] += key == actual_band
                        cell[2] += 1
                for population in populations:
                    bucket = totals[population]
                    bucket[0] += -math.log(actual_probability)
                    bucket[1] += brier
                    bucket[2] += mae
                    bucket[3] += 1
        for row in targets:
            histories[row["element"]].append(row)
            history_pool.append(row)
    result = {}
    for population, (logloss, brier, mae, count) in totals.items():
        result[population] = {
            "n": count,
            "log_loss": logloss / count,
            "brier": brier / count,
            "minutes_mae": mae / count,
            "selection_score": logloss / count + mae / count / 90,
        }
    calibration_rows = {
        target: [
            {
                "range": f"{bucket / 10:.1f}-{(bucket + 1) / 10:.1f}",
                "n": values[2],
                "mean_predicted": values[0] / values[2],
                "actual_rate": values[1] / values[2],
            }
            for bucket, values in sorted(cells.items())
        ]
        for target, cells in calibration.items()
    }
    result["calibration_contenders"] = {
        target: {
            "expected_calibration_error": sum(
                abs(row["mean_predicted"] - row["actual_rate"]) * row["n"]
                for row in rows
            ) / sum(row["n"] for row in rows),
            "bins": rows,
        }
        for target, rows in calibration_rows.items()
    }
    return result


def empirical_baseline_metrics(rows: list[dict]) -> dict:
    """Existing current-season-only model on the folds where it has >=2 observations."""
    by_gw = defaultdict(list)
    histories = defaultdict(list)
    total = [0.0, 0.0, 0.0, 0]
    for row in rows:
        by_gw[row["gw"]].append(row)
    for gw in range(1, 39):
        if gw >= 6:
            for target in by_gw[gw]:
                history = histories[target["element"]]
                recent = history[-3:]
                if len(history) < 2 or sum(row["minutes"] for row in recent) / len(recent) < 30:
                    continue
                counts = {key: 0.0 for key in BANDS}
                weight_total = minute_total = 0.0
                for row in history:
                    weight = 0.5 ** ((gw - row["gw"]) / 5.0)
                    counts[band(row)] += weight
                    minute_total += weight * row["minutes"]
                    weight_total += weight
                probabilities = normalize(counts, BANDS, 0.05)
                actual = band(target)
                total[0] += -math.log(max(probabilities[actual], 1e-9))
                total[1] += sum((probabilities[key] - (key == actual)) ** 2 for key in BANDS)
                total[2] += abs(minute_total / weight_total - target["minutes"])
                total[3] += 1
        for row in by_gw[gw]:
            histories[row["element"]].append(row)
    logloss, brier, mae, count = total
    return {
        "population": "same contender rule, GW6-38, players with >=2 current rows",
        "n": count,
        "log_loss": logloss / count,
        "brier": brier / count,
        "minutes_mae": mae / count,
        "selection_score": logloss / count + mae / count / 90,
    }


def serialize_peer_tables(tables: dict) -> dict:
    result = {}
    for table_name, table in tables.items():
        result[table_name] = {}
        for key, stats in table.items():
            label = "_".join(map(str, key)) if isinstance(key, tuple) else str(key)
            result[table_name][label] = {
                "bands": normalize(stats, BANDS, PROBABILITY_FLOOR),
                "role_states": normalize(
                    {role_name: stats.get(f"role:{role_name}", 0.0) for role_name in ROLE_STATES},
                    ROLE_STATES,
                    PROBABILITY_FLOOR,
                ),
                "conditional_minutes_by_state": {
                    role_name: (
                        stats.get(f"role_minutes:{role_name}", 0.0)
                        / stats[f"role:{role_name}"]
                        if stats.get(f"role:{role_name}", 0.0)
                        else STATE_DEFAULT_MINUTES[role_name]
                    )
                    for role_name in ROLE_STATES
                },
                "exp_minutes": stats["minutes"] / stats["weight"],
                "effective_rows": stats["weight"],
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="download source CSVs if absent")
    args = parser.parse_args()
    if args.fetch:
        fetch_if_needed()
    if not all(path.exists() for path in (GWS, PLAYERS, PRIOR_GWS, PRIOR_PLAYERS)):
        raise SystemExit("historical CSVs missing; run train_minutes.py --fetch")
    rows, prior_rows, _ = load_rows()
    grids = {}
    for label, state_driven in (("rich_states", True), ("coarse_bands", False)):
        candidates = []
        print(f"{label}:")
        for halflife, prior_weight in itertools.product(HALFLIVES, PEER_WEIGHTS):
            score = metrics(rows, prior_rows, halflife, prior_weight, state_driven)
            candidates.append((score["contenders"]["selection_score"], halflife, prior_weight, score))
            print(f"  half-life {halflife:>4.0f}  peer {prior_weight:>3g}  "
                  f"score {score['contenders']['selection_score']:.4f}")
        grids[label] = candidates
    rich_best = min(grids["rich_states"])
    coarse_best = min(grids["coarse_bands"])
    state_driven = rich_best[0] < coarse_best[0]
    selected_label = "rich_states" if state_driven else "coarse_bands"
    _, halflife, prior_weight, best_metrics = rich_best if state_driven else coarse_best
    peer = serialize_peer_tables(peer_tables(prior_rows + rows, 39, halflife))
    baseline = empirical_baseline_metrics(rows)
    payload = {
        "model_version": "hierarchical-minutes-v2",
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_season": "2025/26",
        "training_rows": len(rows),
        "prior_rows": len(prior_rows),
        "training_source": {
            "gameweeks": GWS_URL, "players": PLAYERS_URL,
            "prior_gameweeks": PRIOR_GWS_URL, "prior_players": PRIOR_PLAYERS_URL,
        },
        "gameweeks_sha256": hashlib.sha256(GWS.read_bytes()).hexdigest(),
        "players_sha256": hashlib.sha256(PLAYERS.read_bytes()).hexdigest(),
        "prior_gameweeks_sha256": hashlib.sha256(PRIOR_GWS.read_bytes()).hexdigest(),
        "prior_players_sha256": hashlib.sha256(PRIOR_PLAYERS.read_bytes()).hexdigest(),
        "identity_policy": "prior element id -> players_raw.code -> current stable player code",
        "selected": {
            "decay_halflife_gws": halflife,
            "peer_prior_weight": prior_weight,
            "probability_floor": PROBABILITY_FLOOR,
            "state_probability_floor": STATE_PROBABILITY_FLOOR,
            "state_driven_outputs": state_driven,
            "club_change_retention": CLUB_CHANGE_RETENTION,
            "offseason_gap_gws": OFFSEASON_GAP_GWS,
        },
        "selection_policy": (
            "minimize log_loss + minutes_mae/90 on players averaging >=30 minutes "
            "over their prior three matches; predict 2025/26 GW1-38 from only older rows"
        ),
        "metrics": best_metrics,
        "challenger_comparison": {
            "selected": selected_label,
            "rich_states": rich_best[3],
            "coarse_bands": coarse_best[3],
        },
        "benchmark_current_empirical": baseline,
        "grid": {
            label: [
                {
                    "decay_halflife_gws": h,
                    "peer_prior_weight": p,
                    "metrics": {
                        key: value for key, value in score.items()
                        if key != "calibration_contenders"
                    },
                }
                for _, h, p, score in candidates
            ]
            for label, candidates in grids.items()
        },
        "peer_priors": peer,
        "known_limits": [
            "club-change retention and offseason gap are explicit assumptions, not fitted",
            "one historical season cannot test season-to-season transport",
            "availability/news overrides are evaluated separately",
        ],
    }
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"selected {selected_label}: half-life {halflife:g}, peer weight {prior_weight:g}")
    print(f"wrote {MODEL.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
