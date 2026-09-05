"""Transparent one-gameweek FPL expected-points baseline.

Combines the minutes model, bookmaker-implied match probabilities, official xG/xA,
and current-season per-match history. Component estimates are kept in the output so the
total can be audited. This is a baseline to measure, not a claim of calibrated truth.

Usage:
    python scripts/projections.py --show 30
    python scripts/projections.py archive
    python scripts/projections.py resolve --gw 4
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import minutes
import defcon

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "projections.json"
ARCHIVE_DIR = ROOT / "projections"
MODEL_VERSION = "baseline-v3-defcon"
PRIOR_STRENGTH = 5.0
# Last season is useful early evidence, but not a permanent claim about the player's
# current role. Ten matches is an explicit starting assumption to recalibrate from the
# frozen archives; current-season minutes dilute it one-for-one.
PLAYER_PRIOR_MINUTES = 900.0
# Before becoming the player's prior, a prior-season rate is itself pulled toward the
# positional population by five matches. This limits one small prior-season sample.
POSITION_PRIOR_MINUTES = 450.0
DEFAULT_HORIZON = 6
HORIZON_DISCOUNT = 0.85
FORM_PRIOR_MATCHES = 5.0
FDR_BUCKET_PRIOR_SIDES = 3
FDR_SPARSE_MIN_SIDES = 3
PREVIOUS_SEASON_FIELDS = (
    "season_name", "element_code", "total_points", "minutes", "starts",
    "goals_scored", "assists", "clean_sheets", "goals_conceded", "own_goals",
    "penalties_saved", "penalties_missed", "yellow_cards", "red_cards", "saves",
    "bonus", "bps", "defensive_contribution", "expected_goals", "expected_assists",
    "expected_goals_conceded",
)


def load(path: Path) -> dict | list:
    return json.loads(path.read_text())


def poisson_pmf(k: int, lam: float) -> float:
    return math.exp(-lam) * lam**k / math.factorial(k)


def poisson_match_probs(home_lam: float, away_lam: float) -> tuple[float, float, float]:
    home = draw = away = 0.0
    for hg in range(11):
        hp = poisson_pmf(hg, home_lam)
        for ag in range(11):
            p = hp * poisson_pmf(ag, away_lam)
            if hg > ag:
                home += p
            elif hg == ag:
                draw += p
            else:
                away += p
    total = home + draw + away
    return home / total, draw / total, away / total


def total_goals_lambda(over_2_5: float) -> float:
    """Solve P(Poisson(lambda) >= 3) = market over-2.5 probability."""
    low, high = 0.05, 7.0
    for _ in range(60):
        mid = (low + high) / 2
        over = 1 - math.exp(-mid) * (1 + mid + mid * mid / 2)
        if over < over_2_5:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def infer_goal_lambdas(odds: dict) -> tuple[float, float, float] | None:
    """Fit independent-Poisson team rates to O/U 2.5 and the 1X2 vector.

    O/U fixes total expected goals; a one-dimensional grid finds the home/away split
    minimizing squared error against all three 1X2 probabilities. The model assumption
    and fit error are exposed in output rather than hidden.
    """
    if odds.get("over_2_5") is None:
        return None
    total = total_goals_lambda(odds["over_2_5"])
    best = None
    for step in range(21, 180):
        home_share = step / 200
        home_lam, away_lam = total * home_share, total * (1 - home_share)
        h, d, a = poisson_match_probs(home_lam, away_lam)
        error = (h - odds["home_win"]) ** 2 + (d - odds["draw"]) ** 2 + (a - odds["away_win"]) ** 2
        if best is None or error < best[0]:
            best = (error, home_lam, away_lam)
    return (best[1], best[2], best[0]) if best else None


def expected_goal_conceded_deduction(lam: float) -> float:
    return sum((goals // 2) * poisson_pmf(goals, lam) for goals in range(12))


def expected_clean_sheet_points(
    scoring: dict, position: str, opponent_lam: float, p_60: float,
) -> float:
    """Clean-sheet points require 60 minutes; DefCon deliberately does not."""
    return scoring["clean_sheets"][position] * math.exp(-opponent_lam) * p_60


@lru_cache(maxsize=None)
def history_for(player_id: int, target_gw: int) -> tuple[dict, ...]:
    path = DATA_DIR / f"element_summary/{player_id}.json"
    if not path.exists():
        return ()
    fixtures = load(DATA_DIR / "fixtures.json")
    history = minutes.completed_history(load(path)["history"], fixtures)
    return tuple(row for row in history if row["round"] < target_gw)


@lru_cache(maxsize=None)
def previous_season_for(player_id: int) -> dict | None:
    path = DATA_DIR / f"element_summary/{player_id}.json"
    if not path.exists():
        return None
    rows = load(path).get("history_past", [])
    return rows[-1] if rows else None


def previous_season_snapshot(previous: dict | None) -> dict | None:
    """Keep the official actuals needed to reinterpret a frozen prior later."""
    if not previous:
        return None
    return {field: previous.get(field) for field in PREVIOUS_SEASON_FIELDS}


def defensive_actions(row: dict, position: str) -> int:
    actions = row.get("tackles", 0) + row.get("clearances_blocks_interceptions", 0)
    if position in {"MID", "FWD"}:
        actions += row.get("recoveries", 0)
    return actions


def build_priors(players: list[dict], types: dict[int, str], target_gw: int) -> dict:
    buckets = {
        position: {"plays": 0, "minutes": 0, "xg": 0.0, "xa": 0.0, "yellow": 0,
                   "red": 0, "defcon": 0, "bonus": 0.0, "saves": 0}
        for position in types.values()
    }
    for player in players:
        position = types[player["element_type"]]
        threshold = 10 if position == "DEF" else 12
        for row in history_for(player["id"], target_gw):
            if row["minutes"] <= 0:
                continue
            bucket = buckets[position]
            bucket["plays"] += 1
            bucket["minutes"] += row["minutes"]
            bucket["xg"] += float(row.get("expected_goals") or 0)
            bucket["xa"] += float(row.get("expected_assists") or 0)
            bucket["yellow"] += bool(row.get("yellow_cards"))
            bucket["red"] += bool(row.get("red_cards"))
            bucket["bonus"] += row.get("bonus", 0)
            bucket["saves"] += row.get("saves", 0)
            if position != "GKP" and defensive_actions(row, position) >= threshold:
                bucket["defcon"] += 1
    priors = {}
    for position, bucket in buckets.items():
        plays = bucket["plays"] or 1
        priors[position] = {
            "yellow": bucket["yellow"] / plays,
            "red": bucket["red"] / plays,
            "defcon": bucket["defcon"] / plays,
            "bonus": bucket["bonus"] / plays,
            "expected_goals_per_90": bucket["xg"] * 90 / (bucket["minutes"] or 1),
            "expected_assists_per_90": bucket["xa"] * 90 / (bucket["minutes"] or 1),
            "yellow_cards_per_90": bucket["yellow"] * 90 / (bucket["minutes"] or 1),
            "red_cards_per_90": bucket["red"] * 90 / (bucket["minutes"] or 1),
            "saves_per_90": bucket["saves"] * 90 / (bucket["minutes"] or 1),
            "sample": bucket["plays"],
        }
    return priors


def shrunk_rate(successes: float, n: int, prior: float, strength: float = PRIOR_STRENGTH) -> float:
    return (successes + prior * strength) / (n + strength)


def prior_season_rate(previous: dict | None, field: str, position_rate: float) -> tuple[float, dict]:
    """Build an auditable player prior from the latest official season aggregate."""
    previous_minutes = int(previous.get("minutes", 0)) if previous else 0
    previous_total = float(previous.get(field) or 0) if previous else 0.0
    if previous_minutes:
        rate = (
            previous_total * 90 + position_rate * POSITION_PRIOR_MINUTES
        ) / (previous_minutes + POSITION_PRIOR_MINUTES)
        source = "previous_season_shrunk_to_position"
    else:
        rate = position_rate
        source = "position_only"
    return rate, {
        "source": source,
        "season": previous.get("season_name") if previous else None,
        "raw_total": round(previous_total, 5),
        "raw_minutes": previous_minutes,
        "raw_per_90": round(previous_total * 90 / previous_minutes, 5) if previous_minutes else None,
        "position_per_90": round(position_rate, 5),
        "position_prior_minutes": POSITION_PRIOR_MINUTES,
        "player_prior_per_90": round(rate, 5),
        "effective_prior_minutes": PLAYER_PRIOR_MINUTES,
    }


def blended_per_90(player: dict, target_gw: int, prior: dict, field: str) -> tuple[float, dict]:
    """Blend completed current-season evidence with a finite prior-season anchor."""
    rows = history_for(player["id"], target_gw)
    played_minutes = sum(row["minutes"] for row in rows)
    observed = sum(float(row.get(field) or 0) for row in rows)
    position_rate = prior[f"{field}_per_90"]
    previous = previous_season_for(player["id"])
    player_prior, audit = prior_season_rate(previous, field, position_rate)
    rate = (observed * 90 + player_prior * PLAYER_PRIOR_MINUTES) / (
        played_minutes + PLAYER_PRIOR_MINUTES
    )
    audit.update({
        "current_total": round(observed, 5),
        "current_minutes": played_minutes,
        "current_per_90": round(observed * 90 / played_minutes, 5) if played_minutes else None,
        "blended_per_90": round(rate, 5),
    })
    return rate, audit


def historical_components(
    player: dict,
    position: str,
    target_gw: int,
    prior: dict,
    p_play: float,
    exp_minutes: float,
    defcon_points: float,
) -> dict:
    rows = [row for row in history_for(player["id"], target_gw) if row["minutes"] > 0]
    n = len(rows)
    threshold = 10 if position == "DEF" else 12
    yellow, yellow_audit = blended_per_90(player, target_gw, prior, "yellow_cards")
    red, red_audit = blended_per_90(player, target_gw, prior, "red_cards")
    saves, saves_audit = (
        blended_per_90(player, target_gw, prior, "saves")
        if position == "GKP" else (0.0, None)
    )
    bonus = shrunk_rate(sum(r.get("bonus", 0) for r in rows), n, prior["bonus"])
    defcon_hits = sum(defensive_actions(r, position) >= threshold for r in rows) if position != "GKP" else 0
    defcon = shrunk_rate(defcon_hits, n, prior["defcon"]) if position != "GKP" else 0
    return {
        "yellow": -yellow * exp_minutes / 90,
        "red": -3 * red * exp_minutes / 90,
        # Fallback only. The trained threshold model overwrites this when available.
        # Unlike clean-sheet points, DefCon has no 60-minute requirement.
        "defcon": defcon_points * defcon,
        "bonus": bonus * p_play,
        "saves": saves / 3 * exp_minutes / 90 if position == "GKP" else 0.0,
        "history_appearances": n,
        "prior_audit": {
            "yellow_cards": yellow_audit,
            "red_cards": red_audit,
            **({"saves": saves_audit} if saves_audit else {}),
            "bonus": "previous season excluded because 2026/27 BPS rules changed",
            "defcon": "previous aggregate cannot reconstruct per-match threshold hits",
        },
    }


def recent_team_factors(team_ids: list[int]) -> tuple[dict[int, float], dict[int, float]]:
    """Shrunk attack/defence factors from finalized team xG, one value per fixture."""
    ledger = ROOT / "observations" / "player_fixtures.jsonl"
    if not ledger.exists():
        return ({team: 1.0 for team in team_ids}, {team: 1.0 for team in team_ids})
    latest = {}
    for line in ledger.read_text().splitlines():
        row = json.loads(line)
        latest[(row["season"], row["fixture_id"], row["element"])] = row
    team_fixture_xg = {}
    opponent_by_team_fixture = {}
    for row in latest.values():
        key = (row["team"], row["fixture_id"])
        team_fixture_xg[key] = team_fixture_xg.get(key, 0.0) + float(row.get("expected_goals") or 0)
        opponent_by_team_fixture[key] = row["opponent_team"]
    samples = {team: [] for team in team_ids}
    conceded = {team: [] for team in team_ids}
    for (team, fixture), xg in team_fixture_xg.items():
        samples.setdefault(team, []).append(xg)
        opponent = opponent_by_team_fixture[(team, fixture)]
        conceded.setdefault(opponent, []).append(xg)
    all_xg = list(team_fixture_xg.values())
    league = sum(all_xg) / len(all_xg) if all_xg else 1.4

    def factor(values: list[float]) -> float:
        recent = values[-6:]
        shrunk = (sum(recent) + FORM_PRIOR_MATCHES * league) / (len(recent) + FORM_PRIOR_MATCHES)
        return shrunk / league

    return (
        {team: factor(samples.get(team, [])) for team in team_ids},
        {team: factor(conceded.get(team, [])) for team in team_ids},
    )


def isotonic_decreasing(values: list[float], weights: list[float]) -> list[float]:
    """Weighted pool-adjacent-violators fit constrained to non-increasing values."""
    blocks = []
    for index, (value, weight) in enumerate(zip(values, weights)):
        blocks.append({"start": index, "end": index, "weight": weight, "mean": value})
        while len(blocks) >= 2 and blocks[-2]["mean"] < blocks[-1]["mean"]:
            right = blocks.pop()
            left = blocks.pop()
            weight = left["weight"] + right["weight"]
            blocks.append({
                "start": left["start"],
                "end": right["end"],
                "weight": weight,
                "mean": (left["mean"] * left["weight"] + right["mean"] * right["weight"]) / weight,
            })
    fitted = [0.0] * len(values)
    for block in blocks:
        for index in range(block["start"], block["end"] + 1):
            fitted[index] = block["mean"]
    return fitted


def fdr_goal_priors(odds_rows: list[dict], fixtures: list[dict]) -> tuple[dict, dict]:
    """Odds-calibrated FDR rates, constrained to get harder from FDR 1 through 5."""
    fixtures_by_id = {row["id"]: row for row in fixtures}
    buckets = {}
    all_rates = []
    for row in odds_rows:
        inferred = infer_goal_lambdas(row)
        fixture = fixtures_by_id.get(row["fixture_id"])
        if not inferred or not fixture:
            continue
        home_lam, away_lam, _ = inferred
        pairs = [
            ((True, fixture["team_h_difficulty"]), home_lam),
            ((False, fixture["team_a_difficulty"]), away_lam),
        ]
        for bucket, value in pairs:
            buckets.setdefault(bucket, []).append(value)
            all_rates.append(value)
    global_rate = sum(all_rates) / len(all_rates)
    priors = {}
    diagnostics = {
        "global_goal_rate": round(global_rate, 5),
        "global_prior_team_sides_per_bucket": FDR_BUCKET_PRIOR_SIDES,
        "sparse_below_market_team_sides": FDR_SPARSE_MIN_SIDES,
        "venues": {},
    }
    for home in (False, True):
        raw = []
        weights = []
        counts = []
        for difficulty in range(1, 6):
            values = buckets.get((home, difficulty), [])
            raw.append(
                (sum(values) + FDR_BUCKET_PRIOR_SIDES * global_rate)
                / (len(values) + FDR_BUCKET_PRIOR_SIDES)
            )
            weights.append(len(values) + FDR_BUCKET_PRIOR_SIDES)
            counts.append(len(values))
        fitted = isotonic_decreasing(raw, weights)
        venue = "home" if home else "away"
        diagnostics["venues"][venue] = {
            f"fdr{difficulty}": {
                "market_team_sides": counts[difficulty - 1],
                "sparse": counts[difficulty - 1] < FDR_SPARSE_MIN_SIDES,
                "raw_shrunk_goal_rate": round(raw[difficulty - 1], 5),
                "monotonic_goal_rate": round(fitted[difficulty - 1], 5),
            }
            for difficulty in range(1, 6)
        }
        for difficulty, value in enumerate(fitted, 1):
            priors[(home, difficulty)] = value
    diagnostics["sparse_buckets"] = sum(
        bucket["sparse"]
        for venue in diagnostics["venues"].values()
        for bucket in venue.values()
    )
    diagnostics["total_market_team_sides"] = len(all_rates)
    return priors, diagnostics


def extend_horizon(
    payload: dict, bootstrap: dict, fixtures: list[dict], odds_payload: dict,
    horizon: int, defcon_context: dict | None,
) -> None:
    def compact_defcon(prediction: dict) -> dict:
        """Fixture-varying fields only; common player evidence lives on the record."""
        audit = prediction.get("audit", {})
        return {
            key: prediction[key] for key in (
                "probability", "source", "threshold", "minutes_scenario_source"
            ) if key in prediction
        } | {
            "fixture_factors": {
                key: round(audit[key], 6)
                for key in ("opponent_factor", "venue_factor", "fixture_factor")
                if key in audit
            }
        }

    target_gw = payload["meta"]["gw"]
    scoring = bootstrap["game_config"]["scoring"]
    team_ids = {team["name"]: team["id"] for team in bootstrap["teams"]}
    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    attack_factor, defence_factor = recent_team_factors(list(team_names))
    fdr_priors, fdr_diagnostics = fdr_goal_priors(odds_payload["fixtures"], fixtures)
    payload["model_inputs"] = {
        "fdr_goal_priors": {
            f"{'home' if home else 'away'}_fdr{difficulty}": round(value, 5)
            for (home, difficulty), value in fdr_priors.items()
        },
        "fdr_calibration": fdr_diagnostics,
        "recent_attack_factors": {
            team_names[team]: round(value, 5) for team, value in attack_factor.items()
        },
        "recent_defence_factors": {
            team_names[team]: round(value, 5) for team, value in defence_factor.items()
        },
        "odds_snapshot": odds_payload,
    }
    exact_odds = {row["fixture_id"]: row for row in odds_payload["fixtures"]}
    players_by_id = {player["id"]: player for player in bootstrap["elements"]}
    fixture_lookup = {}
    for fixture in fixtures:
        if fixture.get("event") is None:
            continue
        fixture_lookup.setdefault((fixture["event"], fixture["team_h"]), []).append((fixture, True))
        fixture_lookup.setdefault((fixture["event"], fixture["team_a"]), []).append((fixture, False))

    for record in payload["players"].values():
        team_id = team_ids[record["team"]]
        gameweeks = []
        base_goal_lam = record["team_goal_lambda"] or 1
        for offset in range(horizon):
            gw = target_gw + offset
            matches = fixture_lookup.get((gw, team_id), [])
            if not matches:
                gameweeks.append({"gw": gw, "blank": True, "xP": 0.0, "source": "blank"})
                continue
            fixture_forecasts = []
            gw_components = {key: 0.0 for key in record["components"]}
            for fixture, home in matches:
                opponent_id = fixture["team_a"] if home else fixture["team_h"]
                odds = exact_odds.get(fixture["id"])
                if odds and (inferred := infer_goal_lambdas(odds)):
                    home_lam, away_lam, fit_error = inferred
                    team_lam, opponent_lam = (home_lam, away_lam) if home else (away_lam, home_lam)
                    source = "bookmaker"
                else:
                    difficulty = fixture["team_h_difficulty"] if home else fixture["team_a_difficulty"]
                    opponent_difficulty = fixture["team_a_difficulty"] if home else fixture["team_h_difficulty"]
                    team_lam = fdr_priors[(home, difficulty)] * math.sqrt(
                        attack_factor[team_id] * defence_factor[opponent_id]
                    )
                    opponent_lam = fdr_priors[(not home, opponent_difficulty)] * math.sqrt(
                        attack_factor[opponent_id] * defence_factor[team_id]
                    )
                    fit_error = None
                    source = "fdr_recent_xg_fallback"
                    team_bucket = fdr_diagnostics["venues"]["home" if home else "away"][f"fdr{difficulty}"]
                    opponent_bucket = fdr_diagnostics["venues"]["away" if home else "home"][f"fdr{opponent_difficulty}"]
                scale = team_lam / base_goal_lam
                components = dict(record["components"])
                components["goals"] = record["components"]["goals"] * scale
                components["assists"] = record["components"]["assists"] * scale
                components["clean_sheet"] = expected_clean_sheet_points(
                    scoring, record["position"], opponent_lam,
                    record["minutes_bands"]["p_60_plus"],
                )
                if record["position"] in {"GKP", "DEF"}:
                    exposure = opponent_lam * record["exp_minutes"] / 90
                    components["goals_conceded"] = -expected_goal_conceded_deduction(exposure)
                defcon_prediction = defcon.predict(
                    players_by_id[record["element"]], record["position"], record["team"],
                    team_names[opponent_id], home, target_gw,
                    record["defcon_minutes_input"], defcon_context,
                )
                if defcon_prediction["probability"] is not None:
                    components["defcon"] = (
                        scoring["defensive_contribution"][record["position"]]
                        * defcon_prediction["probability"]
                    )
                for key, value in components.items():
                    gw_components[key] += value
                fixture_forecasts.append({
                    "fixture_id": fixture["id"],
                    "opponent": team_names[opponent_id],
                    "home": home,
                    "source": source,
                    "team_goal_lambda": round(team_lam, 3),
                    "opponent_goal_lambda": round(opponent_lam, 3),
                    "goal_model_fit_error": round(fit_error, 6) if fit_error is not None else None,
                    "defcon_model": compact_defcon(defcon_prediction),
                    **({
                        "fdr_calibration": {
                            "team": team_bucket,
                            "opponent": opponent_bucket,
                            "sparse": team_bucket["sparse"] or opponent_bucket["sparse"],
                        }
                    } if source == "fdr_recent_xg_fallback" else {}),
                    "components": {key: round(value, 3) for key, value in components.items()},
                    "xP": round(sum(components.values()), 3),
                })
            gameweeks.append({
                "gw": gw,
                "blank": False,
                "fixtures": fixture_forecasts,
                "components": {key: round(value, 3) for key, value in gw_components.items()},
                "xP": round(sum(gw_components.values()), 3),
                "source": "+".join(sorted({row["source"] for row in fixture_forecasts})),
            })
        record["gameweeks"] = gameweeks
        record["horizon_xP"] = round(sum((HORIZON_DISCOUNT**i) * row["xP"] for i, row in enumerate(gameweeks)), 3)


def assign_calibration_weights(payload: dict, bootstrap: dict) -> None:
    """Freeze a broad decision set: owned plus top xP and value by position."""
    players = {player["id"]: player for player in bootstrap["elements"]}
    entry = load(DATA_DIR / "entry.json")
    picks_path = DATA_DIR / f"picks_gw{entry['current_event']}.json"
    owned = {pick["element"] for pick in load(picks_path)["picks"]} if picks_path.exists() else set()
    contenders = set(owned)
    records = list(payload["players"].values())
    for position in {row["position"] for row in records}:
        eligible = [row for row in records if row["position"] == position and row["exp_minutes"] >= 45]
        contenders.update(row["element"] for row in sorted(eligible, key=lambda row: -row["horizon_xP"])[:10])
        contenders.update(row["element"] for row in sorted(
            eligible, key=lambda row: -(row["horizon_xP"] / players[row["element"]]["now_cost"])
        )[:10])
    for record in records:
        reasons = []
        if record["element"] in owned:
            reasons.append("owned")
        if record["element"] in contenders and record["element"] not in owned:
            reasons.append("six-week xP/value contender")
        record["calibration_weight"] = 1.0 if reasons else 0.0
        record["calibration_reasons"] = reasons or ["diagnostic only"]
        record["selected_by_percent"] = players[record["element"]]["selected_by_percent"]
    payload["meta"]["calibration_players"] = sum(row["calibration_weight"] > 0 for row in records)
    payload["meta"]["ownership_policy"] = "display only; excluded from forecasts, candidates and weights"


def build(show: int = 0, horizon: int = DEFAULT_HORIZON) -> dict:
    bootstrap = load(DATA_DIR / "bootstrap.json")
    config = load(ROOT / "config.json")
    scoring = bootstrap["game_config"]["scoring"]
    target = next((event for event in bootstrap["events"] if event.get("is_next")), None)
    if not target:
        raise SystemExit("no next gameweek in bootstrap.json")
    target_gw = target["id"]

    minute_payload = minutes.build()
    if minute_payload["meta"]["gw"] != target_gw:
        raise SystemExit("minutes model and projection target gameweeks disagree")

    odds_payload = load(DATA_DIR / "odds.json")
    gameweek_odds = [row for row in odds_payload["fixtures"] if row["event"] == target_gw]
    if len(gameweek_odds) != 10:
        raise SystemExit(f"GW{target_gw} has odds for {len(gameweek_odds)}/10 fixtures — refusing partial rankings")

    players = bootstrap["elements"]
    defcon_context = defcon.load_context(bootstrap, config["season"])
    types = {row["id"]: row["singular_name_short"] for row in bootstrap["element_types"]}
    priors = build_priors(players, types, target_gw)
    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    lambdas = {}
    for row in gameweek_odds:
        inferred = infer_goal_lambdas(row)
        if inferred is None:
            raise SystemExit(f"fixture {row['fixture_id']} lacks usable 2.5-goal odds")
        home_lam, away_lam, fit_error = inferred
        lambdas[row["home_team"]] = (home_lam, away_lam, fit_error, row)
        lambdas[row["away_team"]] = (away_lam, home_lam, fit_error, row)

    minute_rows = minute_payload["players"]
    weights = {}
    for player in players:
        mins = minute_rows.get(str(player["id"]))
        if not mins or player["element_type"] == 1:
            continue
        position = types[player["element_type"]]
        xg_rate, xg_audit = blended_per_90(
            player, target_gw, priors[position], "expected_goals"
        )
        xa_rate, xa_audit = blended_per_90(
            player, target_gw, priors[position], "expected_assists"
        )
        weights[player["id"]] = {
            "goal": xg_rate * mins["exp_minutes"] / 90,
            "assist": xa_rate * mins["exp_minutes"] / 90,
            "prior_audit": {"expected_goals": xg_audit, "expected_assists": xa_audit},
        }

    team_weight_totals = {}
    for player in players:
        if player["id"] not in weights:
            continue
        totals = team_weight_totals.setdefault(player["team"], {"goal": 0.0, "assist": 0.0})
        totals["goal"] += weights[player["id"]]["goal"]
        totals["assist"] += weights[player["id"]]["assist"]

    season_goals = sum(player.get("goals_scored", 0) for player in players)
    season_assists = sum(player.get("assists", 0) for player in players)
    assisted_goal_rate = min(max(season_assists / season_goals if season_goals else 0.7, 0.5), 0.9)

    records = {}
    for player in players:
        mins = minute_rows.get(str(player["id"]))
        team = team_names[player["team"]]
        if not mins or team not in lambdas or mins["insufficient_evidence"]:
            continue
        position = types[player["element_type"]]
        team_lam, opponent_lam, fit_error, fixture = lambdas[team]
        totals = team_weight_totals.get(player["team"], {})
        goal_weight = weights.get(player["id"], {}).get("goal", 0)
        assist_weight = weights.get(player["id"], {}).get("assist", 0)
        goal_share = goal_weight / totals.get("goal", 1) if totals.get("goal") else 0
        assist_share = assist_weight / totals.get("assist", 1) if totals.get("assist") else 0
        exp_goals = team_lam * goal_share
        exp_assists = team_lam * assisted_goal_rate * assist_share
        p_play = 1 - mins["bands"]["p_zero"]
        p_60 = mins["bands"]["p_60_plus"]

        components = {
            "appearance": mins["bands"]["p_1_59"] + 2 * p_60,
            "goals": scoring["goals_scored"][position] * exp_goals,
            "assists": scoring["assists"] * exp_assists,
            "clean_sheet": expected_clean_sheet_points(
                scoring, position, opponent_lam, p_60
            ),
            "goals_conceded": 0.0,
        }
        if position in {"GKP", "DEF"}:
            exposure_lam = opponent_lam * mins["exp_minutes"] / 90
            components["goals_conceded"] = -expected_goal_conceded_deduction(exposure_lam)
        hist = historical_components(
            player, position, target_gw, priors[position], p_play,
            mins["exp_minutes"], scoring["defensive_contribution"][position],
        )
        components.update({key: hist[key] for key in ("yellow", "red", "defcon", "bonus", "saves")})
        defcon_minutes_input = {
            "source": mins["source"],
            "role_states": mins.get("role_states"),
            "conditional_minutes_by_state": mins.get("conditional_minutes_by_state"),
            "exp_minutes": mins["exp_minutes"],
            "chance_of_playing_next_round": mins.get("chance_of_playing_next_round"),
        }
        defcon_prediction = defcon.predict(
            player, position, team,
            fixture["away_team"] if team == fixture["home_team"] else fixture["home_team"],
            team == fixture["home_team"], target_gw, defcon_minutes_input, defcon_context,
        )
        if defcon_prediction["probability"] is not None:
            components["defcon"] = (
                scoring["defensive_contribution"][position]
                * defcon_prediction["probability"]
            )
            hist["prior_audit"]["defcon"] = "trained threshold model; see defcon_model audit"
        rounded = {key: round(value, 3) for key, value in components.items()}
        records[str(player["id"])] = {
            "element": player["id"],
            "web_name": player["web_name"],
            "team": team,
            "position": position,
            "fixture_id": fixture["fixture_id"],
            "opponent": fixture["away_team"] if team == fixture["home_team"] else fixture["home_team"],
            "home": team == fixture["home_team"],
            "exp_minutes": mins["exp_minutes"],
            "minutes_bands": mins["bands"],
            "minutes_source": mins["source"],
            "defcon_minutes_input": defcon_minutes_input,
            "status": mins["status"],
            "now_cost": player["now_cost"],
            "expected_goals": round(exp_goals, 3),
            "expected_assists": round(exp_assists, 3),
            "attacking_inputs": {
                "shrunk_xg_per_90": round(goal_weight * 90 / mins["exp_minutes"], 4) if mins["exp_minutes"] else 0,
                "shrunk_xa_per_90": round(assist_weight * 90 / mins["exp_minutes"], 4) if mins["exp_minutes"] else 0,
                "team_goal_share": round(goal_share, 5),
                "team_assist_share": round(assist_share, 5),
                "prior_audit": weights.get(player["id"], {}).get("prior_audit"),
            },
            "team_goal_lambda": round(team_lam, 3),
            "opponent_goal_lambda": round(opponent_lam, 3),
            "goal_model_fit_error": round(fit_error, 6),
            "odds_bookmakers": {
                "h2h": fixture["h2h_bookmakers"],
                "over_under_2_5": fixture["totals_bookmakers"],
            },
            "components": rounded,
            "xP": round(sum(components.values()), 3),
            "history_appearances": hist["history_appearances"],
            "component_prior_audit": hist["prior_audit"],
            "defcon_model": defcon_prediction,
            "previous_season_actuals": previous_season_snapshot(
                previous_season_for(player["id"])
            ),
            "limitations": [
                "bonus is shrunk current-season history",
                "rare penalty/own-goal events not modeled",
                "player props not yet calibrated",
                *(["under 3 bookmakers supplied the exact 2.5-goal line"] if fixture["totals_bookmakers"] < 3 else []),
            ],
        }

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_version": MODEL_VERSION,
            "season": config["season"],
            "gw": target_gw,
            "players": len(records),
            "assisted_goal_rate": round(assisted_goal_rate, 4),
            "player_prior_minutes": PLAYER_PRIOR_MINUTES,
            "position_prior_minutes": POSITION_PRIOR_MINUTES,
            "prior_policy": (
                "latest official history_past rate shrunk 450 minutes toward position; "
                "then weighted as 900 minutes against completed current-season evidence"
            ),
            "history_policy": "fixture finished or finished_provisional",
            "goal_model": "independent Poisson fitted to de-vigged 1X2 and O/U 2.5",
            "unmodeled": ["penalty saves", "penalty misses", "own goals"],
            "horizon": horizon,
            "horizon_discount": HORIZON_DISCOUNT,
            "form_prior_matches": FORM_PRIOR_MATCHES,
            "prior_strength": PRIOR_STRENGTH,
            "defcon_model": (
                defcon_context["model"]["model_version"] if defcon_context else None
            ),
            "defcon_model_sha256": (
                defcon_context["model"]["_artifact_sha256"] if defcon_context else None
            ),
            "defcon_current_finalized_rows": (
                defcon_context["current_rows"] if defcon_context else 0
            ),
            "defcon_model_limits": (
                defcon_context["model"]["known_limits"] if defcon_context else [
                    "trained DefCon model unavailable; corrected current-season hit-rate fallback used"
                ]
            ),
        },
        "priors": priors,
        "players": records,
    }
    fixtures = load(DATA_DIR / "fixtures.json")
    extend_horizon(payload, bootstrap, fixtures, odds_payload, horizon, defcon_context)
    assign_calibration_weights(payload, bootstrap)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(records)} players, GW{target_gw}")
    sparse = payload["model_inputs"]["fdr_calibration"]["sparse_buckets"]
    total_sides = payload["model_inputs"]["fdr_calibration"]["total_market_team_sides"]
    if sparse:
        print(f"  FDR fallback: {sparse}/10 sparse venue/FDR buckets from {total_sides} market team-sides")
    if show:
        ranked = sorted(records.values(), key=lambda row: -row["horizon_xP"])[:show]
        print(f"\n{'player':<18}{'pos':<5}{'opp':<18}{'mins':>6}{'GW+1':>7}{'horizon':>10}")
        for row in ranked:
            venue = "(H)" if row["home"] else "(A)"
            print(f"{row['web_name']:<18}{row['position']:<5}{(row['opponent'] + ' ' + venue):<18}{row['exp_minutes']:>6.0f}{row['xP']:>7.2f}{row['horizon_xP']:>10.2f}")
    return payload


def archive(payload: dict) -> None:
    path = ARCHIVE_DIR / f"gw{payload['meta']['gw']:02d}.json"
    display_path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    if path.exists():
        print(f"{display_path} already exists — not overwriting")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(json.dumps(payload))
    frozen["meta"]["archive_policy"] = (
        "full inputs for calibration-weighted players; minimal horizon xP for diagnostic-only players"
    )
    for element, record in list(frozen["players"].items()):
        if record["calibration_weight"] == 0:
            frozen["players"][element] = {
                "element": record["element"],
                "web_name": record["web_name"],
                "team": record["team"],
                "position": record["position"],
                "xP": record["xP"],
                "horizon_xP": record["horizon_xP"],
                "gameweeks": [{"gw": row["gw"], "xP": row["xP"]} for row in record["gameweeks"]],
                "calibration_weight": 0.0,
                "calibration_reasons": record["calibration_reasons"],
            }
        frozen["players"][element]["actual_points"] = None
    path.write_text(json.dumps(frozen, separators=(",", ":")) + "\n")
    print(f"froze {len(payload['players'])} projections to {display_path}")


def resolve(gw: int) -> None:
    path = ARCHIVE_DIR / f"gw{gw:02d}.json"
    if not path.exists():
        raise SystemExit(f"no archived projections for GW{gw}")
    payload = load(path)
    rows = list(payload["players"].values())
    resolved = []
    for row in rows:
        played = [item for item in history_for(row["element"], gw + 1) if item["round"] == gw]
        if played:
            row["actual_points"] = sum(item["total_points"] for item in played)
            resolved.append(row)
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    if resolved:
        mae = sum(abs(row["actual_points"] - row["xP"]) for row in resolved) / len(resolved)
        calibrated = [row for row in resolved if row["calibration_weight"] > 0]
        weighted_mae = (
            sum(abs(row["actual_points"] - row["xP"]) * row["calibration_weight"] for row in calibrated)
            / sum(row["calibration_weight"] for row in calibrated)
            if calibrated else None
        )
        print(f"GW{gw}: resolved {len(resolved)}/{len(rows)}")
        print(f"  all-player diagnostic MAE       {mae:.2f} points")
        if weighted_mae is not None:
            print(f"  decision-weighted primary MAE   {weighted_mae:.2f} points ({len(calibrated)} players)")
    else:
        print(f"GW{gw}: nothing resolved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", type=int, default=0)
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("archive")
    resolver = sub.add_parser("resolve")
    resolver.add_argument("--gw", type=int, required=True)
    args = parser.parse_args()
    if args.command == "resolve":
        resolve(args.gw)
        return
    if not 1 <= args.horizon <= 10:
        raise SystemExit("--horizon must be between 1 and 10")
    payload = build(show=args.show, horizon=args.horizon)
    if args.command == "archive":
        archive(payload)


if __name__ == "__main__":
    main()
