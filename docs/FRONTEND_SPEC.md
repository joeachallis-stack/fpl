# FPL decision room — frontend specification

Status: approved build contract and active implementation, 2026-09-06. Joe's direction is fixed as desktop-only,
squad plus options on the opening screen, and playful/recognizably fantasy-football rather
than restrained analyst software. Implementation is isolated on `codex/frontend-v1` so
the repaired GW4 model and scheduler path on `main` remain unchanged.

## Product definition

This is a private desktop decision room for one FPL manager. Its primary job is to help
Joe make one considered gameweek decision from the current squad, model, official state,
fixture landscape and creator evidence without pretending that the leading numerical
plan is known to be optimal.

It is not a general-purpose FPL site, a live team editor, a social product or a prettier
wrapper around every JSON field. The first release should make the weekly routine more
enjoyable, faster and harder to misread.

Success means Joe can answer these questions in under two minutes:

1. Is the data current and is anything incomplete?
2. How does the squad line up this week?
3. Which two or three plans are worth comparing with holding?
4. Is an apparent edge driven by bookmaker-backed fixtures or the weaker fallback tail?
5. What do the useful YouTube creators agree and disagree about?
6. What assumptions or news could reverse the order?
7. Who should start, captain and sit first on the bench?
8. Has the forecast and final decision been recorded?

## Information architecture

The product has four rooms, reached from persistent desktop navigation:

1. **My gameweek** — squad, transfer options, captaincy and final checks.
2. **Expert room** — creator consensus, dissent and verified claims.
3. **Fixture wall** — Excel-like past-and-future fixture grid for all clubs.
4. **Model form** — minutes and xP calibration, errors and version history.

“My gameweek” is always the default. The other rooms support the decision; they do not
compete with it for attention on one endlessly scrolling dashboard.

On the pitch, each player sticker shows the target-gameweek xP beside the fixture. Expected
minutes remains available in the player drawer with its probability bands: xP is the
decision-facing summary, while xM is a diagnostic input.

## Product principles

- **Readiness before ranking.** Freshness, missing fixtures, unresolved forecasts and
  uncalibrated uncertainty appear before any transfer ranking.
- **Squad plus options.** The opening view always shows the current XI beside hold and a
  maximum of three credible alternatives.
- **Comparison, not command.** Say “leads this comparison,” never “optimal” or “you should.”
- **Show the hinge.** Every plan names the few players, assumptions and gameweeks that
  create its advantage.
- **Expert evidence is player-shaped.** Group creator claims around the player or decision,
  not as a feed of videos to watch.
- **Separate model record from human action.** The frozen forecast and Joe's later journal
  decision can disagree without either being overwritten.
- **No hidden model blending.** Shadow forecasts can appear only in Model form. They never
  appear in the live decision room.
- **Playful, not toy-like.** Borrow from sticker albums, fixture posters, shirts, match
  tickets and fantasy draft boards. Avoid casino energy, confetti and gamified certainty.
- **Earn visual emphasis.** Red means an action-blocking problem. Amber means a known
  limitation. Green means a completed check, never a recommendation.

## System state model

The interface must never collapse several different meanings of “my team” into one. Every
squad display carries one of five explicit states:

1. **Last official squad** — public picks saved at the previous deadline. This is the only
   squad the unauthenticated FPL API can currently prove.
2. **Selected scenario** — an ephemeral what-if assembled from an optimizer option or
   Joe's own proposed transfers. It changes no file and disappears unless recorded.
3. **Frozen forecast** — the first successful pre-deadline model and decision archive.
   It is immutable even if later news changes the real choice.
4. **Recorded decision** — the recommendation and runner-up appended to the journal.
5. **Submitted team** — what Joe actually saved in FPL. Treat this as unknown until it is
   manually confirmed or becomes visible through the following deadline's public picks.

The pitch header names the current state in plain language. “Your squad” alone is not
enough. A transfer option changes the view to “Selected scenario”; returning to hold
restores “Last official squad.” The frozen and recorded states have their own timestamp
and never masquerade as the live scenario.

## Safe action boundary

Read-only means **no changes to the FPL account**, not a passive application. V1 may:

- Refresh official data, odds and creator feeds, with the last successful source refresh
  and any bookmaker-credit use shown before running.
- Rebuild minutes, projections and decision comparisons without archiving them.
- Create and compare ephemeral what-if transfer scenarios.
- Append a recommendation, runner-up and rationale to the local decision journal after a
  review step.
- Open the official FPL site in a separate tab.

V1 may not:

- Submit transfers, lineups, captaincy or chips to FPL.
- Overwrite or delete a minutes, projection or decision archive.
- Change model parameters, scoring configuration or fitted artifacts.
- Promote a shadow model into a live decision.
- Infer that an opened FPL page means the displayed scenario was submitted.

The scheduler remains the owner of normal archiving. The interface reports its status and
the safest recovery instruction after a failure; it does not add a casual “Freeze now”
button beside ordinary controls.

## Cross-room context

One `selected_scenario_id` follows the user through all four rooms:

- My gameweek renders that scenario on the pitch and compares it with hold.
- Expert room leads with the players and captaincy affected by it.
- Fixture wall marks the clubs gained and lost by it, while owned clubs remain distinct.
- Model form can explain the model version and forecast sources behind it, but never swaps
  in a shadow result.
- The player drawer opens the same player and comparison context from every room.

Navigation, refresh and reopening the application preserve the selection only in local
presentation state. Recording a decision is the explicit act that makes a scenario part
of the journal.

## Visual direction: fantasy sticker-board

The interface should feel like laying out a fantasy squad on a matchday sticker board.
Players are tactile pieces, transfer alternatives resemble swap cards, and fixtures read
like a wall chart. The analytical layer remains exact and aligned underneath that playful
surface.

This should be recognizably fantasy football without cloning FPL's purple-and-green
identity. Avoid a generic grid of SaaS cards, decorative gradients, glass effects, giant
KPI numbers and dashboard filler.

### Type

- **Changa One 400** for the gameweek title and the four room names. It supplies the one
  playful, fantasy-sports voice.
- **Barlow 400/500/600** for interface text, player names and data.
- **Barlow Condensed 500/600** for fixtures and compact numeric comparisons.
- Use tabular numerals wherever xP, prices, minutes or deadlines align.

Sentence case only. Never use tracked all-caps labels. Changa One is seasoning: it must
not be used for explanatory text or tables.

### Color tokens

| Token | Value | Use |
|---|---:|---|
| Floodlight | `#F7FAF4` | Main canvas |
| Night league | `#32165F` | Navigation and strongest text |
| Turf | `#35A86B` | Pitch, completed checks and future-fixture accents |
| Fixture lilac | `#E9E0FF` | Selected cells and secondary surfaces |
| Ticket yellow | `#FFD45C` | Deadline, captain and one focal highlight |
| Match coral | `#EF6657` | Transfers out and important dissent |
| Ink | `#282331` | Body text and table rules |

Large surfaces use Floodlight or very pale tints. Night league, Turf and Match coral must
pass contrast checks wherever they carry text. Team colors appear as small identity marks,
not as objective weights; Chelsea blue does not become the application theme.

### Shape and texture

- The pitch is a flat illustrated surface with crisp markings, never photorealistic grass.
- Player pieces use a clipped sticker silhouette or shirt tab, not identical rounded cards.
- Transfer options use opposing coral/turf edges to make out/in direction readable.
- Section dividers may borrow the perforation of a match ticket.
- One subtle diagonal stripe may appear in the active room header. Do not repeat it across
  every panel.
- No drop shadow unless a player piece is actively being compared or dragged visually.

## Desktop shell

Target a 1280–1600px desktop window. The application is intentionally not designed for
phone use in v1. Text is left-aligned; numerical columns are right-aligned.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ FPL Decision Room      My gameweek  Expert room  Fixture wall  Model form   │
├──────────────────────────────────────────────────────────────────────────────┤
│ GW4 · Sat 12 Sep, 12:30 UTC  │ 4 free transfers │ £1.5m │ Not archived      │
│ GW3 incomplete 8/10          │ Market fixtures: GW4–5 │ No measured margin  │
├───────────────────────────────────────────┬──────────────────────────────────┤
│                                           │ Options                          │
│             CURRENT XI                    │                                  │
│                                           │ Hold                  baseline   │
│        João Pedro       Isak              │ Tzolis ⇄ Tavernier    +3.8 / +8.5│
│                                           │ Two transfers         horizon flip│
│ Rogers  Tzolis  Bruno©  Szoboszlai        │                                  │
│                                           │ Why it moves                     │
│   Calafiori  Virgil  Guéhi  Palestra      │ Tavernier leads in GW4–5.        │
│                                           │ Thiago depends more on GW6–9.    │
│                Kinsky                     │                                  │
│                                           │ Expert pulse                     │
│ Bench  Dubravka · Shaw · Gibbs-White ...  │ No GW4 videos extracted yet.     │
├───────────────────────────────────────────┴──────────────────────────────────┤
│ Checklist clean  │ Freeze pending │ Decision not journaled                  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Room 1: My gameweek

### Readiness ribbon

One horizontal ribbon answers whether the page is safe to use:

- Gameweek and deadline.
- Cache age and most recent official refresh.
- Completed fixtures in the previous gameweek.
- Odds-backed gameweeks versus fallback gameweeks.
- Creator corpus coverage.
- Minutes, projection and decision archive state.
- Evaluation state: “No measured decision margin” until evidence exists.

Incomplete state uses a sentence, not only a colored dot: “GW3 is 8/10 complete; Arsenal,
Chelsea, Everton and Manchester United have one fewer match of evidence.”

### Squad pitch

- Show the selected plan's starting XI in formation.
- Captain uses Ticket yellow and a `C`; vice gets a quiet `V`.
- Bench order is explicit below the pitch, goalkeeper separated.
- V1 uses simple club-colored shirt shapes with player initials or names. It does not rely
  on player portraits, club crests or other licensed imagery.
- Each player piece contains name, opponent and expected minutes. GW xP appears on focus or
  selection so the pitch does not become a spreadsheet.
- Availability, duty or creator disagreement attaches to the player piece.
- Selecting a transfer option changes the pitch in place. Outgoing stickers recede and
  incoming stickers slide along one short swap path. Respect reduced motion.

### Options board

Show hold plus at most three alternatives. Default columns:

| Field | Meaning |
|---|---|
| Move | Transfers in and out, grouped by position |
| 2-GW edge | Difference from hold using bookmaker-backed GW4–5 |
| 6-GW edge | Discounted difference including the fallback tail |
| After hits | Net of transfer costs |
| Cash | Remaining budget; never colored as a reward |
| Next bank | Expected free-transfer stock next week |
| Stability | Stable, partial flip or material flip across horizons |

The table never sorts on availability-adjusted xP or shadow xP. Availability-adjusted xP
is an expandable sensitivity beside the primary result.

### Why the order changes

For the selected plan, show only the largest differences from hold:

- Gameweeks contributing the edge.
- Appearance/minutes difference.
- Goal and assist expectation.
- Clean-sheet, goals-conceded, saves, DefCon and bonus where relevant.
- Bookmaker or fallback fixture source.
- Role/duty flag and creator disagreement.

Use a signed horizontal contribution plot rather than a pie chart. Components can be
negative and the question is comparison, not composition of a whole.

### Final strip

Show the checklist, archive state and journal state. There are no “Make transfers” or
“Save team” controls in v1. A later link to FPL may be considered only after the forecast
record and Joe's actual decision are visibly distinct.

### Transfer, price and chip constraints

Every option exposes the rules that can turn an attractive score into an invalid or poor
decision:

- Free transfers used, hits charged and free transfers expected next week.
- Purchase, current and selling prices for outgoing players.
- Remaining cash as feasibility, never as a points reward.
- Club and position legality.
- Price-change warning only when the projected movement can block that exact scenario.
- Chip availability, half-season expiry and whether the candidate is merely the best chip
  squad rather than evidence that the chip should be played.
- A chip option never displaces hold or ordinary transfers in the primary list unless a
  separate preservation-value policy eventually justifies that comparison.

### Safe local controls

The desktop header may contain `Refresh data` and `Rebuild comparisons`. The final strip
may contain `Record decision` once a scenario and runner-up have been selected. Each control
states exactly which local artifacts it will update. Long-running work shows progress and
the last successful state remains visible if a refresh fails.

## Room 2: Expert room

This is a first-class product area, not a news sidebar. Its job is to reveal consensus,
dissent and information the model cannot observe.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Expert room             8 videos · 6 creators · refreshed Thu 18:40         │
├──────────────────────────────┬───────────────────────────────────────────────┤
│ What could change the call   │ Creator × player board                        │
│                              │               Harry  Raptor  General  Blackbox│
│ Tzolis                       │ Tzolis          Sell    Hold     Sell     Sell │
│ 3 sell · 1 hold              │ Tavernier        Buy     Buy      —       Buy │
│ Rotation concern disputed    │ Palmer         Captain  Buy    Captain    Buy │
│                              │ Isak             Hold    Sell     Hold      —  │
│ Tavernier                    │                                               │
│ 3 buy · minutes consensus    │ Select one cell to read the verified claim.   │
├──────────────────────────────┴───────────────────────────────────────────────┤
│ Model disagreement: creator minutes view for Tzolis is lower than model.     │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Expert pulse

Consensus-by-player is the primary Expert room view. The creator matrix is the detailed
second view below it. The top section lists only players and decisions relevant to Joe's
squad, captain pool or top three plans. Each row shows:

- Consensus counts by claim, not a sentiment score.
- Meaningful dissent.
- Creator actions separately from advice.
- Minutes, injury, role, set-piece, captaincy and transfer categories.
- Whether a falsifiable claim agrees with the official record.
- A direct route to the source video/transcript and publication time.
- Corpus coverage: videos detected, fully extracted, partial and failed.
- Whether later official team news makes the claim stale.

### Creator × player board

Use a dense matrix when several creators discuss the same shortlist. Rows are players;
columns are creators. A cell contains one readable stance such as `Buy`, `Hold`, `Sell`,
`Captain` or `Minutes`. Selecting it shows the actual extracted finding, confidence,
timestamp and verification result in one summary area.

Do not average creators into a synthetic expert score. Four repeated opinions are useful
consensus, not an independent probability estimate.

Near-duplicate claims from the same creator/video count once in consensus. Repeated claims
across different videos remain visible as repetition but do not become extra statistical
independence. Selecting a finding shows its source, publication time, extraction confidence,
claim category, transcript context and official verification result.

### Empty and stale states

- Empty: “No GW4 material yet. The latest 65 transcripts concern earlier gameweeks.”
- Partial: state how many known videos remain unextracted.
- Stale: keep findings visible, but label anything published before material team news.
- Contradiction: show the creator claim beside the official correction.

## Room 3: Fixture wall

The fixture wall is the requested Excel-like overview. Clubs are rows and gameweeks are
columns, with the current boundary fixed visually between past and future. The grid is
dense, sortable and inspectable without becoming a rainbow FDR table.

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Fixture wall       View: Fixtures ▾       GW1  GW2  GW3 │ GW4  GW5  GW6 ... │
├──────────────────────────────────────────────────────────────────────────────┤
│ Arsenal                                  MCI  lee  CHE │ sun   bha   EVE     │
│ Aston Villa                              ...  ...  ... │ NFO   ...   ...     │
│ Chelsea                                  ...  ...  ars │ HUL   ...   ...     │
│ Liverpool                                ...  ...  ips │ FUL   ...   ...     │
│ Manchester United                        ...  ...  eve │ mci   ...   ...     │
│ ...                                                                          │
├──────────────────────────────────────────────────────────────────────────────┤
│ Chelsea · GW4 · Hull City at home · 2.21 expected goals · bookmaker source  │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Grid behavior

- Exactly one readable identifier appears in each cell: uppercase opponent for home,
  lowercase opponent for away. Accessible text supplies the full fixture and metric.
- A heavy “now” divider separates settled results from forecasts.
- Past cells can switch from opponent to result; future cells remain fixtures.
- Owned-player clubs receive one quiet shirt marker beside the club name.
- Selecting a cell updates one summary line below the grid; it does not open another card.
- Freeze the club column and gameweek headers during scrolling.
- Double gameweeks split the cell diagonally; blanks use a neutral dash.
- The product opens around the current gameweek, but all 38 columns remain reachable by
  horizontal scroll. Club names and gameweek headers remain frozen.
- Canonical league order is the default. Optional sorts may surface best attacking run,
  best defensive run or largest fixture swing, with a visible way back to league order.

### Grid views

The default is **Fixtures**, with neutral cells. One compact selector changes the future-
fixture fill while keeping the opponent identifier:

1. **Fixtures** — neutral home/away structure, minimal color.
2. **Attack** — expected team goals for future fixtures.
3. **Defence** — clean-sheet probability for future fixtures.
4. **Difficulty** — model-derived fixture difficulty, labeled by source and never presented
   as official FPL FDR.

Past cells show opponent/result structure and do not inherit forecast heat colors. Attack
and Defence use stable, season-level domains frozen in the frontend view model rather than
rescaling to whatever rows happen to be visible. The legend states the numeric endpoints
and bookmaker/fallback provenance. The now divider and selected-cell sentence make the
change from actual past to forecast future explicit.

Postponed fixtures retain their original cell with a postponement mark and appear again in
their rescheduled gameweek. A double-gameweek selection lists both fixtures and their
separate forecast sources; no cell silently adds two probabilities together.

## Room 4: Model form

“Calibration” is technically correct but too cold for primary navigation. The room name is
Model form; calibration remains the language inside the page.

### Empty state now

> No projection has completed its forecast window yet. GW4 will be the first baseline.

Show the next milestone and what will become measurable. Do not fill the empty state with
training-set scores that look like live evidence.

### Minutes calibration

- MAE and signed bias by resolved gameweek.
- Multiclass Brier score and log loss for zero, 1–59 and 60+ probability bands.
- Reliability plots only after enough independent gameweeks exist to bin honestly; before
  then, show the raw forecasts and outcomes without a fitted-looking curve.
- Confusion counts for the most likely band as a secondary, descriptive view.
- Starter versus substitute error.
- Largest misses with owned/shortlist relevance.
- Sample count in independent gameweeks, not only player rows.

### Points calibration

- Projection MAE and bias by lead time.
- RMSE beside MAE so large misses remain visible.
- Two- and six-week decision stability over time.
- Component error as aligned small multiples.
- Calibration-player and all-player views clearly distinguished.
- Model-version boundaries; never draw one trend through a version change.
- Forecast-minus-actual is the fixed signed-error convention everywhere.

No trend line or robustness-margin estimate is drawn before six independent resolved
gameweeks at the relevant lead. Six unlocks an early estimate, not a “calibrated” badge.
Every chart shows independent gameweeks alongside player-row counts and labels estimates
as early while the sample remains thin.

### Live versus shadow

The shadow comparison appears only here, after results:

- Paired live and challenger error on the same player-gameweeks.
- Gameweek-clustered uncertainty.
- Total-xP result first; xG/xA components as supporting evidence.
- A permanent note: “Not used for squad decisions.”

Journal outcomes remain separate from forecast outcomes. A good decision can produce a bad
score and vice versa.

### Model and decision scoreboards stay separate

Model form may reconstruct realized points for alternative archived squads, but it must
label that as a counterfactual comparison rather than proof that an unchosen action was a
better decision. The journal view evaluates whether the pre-deadline reasoning and recorded
runner-up were sensible given information available then. It never grades a decision only
by whether a player returned.

## Player detail drawer

Available from the squad, options, expert board and fixture wall. It answers “why does the
system think this?” in this order:

1. Expected minutes and its three probability bands.
2. Fixture-by-fixture xP and source.
3. Scoring-component contribution.
4. Current-season versus prior-season evidence and shrinkage.
5. Set-piece duty and known changes.
6. Creator evidence and contradictions.
7. Price and ownership as context only.

Do not expose raw implementation labels such as `hierarchical_trained` without a plain-
language translation. Advanced audit JSON may be downloadable, not dumped into the UI.

## Data contracts for v1

The frontend reads generated artifacts; it does not import or reimplement model logic:

- `data/bootstrap.json`, `fixtures.json`, `entry.json`, latest `picks_gwNN.json`.
- `data/minutes.json`, `projections.json`, `decisions.json`, `evaluation.json`.
- `news/findings/gwNN_*.jsonl` through a prepared summary rather than browser parsing.
- `journal/entries.jsonl` and archive-presence metadata.

A small read-only adapter normalizes these files into a frontend view model. It displays
each artifact's generation time and rejects mixed gameweeks rather than silently combining
them. Shadow fields are removed at the adapter boundary for every live-decision route.

Every successful rebuild creates one `analysis_run_id` with:

- Target gameweek and generation time.
- Source timestamps and completeness.
- Projection and minutes model versions.
- Two- and six-week decision outputs produced from the same underlying input snapshot.
- Archive and journal state.

The UI renders one coherent run. A partial refresh never combines new fixtures with an old
decision output under the same readiness state.

The two- and six-week comparison should be precomputed into separate artifacts or one
combined view model. Opening the page must not mutate `data/projections.json` by silently
rerunning a different horizon.

## Explicit non-goals for v1

- Phone or tablet layouts.
- Authentication or multi-manager support.
- Editing or submitting the FPL team. Local what-if scenarios and journal recording are
  explicitly in scope.
- Automatic transfers, captaincy or chips.
- Push notifications.
- A universal confidence or creator score.
- Ownership or effective ownership in the objective.
- Reimplementing projections in JavaScript.
- A live video player or general news feed.

## Failure and recovery states

Every room supports five states: loading, empty, partial, valid and failed. A failed rebuild
keeps the last valid analysis visible with its old timestamp. It never clears the pitch or
shows half-new rankings.

- Official-data failure: name the endpoint class and retain the prior coherent run.
- Optional odds/news failure: show which source is stale; official refresh may still pass.
- Mixed gameweek or model version: block comparisons and request a coherent rebuild.
- Scheduler failure: show the missing archive and the safe manual retry command.
- Journal failure: preserve the reviewed entry in the form and do not claim it was recorded.

Errors use plain verbs and recovery instructions. “Something went wrong” is never enough.

## Local delivery and privacy

V1 runs locally against this repository and binds only to the local machine. It has no
authentication because it has no remote users or hosted surface. The adapter must not expose
the filesystem generally; it serves only the explicit view model and safe workflow actions.
Moving to hosted or multi-device use is a separate security and product decision.

## Build slices and acceptance criteria

### Slice 0: coherent analysis adapter

- Produces one versioned `analysis_run_id` from the existing artifacts.
- Precomputes two- and six-week comparisons without overwriting one horizon with the other.
- Rejects mixed gameweeks and incomplete required inputs.
- Removes all `shadow_*` fields from live-decision routes.
- Exposes source timestamps, completeness and archive state.

### Slice 1: My gameweek

- Renders the last official squad, hold and at most three options from real data.
- Switching an option updates the pitch, captaincy, bench, hinge and constraints together.
- Clearly distinguishes last official squad, selected scenario, frozen forecast and journal.
- Supports ephemeral user-created what-if transfers without writing to FPL.
- Refresh, rebuild and journal actions have explicit success/failure states.

### Slice 2: Fixture wall

- Renders all 20 teams across all 38 gameweeks with frozen headers and club column.
- Handles home/away, past/future, blanks, doubles and postponements.
- Defaults to neutral fixtures and keeps forecast heat colors out of past cells.
- Selected scenario clubs remain highlighted consistently with My gameweek.

### Slice 3: Expert room

- Leads with consensus/dissent for the selected scenario and current squad.
- Shows coverage, freshness, provenance and verification.
- Preserves empty and partial states without inventing a consensus score.
- Creator matrix is available as the detailed second view.

### Slice 4: Model form

- Begins with an honest empty state when no resolved forecasts exist.
- Adds minutes metrics first, then projection metrics by lead as evidence resolves.
- Shows independent-gameweek counts and model-version boundaries everywhere.
- Keeps shadow and counterfactual results visibly outside live decisions.

### Release definition

V1 is ready when Joe can complete the weekly loop—refresh, compare, inspect evidence, check
constraints and record a decision—without a terminal, while the three immutable archive
steps remain protected and FPL team submission remains outside the product.

## Design self-critique

The first draft was too restrained for Joe's preference and too close to a professional
analytics workstation. This revision introduces fantasy-football character through player
stickers, swap cards, a fixture wall and a single playful display face. The analytical
views deliberately stay disciplined: making every table purple, every result a badge and
every section a collectible card would turn playfulness into noise.

The expert area could easily become a popularity contest. Grouping by player and preserving
dissent avoids treating repeated creator opinions as truth. The calibration area could
equally become false reassurance; it begins empty and always shows independent-gameweek
counts and model-version boundaries.

## Resolved design decisions

- Desktop only for v1.
- Opening view is squad plus options.
- Playful fantasy-football identity with disciplined analytical views.
- Simple shirt-shaped player pieces; no portraits or crests in v1.
- Expert room leads with consensus-by-player; creator matrix is secondary.
- Fixture wall defaults to neutral fixtures.
- Model form is visually quieter than the live gameweek and fixture rooms.
- Safe local workflow actions are allowed; FPL account writes are not.

## Remaining implementation decisions

1. Decide whether a confirmed “Submitted team” is entered manually or deferred until the
   following deadline proves it through public picks.
2. Decide whether the one-click macOS `.command` launcher is sufficient or worth packaging
   as a native `.app` after the weekly flow has been used in practice.

The independent horizon comparison was implemented on 2026-09-06. It takes an explicit
two-week view of the same canonical weekly projections and runs a separate exact optimizer,
without changing the archive-producing build functions. Its temporary optimizer writes are
isolated, canonical caches and archives are hashed before and after, and the frontend rejects
the comparison artifact as soon as its source projection or decision hash becomes stale.
