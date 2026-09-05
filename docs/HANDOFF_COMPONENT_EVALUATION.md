# Claude Code handoff: component-level projection evaluation

Updated: 2026-09-05

## Where this session stopped

This session completed one coherent slice: the projection model can now be evaluated
by FPL scoring component once genuine pre-deadline projection archives resolve. The
implementation is committed with this document. Do not create a retrospective GW4
archive: GW3 was still unfinished during this work, and a forecast frozen after seeing
later information would not be an honest forecast.

There are currently no files in `projections/`, so `python scripts/evaluate.py` correctly
produces an empty-but-valid `data/evaluation.json`. Real error measurements begin after
the next projection is archived before its deadline and the relevant gameweek finalizes.

## Decisions that are now encoded

- Evaluate total xP and each modeled component: appearance, goals, assists, clean sheet,
  goals conceded, yellow cards, red cards, DefCon, bonus, and saves.
- Reconstruct actual points from the finalized player-fixture observation ledger using
  the scoring rules frozen in the projection archive.
- Keep own goals, penalty saves, and penalty misses as an explicit residual instead of
  pretending the model predicts them. Any unexplained accounting difference is also
  visible and causes archive evaluation to fail if official and reconstructed totals do
  not match.
- Score each fixture separately before aggregating a player's double-gameweek total.
  This matters for threshold rules such as appearances, saves, and goals conceded.
- Report unweighted all-player diagnostics, but use the pre-deadline frozen contender
  weights for the primary calibration population. The model may score every player; it
  should not optimize equally for irrelevant non-contenders.
- Break results out by forecast lead and model version so future changes are not blended
  into one misleading number.
- Freeze the scoring map and component order in archive metadata. Full contender audit
  records remain intact; diagnostic-only players retain compact ordered component
  vectors so archive growth stays bounded.

## Files changed

- `scripts/evaluate.py`: component reconstruction, weighted/unweighted metrics, lead and
  version splits, archive audit, JSON output, and concise console report.
- `scripts/projections.py`: archive schema version 2, frozen scoring rules, frozen
  component order, and compact diagnostic component vectors.
- `tests/test_model_inputs.py`: accounting, DGW aggregation, weighting, and archive
  round-trip tests.
- `CLAUDE.md`, `docs/IDEAS.md`, `docs/DATA_SOURCES.md`: workflow and methodology notes.

## Validation completed

- `python -m unittest discover -s tests -v`: 20 tests pass.
- `python -m py_compile scripts/*.py`: passes.
- Reconstructed all 1,236 latest finalized observation rows then present in the ledger;
  every row matched its official `total_points` exactly.
- A temporary (not repository) GW4 archive round-trip retained component forecasts for
  all 3,912 player-gameweek rows.
- That temporary six-week archive was 1,509,342 bytes. Compact diagnostic vectors added
  258,340 bytes over the same archive with those vectors removed. This is considered a
  reasonable audit cost; no historical input ledgers were duplicated.
- `python scripts/evaluate.py` safely reports that no frozen projection archives exist.
- No GW4 projection, minutes, or decision archive was created.

## Normal use after the next deadline cycle

Before a deadline, follow the existing workflow to generate and freeze the projection.
After each forecast gameweek is finalized and the observation ledger has been refreshed,
run:

```bash
python scripts/evaluate.py
```

Read the contender metrics first, especially by lead. Use all-player results to diagnose
systematic behavior, not as the optimization target. Inspect component bias and RMSE
before changing a component model; do not tune from a single gameweek.

## Next logical work

Do not add another model feature immediately. The next sound step is to let real frozen
forecasts accumulate, then inspect whether component residuals reveal a consistent error.
When enough observations exist, compare candidate recalibrations walk-forward and keep a
change only if it improves the relevant contender population without hiding regressions
in the all-player diagnostic.

The broader product direction remains a local decision dashboard combining the model,
team/transfer feasibility, creator consensus and dissent, and historical audits. The
component evaluator should be treated as the measurement layer feeding that dashboard,
not as a reason to add UI or model complexity before there is evidence.
