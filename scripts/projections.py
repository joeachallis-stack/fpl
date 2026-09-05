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
from pathlib import Path

import minutes

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "projections.json"
ARCHIVE_DIR = ROOT / "projections"
MODEL_VERSION = "baseline-v1"
PRIOR_STRENGTH = 5.0
RARE_PRIOR_STRENGTH = 20.0
ATTACK_PRIOR_MINUTES = 180.0
DEFAULT_HORIZON = 6
HORIZON_DISCOUNT = 0.85
FORM_PRIOR_MATCHES = 5.0


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


def history_for(player_id: int, target_gw: int) -> list[dict]:
    path = DATA_DIR / f"element_summary/{player_id}.json"
    if not path.exists():
        return []
    return [row for row in load(path)["history"] if row["round"] < target_gw]


def defensive_actions(row: dict, position: str) -> int:
    actions = row.get("tackles", 0) + row.get("clearances_blocks_interceptions", 0)
    if position in {"MID", "FWD"}:
        actions += row.get("recoveries", 0)
    return actions


def build_priors(players: list[dict], types: dict[int, str], target_gw: int) -> dict:
    buckets = {
        position: {"plays": 0, "minutes": 0, "xg": 0.0, "xa": 0.0, "yellow": 0,
                   "red": 0, "defcon": 0, "bonus": 0.0, "save_points": 0.0}
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
            bucket["save_points"] += row.get("saves", 0) // 3
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
            "save_points": bucket["save_points"] / plays,
            "xg_per_90": bucket["xg"] * 90 / (bucket["minutes"] or 1),
            "xa_per_90": bucket["xa"] * 90 / (bucket["minutes"] or 1),
            "sample": bucket["plays"],
        }
    return priors


def shrunk_rate(successes: float, n: int, prior: float, strength: float = PRIOR_STRENGTH) -> float:
    return (successes + prior * strength) / (n + strength)


def attacking_rate(player: dict, position: str, target_gw: int, prior: dict, stat: str) -> float:
    """Per-90 xG/xA shrunk by minutes, so two hot games cannot own a team forecast."""
    rows = history_for(player["id"], target_gw)
    played_minutes = sum(row["minutes"] for row in rows)
    history_field = {"xg": "expected_goals", "xa": "expected_assists"}[stat]
    observed = sum(float(row.get(history_field) or 0) for row in rows)
    prior_rate = prior[f"{stat}_per_90"]
    return (observed * 90 + prior_rate * ATTACK_PRIOR_MINUTES) / (
        played_minutes + ATTACK_PRIOR_MINUTES
    )


def historical_components(player: dict, position: str, target_gw: int, prior: dict, p_play: float, p_60: float) -> dict:
    rows = [row for row in history_for(player["id"], target_gw) if row["minutes"] > 0]
    n = len(rows)
    threshold = 10 if position == "DEF" else 12
    yellow = shrunk_rate(sum(bool(r.get("yellow_cards")) for r in rows), n, prior["yellow"])
    red = shrunk_rate(sum(bool(r.get("red_cards")) for r in rows), n, prior["red"], RARE_PRIOR_STRENGTH)
    bonus = shrunk_rate(sum(r.get("bonus", 0) for r in rows), n, prior["bonus"])
    defcon_hits = sum(defensive_actions(r, position) >= threshold for r in rows) if position != "GKP" else 0
    defcon = shrunk_rate(defcon_hits, n, prior["defcon"]) if position != "GKP" else 0
    save_points = shrunk_rate(sum(r.get("saves", 0) // 3 for r in rows), n, prior["save_points"])
    return {
        "yellow": -yellow * p_play,
        "red": -3 * red * p_play,
        "defcon": 2 * defcon * p_60,
        "bonus": bonus * p_play,
        "saves": save_points * p_play if position == "GKP" else 0.0,
        "history_appearances": n,
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


def fdr_goal_priors(odds_rows: list[dict], fixtures: list[dict]) -> dict[tuple[bool, int], float]:
    """Calibrate venue/FDR goal-rate buckets from the current bookmaker market."""
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
    for home in (False, True):
        for difficulty in range(1, 6):
            values = buckets.get((home, difficulty), [])
            priors[(home, difficulty)] = (sum(values) + 3 * global_rate) / (len(values) + 3)
    return priors


def extend_horizon(payload: dict, bootstrap: dict, fixtures: list[dict], odds_payload: dict, horizon: int) -> None:
    target_gw = payload["meta"]["gw"]
    scoring = bootstrap["game_config"]["scoring"]
    team_ids = {team["name"]: team["id"] for team in bootstrap["teams"]}
    team_names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    attack_factor, defence_factor = recent_team_factors(list(team_names))
    fdr_priors = fdr_goal_priors(odds_payload["fixtures"], fixtures)
    payload["model_inputs"] = {
        "fdr_goal_priors": {
            f"{'home' if home else 'away'}_fdr{difficulty}": round(value, 5)
            for (home, difficulty), value in fdr_priors.items()
        },
        "recent_attack_factors": {
            team_names[team]: round(value, 5) for team, value in attack_factor.items()
        },
        "recent_defence_factors": {
            team_names[team]: round(value, 5) for team, value in defence_factor.items()
        },
        "odds_snapshot": odds_payload,
    }
    exact_odds = {row["fixture_id"]: row for row in odds_payload["fixtures"]}
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
                scale = team_lam / base_goal_lam
                components = dict(record["components"])
                components["goals"] = record["components"]["goals"] * scale
                components["assists"] = record["components"]["assists"] * scale
                components["clean_sheet"] = (
                    scoring["clean_sheets"][record["position"]]
                    * math.exp(-opponent_lam)
                    * record["minutes_bands"]["p_60_plus"]
                )
                if record["position"] in {"GKP", "DEF"}:
                    exposure = opponent_lam * record["exp_minutes"] / 90
                    components["goals_conceded"] = -expected_goal_conceded_deduction(exposure)
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
        weights[player["id"]] = {
            "goal": attacking_rate(player, position, target_gw, priors[position], "xg")
            * mins["exp_minutes"] / 90,
            "assist": attacking_rate(player, position, target_gw, priors[position], "xa")
            * mins["exp_minutes"] / 90,
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
            "clean_sheet": scoring["clean_sheets"][position] * math.exp(-opponent_lam) * p_60,
            "goals_conceded": 0.0,
        }
        if position in {"GKP", "DEF"}:
            exposure_lam = opponent_lam * mins["exp_minutes"] / 90
            components["goals_conceded"] = -expected_goal_conceded_deduction(exposure_lam)
        hist = historical_components(player, position, target_gw, priors[position], p_play, p_60)
        components.update({key: hist[key] for key in ("yellow", "red", "defcon", "bonus", "saves")})
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
            "status": mins["status"],
            "now_cost": player["now_cost"],
            "expected_goals": round(exp_goals, 3),
            "expected_assists": round(exp_assists, 3),
            "attacking_inputs": {
                "shrunk_xg_per_90": round(goal_weight * 90 / mins["exp_minutes"], 4) if mins["exp_minutes"] else 0,
                "shrunk_xa_per_90": round(assist_weight * 90 / mins["exp_minutes"], 4) if mins["exp_minutes"] else 0,
                "team_goal_share": round(goal_share, 5),
                "team_assist_share": round(assist_share, 5),
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
            "attack_prior_minutes": ATTACK_PRIOR_MINUTES,
            "goal_model": "independent Poisson fitted to de-vigged 1X2 and O/U 2.5",
            "unmodeled": ["penalty saves", "penalty misses", "own goals"],
            "horizon": horizon,
            "horizon_discount": HORIZON_DISCOUNT,
            "form_prior_matches": FORM_PRIOR_MATCHES,
            "prior_strength": PRIOR_STRENGTH,
            "rare_prior_strength": RARE_PRIOR_STRENGTH,
        },
        "priors": priors,
        "players": records,
    }
    fixtures = load(DATA_DIR / "fixtures.json")
    extend_horizon(payload, bootstrap, fixtures, odds_payload, horizon)
    assign_calibration_weights(payload, bootstrap)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(records)} players, GW{target_gw}")
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
