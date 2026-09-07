"""Build the read-only view model consumed by the local FPL decision room.

This module is deliberately an adapter, not a second model. It joins the existing
official, minutes, projection, decision, creator and journal artifacts into one coherent
payload. Live-decision routes are recursively stripped of evaluation-only shadow fields.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _expert_room(target_gw: int, relevant_names: set[str]) -> dict:
    files = sorted((ROOT / "news" / "findings").glob(f"gw{target_gw:02d}_*.jsonl"))
    findings = [row for path in files for row in load_jsonl(path)]
    creator_counts = Counter(row.get("source", "Unknown") for row in findings)
    by_player: dict[str, dict] = {}
    for finding in findings:
        for raw_name in finding.get("players", []):
            name = raw_name.split(" (", 1)[0]
            if relevant_names and name not in relevant_names:
                continue
            row = by_player.setdefault(
                name,
                {"player": name, "positive": 0, "negative": 0, "neutral": 0, "findings": []},
            )
            stance = finding.get("stance", "neutral")
            bucket = stance if stance in {"positive", "negative", "neutral"} else "neutral"
            row[bucket] += 1
            row["findings"].append(
                {
                    "creator": finding.get("source"),
                    "published": finding.get("published"),
                    "category": finding.get("category"),
                    "stance": stance,
                    "claim": finding.get("claim"),
                    "conviction": finding.get("conviction"),
                    "videoId": finding.get("video_id"),
                }
            )
    return {
        "targetGw": target_gw,
        "files": len(files),
        "findings": len(findings),
        "creators": len(creator_counts),
        "creatorCounts": dict(creator_counts),
        "players": sorted(by_player.values(), key=lambda row: -len(row["findings"])),
        "state": "empty" if not findings else "valid",
        "emptyMessage": f"No GW{target_gw} creator findings have been extracted yet.",
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
            "experts": _expert_room(target_gw, relevant_names),
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
