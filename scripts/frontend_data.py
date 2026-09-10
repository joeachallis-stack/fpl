"""Build the read-only view model consumed by the local FPL decision room.

This module is deliberately an adapter, not a second model. It joins the existing
official, minutes, projection, decision, creator and journal artifacts into one coherent
payload. Live-decision routes are recursively stripped of evaluation-only shadow fields.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import findings as findings_schema  # noqa: E402  (needs the path line above)
import prices as prices_module  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VIEW_MODEL_VERSION = "decision-room-v1"


class AnalysisInputError(RuntimeError):
    """Raised when the adapter cannot construct one coherent analysis run."""


def load_json(path: Path) -> Any:
    if not path.exists():
        raise AnalysisInputError(f"Missing {path.relative_to(ROOT)}. Run scripts/fetch_data.py.")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise AnalysisInputError(f"Invalid JSON in {path.relative_to(ROOT)}: {exc}") from exc


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for number, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AnalysisInputError(
                f"Invalid JSON on line {number} of {path.relative_to(ROOT)}"
            ) from exc
    return rows


def live_only(value: Any) -> Any:
    """Remove evaluation-only fields from anything sent to a live-decision screen."""
    if isinstance(value, dict):
        return {
            key: live_only(item)
            for key, item in value.items()
            if not str(key).startswith("shadow_")
        }
    if isinstance(value, list):
        return [live_only(item) for item in value]
    return value


def _iso_mtime(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _week_projection(player: dict, gw: int) -> dict | None:
    return next((row for row in player.get("gameweeks", []) if row.get("gw") == gw), None)


def _discounted_plan_score(plan: dict, weeks: int, discount: float) -> float:
    return round(
        sum(
            float(row.get("planned_total_xP", 0)) * discount**index
            for index, row in enumerate(plan.get("lineups", [])[:weeks])
        ),
        3,
    )


def _plan_label(plan: dict) -> str:
    if not plan.get("transfers_out"):
        return "Hold"
    incoming = ", ".join(row["name"] for row in plan["transfers_in"])
    outgoing = ", ".join(row["name"] for row in plan["transfers_out"])
    return f"{outgoing} → {incoming}"


def _plan_hinge(plan: dict, projections: dict[str, dict], discount: float) -> list[dict]:
    outgoing = plan.get("transfers_out", [])
    incoming = plan.get("transfers_in", [])
    rows = []
    for index, new in enumerate(incoming):
        old = outgoing[index] if index < len(outgoing) else None
        new_projection = projections.get(str(new["element"]), {})
        old_projection = projections.get(str(old["element"]), {}) if old else {}
        by_week = []
        for week_index, new_week in enumerate(new_projection.get("gameweeks", [])[:6]):
            gw = new_week.get("gw")
            old_week = _week_projection(old_projection, gw) or {}
            delta = float(new_week.get("xP", 0)) - float(old_week.get("xP", 0))
            by_week.append(
                {
                    "gw": gw,
                    "delta": round(delta, 2),
                    "source": new_week.get("source", "unknown"),
                }
            )
        rows.append(
            {
                "label": f"{old['name'] if old else 'Open slot'} → {new['name']}",
                "twoWeekDelta": round(sum(r["delta"] * discount**i for i, r in enumerate(by_week[:2])), 2),
                "sixWeekDelta": round(sum(r["delta"] * discount**i for i, r in enumerate(by_week)), 2),
                "byWeek": by_week,
            }
        )
    return rows


def _player_view(
    element_id: int,
    elements: dict[int, dict],
    projections: dict[str, dict],
    team_names: dict[int, dict],
    target_gw: int,
) -> dict:
    element = elements[element_id]
    projection = live_only(projections.get(str(element_id), {}))
    week = _week_projection(projection, target_gw) or {}
    fixture = (week.get("fixtures") or [{}])[0]
    duty_changes = projection.get("attacking_inputs", {}).get("set_piece_duty_changes", [])
    chance = element.get("chance_of_playing_next_round")
    warnings = []
    if element.get("news"):
        warnings.append(element["news"])
    if chance is not None and chance < 100:
        warnings.append(f"{chance}% chance of playing")
    if duty_changes:
        warnings.append("Recent set-piece duty change")
    return {
        "id": element_id,
        "name": element.get("web_name", str(element_id)),
        "fullName": f"{element.get('first_name', '')} {element.get('second_name', '')}".strip(),
        "teamId": element["team"],
        "team": team_names[element["team"]]["name"],
        "teamShort": team_names[element["team"]]["short_name"],
        "position": projection.get("position") or str(element.get("element_type")),
        "opponent": fixture.get("opponent", projection.get("opponent", "—")),
        "home": fixture.get("home", projection.get("home")),
        "expectedMinutes": projection.get("exp_minutes"),
        "minutesBands": projection.get("minutes_bands"),
        "gameweekXP": week.get("xP", projection.get("xP")),
        "price": element.get("now_cost"),
        "status": element.get("status", "a"),
        "news": element.get("news") or None,
        "warnings": warnings,
        "components": week.get("components", projection.get("components", {})),
        "setPieceDutyChanges": duty_changes,
    }


def _lineup_view(lineup: dict) -> dict:
    return {
        "gw": lineup["gw"],
        "formation": lineup["formation"],
        "starters": lineup["starters"],
        "captain": lineup["captain"],
        "viceCaptain": lineup["vice_captain"],
        "bench": lineup["bench"],
        "plannedXP": lineup["planned_total_xP"],
        "availabilityAdjustedXP": lineup["availability_adjusted_xP"],
        "source": lineup["source"],
    }


def _plan_view(
    plan: dict,
    plan_id: str,
    hold: dict,
    projections: dict[str, dict],
    discount: float,
) -> dict:
    two_score = _discounted_plan_score(plan, 2, discount)
    hold_two = _discounted_plan_score(hold, 2, discount)
    two_edge = round(two_score - hold_two - float(plan.get("points_hit", 0)), 2)
    six_edge = round(float(plan.get("gain_after_hits", 0)), 2)
    stability = _stability(plan_id, two_edge, six_edge)
    return {
        "id": plan_id,
        "label": _plan_label(plan),
        "state": "last_official" if plan_id == "hold" else "selected_scenario",
        "transferCount": plan.get("transfer_count", 0),
        "transfersOut": plan.get("transfers_out", []),
        "transfersIn": plan.get("transfers_in", []),
        "cashAfter": plan.get("cash_after"),
        "pointsHit": plan.get("points_hit", 0),
        "nextFreeTransfers": plan.get("next_gw_free_transfers"),
        "twoWeekEdge": two_edge,
        "sixWeekEdge": six_edge,
        "sixWeekXP": plan.get("horizon_xP"),
        "stability": stability,
        "lineup": _lineup_view(plan["lineups"][0]),
        "squad": plan["squad"],
        "hinge": _plan_hinge(plan, projections, discount),
    }


def _stability(plan_id: str, two_edge: float, six_edge: float) -> str:
    if plan_id == "hold":
        return "Baseline"
    if (two_edge > 0) != (six_edge > 0):
        return "Material flip"
    if abs(six_edge - two_edge) >= 4:
        return "Tail-sensitive"
    return "Stable leader"


def _load_independent_comparison(target_gw: int) -> dict | None:
    """Use the optional comparison only while it matches the canonical artifacts."""
    path = DATA / "horizon_comparison.json"
    if not path.exists():
        return None
    try:
        payload = load_json(path)
    except AnalysisInputError:
        return None
    meta = payload.get("meta", {})
    if (
        payload.get("schemaVersion") != "horizon-comparison-v1"
        or meta.get("targetGw") != target_gw
        or meta.get("horizons") != [2, 6]
        or meta.get("canonicalProjectionsSha256") != _sha256(DATA / "projections.json")
        or meta.get("canonicalDecisionsSha256") != _sha256(DATA / "decisions.json")
    ):
        return None
    return live_only(payload)


def _independent_plan_view(candidate: dict, projections: dict[str, dict], discount: float) -> dict:
    plan = candidate["plan"]
    plan_id = candidate["id"]
    two = candidate["scores"]["2"]
    six = candidate["scores"]["6"]
    two_edge = round(float(two["gain_after_hits"]), 2)
    six_edge = round(float(six["gain_after_hits"]), 2)
    return {
        "id": plan_id,
        "label": _plan_label(plan),
        "state": "last_official" if plan_id == "hold" else "selected_scenario",
        "transferCount": plan.get("transfer_count", 0),
        "transfersOut": plan.get("transfers_out", []),
        "transfersIn": plan.get("transfers_in", []),
        "cashAfter": plan.get("cash_after"),
        "pointsHit": plan.get("points_hit", 0),
        "nextFreeTransfers": plan.get("next_gw_free_transfers"),
        "twoWeekEdge": two_edge,
        "sixWeekEdge": six_edge,
        "sixWeekXP": six.get("horizon_xP"),
        "stability": _stability(plan_id, two_edge, six_edge),
        "lineup": _lineup_view(six["lineups"][0]),
        "squad": plan["squad"],
        "hinge": _plan_hinge(plan, projections, discount),
        "sourceHorizons": candidate.get("sourceHorizons", []),
    }


def _fixture_wall(
    bootstrap: dict, fixtures: list[dict], projections: dict[str, dict], owned: set[int]
) -> dict:
    teams = {row["id"]: row for row in bootstrap["teams"]}
    forecast_by_fixture: dict[tuple[int, str], dict] = {}
    for player in projections.values():
        for week in player.get("gameweeks", []):
            for fixture in week.get("fixtures", []):
                forecast_by_fixture.setdefault(
                    (fixture["fixture_id"], player["team"]),
                    {
                        "source": fixture.get("source"),
                        "attack": fixture.get("team_goal_lambda"),
                        "cleanSheet": round(math.exp(-float(fixture.get("opponent_goal_lambda", 0))), 3),
                    },
                )
    fixture_rows: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for fixture in fixtures:
        gw = fixture.get("event")
        if not gw:
            continue
        for team_id, opponent_id, home in (
            (fixture["team_h"], fixture["team_a"], True),
            (fixture["team_a"], fixture["team_h"], False),
        ):
            forecast = forecast_by_fixture.get((fixture["id"], teams[team_id]["name"]), {})
            score = None
            if fixture.get("team_h_score") is not None:
                own_score = fixture["team_h_score"] if home else fixture["team_a_score"]
                opp_score = fixture["team_a_score"] if home else fixture["team_h_score"]
                score = f"{own_score}–{opp_score}"
            fixture_rows[(team_id, gw)].append(
                {
                    "fixtureId": fixture["id"],
                    "opponent": teams[opponent_id]["name"],
                    "opponentShort": teams[opponent_id]["short_name"],
                    "home": home,
                    "kickoff": fixture.get("kickoff_time"),
                    "finished": bool(fixture.get("finished") or fixture.get("finished_provisional")),
                    "score": score,
                    "postponed": fixture.get("kickoff_time") is None,
                    **forecast,
                }
            )
    rows = []
    for team in sorted(teams.values(), key=lambda row: row["id"]):
        rows.append(
            {
                "teamId": team["id"],
                "name": team["name"],
                "shortName": team["short_name"],
                "owned": team["id"] in owned,
                "gameweeks": [
                    {"gw": gw, "fixtures": fixture_rows.get((team["id"], gw), [])}
                    for gw in range(1, 39)
                ],
            }
        )
    return {"rows": rows, "gameweeks": list(range(1, 39))}


# How firmly a claim was asserted, as a weight on its stance. A passing remark and a
# strongly argued case should not count the same in a consensus.
CONVICTION_WEIGHT = {"strong": 1.0, "moderate": 0.6, "passing": 0.3}
STANCE_SIGN = {"positive": 1.0, "negative": -1.0, "neutral": 0.0}

# What the model structurally cannot produce for itself ranks highest. A cited statistic
# is usually a number `projections.py` already computes, so it is kept as a cross-check
# rather than as news.
KIND_VALUE = {"news": 3, "read": 2, "recommendation": 1, "action": 1, "stat": 0}

CHIP_PATTERNS = {
    "Wildcard": r"wildcard|\bwc\b",
    "Free Hit": r"free.?hit",
    "Bench Boost": r"bench.?boost",
    "Triple Captain": r"triple.?captain|\btc\b",
}

# Above this gap between creator consensus and the model's own ranking, the row is worth
# looking at whichever way it points. Not a threshold for action — a threshold for reading.
DISAGREEMENT_FLAG = 0.8


def _load_findings(target_gw: int) -> tuple[list[dict], str, int]:
    """Delegated to `findings.py` so the adapter and the CLI brief can never disagree
    about which files count. A naive glob matches a batch and its migrated twin."""
    paths = findings_schema.paths(target_gw)
    schema = "v2" if any(p.name.endswith(".v2.jsonl") for p in paths) else "legacy"
    return findings_schema.load(target_gw), schema, len(paths)


def _finding_view(finding: dict) -> dict:
    return {
        "creator": finding.get("source"),
        "published": finding.get("published"),
        "topic": finding.get("topic") or finding.get("category"),
        "kind": finding.get("kind"),
        "horizon": finding.get("horizon"),
        "stance": finding.get("stance", "neutral"),
        "conviction": finding.get("conviction"),
        "claim": finding.get("claim"),
        "quote": finding.get("quote"),
        "videoId": finding.get("video_id"),
        "players": finding.get("players", []),
        "teams": finding.get("teams", []),
        "inferred": finding.get("inferred", []),
    }


def _stance_weight(finding: dict) -> float:
    sign = STANCE_SIGN.get(finding.get("stance", "neutral"), 0.0)
    return sign * CONVICTION_WEIGHT.get(finding.get("conviction"), 0.6)


def _player_index(elements: dict, teams: dict) -> dict[tuple[str, str], int]:
    """Keyed by (web name, team name), because display names collide — there are two
    Palmers. A finding's `players` entry carries the team, so the collision is decidable."""
    index: dict[tuple[str, str], int] = {}
    for element_id, element in elements.items():
        team = teams.get(element["team"], {}).get("name", "")
        index[(element.get("web_name", ""), team)] = element_id
    return index


def _resolve_finding_player(entry: str, index: dict, elements: dict) -> int | None:
    name, _, rest = entry.partition(" (")
    team = rest.split(",")[0].strip() if rest else ""
    if (name, team) in index:
        return index[(name, team)]
    matches = [pid for (pname, _team), pid in index.items() if pname == name]
    return matches[0] if len(matches) == 1 else None


def _model_signal(projections: dict, elements: dict) -> dict[int, float]:
    """Each player's six-week outlook as a percentile within their own position,
    rescaled to [-1, 1] so it is directly comparable with creator consensus."""
    by_position: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for raw_id, projection in projections.items():
        horizon = projection.get("horizon_xP")
        if horizon is None:
            continue
        by_position[projection.get("position", "?")].append((int(raw_id), float(horizon)))
    signal: dict[int, float] = {}
    for rows in by_position.values():
        rows.sort(key=lambda row: row[1])
        last = len(rows) - 1
        for rank, (player_id, _xp) in enumerate(rows):
            signal[player_id] = 2.0 * (rank / last) - 1.0 if last else 0.0
    return signal


def _expert_player_rows(
    findings: list[dict],
    elements: dict,
    teams: dict,
    projections: dict,
    owned: set[int],
    target_gw: int,
    corpus_creators: int,
) -> list[dict]:
    index = _player_index(elements, teams)
    signal = _model_signal(projections, elements)
    grouped: dict[int, list[dict]] = defaultdict(list)
    for finding in findings:
        for entry in finding.get("players", []):
            player_id = _resolve_finding_player(entry, index, elements)
            if player_id is not None:
                grouped[player_id].append(finding)
    # Midweek football is shown, never scored. The FPL API cannot see a cup appearance at
    # all, so a player who went 90 minutes in a Carabao tie looks identical to one who
    # rested. That is a real risk to his next league start and the model has no way to
    # know it — so it is surfaced beside the projection rather than folded into it.
    # FPL's own price-change projections. These earn no points and must never reach the
    # optimizer — decisions.py is right to treat price as a feasibility constraint only.
    # They change what the same plan costs to execute, which is worth seeing before
    # pressing the button rather than after.
    price = prices_module.by_element()
    midweek: dict[int, list[dict]] = defaultdict(list)
    for finding in findings_schema.midweek_findings(findings):
        for entry in finding.get("players", []):
            player_id = _resolve_finding_player(entry, index, elements)
            if player_id is not None:
                midweek[player_id].append(finding)

    rows = []
    for player_id, group in grouped.items():
        element = elements.get(player_id)
        if element is None:
            continue
        projection = projections.get(str(player_id), {})
        week = _week_projection(projection, target_gw) or {}
        weights = [_stance_weight(f) for f in group]
        magnitude = sum(abs(w) for w in weights)
        net = sum(weights) / magnitude if magnitude else 0.0
        # One creator saying something once is not the same evidence as two creators
        # agreeing, but a raw net stance saturates at 1.0 for both. Scaling by how many
        # of the available creators actually spoke keeps a single passing mention from
        # outranking real agreement.
        speakers = len({f.get("source") for f in group})
        support = speakers / corpus_creators if corpus_creators else 0.0
        consensus = net * min(1.0, support)
        model = signal.get(player_id, 0.0)
        counts = Counter(f.get("stance", "neutral") for f in group)
        sharpest = max(group, key=lambda f: (
            abs(_stance_weight(f)), KIND_VALUE.get(f.get("kind"), 0)))
        rows.append({
            "id": player_id,
            "name": element.get("web_name"),
            "team": teams.get(element["team"], {}).get("short_name"),
            "position": projection.get("position") or "?",
            "price": element.get("now_cost"),
            "owned": player_id in owned,
            "status": element.get("status", "a"),
            "news": element.get("news") or None,
            "positive": counts.get("positive", 0),
            "negative": counts.get("negative", 0),
            "neutral": counts.get("neutral", 0),
            "mentions": len(group),
            "creators": len({f.get("source") for f in group}),
            "netStance": round(net, 3),
            "support": round(min(1.0, support), 3),
            "consensus": round(consensus, 3),
            "modelSignal": round(model, 3),
            "disagreement": round(consensus - model, 3),
            "disagrees": abs(consensus - model) >= DISAGREEMENT_FLAG,
            "gameweekXP": week.get("xP", projection.get("xP")),
            "horizonXP": projection.get("horizon_xP"),
            "expectedMinutes": projection.get("exp_minutes"),
            "priceOutlook": price.get(player_id),
            "midweek": [_finding_view(f) for f in midweek.get(player_id, [])],
            "topClaim": _finding_view(sharpest),
            "findings": [_finding_view(f) for f in sorted(
                group, key=lambda f: (-KIND_VALUE.get(f.get("kind"), 0),
                                      -abs(_stance_weight(f))))],
        })
    return rows


def _expert_room(
    target_gw: int,
    elements: dict,
    teams: dict,
    projections: dict,
    owned: set[int],
    bank: float,
) -> dict:
    findings, schema, file_count = _load_findings(target_gw)
    if not findings:
        return {
            "targetGw": target_gw,
            "state": "empty",
            "emptyMessage": f"No GW{target_gw} creator findings have been extracted yet.",
            "corpus": {"findings": 0, "creators": 0, "videos": 0, "files": 0},
            "sections": {},
        }

    corpus_creators = len({f.get("source") for f in findings})
    rows = _expert_player_rows(
        findings, elements, teams, projections, owned, target_gw, corpus_creators)
    by_id = {row["id"]: row for row in rows}
    # An owned player nobody mentioned still belongs in the squad table. Silence about a
    # starter is a fact about the week, and dropping the row hides it.
    signal = _model_signal(projections, elements)
    price = prices_module.by_element()
    for player_id in owned - set(by_id):
        element = elements.get(player_id)
        if element is None:
            continue
        projection = projections.get(str(player_id), {})
        week = _week_projection(projection, target_gw) or {}
        row = {
            "id": player_id,
            "name": element.get("web_name"),
            "team": teams.get(element["team"], {}).get("short_name"),
            "position": projection.get("position") or "?",
            "price": element.get("now_cost"),
            "owned": True,
            "status": element.get("status", "a"),
            "news": element.get("news") or None,
            "positive": 0, "negative": 0, "neutral": 0,
            "mentions": 0, "creators": 0,
            "netStance": 0.0, "support": 0.0, "consensus": 0.0,
            "modelSignal": round(signal.get(player_id, 0.0), 3),
            "disagreement": 0.0,
            "disagrees": False,
            "gameweekXP": week.get("xP", projection.get("xP")),
            "horizonXP": projection.get("horizon_xP"),
            "expectedMinutes": projection.get("exp_minutes"),
            "priceOutlook": price.get(player_id),
            "midweek": [],
            "topClaim": None,
            "findings": [],
        }
        rows.append(row)
        by_id[player_id] = row

    # Section 1 — only what the model cannot see, dated to this deadline, about a player
    # who is either in the squad or has a real chance of entering it.
    considered = owned | {row["id"] for row in rows
                          if not row["owned"] and row["consensus"] > 0}
    index = _player_index(elements, teams)
    act_now = []
    for finding in findings:
        if finding.get("kind") not in {"news", "read"}:
            continue
        if finding.get("horizon") not in {"this_gw", None}:
            continue
        if finding.get("conviction") == "passing":
            continue
        touched = {_resolve_finding_player(e, index, elements)
                   for e in finding.get("players", [])} & considered
        if not touched:
            continue
        view = _finding_view(finding)
        view["owned"] = bool(touched & owned)
        view["playerIds"] = sorted(pid for pid in touched if pid is not None)
        act_now.append(view)
    # A kind that a rule actually determined outranks one the migration defaulted to.
    # Without this the section fills with rows whose information type was never
    # established, which is exactly the overstatement this room is meant to avoid.
    act_now.sort(key=lambda v: (
        "kind" in (v.get("inferred") or []),
        not v["owned"],
        -KIND_VALUE.get(v["kind"], 0),
        -CONVICTION_WEIGHT.get(v["conviction"], 0.6),
    ))

    squad = sorted((row for row in rows if row["owned"]),
                   key=lambda row: (row["mentions"] == 0,
                                    row["consensus"] + row["modelSignal"]))
    # Current price, not selling price: purchase prices are not in this payload, so the
    # affordability flag is an approximation and the UI says so.
    owned_by_position: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        if row["owned"] and row["price"] is not None:
            owned_by_position[row["position"]].append(float(row["price"]))
    for row in rows:
        headroom = max(owned_by_position.get(row["position"], [0.0]) or [0.0])
        row["affordable"] = (row["price"] or 0) <= headroom + (bank or 0)

    targets = sorted(
        (row for row in rows if not row["owned"] and row["consensus"] > 0),
        key=lambda row: -(row["consensus"] + row["modelSignal"]),
    )
    fades = sorted(
        (row for row in rows if row["consensus"] < 0),
        key=lambda row: row["consensus"] + row["modelSignal"],
    )

    captain_findings = [_finding_view(f) for f in findings
                        if f.get("topic") == "captaincy"
                        and f.get("horizon") in {"this_gw", None}]
    model_captains = sorted(
        (row for row in (by_id.get(pid) for pid in owned) if row),
        key=lambda row: -float(row["gameweekXP"] or 0),
    )[:5]
    if len(model_captains) < 5:
        pool = [(pid, projections.get(str(pid), {})) for pid in owned]
        model_captains = [
            {
                "id": pid,
                "name": elements[pid].get("web_name"),
                "team": teams.get(elements[pid]["team"], {}).get("short_name"),
                "gameweekXP": (_week_projection(proj, target_gw) or {}).get("xP", proj.get("xP")),
            }
            for pid, proj in sorted(
                pool, key=lambda item: -float(
                    (_week_projection(item[1], target_gw) or {}).get(
                        "xP", item[1].get("xP")) or 0))
        ][:5]

    chips = []
    for chip, pattern in CHIP_PATTERNS.items():
        matched = [_finding_view(f) for f in findings
                   if f.get("topic") == "chip"
                   and re.search(pattern, f"{f.get('claim', '')} {f.get('quote', '')}", re.I)]
        if matched:
            chips.append({"chip": chip, "findings": matched,
                          "mentions": len(matched),
                          "creators": sorted({f["creator"] for f in matched})})

    # Club and league claims only. A creator's own-team statement with no player named
    # is not context about a club — it belongs in section 8, and letting it fall through
    # here filled "league-wide" with wildcard plans.
    context: dict[str, list[dict]] = defaultdict(list)
    for finding in findings:
        if finding.get("players") or finding.get("kind") == "action":
            continue
        for team_name in finding.get("teams", []) or ["League-wide"]:
            context[team_name].append(_finding_view(finding))
    context_rows = sorted(
        ({"team": name, "findings": items, "mentions": len(items)}
         for name, items in context.items()),
        key=lambda row: -row["mentions"],
    )

    # Two asymmetric risks worth stating separately: a player you own losing value, and
    # a player you want gaining it. Only confident, dated projections qualify — an
    # undated drift is not something to act on.
    alerts = {"owned_falling": [], "target_rising": []}
    for row in rows:
        outlook = row.get("priceOutlook")
        if not outlook or outlook["when"] is None or not outlook["confident"]:
            continue
        entry = {"id": row["id"], "name": row["name"], "price": row["price"],
                 "when": outlook["when"], "direction": outlook["direction"],
                 "percent": outlook["percent"]}
        if row["owned"] and outlook["direction"] == "fall":
            alerts["owned_falling"].append(entry)
        elif not row["owned"] and outlook["direction"] == "rise" and row["consensus"] > 0:
            alerts["target_rising"].append(entry)
    for key in alerts:
        alerts[key].sort(key=lambda e: (e["when"], -abs(e["percent"])))

    actions = [_finding_view(f) for f in findings if f.get("kind") == "action"]
    unresolved = Counter(name for f in findings for name in f.get("unresolved", []))
    inferred = Counter(field for f in findings for field in f.get("inferred", []))
    published = sorted({f.get("published") for f in findings if f.get("published")})

    return {
        "targetGw": target_gw,
        "state": "valid",
        "corpus": {
            "findings": len(findings),
            "creators": len({f.get("source") for f in findings}),
            "videos": len({f.get("video_id") for f in findings}),
            "files": file_count,
            "schema": schema,
            "creatorCounts": dict(Counter(f.get("source", "Unknown") for f in findings)),
            "publishedFrom": published[0] if published else None,
            "publishedTo": published[-1] if published else None,
            "noTopic": sum(1 for f in findings if not (f.get("topic") or f.get("category"))),
            "inferredFields": dict(inferred),
        },
        "sections": {
            "actNow": act_now[:10],
            "squad": squad,
            "targets": targets,
            "fades": fades,
            "captaincy": {"creators": captain_findings, "model": model_captains},
            "chips": chips,
            "context": context_rows,
            "creatorActions": actions,
            "priceAlerts": alerts,
        },
        "quality": {
            "unresolved": [{"name": name, "count": n}
                           for name, n in unresolved.most_common(20)],
            "inferredFields": dict(inferred),
            "disagreementThreshold": DISAGREEMENT_FLAG,
            "affordabilityNote": "Affordability uses current price, not selling price.",
        },
    }


def _archive_exists(folder: str, gw: int) -> bool:
    directory = ROOT / folder
    return any(
        path.exists()
        for path in (
            directory / f"gw{gw:02d}.jsonl",
            directory / f"gw{gw:02d}.json",
        )
    )


def _model_form(evaluation: dict, target_gw: int) -> dict:
    minutes_files = sorted((ROOT / "minutes").glob("gw*.jsonl"))
    resolved_games = []
    for path in minutes_files:
        rows = load_jsonl(path)
        if rows and all(row.get("actual_minutes") is not None for row in rows):
            resolved_games.append(int(path.stem.removeprefix("gw")))
    archives = evaluation.get("archives", []) if isinstance(evaluation, dict) else []
    return {
        "resolvedMinutesGameweeks": resolved_games,
        "resolvedProjectionArchives": len(archives),
        "overall": evaluation.get("overall", {}) if isinstance(evaluation, dict) else {},
        "byLead": evaluation.get("by_lead", {}) if isinstance(evaluation, dict) else {},
        "byModelVersion": evaluation.get("by_model_version", {}) if isinstance(evaluation, dict) else {},
        "state": "valid" if archives or resolved_games else "empty",
        "emptyMessage": (
            f"No projection has completed its forecast window yet. GW{target_gw} will be the first baseline."
        ),
    }


def build_analysis(root: Path = ROOT) -> dict:
    """Return one coherent, frontend-safe analysis payload from the current repo state."""
    global ROOT, DATA
    original_root, original_data = ROOT, DATA
    ROOT, DATA = root, root / "data"
    try:
        bootstrap = load_json(DATA / "bootstrap.json")
        fixtures = load_json(DATA / "fixtures.json")
        entry = load_json(DATA / "entry.json")
        minutes = load_json(DATA / "minutes.json")
        projection_payload = load_json(DATA / "projections.json")
        decisions = live_only(load_json(DATA / "decisions.json"))
        evaluation_path = DATA / "evaluation.json"
        evaluation = load_json(evaluation_path) if evaluation_path.exists() else {}

        gameweeks = {
            "minutes": minutes.get("meta", {}).get("gw"),
            "projections": projection_payload.get("meta", {}).get("gw"),
            "decisions": decisions.get("meta", {}).get("gw"),
        }
        if len(set(gameweeks.values())) != 1 or None in gameweeks.values():
            raise AnalysisInputError(f"Mixed gameweeks: {gameweeks}. Rebuild a coherent analysis.")
        target_gw = int(gameweeks["decisions"])
        if decisions["meta"].get("horizon", 0) < 6:
            raise AnalysisInputError("decisions.json has fewer than six weeks; rebuild with --horizon 6")
        projections = live_only(projection_payload.get("players", {}))
        if not projections:
            raise AnalysisInputError("projections.json contains no players")

        elements = {row["id"]: row for row in bootstrap["elements"]}
        teams = {row["id"]: row for row in bootstrap["teams"]}
        hold = decisions["hold"]
        discount = float(decisions["meta"]["horizon_discount"])
        comparison = _load_independent_comparison(target_gw)
        if comparison:
            selected_comparisons = comparison.get("candidates", [])[:3]
            plans = [
                _independent_plan_view(comparison["hold"], projections, discount),
                *(
                    _independent_plan_view(candidate, projections, discount)
                    for candidate in selected_comparisons
                ),
            ]
            selected_plan_payloads = [candidate["plan"] for candidate in selected_comparisons]
            comparison_policy = "Independent exact searches over two and six gameweeks"
        else:
            plan_candidates = []
            for count, candidate_plans in decisions.get("transfers", {}).items():
                for index, plan in enumerate(candidate_plans):
                    plan_candidates.append((f"transfer-{count}-{index + 1}", plan))
            plan_candidates.sort(
                key=lambda item: float(item[1].get("gain_after_hits", -999)), reverse=True
            )
            selected_candidates = plan_candidates[:3]
            plans = [_plan_view(hold, "hold", hold, projections, discount)] + [
                _plan_view(plan, plan_id, hold, projections, discount)
                for plan_id, plan in selected_candidates
            ]
            selected_plan_payloads = [plan for _, plan in selected_candidates]
            comparison_policy = "Same six-week candidate set rescored over two and six weeks"

        player_ids = set(decisions["current"]["squad"])
        for plan in selected_plan_payloads:
            player_ids.update(plan["squad"])
        players = {
            str(player_id): _player_view(player_id, elements, projections, teams, target_gw)
            for player_id in sorted(player_ids)
        }
        player_pool = []
        for raw_id, projection in projections.items():
            player_id = int(raw_id)
            element = elements[player_id]
            week = _week_projection(projection, target_gw) or {}
            fixture = (week.get("fixtures") or [{}])[0]
            player_pool.append(
                {
                    "id": player_id,
                    "name": element.get("web_name", str(player_id)),
                    "fullName": f"{element.get('first_name', '')} {element.get('second_name', '')}".strip(),
                    "teamId": element["team"],
                    "team": teams[element["team"]]["name"],
                    "teamShort": teams[element["team"]]["short_name"],
                    "position": projection.get("position"),
                    "price": element.get("now_cost"),
                    "expectedMinutes": projection.get("exp_minutes"),
                    "gameweekXP": week.get("xP", projection.get("xP")),
                    "opponent": fixture.get("opponent", projection.get("opponent", "—")),
                    "home": fixture.get("home", projection.get("home")),
                    "status": element.get("status", "a"),
                    "news": element.get("news") or None,
                }
            )
        player_pool.sort(key=lambda row: (row["position"], -float(row["gameweekXP"] or 0), row["name"]))
        relevant_names = {row["name"] for row in players.values()}

        previous_event = next(
            (row for row in bootstrap["events"] if row["id"] == target_gw - 1), {}
        )
        previous_fixtures = [row for row in fixtures if row.get("event") == target_gw - 1]
        settled = sum(
            bool(row.get("finished") or row.get("finished_provisional"))
            for row in previous_fixtures
        )
        next_event = next((row for row in bootstrap["events"] if row["id"] == target_gw), {})
        journal_entries = [
            row for row in load_jsonl(ROOT / "journal" / "entries.jsonl") if row.get("gw") == target_gw
        ]
        source_paths = {
            "official": DATA / "bootstrap.json",
            "fixtures": DATA / "fixtures.json",
            "minutes": DATA / "minutes.json",
            "projections": DATA / "projections.json",
            "decisions": DATA / "decisions.json",
        }
        source_times = {
            name: payload.get("meta", {}).get("generated_at")
            if name in {"minutes", "projections", "decisions"}
            else _iso_mtime(path)
            for name, path in source_paths.items()
            for payload in [
                minutes if name == "minutes" else projection_payload if name == "projections" else decisions
            ]
        }
        if comparison:
            source_times["horizonComparison"] = comparison["meta"].get("generatedAt")
        run_seed = json.dumps(
            {"gw": target_gw, "sources": source_times, "version": VIEW_MODEL_VERSION},
            sort_keys=True,
        )
        run_id = f"gw{target_gw}-{hashlib.sha256(run_seed.encode()).hexdigest()[:10]}"
        archive_state = {
            "minutes": _archive_exists("minutes", target_gw),
            "projections": _archive_exists("projections", target_gw),
            "decisions": _archive_exists("decisions", target_gw),
        }
        bookmaker_weeks = sorted(
            {row["gw"] for row in hold["lineups"] if row.get("source") == "bookmaker"}
        )
        fallback_weeks = sorted(
            {row["gw"] for row in hold["lineups"] if row.get("source") != "bookmaker"}
        )
        owned_team_ids = {elements[player_id]["team"] for player_id in decisions["current"]["squad"]}

        return {
            "schemaVersion": VIEW_MODEL_VERSION,
            "analysisRunId": run_id,
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "meta": {
                "season": decisions["meta"].get("season"),
                "targetGw": target_gw,
                "deadline": next_event.get("deadline_time"),
                "manager": entry.get("player_first_name", "Joe"),
                "teamName": entry.get("name"),
                "projectionModel": projection_payload.get("meta", {}).get("model_version"),
                "minutesModel": minutes.get("meta", {}).get("model_version"),
                "comparisonPolicy": comparison_policy,
            },
            "readiness": {
                "state": "partial" if settled < len(previous_fixtures) or not previous_event.get("data_checked") else "valid",
                "previousGw": target_gw - 1,
                "settledFixtures": settled,
                "totalFixtures": len(previous_fixtures),
                "officialDataChecked": bool(previous_event.get("data_checked")),
                "bookmakerWeeks": bookmaker_weeks,
                "fallbackWeeks": fallback_weeks,
                "sourceTimes": source_times,
                "archives": archive_state,
                "journaled": bool(journal_entries),
                "message": (
                    f"GW{target_gw - 1} is {settled}/{len(previous_fixtures)} provisionally settled; "
                    "official data check is still pending."
                    if settled < len(previous_fixtures) or not previous_event.get("data_checked")
                    else f"GW{target_gw - 1} is complete and officially checked."
                ),
                "uncertainty": "No measured decision margin yet; compare leaders, do not treat them as automatic actions.",
            },
            "current": {
                "squad": decisions["current"]["squad"],
                "bank": decisions["current"]["bank"],
                "freeTransfers": decisions["current"]["free_transfers"],
                "warning": decisions["current"].get("warning"),
                "stateLabel": "Last official squad · model-selected GW lineup",
            },
            "players": players,
            "playerPool": player_pool,
            "plans": plans,
            "fixtureWall": _fixture_wall(bootstrap, fixtures, projections, owned_team_ids),
            "experts": _expert_room(
                target_gw,
                elements,
                teams,
                projections,
                set(decisions["current"]["squad"]),
                decisions["current"].get("bank") or 0,
            ),
            "modelForm": _model_form(evaluation, target_gw),
            "journal": {"entries": journal_entries, "recorded": bool(journal_entries)},
            "actions": {
                "refresh": {"label": "Refresh data", "updates": "Official cache, odds and creator feeds"},
                "rebuild": {"label": "Rebuild comparisons", "updates": "Minutes, projections and decision cache; no archives"},
                "record": {"label": "Record decision", "updates": "Appends one reviewed entry to journal/entries.jsonl"},
            },
        }
    finally:
        ROOT, DATA = original_root, original_data


if __name__ == "__main__":
    print(json.dumps(build_analysis(), indent=2))
