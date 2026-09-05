"""Walk-forward selection for team ratings, against the FDR-bucket incumbent.

The question is narrow: beyond the bookmaker horizon, does a continuous attack/defence
rating predict team goals better than the tier-plus-recent-form fallback now in
projections.py? Nothing is adopted here — this only produces the evidence.

Design notes that matter for reading the result:

- The incumbent is replicated in its exact production form,
  `fdr_prior[venue, difficulty] * sqrt(attack_factor[team] * defence_factor[opponent])`,
  with the same FORM_PRIOR_MATCHES and bucket-shrinkage constants.
- Historical FDR does not exist in the data, so difficulty is proxied by ranking teams
  into five tiers on goal difference known before the cutoff. This is *generous* to the
  incumbent: a tier that updates every week is strictly better information than FPL's
  effectively static preseason FDR, which over the live GW4-9 horizon assigns six clubs
  an identical 3.00. Read any ratings win as a lower bound on the real gap.
- The incumbent's bucket rates are calibrated on actual historical goals rather than
  bookmaker odds, because historical odds do not exist. Also generous to the incumbent.
- 2024/25 is prehistory only. All scoring happens on 2025/26, walking forward, with a
  strict information cutoff at the start of the gameweek the forecast is made from.
- Lead L means "forecast made before round c, scored on round c + L - 1", matching how
  projections.py forecasts a six-gameweek horizon from one deadline.

Primary metric is Poisson negative log-likelihood on actual goals, which is proper for
counts. MAE and RMSE are reported as diagnostics, not selection criteria.

Usage:
    python scripts/train_ratings.py
    python scripts/train_ratings.py --quick
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import ratings

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODELS_DIR = ROOT / "models"
OUT_PATH = MODELS_DIR / "ratings_params.json"

# Mirrored from projections.py so the incumbent is not weakened by a different constant.
FORM_PRIOR_MATCHES = 5.0
FDR_BUCKET_PRIOR_SIDES = 3
RECENT_WINDOW = 5
MAX_LEAD = 6

HALF_LIVES = (30.0, 60.0, 120.0, 180.0, 365.0, 540.0, 730.0, 3650.0)
PRIOR_STRENGTHS = (2.0, 4.0, 8.0, 16.0, 32.0)
TARGETS = ("goals", "xg")


def poisson_nll(lam: float, observed: float) -> float:
    lam = max(lam, 1e-6)
    return lam - observed * math.log(lam) + math.lgamma(observed + 1)


def score(predictions: list[tuple[float, float]]) -> dict:
    if not predictions:
        return {"n": 0, "nll": None, "mae": None, "rmse": None, "bias": None}
    nll = statistics.mean(poisson_nll(lam, obs) for lam, obs in predictions)
    mae = statistics.mean(abs(lam - obs) for lam, obs in predictions)
    rmse = math.sqrt(statistics.mean((lam - obs) ** 2 for lam, obs in predictions))
    bias = statistics.mean(lam - obs for lam, obs in predictions)
    return {
        "n": len(predictions),
        "nll": round(nll, 5),
        "mae": round(mae, 5),
        "rmse": round(rmse, 5),
        "bias": round(bias, 5),
    }


def isotonic_decreasing(values: list[float], weights: list[float]) -> list[float]:
    """Same weighted pool-adjacent-violators fit projections.py applies to FDR buckets."""
    blocks = []
    for index, (value, weight) in enumerate(zip(values, weights)):
        blocks.append({"start": index, "end": index, "weight": weight, "mean": value})
        while len(blocks) >= 2 and blocks[-2]["mean"] < blocks[-1]["mean"]:
            right = blocks.pop()
            left = blocks.pop()
            weight = left["weight"] + right["weight"]
            blocks.append({
                "start": left["start"], "end": right["end"], "weight": weight,
                "mean": (left["mean"] * left["weight"] + right["mean"] * right["weight"]) / weight,
            })
    fitted = [0.0] * len(values)
    for block in blocks:
        for index in range(block["start"], block["end"] + 1):
            fitted[index] = block["mean"]
    return fitted


def build_incumbent(history: list[dict]) -> dict | None:
    """Tier-plus-recent-form fallback, rebuilt from everything known before the cutoff."""
    if len(history) < 40:
        return None
    league_scored = statistics.mean(row["goals"] for row in history)

    # Tier proxy for FDR: five bands on goal difference, hardest opponent = difficulty 5.
    scored = defaultdict(list)
    conceded = defaultdict(list)
    for row in history:
        scored[row["team"]].append(row["goals"])
        conceded[row["opponent"]].append(row["goals"])
    teams = sorted(set(scored) | set(conceded))
    strength = {
        team: (statistics.mean(scored.get(team, [league_scored]))
               - statistics.mean(conceded.get(team, [league_scored])))
        for team in teams
    }
    ordered = sorted(teams, key=lambda team: strength[team])
    tier = {}
    for position, team in enumerate(ordered):
        tier[team] = min(5, 1 + int(5 * position / max(len(ordered), 1)))

    # Bucket goal rates by venue and the difficulty of the opponent faced.
    buckets: dict[tuple[bool, int], list[float]] = defaultdict(list)
    for row in history:
        buckets[(row["home"], tier[row["opponent"]])].append(row["goals"])
    priors = {}
    for home in (False, True):
        raw, weights = [], []
        for difficulty in range(1, 6):
            values = buckets.get((home, difficulty), [])
            raw.append((sum(values) + FDR_BUCKET_PRIOR_SIDES * league_scored)
                       / (len(values) + FDR_BUCKET_PRIOR_SIDES))
            weights.append(len(values) + FDR_BUCKET_PRIOR_SIDES)
        for difficulty, value in enumerate(isotonic_decreasing(raw, weights), 1):
            priors[(home, difficulty)] = value

    # Recent-form factors: last RECENT_WINDOW matches, shrunk toward the league rate.
    def factor(values: list[float]) -> float:
        recent = values[-RECENT_WINDOW:]
        shrunk = ((sum(recent) + FORM_PRIOR_MATCHES * league_scored)
                  / (len(recent) + FORM_PRIOR_MATCHES))
        return shrunk / league_scored

    attack = {team: factor(scored.get(team, [])) for team in teams}
    defence = {team: factor(conceded.get(team, [])) for team in teams}
    return {"priors": priors, "tier": tier, "attack": attack, "defence": defence,
            "league": league_scored}


def incumbent_lambda(model: dict, team: str, opponent: str, home: bool) -> float:
    difficulty = model["tier"].get(opponent, 3)
    prior = model["priors"][(home, difficulty)]
    attack = model["attack"].get(team, 1.0)
    defence = model["defence"].get(opponent, 1.0)
    return prior * math.sqrt(attack * defence)


def league_average_lambda(history: list[dict], home: bool) -> float:
    values = [row["goals"] for row in history if row["home"] == home]
    return statistics.mean(values) if values else 1.4


def cutoffs_for(rows: list[dict]) -> dict[int, datetime]:
    """Earliest kickoff of each round — the information boundary for a forecast made then."""
    first: dict[int, datetime] = {}
    for row in rows:
        current = first.get(row["round"])
        if current is None or row["kickoff"] < current:
            first[row["round"]] = row["kickoff"]
    return first


def evaluate(prehistory: list[dict], season: list[dict], grid: list[tuple], quick: bool) -> dict:
    rounds = cutoffs_for(season)
    by_round: dict[int, list[dict]] = defaultdict(list)
    for row in season:
        by_round[row["round"]].append(row)
    promoted = ({row["team"] for row in season}
                - {row["team"] for row in prehistory})

    cutoff_rounds = sorted(rounds)
    if quick:
        cutoff_rounds = cutoff_rounds[::3]

    # Baselines first: they do not depend on the ratings hyperparameters.
    baseline: dict[str, dict[int, list]] = {
        "league_average": defaultdict(list), "incumbent": defaultdict(list),
    }
    rating_preds: dict[tuple, dict[int, list]] = {
        params: defaultdict(list) for params in grid
    }

    for cutoff_round in cutoff_rounds:
        cutoff = rounds[cutoff_round]
        history = [row for row in prehistory + season if row["kickoff"] < cutoff]
        if not history:
            continue
        incumbent = build_incumbent(history)
        fitted = {}
        for params in grid:
            half_life, prior_strength, target = params
            try:
                fitted[params] = ratings.fit(
                    history, cutoff, half_life_days=half_life,
                    prior_strength=prior_strength, target=target, promoted=promoted,
                )
            except ValueError:
                fitted[params] = None

        for lead in range(1, MAX_LEAD + 1):
            target_round = cutoff_round + lead - 1
            for row in by_round.get(target_round, []):
                observed = row["goals"]
                baseline["league_average"][lead].append(
                    (league_average_lambda(history, row["home"]), observed)
                )
                if incumbent:
                    baseline["incumbent"][lead].append(
                        (incumbent_lambda(incumbent, row["team"], row["opponent"], row["home"]),
                         observed)
                    )
                for params, model in fitted.items():
                    if not model:
                        continue
                    home_lam, away_lam = ratings.expected_goals(
                        model,
                        row["team"] if row["home"] else row["opponent"],
                        row["opponent"] if row["home"] else row["team"],
                    )
                    rating_preds[params][lead].append(
                        (home_lam if row["home"] else away_lam, observed)
                    )

    def summarize(by_lead: dict[int, list]) -> dict:
        pooled = [pair for lead in by_lead for pair in by_lead[lead]]
        return {
            "overall": score(pooled),
            "by_lead": {str(lead): score(by_lead[lead]) for lead in sorted(by_lead)},
        }

    return {
        "baselines": {name: summarize(rows) for name, rows in baseline.items()},
        "candidates": {
            f"hl{hl:g}_ps{ps:g}_{tgt}": {
                "half_life_days": hl, "prior_strength": ps, "target": tgt,
                **summarize(rating_preds[(hl, ps, tgt)]),
            }
            for (hl, ps, tgt) in grid
        },
        "promoted_in_eval_season": sorted(promoted),
        "cutoff_rounds": len(cutoff_rounds),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quick", action="store_true", help="every third cutoff round")
    args = parser.parse_args()

    prehistory = ratings.team_match_rows(DATA_DIR / "2024-25_merged_gw.csv")
    season = ratings.team_match_rows(DATA_DIR / "2025-26_merged_gw.csv")
    grid = [(hl, ps, tgt) for hl in HALF_LIVES for ps in PRIOR_STRENGTHS for tgt in TARGETS]
    print(f"prehistory {len(prehistory)} team-matches, eval season {len(season)}, "
          f"{len(grid)} candidates")

    result = evaluate(prehistory, season, grid, args.quick)

    best_name, best = min(
        result["candidates"].items(), key=lambda item: item[1]["overall"]["nll"]
    )
    incumbent = result["baselines"]["incumbent"]["overall"]
    average = result["baselines"]["league_average"]["overall"]

    print(f"\n{'model':28s} {'n':>6s} {'NLL':>9s} {'MAE':>8s} {'RMSE':>8s} {'bias':>8s}")
    for label, row in (("league average", average), ("incumbent (FDR+form)", incumbent),
                       (f"ratings {best_name}", best["overall"])):
        print(f"{label:28s} {row['n']:6d} {row['nll']:9.5f} {row['mae']:8.5f} "
              f"{row['rmse']:8.5f} {row['bias']:8.5f}")

    print(f"\n{'lead':>5s} {'incumbent':>11s} {'ratings':>11s} {'delta':>9s}")
    for lead in sorted(best["by_lead"], key=int):
        a = incumbent and result["baselines"]["incumbent"]["by_lead"][lead]["nll"]
        b = best["by_lead"][lead]["nll"]
        if a is None or b is None:
            continue
        print(f"{lead:>5s} {a:11.5f} {b:11.5f} {b - a:+9.5f}")

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": "team-ratings-v1",
        "eval_season": "2025-26",
        "prehistory_season": "2024-25",
        "primary_metric": "poisson negative log-likelihood on actual team goals",
        "selected": {"name": best_name, **{k: v for k, v in best.items() if k != "by_lead"},
                     "by_lead": best["by_lead"]},
        "incumbent_note": (
            "FDR replicated in production form with difficulty proxied by rolling goal-"
            "difference tiers and buckets calibrated on actual goals, both of which "
            "favour the incumbent over the live static-FDR, odds-calibrated version"
        ),
        **result,
    }, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
