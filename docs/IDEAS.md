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

**Known standing behaviour, accepted rather than fixed:** a regular starter carrying a
fitness flag is cut hard — at GW3, Coyle had played 114 of a possible 180 minutes, was
flagged 75% fit, and reads 22 expected minutes. The eased-in-off-the-bench assumption
behind rule 2 fits a returning player, not one playing through a niggle. Left alone
because it only touches already-flagged players, where news beats the model anyway.
Worth being explicit that **this one does not self-correct with more gameweeks** — it's
a fixed rule, not a sparse-data artifact. What retires it is the track record: with
`status` and `chance_of_playing` frozen next to actual minutes, "what do 75%-flagged
players really average?" becomes measurable, and the constant gets replaced rather than
re-argued.

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
2. d          (doubtful)                          -> chance_of_playing% x 30
3. a, thin evidence, owned                        -> 60-minute floor
4. a, thin evidence, not owned                    -> insufficient_evidence, no recommendation
5. enough evidence                                -> empirical four-bucket distribution
6. modifier: zero minutes this season             -> halve whatever the above produced
```

Worked example, Palestra at GW3: `status: d`, "Unspecified injury - 75% chance of
playing", 0 minutes all season. Rule 2 gives 0.75 x 30 = 22.5, rule 6 halves it to
**11 expected minutes**.

Reasoning behind the non-obvious rules:

- **Rule 2 uses 30 minutes, not 60.** A player carrying a fitness flag who does play
  tends to be eased in off the bench rather than starting. Note the direction of
  `chance_of_playing`: it is the chance of *playing*, so 75% is nearly fit and `i` is the
  0% bucket. Easy to read backwards.
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

Known soft spot, recorded deliberately: rule 2 still gives a fit-but-benched player
minutes on a fitness signal alone. `chance_of_playing` answers "is he fit", never "will he
be picked" — the API has no field for the second. Rule 6 blunts it. Revisit if real output
shows it mattering.

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
