# FPL transcript extraction spec

You will be told the current gameweek and its deadline in your task prompt.

## Step 1 — read the roster FIRST

`news/roster.txt` lists every player in the 2026/27 Fantasy Premier League, one per
line, as `Web Name (Team, POS)`.

**This is the only valid source of player identity.** Read it before the transcripts.

### The hard rule on names

Every entry in a finding's `players` array MUST be a **complete line copied verbatim from
the roster file** — `Palmer (Chelsea, MID)`, not `Palmer`, and not `Cole Palmer`.

The full line is required because display names are not unique. There are two players
called Palmer: Cole (Chelsea, MID) and Alex (Ipswich Town, GKP). A bare surname is
unresolvable.

Do **not** use a player name from your own knowledge of football. Players transfer between
clubs and leagues, and your training data is not current for this season. On an earlier
run an extractor produced "Kyle Walker of Arsenal" and "Estupiñán of Brighton", neither of
whom exist in this game, and copied "Mac Allister of Brighton" from a caption when the
roster says Liverpool. **A fabricated player is worse than a missed mention**, because it
enters a decision as fact.

Do not output team, position or price as separate fields. They are attached later from the
roster. Your job is to name a player and state a claim.

### When you cannot resolve a name

Put the verbatim caption text in `unresolved` and leave that player out of `players`.
A flagged unknown is a good outcome. A guess is not.

But do not be over-cautious either: on an earlier run "Djed Spence" was discarded as
unknown because the caption said "of Brighton" while the roster says Spurs. The roster
wins on club — if the name matches a roster line, use it, and ignore what the caption
claims about their team.

Captions are auto-generated and mangle names phonetically. Known examples:
`Gabrielle` = Gabriel, `Savio` = Sávio, `Bryan and Ben Mee` = Bryan Mbeumo,
`Sessi Muno's` = a garbled run of names. Use surrounding context to identify who is meant,
then find them in the roster.

## Step 2 — the user's squad

Context only, so you recognise who is being discussed. Do **not** label a finding by
whether Joe owns the player — ownership is read from his actual squad downstream.
All are on the roster:

Kinsky, Dúbravka, Virgil, Calafiori, Shaw, Guéhi, Palestra, Szoboszlai, B.Fernandes,
Rogers, Gibbs-White, Tzolis, João Pedro, Isak, Kusi-Asare

## Step 3 — classify each finding on three axes

Do not use one "category" field. A claim has a subject, an information type and a
timeframe, and collapsing them loses the part that matters.

### `topic` — what the claim is ABOUT (pick exactly one)

| topic | covers |
|---|---|
| `minutes` | starting, benching, rotation, hooked early, squad competition, lineup choice |
| `injury` | knock, fitness, return timeline, suspension |
| `role` | where and how he plays — moved central, false 9, dropped deeper |
| `set_piece` | penalty, free-kick or corner duty, especially changing hands |
| `form` | judgment of how he is playing, by eye or by number |
| `fixtures` | schedule — swings, doubles, blanks, European congestion |
| `price` | an imminent rise or fall |
| `captaincy` | captain or vice-captain picks |
| `chip` | Wildcard, Free Hit, Bench Boost, Triple Captain strategy and timing |
| `transfer` | buy, sell or hold advice on a player |

Pick the topic the sentence is **primarily** about. "On a wildcard, lock in Calafiori and
Konsa" is `transfer` — it mentions a chip, it is not about chip strategy.

There is no `owned_player` or `target` topic. Whether Joe owns a player is read from his
actual squad; it is not yours to label, and labelling it left half the corpus with no
topic at all.

### `kind` — what TYPE of information it is (pick exactly one)

| kind | meaning |
|---|---|
| `news` | an external fact reported — injury, rumour, press conference, confirmed lineup, transfer |
| `read` | the creator's own eye-test judgment: "he looked lost", "the team was better balanced without him" |
| `stat` | a cited number — xG, shots, defensive contributions, ownership, points |
| `recommendation` | what the viewer should do |
| `action` | what the creator did or will do with **their own** team |

This axis decides what gets read first. `news` and `read` describe things the model
cannot see and are the most valuable findings in the corpus. `stat` is usually a number
the model already computes, and is kept only as a cross-check. Do not label a claim
`stat` because a number appears in it — label it `stat` when the number **is** the claim.

`action` is strictly the creator's own team. "I've triple-captained Haaland" is `action`;
"you could captain Haaland" is `recommendation`.

### `horizon` — WHEN it bites (pick exactly one)

| horizon | |
|---|---|
| `this_gw` | applies to the upcoming deadline |
| `next_few` | the next two to six gameweeks |
| `season` | long-range — a chip window in GW16, a season-long hold |

You are told the current gameweek. Use it. A named future gameweek beats any phrasing:
"Haaland vs Ipswich GW7" is `season` when the deadline is GW4.

**"This gameweek" inside a claim is not necessarily the upcoming one.** A video recorded
after a round settles says "this gameweek" about the round just played. Past tense gives
it away: "in this Gameweek, Foden is benched and Cherki starts, and we saw Cherki subbed
early" is a report on the gameweek that finished, not team news for the deadline ahead.
Filed as `kind: news` with `horizon: this_gw`, a settled result is presented as current
team news — the single most misleading thing this extraction can produce. Check the
publish date against the deadline you were given, and read the tense.

## Step 4 — teams

Add a `teams` array for claims about a club rather than a player: "Hull have conceded
3.12 xG in two games" is about Hull. Use the club name as the roster writes it. A finding
may have players, teams, both, or neither.

Team-level claims used to land in `misc` and were lost. With a `teams` array they attach
to the fixture wall.

## Step 5 — output

**Write your findings to the file you are given, one JSON object per line (JSONL).**
Do not return them in your reply — a batch produces 50-100 findings and returning them
as text loses them. Your reply is only the short note asked for at the end.

One object per line, in this shape:

```json
{
  "video_id": "...",
  "source": "...",
  "published": "...",
  "players": ["B.Fernandes (Man Utd, MID)"],
  "teams": [],
  "unresolved": [],
  "topic": "minutes",
  "kind": "news",
  "horizon": "this_gw",
  "stance": "positive",
  "conviction": "strong",
  "claim": "one sentence stating what was said",
  "quote": "verbatim snippet under 30 words"
}
```

`stance` is one of positive / negative / neutral.
`conviction` is one of strong / moderate / passing — how firmly it was asserted.
`quote` must be genuinely verbatim so a claim can be audited. Do not clean it up.

**Name the speaker in every claim.** Your task prompt gives a `speaker:` name for each
transcript. Use it — "Raptor is 99% likely to wildcard", never "the creator is 99% likely
to wildcard". Consolidation exists to show which creators agree and which dissent, and a
claim with an anonymous speaker cannot enter that comparison at all.

Plural is different: "Creators see higher upside in City assets" is the speaker reporting
what the community thinks, not referring to himself. Leave that as it is.

Be comprehensive on `minutes`, `injury` and `captaincy`, and on anything you label `news`
or `read` — those are the findings the model cannot produce for itself. Long videos are
conversational and repetitive: extract the substance once, not every time a point is
restated. A livestream is roughly 60-70% filler — ads, chat, and the same bench question
answered twenty times. But read to the end regardless: confirmed team news arrives in the
final lines, after the deadline, where it looks like ad content.

## A specific trap: a mangling can land on another real player's name

The captions rendered **Tzolis** (Arsenal, MID) as **"Solanke"** — and Solanke (Spurs,
FWD) is a real player on the roster. Two extraction runs read the same sentence and
confidently attributed it to different people. Checking the name against the roster
cannot catch this, because the wrong answer is a valid roster line.

What settles it is the record: Tzolis played 45 minutes and was booked in GW2; Solanke
played 15 minutes off the bench and was not. So when a claim states something checkable
about a player — subbed at half time, booked, scored, assisted, played 90 — make sure the
player you attribute it to is the one the surrounding context actually supports, using
the team of the other players named nearby. Eze and Konsa are Arsenal, so a player
substituted for Eze is an Arsenal player.

Known manglings seen in this corpus: Tzolis appears as "Solanke", "Solis" and "solace";
Cherki as "Churkey", "Cherokee" and "Traore"; Calafiori as "Califury" and "Counter fury";
Guéhi as "Gay"; Schade as "Kevin Sharda"; Gvardiol as "Vardyol".
