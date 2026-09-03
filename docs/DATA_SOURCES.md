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

## RSS news feeds (ingested, checked 2026-09-03)

`scripts/fetch_news.py` pulls these on every `fetch_data.py` run and appends new
items to `news/entries.jsonl` (git-tracked — see `news/README.md` for why). All
three are free, headline-and-link only — none exposes the underlying analysis:

| Source | Feed URL | Notes |
|---|---|---|
| Fantasy Football Scout | `fantasyfootballscout.co.uk/feed/` | The main FPL analysis site. Feed gives headline + short summary + link; the actual "Scout Picks" content is a Members Area paywall. |
| FPL Hints | `fplhints.com/blog-feed.xml` | Smaller independent FPL blog. |
| FPL Toolbox | `fpltoolbox.com/feed/` | Smaller independent FPL blog. |

Verify these URLs still resolve if the feed starts returning nothing — WordPress
sites occasionally move `/feed/` or redirect apex↔`www`.

**Not yet ingested — deliberately deferred, WebSearch at decision time covers these for
now** (checked 2026-09-03; two of these are a harder problem than "no feed" implies):
- `premierinjuries.com` — would be the best free injury source (type + estimated return
  date), but it's **actively bot-blocked** (confirmed `403 Blocked` on the real injury-
  table URL, same wall as X and Reddit), not just missing a feed. Building a scraper
  here means working around active bot detection, not parsing a page that's merely
  unstructured — a materially worse trade than the other sources on this list.
- `physioroom.com` — genuinely scrapeable (real server-rendered HTML tables, no JS
  needed, confirmed by fetching and parsing them directly), but confirmed to give
  **injury type only, no return dates** — and `bootstrap-static`'s own `news` field
  already often carries type as free text (e.g. "Groin injury - Unknown return date"),
  so the marginal value over what's already free doesn't clearly justify a maintained
  scraper. Its one genuinely new signal: a **team-level total-injuries table** (squad
  depth/rotation-risk proxy), worth remembering if that ever becomes worth building.
- Predicted-lineup pages (RotoWire, `fpledits.com`) and FFS's own team-news page — both
  load fine, not yet scraped, no feed for either.

A scraper is not currently planned as a fast-follow for any of these — the RSS layer
covers the sources that actually publish a feed; everything else stays WebSearch at
decision time, per the weekly workflow, rather than adversarial scraping for marginal
gain.

## YouTube (checked 2026-09-03) — upload discovery works, transcripts don't

Considered as a news source: trusted FPL creators' videos, not X (ruled out separately —
see the git history for that discussion).

**Video-upload discovery is legitimate and works** — same category as the blog RSS
feeds above, not scraping. Every channel publishes a public feed at
`youtube.com/feeds/videos.xml?channel_id=...`; verified live against FPL Harry's real
channel (`UCcPWnCj5AKC19HaySZjb25g`), returning today's GW3 uploads with titles and
publish times. Needs the channel's underlying ID, not its `@handle` — resolvable from
the channel page's HTML.

Named creators and their upload-feed feasibility:

| Creator | Platform | Feasibility |
|---|---|---|
| FPL Harry, FPL BlackBox, FPL General, FPL Raptor | Own YouTube channel, frequent uploads | Easy |
| Gianni Buttice | Own YouTube channel | Easy (free tier only — Patreon content paywalled) |
| Let's Talk FPL (Andy) | Primarily podcast, has a YouTube channel | Mixed, workable |
| Ben Crellin, BigMan Bakar | No own channel — appear on Fantasy Football Hub's shared channel | Harder — needs filtering FFH's whole channel by name, nothing missed but noisy |

**Transcript pulling: the raw scrape doesn't work, `yt-dlp` does — built and live,
2026-09-03.** A raw HTTP fetch of the signed caption-track URL embedded in a video's
watch page (what `youtube-transcript-api` and similar libraries do under the hood)
returns `HTTP 200`, `server: video-timedtext`, `content-length: 0` — silently empty,
not blocked outright. Confirmed reproducible from a real residential IP (Verizon FiOS,
not a cloud sandbox — checked directly via `ipinfo.io` to rule that out first), so it
isn't an environment artifact. `yt-dlp`'s own extraction logic is a genuinely different
code path and works: real, accurate auto-generated (ASR) captions, confirmed word-for-word
against the actual video's audio on the first test. No official fallback exists either
way — the YouTube Data API's caption-download endpoint requires OAuth and only works
for videos the authenticated account owns, so it never covers third-party creators
regardless of which extraction method is used.

**Built:** `scripts/fetch_news.py` pulls upload feeds for 5 of the named creators (all
"Easy" tier — Ben Crellin and BigMan Bakar excluded, no dedicated channel to pull) and
attempts a transcript for every new video via `yt_dlp`'s Python API. First real run
against 65 videos: **59 transcripts (91%)**, 6 explained failures — 4 age-restricted
(all from one channel, Gianni Buttice's — needs authenticated cookies to bypass, not
worth building, same call already made against session-cookie auth for FPL's
`my-team` endpoint) and 2 unstarted livestreams (will resolve once they air). One
operational finding baked into the code: back-to-back pulls tripped YouTube's rate
limit (`HTTP 429`) after ~4 requests — fixed with a 2-second delay before each pull,
verified afterward by retrying the 5 rate-limited videos, all 5 succeeded.

Transcripts are cleaned plain text (roll-up VTT timing markup stripped and
deduplicated), stored one file per video under `news/transcripts/`, referenced from
`news/entries.jsonl` by path rather than inlined.

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
