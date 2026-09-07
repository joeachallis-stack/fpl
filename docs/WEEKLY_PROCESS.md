# Weekly FPL process — working draft

**Status:** Draft operating process, expected to evolve with evidence  
**Started:** 2026-09-07  
**Objective:** Maximise total FPL points while keeping the decision and measurement record honest.

This document describes the weekly rhythm Joe wants to follow. It is not a finalized
policy. Change it when repeated use exposes friction or the frozen evaluation record gives
us evidence for a better process. Do not quietly weaken the point-in-time, archive or
decision-journal safeguards.

## The two weekly loops

Every gameweek has two connected but distinct loops:

1. **Set the team:** turn current official data, forecasts and human evidence into a
   transfer, captaincy, lineup and bench decision.
2. **Earn trust:** score the forecasts and review the reasoning after the gameweek, without
   confusing a lucky result with a good decision or an unlucky result with a bad one.

The frontend is the review surface for both loops. The official FPL site remains the place
where Joe submits the team.

## Loop 1 — set the team

### A. Once the previous gameweek is officially final

- Refresh the official FPL cache with `python scripts/fetch_data.py`.
- Require both `finished=true` and `data_checked=true`; do not resolve from the scoreline
  merely looking complete.
- Let `freeze.py` resolve any frozen minutes, projections and journal records for the
  settled gameweek.
- Read the resolved audit before treating the next recommendation as trustworthy.
- Rebuild the mutable minutes, projections, decisions and independent horizon comparison
  using the finalized histories.

### B. Early and middle of the week

- Run `python scripts/state.py` to establish the deadline, bank, free transfers and chip
  windows.
- Check that minutes, projections and decisions target the same gameweek and that their
  inputs are fresh.
- Confirm that the target fixtures have complete bookmaker coverage. Missing target-week
  odds are a readiness failure, not permission to weaken the archive check.
- Compare the independently optimized two-gameweek and six-gameweek plans.
  - Agreement is supporting evidence that the move is not driven only by distant fallback
    fixtures.
  - A material flip is uncertainty. Unless another strong reason exists, prefer holding.
- Run the `gameweek-brief` process. Consolidate creator claims, resolve player identities
  against the roster and check factual claims against the official record.
- Inspect disagreements between creators and the minutes model, especially role changes,
  injuries, rotation and set-piece duty. Creator evidence informs judgment; it does not
  become model truth.

### C. From roughly 48 hours before the deadline

- Freeze code and model assumptions. Only refresh data and rebuild the ordinary mutable
  analysis unless a demonstrated defect makes the output unsafe.
- Refresh injury news, manager comments, predicted roles, fixture odds and price context.
- Reduce the choice to a recommended action and a real runner-up. Holding is always an
  eligible action.
- Review the recommendation as a complete team:
  - transfers, their cost and projected gain versus holding;
  - captain and vice-captain;
  - starting XI and formation;
  - bench order;
  - chip or no chip;
  - the main reason the plan could be wrong.
- Treat small raw xP differences as comparisons, not automatic actions, until a calibrated
  robustness margin exists.

### D. Before the deadline

- Run `python scripts/check_team.py` against the last saved official squad.
- Record the recommendation, runner-up and why it won in the decision journal before the
  outcome is known.
- Make the chosen changes on the official FPL site.
- Manually confirm the submitted transfers, XI, bench, captain, vice-captain and chip state
  on the official FPL site. The unauthenticated API cannot prove those pre-deadline changes,
  so a refresh must not be presented as submission verification.
- Verify that the scheduler's first successful pre-deadline archives exist for minutes,
  projections and decisions. The first successful archive wins and is never overwritten.

The weekly decision should finish with a compact answer:

- action: transfer, hold or chip;
- captain and vice-captain;
- XI and bench order;
- expected advantage versus holding;
- whether the two horizons agree;
- confidence: **actionable**, **marginal** or **too uncertain**;
- main failure mode;
- runner-up and why it lost.

## Loop 2 — earn trust and improve

### Expected minutes: did we understand who would play?

Audit the frozen xM forecast after every officially finalized gameweek:

- MAE and signed bias;
- zero / 1–59 / 60+ band accuracy and probability scores;
- starters, used substitutes and unused players separately;
- Joe's owned squad and realistic transfer candidates separately;
- the largest role reversals, injury misses and rotation misses.

Do not let a large number of easy unused-player predictions conceal errors on the players
who affected the decision.

### Expected points: did we price performance correctly?

GW4 is the first honest frozen xP baseline. From there, track:

- total-xP MAE, signed bias and large misses;
- all-player diagnostics separately from decision-relevant players;
- scoring-component errors where the match record supports them;
- model versions rather than pooling incompatible forecasts;
- stability of the two- and six-gameweek recommendations.

There is no honest GW3 xP audit because no pre-deadline GW3 projections archive exists.
Do not reconstruct one after the fact and present it as frozen evidence.

### Decision quality: was the reasoning good at the time?

Review the journal separately from model accuracy:

- Was every material fact available before the deadline?
- Did the reasoning identify the real uncertainty?
- Were the recommendation and runner-up the right comparison?
- Was holding considered fairly?
- Would the reasoning still look sound if the realized points were reversed?

A good decision can lose for a week, and a bad one can win. Realized points are evidence,
not the sole verdict on the process.

## Change-control rules

- Do not retune the model from one player or one gameweek.
- Fix demonstrated software and data defects, subject to the pre-deadline code freeze.
- Test judgmental model changes as evaluation-only shadows first.
- Shadow outputs must never reach `decisions.py`, squad selection or the live frontend.
- Change one identifiable assumption at a time and record its hypothesis and model version.
- Evaluate on later frozen forecasts, never on the same observations used to choose the
  change.
- Use gameweek-clustered uncertainty; player rows within a gameweek are correlated.
- Wait for at least six independent resolved gameweeks before showing even an early
  uncertainty estimate. Do not describe that early estimate as calibrated certainty.
- Improve the creator pipeline each week by recording observed aliases, extraction traps
  and claim-checking failures.

## What should make this process reassuring

Confidence should come from invariants rather than confident language:

- the forecast existed before the result;
- official data adjudicated it;
- the recommendation and runner-up were recorded before the outcome;
- readiness failures and weak evidence were visible;
- evaluation-only experiments could not alter the live decision;
- model trust increases slowly as independent gameweeks resolve.

## Current maturity

- GW3 is the first resolved xM audit.
- GW4 will be the first frozen xP and decision baseline.
- There is not yet a calibrated robustness margin.
- The first six resolved gameweeks are an evidence-building period, not a contest to make
  the model look accurate.
