# Odds archive

One file per distinct bookmaker market state, written by `scripts/odds.py`.

Tracked in git, unlike `data/`. Bookmakers price only about a week ahead, and The Odds
API bills separately for its historical endpoint — a line not stored before kickoff
cannot be recovered at any price. Same reasoning as `news/entries.jsonl` and
`minutes/gwNN.jsonl`: the expensive, unrepeatable thing is the observation.

- `odds_YYYY-MM-DDTHHMMZ.json` — derived fair probabilities matched to FPL fixture ids,
  plus `market_sha256` over the raw market content.
- The raw API response for the same fetch is kept at
  `data/odds_raw/odds_raw_<same stamp>.json` — gitignored, needed only to re-derive
  locally with a different de-vig method.

Identical market content is not re-archived, so a cached read adds nothing. Timestamps
are the fetch time, so the last file before a kickoff is that fixture's closing line.
