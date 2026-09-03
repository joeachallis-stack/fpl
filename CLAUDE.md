# FPL — Fantasy Premier League Assistant

Helps Joe Challis manage his FPL team for the 2026/27 season: weekly transfer/captaincy/
chip recommendations based on form, fixtures, and value.

## The Team
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
  **Rules change every season — re-verify at the start of 2027/28 rather than trusting
  this file forever.**

## Weekly Workflow (the core loop)
When Joe asks "what should I do this week" / "review my team" / similar:
1. Run `fetch_data.py` to refresh the cache.
2. Check the upcoming gameweek deadline (`bootstrap.json` → `events[].deadline_time`) and
   how many free transfers are banked (`entry_history.event_transfers` from the picks
   cache — 0 used means transfers are still available up to the cap).
3. Check fixtures for the next 3-5 gameweeks for players Joe owns and plausible transfer
   targets — favor players with a run of low-FDR fixtures.
4. Check for injuries/rotation risk (`elements[].news`,
   `elements[].chance_of_playing_this_round` in bootstrap-static; supplement with a
   WebSearch for genuinely current news since the API field is often stale).
5. Check chip status (`entry/history/` for chips already used this half-season) and flag
   if a strong Bench Boost / Triple Captain / Free Hit window is coming up (double
   gameweek, favorable fixture swing) — but don't recommend burning a chip without a
   clear edge.
6. Recommend: hold vs. transfer (and who in/out, with the price/points-hit tradeoff),
   captain and vice-captain picks, and whether to bank the free transfer instead.
7. State reasoning in terms of the actual data pulled, not generic FPL wisdom — cite the
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
  fetch_data.py       — pull bootstrap-static, fixtures, entry, history, transfers, picks
  show_team.py        — print current squad + summary from cached data
data/                 — gitignored cache of fetched API responses
docs/
  RULES_2026_27.md    — season rules (chips, transfers, scoring, deadlines)
  DATA_SOURCES.md      — API endpoint reference + third-party sources
```

## Setup
```bash
pip install -r requirements.txt
python scripts/fetch_data.py
python scripts/show_team.py
```
