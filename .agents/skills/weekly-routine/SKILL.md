---
name: weekly-routine
description: Run the full between-gameweeks routine - settle the gameweek just played, then prepare the next one (state, fixtures, flags, projections, decisions, creator brief, recommendation, journal). Use when Joe says /weekly-routine, "GW N ended", "do our regular routine", "what should I do this week", "review my team", or "start the week". Do NOT use for transcript extraction alone (that is gameweek-brief) or for one-off questions about a single player.
---

# Weekly routine

Two halves with opposite timing rules. **Settling** can only happen after FPL finalizes a
gameweek and is safe to run late. **Preparing** must finish before the next deadline and
cannot be redone afterwards. Don't let one block the other: if the last gameweek isn't
final yet, prepare anyway and come back to settle.

## 0. Refresh and find out where you actually are

```bash
python scripts/fetch_data.py      # also pulls RSS + transcripts; close Chrome first
python scripts/state.py           # deadline, banked FTs, chip windows
python scripts/freeze.py --status # what is archived, finalized, awaiting resolve
```

**"The gameweek ended" usually means the weekend ended, not that FPL has settled it.**
Check before resolving anything:

```bash
python -c "import json;b=json.load(open('data/bootstrap.json'));print([(e['id'],e['finished'],e['data_checked']) for e in b['events'] if e['is_current']])"
```

and look for unplayed fixtures (a Monday game) and `data/event_status.json`
`bonus_added: false`. Until `finished` and `data_checked` are both true, the resolve steps
below will score against provisional numbers. Tell Joe what is still outstanding and
whether he has anyone in it, then carry on with the preparing half.

## 1. Settle the last gameweek (only once finalized)

The hourly launchd job (`com.joechallis.fpl-freeze`, running `freeze.py`) resolves minutes,
projections **and the journal**, then refreshes evaluation, on its own. Check `freeze.py --status` says
`awaiting resolve: none`. If it doesn't, run `python scripts/freeze.py --resolve-only`
(it can take over 10 minutes after a fresh `fetch_data.py`; run it in the background).
Then read the results:

```bash
python scripts/journal.py show
python scripts/evaluate.py
```

A resolved entry that a later `SUPERSEDES` entry replaced still gets scored. Report the
taken entries, and read superseded ones only as "what the first recommendation would have
done".

Report briefly: points against the model's projection, whether captain and transfer calls
beat their runners-up, and anything the evaluation now says about lead-time error. Open
entries that supersede one another (a recommendation, then what was actually taken) should
be read together. Score what was **taken**.

## 2. Creator evidence: start it early

Transcript extraction is the slow part and runs in the background, so kick it off as soon
as the refresh is done. Follow the `gameweek-brief` skill (Sonnet agents, at most two at
once, `ledger.py record` after each batch). Early-week videos are "early thoughts". Rerun
`fetch_data.py` + `prepare_extraction.py` later in the week to pick up team-selection
videos, which carry more `action` findings.

**Review videos are mislabelled for this purpose.** A "GW N review" published *after* the
GW N deadline is filtered out by title, but its injuries, suspensions and role reads are
GW N+1 evidence. Look for them in `news/entries.jsonl` (published after the last deadline,
title says the previous GW). Extract them as the new gameweek, and tell the agent to keep
only what carries forward. Livestream reviews run ~65% filler, so expect ~30 findings.

Tell the extraction agents about anything unsettled at recording time (for example, a
Monday fixture still to play) so they don't record speculation as fact.

## 3. Prepare the next gameweek (while extraction runs)

In order, stopping to look at output rather than piping through:

1. `python scripts/check_team.py`: illegal XI, flagged starters, captain and vice in the
   same match, blanks, bench cover. This validates the *last saved* squad only.
2. Injuries and news: `elements[].news` / `chance_of_playing_next_round` for owned players
   and targets. Use WebSearch for anything flagged, because the API field lags.
   **The minutes model is blind to European and cup congestion.** `check_team.py` and
   `decisions.py` now print midweek matches from `midweek/fixtures.json` (a `*` marks a
   buy from a flagged club). `python scripts/midweek.py` shows the full list. The file is
   hand-maintained: after each cup draw, or when TV picks fix kick-off times, add the rows
   with a source URL, and read its `known_gaps` before treating a missing club as fresh.
3. `python scripts/projections.py`: read the component breakdown for implausible inputs
   (minutes, odds coverage, set-piece duty) before trusting totals.
4. `python scripts/decisions.py`: hold against 1-5 transfer plans, plus Free Hit and Wildcard.
   Weigh the gain against banking, because FTs accrue to 5.
5. `python scripts/consolidate.py --gw N --owned` and the full view once batches land.
   Cross creator claims with `data/minutes.json`. Disagreement about role is the most
   useful thing to surface. Once the minutes archive is frozen,
   `python scripts/creator_minutes.py --gw N` lists every player where a creator's
   `minutes_call` and the model's frozen p(60+) disagree. After settlement the same command
   says who was right, and `creator_minutes.py` with no argument keeps the running tally.

## 4. Recommend, then record before the deadline

Recommend hold/transfer (in, out, price, hit), captain and vice, and chip or no chip. Cite
the actual numbers. Objective is **total points**: ownership/EO is context only.

Then log every call **with its runner-up and the case against**:

```bash
python scripts/journal.py add ...   # see journal.py add --help
```

When Joe takes something different, add a superseding `TAKEN:` entry rather than editing.

Archives (`minutes.py archive`, `projections.py archive`, `decisions.py archive`) are
frozen automatically by the hourly job inside the lead window. If the laptop may be asleep
near the deadline, freeze manually with `python scripts/freeze.py --force`. It never
overwrites, so it's safe to run any time.

## Don'ts

- Don't resolve a gameweek that isn't `finished` + `data_checked`.
- Don't use results after the deadline being planned for.
- Don't use cup goals or minutes as projection inputs. They can inform a minutes *read*,
  and belong in the journal as context.
- Don't let `shadow_*` fields near `decisions.py` selection.
