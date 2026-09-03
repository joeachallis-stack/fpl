# The FPL Decision Engine: What Prior Work Says the "Brain" Should Consider

## TL;DR
- The literature converges on a **two-stage architecture**: (1) a per-player, per-gameweek expected-points forecaster whose single hardest and highest-value component is **minutes/appearance probability**, feeding (2) a **multi-period mixed-integer linear program (MILP)** that jointly picks the XI, captain, bench and transfers over a rolling horizon — exactly the design used by the strongest open-source solver (Sertalp Çay's FPL-Optimization-Tools) and by the academic MILP/stochastic-programming papers.
- The two biggest documented pitfalls your engine must solve are **finite-horizon truncation** (models burn transfers/chips because their value falls outside the planning window) and **objective mismatch** (maximising expected points is not the same as maximising expected rank, which is what actually wins). Practitioners fix truncation with **terminal "shadow" values on free transfers and money-in-the-bank plus an exponential future-gameweek decay (~0.84 per GW)**; the rank-vs-points gap is where **effective ownership / contrarian theory** and DFS "picking winners" portfolio methods apply.
- **Every published academic model predates the current ruleset** (DefCon defensive points, two sets of four chips expiring at GW19, five bankable free transfers). Their chip/transfer valuations must be re-derived for 2026/27; the open-source solvers have already been patched for 5-FT rolling and two-chip-sets and are the more reliable starting point than any paper.

## Key Findings

**1. The canonical academic lineage exists and is consistent.** The foundational work is Matthews, Ramchurn & Chalkiadakis (AAAI 2012, Proc. vol. 26(1):1394–1400), which modelled FPL as a Bayesian reinforcement-learning problem (belief-state MDP + Bayesian Q-learning over a multi-dimensional knapsack); its agent "is able to rank at around the top percentile when pitched against 2.5M human players," outperforming human selections in ~99% of simulated cases. The MILP/forecast lineage runs Kristiansen, Gupta & Eilertsen (NTNU MSc, 2018, rolling-horizon heuristic), Gupta (2019), Venter & van Vuuren (ORiON 40(1):69–107, 2024, top-4% in 2020/21), and Ramezani & Dinh (2025, deterministic + robust MILP). The DFS transfer-method literature is anchored by Hunter, Vielma & Zaman, "Picking Winners in Daily Fantasy Sports Using Integer Programming."

**2. Minutes prediction is confirmed as the key lever.** Multiple sources explicitly rank appearance/minutes modelling as foundational and the hardest part; commercial models (FPL Review) treat editable expected minutes (xMins) as their central adjustable input, and OpenFPL's chief modelling compromise was to dispense with proprietary xMins, "using instead the categorical availability tags provided by the FPL API."

**3. Point-estimate vs distributional: the gain is modest and non-uniform.** Ramezani & Dinh found ARIMA with a constrained budget and rolling window most consistent; Monte Carlo and weighted averages were competitive but robust/stochastic variants were "not uniformly superior." The bigger accuracy wins come from better features (xG, xA, minutes, bookmaker odds), not from stochastic machinery.

**4. Empirical: skill is real and concentrated in a few decisions.** O'Brien, Gleeson & O'Sullivan (PLOS ONE 2021, 16(3):e0246698; 901,912 managers, 2018/19) show season-to-season points correlation of 0.42 (adjacent seasons), each extra year of experience worth ~22.1 points, team value at GW19 worth ~21.8 points per £1M, and chip timing sharply tier-dependent (79.4% of top-10k played Bench Boost in DGW35 vs only 28.9% of the rest). The prime distinguishing factor is long-term planning.

## Details

### A. Academic papers and theses (verified)

- **Matthews, Ramchurn & Chalkiadakis (2012), "Competing with Humans at Fantasy Football: Team Formation in Large Partially-Observable Domains" (AAAI):** first sequentially-optimal FPL benchmark. Belief-state MDP with Bayesian Q-learning; action space exponential in number of players; beliefs held over multiple player characteristics; team selection modelled as a multi-dimensional knapsack. Result: ~top percentile vs 2.5M humans, beating human selections in ~99% of simulated cases. Your reference for a principled, uncertainty-aware sequential formulation.
- **Kristiansen, Gupta & Eilertsen (2018, NTNU MSc), "Developing a Forecast-Based Optimization Model for FPL":** a full mathematical model of FPL solved with a **rolling-horizon heuristic** fed by three forecasting methods (recent-average; multiple regression; and a third variable-based approach). Run over the first 35 GWs of 2017/18 and compared to real managers. The clearest academic precedent for your multi-period transfer engine.
- **Venter & van Vuuren (2024), ORiON 40(1):69–107, "An optimisation approach towards soccer Fantasy Premiere League team selection":** combinatorial optimisation + statistical/ML forecasts; retrospectively placed **top 4%** worldwide in 2020/21.
- **Ramezani & Dinh (2025), arXiv:2505.02170, "A data-driven framework for team selection in FPL":** deterministic and robust MILPs choosing XI, bench and captain under budget (they set the XI budget b=£83.5m, reserving ~£16.5m for four bench players), formation and 3-per-club constraints. Captaincy is modelled with an explicit binary y_j and the objective adds a second c_j when a player is captain. Benchmarks simple/weighted averages, exponential smoothing, ARIMA, Monte Carlo and a hybrid ridge-regression score (features: ICT index, xG, xA, xGI, xGC, selected%, starts). The robust variant uses a box uncertainty set and a max-min objective. **Finding: ARIMA + constrained budget + rolling window most consistent on 2023/24; robust and hybrid help selectively, not uniformly.** Chips are explicitly excluded ("special and one-time cards are not taken into account") — a key limitation for your purposes.
- **Thesis / prediction cluster:** Dykman (2018, Stellenbosch, "Decision support for effective team selection in FPL"); Saifi (2020); Lindberg & Söderberg (2020); Ramdas (CNN thesis); Valouxis; the Nova de Lisboa 2024 squad-composition thesis; and the Uppsala 2025 XAI/LLM thesis (diva2:1972615) form the broader prediction/ML literature.
- **DFS transfer methods — Hunter, Vielma & Zaman, "Picking Winners in Daily Fantasy Sports Using Integer Programming" (arXiv:1604.01455; INFORMS J. Optimization):** portfolio of lineups for top-heavy payoffs; the objective is the probability that at least one entry wins (submodular, NP-hard, greedy has strong performance guarantees); entries modelled as jointly Gaussian using pairwise marginal winning probabilities. **This is the key theoretical basis for rank/percentile (not expected-points) objectives and for contrarian construction.** Newell & Easton (2017) add a stochastic IP maximising expected payout; a related framework (How to Play Fantasy Sports Strategically) explicitly models opponents' lineups and reduces the problem to a series of binary quadratic programs — directly relevant to effective-ownership optimisation.

### B. How the literature handles the user's specific problems

**Finite-horizon truncation & terminal values.** Handled operationally in FPL rather than theoretically. The multi-stage stochastic-programming (MSP) literature (Rolling Horizon Policies in MSP, arXiv:2102.04874) prescribes an ε-sufficient number of stages for discounted infinite-horizon problems and terminal value-function approximations (e.g. piecewise-linear terminal value) to defeat myopia. In FPL practice, Çay's solver defeats truncation with three devices in settings.json: a **future-gameweek decay (decay_base ≈ 0.84, i.e. gameweek k's EV weighted 0.84^k)**, an explicit **free-transfer terminal value (ft_value ≈ 0.8–1.5 points per banked FT)**, and a **money-in-the-bank value (itb_value ≈ 0.08–0.2 points per £0.1m)**. These are the practical "terminal value functions" that stop the solver dumping transfers, chips and bank at the window's edge. Typical **horizon = 5–8 gameweeks.** Both Kristiansen and the MSP theory warn the horizon must be long enough that end-of-window effects don't distort early decisions.

**Chip valuation.** No peer-reviewed shadow-price estimates for chips exist; the academic MILPs largely exclude chips. The best quantitative anchors are empirical (O'Brien et al., below). The standard engineering solution, documented in the "holistic solver" write-up (fpl.hashnode.dev): keep the **Wildcard inside the MILP via a Big-M constraint on transfer banking** (M≈15 deactivates the transfer-cost rule that week), but **enumerate Bench Boost / Triple Captain / Free Hit as scenarios** — solve the full MILP once per candidate (chip, gameweek) combination — because they create non-linear interactions (BB re-scores all 15; TC changes the captain multiplier; FH is a one-week squad) that would otherwise require auxiliary binaries per player-gameweek and blow up runtime. Practitioner rule for Free Hit: worth more than serial hits once ~4+ players need replacing (4×−4 = −12 before any gain).

**Point-estimate vs distributional.** Deterministic expected points dominates practice; Ramezani & Dinh show Monte Carlo competitive but not superior. Matthews et al. is the main genuinely distributional (Bayesian) approach. Evidence-based recommendation: use expected points for the core solve, and reserve distributional/Monte-Carlo for captaincy and chip timing, where variance matters most.

**Objective: points vs rank.** The FPL MILP literature maximises expected points; the DFS literature (Hunter–Vielma–Zaman; Newell–Easton) maximises probability-of-winning / expected payout and explicitly models rank and opponents. Practitioner "effective ownership" (EO) theory formalises the bridge: above ~70% EO, captaining a player is a rank-neutral-to-negative decision in expectation; the template is the correct default only when EO asymmetry doesn't justify variance; rank-climbing requires lower-EO/differential exposure while rank-protection tracks the high-EO template.

**Captaincy as a sub-problem.** Treated as a distinct, high-leverage decision. O'Brien et al. show captaincy points distributions rise monotonically by manager tier. Practitioner consensus: across a 38-GW season, captaincy swings more points than all transfers combined; decide it on expected points modified by EO and rank situation.

**Bench & autosub value.** Modelled as fractional weights on bench EV. Çay's default bench_weights ≈ {GK 0.03, first outfield sub 0.21, second 0.06, third 0.002–0.06}, reflecting the probability each bench slot is auto-subbed in. The better approach (noted in practitioner code but often unimplemented) is to derive these weights from each player's xMins rather than using static constants.

### C. Player-points prediction models — features and measured accuracy

- **OpenFPL (Groos, 2025, arXiv:2508.09992):** position-specific ensembles (XGBoost + Random Forest, median of 50 models) on FPL + Understat public data, trained 2020-21 to 2023-24, tested prospectively on 2024-25 (GW32–38). Features averaged over 1/3/5/10/38-match horizons; uses FPL categorical availability tags (0/25/50/75/100%) instead of proprietary xMins. **Measured 1-GW-ahead RMSE for "Haulers" (>2 pts): OpenFPL 5.142 vs FPL Review 5.169 vs Last-5 baseline 5.573; for "Tickers": OpenFPL 1.517 vs FPL Review 1.605 vs Last-5 2.365.** OpenFPL matches the paid FPL Review Massive Data Model overall and beats it for high-return players, across 1–3 GW horizons. Confirms xG/xA, ICT and recent form as top features, and that public data suffices.
- **Frees, Ravella & Zhang (2024, arXiv:2405.02412), "Deep Learning and Transfer Learning Architectures for EPL Player Performance Forecasting":** Ridge/LightGBM/CNN; the best CNN beats prior EPL forecasting models with fewer features; most predictive features = recent FPL points, Influence, Creativity, Threat, and **playtime (minutes)**.
- **FPL Review "Massive Data" model:** built on bookmaker odds + editable xMins, but its own published analysis found a data-driven goalscoring model *more* predictive than bookmaker-odds implications; recent xG over ~450 minutes is barely better than a positional dummy, whereas long-run (20+ game) xG approaches bookmaker quality. Takeaway: use odds as a feature, but a good long-horizon xG model rivals them.
- **Minutes as the crux:** corroborated across OpenFPL (availability tags are its main compromise), FPL Review (xMins is the central editable input), Frees et al. (playtime a top feature) and practitioner modelling ("appearance minutes are the foundation of FPL performance"). This validates the user's belief that minutes are the highest-value and hardest component.

### D. Notable open-source projects and design decisions

- **sertalpbilal/FPL-Optimization-Tools (now solioanalytics/open-fpl-solver):** the reference implementation. Deterministic MILP via HiGHS/highspy (earlier CBC/sasoptpy). Multi-week horizon (default 5–8). Objective = decayed sum of weekly XI EV + captain EV + weighted bench EV, minus hit costs, plus terminal FT and ITB values. Documented parameters include horizon 5–8, decay_base 0.84, ft_value 0.8–1.5, itb_value 0.08–0.2, and bench_weights {0:0.03, 1:0.21, 2:0.06, 3:0.002}. Handles 5-FT rolling and WC/FH FT-roll logic (patched for new rules); supports custom ft_value_list; chips via forced/allowed/combination enumeration and per-chip limits. Compatible with FPL Review and Mikkel Tokvam projections. This is the closest existing thing to the engine the user wants to build.
- **AIrsenal (Alan Turing Institute):** two-model prediction — a team-level model to predict scorelines and a player-level model for goal involvements, plus historical-average heuristics; default 3-GW prediction horizon; transfer optimisation over a horizon; chips supported in optimisation (though not auto-applied via the API). Trains on the prior three seasons. Documented weakness: no correlation-awareness (early on it recommended tripling up on one team's defenders); finished top ~30% in year one and poorly in year two — a cautionary tale about model drift and unmodelled correlation. A release explicitly updated it "for new FPL rules allowing up to 5 free transfers to be saved."
- **FPL Review:** paid projections (bookmaker-odds + editable xMins) plus a transfer planner and solver; the Massive Data model is the commercial accuracy benchmark OpenFPL matched.
- **Fantasy Football Fix:** a predictive-algorithm service with ownership/captaincy/EO analytics and "Elite" manager tracking (its content evidences EO-driven decision-making among top managers).
- **Others worth studying:** lazyFPL (janbjorge), JFPL (Julia port sharing the same decay/bench/ft parameters), FPLForm-fed PuLP solvers (dbozbay), and OpenFPL's own repository (daniegr/OpenFPL, MIT-licensed models + inference code).

### E. Analytical strategy guides & empirical findings

- **O'Brien, Gleeson & O'Sullivan (PLOS ONE 2021, 16(3):e0246698)** — the single most rigorous empirical study, 901,912 managers, 2018/19 season:
  - **Season-to-season points correlation 0.42** (adjacent seasons), decaying with the gap (0.36 at two seasons, down to ~0.13 at 12 seasons); skill persists over 13 seasons.
  - **Each extra year of experience ≈ +22.1 points** (R²=0.082); the season winner scored 2,659 points.
  - **Team value at GW19 ≈ +21.8 points per £1M** (R²=0.169) — financial/team-value management is measurably worth points.
  - Higher tiers make better transfers (steeper CCDF of "a better transfer was available"), better captaincy, and — most strikingly — **superior chip timing**: "79.4% choosing to play their BB chip during DGW35 in comparison to only 28.9% of those in the rest of the dataset," with Bench Boost averaging 23.2 points (top-10k) vs 13.8 (field); Free Hit concentrated in DGW32, second Wildcard in GW34, Triple Captain in GW36.
  - Conclusion: **"long-term planning and consistently good decision-making"** are the prime skill factors; template "herding" exists but is transient.
- **Practitioner analytical pieces of merit:** effective-ownership/rank-mode frameworks (FPL Oracle: EO thresholds ~40–70% as the decision-pivot zone, >70% as rank-neutral); transfer-hit break-even analysis (a single −4 needs the incoming player to beat the outgoing by >4 points over the hold horizon; with up to five bankable free transfers the bar for taking hits has risen and "save toward a mini-wildcard" is now a first-class option).

### F. What is now outdated (must be re-derived for 2026/27)

- **DefCon (defensive contribution points), introduced 2025/26, retained 2026/27:** +2 pts for a defender reaching a combined 10 clearances, blocks, interceptions and tackles (CBIT); midfielders/forwards need 12 defensive contributions including ball recoveries (CBIRT); capped at +2 per match. No academic model includes this; it materially raises the value of defensive players (e.g. reported ~33% average hit-rate among considered defenders in 2025/26; standout Senesi 70.3% hit-rate, 52 DefCon points) and requires a **new threshold-probability sub-model** (per-player hit-rate per fixture). BPS was also re-weighted for 2026/27 (1 BPS per 3 CBI, down from 1 per 2).
- **Two sets of four chips** (Wildcard, Free Hit, Triple Captain, Bench Boost) per season — eight in total; the Assistant Manager chip has been removed. The **first set must be used before the GW19 deadline** (in 2026/27, 13:30 UTC on Saturday 2 January 2027) and does not carry over; a fresh set is available from GW20. Every "one wildcard per half / one of each chip per season" assumption in older papers is void; chip valuation must now handle two independent expiry windows.
- **Up to five bankable free transfers** (was two). This changes the transfer shadow price and makes deliberate banking toward a five-man restructure ("mini-wildcard") a first-class strategy; the FT terminal-value function must cap at 5 and value the marginal FT differently as the bank fills.
- **Minor but real:** the simplified 2025/26+ assist definition, and the AFCON accommodation whereby every manager's free-transfer count is topped up to the maximum of five in Gameweek 16.

## Recommendations

**Stage 1 — Build the forecaster first, and the minutes model first of all.** Implement a position-specific ensemble (XGBoost + Random Forest) on public FPL + Understat data, mirroring OpenFPL (target ~5.14 RMSE on haulers, ~1.52 on tickers at 1 GW ahead). Build a dedicated **appearance/minutes model** (start probability × expected minutes given start) as a separate, carefully validated component — the literature is unanimous this is the highest-value, hardest input. Add a **DefCon threshold sub-model** (per-player probability of clearing 10 CBIT / 12 CBIRT vs each opponent) since no prior model covers it. Blend bookmaker odds (match result, over/under, anytime goalscorer) as features, but note FPL Review's finding that a strong long-run xG model rivals odds implications.

**Stage 2 — Multi-period MILP, not a myopic solver.** Fork or closely replicate sertalpbilal/FPL-Optimization-Tools. Use **horizon 5–8 GW**, **exponential decay ≈ 0.84/GW**, and explicit **terminal FT value (~0.8–1.5 pts, capped at 5 FTs)** and **ITB value (~0.1–0.2 pts per £0.1m)** to prevent truncation from dumping transfers/chips/bank at the window's edge. Model the Wildcard inside the MILP (Big-M on transfer-banking constraints); **enumerate BB/TC/FH as scenarios** across candidate gameweeks, respecting the two-set structure and the GW19 expiry.

**Stage 3 — Choose the objective by rank goal.** Default to expected decayed points for squad and transfers. For captaincy and late-season chip timing, switch to a **rank/percentile objective** informed by effective ownership (Hunter–Vielma–Zaman style): protect rank with high-EO picks when ahead, take lower-EO differentials when climbing. Use Monte Carlo here, where variance dominates the decision.

**Stage 4 — Calibrate chip and hit thresholds to the new rules empirically.** Re-derive chip shadow prices by backtesting on 2025/26 data (the first DefCon + two-chip-set season). Encode the transfer-hit rule: take a −4 only when projected gain over the hold horizon exceeds 4 points (a higher bar now that up to five FTs can be banked); otherwise prefer banking toward a five-transfer restructure.

**Benchmarks that would change the plan:** if your minutes model's start-probability discrimination is weak (AUC below ~0.85) or your hauler RMSE materially exceeds ~5.2, prioritise prediction over optimisation — the optimiser cannot rescue bad projections. If backtested chip timing underperforms the simple "template" calendar (Bench Boost in the biggest DGW, Free Hit/Wildcard around blanks, as the top-10k empirically do), simplify to that dominant chip calendar rather than over-optimising.

## Caveats
- **All peer-reviewed FPL optimisation papers predate DefCon, the two chip-sets and the 5-FT rule.** Treat their chip/transfer numbers as structurally obsolete; the open-source solvers (already patched) are more current than any paper.
- The precise solver parameters (decay_base 0.84, ft_value, itb_value, bench_weights) are **practitioner defaults, not validated optima** — reasonable priors to tune on your own backtest, not ground truth.
- The strongest empirical study (O'Brien et al.) covers a single season (2018/19) under the old ruleset; its captaincy and net-transfer per-tier *averages* exist only as unreadable in-figure labels, so only the chip-usage, experience and correlation figures are exact numbers.
- Commercial models (FPL Review, Fantasy Football Fix) are closed-source; their accuracy claims are self-reported except where OpenFPL independently benchmarked FPL Review.
- Several strategy figures quoted around xPts-vs-form point gains come from vendor blogs and should be treated as marketing-adjacent unless independently verified.
---

# Cross-check against this project's verified data

*Appended 2026-09-02. The document above is stored verbatim as received. This section
records where its claims were checked against the live 2026/27 API cache in `data/`,
and is the only part written by this project.*

## Confirmed independently

- **Defensive contribution composition.** The report's "defenders need 10 CBIT;
  midfielders/forwards need 12 including ball recoveries (CBIRT)" matches what was
  derived empirically from `element_summary` before this document arrived: DEF =
  tackles + CBI, MID/FWD = tackles + CBI + recoveries, GKP always 0. Thresholds have since
  been **pinned exactly against all 29,757 player-gameweeks of 2025/26: DEF 10, MID 12,
  FWD 12**, with clean boundaries (highest non-scoring defender on 9, lowest scoring on
  10). Safe to hardcode. The *composition* is the part documented nowhere and worth having
  derived. `game_config.scoring.defensive_contribution` gives 2 pts for DEF, MID
  **and FWD** — consistent with the report's "capped at +2 per match".
- **Assistant Manager chip removed.** All `mng_*` keys in `game_config.scoring` are 0,
  and `bootstrap.chips` contains exactly 8 grants: Wildcard, Free Hit, Bench Boost,
  Triple Captain × two windows (GW1/2–19 and GW20–38). Dated precisely from the data: the
  chip ran in **2024/25 only** (322 `AM` position rows, GW23–38), and 2025/26 has none.
  Useful consequence — **2025/26 matches 2026/27 exactly on chip structure**, so it is a
  clean season for backtesting chip timing; 2024/25 and earlier are not.
- **Five bankable free transfers.** `game_settings.max_extra_free_transfers` is 4, so the
  cap is 5. Read it from there rather than hardcoding.
- **Horizon decay.** The report's practitioner default of 0.84/GW closely matches the
  0.85 in the design brief, and its "horizon 5–8 GW" brackets the brief's 6.

## Conflicts — do not act on either side without checking

- **AFCON free-transfer top-up in GW16 — RESOLVED 2026-09-02, the report is wrong for
  this season.** It says "every manager's free-transfer count is topped up to the maximum
  of five in Gameweek 16."
  **AFCON 2027 runs 19 June – 17 July 2027**, a summer tournament hosted by Kenya, Uganda
  and Tanzania — entirely outside the 2026/27 season. The claim is a carryover from
  2025/26, when AFCON 2025 ran Dec 2025 – Jan 2026 and did disrupt the season.
  [`RULES_2026_27.md`](RULES_2026_27.md) is correct; `scripts/state.py` needs no GW16
  special case. (For the record, `bootstrap.json` carries no free-transfer field on any
  event, so the API could not have settled this either way.)
  **General lesson for this document: it does not reliably distinguish 2025/26 from
  2026/27 rules.** Date-check any rules claim in it before acting.
- **Team value.** The report cites O'Brien et al.: team value at GW19 worth ~+21.8 points
  per £1M (R²=0.169). The design brief says value is "a tiebreaker, never an objective…
  worth ~0.1–0.2 pts/GW at the margin." The tension is likely **observational, not
  causal** — better managers make better transfers, which produces both higher value and
  more points. Value is a proxy for skill in that regression, not necessarily a lever.
  The brief's treatment is still the safer encoding.

## Tension with the recommendations already made

- **Objective: points vs rank.** The report is more sympathetic to a rank objective than
  the audit's recommendation to cut effective ownership was, and it is the strongest
  counterargument on file. Two things temper it: the DFS literature it draws on
  (Hunter–Vielma–Zaman) optimises for **top-heavy winner-take-all payoffs**, a different
  regime from overall rank in a 9M field; and the brief itself chose total points
  explicitly. The EO thresholds it cites (~40–70% as the decision-pivot zone, >70% as
  rank-neutral) are worth keeping as **displayed context** in the weekly brief regardless.
- **Backtest data — the report was right, this project was wrong.** Stage 4 recommends
  re-deriving chip shadow prices "by backtesting on 2025/26 data (the first DefCon +
  two-chip-set season)." An earlier cross-check here claimed that data was unobtainable
  because vaastav's repo stopped at 2024/25. **Verified 2026-09-02: it is available.**
  `data/2025-26/gws/merged_gw.csv` holds 29,757 rows across all 38 gameweeks with 46
  columns, including `defensive_contribution`, `tackles`, `recoveries`, `expected_goals`,
  `starts`, `value` and `selected`. A `2026-27` directory exists too. The Stage 4
  recommendation is executable — with the caveat that one season prices free transfers
  well and chips badly.

## Concrete numbers worth lifting

Useful as priors, not ground truth — the report flags them as practitioner defaults:

| Parameter | Value |
|---|---|
| Future-gameweek decay | 0.84 per GW |
| Free transfer terminal value | 0.8–1.5 pts (brief assumed ~1.5, the top of the range) |
| Money-in-the-bank value | 0.08–0.2 pts per £0.1m |
| Bench weights | GK 0.03, sub 1 0.21, sub 2 0.06, sub 3 0.002 |
| Free Hit break-even | worth more than serial hits at ~4+ replacements needed |
| Target hauler RMSE (1 GW) | ~5.14 (OpenFPL); above ~5.2 means fix projections before optimising |
| Target start-probability AUC | ~0.85; below that, prioritise the minutes model |
