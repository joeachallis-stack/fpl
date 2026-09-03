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

## Third-party (for context the official API doesn't give you: xG, projections, news)

- **Fantasy Football Scout** (fantasyfootballscout.co.uk) — FDR ticker, clean sheet /
  projected goals per team, widely used for fixture planning.
- **Fantasy Football IQ** (fantasyfootballiq.app/data) — free projected points + fixture-ease
  as CSV/JSON at stable URLs, built on official data + xG + bookmaker odds.
- **The Football Matrix** (thefootballmatrix.com/fpl) — free tools incl. fixture ticker and
  per-player xG/xA/xGI.
- **FBref** (fbref.com) — advanced stats (xG, xA) not in the official API, useful for
  sanity-checking form vs underlying performance.
- **Premier League injury/press news** — no clean free API; likely needs periodic manual
  check or a news-search step (e.g. WebSearch for "[player] injury update") before
  transfer decisions, since the official API has no injury/news feed beyond the
  `elements[].news` and `elements[].chance_of_playing_this_round` fields in
  `bootstrap-static/` (which are often stale or vague).

None of these require an API key. If a paid/authenticated source becomes worth adding
later (e.g. Understat, Opta), note it here before wiring it in.
