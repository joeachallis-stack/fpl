# Handoff — Claude to Codex, 2026-09-06

Session scope was deliberately narrow: verify the state described in
`HANDOFF_2026_09_06_CODEX_TO_CLAUDE.md`, then act only on what that verification found.
No model work, no frontend work, no GW4 analysis. One defect was found and fixed. The
highest-leverage remaining feature was **not** started, and the reason is a design fork
that needs a decision before Thursday.

## Read this first

- Current branch: `codex/frontend-v1`, clean.
- Two new commits, both on that branch:

```text
6cfb0c4 Store the GW4 bookmaker market state from 2026-09-06T22:07Z
5d6a83b Stop tests forging entries in the real freeze log
5c468e9 Hand off frontend and GW4 state to Claude
```

- `origin/main` still `5558d42`. Local `main` still `e148523`. Neither moved.
- GW4 deadline: Saturday 2026-09-12 12:30 UTC. Code freeze Thursday 2026-09-10 12:30 UTC.
- `freeze.py` runs from `FREEZE_LEAD_HOURS = 12`, so the **first automatic archive attempt
  is Saturday 2026-09-12 00:30 UTC**. That is the first time `projections/` and
  `decisions/` will ever be written.
- Objective remains total FPL points.

## Exact state at 2026-09-06 23:40 UTC

A genuinely fresh `fetch_data.py` was run at 22:07 UTC and completed fully, including the
small-league standings that failed in the previous session. On that fresh cache:

- **GW3 is still not finalized.** `events[3].finished false`, `events[3].data_checked
  false`, `bonus_added false` on all three match dates. `freeze.py --status` agrees
  independently: finalized gameweeks are 1 and 2, awaiting resolve is none.
- `minutes/gw03.jsonl`: 652 frozen rows, 0 with `actual_minutes`. Untouched.
- `projections/` and `decisions/` still do not exist. The mutable `data/projections.json`
  and `data/decisions.json` do. That distinction is load-bearing below.
- GW4: 4 free transfers banked (cap 5), 186 points, OR 2,228,734, £100.2m + £1.5m bank,
  all first-half chips available.
- `journal/entries.jsonl` is still empty. GW1–3 were **not** backfilled and must not be.
  GW4 is the first honest entry.

## What was built

One defect, three files, 36 insertions (`5d6a83b`).

`scripts/freeze.py` bound `LOG_PATH = DATA_DIR / "freeze.log"` at import. The freeze tests
in `tests/test_audit_repairs.py` redirect the module at a temporary root by reassigning
`freeze.ROOT` and `freeze.DATA_DIR` *after* import, which cannot reach a constant already
computed from the real one. Every `pytest` run therefore appended its fixture state to the
real log:

```text
GW4 deadline has passed — refusing to archive after the fact
  resolved projections GW4
no upcoming deadline (season over or awaiting finalization)
```

All three are false in reality — GW4 was 134 hours away and `projections/gw04.json` does
not exist. **Of the 74 lines in `data/freeze.log`, 73 were test output.** One line came
from the scheduled job.

Fixed by resolving the path inside `log()` on every call. Added a regression test asserting
the real log is byte-identical after a redirected call. Documented in the plist that
liveness is checked with `launchctl print … | grep runs`, not with the log.

`data/freeze.log` was then truncated to its single launchd-attested line. The selection rule
was principled rather than eyeballed: keep only lines that also appear in
`data/freeze.stdout.log`, which only launchd can write.

## What was measured

**The complete freeze/archive path works.** Exercised in an isolated full-repo copy under
the scratchpad, via `freeze.py --force`, because it cannot be tested in place (see the
build() finding below):

| Step | Result | Size |
|---|---|---|
| minutes | archived | 1,193,490 B |
| projections | archived | 2,228,999 B |
| decisions | archived | 35,076 B |

`GW4 fully frozen`, exit 0, ~26 s total (decisions ~20 s of it). 865 files in the real repo
hashed before and after: **byte-for-byte unchanged**. No real GW4 archive was created.

- `projections/gw04.json`: schema v3, 654 players, 0 rows carrying `actual_points`.
  `validate_component_totals` passed inside `archive()`.
- `decisions/gw04.json`: gw 4, horizon 6. **Zero `shadow_*` keys.** The single string match
  is `meta.projection_input_policy` prose describing the removal. The optimizer boundary
  survives into the archive.
- **No-overwrite refusal verified directly.** The first attempt at this was worthless: a
  second `freeze.py --force` printed nothing because `missing_steps()` was empty, so it
  never invoked the archive commands, and the byte-identical result proved only that a
  script which did not run did not write. Re-tested by calling `minutes.py archive`,
  `projections.py archive` and `decisions.py archive` directly against existing files. All
  three refuse and leave the file byte-identical.

**The launchd job is alive.** `launchctl print` reports `runs = 13`, `last exit code = 0`.
That is consistent with an hourly `StartInterval` since the plist was installed Sep 5 17:35
local, on a laptop that sleeps. Note the correction that prompted this check: a recent cache
mtime does **not** prove the monitor is running, it only proves something refreshed the
cache.

**The regression test has teeth.** Verified by reintroducing the exact bug and running the
new test alone — it fails on the redirect assertion. Then the fix was restored. That
deliberate buggy run leaked one line into the real log, which was removed.

## The finding that matters most

**Every `archive` subcommand calls `build()` first, and `build()` unconditionally writes the
mutable `OUT`.**

- `scripts/minutes.py:686`
- `scripts/projections.py:1112`
- `scripts/decisions.py:624`

So `python scripts/projections.py --horizon 2` overwrites `data/projections.json` before it
ever returns a payload. The previous handoff's warning is exact and now has line numbers.
Two consequences:

1. The archive path cannot be smoke-tested in place. Hence the isolated root.
2. **The cheap implementation of the 2-GW/6-GW comparison is ruled out.** You cannot call
   the existing CLI at a second horizon and treat it as read-only.

## What was deliberately NOT done

1. **GW3 not resolved.** Not finalized. `minutes/gw03.jsonl` untouched.
2. **`consolidate.py --gw 4` not run.** It is not technically blocked — it can run now with
   claim verification explicitly deferred — but it must be rerun after finalization anyway,
   and nothing in this session depended on it. Nothing schedules it; `freeze.py` handles
   minutes, projections and journal resolution but **not** consolidation. It is the one
   genuinely manual step after GW3 finalizes.
3. **The independent 2-GW/6-GW comparison was not started.** See the fork below.
4. **Journal GW1–3 not backfilled.** Correct per the prior handoff.
5. **`5d6a83b` not cherry-picked to `main`.** Open question below.
6. **`npm test` / `npm run build` not run.** The change is Python-only and touches no
   adapter or route, so the frontend result carries no information about it. The
   established baseline is unchanged at 4 passed / build successful; `pytest` is now
   **43 passed** (was 42).
7. **The live plist in `~/Library/LaunchAgents/` was not re-synced.** It now differs from the
   tracked copy by comments only, so the running job is behaviourally identical.

## The open design fork — decide before writing code

The horizon comparison needs a non-writing build path. Two options:

- **A: give `build()` a "don't write" switch.** Smallest diff, but it adds a mode to a
  function the freeze path depends on, four days before that path runs for the first time
  ever.
- **B: give the comparison its own read-only path** that calls the underlying builders
  without `OUT.write_text` at all. Larger diff, but leaves the code the never-redoable
  operation runs byte-for-byte untouched.

Claude's recommendation is **B**, on the reasoning that Saturday's archive is unrecoverable
and this week is the wrong week to add a mode to the code that produces it. This was not
acted on unilaterally because it is a judgment call with a real cost either way.

Requirements from the prior handoff still stand: separate artifact such as
`data/horizon_comparison.json`, record target GW / horizon / source hash / generated time /
model versions, preserve the `shadow_*` exclusion, and a test that hashes canonical caches
and archives before and after. **The hashing harness from this session's smoke test can be
adapted into that test rather than written fresh** — it already walks the tree, skips
`.git`/`node_modules`/`__pycache__`, and diffs created/modified/deleted.

Hard rule, unchanged: if the non-mutation tests are not green by Wednesday, revert and keep
the honest `same candidate set` label. A half-changed `build()` signature must not cross
Thursday.

## What Claude most wants challenged

1. **"The launchd job is healthy" rests on `runs = 13` and `last exit code = 0`, not on
   observing a scheduled run do work.** `freeze.py` logs only when it acts, so a healthy
   idle job and a dead one are indistinguishable in both logs. There is still no heartbeat.
   If you want certainty before Saturday, the only real test is watching
   `data/freeze.stdout.log` gain a line at a moment when the job genuinely has work to do.
2. **The smoke test proved the archive path works on *today's* inputs.** Saturday's run will
   execute on post-GW3-finalization inputs after a rebuild — different odds completeness,
   different minutes, resolved histories. In particular `projections.py` **refuses a partial
   next gameweek of odds**, and that refusal path was not exercised. If it triggers at
   00:30 Saturday it produces a permanent hole in the projections record, and
   `freeze.py` will retry hourly but will keep hitting the same refusal. This is the
   single largest untested risk to the first-ever archive.
3. **Truncating `data/freeze.log` was destructive and was Claude's judgment call**, taken on
   the user's instruction. The rule used is defensible but discards 73 lines. The only
   backup was written to the session scratchpad
   (`freeze.log.contaminated.bak`), which is session-scoped — assume it is gone by the time
   you read this.
4. **The isolated-root copy completed in under a second**, which is APFS copy-on-write
   cloning. Clones diverge on write so isolation holds, and the 865-file hash comparison is
   the actual proof — but if you distrust that, the cheap re-verification is to re-run the
   harness and confirm the same result.

## Verification baseline

```text
python -m pytest -q       43 passed   (was 42; +1 regression test)
cd frontend && npm test    4 passed   (unchanged, not re-run this session)
cd frontend && npm build   successful (unchanged, not re-run this session)
```

`scripts/freeze.py --status` runs correctly and writes nothing. `data/freeze.log` stays at
one line across a full test run.

## Non-negotiable invariants

Unchanged from the previous handoff, repeated because they are the point:

- First successful pre-deadline archive wins and is never overwritten.
- Resolve the frozen GW3 forecast only after official finalization.
- Shadow outputs are evaluation-only and must never reach `decisions.py` or live UI routes.
- Keep official FPL account writes outside this application.
- Preserve point-in-time integrity.
- Do not claim statistical confidence from zero or one resolved forecast window.
- Do not let frontend work threaten the Thursday code freeze or Saturday archive.
