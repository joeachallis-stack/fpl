"""Pre-deadline sanity check on the squad. Run fetch_data.py first.

Catches the cheap, avoidable losses: an illegal XI, a flagged player left starting, a
vice-captain playing in the same match as the captain, a blanking player, a bench that
cannot cover. Squad rules are read from bootstrap rather than hardcoded.

IMPORTANT: this validates the last squad the API has on record — the one from the most
recently completed gameweek. Transfers or lineup changes saved in the app since that
deadline are NOT visible here (that needs the authenticated my-team endpoint), so treat
this as a check on your starting point, and re-run after the next deadline passes.

Usage:
    python scripts/check_team.py
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# FPL availability codes. Anything not "a" means the player is not fully fit/available.
BLOCKING_STATUS = {"i": "injured", "s": "suspended", "u": "unavailable", "n": "not in squad"}
DOUBTFUL_STATUS = "d"


def load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


class Report:
    """Collects findings so the exit summary can say how bad it is."""

    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []

    def fail(self, msg: str) -> None:
        self.fails.append(msg)
        print(f"  FAIL  {msg}")

    def warn(self, msg: str) -> None:
        self.warns.append(msg)
        print(f"  WARN  {msg}")

    def ok(self, msg: str) -> None:
        print(f"  ok    {msg}")


def next_event(boot: dict) -> dict | None:
    for event in boot["events"]:
        if event.get("is_next"):
            return event
    return next((e for e in boot["events"] if not e["finished"]), None)


def fixtures_by_team(fixtures: list[dict], gw: int) -> dict[int, list[dict]]:
    """team id -> fixtures they play in this gameweek (0 = blank, 2+ = double)."""
    out: dict[int, list[dict]] = defaultdict(list)
    for f in fixtures:
        if f["event"] != gw:
            continue
        out[f["team_h"]].append(f)
        out[f["team_a"]].append(f)
    return out


def availability(el: dict) -> str | None:
    """Human-readable problem with this player, or None if they're fine."""
    if el["status"] in BLOCKING_STATUS:
        note = el.get("news") or BLOCKING_STATUS[el["status"]]
        return note
    chance = el.get("chance_of_playing_next_round")
    if el["status"] == DOUBTFUL_STATUS or (chance is not None and chance < 100):
        note = el.get("news") or "doubtful"
        pct = f" ({chance}% chance)" if chance is not None else ""
        return f"{note}{pct}"
    return None


def main() -> None:
    boot = load("bootstrap.json")
    entry = load("entry.json")
    fixtures = load("fixtures.json")

    current_gw = entry["current_event"]
    picks_path = DATA_DIR / f"picks_gw{current_gw}.json"
    if not picks_path.exists():
        print(f"No cached picks for GW{current_gw}. Run: python scripts/fetch_data.py")
        return
    with open(picks_path) as f:
        picks = json.load(f)

    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["short_name"] for t in boot["teams"]}
    types = {t["id"]: t for t in boot["element_types"]}
    settings = boot["game_settings"]

    event = next_event(boot)
    if not event:
        print("No upcoming gameweek to check.")
        return
    gw = event["id"]
    team_fixtures = fixtures_by_team(fixtures, gw)

    print(f"Checking the GW{current_gw} squad against {event['name']} "
          f"(deadline {event['deadline_time']})")
    print("Squad on record from the last deadline — changes saved in the app since "
          "are not visible.\n")

    r = Report()
    squad = picks["picks"]
    starters = [p for p in squad if p["position"] <= settings["squad_squadplay"]]
    bench = [p for p in squad if p["position"] > settings["squad_squadplay"]]

    # --- squad shape -------------------------------------------------------------
    if len(squad) != settings["squad_squadsize"]:
        r.fail(f"squad has {len(squad)} players, expected {settings['squad_squadsize']}")
    if len(starters) != settings["squad_squadplay"]:
        r.fail(f"XI has {len(starters)} players, expected {settings['squad_squadplay']}")
    else:
        r.ok(f"{len(starters)} starters, {len(bench)} on the bench")

    formation = Counter(elements[p["element"]]["element_type"] for p in starters)
    shape = []
    for tid, t in sorted(types.items()):
        n = formation.get(tid, 0)
        shape.append(f"{n}{t['singular_name_short']}")
        if not (t["squad_min_play"] <= n <= t["squad_max_play"]):
            r.fail(
                f"{n} {t['singular_name_short']} in the XI — "
                f"must be {t['squad_min_play']}-{t['squad_max_play']}"
            )
    r.ok(f"formation {' '.join(shape)}")

    club_counts = Counter(elements[p["element"]]["team"] for p in squad)
    over = {teams[t]: n for t, n in club_counts.items() if n > settings["squad_team_limit"]}
    if over:
        r.fail(f"over the {settings['squad_team_limit']}-per-club limit: {over}")
    else:
        r.ok(f"no club over the {settings['squad_team_limit']}-player limit")

    # --- availability and blanks in the XI ---------------------------------------
    clean_xi = True
    for p in starters:
        el = elements[p["element"]]
        name = el["web_name"]
        problem = availability(el)
        if problem:
            clean_xi = False
            if el["status"] in BLOCKING_STATUS:
                r.fail(f"{name} starting but {problem}")
            else:
                r.warn(f"{name} starting — {problem}")
        if not team_fixtures.get(el["team"]):
            clean_xi = False
            r.fail(f"{name} ({teams[el['team']]}) has no fixture in GW{gw} — blank")
    if clean_xi:
        r.ok(f"all {len(starters)} starters fit and playing in GW{gw}")

    doubles = {
        teams[el_team]: len(fx)
        for el_team, fx in team_fixtures.items()
        if len(fx) > 1 and any(elements[p["element"]]["team"] == el_team for p in squad)
    }
    if doubles:
        r.ok(f"double gameweek for squad clubs: {doubles}")

    # --- captaincy ---------------------------------------------------------------
    captain = next((p for p in squad if p["is_captain"]), None)
    vice = next((p for p in squad if p["is_vice_captain"]), None)
    if not captain:
        r.fail("no captain set")
    if not vice:
        r.fail("no vice-captain set")

    if captain and vice:
        cap_el, vice_el = elements[captain["element"]], elements[vice["element"]]
        r.ok(f"captain {cap_el['web_name']}, vice {vice_el['web_name']}")

        for role, pick, el in (("captain", captain, cap_el), ("vice", vice, vice_el)):
            problem = availability(el)
            if problem:
                r.warn(f"{role} {el['web_name']} — {problem}")
            if not team_fixtures.get(el["team"]):
                r.fail(f"{role} {el['web_name']} has no fixture in GW{gw}")
            if pick["position"] > settings["squad_squadplay"]:
                r.warn(f"{role} {el['web_name']} is on the bench")

        cap_fx = {f["id"] for f in team_fixtures.get(cap_el["team"], [])}
        vice_fx = {f["id"] for f in team_fixtures.get(vice_el["team"], [])}
        if cap_fx and cap_fx == vice_fx:
            r.warn(
                f"{cap_el['web_name']} and {vice_el['web_name']} play the same match — "
                "if it's postponed you lose the armband entirely"
            )

    # --- bench -------------------------------------------------------------------
    outfield_subs = [
        p for p in bench if elements[p["element"]]["element_type"] != 1
    ]
    if outfield_subs:
        first = outfield_subs[0]
        el = elements[first["element"]]
        problem = availability(el)
        if problem:
            r.warn(f"first sub {el['web_name']} — {problem}; weak autosub cover")
        elif not team_fixtures.get(el["team"]):
            r.warn(f"first sub {el['web_name']} blanks in GW{gw}; weak autosub cover")
        else:
            r.ok(f"first sub {el['web_name']} is fit and playing")

    print()
    if r.fails:
        print(f"{len(r.fails)} problem(s) to fix, {len(r.warns)} to think about.")
    elif r.warns:
        print(f"Nothing broken. {len(r.warns)} thing(s) to think about.")
    else:
        print("Clean — nothing to fix before the deadline.")


if __name__ == "__main__":
    main()
