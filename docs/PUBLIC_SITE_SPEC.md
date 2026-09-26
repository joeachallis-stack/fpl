# Public FPL site: product and experience spec

Status: agreed direction, 2026-09-25. Build against this document. The current private Decision Room remains a separate tool.

## Product promise

Help an FPL manager manage the next gameweek and plan future gameweeks. The first-visit season story is a personalized introduction to that ongoing product. Use the manager's public FPL entry ID to make the experience specific to their team. The public ID identifies a team; it does not prove the visitor owns it.

Success means a first-time visitor reaches a useful current-gameweek view after entering an ID, and a returning visitor can quickly compare hold, transfer, captain and future plans. Season in Review remains available at any time.

## One connected world

The organizing device is a living season timeline with the current gameweek at the center. Season in Review travels backward; Plan Ahead travels forward. Keep the same team identity, squad, player cards, fixture strips, typography, color system and navigation across the site. The first-visit reveal, the weekly view and the planning view should feel like different positions on one timeline.

Visual language: match programmes, player stickers, floodlit pitches and scoreboards. Motion follows meaning: moving between gameweeks shifts the timeline; selecting a player expands the same card; testing a transfer replaces a player on the same pitch and updates nearby numbers. Animation is user-controlled where it advances content, skippable during onboarding, and respects reduced-motion preferences. Use Rare UI, ObsidianUI, Transitions.dev and Design Spells as references for interaction craft, with one coherent design system rather than independent page treatments.

## Information architecture

1. **My Gameweek** is the returning-user home. Show the last publicly confirmed squad, next deadline, flags, captain and vice, hold and at most a few credible options, their points/hit tradeoffs, and why the comparison leads. Label data freshness and uncertainty. Do not imply that unsaved or post-deadline team edits are visible.
2. **Plan Ahead** is the interactive workspace. Let users shop players and possible teams for this and future gameweeks, move along a gameweek rail, try transfers and chips, inspect fixtures, budget and free-transfer effects, compare a draft with hold and other drafts, and save or revisit scenarios. A scenario is a hypothesis, never a confirmed FPL submission.
3. **Season in Review** is a permanent route. Replay the first-visit story and explore historical gameweeks, transfers, captains, chips, bench points and decision outcomes. Add new chapters as gameweeks settle.

No dedicated Expert Room in the public navigation. Relevant creator evidence may later appear in a player or decision explanation with source attribution.

## First visit

1. Show a centered team ID field on the season canvas with a clear CTA. A nearby help element shows where to find an ID in the official FPL team URL. Accept either the number or a pasted team URL. Confirm the returned team name before presenting its analysis. No account is required to try it.
2. Fetch and process the public entry, history, transfers, picks and relevant player/gameweek data. Animate honest progress labels such as "Reading your gameweeks", "Replaying your transfers" and "Comparing choices with pre-deadline forecasts" only while those tasks actually run. Never delay a ready result to complete an animation. Use "analysing xG" only where xG is truly part of the work underway.
3. Reveal a short, clickable season story selected from that team's real history. Favor contrast and specificity: a successful move, a painful result, a high point, and where decision quality differed from outcome. Include an evidence/details affordance, back and skip controls, and a progress marker. Do not fabricate a chapter to fill a fixed count.
4. The final story card moves the timeline to the current gameweek and opens My Gameweek. Primary action: "Manage my gameweek". Secondary action: "Explore plans". On return visits, open My Gameweek directly; Season in Review keeps the story accessible.

## Decision quality and luck

For each eligible historical decision distinguish (a) the information available before its deadline, (b) how the chosen option compared with a reasonable alternative then, and (c) the realized points afterward. "Expected +2.1, got -6" is a useful shape; the numbers must come from actual frozen forecasts and settled outcomes. Avoid a universal manager skill score from a short sample. Mark hindsight-only analysis clearly.

The existing model has frozen all-player pre-deadline projections from GW4 of 2026/27 onward. Earlier current-season weeks lack that basis. Public entry data includes gameweek history, transfers and picks; past seasons provide only aggregate totals and ranks. Free Hit transfers need special handling. Public picks prove the squad saved at the last deadline, not changes since. Historical stories must expose these limits where relevant.

## Build sequence

1. Separate public-site prototype: real entry ID lookup, honest loading, shared timeline shell, short evidence-backed season story and navigable pages. It must not alter the private Decision Room or make changes to an FPL account.
2. Complete historical scoring and eligible pre-deadline comparisons, including transfer, captain and chip caveats.
3. Bring the current projection/decision engine to arbitrary public teams, then make My Gameweek and Plan Ahead fully actionable with scenario comparison and saved plans.
4. Test the first visit and weekly return path with users before public launch. Any publicly reachable deployment, outreach or account system needs a separate reviewed release decision.

## Sources

- `docs/IDEAS.md`, "Season review for any team ID" (2026-09-15).
- `docs/FRONTEND_SPEC.md`, private Decision Room principles and state labels.
- Woof woof + Instinct shared workspace and Archive in Google Drive: FPL hindsight workstream, site as primary distribution channel, and animation references.
