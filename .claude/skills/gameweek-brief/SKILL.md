---
name: gameweek-brief
description: Consolidate what FPL content creators are saying into a decision brief for the upcoming gameweek. Use when Joe says /gameweek-brief, "what are the creators saying", "what should I do this week", "review my team", "consolidate the news", or before any transfer, captaincy or chip decision. Reads YouTube transcripts and RSS items already pulled by fetch_news.py, extracts structured findings, checks them against FPL's own data, and reports consensus and dissent. Do NOT use for pulling new transcripts (that is fetch_data.py) or for scoring past decisions (that is journal.py).
---

# Gameweek brief

Replaces the manual routine: watch several creators, take the bits relevant to your own
team, and whittle infinite options down to a few. Same inputs, but the claims get checked
against FPL's own data instead of being believed.

**The one rule everything else serves: an LLM is never the authority on a fact FPL already
publishes.** Extraction supplies claims. The roster supplies identity. The match record
adjudicates. Where they disagree, the data wins and the disagreement is shown.

## Run it

### 1. Refresh, then prepare

```bash
python scripts/fetch_data.py          # also runs fetch_news.py
python scripts/prepare_extraction.py --gw N
```

`prepare_extraction.py` prints the batches to run and writes `news/roster.txt`. It has
already discarded everything not worth reading — see *Why the filtering matters* below.
If it says nothing to do, every current video is already extracted; go straight to step 3.

After each batch finishes, record it:

```bash
python scripts/ledger.py record --video VIDEO_ID --gw N --findings COUNT --model sonnet
```

`news/extracted.jsonl` is why a rerun costs almost nothing: a video is read once, ever.
Record it explicitly rather than letting the next run infer it from findings on disk — an
agent that dies mid-batch leaves partial findings, and the videos it never reached look
identical to the ones it finished. Two batches died on a session limit exactly that way.
Use `--status partial` if an agent was cut off, so the video is retried rather than
skipped.

The ledger also stores the spec version. When the spec gains something material — the
Tzolis trap, a batch of new aliases — `ledger.py show` marks which videos were read under
older rules, so re-reading a few high-value ones becomes a decision you can actually make.

### 2. Extract — one subagent per batch, **on Sonnet**

Use `model: sonnet`. This is a tight spec with no open-ended judgment and four validation
layers behind it; Opus costs roughly five times as much for work the validators would
catch anyway. Save Opus for step 3, where judgment actually happens.

Run at most **two agents at once**. This caps concurrency, not coverage — every video
still gets read, just not simultaneously. Five in parallel does not extract more; it hits
the session limit and loses all five, which is how ten GW3 videos went unread on the first
attempt.

Each agent's prompt needs only: follow `.claude/skills/gameweek-brief/extraction_spec.md`,
the batch's transcript paths with their `video_id` / `source` / `published`, the current
gameweek and deadline, and the output path `news/findings/gwNN_batchN.jsonl`.

**Agents write findings to that file and return only a short note.** A batch produces
100+ findings; returning them as conversation text costs enormous context and risks
losing them. The note should cover unresolved names, shaky attributions, and anything a
future run should know — that note is how this skill improves.

Pass any manglings earlier batches confirmed. Cross-video triangulation is what pins down
a garbled name, so agents that know what previous agents decoded do better.

### 3. Consolidate

```bash
python scripts/consolidate.py --gw N            # everything with 2+ mentions
python scripts/consolidate.py --gw N --owned    # just the current squad
```

Resolves every name, checks every falsifiable claim against the record, groups by player
so agreement and dissent are visible. Contradictions print first.

### 4. Read it against the deterministic layer

The brief is evidence, not a decision. Cross it with `state.py` (free transfers, chip
windows), `check_team.py` (legal XI, flags) and `data/minutes.json` (the model's own
minutes view). Where a creator and the minutes model disagree about a player's role,
say so — that disagreement is the most useful thing in the brief.

### 5. Improve this skill

Every run finds something. Fold it in before finishing: new aliases into
`news/aliases.json`, new traps into `extraction_spec.md`, new filters into
`claims.py`. The alias table and the spec are the assets that compound.

## Why the filtering matters

Two thirds of the corpus is worth nothing, and reading it is worse than not reading it.

- **A gameweek number is not a gameweek.** Videos titled "FPL Gameweek 13" published in
  November 2024 look, by label, like advice ten weeks ahead. Publish date against this
  season's first deadline separates them.
- **Videos are about a gameweek, not a date.** A six-day-old livestream is not slightly
  stale current advice; it is a settled gameweek's captaincy calls and team news. Filtering
  by "last 7 days" pulled 76 findings out of a played gameweek as though they were live.
- **Titles state the gameweek 79% of the time** and beat publish date, since a Monday
  video previews Saturday.
- **World Cup Fantasy is a different game.** These creators cover both on one channel.

## The four validation layers

Each catches something the others cannot.

1. **Constrained vocabulary.** Agents may only emit complete roster lines —
   `Palmer (Chelsea, MID)`, never `Palmer`. Display names are not unique: 17 collide,
   including two Palmers, Cole (Chelsea, MID) and Alex (Ipswich, GKP).
2. **Roster validation.** `roster.py` resolves names and attaches team, position and
   price. When a caption says "Mac Allister of Brighton" and the roster says Liverpool,
   the roster wins. Collisions resolve by attention (ownership x price) and stay
   ambiguous when genuinely close — Martinez is a Chelsea keeper and a Man Utd defender,
   both playing every minute at the same price, and that is not a call worth guessing.
3. **Unresolved report and aliases.** Misses are printed with counts, and recurring ones
   earn an entry in `news/aliases.json`. If "Gabrielle" fails twenty times, that is every
   mention of Gabriel vanishing silently. The table only grows from observed failures.
4. **Claim verification.** `claims.py` tests falsifiable claims against the record. This
   is the only layer that catches the dangerous case: **a mangling that lands on another
   real player's name.** Captions rendered Tzolis as "Solanke" — both real, both valid
   roster lines, so every name check passed and two runs attributed the same event to
   different people. The record settled it: Tzolis played 45 minutes and was booked;
   Solanke played 15 off the bench and was not.

   It stays quiet on anything hedged or negated. A checker that cries wolf gets ignored.

## Categories

`owned_player`, `target`, `chip`, `fixtures`, `captaincy`, `minutes_risk`, `set_piece`,
`price`, `creator_action`, `misc`.

`minutes_risk` is consistently the largest bucket and feeds the minutes model directly.
`creator_action` — what a creator *did* with their own team — is stronger evidence than
what they advise. `set_piece` and `price` are empty in Shorts and rich in long-form; that
is a format artifact, not a dead category.

## Known costs

A full week is ~250KB of long-form across ~9 videos, plus ~11 Shorts that are only 8% of
the text. Fixed overhead is ~4k tokens per agent for spec and roster, which is why Shorts
go in one batch rather than spread across four.
