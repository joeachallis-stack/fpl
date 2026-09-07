# Codex handoff: audit repairs and first trustworthy projection baseline

Started: 2026-09-05.
Status: implementation complete; this document is included in the v9 checkpoint.

This session follows the adversarial review of commits `b07d36a..1310592`. The objective
is to repair the measurement loop before GW4 is frozen, correct the live penalty model,
and move the evidence-scaled prior out of the live path until it has genuinely
out-of-sample evidence.

## Findings being repaired

1. `freeze.py` considered every projection archive resolved because archives are created
   with `actual_points: null` and the check tested key presence rather than a non-null
   value.
2. The scheduler refreshed the cache only inside the twelve-hour freeze window, so it
   could not independently discover a newly finalized gameweek between deadlines.
3. Penalty-taker availability was applied once in `taker_probability` and again when the
   per-90 xG rate was multiplied by expected minutes.
4. Unassigned penalty goals were returned to the goal-allocation pool and then incorrectly
   treated as assistable goals. Penalty-miss deductions were not projected.
5. `evidence_capped_2700` was selected and tested on the same historical season. It also
   changed cards and fallback saves even though only xG and xA were measured.
6. Projection metadata and the previous handoff contain stale descriptions of the live
   prior and commit range.

## Intended end state

- The hourly agent refreshes stale official inputs, freezes only before the deadline, and
  automatically resolves every available record after settlement.
- The live projection uses corrected explicit penalty duty and the established flat-900
  prior. The evidence-scaled prior remains a frozen shadow challenger rather than changing
  decisions.
- Projection archives carry schema-aware component vectors, including modeled penalty
  misses, and evaluation preserves the meaning of older archives.
- GW3's existing minutes archive is never overwritten.

## Work log

- Began this handoff before editing implementation files.
- Repaired scheduler state detection. Projection archives are unresolved while
  `actual_points` is null; new minutes rows and projection archives receive explicit
  `resolved_at` markers. Both resolvers refuse to run before FPL marks the event finished
  and data-checked.
- Moved the six-hour official-state refresh ahead of all freeze-window early returns. The
  maintenance fetch uses `--skip-slow --skip-optional`, so it does not consume bookmaker
  credits or fetch RSS feeds merely to discover a deadline rollover.
- Made resolution refresh every element summary first. `fetch_data.py` now exits nonzero
  when the bulk summary pull aborts, preventing incomplete actuals from being marked
  resolved. The timer retries on its next run.
- Corrected penalty duty by separating conditional duty while on the pitch from the
  unconditional taking probability. The per-90 xG strip now applies availability once.
- Split generic goal allocation from assistable goals. Unknown takers' goal expectation
  remains conserved, all penalty goals are excluded from assists, and expected penalty
  misses now receive the live scoring deduction. When the named takers are unavailable,
  the unknown remainder is assigned by the same generic xG share used for its goal.
- Returned every live prior-season rate to flat 900 minutes. The existing
  `evidence_capped_2700` policy is now a shadow that changes xG and xA only and never enters
  `decisions.py`.
- Made that decision boundary executable rather than conventional. `decisions.py` now
  recursively removes every `shadow_*` field before its player records reach squad
  selection, lineup scoring or captaincy. A regression test changes shadow xP from
  +4,000 to -4,000 and verifies that the optimizer input is identical.
- Added compact live and shadow component vectors to the same projection archive. This
  avoids fragmenting the live model-version series. Evaluation reports paired shadow-minus-
  live MAE, including gameweek-clustered uncertainty and component deltas.
- Bumped projection archives to schema 3 and made component evaluation schema-aware.
  Penalty misses remain residual for old archives and become modeled only when present in
  the frozen component order.
- Added an archive-time invariant that refuses component vectors which do not reconstruct
  their stated xP.
- Marked the prior grid and its same-sample t statistic exploratory in both the training
  output and saved artifact. Corrected `IDEAS.md`, `DATA_SOURCES.md`, and the earlier
  handoffs; the v7 penalty-effect table is explicitly retracted rather than silently
  rewritten.

## Live and shadow policy after this session

- Live version: `baseline-v9-penaltyfix`.
- Live prior: flat 900 minutes for xG, xA, cards and fallback saves.
- Shadow: `evidence_capped_2700`, affecting xG/xA and their derived goal allocation only.
- Shadow adoption gate: at least six resolved archives. Paired realized total-xP error is
  primary; xG/xA component error is supporting. Do not select a different cap on those
  same future observations and call its result confirmatory.
- Ratings and bookmaker anchoring remain outside the live path.

## GW4 code freeze and archive policy

- **Hard code-freeze: Thursday 2026-09-10 at 12:30 UTC**, 48 hours before the currently
  published GW4 deadline. After that point, do not change scheduler behavior, projection
  logic, optimizer logic, archive schemas, scoring configuration or fitted artifacts
  until all three GW4 archives exist. Documentation-only edits are harmless.
- Before the code-freeze, either finish and verify a repair or revert it to the documented
  behavior. Do not carry a partially implemented repair into the rehearsal window.
- Leave the installed hourly agent running unchanged from Thursday through the Saturday
  freeze. On Thursday and Friday inspect `python scripts/freeze.py --status` and
  `data/freeze.log`; do not use `--force` merely to rehearse because that would create the
  real, non-overwriteable archive.
- **First successful archive wins.** This is a deliberate safety trade, not inherited
  wording. A replace-until-deadline policy could capture later team news, but its safety
  depends on correct clocks, deadline parsing and overwrite guards. The unconditional
  never-overwrite invariant is easier to audit and cannot silently replace a forecast
  after information leakage. Its accepted cost is that a T-11h success can be less
  informed than a hypothetical T-2h run.
- Reconsidering that policy requires a separate design that preserves every timestamped
  pre-deadline forecast rather than overwriting one. Do not weaken the current invariant
  immediately before GW4.

## Files changed

- `scripts/freeze.py`, `scripts/fetch_data.py`, `scripts/minutes.py`: reliable refresh and
  resolution lifecycle.
- `scripts/set_pieces.py`, `scripts/projections.py`: corrected penalties, flat live prior,
  frozen shadow challenger, schema 3.
- `scripts/decisions.py`: enforced live-only projection boundary and explicit archive
  verification.
- `scripts/evaluate.py`: schema-aware components and paired shadow evaluation.
- `scripts/train_priors.py`, `models/prior_weight_params.json`: honest exploratory label.
- `odds/odds_2026-09-06T0352Z.json`: expected append-only market snapshot from the
  decision-planning refresh.
- `tests/test_audit_repairs.py`, `tests/test_model_inputs.py`: regression and archive tests.
- `CLAUDE.md`, `docs/IDEAS.md`, `docs/DATA_SOURCES.md`, and both earlier handoffs: workflow
  and audit corrections.

## Verification log

- `python -m unittest discover -s tests -v`: **37 tests pass**.
- `python -m compileall -q scripts tests`: passes.
- `git diff --check`: passes.
- Full `projections.py` build: 653 players, GW4, version
  `baseline-v9-penaltyfix`; partial-GW3 warning remains correctly visible.
- Live and shadow component vectors reconstruct xP with maximum observed rounding error
  0.002 points.
- Summed player goal expectation matches every team's bookmaker lambda with maximum
  rounding error 0.002 goals.
- Summed live and shadow penalty-miss expectation matches each team's modeled miss total
  with maximum rounding error about 0.00214 misses after player-level JSON rounding.
- Temporary schema-3 archive: 653 players, 65 calibration players, live and shadow compact
  vectors round-trip successfully. No real GW4 archive was created.
- `decisions.py --no-chips` completes against v9. Unit coverage now proves that extreme
  changes to shadow xP cannot change the records supplied to its optimizer, and exercises
  `decisions.py archive` in a temporary directory to prove that a second success cannot
  overwrite the first. No real decision archive was created.
- `freeze.py --status` remains read-only and reports GW4 unarchived, with GW3's existing
  minutes archive untouched.

## State and remaining caveats

- There are still no real files in `projections/` or `decisions/`. `minutes/gw03.jsonl`
  remains the only minutes archive and was not modified.
- The cached GW3 state was still 8/10 complete during verification. Once the official API
  marks it finished and data-checked, the next stale-state refresh should trigger the full
  summary pull and resolve GW3 minutes automatically.
- A complete all-player resolve refresh is intentionally expensive. Correctness wins here:
  it runs only when an unresolved finalized record exists, and a failed pull is retried.
- The penalty rate still rests on sparse missed-penalty evidence, scales proportionally
  with team attacking lambda, and treats teammates' availability as independent. Those are
  frozen assumptions to test, not established facts.
- Current-duty stripping is still historically wrong for recent duty changes such as
  Barry. The change remains surfaced in `set_piece_duty_changes`; v9 does not pretend to
  have historical duty data that was never captured.
- The launchd agent was already installed and points at the repository script, so no plist
  reinstall is required. No real freeze was forced. The implementation verification used
  `--status` only; the 2026-09-06 decision-planning follow-up then ran the normal full data
  refresh and created the expected timestamped odds snapshot.

## GW4 operating plan added 2026-09-06

A fresh full pull found two GW3 fixtures still unplayed: Everton–Manchester United and
Arsenal–Chelsea. The projection therefore remains explicitly partial for players from
those four clubs. The saved squad is legal and unflagged, Joe has four free transfers and
£1.5m in the bank, and holding through GW4 would accrue the fifth transfer rather than
waste one. There are no GW4 creator findings yet; all 65 available transcripts were about
earlier gameweeks.

Highest-leverage sequence:

1. Commit the audited v9 candidate and stop adding model features. Let both remaining GW3
   fixtures finish, then confirm the automatic GW3 minutes resolution and rebuild the
   projections with a complete round of evidence.
2. Audit minutes, role and set-piece assumptions for the decision-changing shortlist,
   currently Tzolis/Tavernier/Mbeumo, Isak/Thiago, Rogers/Palmer and the Bruno-versus-Palmer
   captaincy fork. Do not act on the provisional optimizer ranking while GW3 is partial.
3. Refresh and extract creator/news evidence after GW4 material actually appears. Focus on
   role and availability disagreements; there is no value in repeatedly processing the
   empty corpus early in the week.
4. Compare `decisions.py --horizon 2` with the default six-week run. GW4-5 use bookmaker
   fixture inputs while GW6-9 use the FDR/recent-xG fallback. On the partial-GW3 test,
   Tzolis to Tavernier remained the leading single transfer, but the preferred multi-move
   packages changed and the six-week Isak to Thiago emphasis weakened. A flip is evidence
   that the choice depends on the weak tail; stability is useful but does not prove the
   forecast correct because both runs still share minutes and scoring assumptions.
5. At the Thursday code-freeze run the full test suite, projection build, decision smoke
   test and `freeze.py --status`. Leave the hourly agent unchanged afterward. Its twelve-
   hour window begins at 2026-09-12 00:30 UTC.
6. Near the deadline, produce one decision packet: hold/transfers with runner-up, captain
   and vice, chip decision, injury/role/news disagreements, price constraints, uncertainty
   warning and checklist result. Archive the model's first successful pre-deadline state;
   journal the action Joe actually chooses if later news changes it.

Do **not** build the full frontend before GW4. It would consume the remaining safety
window and make raw, uncalibrated ranks feel more authoritative than they are. After all
three GW4 archives exist, a read-only frontend is a good next project; it need not wait
until November. Its first version should expose freshness, warnings, component breakdowns,
the top few plan comparisons, creator/model disagreements and archive status. It should
not label a plan optimal, hide uncertainty, expose shadow forecasts to decisions or write
team changes.

The design-only follow-up created `docs/FRONTEND_SPEC.md`. After Joe's preferences, the
direction became a desktop-only, playful “fantasy sticker-board” with four rooms: My
gameweek, Expert room, Fixture wall and Model form. The opening view pairs the squad pitch
with two-versus-six-GW options; experts are organized as consensus/dissent by player; the
fixture wall is an Excel-like team-by-gameweek grid; calibration remains separate from
live decisions. No repository frontend code or dependencies were added.

The next review converted the visual proposal into a build contract. The spec now defines
five distinct squad states, safe local actions versus forbidden FPL/archive writes, shared
scenario context across rooms, probabilistic minutes-calibration metrics, fixture-grid
past/future semantics, creator coverage/provenance, chip and selling-price constraints,
coherent `analysis_run_id` snapshots, failure recovery, local-only delivery and five
acceptance-tested build slices. The agreed defaults are shirt-shaped player pieces,
consensus-first experts, neutral fixtures and a quieter Model form room.

Joe subsequently authorized implementation. The safe boundary is to commit this design
record on `main`, then build on `codex/frontend-v1`; no frontend work should modify the
repaired GW4 model or scheduler path before its first archive.
