# Claude Code handoff: measurement automation, team ratings, set pieces, prior weight

Written: 2026-09-05, for Codex review.
Picks up from [`HANDOFF_COMPONENT_EVALUATION.md`](HANDOFF_COMPONENT_EVALUATION.md).
17 commits, `b07d36a..1310592`. 20 tests pass; all scripts compile.

> Subsequent audit repairs are tracked in
> [`HANDOFF_2026_09_05_CODEX_AUDIT_REPAIRS.md`](HANDOFF_2026_09_05_CODEX_AUDIT_REPAIRS.md).
> This remains the point-in-time record that was reviewed; its v8 live-model and scheduler
> descriptions have been superseded.

## Read this first: where we ignored your advice

Your handoff opened with **"Do not add another model feature immediately. The next sound
step is to let real frozen forecasts accumulate."** We added several model features. That
was a deliberate choice by Joe, not an oversight, but you should read the rest knowing it.

Partial defence, offered as context rather than justification:

- The one thing genuinely blocking your advice was that accumulation depended on Joe
  remembering to run three commands before every deadline, forever. That is now automated
  on both sides, which is the part of your instruction that needed building rather than
  waiting.
- Nothing speculative reached the live path. Team ratings and odds anchoring were built,
  measured, and **deliberately not adopted**.
- Two changes that *did* reach the live path are omissions and defects rather than
  speculative features: penalty duty was being ignored while `penalties_order` was
  snapshotted daily and read by nothing, and the prior-season weight was a flat constant
  that treated 480 and 3,065 minutes of evidence identically.

If you disagree with either live change, they are isolated and revertible — see
"Live-path changes" below.

## The most important thing in this document

**Three statistical corrections invalidated numbers we had already reported.** If you read
only one section, read this one, because the same errors are easy to repeat.

1. **Standard errors assumed independence and were wrong by roughly 2x.** Every match-side
   is re-forecast from up to six cutoffs, and those forecasts share one actual outcome.
   `n = 4,260` was really 760 correlated clusters. `paired_stats` in `train_ratings.py` now
   computes a cluster-robust (CR0) error. Effect: the ratings headline fell from t = -6.21
   to **t = -2.88**; the anchoring result from -6.11 to **-3.70**.

2. **Hyperparameters were selected on the evaluation data.** `nested_selection_test` now
   selects on 2024/25 and scores once on 2025/26. The honest gap is **-0.01482 at t = -1.75**
   against the in-sample -0.02276 at t = -2.88. Three estimates reconcile exactly:
   best-of-80 -0.02276, median candidate -0.01585, honest -0.01482. The headline's extra
   0.008 was purely the best-of-80 bonus.

3. **A finding was retracted.** We reported that odds anchoring helps most where a rating
   has gone stale — the managerial-change case — at "3x more benefit." Under clustered
   errors the most-stale quartile falls to **t = -1.92**, the quartile ordering is not
   monotone, and the "3x" was a post-hoc comparison never formally tested. It is now
   documented as suggestive and not established.

A fourth, smaller one: cluster ids initially omitted a season tag, and fixture ids restart
each season, so two different matches were being silently merged into one cluster.

## Live-path changes (these need your review most)

`scripts/projections.py`, `MODEL_VERSION` `baseline-v6-availability` -> `baseline-v8-priorweight`.

### 1. Penalty duty is now modelled explicitly (`scripts/set_pieces.py`)

Official xG **includes penalties**, and the projection allocates team goals by xG share.
So a player who had just gained duty got no credit, one who had lost it kept credit, and an
established taker was paid only diffusely. The team goal expectation is now split:
penalties go to whoever is on duty weighted by the minutes model, and the remainder is
allocated by xG with the estimated penalty component removed. Total is conserved and
unassignable penalties return to the open-play pool; assists scale with open play alone
because a penalty has no assist.

The rate is derived, not assumed. No `penalties_scored` field exists anywhere in the API,
but `penalties_missed` does, and missed volume at a known conversion implies taken volume:
14 and 15 misses over 760 team-matches per cached season give 0.088 and 0.094 per
team-match at 79% conversion. **~15 events, so the sampling error is wide.**

Effect: 22.0 total absolute horizon xP moved over 653 players. Palmer +0.381, Haaland
+0.352, Saka +0.255; non-takers on high-scoring sides slightly negative. Fernandes gains
only +0.080 despite near-certain duty, which is the double-count correction working.

**Known defect we did not fix.** `penalty_xg_per_90` assumes current duty held across the
history the xG rate was measured over. Barry gained Everton's duty on 5 September, so we
strip 0.045 xG/90 from him that was largely never there, then add it back explicitly.
Roughly self-cancelling, but wrong. `set_piece_duty_changes` flags the affected players
(20 currently) without correcting them.

### 2. Prior-season weight now scales with evidence (`scripts/train_priors.py`)

Was a flat 900 minutes for everyone. 140 players carried under 900 prior minutes and were
credited with 900; 123 carried over 2,000 and were also credited with only 900 — so two or
three current matches could swing a well-established rate by 40%. Fernandes: 3,065 prior
minutes at 0.298 xG/90, 180 current at 1.05, blend 0.424.

Calibrated walk-forward on 7,441 player-cutoff samples across 314 players. Every
evidence-scaled scheme with a generous cap beat every flat scheme on future xG.
`flat_1800` (0.01351) against `evidence_capped_1800` (0.01334) isolates the mechanism: the
same ceiling, so the gain is from scaling with evidence, not from trusting the prior more.

**Adopted at t = -1.68, which is directional and not significant.** The reasoning was that
the incumbent constant had no evidence behind it at all, so between two schemes the
principled one wins the tie-break. **This is the change most worth your challenge.**
Assists were indifferent to every scheme (best t = -0.67) and applying this uniformly costs
a non-significant t = +1.08 there; a metric-specific rule was rejected as overfitting.

Effect: Fernandes 25.36 -> 24.50 xP. Top two unchanged, middle reorders.

### 3. Partial-round warning

There was already a guard against ranking a target gameweek with partial odds; this is its
mirror on the input side. While GW3 was 8/10 complete, Haaland's rates included GW3 and
Palmer's did not, purely by kickoff time. Nothing is corrupt — `completed_history()`
correctly excludes unplayed rows — but the population is unevenly updated, which biases
relative ranking, and relative ranking is what a transfer decision consumes. Reported, not
enforced, and frozen into `meta.previous_gw_completeness`.

## Measurement automation (the part that serves your advice)

`scripts/freeze.py` under a launchd agent, hourly. Two phases with opposite timing
constraints: the freeze must happen before a deadline and can never be redone; resolving
can only happen after settlement and is safe to repeat, so it runs on every pass regardless
of the freeze window.

- Runs often, almost always exits immediately. Acts only inside `FREEZE_LEAD_HOURS` (12)
  with an archive actually missing.
- `StartInterval`, not `StartCalendarInterval`: launchd fires a missed `StartInterval` job
  when the machine next wakes, so a sleeping laptop catches up.
- Steps are independent — `projections.py` refusing partial odds still leaves minutes and
  decisions archived, and the next run retries.
- Pending resolves are detected per record (`actual_minutes` populated, `actual_points`
  present, `resolved_at` set), not in a state file, so nothing can drift.
- Accepted trade: first success wins, so a freeze at T-11h keeps staler team news than
  T-2h. A stale-but-honest forecast beats a hole.

**Odds are now archived per distinct market state** (`odds/`, git-tracked; raw responses in
gitignored `data/odds_raw/`), keyed on a content hash. This already paid off within hours:
the 15:07 snapshot held 8 GW3 fixtures, and by 22:18 GW3 was down to 2 while GW5 appeared.
Six GW3 lines that existed at 15:07 no longer exist anywhere.

## Built, measured, deliberately NOT adopted

### Team attack/defence ratings (`ratings.py`, `train_ratings.py`)

Motivated structurally: across the live GW4-9 horizon FPL difficulty is nearly a per-team
constant, with six clubs at exactly 3.00 and zero variance, so the FDR fallback cannot
distinguish Tottenham from Everton and no information about a team can reach that team's
later fixture.

Honest result: **-0.01482 at clustered t = -1.75**, one season of evaluation. What holds up
is the sign — 79 of 80 grid candidates beat the incumbent, at every lead 1-6. What does not
is the margin. `IDEAS.md` says not to wire this into `projections.py` on this evidence.

Two secondary findings worth your attention:

- **The incumbent barely beats assuming every team is league average** (1.46336 against
  1.46828). Most of what looks like a fixture model is doing very little.
- **The eval set cannot be expanded within cached data.** Scoring 2024/25 as a second
  evaluation season doubles the rows but answers a different question: it has no prior
  season, so both models start cold, and the incumbent degrades far more in a cold start
  (-0.04867, t = -4.49 there against -0.02276, t = -2.88 on 2025/26). Pooling gives a
  flattering -0.03514 at t = -5.30 that mixes two regimes. Production always has two cached
  seasons plus the live one, so we are never in the cold-start regime.
- A held-out third of 2025/26 was considered and rejected: random sampling of games lets
  the model train on matches after held-out ones, and resampling shows a third detects the
  true effect only 34% of the time.

### Odds anchoring (in `ratings.fit`, weight 2.0)

Priced fixtures enter the fit as weighted observations, so one price moves a team's rating
and reaches every fixture it plays. Mechanism verified: weight 0 reproduces the unanchored
fit exactly, weight to infinity recovers the market lambda (3.196 against 3.200), and a
Chelsea price moves Chelsea's lambda against Spurs — an unpriced fixture — from 1.776 to
1.925.

Cannot be validated, so it is bracketed by two leaking oracles, and **the bracket is the
finding: the sign depends on how noisy the anchor is.** On realized xG (one draw from
lambda) anchoring HURTS and worsens with weight (t = -0.05, +1.73, +4.94 at weights 2, 6,
20). On a full-season model lambda it HELPS at every weight (-3.70, -3.70, -3.72). A real
price sits between and nothing cached says where. `ODDS_MATCH_EQUIVALENT = 2.0` is the
largest weight still non-harmful under the pessimistic bound.

Ceiling is small: best case ~0.003 NLL against the 0.023 the ratings change itself is worth.

### Promoted-team prior

Kept but **not evidence-selected**: paired ablation over 639 promoted-team forecasts gives
pooled t = +0.40 clustered, no bucket significant, sign flips between buckets. Retained on
a priori grounds only — at zero history the alternative is calling a promoted side exactly
league average, known wrong in advance. The 20+ bucket carries the real finding: prior and
no-prior become indistinguishable, so a promoted team's own results have fully taken over.
Live consequence: Coventry, Hull and Ipswich have no history in either cached season.

### Corners and direct free kicks — measured, deliberately not priced

Designated corner takers carry 2.26x (DEF) and 2.45x (MID) the xA per 90 of non-takers, and
direct free-kick takers 2.52x and 1.88x. Neither is usable: the ratios are **confounded**
(creative players are chosen to take corners, and separating duty from selection needs
within-player duty changes that three days of snapshots cannot supply), and unlike
penalties **no rate is derivable**. Direct free kicks also add essentially nothing to goals
(0.73x DEF, 1.14x MID). Built instead: duty and duty-change flags, priced at zero.

## Designed, not built

**Bonus** (`IDEAS.md`). The deferral rested on a wrong framing — that we must learn which
player types collect bonus, which the BPS retune makes unlearnable. Two facts change it:
bonus is a **rank statistic within a match**, not a rate, so a per-player rate is
structurally wrong however well calibrated; and the BPS table is **recoverable from our own
ledger** (regression on 622 rows returns goals +22.13, assists +11.34, clean sheet +5.53 at
R2 = 0.783), which tracks current rules with no external dependency. Ranking within match on
predicted BPS identifies 80.6% of real bonus recipients — but that uses realized components,
so it is a hard upper bound. Unobserved fields (passes, big chances, shots on target, fouls,
errors) are 22% of BPS and belong in the model as noise. Build trigger ~GW8-10, gated on
**ledger volume, not archives**, so it runs on a different clock. Bonus is 7.0% of points.

## State

- No files in `projections/` or `decisions/`; `minutes/` holds only `gw03.jsonl`.
  `data/evaluation.json` still reports zero resolved forecasts. **This is unchanged from
  your handoff and remains the bottleneck.**
- GW4 deadline Sat 12 Sep 12:30 UTC. The scheduler will freeze it unattended.
- GW3 was 8/10 complete at time of writing. Once `data_checked`, the scheduler auto-resolves
  `minutes/gw03.jsonl` — the first real error number the project will have produced.
- `models/` now also holds `ratings_params.json` and `prior_weight_params.json`.

## What we would most like challenged

1. **The prior-weight adoption at t = -1.68.** We changed the live model on a
   directional, non-significant result, reasoning that the incumbent constant had no
   evidence at all. Is that the right tie-break, or should the live path have stayed put
   until archives could adjudicate?
2. **Applying the prior-weight scheme to assists** where it is measurably (if
   insignificantly) worse, to avoid metric-specific overfitting.
3. **The penalty rate resting on ~15 missed penalties**, and the untested assumption that
   penalty rate scales proportionally with a team's attacking strength.
4. **Whether ratings should be adopted at t = -1.75.** We said no. The sign is consistent
   across 79/80 candidates and all six leads, which is itself evidence.
5. **Whether we should have built any of this**, given your explicit advice not to. The
   counter-argument is that everything adopted was a defect fix and everything speculative
   was withheld — but that is our framing, and we would rather you tested it than accepted it.
