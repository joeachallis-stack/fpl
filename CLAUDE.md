# FPL — Fantasy Premier League Assistant

Helps Joe Challis manage his FPL team for the 2026/27 season: weekly transfer/captaincy/
chip recommendations based on form, fixtures, and value.

## The Team
- **Objective: maximise total points**, not overall rank and not mini-league position.
  Ownership and effective ownership are *displayed context* so Joe can see the variance
  he's carrying — never objective terms. See [`docs/IDEAS.md`](docs/IDEAS.md) for the
  reasoning, the data audit, and the build order.
- Manager: Joe Challis (favourite club: Chelsea)
- FPL team ID: `8837120` (see `config.json`)
- Team/entry URL pattern: `https://fantasy.premierleague.com/api/entry/8837120/...`

## Data
- `scripts/fetch_data.py` pulls fresh data from the official FPL API into `data/`
  (gitignored — always live, never commit it). Run it before any analysis; the cache can
  be hours stale otherwise.
- `scripts/show_team.py` prints the current squad from the cache.
- Full endpoint reference: [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) (official API +
  free third-party sources for xG/projections/fixture difficulty).
- Season rules (chips, transfers, scoring): [`docs/RULES_2026_27.md`](docs/RULES_2026_27.md).
  **Prefer the live parameterization over this prose**: `bootstrap.json` → `game_settings`
  (`max_extra_free_transfers`, `squad_team_limit`, `squad_squadsize`), `element_types[]`
  (`squad_min_play`/`squad_max_play`), and `chips[]` (each chip's `start_event`/`stop_event`)
  are what the game actually enforces. The scripts read those; the doc is background.
  **Rules change every season — re-verify at the start of 2027/28 rather than trusting
  this file forever.**

## Weekly Workflow (the core loop)
When Joe asks "what should I do this week" / "review my team" / similar:
1. Run `fetch_data.py` to refresh the cache.
2. Run `scripts/state.py` for the deadline, banked free transfers, and chip windows.
   Free transfers are **reconstructed** by walking `history.current` forward (start at 1,
   spend what was used, accrue 1/week to the cap, wildcards and free hits leave the bank
   untouched) — a single gameweek's `event_transfers` cannot tell you the banked count.
3. Check fixtures for the next 3-5 gameweeks for players Joe owns and plausible transfer
   targets — favor players with a run of low-FDR fixtures.
4. Check for injuries/rotation risk (`elements[].news`,
   `elements[].chance_of_playing_this_round` in bootstrap-static; supplement with a
   WebSearch for genuinely current news since the API field is often stale).
5. Check chip status (`entry/history/` for chips already used this half-season) and flag
   if a strong Bench Boost / Triple Captain / Free Hit window is coming up (double
   gameweek, favorable fixture swing) — but don't recommend burning a chip without a
   clear edge.
6. Run `scripts/check_team.py` to catch the avoidable losses (illegal XI, flagged
   starter, captain and vice in the same match, blanks, bench that can't cover). Note it
   validates the *last saved* squad — changes made in the app since aren't visible.
6a. Log the week's recommendation(s) with `scripts/journal.py add` — captain, transfer,
   chip or hold — before the deadline, including the runner-up and why it lost. This is
   what makes next week's review honest instead of hindsight-biased. Once a prior
   gameweek has settled, run `scripts/journal.py resolve --gw N` and read `show --open`
   for anything still outstanding before making this week's call.
6b. Freeze the minutes model's predictions with `scripts/minutes.py archive` — **before
   the deadline, every week**. It refuses to overwrite an existing file, because a
   prediction you can rewrite afterwards isn't one. Once a gameweek has settled, run
   `scripts/minutes.py resolve --gw N` for its error. This is the same discipline as
   the journal one step up, aimed at the model rather than the decision: minutes is the
   highest-leverage input and the one most likely to be quietly wrong, and the measured
   error is what decides whether the LLM/news override layer is worth building at all.
6c. Run `scripts/projections.py` (six-GW horizon by default; `--horizon N` to change),
   inspect its component breakdown for implausible inputs, then freeze it with
   `scripts/projections.py archive` before the deadline. Resolve the prior week with
   `scripts/projections.py resolve --gw N`, and run `scripts/evaluate.py` for rolling,
   lead-time-specific error. This is a measured baseline, not an oracle: it refuses a
   partial next gameweek of odds and records sparse-data limits.
6d. Run `scripts/decisions.py` to compare hold with the top exact 1-5 transfer squads and,
   when available, the model-optimal Free Hit and Wildcard squads. Prices constrain
   feasibility but earn no points; vice/autosub cover, transfer stock and uncertainty
   remain visible rather than being hidden in the ranking. Once the recommendation is
   ready, freeze the search with `scripts/decisions.py archive`; it will not overwrite an
   existing gameweek archive.
6e. Run the `gameweek-brief` skill for what the FPL creators are saying — extracted from
   the YouTube transcripts, name-resolved against the roster, and claim-checked against
   the match record. It reports consensus and dissent per player rather than a wall of
   quotes. Treat it as evidence, not instruction: where a creator and the minutes model
   disagree about a player's role, that disagreement is the useful part.
7. Recommend: hold vs. transfer (and who in/out, with the price/points-hit tradeoff),
   captain and vice-captain picks, and whether to bank the free transfer instead.
8. State reasoning in terms of the actual data pulled, not generic FPL wisdom — cite the
   specific fixture runs, form numbers, or price changes driving the call.

## Constraints
- Point-in-time only: never suggest transfers based on results that happened after the
  gameweek being planned for — deadline is a hard cutoff.
- A transfer costs 4 points if it exceeds the free transfer allowance (up to 5 banked) —
  always weigh a suggested transfer's expected points gain against that cost.
- This is a free-to-play hobby game — there's no need for production-grade error handling
  or test coverage here. Keep scripts small and readable; optimize for Joe reading the
  output, not for shipping a service.

## Project Structure
```
config.json          — team ID + manager identity (not secret, just config)
scripts/
  fetch_data.py       — pull bootstrap-static, fixtures, event-status, entry, history,
                        transfers, picks, per-player summaries, small-league standings;
                        also snapshots bootstrap.json daily (see data/snapshots/ below)
                        and runs fetch_news.py (see news/ below) as part of the same fetch
  fetch_news.py       — pull free FPL-adjacent RSS feeds, append new items to
                        news/entries.jsonl; runs automatically from fetch_data.py
  state.py            — derived state: banked free transfers, chip windows, next deadline
  check_team.py       — pre-deadline checklist (legal XI, flags, captaincy, blanks, bench)
  journal.py          — decision journal: log recommendations, resolve realized outcomes
  prepare_extraction.py — pick which transcripts still need reading, batch them, and
                        write the trimmed roster the extraction agents use
  consolidate.py      — merge extracted findings, resolve names, check claims against
                        the record, print consensus and dissent per player
  roster.py           — canonical player-name resolution; the authority on identity
  claims.py           — check what a transcript claims against what the data records,
                        plus which gameweek a video is actually about
  minutes.py          — trained hierarchical minutes model: current and prior-season
                        role history plus position/price peers produce scoring-aligned
                        bands (p_zero / p_1_59 / p_60_plus).
                        `archive` freezes a GW's predictions, `resolve` scores them
  train_minutes.py    — walk-forward fit of recency and peer-prior strength; writes the
                        small tracked parameter artifact under models/
  odds.py             — fetch near-term EPL odds; remove bookmaker margin and aggregate
                        fair 1X2 and over/under 2.5 probabilities across UK bookmakers
  observations.py     — append finalized player-fixture facts once, revisioning any
                        later official correction instead of silently overwriting it
  projections.py      — auditable multi-GW expected points by scoring component; combines
                        minutes, odds, official xG/xA, and shrunk match-history rates
  evaluate.py         — walk-forward error by forecast lead; all-player diagnostics and
                        decision-weighted primary metrics remain separate
  decisions.py        — legal whole-squad optimizer: hold, exact 1-5 transfer plans,
                        weekly XI/captain/bench, and available Free Hit/Wildcard squads
  show_team.py        — print current squad + summary from cached data
data/                 — gitignored cache of fetched API responses
  decisions.json      — full auditable output from the latest whole-squad optimization
  odds_raw.json       — reproducible The Odds API response plus fetch/quota metadata
  odds.json           — derived probabilities matched to official FPL fixture IDs
  element_summary/    — per-player fixture history + remaining fixtures (owned players)
  standings_{id}.json — mini-league standings (leagues under 500 entries only)
  snapshots/           — one dated bootstrap.json per day; the only backfill for set-piece
                        order, which the live API never exposes historically
journal/
  entries.jsonl        — one JSON object per logged recommendation. Tracked in git,
                        unlike data/ — an authored record, not an API cache.
minutes/
  gwNN.jsonl           — the minutes model's frozen pre-deadline predictions for one
                        gameweek, with the inputs that produced them. Tracked in git:
                        data/minutes.json is overwritten every run, so an unrecorded
                        prediction is gone. Storing the inputs is what lets the model's
                        hardcoded constants be replaced by measurements later.
observations/
  player_fixtures.jsonl — immutable finalized facts, one row per player-fixture; doubles
                          aggregate naturally and corrections append a revision
projections/
  gwNN.json           — frozen pre-deadline horizon forecasts and inputs, later resolved
                        with actual points to measure projection error
decisions/
  gwNN.json           — frozen hold/transfer/chip search, including point-in-time prices,
                        legal weekly lineups and the alternatives shown to Joe
models/
  minutes_params.json — fitted parameters, source hashes, calibration and peer priors
news/
  findings/gwNN_*.jsonl — structured claims extracted from transcripts, one file per
                        extraction batch. Git-tracked: reading a transcript is the
                        expensive step and a video is extracted once, ever.
  aliases.json         — caption manglings mapped to roster names ("Solace" is Tzolis,
                        "Califury" is Calafiori). Grown only from observed failures.
  roster.txt           — the trimmed player vocabulary extraction agents may use.
                        Regenerated by prepare_extraction.py.
  entries.jsonl        — one JSON object per RSS item (headline, link, summary), append-
                        only. Tracked in git, unlike data/ — feed items are unrecoverable
                        once they scroll off the source, same reasoning as snapshots/.
docs/
  IDEAS.md            — objective, backlog, open questions, build order
  PRIOR_ART.md        — literature/solver review + cross-check against verified data
  RULES_2026_27.md    — season rules (chips, transfers, scoring, deadlines)
  DATA_SOURCES.md      — API endpoint reference + third-party sources
```

## Setup
```bash
pip install -r requirements.txt
python scripts/train_minutes.py --fetch  # one-time historical cache + reproducible refit
python scripts/fetch_data.py
python scripts/show_team.py
```
