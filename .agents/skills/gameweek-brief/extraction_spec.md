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

For the `owned_player` category. All are on the roster:

Kinsky, Dúbravka, Virgil, Calafiori, Shaw, Guéhi, Palestra, Szoboszlai, B.Fernandes,
Rogers, Gibbs-White, Tzolis, João Pedro, Isak, Kusi-Asare

## Step 3 — categories

- `owned_player` — about a player in the squad above
- `target` — a player suggested as a transfer target or flagged as good value
- `chip` — Wildcard, Free Hit, Bench Boost, Triple Captain strategy and timing
- `fixtures` — double/blank gameweeks, fixture swings, rescheduled matches
- `captaincy` — captain or vice-captain recommendations
- `minutes_risk` — rotation, benching, hooked early, squad competition, return from injury
- `set_piece` — penalty, free-kick or corner duty, especially changing hands
- `price` — a player about to rise or fall in price
- `creator_action` — what the creator did with their OWN team, as distinct from what they
  advise. "I've triple-captained Haaland" is an action; "you could captain Haaland" is not.
- `misc` — injury news, press conference, kickoff timing, anything else decision-relevant

## Step 4 — output

**Write your findings to the file you are given, one JSON object per line (JSONL).**
Do not return them in your reply — a batch produces 50-100 findings and returning them
as text loses them. Your reply is only the short note asked for at the end.

One object per line, in this shape:

```json
{
  "video_id": "...",
  "source": "...",
  "published": "...",
  "category": "owned_player",
  "players": ["B.Fernandes (Man Utd, MID)"],
  "unresolved": [],
  "stance": "positive",
  "claim": "one sentence stating what was said",
  "quote": "verbatim snippet under 30 words",
  "conviction": "strong"
}
```

`stance` is one of positive / negative / neutral.
`conviction` is one of strong / moderate / passing — how firmly it was asserted.
`quote` must be genuinely verbatim so a claim can be audited. Do not clean it up.

Be comprehensive on `owned_player`, `minutes_risk` and `captaincy`. Do not pad `misc`.
Long videos are conversational and repetitive — extract the substance once, not every
time a point is restated. A livestream is roughly 60-70% filler: ads, chat, and the same
bench question answered twenty times. But read to the end regardless — confirmed team
news arrives in the final lines, after the deadline, where it looks like ad content.

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
