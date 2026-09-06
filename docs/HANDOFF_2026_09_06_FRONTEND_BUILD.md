# Handoff — frontend build session, 2026-09-06

## Why this branch exists

Joe approved implementation of `docs/FRONTEND_SPEC.md` before GW4, but the first immutable
v9 archive is still pending. Frontend work is therefore isolated on `codex/frontend-v1`.
The repaired model and scheduler path on `main` has not been changed.

The approved spec and the final audit-handoff note were committed locally on `main` as
`e148523` before this branch was created. A push attempt was rejected by the execution
policy because trust for the external `origin` had not been established in this session;
that commit and the frontend branch are local unless a later operator explicitly pushes.

## What was built

### Analysis boundary

`scripts/frontend_data.py` joins the official cache, minutes, projections, decisions,
evaluation, fixture, creator and journal artifacts into one coherent frontend payload.
It:

- requires minutes, projections and decisions to agree on the target gameweek;
- creates a stable `analysis_run_id` from the target and source timestamps;
- recursively removes every `shadow_*` field from players and plan routes;
- re-scores the same six-week optimizer candidates over the first two weeks without
  rerunning or overwriting `data/projections.json`;
- exposes source times, official completeness, odds/fallback weeks and immutable archive
  presence;
- builds the 20-team by 38-gameweek fixture wall, including side-specific attack and
  clean-sheet forecasts;
- prepares honest empty states for creator evidence and model calibration.

Important limitation: the two-week column evaluates the six-week candidate set. It is a
valid horizon sensitivity for those squads, not an independently optimized two-week search.
The UI labels this “same candidate set.”

### Local server and actions

`scripts/frontend_server.py` binds to `127.0.0.1` only, serves the production frontend and
exposes a fixed API. Its permitted mutations are the ones in the spec: refresh caches,
rebuild non-archived analysis artifacts, and append a reviewed journal entry. It has no FPL
submission route and no archive-write route. POST requests with a non-local browser origin
are rejected.

### React interface

`frontend/` contains the Vite/React/TypeScript app. It implements all four rooms:

1. **My gameweek** — readiness first, shirt-shaped squad board, hold plus three real options,
   two/six-week comparison, contribution hinge, player drawer and journal review form.
   A free-form same-position swap editor uses the full projected player pool; its preview
   is explicitly unscored, stays in browser state and cannot be journaled until rebuilt.
2. **Expert room** — an honest GW4 empty state now, with consensus-by-player and claim views
   ready for extracted findings.
3. **Fixture wall** — all 20 teams and 38 gameweeks, frozen headers/club column, past/future
   distinction, owned/scenario clubs, and neutral/attack/defence views.
4. **Model form** — an intentionally empty calibration state until forecasts resolve, with
   the six-independent-gameweek milestone and a visible shadow-model boundary.

The visual language follows the approved “fantasy sticker-board”: flat pitch, shirt tabs,
match-ticket yellow, one playful display face, and quieter analytical rooms. It does not
copy FPL branding, use player portraits, or imply model certainty.

## Current live-cache result

At the implementation check, the generated view model was `gw4-b76e2b850d`:

- GW3: 10/10 fixtures provisionally settled, official `data_checked` still false;
- GW4 target, four displayed plans (hold plus three alternatives);
- market-backed GW4–5 and fallback GW6–9;
- GW4 expert findings: empty;
- immutable GW4 archive: pending;
- no measured decision margin.

Chelsea's GW4 side-specific cell was checked against Hull's inverse cell: Chelsea 2.609
team xG / 44.8% clean sheet versus Hull 0.802 / 7.4%. This caught and fixed an early
adapter bug that could have reused the first side encountered for both teams.

## Verification completed

```text
python -m pytest -q       40 passed
cd frontend && npm test   4 passed
cd frontend && npm build  production bundle built successfully
```

The built HTML and `/api/analysis` were both served successfully from the loopback server.
The production JS bundle is about 218 kB before gzip and 68 kB after gzip.

## Run it

```bash
cd frontend
npm install
npm run build
cd ..
python scripts/frontend_server.py
```

Then open `http://127.0.0.1:8765`.

On macOS, `Open FPL Decision Room.command` provides a one-click build, server and browser
launcher. Closing that Terminal window stops the server.

## Honest remaining work

- Add a browser-level interaction test once an approved browser harness is available. The
  adapter, TypeScript and production build are verified; screenshot-level visual QA remains
  a human/browser pass.
- Decide whether to generate an independent two-week optimizer artifact. Do not get it by
  silently overwriting the six-week cache.
- Add submitted-team manual confirmation only if Joe chooses that policy.
- If a Terminal window is still too much friction, package the launcher as a native `.app`;
  the current `.command` file already removes the need to type commands.

Do not let frontend completion delay or mutate the GW4 first-success archive. The archive
remains more important than this branch.

## Later on 2026-09-06: GW3 wait and early GW4 evidence

Two fresh official-data checks after the final fixture still returned all 10 fixtures as
provisionally settled, while GW3 remained `finished: false`, `data_checked: false` and
`bonus_added: false`. Do not resolve `minutes/gw03.jsonl` or rebuild the GW4 model from
the supposedly complete round until those official flags change. `check_team.py` is clean
for the last saved squad: legal XI, all starters available, valid captain/vice and a fit
first substitute.

The refresh found two genuine GW4 creator videos. Both were extracted under the
`gameweek-brief` contract and recorded in the ledger:

- FPL Raptor: 57 findings from an early Sunday Wildcard draft.
- FPL Harry: 40 findings from an early Sunday transfer/chip draft.

The current owned-player read is strongly positive on Rogers and João Pedro; mixed on
Tzolis and Bruno Fernandes; positive on Calafiori and Gibbs-White; negative on Shaw; and
concerned about Szoboszlai's open-play threat despite agreement that his minutes are secure.
Both creators treat João Pedro as a leading GW4 captain, generally beside Palmer.

This run exposed two validation traps and fixed them. Claim checks are now deferred until
the referenced gameweek is officially `finished` and `data_checked`; a sentence naming
several players is not applied indiscriminately to every player; and “scored six points”
is no longer read as “scored a goal.” The roster trim now retains flagged zero-minute
players after Saliba was omitted from the vocabulary, and the observed “Celiba” alias was
recorded. “Bayas” remains unresolved because its identity is not proven.

Once GW3 finalizes: resolve the minutes archive first, refresh the element histories, rerun
the GW4 consolidation with official claim checks, and inspect the Tzolis disagreement. The
pre-finalization minutes file had Tzolis at 52.3 expected minutes / 42.1% for 60+, while
Raptor points to his GW3 90 minutes as evidence the earlier role doubt may have eased.
