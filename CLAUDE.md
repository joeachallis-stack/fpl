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
  show_team.py        — print current squad + summary from cached data
data/                 — gitignored cache of fetched API responses
  element_summary/    — per-player fixture history + remaining fixtures (owned players)
  standings_{id}.json — mini-league standings (leagues under 500 entries only)
  snapshots/           — one dated bootstrap.json per day; the only backfill for set-piece
                        order, which the live API never exposes historically
journal/
  entries.jsonl        — one JSON object per logged recommendation. Tracked in git,
                        unlike data/ — an authored record, not an API cache.
news/
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
python scripts/fetch_data.py
python scripts/show_team.py
```
