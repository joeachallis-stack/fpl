"""Persist and evaluate authored multi-gameweek FPL plans.

Plans are hypotheses, not recommendations and not FPL account state.  This module keeps
the authored sequence (transfers, wildcard and parked ideas) in ``plans/drafts.json`` and
re-scores it against the current canonical projection artifact on demand.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decisions
import state

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
PLANS_FILE = ROOT / "plans" / "drafts.json"
SCHEMA_VERSION = "fpl-plans-v1"
ID_PATTERN = re.compile(r"^[a-z0-9-]{1,80}$")


class PlanError(ValueError):
    """A user-editable plan is invalid or cannot be evaluated."""


def _load(path: Path) -> dict | list:
    return json.loads(path.read_text())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _plan_store(path: Path = PLANS_FILE) -> dict:
    if not path.exists():
        return {"schemaVersion": SCHEMA_VERSION, "plans": []}
    payload = _load(path)
    if payload.get("schemaVersion") != SCHEMA_VERSION or not isinstance(payload.get("plans"), list):
        raise PlanError("Saved plan file has an unsupported schema.")
    return payload


def list_plans(path: Path = PLANS_FILE) -> list[dict]:
    return sorted(_plan_store(path)["plans"], key=lambda row: row.get("updatedAt", ""), reverse=True)


def normalize_plan(raw: dict, *, assign_id: bool = False) -> dict:
    name = str(raw.get("name", "")).strip()[:80]
    if not name:
        raise PlanError("Give this draft a name before saving it.")
    plan_id = raw.get("id")
    if assign_id and not plan_id:
        plan_id = f"draft-{uuid.uuid4().hex[:12]}"
    if plan_id is not None and (not isinstance(plan_id, str) or not ID_PATTERN.fullmatch(plan_id)):
        raise PlanError("Plan id contains unsupported characters.")

    events = []
    seen_weeks: set[int] = set()
    for raw_event in raw.get("events", []):
        gw = int(raw_event.get("gw", 0))
        if gw in seen_weeks:
            raise PlanError(f"GW{gw} appears more than once in this plan.")
        seen_weeks.add(gw)
        chip = raw_event.get("chip") or None
        if chip not in {None, "wildcard"}:
            raise PlanError("Plan Ahead currently supports ordinary transfers and Wildcard.")
        transfers = []
        for move in raw_event.get("transfers", []):
            outgoing, incoming = int(move.get("out", 0)), int(move.get("in", 0))
            if outgoing <= 0 or incoming <= 0 or outgoing == incoming:
                raise PlanError(f"GW{gw} contains an invalid transfer.")
            transfers.append({"out": outgoing, "in": incoming})
        if transfers or chip:
            events.append({"gw": gw, "chip": chip, "transfers": transfers})

    ideas = []
    for raw_idea in raw.get("ideas", [])[:100]:
        text = str(raw_idea.get("text", "")).strip()[:300]
        if not text:
            continue
        idea_id = str(raw_idea.get("id") or f"idea-{uuid.uuid4().hex[:10]}")
        if not ID_PATTERN.fullmatch(idea_id):
            idea_id = f"idea-{uuid.uuid4().hex[:10]}"
        raw_gw = raw_idea.get("gw")
        ideas.append({"id": idea_id, "gw": int(raw_gw) if raw_gw else None, "text": text})

    return {
        "id": plan_id,
        "name": name,
        "baseGw": int(raw.get("baseGw", 0)),
        "baseAnalysisRunId": str(raw.get("baseAnalysisRunId", ""))[:100],
        "events": sorted(events, key=lambda row: row["gw"]),
        "ideas": ideas,
    }


def _validate_squad(squad: list[int], players: dict[int, dict], bootstrap: dict) -> None:
    if len(squad) != 15 or len(set(squad)) != 15:
        raise PlanError("A planned squad must contain 15 different players.")
    elements = {row["id"]: row for row in bootstrap["elements"]}
    types = {row["singular_name_short"]: row["squad_select"] for row in bootstrap["element_types"]}
    actual = Counter(players[element]["position"] for element in squad)
    if any(actual[position] != count for position, count in types.items()):
        raise PlanError("The planned squad has an illegal position balance.")
    clubs = Counter(elements[element]["team"] for element in squad)
    if clubs and max(clubs.values()) > bootstrap["game_settings"]["squad_team_limit"]:
        raise PlanError("That move would exceed the players-per-club limit.")


def _chip_is_available(gw: int, bootstrap: dict, history: dict) -> bool:
    return any(
        row["name"] == "wildcard"
        and row["start"] <= gw <= row["stop"]
        and row["played_gw"] is None
        for row in state.chip_windows(bootstrap, history)
    )


def evaluate_plan(raw: dict) -> dict:
    plan = normalize_plan(raw)
    bootstrap = _load(DATA / "bootstrap.json")
    projection_payload = _load(DATA / "projections.json")
    players = decisions.live_optimizer_players(projection_payload)
    context = decisions.current_context(bootstrap)
    elements = {row["id"]: row for row in bootstrap["elements"]}
    history = _load(DATA / "history.json")
    acquisition = decisions.acquisition_prices(
        context["squad"], bootstrap, _load(DATA / "transfers.json")
    )
    settings = bootstrap["game_settings"]
    target_gw = int(projection_payload["meta"]["gw"])
    horizon = int(projection_payload["meta"]["horizon"])
    weeks = list(range(target_gw, target_gw + horizon))
    if plan["baseGw"] > target_gw:
        raise PlanError(
            f"This draft starts at GW{plan['baseGw']}, but the current forecast starts at GW{target_gw}."
        )
    past_events = [event for event in plan["events"] if event["gw"] < target_gw]
    for event in plan["events"]:
        if event["gw"] > weeks[-1]:
            raise PlanError(f"GW{event['gw']} is outside the current GW{weeks[0]}–GW{weeks[-1]} forecast.")
    if sum(event["chip"] == "wildcard" for event in plan["events"]) > 1:
        raise PlanError("A draft can schedule only one Wildcard in this forecast window.")

    missing = set(context["squad"]) - players.keys()
    if missing:
        raise PlanError(f"Owned players lack projections: {sorted(missing)}")
    play_rules = {
        row["singular_name_short"]: (row["squad_min_play"], row["squad_max_play"])
        for row in bootstrap["element_types"]
        if row["singular_name_short"] != "GKP"
    }
    cap = 1 + int(settings["max_extra_free_transfers"])
    discount = float(projection_payload["meta"]["horizon_discount"])
    squad = list(context["squad"])
    bank = int(context["bank"])
    free_transfers = int(context["free_transfers"])
    purchase_prices = {element: row["purchase_price"] for element, row in acquisition.items()}
    events_by_week = {event["gw"]: event for event in plan["events"] if event["gw"] >= target_gw}
    timeline = []
    total_hits = 0
    raw_xp = 0.0
    discounted_xp = 0.0
    hold_discounted_xp = 0.0

    for index, gw in enumerate(weeks):
        event = events_by_week.get(gw, {"gw": gw, "chip": None, "transfers": []})
        wildcard = event["chip"] == "wildcard"
        if wildcard and not _chip_is_available(gw, bootstrap, history):
            raise PlanError(f"Wildcard is not available in GW{gw} under the live chip windows.")
        transfers_before = free_transfers
        move_views = []
        for move in event["transfers"]:
            outgoing, incoming = move["out"], move["in"]
            if outgoing not in squad:
                raise PlanError(f"GW{gw}: the outgoing player is no longer in this draft's squad.")
            if incoming in squad:
                raise PlanError(f"GW{gw}: the incoming player is already in this draft's squad.")
            if outgoing not in players or incoming not in players:
                raise PlanError(f"GW{gw}: a transfer target lacks a current projection.")
            if players[outgoing]["position"] != players[incoming]["position"]:
                raise PlanError(f"GW{gw}: transfers must replace the same position.")
            sale = decisions.selling_price(
                purchase_prices[outgoing], elements[outgoing]["now_cost"], settings
            )
            purchase = int(elements[incoming]["now_cost"])
            if bank + sale - purchase < 0:
                raise PlanError(
                    f"GW{gw}: {players[incoming]['web_name']} is unaffordable at current prices."
                )
            bank += sale - purchase
            squad[squad.index(outgoing)] = incoming
            purchase_prices.pop(outgoing)
            purchase_prices[incoming] = purchase
            move_views.append(
                {
                    "out": outgoing,
                    "outName": players[outgoing]["web_name"],
                    "in": incoming,
                    "inName": players[incoming]["web_name"],
                    "position": players[incoming]["position"],
                    "salePrice": sale,
                    "purchasePrice": purchase,
                }
            )
        _validate_squad(squad, players, bootstrap)
        transfer_count = len(move_views)
        hit = 0 if wildcard else 4 * max(0, transfer_count - free_transfers)
        if not wildcard:
            free_transfers = max(0, free_transfers - transfer_count)
        free_transfers = min(cap, free_transfers + 1)
        total_hits += hit
        lineup = decisions.best_lineup(tuple(squad), players, index, play_rules)
        hold_lineup = decisions.best_lineup(tuple(context["squad"]), players, index, play_rules)
        weekly_xp = float(lineup["planned_total_xP"])
        raw_xp += weekly_xp
        discounted_xp += (discount**index) * weekly_xp
        hold_discounted_xp += (discount**index) * float(hold_lineup["planned_total_xP"])
        timeline.append(
            {
                "gw": gw,
                "chip": event["chip"],
                "transfers": move_views,
                "freeTransfersBefore": transfers_before,
                "freeTransfersAfter": free_transfers,
                "hit": hit,
                "cash": bank,
                "squad": list(squad),
                "lineup": {
                    "gw": lineup["gw"],
                    "formation": lineup["formation"],
                    "starters": lineup["starters"],
                    "captain": lineup["captain"],
                    "viceCaptain": lineup["vice_captain"],
                    "bench": lineup["bench"],
                    "plannedXP": lineup["planned_total_xP"],
                    "availabilityAdjustedXP": lineup["availability_adjusted_xP"],
                    "source": lineup["source"],
                },
            }
        )

    return {
        "plan": plan,
        "evaluatedAt": _now(),
        "forecastStartGw": target_gw,
        "forecastEndGw": weeks[-1],
        "weeks": timeline,
        "rawXP": round(raw_xp, 3),
        "discountedXP": round(discounted_xp, 3),
        "totalHits": total_hits,
        "netXP": round(discounted_xp - total_hits, 3),
        "edgeVsHold": round(discounted_xp - total_hits - hold_discounted_xp, 3),
        "assumptions": [
            "Current player prices are held constant across the forecast.",
            f"Future xP is discounted by {discount:.2f} per gameweek.",
            "Every week's XI, captain, vice and bench are selected by the Python model.",
            "A saved draft is a planning hypothesis, not a recommendation or submitted FPL team.",
        ] + ([f"{len(past_events)} past plan event(s) were not replayed; the current official squad is the new starting point."] if past_events else []),
    }


def save_plan(raw: dict, path: Path = PLANS_FILE) -> tuple[dict, dict]:
    plan = normalize_plan(raw, assign_id=True)
    evaluation = evaluate_plan(plan)
    store = _plan_store(path)
    now = _now()
    existing = next((row for row in store["plans"] if row.get("id") == plan["id"]), None)
    saved = {
        **plan,
        "createdAt": existing.get("createdAt", now) if existing else now,
        "updatedAt": now,
        "lastEvaluation": {
            "analysisRunId": plan["baseAnalysisRunId"],
            "evaluatedAt": evaluation["evaluatedAt"],
            "netXP": evaluation["netXP"],
            "edgeVsHold": evaluation["edgeVsHold"],
        },
    }
    store["plans"] = [row for row in store["plans"] if row.get("id") != plan["id"]]
    store["plans"].append(saved)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(store, indent=2) + "\n")
    temporary.replace(path)
    return saved, evaluation
