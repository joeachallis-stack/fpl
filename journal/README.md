# Decision journal

`entries.jsonl` — one JSON object per line, append-only, created by `scripts/journal.py`.
Not present until the first entry is logged.

Tracked in git deliberately, unlike `data/` — this is an authored record with value for
the whole season, not an API cache to discard and refetch.

See `scripts/journal.py` module docstring for usage.
