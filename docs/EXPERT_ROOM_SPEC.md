# Expert room — schema and section restructure

Draft for review. Replaces the flat `category` field and the undifferentiated
findings-per-player list with a decision-shaped brief.

## Why change it

The current 10 categories are four different axes in one field:

- relevance to Joe — `owned_player`, `target`
- topic — `minutes_risk`, `set_piece`, `price`, `fixtures`
- decision — `captaincy`, `chip`
- speaker state — `creator_action`
- dump — `misc`

Because the relevance axis is not a topic, it swallows 51% of the corpus (243 of 474)
and leaves it topically unclassified. Of those 243, roughly a third carry minutes
language, a quarter fixture language, a fifth chip language. Only 18% are pure opinion.

The relevance axis is also redundant: `consolidate.py` and `frontend_data.py` both derive
ownership from `picks_gwN.json`. The extractor never needed to tell us who Joe owns.

## Schema

```json
{
  "video_id": "...", "source": "...", "published": "2026-09-07",
  "players": ["Tzolis (Arsenal, MID)"],
  "teams": ["Hull City"],
  "unresolved": [],
  "topic": "minutes",
  "kind": "news",
  "horizon": "this_gw",
  "stance": "negative",
  "conviction": "strong",
  "claim": "one sentence stating what was said",
  "quote": "verbatim snippet under 30 words"
}
```

Unchanged: `video_id`, `source`, `published`, `players`, `unresolved`, `stance`,
`conviction`, `claim`, `quote`.

Removed: `category`. The owned/target distinction is derived, never extracted.

### `topic` — what the claim is about (one axis, 10 values)

| topic | covers |
|---|---|
| `minutes` | starting, benching, rotation, hooked early, squad competition |
| `injury` | knock, fitness, return timeline, suspension |
| `role` | where and how he plays — moved central, false 9, deeper role |
| `set_piece` | penalty, free-kick, corner duty — especially changing hands |
| `form` | judgment of how he is playing, by eye or by number |
| `fixtures` | schedule — swings, doubles, blanks, European congestion |
| `price` | imminent rise or fall |
| `captaincy` | armband picks |
| `chip` | Wildcard, Free Hit, Bench Boost, Triple Captain |
| `transfer` | buy / sell / hold advice on a player |

`set_piece` stays separate from `role` despite low volume: penalty duty changing hands is
worth real expected points, the model has `set_pieces.py`, and it must stay visible.

### `kind` — what type of information it is (5 values)

| kind | meaning | why it matters |
|---|---|---|
| `news` | an external fact reported — injury, rumour, press conference, lineup | the model structurally cannot see this. Highest value. |
| `read` | the creator's own eye-test judgment | also unseeable. High value, low reliability. |
| `stat` | a cited number | the model probably already has it; value is as a cross-check |
| `recommendation` | what you should do | value is only in aggregation across creators |
| `action` | what the creator did with their own team | revealed preference, not advice |

This is the field that lets the room rank a rumoured signing above a restated xG figure.
About 13% of the current corpus cites a stat we already compute.

### `horizon` — when it bites

`this_gw` · `next_few` (2–6 GW) · `season`

Stops a Triple Captain window in GW16 from cluttering the GW4 view.

### `teams` — new

Verbatim team names for team- and league-level claims ("Hull have conceded 3.12 xG in two
games"). Currently these land in `misc` and die there. With a `teams` field they attach to
the fixture wall.

## Migration of the existing 474 findings

Re-reading a transcript is the expensive step and a video is extracted once, ever. So the
transcripts are not re-read.

1. Deterministic map where the old category is unambiguous: `minutes_risk`→`minutes`,
   `set_piece`→`set_piece`, `price`→`price`, `captaincy`→`captaincy`, `chip`→`chip`,
   `fixtures`→`fixtures`.
2. `owned_player`, `target`, `misc` (260 rows) and every row's `kind` / `horizon` need a
   classification pass over the **claim and quote text only** — never the transcript.
3. Migrated rows are written alongside the originals, which stay immutable, matching the
   revisioning discipline in `observations/`.

## Section layout

Ordered by the decision each one serves. Every section puts the creator view next to the
model view — that juxtaposition is the point, not the quotes.

**0 · Header strip.** Findings / creators / videos, date range, target gameweek,
contradicted-claim count, unresolved-name count.

**1 · Act on this.** The 5–10 findings that are about the squad or a live target, are
`kind` news or read (the model cannot see them), are `horizon: this_gw`, and are strongly
asserted. The panel to read if you read nothing else.

**2 · Your squad.** One row per owned player: consensus (+/=/−, creator count), model xP
this GW and over six, expected minutes, and the sharpest claim. **Sorted by
creator–model disagreement**, so the top rows are where creators are negative and the
model is not, or the reverse. That disagreement is the drop-candidate list.

**3 · Targets.** Non-owned, positive stance, ranked by consensus strength against model
six-week xP. Price, affordability given bank and sellable value, expected minutes.
Grouped by position so it reads against squad shape.

**4 · Avoid and fade.** Non-owned players with negative consensus, plus owned players the
creators want sold. Stops a transfer into a trap the creators already flagged.

**5 · Captaincy.** Creator picks for the target gameweek in one column, model top-five xP
in the other, agreement highlighted.

**6 · Chips.** One block per chip: Joe's availability from `state.py`, what creators plan
and when, and named future windows. `horizon: season` rows live here.

**7 · Team and league context.** Team-scoped claims, linked to the fixture wall.

**8 · What they actually did.** `kind: action` rows — revealed preference, kept separate
from advice.

**9 · Quality.** Collapsed. Contradicted claims, unresolved names, dropped findings.

Sections 1–5 are the pre-transfer read. 6–9 are reference.


## Built — measured outcome, 2026-09-08

`scripts/migrate_findings.py` converted all 474 findings without re-reading a transcript.
It classifies with visible scored rules rather than a model call, so the result is
reproducible. Position-weighted scoring replaced first-match ordering after first-match
filed every "on a wildcard, lock in Calafiori" under `chip`.

Measured on the full corpus:

| field | rule-determined | fell back to a default |
|---|---|---|
| `topic` | 94% (29 rows unplaced, left null) | — |
| `kind` | 70% | 30% defaulted to `read` |
| `horizon` | 29% | 71% inherited from the topic |

**The migrated `horizon` is weak and should not be leaned on.** At 71% it is mostly a
restatement of the topic. It is honest for newly extracted findings, where the extractor
reads the transcript and knows; it is close to uninformative on migrated rows. Every
defaulted field is listed in the row's `inferred` array and surfaced in the UI as a `?`
on the kind tag and a count in section 09.

This has a real consequence for section 1: only 2 of the 10 "Act on this" rows carry a
`kind` a rule actually determined. Rows with an inferred kind are ranked last and the
section header states the count, rather than presenting all ten as equally established.

### Consensus is weighted by creator support

A raw net stance saturates at 1.0 whether one creator mentioned a player once or two
creators agreed across five claims. Consensus is therefore scaled by the share of the
corpus's creators who actually discussed the player, and the stance bar draws the scaled
value so the picture matches the ranking. Before this change the target list was topped by
single passing mentions; after it, every leading target has two-creator agreement.

### Known thin spots

- `teams` is nearly empty on migrated rows, because the old schema had no such field and
  it can only be recovered where a club is named in the claim text. Section 07 will fill
  in as new transcripts are extracted under the new spec.
- The model signal is a within-position percentile, so an owned squad of strong players
  sits near the ceiling. Disagreement is therefore almost always "creators are colder than
  the model", not the reverse. That is a property of the squad, not a bug, but it means the
  Δ column is not symmetric in practice.
