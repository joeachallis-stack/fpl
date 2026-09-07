# Handoff — independent horizon comparison, 2026-09-06

This supersedes the open design fork in
`HANDOFF_2026_09_06_CLAUDE_TO_CODEX.md`. Option B was chosen: the comparison has its own
isolated path and the three archive-producing `build()` functions remain unchanged.

## What changed

- Added `scripts/horizon_compare.py`.
- Added a non-mutation integration test in `tests/test_horizon_compare.py`.
- `scripts/frontend_data.py` now accepts a matching independent comparison artifact.
- `scripts/frontend_server.py` builds the comparison after the normal projection and
  decision rebuild.
- The Options board labels the result `independent searches` only when the artifact's
  canonical projection and decision hashes still match.

The comparison does not rebuild projections at a second horizon. The canonical six-week
artifact already contains unchanged weekly forecasts for GW4–9, so the script deep-copies
it, keeps GW4–5, recomputes each player's two-week horizon total, and runs the exact squad
optimizer independently over those two weeks. It then cross-scores the union of the two-
and six-week candidate sets over both horizons.

All optimizer writes are redirected to a temporary directory. Before and after the run,
the script hashes:

- `data/minutes.json`, `data/projections.json`, `data/decisions.json`;
- every file in `minutes/`, `projections/` and `decisions/`.

Only `data/horizon_comparison.json` is published, and it is gitignored with the rest of
`data/`. The artifact records its input hash, canonical artifact hashes, target gameweek,
model versions, horizons and the passed mutation check. If an official refresh or rebuild
invalidates the source hashes, the frontend ignores it and falls back to the prior
same-candidate-set comparison until the comparator runs again.

## Provisional GW4 result

The current cache is still pre-finalization: GW3 is 10/10 provisionally settled but is not
officially `finished` and `data_checked`. Do not turn these numbers into a transfer call.

On that provisional input, twelve distinct candidate squads were found. The leading
packages differ:

```text
2 GW: Gibbs-White, Rogers, Tzolis, Isak
      -> Gakpo, Palmer, Tavernier, Thiago
      +8.72 xP after hits versus hold

6 GW: Kinsky, Rogers, Tzolis, Isak
      -> Kelleher, Palmer, Tavernier, Thiago
      +18.68 xP after hits versus hold
```

Both use four free transfers and no hit. The disagreement is Gakpo versus Kelleher after
accounting for the different outgoing players; it demonstrates that the fallback tail can
change the preferred package. It does not prove either package is actionable because there
is still no calibrated robustness margin and the inputs precede official GW3 settlement.

## Verification

```text
python -m pytest -q       47 passed
cd frontend && npm test   4 passed
cd frontend && npm build  successful
```

The browser-to-API-to-artifact flow was also checked on `127.0.0.1:8765`:

- API returned `Independent exact searches over two and six gameweeks`.
- The rendered Options board showed `independent searches` and four coherent rows.
- No browser console warnings or errors.
- The readiness ribbon remained partial because GW3 is not officially checked.

## Next actions

1. Keep waiting for a fresh official cache where GW3 is both `finished` and
   `data_checked`; do not resolve early.
2. Once final, verify the scheduler resolves `minutes/gw03.jsonl`, then audit its first
   out-of-sample errors without retuning from one gameweek.
3. Rerun `python scripts/consolidate.py --gw 4` for official claim checks; this step is not
   scheduled.
4. Rebuild the canonical GW4 projections and decisions, then rerun
   `python scripts/horizon_compare.py`. Confirm the frontend still says `independent
   searches`; a stale artifact intentionally falls back.
5. Run `scripts/check_team.py`, inspect creator/model disagreements, decide, and create the
   first honest journal entry with the runner-up and why it lost.
6. Keep the Thursday 2026-09-10 12:30 UTC code freeze. Saturday's first-success archive
   remains more important than another feature.

The largest remaining archive risk from Claude's handoff is unchanged: projections refuse
a partial target gameweek of odds. Current inputs have complete GW4 odds and the isolated
full archive path passed, but the Saturday run will use later inputs. Check
`python scripts/freeze.py --status` and odds completeness before Thursday's freeze; do not
weaken the refusal merely to make an archive appear.
