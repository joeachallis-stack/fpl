# Ideas & Roadmap

Working backlog for the FPL assistant. Nothing here is committed to a schedule — it's the
shape of the thing being built, and the open questions that block each piece.

## The objective (revised 2026-09-02, from the decision-engine brief)

**Maximise total points by the end of the season.** Not overall rank, not mini-league
position.

This supersedes an earlier answer in the same session where Joe picked "overall rank" when
asked to choose. The written brief is the authority.

The two are closer than they look — maximising expected points is approximately
maximising expected overall rank, because rank is a monotone function of points across a
9M-entry field. The real consequence is **risk posture**: a points-maximiser is
risk-neutral and ignores the field.

Tractable proxy, from the brief: a 6-gameweek rolling horizon with a terminal value term
that prices unused chips, banked transfers and squad quality, so the optimiser doesn't
burn everything inside the window. Solve six, execute one, re-solve weekly. Never
pre-commit to the printed multi-week plan.

Downstream consequences:

- Effective ownership and template hedging **drop out of the objective**. Keep global
  ownership as displayed context so the variance is visible; never let it into the
  optimiser.
- Mini-league standings stay read-only colour.
- Team value is a tiebreaker, never an objective term.

## Data audit and build order

Full audit of every input against the brief (A = have it, B = available not wired,
C = doesn't exist cleanly), answers to the four open decisions, and the sequenced build
order: **https://claude.ai/code/artifact/0aa2b619-df39-4715-916e-6bac79174ed3**

Headline results — 15 A, 6 B, 5 C across 26 items. The four decisions, settled:

1. **Cut effective ownership from the objective**, keep it as a reporting field.
2. **Minutes: build the cheap empirical distribution first.** Predicted XIs are strictly
   less information and an external dependency; add only if the journal shows minutes
   error dominating.
3. **Derive free transfers, don't add a session cookie.** Already working. The live-squad
   limitation costs ~nothing given a Thursday solve.
4. **Split the backtest.** Calibrate free-transfer and money-in-the-bank shadow prices on
   2025/26 — verified available and complete (vaastav
   `data/2025-26/gws/merged_gw.csv`, 29,757 rows, GW1–38, all DefCon columns). Do **not**
   trust chip values from it: a Bench Boost is worth whatever the one big double gameweek
   that season was worth, and a single season can't turn that into a distribution. BPS was
   retuned for 2026/27, and that error is **directional, not symmetric**: the change from
   1 BPS per 2 CBI to 1 per 3 was made to reduce overlap with DefCon, so it shifts bonus
   away from clearance-heavy centre-backs and toward attacking contributors (dropping the
   −1 for being tackled pushes the same way). Anything trained on 2025/26 to learn *which
   player types collect bonus* will systematically overvalue defensive bonus — correct for
   it or exclude bonus from what you learn. Chip structure, by contrast, is clean: 2025/26
   was the first two-set, no-Assistant-Manager season, matching 2026/27 exactly, so
   chip-timing behaviour backtests honestly (2024/25 and earlier do not — different chip
   menu *and* no DefCon). The transfer threshold still gets calibrated in-season from the
   journal regardless.
   *(An earlier version of this said the data didn't exist. It does — that was my error.)*

### Highest priority: never miss a pre-deadline freeze

**The track record is the bottleneck, and it can only be built forward.** As of
2026-09-05 there are no files in `projections/` or `decisions/`, `minutes/` holds only
GW3, and `data/evaluation.json` reports zero resolved forecasts. Every constant in the
model — the 900/450-minute attacking priors, the 0.85 horizon discount, the fitted
half-lives — is an assumption against 2026/27 until frozen forecasts resolve.

A late archive is not a worse forecast, it is not a forecast. Re-running after a
deadline reads an `element_summary` containing the played gameweek, a minutes model
retrained on it, moved odds and changed prices. The archives refuse to overwrite for
exactly this reason, so a missed deadline is a permanent hole.

Automated 2026-09-05 by `scripts/freeze.py` under a launchd agent
(`scripts/com.joechallis.fpl-freeze.plist`, hourly). The script runs often and almost
always does nothing: it exits unless a deadline is inside `FREEZE_LEAD_HOURS` (12) and
an archive is actually missing, then archives only the missing steps. A step that
refuses — `projections.py` declines a partial gameweek of odds — does not block the
others, and the next run retries. launchd fires a missed `StartInterval` job when the
machine next wakes, so a sleeping laptop catches up rather than losing the gameweek.

**Resolving is automated too, added 2026-09-05.** Automating only the freeze reproduces
the failure this project already had: a pile of perfect frozen forecasts that nothing ever
scores. The same hourly job now also resolves every finalized gameweek whose minutes,
projections or journal record is still unresolved, then refreshes `data/evaluation.json`.
The two phases have opposite timing constraints — the freeze can never be redone and the
resolve can never be early — so resolving runs on every pass regardless of the freeze
window, and is safe to repeat. Detection uses explicit `resolved_at` markers, with
non-null actuals only as backward compatibility for older archives. Before setting those
markers, the job completes a fresh all-player summary pull; an interrupted bulk pull exits
nonzero and is retried rather than permanently blessing partial actuals.

Consequences accepted deliberately:

- First success wins, so a freeze at T-11h locks in staler team news than T-2h. A
  stale-but-honest forecast beats a hole. Keeping the laptop open near a deadline still
  produces a better archive. This is a deliberate safety policy: replace-until-deadline
  could retain later information, but depends on a correct clock, deadline parser and
  conditional overwrite guard. Never-overwrite is unconditional and therefore easier to
  audit. Revisit only with append-only timestamped forecasts, not an overwrite exception.
- If the freeze lands at T-11h and the real transfer is made at T-1h on late news, the
  decision archive will not match the action taken. That is fine as long as
  `journal.py add` records what was actually done — the mismatch measures what late team
  news is worth.

For GW4, implementation changes stop **Thursday 2026-09-10 at 12:30 UTC**, 48 hours
before the published deadline. The installed hourly agent then runs the same code through
Saturday. Only documentation edits are allowed in that rehearsal window; any unfinished
repair is reverted before the cutoff. Inspect `freeze.py --status` and `data/freeze.log`
without forcing an early real archive.
Timeline this buys, given the international break (GW5 is 18 Sep, GW6 is 10 Oct): first
resolved lead-1 error ~15 Sep, six lead-1 samples ~2 Nov, six samples at every lead
~5 Dec. Because each archive spans a six-gameweek horizon, lead-*k* error gets its first
sample only *k* weeks after the first archive. Do not retune a component before that
window fills; `evaluate.py` splits by `model_version`, so changing a model mid-series
resets the count toward six comparable archives.

Statistical power is thinner than the row counts suggest. With 63 contenders per archive,
six weeks of lead-1 forecasts is ~378 contender player-weeks. Event rates in the current
ledger (622 played rows): DefCon threshold hits 9.6%, goals 8.5%, assists 8.5%, bonus
10.0%, clean sheets 19.6%, yellows 11.9% — but red cards 0.16%, own goals 0.64%,
penalties missed 0.16%, penalties saved 0%. Expect to detect component *bias* well before
component RMSE is tunable, and accept that red-card and penalty events will not be
measurable this season. Keeping them as an explicit residual is the permanent answer,
not a placeholder.

### Urgent, before the next fetch

`fetch_data.py` overwrites `bootstrap.json` on every run. Set-piece order
(`penalties_order`, `direct_freekicks_order`, `corners_and_indirect_freekicks_order`) is
the **only** input the API does not backfill — `element_summary[].history[]` gives price
and ownership retrospectively, but not this. Every fetch destroys the evidence that
penalty duty changed. Dated snapshots are one line and unrecoverable retroactively.

## Built

1. **`fetch_data.py` gaps** — `event-status/`, `element-summary/` for owned players,
   `leagues-classic/{id}/standings/` for leagues under 500 entries.
2. **`state.py`** — derived state, no hand-maintained file: banked free transfers
   reconstructed from history, chip windows from `bootstrap.chips`, next deadline.
3. **`check_team.py`** — pre-deadline checklist. Rules read from the live
   parameterization, not hardcoded.
0. **Dated `bootstrap.json` snapshots** (`fetch_data.py` → `data/snapshots/`), added
   2026-09-03. One a day; catches set-piece order changes the live API doesn't backfill.
4. **`journal.py`** — decision journal, added 2026-09-03. `add` logs a recommendation
   with its runner-up and reasoning; `resolve` pulls both players' actual gameweek
   points from `event/{gw}/live/` and computes the realized delta automatically, so
   scoring is against the counterfactual, not zero. Entries in `journal/entries.jsonl`,
   tracked in git. Tested end-to-end against the real GW2 captaincy call (João Pedro
   over Rogers, resolved delta +4) before being cleared for the real season.
5. **`fetch_news.py`** — news log, added 2026-09-03. Pulls three free RSS feeds
   (Fantasy Football Scout, FPL Hints, FPL Toolbox) and appends new items to
   `news/entries.jsonl` — headline, link, summary, published date, and when this
   project fetched it. Runs automatically from `fetch_data.py`, no separate
   schedule. Git-tracked, not gitignored: RSS feeds only show recent items, so an
   entry not caught before it scrolls off is gone for good — the same
   unrecoverability problem set-piece order had before `data/snapshots/`. Headlines
   only, no analysis or judgment — that's the LLM layer's job, not this script's.
   Injury data (`premierinjuries.com`) and predicted lineups have no free feed and
   are deliberately not scraped yet; see `docs/DATA_SOURCES.md` for the candidates
   and `WebSearch` covers them for now.
6. **YouTube video transcripts**, added 2026-09-03. Upload detection via each
   creator's public video RSS feed (5 of the named creators — Ben Crellin and
   BigMan Bakar excluded, no dedicated channel to filter from a shared one yet).
   A raw scrape of the caption endpoint every unofficial library relies on
   returned `HTTP 200` with an empty body — confirmed not a cloud-sandbox
   artifact, reproduced from a real residential IP — but `yt-dlp`'s own
   extraction is a different code path and works: **59 of 65 real transcripts
   (91%)** on the first run, the other 6 explained (4 age-restricted on one
   channel, 2 unstarted livestreams) rather than mysterious. Hit YouTube's rate
   limit after ~4 back-to-back pulls; fixed with a 2-second delay, verified by
   recovering all 5 rate-limited videos afterward. Transcripts are cleaned plain
   text under `news/transcripts/`, referenced by path from `news/entries.jsonl`,
   not inlined. See `docs/DATA_SOURCES.md` for the full writeup.
7. **Price-change watch**, added 2026-09-04. `show_team.py` now surfaces strong
   price-movement signals for owned players from FPL's own `bootstrap-static`
   projections. It shows the earliest projection within two days whose signed
   likelihood reaches an absolute value of 4, plus net gameweek transfers. This is
   an official FPL projection, not a third-party model, but the endpoint is
   undocumented: its formula and likelihood calibration are unknown, so the output
   deliberately labels it as a projection rather than a guaranteed change.
8. **Bookmaker-odds ingestion**, added 2026-09-04. `scripts/odds.py` fetches UK
   `h2h,totals` markets from The Odds API, stores the reproducible raw response, removes
   each bookmaker's margin independently, takes component medians and renormalizes them,
   then matches the result to official FPL fixtures using explicit team aliases plus
   kickoff time. The first run matched all 19 returned events with zero unmatched.
   `fetch_data.py` calls it as an optional source with a two-hour cache; missing keys or
   API failures cannot block the official refresh. This is ingestion only — the derived
   probabilities are not yet wired into player projections or decisions.
9. **Auditable one-gameweek xP baseline**, added 2026-09-04. `scripts/projections.py`
   combines the existing minutes distribution with an independent-Poisson match model
   fitted to de-vigged 1X2 and over/under 2.5 probabilities. It allocates team attacking
   expectation using official xG/xA rates shrunk by 180 minutes toward position averages,
   and estimates cards, DefCon, saves and bonus from player history shrunk toward live
   position priors. Every scoring component, source count, fit error and known limitation
   remains visible per player. It refuses to rank a partial ten-fixture gameweek. Rare
   penalty/own-goal events and uncalibrated player props remain explicitly unmodeled.
   `archive`/`resolve` provide the same non-rewriteable measurement discipline as the
   minutes ledger; the model reads scoring weights from live `game_config.scoring`.
10. **Finalized observations, multi-GW forecasts and walk-forward evaluation**, added
    2026-09-04. `observations/player_fixtures.jsonl` stores actual component data once per
    finalized player-fixture and revisions official corrections. `projections.py` now
    emits a configurable horizon (default six): bookmaker fixtures first, then a labeled
    fallback using odds-calibrated venue/FDR goal buckets adjusted by recent team xG and
    xG-conceded factors shrunk toward league average. It handles blanks and multiple
    fixtures per gameweek without overwriting. Pre-deadline calibration weights select
    owned players plus top horizon-xP and xP/value candidates by position; ownership is
    display-only. `evaluate.py` separates all-player diagnostics from decision-weighted
    primary error and reports each forecast lead independently. Archives retain minimal
    forecasts for everyone but full audit inputs only for fitting-relevant players,
    reducing the tested weekly archive from ~2.9 MB to ~482 KB.
11. **Whole-squad decision optimizer**, added 2026-09-05. `scripts/decisions.py` uses a
    mixed-integer solver to find the hold baseline, top three exact one- and two-transfer
    squads, and best exact three-, four- and five-transfer squads. It reconstructs each
    owned player's selling price, enforces live budget/position/club rules, and chooses a
    legal XI and captain independently in every horizon gameweek. Prices, hits and
    next-week transfer stock remain explicit. When live chip windows allow it, the same
    machinery emits one-week Free Hit and horizon Wildcard squads. Planned XI/captain xP
    is the exact ranking objective; vice takeover and autosub expectations are displayed
    separately under an explicit independent-appearance assumption, because the current
    early-season `p_zero` estimates are not calibrated enough to drive squad selection.
    `decisions.py archive` freezes the full point-in-time search without overwriting, so
    the journal's chosen action and runner-up can later be audited against the candidates
    and prices that were actually available.

12. **Cross-season hierarchical minutes training**, added 2026-09-05. The first proposed
    peer-smoothed model was rejected before integration because, when tested only within
    2025/26, it scored worse than the existing empirical baseline for established
    contenders. The corrected experiment uses safely code-matched 2024/25 rows as
    prehistory and predicts 2025/26 forward without future leakage. A small walk-forward
    grid selected a three-GW half-life and only 0.5 effective position/price-peer rows,
    evidence that role should update quickly and peer priors should mainly stabilize cold
    starts rather than overpower player history. `models/minutes_params.json` tracks the
    source hashes, complete grid, selected parameters, early/later and all/contender
    metrics, probability calibration bins and explicit unfitted assumptions. Live rows
    freeze their effective current, prior-season and peer weights. The old heuristic path
    remains an automatic fallback when the historical cache is absent. The gain is
    deliberately recorded as modest: versus the old empirical model on the comparable
    later-GW contender slice, band log loss improved 0.7851 -> 0.7734 and Brier
    0.4501 -> 0.4364, but minutes MAE worsened 25.65 -> 26.33. The combined selection
    score moved only 1.0701 -> 1.0659. This is a better-calibrated early-history bridge,
    not a claim that minutes are solved.

    **Richer minutes states, added 2026-09-05.** The model now retains eight joint
    role/minutes outcomes: unused; cameos at 1-29, 30-59 and the rare 60-plus case; and
    starters at 1-59, 60-74, 75-89 and 90-plus. Existing bands and expected minutes are
    derived summaries, while start/cameo probabilities and conditional minutes remain
    available for role security and future DefCon work. Against an independently tuned
    coarse-band challenger on the same folds, the richer representation improved log
    loss 0.77717 -> 0.77697, Brier 0.43849 -> 0.43836, minutes MAE 26.398 -> 26.385 and
    combined score 1.07048 -> 1.07013. This is a narrow measured win, not a material jump.

    **GW4 model-input audit and fixes, 2026-09-05.** The live run found three material
    issues before any recommendation was made:

    - `element-summary` already contains all-zero rows for an unstarted current-GW
      fixture. `minutes.py` and `projections.py` had accepted every row whose round was
      before the target GW, so an unplayed Everton-Man Utd row was learned as a genuine
      nonappearance for Barry and Mbeumo. History inputs must be joined to `fixtures.json`
      and limited to completed (`finished_provisional` or `finished`) fixtures. Fixed in
      both models through one shared filter; live/unfinished rows no longer count.
    - The 180-minute attacking prior gives two-match outliers too much control over team
      goals. Barry's 1.93 xG in 147 minutes became a 48% Everton goal share; De Cuyper's
      one 1.47-xG match became a 22% Brighton share. Raising only this prior to 900 minutes
      changed the best one-transfer move and cut the leading two-transfer gain from 15.62
      to 9.46 xP. Fixed with a transparent prior-season blend: a player's latest official
      season rate is shrunk 450 minutes toward position, then weighted as 900 minutes
      against completed current evidence. These weights are starting assumptions, frozen
      with raw inputs for walk-forward recalibration. Yellow/red/save rates use the same
      blend; prior bonus and DefCon are excluded where the historical aggregates are not
      comparable or cannot reconstruct the scoring threshold.
    - The later-GW FDR fallback fits ten venue/difficulty buckets from only 36 currently
      priced team-sides. Three buckets have no observations and the resulting rates are
      not monotonic with difficulty. Five of the six horizon weeks use this fallback;
      only 1.81 of Barry's reported 9.56 one-transfer gain came from bookmaker-backed
      GW4. Store coverage counts and replace or constrain this fallback before using its
      six-week differences as decision-grade evidence. Fixed by a weighted monotonic fit
      for each venue. Coverage counts, pre-fit rates and sparse flags are now shown; the
      live build currently labels 5/10 buckets sparse from 30 usable market team-sides.

    These changes make the inputs inspectable; they do not turn the early-season ranking
    into a recommendation. Rebuild after GW3 settles and use resolved archives to test
    whether the explicit 900/450-minute starting weights should survive recalibration.

13. **DefCon threshold model**, added 2026-09-05. Replaced the current-season hit-rate
    estimate multiplied by `p60` with a direct probability of crossing the official action
    threshold. Clean-sheet scoring still requires and uses `p60`; DefCon does not. The model
    partially pools each player's recency-weighted actions per 90 toward position peers,
    evaluates an overdispersed count tail inside every predicted role/minutes state, and
    applies opponent/venue factors only because both survived walk-forward ablation. On
    8,982 contender forecasts, log loss improved 0.35911 -> 0.33996 and Brier
    0.10838 -> 0.10500. A corrected hit-rate baseline without the erroneous p60 multiplier
    reached 0.34725, while collapsing the richer minutes distribution to one expected-minutes
    value worsened log loss to 0.40309. The model and its full audit live in
    `models/defcon_params.json`; only 2025/26 has the necessary action fields, so cross-season
    transport remains explicitly unmeasured.

### Defensive and goalkeeper scoring — agreed sequence

Build these one measured component at a time rather than turning them into one opaque
"defence model":

1. **Goalkeeper save thresholds — BUILT 2026-09-05.** Replaced the linear `expected saves / 3`
   approximation with a distribution over save counts, mixed over the minutes model's
   role states. FPL awards a point at 3, 6, 9, ... saves, so the target is
   `E[floor(saves / 3)]`, not a fractional point for every save. Estimate a recency-
   weighted keeper rate with partial pooling; test opponent, defending-team and venue
   factors by walk-forward ablation. Both 2024/25 and 2025/26 contain saves, allowing a
   cleaner cross-season test than DefCon. Historical bookmaker odds are unavailable, so
   they were not backfilled with actual results. Walk-forward testing on 856 contender
   keeper forecasts selected a 12-GW half-life, 900-minute player prior, dispersion 0.25
   and opponent-only fixture factor. Save-point RMSE improved 0.64510 -> 0.59400 and the
   old model's +0.233-point bias fell to -0.001. Defending-team and venue factors made the
   result worse and were excluded. The role-state mixture beat expected minutes on RMSE
   (0.59400 vs 0.59859), though expected minutes had slightly lower MAE (0.50807 vs
   0.51871); selection uses RMSE because squared error is proper for a conditional mean.
2. **Clean-sheet and goals-conceded exposure — BUILT 2026-09-05.** Kept the bookmaker/FDR
   opponent-goal model unchanged, but integrated its Poisson outcomes inside the full minutes states.
   Clean-sheet points still require 60 minutes, while a player substituted after 60 keeps
   the clean sheet if no goal was conceded during his own time on the pitch. Goals-conceded
   deductions are also nonlinear (`floor(goals / 2)`) and now use the same exposure
   mixture instead of one expected-minutes value. The transform reads both point values
   from the live scoring configuration and freezes state-level exposure, clean-sheet and
   2+/4+/6+ goal probabilities. A deliberately weak but genuinely pre-match historical
   comparison used the fixed 2024/25 league goal rate to predict 2025/26. On 9,804
   contender rows, combined RMSE changed only 1.24918 -> 1.24899 and MAE was effectively
   unchanged at 0.71267. That is evidence of neutral forecast impact, not a meaningful
   accuracy win; the change earns its place because it implements the scoring/exposure
   rules correctly without degrading the aggregate result. The test does not validate
   the separate bookmaker/FDR goal-rate model.
3. **Bonus — designed 2026-09-05, build trigger set. Not yet built.**

   The original plan was to wait for enough 2026/27 weeks to fit a player-type model.
   That framing is wrong, and it is why this component kept getting deferred: it assumes
   we must learn *which players collect bonus*, which is exactly what the 2026/27 BPS
   retune makes unlearnable from history.

   Two structural facts change the approach.

   **Bonus is a rank statistic, not a rate.** Three bonus points go to the top BPS scorer
   in each match, two to second, one to third. The current shrunk per-player rate ignores
   this entirely — it cannot represent two Arsenal defenders competing with each other for
   the same bonus, or the fact that a 4-0 win hands out the same three bonus points as a
   1-1 draw. Any per-player rate model is structurally wrong here regardless of how well
   it is calibrated.

   **The BPS table can be learned from our own ledger rather than sourced.** BPS is a
   linear function of counted actions. The API does not publish the award table and
   `docs/RULES_2026_27.md` only records that it was "tweaked", but the ledger stores both
   `bps` and its inputs, so a regression recovers the coefficients directly. On the 622
   played rows currently available it returns recognisable values — goals +22.13, assists
   +11.34, clean sheet +5.53, yellow -4.71, own goal -8.06 — at R2 = 0.783. This
   automatically tracks the current season's rules with no external dependency and no
   2025/26 contamination, which is precisely what the deferral was waiting for.

   **The missing 22% is irreducible and must be modelled as noise, not ignored.** FPL
   counts passes completed, big chances created, shots on target, dribbles, fouls,
   offsides and errors leading to a goal, none of which the API exposes per player.
   Residual SD is 5.68 BPS against a total SD of 12.19.

   Measured viability, ranking players within each match on BPS predicted from observables
   alone: **80.6% of actual bonus recipients correctly identified** (50/62), with the whole
   bonus set exactly right in 45% of fixtures. Ranking on actual BPS recovers 100% by
   construction, so that 19-point gap is the cost of the unobserved fields.

   Note carefully that 80.6% uses *realized* components. Production would feed *projected*
   components, so it is a hard upper bound and the realistic figure is materially lower.

   Proposed implementation, reusing what already exists:

   1. Fit BPS coefficients on current-season ledger rows; freeze them into each projection
      archive alongside the scoring rules, as the other components already do.
   2. Monte Carlo per fixture: draw each player's components from the existing minutes,
      goals, assists, clean-sheet, saves and DefCon distributions; compute BPS from the
      fitted coefficients; add a N(0, residual SD) term for the unobserved fields; rank;
      award 3/2/1.
   3. Average across draws for expected bonus per player. The noise term matters — without
      it no player would ever be uncertain of bonus, which is plainly false.

   **Build trigger: roughly GW8-10.** The blocker is ledger volume, not frozen archives —
   16 coefficients on 622 rows is thin, and the ledger grows about 600 rows a week, so
   ~2,500 rows by GW8 is comfortable. This is on a *different clock* from the rest of the
   backlog, which waits on resolved forecasts.

   Worth keeping in proportion: bonus is 7.0% of all points scored in the ledger so far.
   This is a real component, not a decisive one.
4. **Penalty saves — defer.** Preserve them in observations, but do not fit a noisy
   player-specific rare-event model without enough evidence. A strongly pooled future
   model must beat an explicit zero/frequency baseline before earning a place in xP.

For each component, evaluate all players diagnostically but select parameters on the
pre-deadline-reproducible contender population. Freeze source hashes, parameters,
intermediate rates and threshold probabilities so later recalibration can explain why a
forecast changed.

### Component-level projection evaluation — built 2026-09-05

`scripts/evaluate.py` now attributes forecast error instead of reporting only total xP
error. For each finalized player-fixture it reconstructs actual appearance, goal, assist,
clean-sheet, goals-conceded, card, DefCon, bonus and save points from the observation
ledger and the scoring rules frozen with that projection. Own goals and penalty saves are
reported as an explicit unmodeled residual; penalty-miss deductions are modeled from v9
onward, while schema-aware evaluation keeps them residual for older archives. Any
remaining unexplained point is a hard accounting warning rather than being silently
assigned to a model.

Double-gameweek fixtures are scored separately and then aggregated to the same player-GW
unit as the forecast. Output separates unweighted all-player diagnostics from metrics
using the contender weights frozen before the deadline, and breaks both out by forecast
lead and projection model version. MAE, RMSE, bias, predicted mean and actual mean are
retained for each component. The archive keeps compact component vectors for diagnostic
players and full inputs for contenders, so all-player component grading remains possible
without returning to the earlier multi-megabyte format. The current 1,236 finalized
observation rows reconstruct official total points exactly. There are no frozen projection
archives yet, so real forecast-error tables begin with the next pre-deadline archive.

### Prior-season weight — measured 2026-09-05, retained as a shadow challenger

The GW4 input audit found `effective_prior_minutes` was a flat 900 for every player,
regardless of how much prior evidence existed. 140 players carried under 900 prior minutes
and were credited with 900; 123 carried over 2,000 and were also credited with only 900.
The consequence lands where it matters most: Bruno Fernandes had 3,065 prior minutes at
0.298 xG/90, and 180 current minutes at 1.05 dragged his blend to 0.424 — a 42% swing off
two matches, on the most captained player in the game.

**This question did not need frozen archives**, which is why it was worth doing now. It
involves only player xG rates and two complete cached seasons, so `scripts/train_priors.py`
answers it walk-forward: at each 2025/26 cutoff, blend the 2024/25 prior with
current-season-to-date evidence and score against what actually happened over the next six
gameweeks. 7,441 player-cutoff samples across 314 players.

The ordering is the finding. Every evidence-scaled scheme with a generous cap beat every
flat scheme on future xG:

| scheme | weighted MSE |
|---|---|
| evidence_capped_2700 | 0.01332 |
| evidence_uncapped | 0.01333 |
| evidence_capped_1800 | 0.01334 |
| flat_1800 | 0.01351 |
| flat_2700 | 0.01357 |
| **flat_900 (incumbent)** | **0.01361** |
| flat_450 | 0.01409 |

Compare `flat_1800` (0.01351) with `evidence_capped_1800` (0.01334): the same ceiling, so
the gain comes from *scaling with evidence*, not from trusting the prior more in general.

**Audit correction.** `evidence_capped_2700` was chosen as the lowest-error member of the
grid and then given a paired test on those same 2025/26 samples. Its reported **t = -1.68**
is therefore selection-biased, just like the earlier ratings headline. For assists the same
policy costs a non-significant t = +1.08, and the implementation also changed cards and
fallback saves without evaluating them. The live model has returned to flat 900 for every
field. `evidence_capped_2700` is frozen alongside it as a decision-inert shadow affecting
xG and xA only.

The historical effect remains useful for sizing the challenger, not for claiming it works.
Adoption is reconsidered only after at least six resolved archives, with paired total-xP
error primary and xG/xA component error supporting.

The shadow shares the live archive rather than creating another model-version split.
`MODEL_VERSION` is now `baseline-v9-penaltyfix`.

### Penalty duty — built and wired in 2026-09-05

`penalties_order` had been snapshotted daily since 2026-09-03 specifically because the API
never backfills it, and nothing read it. That was an omission rather than a missing
refinement: the projection allocates team goals by xG share and **official xG already
includes penalties**, so a player who had just gained duty got no credit, one who had lost
it kept credit he no longer earned, and an established taker was paid only diffusely
through an inflated share.

`scripts/set_pieces.py` splits the team's goal expectation. Penalties are modelled
explicitly and assigned to whoever is on duty; the remainder is allocated by xG with the
estimated penalty component removed, which is what stops a taker being paid twice. Total
is conserved — anything not assignable to a known taker returns to the generic goal
allocation pool — while a separate assistable lambda removes every expected penalty.
Penalty-miss deductions are assigned with the same duty probabilities.

**The rate came from our own data, not an assumption.** There is no `penalties_scored`
field anywhere in the API, but `penalties_missed` exists, and missed volume at a known
conversion rate implies taken volume: 14 and 15 misses over 760 team-matches in the two
cached seasons give 0.088 and 0.094 penalties per team-match at 79% conversion. Consistent
across seasons, but resting on ~15 events, so the sampling error is wide. A first-choice
taker playing full matches is worth about 0.074 goals per match from penalties.

The first implementation reported **22.0 total absolute horizon xP moved across 653
players**, but that number is retracted: it applied availability inside the per-90 penalty
rate and again when converting the rate to expected goals, and it omitted miss deductions.
The corrected v9 implementation applies minutes once and will be judged from frozen output.

For audit history only, these are the retracted v7 deltas and must not be used:

| player | order | P(takes) | delta horizon xP |
|---|---|---|---|
| Palmer | 1 | 0.860 | +0.381 |
| Haaland | 1 | 0.884 | +0.352 |
| Saka | 1 | 0.692 | +0.255 |
| B.Fernandes | 1 | 0.987 | +0.080 |
| Cherki | none | 0 | -0.268 |
| Gakpo | 3 | 0.024 | -0.222 |

The earlier interpretation of Fernandes' small change is also retracted because it relied
on the faulty double-minutes calculation. The structural expectation remains that an
established taker's historical penalty xG offsets much of the explicit allocation, but v9
must establish the size honestly.

The snapshot change detector immediately paid for itself. Between 4 and 5 September:
Woltemade joined Juventus on loan and lost Newcastle's duty (1 -> None), Osula was promoted
(2 -> 1), Barry took over at Everton (2 -> 1), and Watkins came off Villa's list. Osula
correctly still projects zero because he carries a foot injury — the availability override
and the set-piece model compose properly.

Assumptions that remain unmeasured and should face an ablation once archives resolve: that
penalty rate scales proportionally with a team's attacking strength, and that current duty
held across the history each player's xG rate was measured over. The second is wrong
exactly when duty has changed, which is what `order_changes()` is for.

**Corners and direct free kicks were measured and deliberately not priced.** The obvious
next step was to give them the same treatment as penalties. On 291 players with 900+
minutes last season, designated corner takers carry 2.26x (DEF) and 2.45x (MID) the xA per
90 of non-takers, and direct free-kick takers 2.52x and 1.88x. Both look compelling and
neither can be used:

- **Confounded.** Creative players are chosen to take corners, so the ratio mixes the
  effect of the duty with the selection into it. Separating them needs within-player duty
  changes, and set-piece order has only been snapshotted since 2026-09-03.
- **No derivable rate.** `penalties_missed` let the penalty rate be recovered from our own
  data. Nothing counts corners or free kicks taken, so any allocation would rest on an
  invented number, double-counted against an xA rate that already contains the effect.

Direct free kicks also contribute essentially nothing to goals — 0.73x for defenders and
1.14x for midfielders, neither meaningfully above one — which removes the most obvious
version of the idea entirely.

What is built instead is the part that is honest and cheap: `order_changes()` now covers
all three orders, and every projection carries `set_piece_duty` plus
`set_piece_duty_changes`. A non-empty change list means the player's own history predates
his current role, so his xG/xA rate deserves less trust than its sample size suggests.
Twenty players currently carry that flag. This prices nothing and flags everything, which
is the correct treatment for an effect that is real but not identifiable.

### Team attack/defence ratings — built and validated 2026-09-05, not yet adopted

`scripts/ratings.py` fits an independent-Poisson team model,
`log lambda = mu + home_advantage + attack[team] - defence[opponent]`, by weighted
maximum likelihood with exponential time decay and an L2 penalty toward a per-team prior.
`scripts/train_ratings.py` selects it walk-forward on 2025/26 with 2024/25 as prehistory,
against the FDR fallback replicated in its exact production form.

The motivation is structural, not sample size. Over the live GW4-9 horizon FPL's
difficulty is nearly a per-team constant — six clubs sit at exactly 3.00 with zero
variance — so the bucket fallback cannot distinguish Tottenham from Everton, and no
information about a team can reach that team's later fixture. Ratings are continuous and
per team, so one fixture constrains both sides and a rating applies to every fixture the
team plays.

**Statistical caveats, stated before the numbers.** Every match-side is re-forecast from
up to six cutoffs, and those forecasts share one actual outcome, so `n = 4,260` is really
760 correlated clusters. All standard errors below are cluster-robust on the match-side;
the naive versions inflate every t-statistic by roughly 2x and an earlier version of this
section reported them. There is also **no held-out season** — 2025/26 is both where
hyperparameters were chosen and where they were scored — so the selected parameters are
not validated out of sample, only the model class is.

Walk-forward result, 4,260 scored team-match sides in 760 clusters across 38 cutoff
rounds, Poisson NLL on actual goals (lower is better):

| model | NLL | MAE | RMSE | bias |
|---|---|---|---|---|
| league average | 1.46828 | 0.93959 | 1.11778 | +0.05687 |
| incumbent (FDR tier + 5-match form) | 1.46336 | 0.90601 | 1.11518 | -0.02172 |
| ratings, half-life 730d, prior 8, xG target | 1.44060 | 0.88453 | 1.08577 | +0.01613 |

Ratings win at every forecast lead 1-6 (NLL delta -0.018 to -0.027), which is the point:
the gap does not close as the horizon lengthens.

**Is the headline real, or selection noise? Partly the latter.** Three checks:

- Clustered paired test of the selected model against the incumbent: mean delta -0.02276,
  clustered t = -2.88 (naive t would have said -6.21).
- Selection robustness: **79 of 80 grid candidates beat the incumbent**, median candidate
  gap -0.01585. The *sign* is therefore not an artifact of picking a winner.
- **Nested selection, which is the honest test.** Hyperparameters chosen on 2024/25 alone,
  with 2025/26 never consulted during selection, then scored once: **gap -0.01482,
  clustered t = -1.75.** Not significant.

Those three reconcile exactly, and the reconciliation is the finding:

| estimate | gap |
|---|---|
| best of 80, selected on the evaluation data | -0.02276 |
| median candidate | -0.01585 |
| honest, parameters selected on 2024/25 | -0.01482 |

**The honest gap matches the median candidate, not the best one. The headline's extra
0.008 was the best-of-80 bonus.** Ratings very consistently beat the FDR fallback in sign
— 79/80 candidates, every lead — but the margin is small enough that one season of
evaluation cannot establish it at conventional significance. The correct summary is
"probably real, small, not proven", and earlier versions of this section overstated it.

An earlier claim here that the hyperparameter surface is "flat" was also wrong in a way
that matters. Selection on 2024/25 chose half-life 60 / prior 2; selection on 2025/26
chose 730 / 8, and the two do not perform equivalently out of sample. Part of that is a
genuine weakness in the nested test — the selection environment has no prehistory while
the evaluation environment has a full season of it — but "flat, so the choice does not
matter" is not supported.

**What would fix this is more evaluation data, not more model — and the cached data
cannot supply it.** Three routes were tried or considered:

1. A held-out third of 2025/26: rejected. Randomly sampling games lets the model train on
   matches occurring after held-out ones, which leaks in the direction that matters, and
   it is underpowered anyway — resampling says a one-third holdout detects the true effect
   only 34% of the time (median clustered t = -1.73).
2. **Scoring 2024/25 as a second evaluation season: tried, and it does not answer the same
   question.** It doubles the rows, but 2024/25 has no prior season behind it, so both
   models start cold — and the incumbent degrades far more in a cold start than ratings
   do. Its gap is -0.04867 (t = -4.49) against -0.02276 (t = -2.88) on 2025/26. Pooling
   them gives a flattering -0.03514 at t = -5.30 that answers a mixture of two questions.
   Production always has at least two cached seasons plus the live one behind a forecast,
   so the cold-start regime is one we are never in. 2025/26 stays the primary population;
   2024/25 is retained only as a cold-start diagnostic.
3. 2026/27's frozen archives, accumulating forward. This is the only real answer.

The honest estimate therefore remains **-0.01482 at clustered t = -1.75** on a single
season, and no amount of re-slicing the cached data improves it.

Three things to read honestly:

- **The incumbent is barely better than assuming every team is league average** (1.46336
  against 1.46828). Most of what looked like a fixture model was doing very little work.
- **The win comes from xG and continuous team identity, not from the decay schedule.**
  Every one of the top eight candidates uses the xG target (best xG 1.44060 against best
  goals 1.44637), while half-life is flat from 365 through 3650 days (1.44060 to 1.44069,
  differences in the fifth decimal). Team strength over a two-season window is close to
  stationary. This contradicts the prior expectation that 2025/26 should be weighted much
  more heavily than 2024/25 — recency is not where the signal is. What *does* handle a
  managerial change or regime shift is the odds anchor, not a shorter half-life.
- The incumbent was given every advantage available: historical FDR does not exist in the
  data, so difficulty was proxied by rolling goal-difference tiers that update weekly
  (strictly better than FPL's static preseason FDR), and its buckets were calibrated on
  actual goals rather than the unavailable historical odds. The measured gap is a lower
  bound.

**Promoted teams, and what the prior is actually worth.** Sides with no top-flight
history are pulled toward a promoted-team prior (2025/26 promoted teams scored 0.73-0.94x
and conceded 0.92-1.44x league average). `train_ratings.py` now runs a paired ablation of
that prior against simply using league average, bucketed by matches played, over 639
promoted-team forecasts:

| matches played | n | mean delta NLL | SE | t |
|---|---|---|---|---|
| 0-4 | 90 | -0.00751 | 0.02330 | -0.32 |
| 5-9 | 90 | +0.02052 | 0.02524 | +0.81 |
| 10-19 | 180 | +0.00696 | 0.01617 | +0.43 |
| 20+ | 279 | -0.00163 | 0.01002 | -0.16 |
| pooled | 639 | +0.00308 | 0.00907 | +0.34 |

Negative favours the prior. **The prior is not evidence-selected**: no bucket reaches
|t| = 2 and the sign flips between buckets. By this document's own ablation rule it does
not earn its place, and it is retained on a priori grounds only — at genuine zero history
the alternative is to call a promoted side exactly league average, which is known to be
wrong before a ball is kicked. That justifies a mild prior, not a strong one. Three teams
in one season is underpowered, so this is "no evidence it helps", not "proven useless".

The 20+ row carries the useful finding: by then the prior and no-prior variants are
indistinguishable (t = -0.39), so a promoted team's own results have fully taken over.
That is the convergence, and it is the only part of the table that answers it — do not
read improvement down the NLL column, because the level moves with which opponents fall
in each bucket. Only the paired difference is interpretable.

Practically this is live. Coventry, Hull and Ipswich have no history in either cached
season and roughly three matches each, putting them in the least-informed bucket for the
next several gameweeks and reaching parity around GW20. `ratings.fit` now returns
`effective_matches_by_team` so thin evidence is visible downstream rather than hidden
behind a rating that reads as firmly as Arsenal's.

#### Odds anchoring — built and bracketed 2026-09-05, deliberately left near-off

Priced fixtures now enter the fit as weighted observations: `ratings.fit(odds_rows=...,
odds_weight=...)`, where the observation is the bookmaker-implied lambda carrying
`ODDS_MATCH_EQUIVALENT` matches of weight. Because ratings are per team, a price on one
fixture moves that team's rating and therefore every other fixture it plays. Mechanism
verified directly: weight 0 reproduces the unanchored fit exactly, weight to infinity
recovers the market lambda on the priced fixture (3.196 against a 3.200 target), and a
Chelsea price moves Chelsea's lambda in a *different, unpriced* fixture against Spurs
from 1.776 to 1.925, with Everton's defence updating from appearing only as an opponent.

Validation is impossible for now — historical odds do not exist — so `train_ratings.py`
brackets the mechanism with two leaking oracles instead. **The bracket is the finding:
the sign of this feature depends entirely on how noisy the anchor is.**

| oracle | weight 2 | weight 6 | weight 20 |
|---|---|---|---|
| realized xG (one draw from lambda; noisier than a price) | t = -0.05 | +1.73 | **+4.94** |
| full-season model lambda (pure team strength; no market is this clean) | **t = -3.70** | -3.70 | -3.72 |

All t-statistics cluster-robust on the match-side.

Negative favours anchoring, leads 2-6 only. Anchoring on a *noisy* estimate is actively
harmful and gets worse with weight — injecting one match of noise into a rating built on
20-plus matches damages it. Anchoring on clean team strength helps at every weight. A real
bookmaker line sits between the two and nothing cached says where.

`ODDS_MATCH_EQUIVALENT` is therefore set to **2.0**, the largest weight still non-harmful
under the pessimistic bound. This is not a fitted value and must not be raised until it
can be fitted against real archived prices, which `odds/` began accumulating the same day.

**The managerial-change hypothesis is suggestive but NOT established.** Splitting the
clean-oracle result by how far a rating had drifted, with cluster-robust standard errors:

| staleness quartile | mean delta NLL | clustered t | naive t |
|---|---|---|---|
| Q1 least stale | -0.00154 | -1.79 | -2.03 |
| Q2 | -0.00289 | -3.16 | -4.10 |
| Q3 | -0.00286 | -3.38 | -4.14 |
| Q4 most stale | -0.00487 | **-1.92** | -3.31 |

The point estimate is largest for the most stale quartile, which is the Chelsea case and
the direction theory predicts. But **Q4 does not reach significance once clustered**
(t = -1.92), the quartile ordering is not monotone, and the "3x Q4 over Q1" comparison was
never a pre-registered test. An earlier version of this section claimed the hypothesis
held; on the corrected standard errors it does not. It remains the best *reason* to expect
the feature to work, not evidence that it does.

**But keep the ceiling in view.** The best case here is ~0.003-0.005 NLL, against the
0.023 already banked by replacing the FDR fallback with ratings at all. Anchoring is a
refinement worth roughly an eighth of the change it refines. It should not absorb more
effort until real prices can fit its weight.

#### Current-season loader — built 2026-09-05

`ratings.current_season_rows()` reads finished 2026/27 fixtures from the observation
ledger (latest revision only, so official corrections supersede rather than double-count)
and emits the same schema as the cached-CSV reader. `ratings.load_all_rows()` concatenates
both. Without this the ratings would be frozen at last season and could never learn that a
side has changed, which is most of the point. `python scripts/ratings.py --season live`
fits across all of it — currently 1,560 team-match sides, 40 of them from 2026/27 GW1-2.

It also makes the promoted-team problem concrete rather than theoretical: Hull City
currently rates fifth on attack-over-defence off **two matches**, and is flagged `thin`
by `effective_matches_by_team` precisely so that number is not mistaken for Arsenal's.

**Still not adopted, and the bar is now higher than it looked.** The honest out-of-sample
margin is -0.0148 at t = -1.75, so ratings are not established as better on this evidence
alone — only consistently better in sign. Adoption must in any case be judged on
decision-weighted player forecasts rather than team goals, and that test cannot run until
frozen projection archives resolve. Do not wire ratings into `projections.py` on the
strength of the backtest.

Also note the scope of what was measured: this improves **team goals**, an input. The
adoption rule in this document is improvement in decision-weighted player forecasts.
That test cannot run until frozen projection archives resolve, so the ratings model
should be wired in behind the same walk-forward discipline and judged again there.

## Future decision dashboard

Once the command-line data contracts are stable, build a local/static HTML decision
cockpit over their JSON artifacts before considering hosting, authentication or a new
database. The dashboard is a presentation layer, not another source of truth. Its useful
top-level views are:

- **This gameweek:** deadline/state, the actual squad, price risks, avoidable lineup
  problems, and the eventual recommendation with its runner-up and confidence.
- **Expert evidence:** players discussed, transfers in/out, captaincy, chip strategy,
  considerations and other themes from the gameweek-brief pipeline, with consensus,
  dissent and polarizing views visible rather than flattened into one answer.
- **Model evidence:** hold and legal transfer-count alternatives, Free Hit/Wildcard teams,
  weekly XI/captain choices, source coverage, component explanations and uncertainty.
- **History and calibration:** actual points/minutes/components, frozen predictions,
  decision outcomes and lead-specific error for the decision-relevant population.

Avoid an information dump: lead with the decision and the few facts capable of changing
it, then progressively disclose components, raw claims and historical rows. Visually and
semantically distinguish official facts, creator claims, model estimates and realized
outcomes; always show source timestamps and the hard pre-deadline cutoff. Do not build
the dashboard until the underlying unfinished-fixture, attacking-prior and later-fixture
fallback issues above are resolved, or it will make fragile numbers look authoritative.

**Recalibration policy:** evaluate a candidate calibration every settled gameweek over
the most recent six archived forecast weeks, with results separated by forecast lead.
Do not automatically replace the active parameters after one week; promote a change only
after repeated walk-forward improvement on the frozen decision-weighted population.
All-player error remains diagnostic. New features face the same ablation rule: retain
them only when adding the feature improves out-of-sample decision-weighted forecasts.

**Projection is not transfer value.** A player's horizon xP and xP/current-price are
screening statistics, not a claim that buying him is worthwhile. Transfer value is
pair-specific: it must compare the best legal squad after `player out -> player in`
with the best hold squad over the same horizon, then account for any points hit and the
option value of spending rather than banking a free transfer. Feasibility depends on the
outgoing player's actual selling price, money in the bank, position, the three-per-club
limit and the rest of the squad. It can also change the optimal XI, bench and captain in
each gameweek. Until that decision layer exists, do not call the projection ranking or
the difference between two unpaired players a "net gain" or a transfer recommendation.
The decision output should show the best legal result at each transfer count from zero
(hold) through five, rather than presenting only one unconstrained optimum. Each incoming
player must preserve the outgoing position inventory: GKP for GKP, DEF for DEF, MID for
MID and FWD for FWD. For combinations, this is enforced on the squad as a whole, so a
two-player move may replace one midfielder and one forward but may not silently change
the required 2/5/5/3 positional counts.

Every candidate squad must be scored by its expected FPL points, not by its monetary
team value and not as the sum of fifteen unconditional player projections. For every
forecast gameweek, independently choose the legal XI that maximizes projected points
using the live `element_types[].squad_min_play` and
`squad_max_play` rules (currently exactly one GKP, 3-5 DEF, 2-5 MID and 1-3 FWD), then
choose captain, vice-captain and bench order. Thus a player's contribution may change
across the horizon as fixtures change, and an expensive incoming player receives no
artificial credit for weeks when the best estimated decision is to bench him. Captaincy
is part of the projected points total, not an after-the-fact annotation. Use `p_zero` and
the real substitution rules to show expected vice/autosub cover separately, stating the
appearance-independence assumption. Keep that coverage sensitivity out of the primary
ranking until it is calibrated; otherwise an uncertain early-season `p_zero` can silently
make bench depth dominate the result.

Keep transfer stock and monetary state separate from raw projected points:

- **Free-transfer stock.** Use one opportunity-cost term only: compare the next-week bank
  after the proposed moves with the next-week bank after holding, using the live cap, and
  charge for that difference. Do not also add a reward for retained transfers; that is
  the same value expressed from the other side of the hold baseline and would double
  count it. Spending one while already at five has zero stock cost because holding would
  waste the new accrual; at four or fewer, spending one normally leaves one fewer option
  next week. A points hit remains a separate, explicit current-gameweek cost for transfers
  beyond the free allowance.
- **Prices and money in the bank.** The outgoing player's actual selling price and the
  incoming player's current purchase price are hard feasibility constraints. Report the
  resulting cash balance and team value, but do not optimize or add points for either.
  Monetary value matters only insofar as it enables a concrete present or future move;
  introduce a cash shadow value only if a later dynamic-transfer model and walk-forward
  evidence justify one. Price-change projections can inform timing and warn that a move
  may soon become unaffordable, but projected profit is not the objective.

The intended build remains incremental: prove the hold/one-transfer squad evaluator,
then reuse exactly the same legality and weekly-lineup valuation for the best two-,
three-, four- and five-transfer combinations. Chips are a later optimization layer.

**Close-call policy:** default to holding when a proposed move's estimated advantage is
small relative to the model's measured decision-weighted uncertainty. A positive point
estimate is still reported, but it is not automatically an actionable edge: selecting
the maximum from many candidates creates winner's-curse risk, and spending a bankable
transfer reduces future flexibility. Do not invent a permanent fixed points threshold.
Derive the robustness margin from frozen, resolved projection errors once enough relevant
forecasts exist; until then, label marginal leads as uncertain and recommend the hold.
At the five-transfer cap, using one has no transfer-stock opportunity cost, but the same
model-uncertainty test still applies.

**Decision-output policy:** normally wait for the latest team news before transferring.
Move early for a projected price change only when waiting is likely to make an otherwise
preferred move unaffordable; prospective team-value gain alone is not a reason. Use
uncertainty to reject marginal actions, while still maximizing expected points among the
credible alternatives. Show the hold baseline, the top three legal plans using exactly
one transfer, the top three using exactly two, and the best plan at each of exactly three,
four and five transfers. Score all of these as moves made at the upcoming deadline and
then held for the full forecast horizon, with the XI and captain re-optimized weekly.
Do not invent later transfers inside that horizon; future-transfer planning is a separate
layer to consider only after the current-deadline optimizer is measured and useful.

**Chip-team output:** when the live chip data says the relevant chip is available and
inside its active window, also be able to display:

- **Optimal Free Hit squad:** an unlimited-transfer, budget-legal 15-player squad for the
  upcoming gameweek only, including the optimal legal XI, captain, vice and bench order.
  The original squad returns afterwards, so do not credit this team with later-horizon
  points or charge it ordinary transfer hits/stock.
- **Optimal Wildcard squad:** an unlimited-transfer, budget-legal permanent 15-player
  squad, scored across the selected horizon with its XI, captain, vice and bench order
  re-optimized each gameweek. Ordinary transfer hits do not apply and the banked-transfer
  rules continue to come from live state.

Chip-squad affordability must use the current squad's real selling prices plus money in
the bank and current purchase prices for incoming players; retained owned players must
not be treated as if they were sold and rebought at a higher price. Displaying the best
chip squad is not itself a recommendation to activate the chip. Compare its incremental
points with the best no-chip action and report the uncalibrated option value of saving the
chip separately, especially when later blank/double gameweeks are plausible. Call these
teams "optimal under the current projection model," not known-optimal teams.

## Next up

### Minutes model, empirical version — BUILT 2026-09-03

Shipped. `scripts/minutes.py`, output `data/minutes.json`, track record in `minutes/`.
The design notes below are kept as the record of what was decided and why. What changed
in the building of it:

- **Output is scoring-aligned bands, not the role buckets themselves.** The four buckets
  stay as the model's internal structure — role is what persists week to week, so it is
  what carries the signal — but nothing downstream cares whether 70 minutes came off the
  bench. It cares which side of the 60-minute cliff the player lands. So: four role
  buckets in, `p_zero` / `p_1_59` / `p_60_plus` plus `exp_minutes` out.
- **The recency-weighted-across-all-history plan hit a data wall.** `element_summary[]
  .history` is **current season only** — 2 rows per player at GW3. Prior seasons appear
  in `history_past` as season aggregates (minutes and starts totals, no appearance
  count, no per-match rows). Per-gameweek history further back exists only in vaastav's
  dataset, which is not wired in. Decision: this season only, threshold of 2 gameweeks,
  rather than either counting an aggregate as evidence or taking on a second source.
- **Decay constant parked, not fitted.** `DECAY_HALFLIFE_GWS = 5`. With two gameweeks
  every weight is within 15% of every other, so nothing measurable turns on it yet.
- **Bands floored at 5%.** Two observations can't establish certainty, and without a
  floor a player who started twice reads as a 100% chance of 90 minutes — which flows
  straight into captaincy risk, the main reason for wanting a distribution at all.
  Distinct from smoothing a thin sample toward a prior: this declines to assert
  certainty rather than inventing a number.

**Doubtful-player rule corrected 2026-09-05.** The original fallback cut every flagged
player to `chance_of_playing * 30 minutes`. That conflated two questions: whether a player
appears and, conditional on appearing, whether he starts or comes from the bench. It also
made the projection internally inconsistent: appearance bands could retain some 60-plus
probability while DefCon, saves and clean-sheet calculations treated the same player as a
30-minute cameo. The API percentage now replaces only the probability of appearing. The
trained starter/cameo mixture and conditional minutes are renormalized within that
appearance mass, and the resulting single distribution feeds every xP component. The
30-minute cameo assumption survives only as the explicit legacy fallback when no trained
role distribution exists. Historical FPL data does not preserve point-in-time availability
flags, so this correction is rule/semantic consistency rather than a fitted accuracy claim;
the frozen weekly ledgers will measure it prospectively.

### Minutes model, empirical version — design notes

Hashed out 2026-09-03, across two sessions (this one, plus a separate design
conversation whose scratch notes have been folded in here and deleted — nothing lost,
just relocated so it's citable). Not built yet.

**Why it has to be a distribution, not a single average:** every projection input —
`expected_goals`, `expected_assists`, defensive-action counts — is a per-90 rate, which
means nothing for next gameweek without knowing how many of those 90 minutes a player
will actually get. Two reasons the average alone isn't enough: captaincy/chip risk
depends on certainty, not just the mean (a player nailed on for 90' is a safer pick than
one averaging the same points but sometimes hooked at 60', even at equal expected
points); and DefCon is a step function, not a slope — a player subbed at 60' isn't "a
third as likely" to clear the 10/12 threshold, they're close to zero. The DefCon
sub-model needs the shape of the distribution, not its mean.

**Decided:**
- **Full player pool (~600), not a watchlist.** Widen `fetch_data.py`'s
  `element_summary` pull from the owned squad (15) to everyone — a hand-maintained or
  auto-filtered watchlist would miss a bench player who suddenly starts getting
  minutes. Real backoff on this, not just a flat courtesy delay — retry-with-delay on a
  429, not merely a pause between calls. The risk isn't slowness, it's losing API
  access to the undocumented endpoint entirely, which would break everything else in
  this project, not just the minutes model.
- **Recency-weighted across all history, not a season-level blend.** Squad roles shift
  *within* a season (transfers, injury returns, managerial changes), not just between
  seasons, so a gameweek from last month should outweigh one from August regardless of
  which season either fell in.
- **Injury/suspension is a hard override, not a blended signal** — zeroed outright when
  the status flag or fresher news says so, matching how `check_team.py` already treats
  those statuses as a hard fail rather than a warning.
- **Minutes buckets: started-and-finished, started-and-withdrawn, benched-and-used,
  unused.** Already specified in the original data audit (§3, minutes model discussion)
  — not an open question, just needed pulling into this section.

**Explicitly not in v1** (decided in this conversation, 2026-09-02 — quoting Joe's own
v1-scope message directly, since it exists only as chat history and nowhere else yet):
- **The LLM/news override layer ships after the empirical version, not bundled in from
  the start.** Sequencing it in from day one repeats the exact trap Joe named when
  proposing v1 scope: *"the trap to avoid is spending until December on the minutes
  model. It is the highest-value component and it will happily eat the season. Cheap
  version now, measured error, then decide."* Ship the empirical distribution, get it
  into the Monte Carlo loop, measure its error, *then* add overrides.
- **Cup/European rotation risk is out of v1**, per the same message: "rotation and
  congestion modelling" is explicitly on the out-of-v1 list. No clean free source exists
  for UCL/UEL/UECL/domestic-cup fixture congestion anyway (flagged C in the original
  audit) — a `starts`-vs-appearances proxy is the fallback if it's ever revisited.

**Settled 2026-09-03 — the fallback stack.** What the model emits when the empirical
distribution is thin or absent. Verified against the real pool (652 players fetched,
1,236 gameweek rows) before being agreed, not proposed in the abstract.

The evidence behind it: **price predicts minutes, strongly and monotonically.** Measured
across the pool at GW3 — 3.5-4.5m start 18% of the time for 16 minutes a game, rising
through 28%/25min, 53%/46min, to 100%/87min above 8.0m. Price is the one signal available
for a player who has never kicked a ball in the league, because FPL sets it from their own
expectation of the player's role. So the cold-start prior is a **price band x position**
lookup, not a flat default and not a positional average — positions are far too internally
varied (most of the 289 midfielders never play).

```
1. i / s / u  (injured, suspended, unavailable)  -> 0 minutes
2. d          (doubtful)                          -> chance_of_playing% x trained conditional role mix
3. a, thin evidence, owned                        -> 60-minute floor
4. a, thin evidence, not owned                    -> insufficient_evidence, no recommendation
5. enough evidence                                -> empirical four-bucket distribution
6. modifier: zero minutes this season             -> halve whatever the above produced
```

Reasoning behind the non-obvious rules:

- **Rule 2 separates availability from selection.** A 75% flag now means 25% unused and
  75% distributed across that player's trained starter/cameo states in their existing
  conditional proportions. It does not mean 75% of his normal expected minutes, nor does
  it imply a cameo. Note the direction: 75% is nearly fit and `i` is the hard-zero bucket.
  With no trained role distribution, the old 30-minute cameo remains a labeled fallback.
- **Rule 4 refuses rather than guesses.** Joe's call, and it removes a whole class of
  problem: no smoothing scheme, no shrinkage toward a parent cell, no gambling on a cell
  with n=2. Thin evidence shouldn't be trusted just because it exists — the price x
  position table has real cells at n=2 (DEF elite) and n=6 (DEF premium, FWD elite) that
  read as 100% or 33% purely on one or two players.
- **Rule 3 exists because rule 4 can't cover an owned player.** You can't "decline to
  recommend" someone already in the squad — projecting the team's score needs a number
  for him regardless.
- **Rule 6 is the correction to rule 3's optimism.** Without it, an owned permanent
  benchwarmer is projected as a 60-minute starter, so the optimiser reads him as
  productive and *holds him instead of flagging the transfer that should be made*. The
  failure runs in the expensive direction, which is why the modifier is there.

Known soft spot, recorded deliberately: `chance_of_playing` is an editorial availability
estimate, not a predicted-XI probability. Treating it literally may still overstate a
fit-but-unselected player or understate someone expected to play through a minor flag.
The model freezes the raw percentage, pre-override appearance probability and adjusted
distribution so this can be recalibrated from prospective results rather than anecdotes.

**Still open:**
- Exact recency-decay constant. This is a *different* decay from the `0.85^(t-1)`
  projection-horizon discount already locked in — one weights how much to trust old
  training data, the other discounts future gameweeks. Don't reuse the same number for
  both just because they're both "a decay."
- Where an LLM override gets logged: recommended as its own append-only log (same
  `entries.jsonl` pattern as `journal/` and `news/`), not folded into
  `journal/entries.jsonl` — that file's schema is built around scoring a decision
  against its counterfactual, a different shape of record than "prediction changed from
  X to Y because of Z."

### 5. Odds-based fixture difficulty

**Built 2026-09-04.** Uses The Odds API's `soccer_epl` endpoint with UK `h2h,totals`
markets. The key is stored only as
`THE_ODDS_API_KEY` in a gitignored `.env`, never in tracked configuration or logs. A
live request returned 19 fixtures across roughly two rounds; the production verification
matched all 19 to FPL fixture IDs and cost 2 of the free plan's 500 monthly credits.

The interpretation contract is recorded in `docs/DATA_SOURCES.md`: remove bookmaker
margin within each bookmaker/market before taking component medians and renormalizing;
ignore the automatically returned `h2h_lay`; accept only the 2.5 totals line; retain
timestamps and contributing-bookmaker counts; and describe results as bookmaker-implied
probabilities. The verified feed is near-term, not six gameweeks deep, so FPL FDR remains
the fallback outside its coverage. Ingestion is complete; consuming these probabilities
in the projection model is a separate next step.

**Player props checked, deliberately not added.** Anytime-goalscorer and related markets
exist, but a live test returned only two bookmakers. The API supplies one `Yes` price per
player, not a Yes/No pair, and multiple players can score, so normalizing across players
cannot remove the margin. A 19-fixture refresh would also cost 19 credits for one prop
market. See `docs/DATA_SOURCES.md`; do not label inverse goalscorer odds as scoring
probabilities without a separate calibration method.

### 6. Chip expiry monitor & set-piece watch

**Chip expiry monitor.** Half the chips evaporate at the GW19 deadline (13:30 GMT,
Sat 2 Jan 2027) and people routinely waste them. `state.py` already prints the windows;
this adds the judgment: a running "is the best remaining chip plan worth more than zero"
check, escalating in tone as GW19 approaches. Needs a view of upcoming doubles/blanks to
be genuinely useful, which ties it to the blank/DGW detector below.

**Set-piece watch.** Diff `penalties_order`, `direct_freekicks_order`, and
`corners_and_indirect_freekicks_order` between pulls. Penalty duty changing hands is one
of the highest-alpha events in FPL and is badly tracked by most tools. The prerequisite —
dated snapshots to diff against — is now built (`data/snapshots/`, 2026-09-03). The watch
itself (the diff and the alert) is still open; there's only one day of history so far.

## Parked / open questions

- **Fit the minutes-model decay constant.** `DECAY_HALFLIFE_GWS = 5` in `minutes.py` is
  a placeholder, not a measurement. It can't be fitted yet: at GW3 every observation is
  within 15% of every other under any half-life you pick, so the data cannot tell two
  candidate values apart. **Revisit around GW10**, when there's enough spread for the
  choice to bite. Fit it against `minutes/gwNN.jsonl` — vary the constant, re-score the
  frozen predictions, keep what minimises error. Do not reuse the `0.85^(t-1)`
  horizon discount: that one prices *future* gameweeks, this one weights *past*
  observations. Different questions that happen to share a shape.

- **Prior-season per-gameweek history (the vaastav backfill) — BUILT 2026-09-05.** The FPL API gives
  per-gameweek rows for the current season only; earlier seasons are aggregates in
  `history_past` (minutes and starts totals, no per-match rows). So in August the minutes
  model has nothing to work from and everything falls back to price. Fixing it means
  wiring in vaastav's dataset — already verified for the backtest split: `data/2025-26/
  gws/merged_gw.csv`, 29,757 rows, GW1-38, all DefCon columns.

  This is now wired into the trained minutes model rather than postponed to next season.

  The crucial join rule is preserved: **FPL reassigns element IDs every season**, so
  joining last season's rows to this season's players goes through `element_code`, which
  is stable and which `history_past` exposes. Joining on `element` would silently match
  the wrong players.

- **Authenticated `my-team` endpoint.** `check_team.py` can only validate the last *saved*
  squad — transfers made in the app since the last deadline are invisible. Fixing that
  needs a session cookie in the repo. Worth it? Probably not for a hobby project, but it's
  the one real limitation in what's built so far.
- **Effective ownership as a risk gauge.** Global `selected_by_percent` is already cached.
  The work is turning it into "this captaincy call is a 300k-rank swing either way",
  which needs a distribution, not a point estimate.
- **Blank/double gameweek detector.** Can't be predicted from the API — they fall out of
  cup progression and European congestion, and are human-curated (Ben Crellin's planner).
  But early warning is trivial: watch for any fixture with `event: null`, or any gameweek
  whose fixture count drifts off 10. Currently all 38 have exactly 10.
- **Bench Boost handling in `check_team.py`.** With a Bench Boost active all 15 play, so
  the bench checks change meaning. Not relevant until a chip is played.
- **Fantasy Football Hub articles — tested and closed, not open.** No RSS (every real
  feed path 404s) and a Next.js SPA even a plain scrape can't reach — real article text
  loads client-side only. Would need a headless browser to fix, a materially bigger
  dependency than `yt-dlp`. Not worth it: FFS already covers the dominant source,
  Crellin's calendar is handled separately, his and Bakar's video content is already
  excluded from the transcript build. Full writeup in `docs/DATA_SOURCES.md`.
