"""Team attack/defence ratings, fitted to results and anchored to bookmaker odds.

Why this exists: the FDR fallback that covers gameweeks beyond the odds horizon collapses
twenty teams into four tiers, then estimates those tiers from ~30 market observations.
Across the GW4-9 horizon, FPL's difficulty is very nearly a per-team constant — six clubs
sit at exactly 3.00 with zero variance — so the fallback cannot tell Tottenham from
Everton, and no amount of information about one team can reach that team's later fixture.

Ratings fix the structural problem rather than the sample size. Each team gets a
continuous attack and defence rating, so a single fixture constrains both teams at once
and a team's rating applies to every fixture it plays. That is what carries the market's
one-week-ahead view out to week five: bookmakers have already priced a managerial change
or a form swing, and anchoring ratings to odds propagates it to fixtures nobody prices.

Model, standard independent Poisson with home advantage:

    log lambda_home = mu + home_advantage + attack[home] - defence[away]
    log lambda_away = mu + attack[away] - defence[home]

Ratings are fitted by weighted maximum likelihood. Weights decay exponentially with match
age, so a May match counts for more than the previous August without a hard season
boundary — "weight 2025/26 over 2024/25" is then an outcome of the fitted half-life
rather than a hand-set knob. An L2 penalty toward a per-team prior mean supplies both
identifiability and shrinkage; promoted sides with no top-flight history are pulled
toward a promoted-team prior instead of toward league average.

Every constant here is a starting assumption to be selected walk-forward by
train_ratings.py, not a claim.
"""
from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Starting assumptions; train_ratings.py selects these walk-forward.
DEFAULT_HALF_LIFE_DAYS = 180.0
DEFAULT_PRIOR_STRENGTH = 8.0
# Promoted sides in 2025/26 (Burnley, Leeds, Sunderland) scored 0.73-0.94x and conceded
# 0.92-1.44x league average. This prior is motivated a priori, NOT selected by evidence:
# train_ratings.py's paired ablation cannot distinguish it from simply using league
# average (pooled t = +0.80 over 639 promoted-team forecasts, sign flips between
# buckets). It is kept only because at genuine zero history the alternative is to call a
# promoted side exactly league average, which is known to be wrong before a ball is
# kicked. That is a reason for a mild prior, not a strong one — do not raise it without
# evidence, and re-run the ablation once more promoted-team seasons are cached.
PROMOTED_ATTACK_PRIOR = math.log(0.82)
PROMOTED_DEFENCE_PRIOR = -math.log(1.14)

# How many matches of history one bookmaker-priced fixture is worth when learning team
# strength. NOT FITTED — historical odds do not exist, so this cannot yet be selected
# against real market lines. It is set instead from the bracket in train_ratings.py, and
# the bracket is the important part: the sign of this feature depends on how noisy the
# anchor is.
#
#   - Anchored on realized xG (one draw from lambda, so noisier than a real price),
#     anchoring HURTS and worsens with weight: t = -0.05 at weight 2, +1.78 at 6,
#     +5.18 at 20. Injecting single-match noise into a rating built on 20+ matches is
#     actively damaging.
#   - Anchored on a full-season model lambda (pure team strength, no fixture noise, no
#     market achieves this), anchoring HELPS at every weight: t = -5.98, -6.11, -6.32.
#
# A real bookmaker line sits between those two, and nothing in the cached data says
# where. Weight 2 is chosen as the largest value that is still non-harmful under the
# pessimistic bound, so the feature cannot cost anything much while it is unproven.
#
# Note the ceiling is small either way. The best case is ~0.003 NLL, against the 0.023
# already banked by replacing the FDR fallback with ratings at all. This is a refinement,
# not another step change — do not spend heavily on it.
#
# odds/ is now accumulating the archive needed to fit this against real prices.
ODDS_MATCH_EQUIVALENT = 2.0


def decayed_weight(kickoff: datetime, asof: datetime, half_life_days: float) -> float:
    age_days = max((asof - kickoff).total_seconds() / 86400, 0.0)
    return 0.5 ** (age_days / half_life_days)


def team_match_rows(path: Path) -> list[dict]:
    """One row per team-side of a finished match: goals for, team xG, venue, kickoff.

    Player expected_goals sums to team xG closely enough to use as a low-variance target
    (2025/26: 1.551 home xG against 1.526 actual home goals).
    """
    with path.open() as handle:
        player_rows = list(csv.DictReader(handle))

    sides: dict[tuple[int, bool], dict] = defaultdict(lambda: {"xg": 0.0})
    scores: dict[int, tuple[int, int]] = {}
    for row in player_rows:
        fixture = int(row["fixture"])
        home = row["was_home"].strip().lower() == "true"
        side = sides[(fixture, home)]
        side["xg"] += float(row["expected_goals"] or 0)
        side["team"] = row["team"]
        side["kickoff"] = row["kickoff_time"]
        side["round"] = int(row["round"])
        scores[fixture] = (int(row["team_h_score"] or 0), int(row["team_a_score"] or 0))

    rows = []
    for (fixture, home), side in sides.items():
        opponent = sides.get((fixture, not home))
        if not opponent or fixture not in scores:
            continue
        home_goals, away_goals = scores[fixture]
        rows.append({
            "fixture": fixture,
            "team": side["team"],
            "opponent": opponent["team"],
            "home": home,
            "round": side["round"],
            "goals": home_goals if home else away_goals,
            "xg": side["xg"],
            "kickoff": datetime.fromisoformat(side["kickoff"].replace("Z", "+00:00")),
        })
    return sorted(rows, key=lambda row: (row["kickoff"], row["fixture"], not row["home"]))


def fit(
    rows: list[dict],
    asof: datetime,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    prior_strength: float = DEFAULT_PRIOR_STRENGTH,
    target: str = "goals",
    promoted: set[str] | None = None,
    odds_rows: list[dict] | None = None,
    odds_weight: float = ODDS_MATCH_EQUIVALENT,
) -> dict:
    """Weighted Poisson MLE for attack, defence, home advantage and a base rate.

    `target` selects goals or team xG. xG carries less noise per match but is itself a
    model output; which one predicts better is left to walk-forward selection.

    `odds_rows` anchors the fit to the market. Each priced fixture contributes two
    observations whose "goals" is the bookmaker-implied lambda, carrying `odds_weight`
    matches of weight. Because ratings are per team rather than per fixture, a price on
    one fixture moves that team's rating and therefore every other fixture it plays —
    which is the entire point. It is how the market's one-week-ahead view of a side,
    including a managerial change the results have not caught up with, reaches a fixture
    five weeks out that nobody prices.

    Only fixtures at or after `asof` are anchored: a priced fixture already played has a
    result, and the result is the better observation.
    """
    rows = [row for row in rows if row["kickoff"] <= asof]
    if not rows:
        raise ValueError("no matches on or before asof")
    teams = sorted({row["team"] for row in rows} | {row["opponent"] for row in rows})
    teams = list(teams)
    index = {team: position for position, team in enumerate(teams)}
    n_teams = len(teams)
    promoted = promoted or set()

    attack_prior = np.array(
        [PROMOTED_ATTACK_PRIOR if team in promoted else 0.0 for team in teams]
    )
    defence_prior = np.array(
        [PROMOTED_DEFENCE_PRIOR if team in promoted else 0.0 for team in teams]
    )

    anchors = [row for row in (odds_rows or []) if row["kickoff"] >= asof] if odds_weight else []
    for anchor in anchors:
        for team in (anchor["team"], anchor["opponent"]):
            if team not in index:
                index[team] = len(teams)
                teams.append(team)
    n_teams = len(teams)
    if len(attack_prior) != n_teams:
        attack_prior = np.array(
            [PROMOTED_ATTACK_PRIOR if team in promoted else 0.0 for team in teams]
        )
        defence_prior = np.array(
            [PROMOTED_DEFENCE_PRIOR if team in promoted else 0.0 for team in teams]
        )

    observations = rows + anchors
    team_ix = np.array([index[row["team"]] for row in observations])
    opp_ix = np.array([index[row["opponent"]] for row in observations])
    is_home = np.array([1.0 if row["home"] else 0.0 for row in observations])
    observed = np.array(
        [float(row["goals" if target == "goals" else "xg"]) for row in rows]
        + [float(row["lambda"]) for row in anchors]
    )
    weights = np.array(
        [decayed_weight(row["kickoff"], asof, half_life_days) for row in rows]
        + [odds_weight] * len(anchors)
    )

    def unpack(params: np.ndarray):
        return params[0], params[1], params[2:2 + n_teams], params[2 + n_teams:]

    def objective(params: np.ndarray) -> float:
        mu, home_adv, attack, defence = unpack(params)
        log_lambda = mu + home_adv * is_home + attack[team_ix] - defence[opp_ix]
        lam = np.exp(np.clip(log_lambda, -20, 20))
        nll = np.sum(weights * (lam - observed * log_lambda))
        penalty = prior_strength * (
            np.sum((attack - attack_prior) ** 2) + np.sum((defence - defence_prior) ** 2)
        )
        return nll + penalty

    def gradient(params: np.ndarray) -> np.ndarray:
        mu, home_adv, attack, defence = unpack(params)
        log_lambda = mu + home_adv * is_home + attack[team_ix] - defence[opp_ix]
        lam = np.exp(np.clip(log_lambda, -20, 20))
        residual = weights * (lam - observed)
        grad = np.zeros_like(params)
        grad[0] = np.sum(residual)
        grad[1] = np.sum(residual * is_home)
        np.add.at(grad, 2 + team_ix, residual)
        np.add.at(grad, 2 + n_teams + opp_ix, -residual)
        grad[2:2 + n_teams] += 2 * prior_strength * (attack - attack_prior)
        grad[2 + n_teams:] += 2 * prior_strength * (defence - defence_prior)
        return grad

    # Decay-weighted matches behind each team's rating. A promoted side carries far less
    # than an established one, and that difference should be visible downstream rather
    # than hidden behind a rating that looks as firm as Arsenal's.
    effective_by_team = {team: 0.0 for team in teams}
    for row, weight in zip(rows, weights[:len(rows)]):
        effective_by_team[row["team"]] += float(weight)

    start = np.concatenate([[math.log(max(observed.mean(), 0.1)), 0.1], attack_prior, defence_prior])
    result = minimize(objective, start, jac=gradient, method="L-BFGS-B")
    mu, home_adv, attack, defence = unpack(result.x)
    return {
        "mu": float(mu),
        "home_advantage": float(home_adv),
        "attack": {team: float(attack[index[team]]) for team in teams},
        "defence": {team: float(defence[index[team]]) for team in teams},
        "teams": teams,
        "asof": asof.isoformat(),
        "target": target,
        "half_life_days": half_life_days,
        "prior_strength": prior_strength,
        "matches": len(rows),
        "anchored_fixtures": len(anchors),
        "odds_weight": float(odds_weight) if anchors else 0.0,
        "effective_matches": float(weights.sum()),
        "effective_matches_by_team": effective_by_team,
        "promoted": sorted(promoted),
        "converged": bool(result.success),
    }


def expected_goals(model: dict, home_team: str, away_team: str) -> tuple[float, float]:
    """Expected goals for a fixture. Unknown teams fall back to the promoted prior."""
    attack, defence = model["attack"], model["defence"]
    promoted_attack = PROMOTED_ATTACK_PRIOR
    promoted_defence = PROMOTED_DEFENCE_PRIOR
    home_attack = attack.get(home_team, promoted_attack)
    away_attack = attack.get(away_team, promoted_attack)
    home_defence = defence.get(home_team, promoted_defence)
    away_defence = defence.get(away_team, promoted_defence)
    home_lambda = math.exp(model["mu"] + model["home_advantage"] + home_attack - away_defence)
    away_lambda = math.exp(model["mu"] + away_attack - home_defence)
    return home_lambda, away_lambda


def table(model: dict) -> list[dict]:
    """Ratings as multiplicative factors, which read more naturally than log space."""
    return sorted(
        (
            {
                "team": team,
                "attack": math.exp(model["attack"][team]),
                "defence": math.exp(-model["defence"][team]),
                "effective_matches": model["effective_matches_by_team"].get(team, 0.0),
            }
            for team in model["teams"]
        ),
        key=lambda row: -row["attack"] / row["defence"],
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default="2025-26")
    parser.add_argument("--half-life", type=float, default=DEFAULT_HALF_LIFE_DAYS)
    parser.add_argument("--prior-strength", type=float, default=DEFAULT_PRIOR_STRENGTH)
    parser.add_argument("--target", choices=("goals", "xg"), default="goals")
    args = parser.parse_args()

    rows = team_match_rows(DATA_DIR / f"{args.season}_merged_gw.csv")
    asof = max(row["kickoff"] for row in rows)
    model = fit(
        rows, asof,
        half_life_days=args.half_life,
        prior_strength=args.prior_strength,
        target=args.target,
    )
    print(
        f"{args.season}: {model['matches']} team-matches, "
        f"{model['effective_matches']:.1f} effective, "
        f"home advantage {math.exp(model['home_advantage']):.3f}x"
    )
    print(f"{'team':18s} {'attack':>7s} {'defence':>8s} {'eff.matches':>12s}")
    for row in table(model):
        thin = "  thin" if row["effective_matches"] < 10 else ""
        print(f"{row['team']:18s} {row['attack']:7.3f} {row['defence']:8.3f} "
              f"{row['effective_matches']:12.1f}{thin}")


if __name__ == "__main__":
    main()
