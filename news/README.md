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

Each entry: `kind` (`"article"` or `"video"` — absent on entries written before
2026-09-03, treat missing as `"article"`), `source`, `title`, `link`, `published`
(from the feed, best-effort normalized to ISO 8601), `summary` (HTML stripped),
`fetched_at` (when this project pulled it — not the same as `published`). Video
entries also carry `video_id` and `transcript_file` — a path to a plain-text
transcript under `transcripts/`, or `null` if none was available for that video
(no captions, an unstarted livestream, or age-restricted content — see
`scripts/fetch_news.py`'s `pull_transcript` docstring).

Headlines, links, and — for video — transcripts, deliberately with no judgment
about what any of it means. That reading happens in the LLM judgment layer, not
here.

`transcripts/*.txt` — one file per video with available captions, named by video
ID, plain cleaned text (no VTT timing markup). Tracked in git, same reasoning as
`entries.jsonl` itself: pulled once, not re-fetchable if lost.

See `scripts/fetch_news.py`'s module docstring for the source list and rationale.
