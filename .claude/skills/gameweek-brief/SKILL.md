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

Use `model: sonnet`. This is a tight spec with no open-ended judgment and five validation
layers behind it; Opus costs roughly five times as much for work the validators would
catch anyway. Save Opus for step 3, where judgment actually happens.

Run at most **two agents at once**. This caps concurrency, not coverage — every video
still gets read, just not simultaneously. Five in parallel does not extract more; it hits
the session limit and loses all five, which is how ten GW3 videos went unread on the first
attempt.

Each agent's prompt needs only: follow `.claude/skills/gameweek-brief/extraction_spec.md`,
the batch's transcript paths with their `video_id` / `source` / `speaker` / `published`,
the current gameweek and deadline, and the output path `news/findings/gwNN_batchN.jsonl`.
Copy the batch lines `prepare_extraction.py` prints — the `speaker:` name on each one is
what the agent writes into every claim.

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
so agreement and dissent are visible. Schema violations print first, then contradictions.

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

## The five validation layers

Each catches something the others cannot. Layers 1-4 guard *identity* — they catch a
fabricated player and say nothing about a fabricated category. Layer 5 was added when
classification moved to three constrained fields.

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

5. **Schema validation.** `findings.py` holds the allowed vocabulary for `topic`,
   `kind`, `horizon`, `stance` and `conviction`, and `consolidate.py` reports every value
   outside it before anything else. An unrecognised `topic` is worse than a wrong one: it
   makes the finding silently invisible in the brief rather than visibly misfiled. It
   reports and never repairs, for the same reason the unresolved-name report does.

   `findings.py` also owns loading. `gw04_*.jsonl` matches both a batch and its migrated
   `.v2` twin, and a naive glob counted every GW4 finding twice — 194 for a corpus of 97.

## The three classification axes

A finding is classified on three axes, not one. `extraction_spec.md` is authoritative;
this is the summary of why they exist.

- **`topic`** — what the claim is about: `minutes`, `injury`, `role`, `set_piece`,
  `form`, `fixtures`, `price`, `captaincy`, `chip`, `transfer`.
- **`kind`** — what type of information it is: `news`, `read`, `stat`,
  `recommendation`, `action`.
- **`horizon`** — when it bites: `this_gw`, `next_few`, `season`.

Plus a `teams` array, so a claim about a club rather than a player ("Hull have conceded
3.12 xG in two games") attaches to something instead of being lost.

There is no `owned_player` or `target` category any more, and adding one back would be a
mistake. Whether Joe owns a player is read from his actual squad downstream. Asking the
extractor for it put half the corpus on a different axis from the rest and left it with
no topic at all — 51% of 474 findings, of which a third were really minutes claims.

`minutes` is consistently the largest bucket and feeds the minutes model directly.
`kind` is the axis that decides reading order: `news` and `read` describe things the
model structurally cannot see, while `stat` is usually a number `projections.py` already
computes and is kept only as a cross-check. `action` — what a creator *did* with their
own team — is stronger evidence than what they advise, and is deliberately separated
from `recommendation` for that reason. `set_piece` and `price` are empty in Shorts and
rich in long-form; that is a format artifact, not a dead category.

## Name the speaker in every claim

`prepare_extraction.py` prints a `speaker:` name on each batch line, resolved from
`news/creators.json`. Claims must use it — "Raptor is 99% likely to wildcard", never
"the creator is 99% likely to wildcard".

This is not a style preference. The entire value of consolidation is seeing which
creators agree and which dissent, and a claim with an anonymous speaker cannot enter that
comparison. Findings from GW4 batch 1 were written as "the creator" and had to be
rewritten from each row's `source` field afterwards.

Plural is different and must be left alone: "Creators see higher upside in City assets"
is the speaker reporting community consensus, not referring to himself.

**Shorts are dense, not thin.** They are 8% of the text, which makes them look like the
low-value tail — they are the opposite. A 60-second wildcard reveal is a full XI of
rationale with no filler, while a livestream runs 60-70% ads, chat, and the same bench
question answered twenty times. Group Shorts into one agent for cost, never to
deprioritise them.

## Known costs

A full week is ~250KB of long-form across ~9 videos, plus ~11 Shorts that are only 8% of
the text. Fixed overhead is ~4k tokens per agent for spec and roster, which is why Shorts
go in one batch rather than spread across four.
