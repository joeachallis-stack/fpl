"""Compare hold, transfer-count and available chip squads using projected FPL points.

This is the decision layer above projections.py. It optimizes complete legal squads,
reselects the XI/captain/vice/bench for every forecast gameweek, and treats prices as
feasibility constraints rather than as points. All transfers happen now; the resulting
squad is held through the horizon.

Usage:
    python scripts/decisions.py
    python scripts/decisions.py --horizon 4
    python scripts/decisions.py --details
    python scripts/decisions.py --no-chips
    python scripts/decisions.py archive
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix

import projections
import state

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "decisions.json"
ARCHIVE_DIR = ROOT / "decisions"
TOP_BY_TRANSFERS = {1: 3, 2: 3, 3: 1, 4: 1, 5: 1}
POSITION_ORDER = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}


def load(path: Path) -> dict | list:
    return json.loads(path.read_text())


def current_context(bootstrap: dict) -> dict:
    entry = load(DATA_DIR / "entry.json")
    gw = entry.get("current_event")
    picks_path = DATA_DIR / f"picks_gw{gw}.json"
    if not gw or not picks_path.exists():
        raise SystemExit("current saved squad is unavailable; run scripts/fetch_data.py")
    picks = load(picks_path)
    squad = [row["element"] for row in picks["picks"]]
    bank = picks["entry_history"]["bank"]
    free, _ = state.free_transfers(load(DATA_DIR / "history.json"), bootstrap["game_settings"])
    return {"entry": entry, "picks": picks, "squad": squad, "bank": bank, "free_transfers": free}


def acquisition_prices(squad: list[int], bootstrap: dict, transfers: list[dict]) -> dict[int, dict]:
    """Recover the price paid for every currently owned player, with provenance.

    A current player's latest transfer-in cost is authoritative. A player never bought
    after GW1 belongs to the initial squad; the first official element-history value is
    the only public acquisition-price record available without an authenticated my-team
    request. Missing evidence is fatal because substituting now_cost can change legality.
    """
    elements = {row["id"]: row for row in bootstrap["elements"]}
    inbound: dict[int, list[dict]] = defaultdict(list)
    for row in transfers:
        inbound[row["element_in"]].append(row)
    result = {}
    for element in squad:
        if inbound.get(element):
            row = max(inbound[element], key=lambda item: (item.get("time", ""), item.get("event", 0)))
            result[element] = {
                "purchase_price": row["element_in_cost"],
                "source": f"transfer history GW{row['event']}",
            }
            continue
        path = DATA_DIR / f"element_summary/{element}.json"
        history = load(path).get("history", []) if path.exists() else []
        if not history:
            name = elements[element]["web_name"]
            raise SystemExit(f"cannot establish purchase price for initial-squad player {name} ({element})")
        first = min(history, key=lambda item: (item["round"], item.get("kickoff_time", "")))
        result[element] = {
            "purchase_price": first["value"],
            "source": f"official element history GW{first['round']}",
        }
    return result


def selling_price(purchase: int, current: int, settings: dict) -> int:
    if settings.get("element_sell_at_purchase_price"):
        return purchase
    if current <= purchase:
        return current
    fee = float(settings.get("transfers_sell_on_fee", 0.5))
    return purchase + math.floor((current - purchase) * (1 - fee) + 1e-9)


def player_week(player: dict, week: int) -> dict:
    return player["gameweeks"][week]


def week_p_zero(player: dict, week: int) -> float:
    forecast = player_week(player, week)
    if forecast.get("blank"):
        return 1.0
    fixtures = len(forecast.get("fixtures", [])) or 1
    return float(player["minutes_bands"]["p_zero"]) ** fixtures


def captain_pair(
    starters: tuple[int, ...], players: dict[int, dict], week: int
) -> tuple[int, int, float, float]:
    """Captain the highest-xP starter; show vice takeover as a separate sensitivity."""
    ranked = sorted(starters, key=lambda element: player_week(players[element], week)["xP"], reverse=True)
    captain, vice = ranked[:2]
    captain_xp = player_week(players[captain], week)["xP"]
    vice_fallback = week_p_zero(players[captain], week) * player_week(players[vice], week)["xP"]
    return captain, vice, captain_xp, vice_fallback


def missing_distribution(ids: tuple[int, ...], players: dict[int, dict], week: int) -> dict[int, float]:
    dist = {0: 1.0}
    for element in ids:
        p_zero = week_p_zero(players[element], week)
        nxt = defaultdict(float)
        for count, probability in dist.items():
            nxt[count] += probability * (1 - p_zero)
            nxt[count + 1] += probability * p_zero
        dist = dict(nxt)
    return dist


def legal_subs(
    remaining: dict[str, int], available: tuple[int, ...], slots: int,
    players: dict[int, dict], play_rules: dict[str, tuple[int, int]],
) -> tuple[int, ...]:
    """Choose the highest-priority available subset that restores a legal formation."""
    best: tuple[tuple, tuple[int, ...]] | None = None
    for size in range(min(slots, len(available)) + 1):
        for chosen_indices in itertools.combinations(range(len(available)), size):
            counts = dict(remaining)
            for index in chosen_indices:
                position = players[available[index]]["position"]
                counts[position] += 1
            if not all(low <= counts[position] <= high for position, (low, high) in play_rules.items()):
                continue
            # More subs first, then earlier bench slots lexicographically.
            priority = tuple(1 if i in chosen_indices else 0 for i in range(len(available)))
            key = (size, priority)
            chosen = tuple(available[i] for i in chosen_indices)
            if best is None or key > best[0]:
                best = (key, chosen)
    return best[1] if best else ()


def expected_autosubs(
    starters: tuple[int, ...], bench_gkp: int, bench_order: tuple[int, ...],
    players: dict[int, dict], week: int, play_rules: dict[str, tuple[int, int]],
) -> float:
    starter_gkp = next(element for element in starters if players[element]["position"] == "GKP")
    result = week_p_zero(players[starter_gkp], week) * player_week(players[bench_gkp], week)["xP"]
    outfield = tuple(element for element in starters if players[element]["position"] != "GKP")
    by_position = {
        position: tuple(element for element in outfield if players[element]["position"] == position)
        for position in ("DEF", "MID", "FWD")
    }
    distributions = {
        position: missing_distribution(ids, players, week) for position, ids in by_position.items()
    }
    for missing_def, p_def in distributions["DEF"].items():
        for missing_mid, p_mid in distributions["MID"].items():
            for missing_fwd, p_fwd in distributions["FWD"].items():
                scenario_probability = p_def * p_mid * p_fwd
                missing_total = missing_def + missing_mid + missing_fwd
                if not scenario_probability or not missing_total:
                    continue
                remaining = {
                    "DEF": len(by_position["DEF"]) - missing_def,
                    "MID": len(by_position["MID"]) - missing_mid,
                    "FWD": len(by_position["FWD"]) - missing_fwd,
                }
                for mask in range(1 << len(bench_order)):
                    availability_probability = 1.0
                    available = []
                    for index, element in enumerate(bench_order):
                        p_zero = week_p_zero(players[element], week)
                        if mask & (1 << index):
                            availability_probability *= 1 - p_zero
                            available.append(element)
                        else:
                            availability_probability *= p_zero
                    if not availability_probability:
                        continue
                    chosen = legal_subs(
                        remaining, tuple(available), missing_total, players, play_rules
                    )
                    conditional_points = 0.0
                    for element in chosen:
                        appears = 1 - week_p_zero(players[element], week)
                        if appears:
                            conditional_points += player_week(players[element], week)["xP"] / appears
                    result += scenario_probability * availability_probability * conditional_points
    return result


def legal_lineups(squad: tuple[int, ...], players: dict[int, dict], play_rules: dict[str, tuple[int, int]]):
    by_position = {
        position: tuple(element for element in squad if players[element]["position"] == position)
        for position in ("GKP", "DEF", "MID", "FWD")
    }
    for goalkeeper in by_position["GKP"]:
        for defenders in range(play_rules["DEF"][0], play_rules["DEF"][1] + 1):
            for midfielders in range(play_rules["MID"][0], play_rules["MID"][1] + 1):
                forwards = 10 - defenders - midfielders
                if not play_rules["FWD"][0] <= forwards <= play_rules["FWD"][1]:
                    continue
                for selected in itertools.product(
                    itertools.combinations(by_position["DEF"], defenders),
                    itertools.combinations(by_position["MID"], midfielders),
                    itertools.combinations(by_position["FWD"], forwards),
                ):
                    yield (goalkeeper, *selected[0], *selected[1], *selected[2])


def best_lineup(
    squad: tuple[int, ...], players: dict[int, dict], week: int,
    play_rules: dict[str, tuple[int, int]],
) -> dict:
    """Exact legal XI/captain search; no-show coverage is reported separately."""
    best_primary = None
    for starters in legal_lineups(squad, players, play_rules):
        captain, vice, captain_bonus, vice_fallback = captain_pair(starters, players, week)
        base = sum(player_week(players[element], week)["xP"] for element in starters)
        primary = base + captain_bonus
        if best_primary is None or primary > best_primary[0]:
            best_primary = (primary, starters, captain, vice, base, captain_bonus, vice_fallback)
    assert best_primary is not None
    primary, starters, captain, vice, base, captain_bonus, vice_fallback = best_primary
    bench = tuple(element for element in squad if element not in starters)
    bench_gkp = next(element for element in bench if players[element]["position"] == "GKP")
    outfield_bench = tuple(element for element in bench if players[element]["position"] != "GKP")
    best_cover = None
    for order in itertools.permutations(outfield_bench):
        autosub = expected_autosubs(starters, bench_gkp, order, players, week, play_rules)
        if best_cover is None or autosub > best_cover[0]:
            best_cover = (autosub, order)
    assert best_cover is not None
    autosub, order = best_cover
    adjusted = primary + vice_fallback + autosub
    formation = "-".join(
        str(sum(players[element]["position"] == position for element in starters))
        for position in ("DEF", "MID", "FWD")
    )
    source = "+".join(sorted({player_week(players[element], week)["source"] for element in starters}))
    return {
        "gw": player_week(players[starters[0]], week)["gw"],
        "formation": formation,
        "starters": list(starters),
        "captain": captain,
        "vice_captain": vice,
        "bench": [bench_gkp, *order],
        "starting_xP": round(base, 3),
        "captain_bonus_xP": round(captain_bonus, 3),
        "vice_fallback_xP": round(vice_fallback, 3),
        "autosub_xP": round(autosub, 3),
        "planned_total_xP": round(primary, 3),
        "availability_adjusted_xP": round(adjusted, 3),
        "source": source,
    }


def score_squad(
    squad: tuple[int, ...], players: dict[int, dict], horizon: int,
    discount: float, play_rules: dict[str, tuple[int, int]],
) -> tuple[float, float, list[dict]]:
    lineups = [best_lineup(squad, players, week, play_rules) for week in range(horizon)]
    planned = sum((discount**week) * row["planned_total_xP"] for week, row in enumerate(lineups))
    adjusted = sum((discount**week) * row["availability_adjusted_xP"] for week, row in enumerate(lineups))
    return round(planned, 3), round(adjusted, 3), lineups


class SquadMILP:
    """Binary squad + weekly XI/captain optimizer; HiGHS handles the combinatorics."""

    def __init__(
        self, players: dict[int, dict], current: set[int], costs: dict[int, int],
        budget: int, bootstrap: dict, horizon: int, discount: float,
    ) -> None:
        self.players = players
        self.ids = sorted(players)
        self.at = {element: index for index, element in enumerate(self.ids)}
        self.current = current
        self.costs = costs
        self.budget = budget
        self.bootstrap = bootstrap
        self.horizon = horizon
        self.discount = discount
        self.n_players = len(self.ids)
        self.n_vars = self.n_players * (1 + 2 * horizon)
        self.base_rows: list[tuple[dict[int, float], float, float]] = []
        self._build_constraints()

    def x(self, element: int) -> int:
        return self.at[element]

    def y(self, week: int, element: int) -> int:
        return self.n_players * (1 + week) + self.at[element]

    def c(self, week: int, element: int) -> int:
        return self.n_players * (1 + self.horizon + week) + self.at[element]

    def add(self, values: dict[int, float], low: float = -np.inf, high: float = np.inf) -> None:
        self.base_rows.append((values, low, high))

    def _build_constraints(self) -> None:
        settings = self.bootstrap["game_settings"]
        types = {row["id"]: row for row in self.bootstrap["element_types"]}
        elements = {row["id"]: row for row in self.bootstrap["elements"]}
        self.add({self.x(element): 1 for element in self.ids}, 15, 15)
        self.add({self.x(element): self.costs[element] for element in self.ids}, high=self.budget)
        for type_id, rules in types.items():
            members = [element for element in self.ids if elements[element]["element_type"] == type_id]
            self.add({self.x(element): 1 for element in members}, rules["squad_select"], rules["squad_select"])
        for team in {elements[element]["team"] for element in self.ids}:
            members = [element for element in self.ids if elements[element]["team"] == team]
            self.add({self.x(element): 1 for element in members}, high=settings["squad_team_limit"])
        for week in range(self.horizon):
            self.add({self.y(week, element): 1 for element in self.ids}, 11, 11)
            self.add({self.c(week, element): 1 for element in self.ids}, 1, 1)
            for element in self.ids:
                self.add({self.y(week, element): 1, self.x(element): -1}, high=0)
                self.add({self.c(week, element): 1, self.y(week, element): -1}, high=0)
            for type_id, rules in types.items():
                members = [element for element in self.ids if elements[element]["element_type"] == type_id]
                self.add(
                    {self.y(week, element): 1 for element in members},
                    rules["squad_min_play"], rules["squad_max_play"],
                )

    def solve(self, transfers: int | None, cuts: list[set[int]] | None = None) -> tuple[int, ...]:
        rows = list(self.base_rows)
        if transfers is not None:
            rows.append((
                {self.x(element): 1 for element in self.current},
                15 - transfers, 15 - transfers,
            ))
        for squad in cuts or []:
            rows.append(({self.x(element): 1 for element in squad}, -np.inf, 14))
        row_indices, col_indices, values, lows, highs = [], [], [], [], []
        for row_index, (coefficients, low, high) in enumerate(rows):
            for column, value in coefficients.items():
                row_indices.append(row_index)
                col_indices.append(column)
                values.append(value)
            lows.append(low)
            highs.append(high)
        matrix = coo_matrix(
            (values, (row_indices, col_indices)), shape=(len(rows), self.n_vars)
        ).tocsr()
        objective = np.zeros(self.n_vars)
        # Tiny deterministic squad-depth tiebreak: it cannot materially outweigh XI xP,
        # but prevents HiGHS choosing arbitrary dead bench players among equal optima.
        for element in self.ids:
            depth = sum(
                (self.discount**week) * player_week(self.players[element], week)["xP"]
                for week in range(self.horizon)
            )
            objective[self.x(element)] = -1e-7 * depth
        for week in range(self.horizon):
            weight = self.discount**week
            for element in self.ids:
                xp = player_week(self.players[element], week)["xP"]
                objective[self.y(week, element)] = -weight * xp
                objective[self.c(week, element)] = -weight * xp
        result = milp(
            objective,
            integrality=np.ones(self.n_vars),
            bounds=Bounds(np.zeros(self.n_vars), np.ones(self.n_vars)),
            constraints=LinearConstraint(matrix, np.array(lows), np.array(highs)),
            options={"presolve": True, "mip_rel_gap": 1e-7, "time_limit": 60},
        )
        if not result.success or result.x is None:
            raise RuntimeError(f"squad optimization failed: {result.message}")
        return tuple(element for element in self.ids if result.x[self.x(element)] > 0.5)


def chip_available(name: str, gw: int, bootstrap: dict, history: dict) -> bool:
    return any(
        row["name"] == name and row["start"] <= gw <= row["stop"] and row["played_gw"] is None
        for row in state.chip_windows(bootstrap, history)
    )


def decorate_plan(
    squad: tuple[int, ...], current: set[int], players: dict[int, dict], elements: dict[int, dict],
    sell_prices: dict[int, int], bank: int, free_transfers: int, transfer_cap: int,
    horizon: int, discount: float, play_rules: dict[str, tuple[int, int]], hold_xp: float,
    hold_adjusted_xp: float,
    chip: str | None = None,
) -> dict:
    outgoing = sorted(current - set(squad), key=lambda e: (POSITION_ORDER[players[e]["position"]], players[e]["web_name"]))
    incoming = sorted(set(squad) - current, key=lambda e: (POSITION_ORDER[players[e]["position"]], players[e]["web_name"]))
    cash = bank + sum(sell_prices[e] for e in outgoing) - sum(elements[e]["now_cost"] for e in incoming)
    horizon_xp, adjusted_xp, lineups = score_squad(squad, players, horizon, discount, play_rules)
    transfers = len(outgoing)
    if chip:
        hit = 0
        next_bank = min(transfer_cap, free_transfers + 1)
        lost_stock = 0
    else:
        hit = 4 * max(0, transfers - free_transfers)
        hold_next = min(transfer_cap, free_transfers + 1)
        next_bank = min(transfer_cap, max(0, free_transfers - transfers) + 1)
        lost_stock = hold_next - next_bank
    return {
        "chip": chip,
        "transfer_count": transfers,
        "transfers_out": [
            {"element": e, "name": players[e]["web_name"], "position": players[e]["position"], "selling_price": sell_prices[e]}
            for e in outgoing
        ],
        "transfers_in": [
            {"element": e, "name": players[e]["web_name"], "position": players[e]["position"], "purchase_price": elements[e]["now_cost"]}
            for e in incoming
        ],
        "cash_after": cash,
        "horizon_xP": horizon_xp,
        "availability_adjusted_horizon_xP": adjusted_xp,
        "gain_vs_hold": round(horizon_xp - hold_xp, 3),
        "availability_adjusted_gain_vs_hold": round(adjusted_xp - hold_adjusted_xp, 3),
        "points_hit": hit,
        "gain_after_hits": round(horizon_xp - hold_xp - hit, 3),
        "next_gw_free_transfers": next_bank,
        "free_transfer_stock_used": lost_stock,
        "lineups": lineups,
        "squad": list(squad),
    }


def validate_plan(plan: dict, bootstrap: dict, players: dict[int, dict]) -> None:
    """Fail before publishing a financially or structurally illegal result."""
    squad = plan["squad"]
    if len(squad) != 15 or len(set(squad)) != 15:
        raise RuntimeError("optimizer returned a squad that is not 15 unique players")
    elements = {row["id"]: row for row in bootstrap["elements"]}
    types = {row["singular_name_short"]: row for row in bootstrap["element_types"]}
    for position, rules in types.items():
        count = sum(players[element]["position"] == position for element in squad)
        if count != rules["squad_select"]:
            raise RuntimeError(f"illegal {position} squad count: {count}")
    clubs = defaultdict(int)
    for element in squad:
        clubs[elements[element]["team"]] += 1
    if max(clubs.values()) > bootstrap["game_settings"]["squad_team_limit"]:
        raise RuntimeError("optimizer returned more than the allowed players from one club")
    if plan["cash_after"] < 0:
        raise RuntimeError("optimizer returned an unaffordable squad")
    out_positions = sorted(row["position"] for row in plan["transfers_out"])
    in_positions = sorted(row["position"] for row in plan["transfers_in"])
    if out_positions != in_positions:
        raise RuntimeError("incoming and outgoing transfer positions do not balance")
    for lineup in plan["lineups"]:
        starters, bench = lineup["starters"], lineup["bench"]
        if len(starters) != 11 or len(bench) != 4 or set(starters) | set(bench) != set(squad):
            raise RuntimeError(f"GW{lineup['gw']} XI and bench do not partition the squad")
        if lineup["captain"] not in starters or lineup["vice_captain"] not in starters:
            raise RuntimeError(f"GW{lineup['gw']} captain or vice is not in the XI")
        if players[bench[0]]["position"] != "GKP":
            raise RuntimeError(f"GW{lineup['gw']} first bench slot is not the reserve goalkeeper")
        for position, rules in types.items():
            count = sum(players[element]["position"] == position for element in starters)
            if not rules["squad_min_play"] <= count <= rules["squad_max_play"]:
                raise RuntimeError(f"GW{lineup['gw']} illegal {position} starter count: {count}")


def build(horizon: int = 6, include_chips: bool = True) -> dict:
    bootstrap = load(DATA_DIR / "bootstrap.json")
    projection_payload = load(DATA_DIR / "projections.json")
    if projection_payload["meta"]["horizon"] < horizon:
        projection_payload = projections.build(horizon=horizon)
    players = {int(element): row for element, row in projection_payload["players"].items()}
    if projection_payload["meta"]["horizon"] != horizon:
        # Rebuild rather than silently truncate a differently discounted artifact.
        projection_payload = projections.build(horizon=horizon)
        players = {int(element): row for element, row in projection_payload["players"].items()}
    context = current_context(bootstrap)
    current = set(context["squad"])
    missing = current - players.keys()
    if missing:
        raise SystemExit(f"owned players lack projections: {sorted(missing)}")
    elements = {row["id"]: row for row in bootstrap["elements"]}
    acquisition = acquisition_prices(context["squad"], bootstrap, load(DATA_DIR / "transfers.json"))
    settings = bootstrap["game_settings"]
    sell_prices = {
        element: selling_price(acquisition[element]["purchase_price"], elements[element]["now_cost"], settings)
        for element in current
    }
    total_budget = context["bank"] + sum(sell_prices.values())
    costs = {element: (sell_prices[element] if element in current else elements[element]["now_cost"]) for element in players}
    discount = projection_payload["meta"]["horizon_discount"]
    play_rules = {
        row["singular_name_short"]: (row["squad_min_play"], row["squad_max_play"])
        for row in bootstrap["element_types"] if row["singular_name_short"] != "GKP"
    }
    optimizer = SquadMILP(players, current, costs, total_budget, bootstrap, horizon, discount)
    hold_squad = optimizer.solve(0)
    hold_xp, hold_adjusted_xp, _ = score_squad(hold_squad, players, horizon, discount, play_rules)
    cap = 1 + settings["max_extra_free_transfers"]
    common = (
        current, players, elements, sell_prices, context["bank"], context["free_transfers"],
        cap, horizon, discount, play_rules, hold_xp, hold_adjusted_xp,
    )
    hold = decorate_plan(hold_squad, *common, chip=None)
    transfer_plans = {}
    for transfer_count, count in TOP_BY_TRANSFERS.items():
        cuts: list[set[int]] = []
        plans = []
        for _ in range(count):
            squad = optimizer.solve(transfer_count, cuts)
            cuts.append(set(squad))
            plans.append(decorate_plan(squad, *common, chip=None))
        plans.sort(key=lambda row: row["gain_after_hits"], reverse=True)
        transfer_plans[str(transfer_count)] = plans

    target_gw = projection_payload["meta"]["gw"]
    history = load(DATA_DIR / "history.json")
    chips = {}
    if include_chips and chip_available("freehit", target_gw, bootstrap, history):
        freehit_optimizer = SquadMILP(players, current, costs, total_budget, bootstrap, 1, discount)
        squad = freehit_optimizer.solve(None)
        chips["freehit"] = decorate_plan(
            squad, current, players, elements, sell_prices, context["bank"], context["free_transfers"],
            cap, 1, discount, play_rules,
            hold["lineups"][0]["planned_total_xP"],
            hold["lineups"][0]["availability_adjusted_xP"],
            chip="freehit",
        )
    else:
        chips["freehit"] = {"available": False}
    if include_chips and chip_available("wildcard", target_gw, bootstrap, history):
        squad = optimizer.solve(None)
        chips["wildcard"] = decorate_plan(squad, *common, chip="wildcard")
    else:
        chips["wildcard"] = {"available": False}

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "season": projection_payload["meta"]["season"],
            "gw": target_gw,
            "horizon": horizon,
            "horizon_discount": discount,
            "objective": "discounted expected FPL points; prices constrain feasibility only",
            "future_transfers": "none; resulting squad held through horizon",
            "candidate_players": len(players),
            "excluded_players": len(bootstrap["elements"]) - len(players),
            "optimizer": "SciPy MILP/HiGHS; exact planned-XI/captain objective with a 1e-7 squad-depth tiebreak",
            "availability_adjustment": "vice fallback plus FPL-style autosub expectation for the displayed squad under independent appearances; reported separately and excluded from rankings",
            "uncertainty_policy": "marginal leads default to hold; no measured decision margin available yet",
        },
        "current": {
            "squad": context["squad"],
            "bank": context["bank"],
            "free_transfers": context["free_transfers"],
            "selling_budget": total_budget,
            "prices": {
                str(element): {
                    "name": elements[element]["web_name"],
                    "current_price": elements[element]["now_cost"],
                    "purchase_price": acquisition[element]["purchase_price"],
                    "selling_price": sell_prices[element],
                    "purchase_price_source": acquisition[element]["source"],
                }
                for element in context["squad"]
            },
            "warning": "public picks reflect the last deadline squad; post-deadline app transfers are invisible",
        },
        "hold": hold,
        "transfers": transfer_plans,
        "chips": chips,
        "limitations": [
            "candidate pool excludes players the minutes model marks insufficient evidence",
            "autosub appearance events are treated as independent",
            "vice/autosub coverage is a sensitivity, not part of the primary squad ranking",
            "no monetary reward for team value, cash left over or projected price profit",
            "chip preservation value is not estimated; displaying a chip squad is not a play-chip recommendation",
        ],
    }
    validate_plan(hold, bootstrap, players)
    for plans in transfer_plans.values():
        for plan in plans:
            validate_plan(plan, bootstrap, players)
    for plan in chips.values():
        if plan.get("available") is not False:
            validate_plan(plan, bootstrap, players)
    OUT.write_text(json.dumps(payload, indent=2) + "\n")
    return payload


def money(value: int) -> str:
    return f"£{value / 10:.1f}m"


def names(ids: list[int], players: dict[int, dict]) -> str:
    return ", ".join(players[element]["web_name"] for element in ids)


def print_plan(label: str, plan: dict, players: dict[int, dict], details: bool = False) -> None:
    moves = "hold"
    if plan["transfers_out"]:
        groups = []
        for position in POSITION_ORDER:
            outgoing = [row["name"] for row in plan["transfers_out"] if row["position"] == position]
            incoming = [row["name"] for row in plan["transfers_in"] if row["position"] == position]
            if outgoing:
                groups.append(f"{position}: {', '.join(outgoing)} -> {', '.join(incoming)}")
        moves = "; ".join(groups)
    availability_delta = plan["availability_adjusted_horizon_xP"] - plan["horizon_xP"]
    print(
        f"{label:<16} {plan['horizon_xP']:>7.2f} xP  "
        f"gain {plan['gain_vs_hold']:+6.2f}  hit -{plan['points_hit']}  "
        f"after hit {plan['gain_after_hits']:+6.2f}  cash {money(plan['cash_after'])}  "
        f"cover +{availability_delta:.2f}"
    )
    print(f"  {moves} | next FT {plan['next_gw_free_transfers']} (stock used {plan['free_transfer_stock_used']})")
    for lineup in plan["lineups"]:
        print(
            f"  GW{lineup['gw']} {lineup['formation']}  C {players[lineup['captain']]['web_name']}  "
            f"VC {players[lineup['vice_captain']]['web_name']}  "
            f"XI {lineup['starting_xP']:.2f} + C {lineup['captain_bonus_xP']:.2f} "
            f"= {lineup['planned_total_xP']:.2f}  "
            f"[VC {lineup['vice_fallback_xP']:.2f} + subs {lineup['autosub_xP']:.2f}]"
        )
        if details:
            print(f"    XI: {names(lineup['starters'], players)}")
            print(f"    Bench: {names(lineup['bench'], players)}")


def print_report(payload: dict, details: bool = False) -> None:
    players = {
        int(element): row for element, row in load(DATA_DIR / "projections.json")["players"].items()
    }
    meta = payload["meta"]
    current = payload["current"]
    print(
        f"GW{meta['gw']} decision search — {meta['horizon']}-GW horizon | "
        f"bank {money(current['bank'])} | {current['free_transfers']} free transfers"
    )
    print("Prices constrain legality; cash/team value earn no projected points.\n")
    print_plan("HOLD", payload["hold"], players, details)
    for transfer_count in range(1, 6):
        for rank, plan in enumerate(payload["transfers"][str(transfer_count)], 1):
            print_plan(f"{transfer_count} transfer #{rank}", plan, players, details)
    for chip, plan in payload["chips"].items():
        if plan.get("available") is False:
            continue
        print_plan(chip.upper(), plan, players, details)
    print("\nNo calibrated robustness margin yet: treat raw leaders as comparisons, not automatic actions.")
    print(f"Full audit: {OUT.relative_to(ROOT)}")


def archive(payload: dict) -> None:
    path = ARCHIVE_DIR / f"gw{payload['meta']['gw']:02d}.json"
    display_path = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    if path.exists():
        print(f"{display_path} already exists — not overwriting")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")) + "\n")
    print(f"froze decision search to {display_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, default=6)
    parser.add_argument("--no-chips", action="store_true")
    parser.add_argument("--details", action="store_true", help="show every projected XI and bench")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("archive", help="freeze this pre-deadline decision search")
    args = parser.parse_args()
    if not 1 <= args.horizon <= 10:
        raise SystemExit("--horizon must be between 1 and 10")
    payload = build(args.horizon, include_chips=not args.no_chips)
    print_report(payload, details=args.details)
    if args.command == "archive":
        archive(payload)


if __name__ == "__main__":
    main()
