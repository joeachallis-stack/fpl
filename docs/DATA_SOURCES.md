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

**Owned-player selling prices require reconstruction.** The public picks response contains
the squad but no purchase/selling price. `scripts/decisions.py` uses the most recent
`element_in_cost` from the public transfer log for a transferred-in player; for an
initial-squad player it uses the first official `element-summary` history value. It then
applies the live `game_settings.element_sell_at_purchase_price` and
`transfers_sell_on_fee` parameters against the player's current `now_cost`. The script
keeps that provenance per player and refuses to optimize if an acquisition price is
missing, since silently substituting current price could make an unaffordable move look
legal. Like `check_team.py`, this still describes the last deadline squad: only the
authenticated `my-team` endpoint could see transfers made since then.

## What bootstrap-static already carries (checked 2026-09-02)

Don't reach for a third-party source before checking these — several fields that used to
require FBref or a price-tracking site are now native:

- **Underlying numbers**: `expected_goals`, `expected_assists`, `expected_goal_involvements`,
  `expected_goals_conceded`, all with `_per_90` variants, plus `defensive_contribution`,
  `tackles`, `recoveries`, `clearances_blocks_interceptions`. FBref is now a
  sanity-check, not a dependency.
- **Price changes**: `price_change_projections` (percent-to-change at offsets 0/1/2 days
  with a `likelihood` score), `price_change_hourly_rate`, `price_change_locked_until`.
  These projections are supplied by FPL itself in the official `bootstrap-static`
  response — no need to build a model off cache deltas or use a third-party predictor.
  The API is undocumented, so the formula and the exact calibration of the signed
  `likelihood` scale (-5 to +5) are unknown; treat it as FPL's projection, not a
  guaranteed price change. `show_team.py` surfaces owned players whose absolute
  likelihood reaches 4 within the next two days, alongside net gameweek transfers.
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
- `fantasyfootballhub.co.uk` — tested and closed, not just deferred. No RSS: every real
  feed path (`/feed`, `/feed/`, `/rss.xml`) returns `404`. One trap worth knowing about
  if this gets re-checked later — `?feed=rss2` returns `200`, but that's WordPress
  silently falling back to the homepage for an unrecognized query param, not a real
  feed: `content-type: text/html`, zero `<item>` tags. Worse for scraping: FFH is a
  **Next.js single-page app** — fetched Crellin's own calendar article page directly,
  and the raw HTML's only real text is site navigation ("My Team," "Toolbox," "OPTA
  Stats"), not the article body, which loads client-side via JavaScript. Same failure
  mode as `premierleague.com`'s injury page. Getting real article text out would need a
  headless browser (Playwright or similar) — a materially bigger dependency than
  `yt-dlp` was, and the first one that isn't just `pip install` and go. Not worth it:
  Fantasy Football Scout already covers the dominant dedicated FPL outlet, Crellin's
  calendar is already handled separately (the Google Sheet, not FFH's page about it),
  and Crellin/Bakar's video content was already excluded from the transcript build as
  "harder, needs filtering." What's left — FFH's own written articles — is unproven
  value behind real new infrastructure.
- Mainstream outlets (BBC, The Guardian, talkSPORT, Metro) — no sustained FPL beat,
  just occasional one-off pieces; not worth building around. The Athletic has genuine
  FPL depth (a real columnist) but is paywalled — same "leave it alone" call as FFH's
  Members Area and `premierinjuries.com`'s bot-wall, working around a subscription
  isn't a data-ingestion problem, it's a different kind of thing entirely.

A scraper is not currently planned as a fast-follow for any of these — the RSS layer
covers the sources that actually publish a feed; everything else stays WebSearch at
decision time, per the weekly workflow, rather than adversarial scraping for marginal
gain.

## YouTube (checked 2026-09-03) — upload discovery and transcripts both work

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

**Channel IDs: read `externalId`, not the first `channelId` in the page.** A channel
page's markup contains `channelId` strings for related and featured channels too, so
grabbing the first match can silently subscribe you to somebody else's uploads. This
happened: `fplblackbox` pointed at "BlackBox Gaming" — a separate channel from the same
brand — and ingested five horror-game livestreams as FPL analysis before anyone noticed.
Corrected 2026-09-03 to `UCGJ8-xqhOLwyJNuPMsVoQWQ` by reading `externalId` from
`youtube.com/@FPLBlackBox/videos`. Verify a new channel by its feed's `<title>`, not by
the handle resolving without error — the wrong ID resolved fine and returned real videos.

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

### Bookmaker odds — source and interpretation verified 2026-09-04

**Chosen source:** [The Odds API](https://the-odds-api.com/), using its
`soccer_epl` endpoint, UK region, and the `h2h,totals` markets. A live request on
2026-09-04 returned 19 upcoming fixtures across the next two rounds, with 16-21
bookmakers per fixture. The request cost 2 credits from the free plan's monthly
allowance of 500.

**Credential handling:** the key lives only in the gitignored repository `.env` as
`THE_ODDS_API_KEY`. Never put it in `config.json`, a request log, an exception message,
or a committed file. Code should fail clearly or skip this optional source when the
variable is absent; the official FPL refresh must not depend on a third-party secret.

**Raw fields are odds, not probabilities.** Decimal odds include each bookmaker's
margin. Convert and remove that margin separately for every bookmaker and market:

```
raw_i = 1 / decimal_odds_i
fair_i = raw_i / sum(raw outcomes in that bookmaker's market)
```

For `h2h`, the denominator contains home, draw and away. For `totals`, it contains
over and under. Aggregate the resulting fair probabilities across bookmakers with the
component-wise median, then renormalize the median vector to sum to one. Do not average
raw decimal odds or mix bookmakers before removing their individual margins.

Interpretation rules that must be explicit in code and output:

- use `h2h` for home/draw/away probabilities;
- ignore the automatically returned `h2h_lay` exchange market;
- use only `totals` outcomes whose `point` is exactly `2.5` — the live response also
  contained 3.5-goal lines, which answer a different question;
- retain `commence_time` and each bookmaker/market `last_update`, so stale data is
  visible rather than silently treated as current;
- match to FPL fixtures using normalized team aliases plus kickoff time, never team
  display name alone;
- treat bookmaker coverage as near-term only. The verified response covered roughly
  two rounds, not the six-gameweek optimisation horizon, so FPL FDR remains the
  fallback for fixtures without odds;
- describe outputs as bookmaker-implied probabilities, not forecasts or certainties.

The raw response and any derived fixture probabilities belong under gitignored
`data/`. Preserve enough raw bookmaker data and the fetch timestamp to reproduce every
derived number. **Built 2026-09-04:** `scripts/odds.py`, called automatically by
`fetch_data.py`, writes `data/odds_raw.json` and `data/odds.json`. It caches requests for
two hours to protect the 500-credit monthly allowance; `--refresh-odds` bypasses that
cache. The first production run matched all 19 returned events to FPL fixture IDs with
zero unmatched events. H2H coverage was broad (16-21 bookmakers per fixture), while the
exact 2.5-goal totals line was much thinner (1-5), so downstream output must retain and
show the contributing-bookmaker counts.

**Player props verified, not ingested (2026-09-04).** The live event-market endpoint
advertised `player_goal_scorer_anytime`, first/last goalscorer, assists,
score-or-assist, shots-on-target, card and red-card markets. Real requests for Newcastle
v Bournemouth established the actual shapes and coverage:

| Market | Live shape | Bookmakers |
|---|---|---:|
| `player_goal_scorer_anytime` | `name: Yes`, player in `description`; 38-39 players | 2 |
| `player_goals_alternate` | `name: Over`, player in `description`, `point: 1.5`; 7 players | 1 |
| `player_assists` | `name: Over`, player in `description`, `point: 0.5`; 35 players | 1 |
| `player_to_receive_card` | `name: Yes`, player in `description`; 38-42 players | 2 |
| `player_to_receive_red_card` | `name: Yes`, player in `description`; 42 players | 1 |

Player identity must come from `description`, then pass through the canonical roster
resolver; `name` describes the bet outcome, not the footballer.

Do not treat `1 / odds` from this market as a fair scoring probability. Anytime-scorer
outcomes are not mutually exclusive — several players can score — and the response has
no paired `No` price for each player, so the bookmaker margin cannot be removed by
normalizing across the listed players. Coverage is also thin, player names need canonical
roster resolution, and the endpoint is queried once per event: one market across the
verified 19-fixture slate would cost 19 credits per refresh rather than 2. Until there is
a separately specified calibration method and a demonstrated decision use, retain this
as an available future signal rather than presenting it as probability. Alternate goals
can partly recover multi-goal upside via the tail-sum identity
`E[goals] = P(G>=1) + P(G>=2) + ...`, but the verified feed supplied `P(G>=2)` for only
seven players from one bookmaker. Assists similarly supplies only `P(A>=1)`, not expected
assist count. Card and red-card markets may overlap (a red can follow a booking), so they
must not be subtracted independently without a market-definition or historical
calibration that prevents double counting.

### Historical minutes training — built 2026-09-05

`scripts/train_minutes.py --fetch` retrieves vaastav's public `merged_gw.csv` and
`players_raw.csv` for 2024/25 and 2025/26 into gitignored `data/`. The gameweek rows use
season-specific element IDs, so the join is strictly `element -> players_raw.code ->
current elements[].code`; names are never identity keys. Source URLs and SHA-256 hashes
are frozen in `models/minutes_params.json`.

Training predicts every 2025/26 gameweek using only older rows, with 2024/25 as the
cross-season prehistory. It searches a deliberately small grid over recency half-life
and position/price peer-prior strength. Model selection uses log loss plus minutes MAE
scaled to 90 on the pre-deadline-reproducible contender population: players averaging at
least 30 minutes over their prior three matches. All-player, early-GW and later-GW
diagnostics plus probability calibration bins remain in the artifact. The selected v1
fit uses a three-GW half-life and half an effective peer observation. Club-change
retention (0.5) and a four-GW offseason gap remain labeled assumptions because two
seasons cannot fit them reliably.

The fitted target is an eight-state joint role/minutes distribution: unused, 1-29 cameo,
30-59 cameo, rare 60-plus cameo, starter under 60, starter 60-74, starter 75-89, and
starter 90-plus. The rare eighth state preserves the real 60-minute FPL boundary for an
unusually early substitute. Each state retains its conditional expected minutes. The
public `p_zero` / `p_1_59` / `p_60_plus`, expected minutes, start probability, cameo
probability, and conditional start/cameo minutes are derived from that richer object.

This richer-state representation was tested as a challenger against independently
re-tuned coarse bands on exactly the same walk-forward folds. It won narrowly: contender
log loss 0.77717 -> 0.77697, Brier 0.43849 -> 0.43836, minutes MAE 26.398 -> 26.385,
and combined score 1.07048 -> 1.07013. The structural detail is useful, but the measured
forecast improvement is tiny and should be described that way.

On the comparable GW6-38 contender slice, the trained model improved band log loss
from 0.7851 to 0.7734 and Brier score from 0.4501 to 0.4364, while minutes MAE worsened
from 25.65 to 26.33. Its combined selection score improved only from 1.0701 to 1.0659:
useful but modest, not evidence that minutes are solved. Across all contender folds,
expected calibration error is 0.0396 for nonappearance and 0.0322 for 60-plus. The full
bins remain in the artifact so tail miscalibration is visible rather than summarized
away.

At runtime `minutes.py` combines completed current-season rows, safely code-matched
prior-season rows, and the peer prior. It falls back to the older empirical rules if the
historical cache or model artifact is missing. Injury/suspension overrides remain a
separate layer. Each prediction freezes the source hash, stable code, selected parameters
and effective current/prior/peer weights; the probabilities are fitted scenario weights,
not claims of certainty. Each live minutes ledger also freezes the parameter artifact's
SHA-256, so a later retrain cannot silently change what an archived forecast meant.

### Expected-points and evaluation infrastructure — built 2026-09-04

`scripts/observations.py` appends finalized, data-checked player-fixture rows to
`observations/player_fixtures.jsonl`; it is called after element summaries refresh.
Double gameweeks remain separate fixtures and later official corrections append a
revision rather than rewriting history. The first run captured 1,236 finalized rows for
GWs 1-2 and an immediate rerun appended zero duplicates.

`scripts/projections.py` produces a configurable multi-gameweek player xP matrix in
`data/projections.json` (default six, `--horizon N`) and can freeze a pre-deadline ledger
under `projections/`. It deliberately exposes the
component sum instead of returning an unexplained score:

- appearance points from the minutes model's scoring-aligned bands;
- team goal rates from an independent-Poisson model fitted to the de-vigged 1X2 and
  over/under 2.5 probabilities, with numerical fit error retained;
- player goal/assist shares from official per-match xG/xA. Only completed fixtures count.
  Current-season rates are blended against a 900-minute prior built from the player's
  latest official `history_past` season, itself shrunk 450 minutes toward the live
  positional rate. These are explicit starting assumptions to recalibrate, not fitted
  truth; every raw season total, weight and resulting rate is frozen in the archive;
- clean-sheet and goals-conceded expectation from the inferred opponent goal rate;
- yellow, red and save components use the same auditable prior-season blend. DefCon stays
  current-season/position based because a season aggregate cannot recover per-match
  threshold hits. Prior-season bonus is deliberately excluded because the 2026/27 BPS
  changes make it directionally non-comparable; each player's sample size is retained.

The model reads point weights from `bootstrap.game_config.scoring`, refuses to publish a
ranking unless all ten next-gameweek fixtures have usable odds, and records bookmaker
counts plus known limitations on every player. Exact odds supply fixtures where present;
later fixtures use venue/FDR goal-rate buckets calibrated from the live odds sample,
adjusted by recent team xG attack/defence factors shrunk five matches toward league
average. The five rates for each venue are constrained to be monotonic, so a harder FDR
cannot imply a higher base scoring rate. Market team-side counts, raw and fitted rates,
and a sparse flag for buckets with fewer than three observations are retained globally
and on every fallback fixture. Every horizon row labels its source. It does not yet model penalty saves,
penalty misses or own goals, and does not ingest player props until those prices can be
calibrated without mislabeling margined inverse odds as fair probabilities. Bonus is a
shrunk empirical expectation, not a reconstruction of the interdependent BPS contest;
the frozen ledger will determine whether that approximation earns its place.

Calibration membership is frozen before the deadline: owned players plus the top ten
per position by discounted horizon xP and by horizon xP/value, among players projected
for at least 45 minutes. Ownership percentage is display-only and never enters forecasts,
candidates or weights. All players retain minimal archived horizon xP for diagnostic
grading; the calibration-weighted players retain full inputs. This reduced a test archive
from about 2.9 MB to 482 KB without discarding fitting evidence. `scripts/evaluate.py`
reports all-player diagnostics separately from the decision-weighted primary error and
breaks both out by GW+1, GW+2, etc., over a configurable rolling archive window.

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

- **Long-horizon bookmaker odds** — the selected odds source provides current upcoming
  markets, verified at roughly two rounds on 2026-09-04, not the full six-gameweek
  horizon. FPL FDR remains the fallback beyond available bookmaker coverage.
- **Predicted XIs / press conferences** — `chance_of_playing_next_round` lags the news by
  a day or more. `scout_news_link` helps; a WebSearch before the deadline still helps more.
- **Blank and double gameweeks** — not announced in advance; they fall out of cup
  progression and European congestion, and are human-curated (Ben Crellin's planner is the
  reference). Cheap early warning: watch `fixtures.json` for any fixture with
  `event: null`, or any gameweek whose fixture count drifts off 10.
