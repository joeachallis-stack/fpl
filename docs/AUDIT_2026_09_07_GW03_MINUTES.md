# GW3 minutes forecast audit — 2026-09-07

This is the first genuine out-of-sample minutes result in the project. The forecast was
frozen at 2026-09-03 22:09 UTC, before the GW3 deadline, and resolved only after the
official FPL flags changed to both `finished` and `data_checked`.

Resolution ran through `python scripts/freeze.py --resolve-only`, which refreshed every
player history before scoring. It completed at 2026-09-07 13:44 UTC. All 652 archived rows
have an outcome and one common `resolved_at` marker.

An integrity comparison against Git `HEAD` confirmed that every forecast and input field
is byte-equivalent after parsing. The only additions are `actual_minutes`, `actual_band`
and `resolved_at`; no prediction was revised after the result.

## Headline result

The error convention is forecast minus actual, so positive bias means overprediction.

| Population | Rows | MAE | Bias | Modal band correct |
|---|---:|---:|---:|---:|
| All registered players | 652 | 10.28 min | -0.58 min | 81.1% |
| Actual starters | 220 | 15.92 min | -10.99 min | 82.7% |
| Actual substitutes used | 87 | 17.38 min | +4.06 min | 46.0% |
| Actual unused players | 345 | 4.89 min | +4.89 min | 89.0% |
| Joe's GW3 squad | 15 | 6.55 min | +1.11 min | 93.3% |
| Current displayed incoming shortlist | 6 | 3.52 min | -2.52 min | 100.0% |
| Squad plus shortlist | 21 | 5.69 min | +0.08 min | 95.2% |

The three-band multiclass Brier score is 0.313 and log loss is 1.385 across all players.
Those are descriptive first observations, not calibrated benchmarks. The independent
sample size is one gameweek, not 652.

Actual bands were 345 zero, 95 one-to-59, and 212 sixty-plus. The model's modal choices
were 354 zero, 89 one-to-59, and 209 sixty-plus. Those aggregate counts look close while
several player identities are badly wrong, so count-level agreement must not be mistaken
for lineup knowledge.

“Actual starter” and “actual substitute” are retrospective groups joined from the official
GW3 history. The starter bias therefore includes players who unexpectedly entered the XI;
it does not mean the model underpredicts a player already known to start by eleven minutes.

## Largest misses

| Player | Forecast | Actual | Error | Actual role |
|---|---:|---:|---:|---|
| Gudmundsson | 0.0 | 90 | -90.0 | starter |
| Danso | 0.0 | 90 | -90.0 | starter |
| Konsa | 5.9 | 90 | -84.1 | starter |
| Mosquera | 83.6 | 0 | +83.6 | unused |
| Pinnock | 6.4 | 90 | -83.6 | starter |
| Mings | 7.4 | 90 | -82.6 | starter |
| Pau | 82.1 | 0 | +82.1 | unused |
| Disasi | 8.6 | 90 | -81.4 | starter |
| Colwill | 79.8 | 0 | +79.8 | unused |
| Frimpong | 79.3 | 0 | +79.3 | unused |

These are role/selection misses, not small errors around substitution timing. That is the
main failure mode to carry into GW4.

## Joe's squad and shortlist

The owned-player miss that matters most is Tzolis: 59.0 forecast versus 90 actual, and the
modal band was 1–59 rather than 60+. This is the frozen GW3 number; it must not be confused
with the mutable pre-finalization GW4 forecast.

Other material owned errors were Isak at 90 versus 63, Calafiori at 85.3 versus 66,
Palestra at 11.2 versus 0, and Shaw at 80.4 versus 90. The other ten owned players were
within one minute, including exact 90-minute calls on João Pedro, Virgil, Szoboszlai,
Guéhi, Bruno Fernandes, Gibbs-White and Kinsky.

The six incoming names shown across the current top-three horizon options all landed in
the correct band: Gakpo 79.3 versus 90, Palmer 86.3 versus 90, Thiago 86.3 versus 90,
Tavernier 90 versus 88, Hall 90 versus 89, and Kelleher 90 versus 90. This shortlist was
generated on pre-finalization inputs and must be regenerated before it is used for GW4.

## What this changes for GW4

Trust the minutes model more for established starters and obvious nonparticipants than for
fringe players or recent role changes. The attractive aggregate MAE is partly earned on
345 unused players; the 46% substitute-band accuracy and the 75–90 minute role reversals
are more relevant when a transfer decision hinges on selection.

The first result does not justify changing a constant or creating a robustness margin.
Before the GW4 decision:

1. rebuild minutes from the now-final GW3 histories;
2. inspect Tzolis and every duty/role-change flag manually;
3. rerun projections, decisions and the independent horizon comparison;
4. treat packages whose edge depends on uncertain starters more skeptically than packages
   built from established 80–90 minute players;
5. retain the Thursday code freeze and collect more independent gameweeks before retuning.

