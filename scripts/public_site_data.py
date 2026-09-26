"""Read-only public FPL team view for the separate site prototype."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from state import free_transfers

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://fantasy.premierleague.com/api"
_CACHE: dict[str, tuple[float, object]] = {}
_LOCK = threading.Lock()


def fetch_json(path: str) -> object:
    """Cache official responses briefly; keep visitor data out of the repository."""
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(path)
        if cached and cached[0] > now:
            return cached[1]
    request = Request(f"{BASE}/{path}", headers={"User-Agent": "FPL-season-review/0.1"})
    with urlopen(request, timeout=18) as response:
        data = json.load(response)
    ttl = 900 if path in {"bootstrap-static/", "fixtures/"} else 300
    with _LOCK:
        _CACHE[path] = (now + ttl, data)
    return data


def identity(entry_id: int, get=fetch_json) -> dict:
    entry = get(f"entry/{entry_id}/")
    return {
        "id": entry["id"],
        "name": entry["name"],
        "manager": " ".join(filter(None, [entry.get("player_first_name"), entry.get("player_last_name")])),
        "points": entry.get("summary_overall_points"),
        "rank": entry.get("summary_overall_rank"),
    }


def _points(live: dict, player_id: int) -> int:
    return next((row["stats"]["total_points"] for row in live.get("elements", []) if row["id"] == player_id), 0)


def _projection_data(next_gw: int) -> tuple[dict, str | None]:
    path = ROOT / "data" / "projections.json"
    if not path.exists():
        return {}, None
    data = json.loads(path.read_text())
    if data.get("meta", {}).get("gw") != next_gw:
        return {}, None
    return data.get("players", {}), data["meta"].get("generated_at")


def analysis(entry_id: int, get=fetch_json) -> dict:
    entry = get(f"entry/{entry_id}/")
    history = get(f"entry/{entry_id}/history/")
    boot = get("bootstrap-static/")
    fixtures = get("fixtures/")
    checked_events = {event["id"] for event in boot["events"] if event.get("data_checked")}
    all_weeks = history.get("current", [])
    settled = [row for row in all_weeks if row["event"] in checked_events]
    last_settled_gw = settled[-1]["event"] if settled else None
    last_public_gw = all_weeks[-1]["event"] if all_weeks else None
    now = datetime.now(timezone.utc)
    upcoming = next((event for event in boot["events"] if datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00")) > now), None)
    next_gw = upcoming["id"] if upcoming else None
    players = {row["id"]: row for row in boot["elements"]}
    clubs = {row["id"]: row["short_name"] for row in boot["teams"]}
    positions = {row["id"]: row["singular_name_short"] for row in boot["element_types"]}
    projections, projection_time = _projection_data(next_gw) if next_gw else ({}, None)
    gameweeks = [event["id"] for event in boot["events"] if next_gw and next_gw <= event["id"] < next_gw + 6]

    fixture_map: dict[tuple[int, int], list[dict]] = {}
    for fixture in fixtures:
        gw = fixture.get("event")
        if gw not in gameweeks:
            continue
        for club_id, opponent_id, home, difficulty in (
            (fixture["team_h"], fixture["team_a"], True, fixture.get("team_h_difficulty")),
            (fixture["team_a"], fixture["team_h"], False, fixture.get("team_a_difficulty")),
        ):
            fixture_map.setdefault((club_id, gw), []).append({"opponent": clubs.get(opponent_id, "?"), "home": home, "difficulty": difficulty})

    pool = []
    for row in players.values():
        projected = projections.get(str(row["id"]), {})
        weeks = {week["gw"]: week for week in projected.get("gameweeks", [])}
        pool.append({
            "id": row["id"], "name": row["web_name"], "club": clubs.get(row["team"], "?"),
            "clubId": row["team"], "position": positions.get(row["element_type"], "?"),
            "price": row["now_cost"] / 10, "form": row.get("form", "0"),
            "news": row.get("news", ""), "status": row.get("status", "a"),
            "weeks": [{"gw": gw, "xp": weeks.get(gw, {}).get("xP"), "fixtures": fixture_map.get((row["team"], gw), [])} for gw in gameweeks],
        })

    picks = get(f"entry/{entry_id}/event/{last_public_gw}/picks/") if last_public_gw else {"picks": [], "active_chip": None}
    squad_picks = picks
    squad_state = f"Last publicly confirmed squad · GW{last_public_gw}" if last_public_gw else "No public picks yet"
    if picks.get("active_chip") == "freehit" and last_public_gw and last_public_gw > 1:
        squad_picks = get(f"entry/{entry_id}/event/{last_public_gw - 1}/picks/")
        squad_state = f"Squad before GW{last_public_gw} Free Hit · next official picks pending"
    squad = [{"id": pick["element"], "position": pick["position"], "multiplier": pick["multiplier"],
              "captain": pick["is_captain"], "vice": pick["is_vice_captain"]} for pick in squad_picks["picks"]]
    banked, _ = free_transfers(history, boot["game_settings"])
    transfer_log = get(f"entry/{entry_id}/transfers/")
    chip_gws = {chip["event"] for chip in history.get("chips", []) if chip["name"] == "freehit"}

    moments = []
    if settled:
        best = max(settled, key=lambda row: row["points"])
        average = next((event["average_entry_score"] for event in boot["events"] if event["id"] == best["event"]), None)
        moments.append({"kind": "high", "gw": best["event"], "eyebrow": "The high point",
                        "title": f"GW{best['event']} was your biggest week", "number": f"{best['points']} pts",
                        "body": f"Your best gameweek so far. The field average was {average} points." if average is not None else "Your best gameweek so far.",
                        "basis": "Official gameweek history"})
        benched = sum(row.get("points_on_bench", 0) for row in settled)
        if benched:
            moments.append({"kind": "bench", "gw": None, "eyebrow": "The fine margins",
                            "title": "Points on the bench", "number": f"{benched} pts",
                            "body": "Your bench players scored this many points across completed gameweeks. This is not a claim that the points were lost; Bench Boost may already have counted them.",
                            "basis": "Official gameweek history · descriptive, not points lost"})

    # One recent settled transfer creates a concrete decision story without a full-season API burst.
    valid_transfers = [row for row in transfer_log if row["event"] in {item["event"] for item in settled} and row["event"] not in chip_gws]
    if valid_transfers:
        gw = max(row["event"] for row in valid_transfers)
        live = get(f"event/{gw}/live/")
        pairs = [(row, _points(live, row["element_in"]) - _points(live, row["element_out"])) for row in valid_transfers if row["event"] == gw]
        row, swing = max(pairs, key=lambda item: abs(item[1]))
        incoming = players.get(row["element_in"], {}).get("web_name", "Your new player")
        outgoing = players.get(row["element_out"], {}).get("web_name", "the player sold")
        archive = ROOT / "projections" / f"gw{gw:02}.json"
        expected = None
        if archive.exists():
            frozen = json.loads(archive.read_text()).get("players", {})
            a, b = frozen.get(str(row["element_in"])), frozen.get(str(row["element_out"]))
            if a and b:
                expected = round(a["xP"] - b["xP"], 1)
        body = f"{incoming} scored {_points(live, row['element_in'])}; {outgoing} scored {_points(live, row['element_out'])} that week. This player comparison excludes lineup and captain effects."
        if expected is not None:
            body += f" Before the deadline, our frozen forecast had the swap at {expected:+.1f} expected points."
        moments.append({"kind": "transfer", "gw": gw, "eyebrow": "A move revisited",
                        "title": f"{incoming} for {outgoing}", "number": f"{swing:+d} pts", "body": body,
                        "basis": "One-gameweek player comparison; excludes any transfer hit" + (" · pre-deadline forecast available" if expected is not None else " · hindsight only")})

    if last_settled_gw:
        story_picks = picks if last_settled_gw == last_public_gw else get(f"entry/{entry_id}/event/{last_settled_gw}/picks/")
        captain = next((pick for pick in story_picks["picks"] if pick["is_captain"]), None)
        if captain:
            live = get(f"event/{last_settled_gw}/live/")
            name = players.get(captain["element"], {}).get("web_name", "Your captain")
            points = _points(live, captain["element"])
            moments.append({"kind": "captain", "gw": last_settled_gw, "eyebrow": "The armband",
                            "title": f"{name} led your GW{last_settled_gw}", "number": f"{points * captain['multiplier']} pts",
                            "body": f"{points} player points with the saved captain multiplier of {captain['multiplier']}.",
                            "basis": "Official saved picks and settled player points"})

    return {
        "team": identity(entry_id, lambda path: entry if path == f"entry/{entry_id}/" else get(path)),
        "lastGw": last_public_gw, "nextGw": next_gw, "deadline": upcoming["deadline_time"] if upcoming else None,
        "history": [{"gw": row["event"], "points": row["points"], "total": row["total_points"],
                     "rank": row.get("overall_rank"), "bench": row.get("points_on_bench", 0)} for row in settled],
        "squad": squad, "pool": pool, "gameweeks": gameweeks, "freeTransfers": banked,
        "bank": all_weeks[-1]["bank"] / 10 if all_weeks else None,
        "moments": moments, "projectionTime": projection_time,
        "squadState": squad_state,
    }
