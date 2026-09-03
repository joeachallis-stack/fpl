# Ideas & Roadmap

Working backlog for the FPL assistant. Nothing here is committed to a schedule — it's the
shape of the thing being built, and the open questions that block each piece.

## The objective (revised 2026-09-02, from the decision-engine brief)

**Maximise total points by the end of the season.** Not overall rank, not mini-league
position.

This supersedes an earlier answer in the same session where Joe picked "overall rank" when
asked to choose. The written brief is the authority.

The two are closer than they look — maximising expected points is approximately
maximising expected overall rank, because rank is a monotone function of points across a
9M-entry field. The real consequence is **risk posture**: a points-maximiser is
risk-neutral and ignores the field.

Tractable proxy, from the brief: a 6-gameweek rolling horizon with a terminal value term
that prices unused chips, banked transfers and squad quality, so the optimiser doesn't
burn everything inside the window. Solve six, execute one, re-solve weekly. Never
pre-commit to the printed multi-week plan.

Downstream consequences:

- Effective ownership and template hedging **drop out of the objective**. Keep global
  ownership as displayed context so the variance is visible; never let it into the
  optimiser.
- Mini-league standings stay read-only colour.
- Team value is a tiebreaker, never an objective term.

## Data audit and build order

Full audit of every input against the brief (A = have it, B = available not wired,
C = doesn't exist cleanly), answers to the four open decisions, and the sequenced build
order: **https://claude.ai/code/artifact/0aa2b619-df39-4715-916e-6bac79174ed3**

Headline results — 15 A, 6 B, 5 C across 26 items. The four decisions, settled:

1. **Cut effective ownership from the objective**, keep it as a reporting field.
2. **Minutes: build the cheap empirical distribution first.** Predicted XIs are strictly
   less information and an external dependency; add only if the journal shows minutes
   error dominating.
3. **Derive free transfers, don't add a session cookie.** Already working. The live-squad
   limitation costs ~nothing given a Thursday solve.
4. **Split the backtest.** Calibrate free-transfer and money-in-the-bank shadow prices on
   2025/26 — verified available and complete (vaastav
   `data/2025-26/gws/merged_gw.csv`, 29,757 rows, GW1–38, all DefCon columns). Do **not**
   trust chip values from it: a Bench Boost is worth whatever the one big double gameweek
   that season was worth, and a single season can't turn that into a distribution. BPS was
   retuned for 2026/27, and that error is **directional, not symmetric**: the change from
   1 BPS per 2 CBI to 1 per 3 was made to reduce overlap with DefCon, so it shifts bonus
   away from clearance-heavy centre-backs and toward attacking contributors (dropping the
   −1 for being tackled pushes the same way). Anything trained on 2025/26 to learn *which
   player types collect bonus* will systematically overvalue defensive bonus — correct for
   it or exclude bonus from what you learn. Chip structure, by contrast, is clean: 2025/26
   was the first two-set, no-Assistant-Manager season, matching 2026/27 exactly, so
   chip-timing behaviour backtests honestly (2024/25 and earlier do not — different chip
   menu *and* no DefCon). The transfer threshold still gets calibrated in-season from the
   journal regardless.
   *(An earlier version of this said the data didn't exist. It does — that was my error.)*

### Urgent, before the next fetch

`fetch_data.py` overwrites `bootstrap.json` on every run. Set-piece order
(`penalties_order`, `direct_freekicks_order`, `corners_and_indirect_freekicks_order`) is
the **only** input the API does not backfill — `element_summary[].history[]` gives price
and ownership retrospectively, but not this. Every fetch destroys the evidence that
penalty duty changed. Dated snapshots are one line and unrecoverable retroactively.

## Built

1. **`fetch_data.py` gaps** — `event-status/`, `element-summary/` for owned players,
   `leagues-classic/{id}/standings/` for leagues under 500 entries.
2. **`state.py`** — derived state, no hand-maintained file: banked free transfers
   reconstructed from history, chip windows from `bootstrap.chips`, next deadline.
3. **`check_team.py`** — pre-deadline checklist. Rules read from the live
   parameterization, not hardcoded.
0. **Dated `bootstrap.json` snapshots** (`fetch_data.py` → `data/snapshots/`), added
   2026-09-03. One a day; catches set-piece order changes the live API doesn't backfill.
4. **`journal.py`** — decision journal, added 2026-09-03. `add` logs a recommendation
   with its runner-up and reasoning; `resolve` pulls both players' actual gameweek
   points from `event/{gw}/live/` and computes the realized delta automatically, so
   scoring is against the counterfactual, not zero. Entries in `journal/entries.jsonl`,
   tracked in git. Tested end-to-end against the real GW2 captaincy call (João Pedro
   over Rogers, resolved delta +4) before being cleared for the real season.
5. **`fetch_news.py`** — news log, added 2026-09-03. Pulls three free RSS feeds
   (Fantasy Football Scout, FPL Hints, FPL Toolbox) and appends new items to
   `news/entries.jsonl` — headline, link, summary, published date, and when this
   project fetched it. Runs automatically from `fetch_data.py`, no separate
   schedule. Git-tracked, not gitignored: RSS feeds only show recent items, so an
   entry not caught before it scrolls off is gone for good — the same
   unrecoverability problem set-piece order had before `data/snapshots/`. Headlines
   only, no analysis or judgment — that's the LLM layer's job, not this script's.
   Injury data (`premierinjuries.com`) and predicted lineups have no free feed and
   are deliberately not scraped yet; see `docs/DATA_SOURCES.md` for the candidates
   and `WebSearch` covers them for now.

## Next up

### 5. Odds-based fixture difficulty

The real remaining data gap. FDR is a hand-assigned 1-5 integer; win probability and
over/under 2.5 are actual numbers. Everything downstream — transfer targets, captaincy,
chip timing — is currently resting on someone's gut estimate of how hard a fixture is.

**Open, and worth deciding before writing any code:** most odds APIs have a free tier but
need a key. Does a key belong in this repo at all? Options: env var and never committed,
a gitignored `secrets.json`, or skip the API and scrape a public odds page. The answer
changes the implementation, so decide first.

### 6. Chip expiry monitor & set-piece watch

**Chip expiry monitor.** Half the chips evaporate at the GW19 deadline (13:30 GMT,
Sat 2 Jan 2027) and people routinely waste them. `state.py` already prints the windows;
this adds the judgment: a running "is the best remaining chip plan worth more than zero"
check, escalating in tone as GW19 approaches. Needs a view of upcoming doubles/blanks to
be genuinely useful, which ties it to the blank/DGW detector below.

**Set-piece watch.** Diff `penalties_order`, `direct_freekicks_order`, and
`corners_and_indirect_freekicks_order` between pulls. Penalty duty changing hands is one
of the highest-alpha events in FPL and is badly tracked by most tools. The prerequisite —
dated snapshots to diff against — is now built (`data/snapshots/`, 2026-09-03). The watch
itself (the diff and the alert) is still open; there's only one day of history so far.

## Parked / open questions

- **Authenticated `my-team` endpoint.** `check_team.py` can only validate the last *saved*
  squad — transfers made in the app since the last deadline are invisible. Fixing that
  needs a session cookie in the repo. Worth it? Probably not for a hobby project, but it's
  the one real limitation in what's built so far.
- **Effective ownership as a risk gauge.** Global `selected_by_percent` is already cached.
  The work is turning it into "this captaincy call is a 300k-rank swing either way",
  which needs a distribution, not a point estimate.
- **Blank/double gameweek detector.** Can't be predicted from the API — they fall out of
  cup progression and European congestion, and are human-curated (Ben Crellin's planner).
  But early warning is trivial: watch for any fixture with `event: null`, or any gameweek
  whose fixture count drifts off 10. Currently all 38 have exactly 10.
- **Bench Boost handling in `check_team.py`.** With a Bench Boost active all 15 play, so
  the bench checks change meaning. Not relevant until a chip is played.
- **Price-change alerting.** The data is native now (`price_change_projections`), so this
  is presentation, not modelling — probably just a line in the weekly output rather than
  its own feature.
