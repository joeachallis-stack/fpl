# Data Sources

## Official FPL API (free, no key, undocumented but stable)

Base URL: `https://fantasy.premierleague.com/api/`

| Endpoint | Returns |
|---|---|
| `bootstrap-static/` | Every player (`elements`), team (`teams`), position type (`element_types`), and gameweek (`events`) — prices, ownership %, form, ICT index, deadlines. The one endpoint to fetch first; everything else references its IDs. |
| `fixtures/` | All fixtures with kickoff times and FDR (fixture difficulty rating). `?event={gw}` filters to one gameweek, `?future=1` to remaining fixtures. |
| `element-summary/{player_id}/` | Per-player fixture-by-fixture history and remaining fixture list. |
| `event/{gw}/live/` | Live per-player stats for a specific gameweek (updates during matches). |
| `entry/{team_id}/` | Manager overview: name, overall rank, total points, current gameweek. |
| `entry/{team_id}/history/` | Season-by-season and gameweek-by-gameweek history, chips used. |
| `entry/{team_id}/transfers/` | Full transfer log for the season. |
| `entry/{team_id}/event/{gw}/picks/` | Squad, captain/vice, chip active, for one gameweek. |
| `leagues-classic/{league_id}/standings/` | Mini-league standings. |
| `event-status/` | Whether bonus points / league tables are finalized for the current gameweek. |
| `dream-team/{gw}/` | Highest-scoring XI for a gameweek. |

`scripts/fetch_data.py` pulls the ones this project actually uses into `data/` (gitignored,
refresh on demand — this is live season data, not something to commit).

## What bootstrap-static already carries (checked 2026-09-02)

Don't reach for a third-party source before checking these — several fields that used to
require FBref or a price-tracking site are now native:

- **Underlying numbers**: `expected_goals`, `expected_assists`, `expected_goal_involvements`,
  `expected_goals_conceded`, all with `_per_90` variants, plus `defensive_contribution`,
  `tackles`, `recoveries`, `clearances_blocks_interceptions`. FBref is now a
  sanity-check, not a dependency.
- **Price changes**: `price_change_projections` (percent-to-change at offsets 0/1/2 days
  with a `likelihood` score), `price_change_hourly_rate`, `price_change_locked_until`.
  This is FPL's own transfer-momentum model — no need to build one off cache deltas.
- **Set pieces**: `penalties_order`, `direct_freekicks_order`,
  `corners_and_indirect_freekicks_order` plus the `_text` variants.
- **News**: `news`, `news_added`, `status`, `chance_of_playing_this_round`/`_next_round`,
  and `scout_news_link` — a link to the actual club article, which is more current than
  the `news` string alone.
- **Ownership**: `selected_by_percent`, `selected_rank`, `transfers_in_event`,
  `transfers_out_event`.

One trap: **`ep_next`/`ep_this` are not projections.** As of GW3 they equal `form` exactly
for every player sampled. Don't wire them in as expected points.

## Third-party (for context the official API genuinely doesn't have: odds, predicted XIs, DGWs)

- **Fantasy Football Scout** (fantasyfootballscout.co.uk) — FDR ticker, clean sheet /
  projected goals per team, widely used for fixture planning.
- **Fantasy Football IQ** (fantasyfootballiq.app/data) — free projected points + fixture-ease
  as CSV/JSON at stable URLs, built on official data + xG + bookmaker odds.
- **The Football Matrix** (thefootballmatrix.com/fpl) — free tools incl. fixture ticker and
  per-player xG/xA/xGI.
- **FBref** (fbref.com) — advanced stats. Now largely redundant with the native
  `expected_*` fields above; useful for splits the API doesn't break out (per-competition,
  shot location) and for sanity-checking form vs underlying performance.
- **Premier League injury/press news** — no clean free API; likely needs periodic manual
  check or a news-search step (e.g. WebSearch for "[player] injury update") before
  transfer decisions, since the official API has no injury/news feed beyond the
  `elements[].news` and `elements[].chance_of_playing_this_round` fields in
  `bootstrap-static/` (which are often stale or vague).

None of these require an API key. If a paid/authenticated source becomes worth adding
later (e.g. Understat, Opta), note it here before wiring it in.

## Known gaps (nothing free closes these cleanly)

- **Bookmaker odds** — FDR is a hand-assigned 1-5 integer. Win probability and over/under
  2.5 are real numbers and a much better basis for fixture difficulty. Needs an API key,
  so decide whether one belongs in this repo before wiring it up.
- **Predicted XIs / press conferences** — `chance_of_playing_next_round` lags the news by
  a day or more. `scout_news_link` helps; a WebSearch before the deadline still helps more.
- **Blank and double gameweeks** — not announced in advance; they fall out of cup
  progression and European congestion, and are human-curated (Ben Crellin's planner is the
  reference). Cheap early warning: watch `fixtures.json` for any fixture with
  `event: null`, or any gameweek whose fixture count drifts off 10.
