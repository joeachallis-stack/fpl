# News log

`entries.jsonl` — one JSON object per line, append-only, created and updated by
`scripts/fetch_news.py`. Runs automatically every time `scripts/fetch_data.py` runs;
there is no separate schedule.

Tracked in git deliberately, unlike `data/`. An RSS feed only ever shows its most
recent items — once one scrolls off, it's gone for good, with no backfill endpoint.
That's the same problem set-piece order had before `data/snapshots/` existed. This
file is the fix for the news equivalent: append-only means nothing already fetched
is ever overwritten or lost, so "what did we know and when" survives even after the
source feed has moved on.

Each entry: `source`, `title`, `link`, `published` (from the feed, best-effort
normalized to ISO 8601), `summary` (HTML stripped), `fetched_at` (when this project
pulled it — not the same as `published`). Headlines and links only, deliberately —
no judgment about what a headline means. That reading happens in the LLM judgment
layer, not here.

See `scripts/fetch_news.py`'s module docstring for the source list and rationale.
