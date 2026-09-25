# Laya minutes caller: spec

Status: proposed (2026-09-24). Owner: Joe + Claude on the Studio. Shadow only.

## The question

CLAUDE.md step 6b says the measured minutes error "decides whether the LLM/news override
layer is worth building at all", and `scripts/creator_minutes.py` already runs that test
for YouTube creators. Current score (data/creator_minutes.json, GW4 onward): 223 scored
calls, creators 88.3% vs minutes model 89.7%; 29 disagreements, model right 16, creators 13.

This spec adds a third caller: **Laya**, a local "decision model" (open-source clone of
TypeSafe's Jev) that reads a short text and returns calibrated probabilities instead of
prose. The one question it answers here: **for player P in gameweek N, given the text
published before the deadline, will P play 60+ league minutes?**

It never touches a transfer, captain or chip decision. It produces a number, and the
number is scored.

## Why this and not "Laya scores hold vs transfer vs captain"

The idea logged in the shared workspace (Instinct, 2026-09-24) was to have Laya score the
hold/transfer/captain options in shadow mode. That is the wrong job for it:

- Laya's own docs warn against arithmetic, counting and date comparisons. Those
  decisions are projected-points arithmetic over a six-GW horizon, which
  `projections.py` and `decisions.py` already do exactly.
- Its context is 512 to 1024 tokens. A squad plus fixtures plus prices does not fit.

Minutes-from-news is the opposite shape: short text in, one probability out, and a hard
ground truth (actual minutes) that the project already records.

## Model

- **laya-mlx** (MLX port for Apple Silicon, Sep 2026). English checkpoint ~421M params
  (ModernBERT-large), multilingual ~322M. Under 1 GB of memory, ~7 ms per decision.
  Runs locally on the Studio, free, next to Ollama.
- Before installing: confirm the upstream Laya licence and the exact repo/weights
  provenance (the project is a week old and heavily hyped; fake repos are likely).
  Record both in docs/PRIOR_ART.md. Pin the weights by hash.
- Hosted Jev (TypeSafe API) is out of scope: paid, and news text would leave the machine.

## Inputs (all already in the repo)

For each (gw, player) that the minutes model froze in `minutes/gwNN.jsonl`:

1. **News**: `news/entries.jsonl` items whose `published` is before that GW's deadline and
   whose title or summary resolves to the player (reuse the roster name resolution used by
   the gameweek-brief / findings pipeline, never fuzzy-match inside Laya).
2. **Creator claims**: `news/findings/` entries for the player with a `minutes_call`
   (the same rows creator_minutes.py scores), using the `claim` text, not the call.
3. **FPL status**: `elements[].news` and `chance_of_playing_next_round` from the cached
   bootstrap snapshot taken before the deadline.

Hard rules, enforced in code, not in the prompt:
- **No leakage.** Only text with a timestamp strictly before the deadline. Laya is bad at
  dates, so the date filter must happen before Laya sees anything.
- **One player per question.** Build a short state (player, club, the 1 to 5 most recent
  snippets, each under ~60 words, newest first) that fits in ~400 tokens.
- **No numbers for Laya to reason about.** Pass the FPL chance-of-playing as a word band
  ("75% flagged" becomes "flagged doubtful"), or leave it out and test both.

## Questions asked of Laya

- `noul`: "This player will play at least 60 league minutes in the next match." -> p
- `choice`: status in {starts, benched, out, doubt} -> distribution (for comparison with
  creator calls; `doubt` makes no binary call, as in creator_minutes.py)

## New pieces

- `scripts/laya_minutes.py`
  - `build`: assemble the per-player states for a GW from the inputs above and write
    `laya/states/gwNN.jsonl` (auditable: exactly what Laya saw).
  - `archive --gw N`: run Laya on the states **before the deadline** and write
    `laya/gwNN.jsonl` (element, p_60, choice distribution, model hash, run time). Refuses to
    overwrite, same discipline as `minutes.py archive`.
  - `backfill --gw N`: for past GWs only, re-run on the pre-deadline states and mark rows
    `backfill: true`. Backfilled rows are scored separately from live ones.
- `scripts/creator_minutes.py`: add Laya as a third caller in the same report (or a
  sibling `laya_score.py` if that keeps the file clearer). Store results under
  `data/creator_minutes.json` -> `laya` block.
- `freeze.py`: once live, call `laya_minutes.py build && archive` in the same pre-deadline
  window as the minutes freeze. Resolution needs nothing new: actual minutes already land.

## Scoring (what "worth it" means)

Target: 60+ league minutes, identical to creator_minutes.py and the model's `p_60_plus`.

1. **Accuracy at 0.5**, side by side: model, creators, Laya.
2. **Brier score and log loss** of `p_60` vs the model's `p_60_plus` on the same players.
   Laya returns probabilities, so score them as probabilities, not just right/wrong.
3. **Disagreements** (|laya p_60 - model p_60_plus| >= 0.3): who was right, and by how much.
4. **Blend test**: `p = (1 - w) * model + w * laya` for w in {0, 0.1, ..., 0.5}. The only
   outcome that justifies building an override layer is a blend that beats the model alone
   on Brier, out of sample (fit w on backfill GWs, check it on live GWs).
5. **Calibration table**: bucket Laya's p_60 into deciles; does 0.8 mean 80%?

## Gates

- **Gate A (backfill, GW4 to GW5 now, more as they settle):** Laya beats creators on
  Brier. If it can't beat a human reading the same news, stop.
- **Gate B (live, at least 4 GWs archived before deadlines):** a blend weight w > 0 beats
  the model alone on Brier on live rows. If not, record the result in docs/IDEAS.md and stop.
- **Only after Gate B**: propose the override layer as its own spec. Laya still never
  makes a transfer or captain decision directly.

## Out of scope

- Captaincy, transfers, chips, projections.
- Fine-tuning Laya. First see how the stock model does; fine-tuning on ~300 labelled calls
  is a later question with its own overfitting risk.
- Anything that sends news text off the Studio.

## First session checklist

1. Verify laya-mlx provenance and licence; install into `.venv` (or a separate venv if its
   dependencies clash); pin weights by hash; smoke test one question.
2. Write `laya_minutes.py build` for GW5 and read 10 states by eye.
3. Backfill GW4 and GW5, extend the creator_minutes report, read Gate A.
4. Decide whether to wire it into freeze.py before the GW6 deadline (Sat 10 Oct, 10:00 UTC).

## Sources

- Simon Willison on Jev: https://simonwillison.net/2026/Sep/21/jev/
- laya-mlx: https://pasqualepillitteri.it/en/news/17538/laya-mlx-jev-apple-silicon
- Laya-MLX background and limits: https://aiidelist.com/blog/what-is-laya-mlx
