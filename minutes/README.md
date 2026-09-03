# Minutes model track record

One file per gameweek, `gw03.jsonl` and so on, written **before** that gameweek's
deadline by `python scripts/minutes.py archive`.

Git-tracked, unlike `data/`. A prediction is only worth something if it was recorded
before the fact, and it cannot be reconstructed afterwards: `data/minutes.json` is
overwritten on every run, and its inputs — a player's fitness flag, his minutes so far,
who was in the squad — all move on. Same reasoning that put `news/` and
`data/snapshots/` in git.

Each row stores the **inputs as well as the prediction**. That's what lets the model's
own constants be replaced by measurements later. The clearest example: a doubtful player
is currently assumed to play 30 minutes if he plays at all, which is a guess nobody has
ever checked. Store `status` and `chance_of_playing` next to what the player actually
went on to play, and after fifteen gameweeks the question "what do 75%-flagged players
really average?" has a real answer, and the constant can be retired.

`python scripts/minutes.py resolve --gw N` fills in `actual_minutes` and `actual_band`
once the gameweek has settled, rewriting the file in place.
