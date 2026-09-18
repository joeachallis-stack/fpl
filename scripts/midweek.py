"""Midweek football before a league gameweek: European ties and cup games the FPL API cannot see.

The minutes model only knows Premier League rounds, so a Thursday in Spain before a
Sunday at home is invisible to it. That nearly mattered in GW5, when Tavernier was the
model's favourite transfer the same week Bournemouth flew to Real Sociedad.

This is display, not a model input. Nothing here changes a projection. A fatigue or
rotation discount belongs in `minutes.py` only after `train_minutes.py` has fitted and
walk-forward validated one, and that needs flagged players to resolve first. Until then
the flag sits next to the number, the same way the expert room does.

Fixtures come from the hand-maintained `midweek/fixtures.json`. A club missing from it
means "not recorded", not "no fixture". The file lists its own known gaps, and every
report prints them.

Usage:
    python scripts/midweek.py            # next gameweek
    python scripts/midweek.py --gw 6
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FIXTURES_PATH = ROOT / "midweek" / "fixtures.json"

# A match inside this window before a club's league kick-off is shown. Under SHORT_HOURS
# (a Thursday night before a Sunday lunchtime is ~66h) it is marked as a short turnaround.
WINDOW_HOURS = 96
SHORT_HOURS = 72


def _time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def load_fixtures() -> dict:
    if not FIXTURES_PATH.exists():
        return {"fixtures": [], "known_gaps": ["midweek/fixtures.json does not exist"]}
    with open(FIXTURES_PATH) as f:
        return json.load(f)


def next_gw(bootstrap: dict) -> int | None:
    event = next((e for e in bootstrap["events"] if e.get("is_next")), None)
    return event["id"] if event else None


def before_league(gw: int, bootstrap: dict | None = None, fixtures: list[dict] | None = None) -> dict[int, list[dict]]:
    """Team id -> midweek matches shortly before that team's league fixture(s) in `gw`."""
    if bootstrap is None:
        with open(DATA_DIR / "bootstrap.json") as f:
            bootstrap = json.load(f)
    if fixtures is None:
        with open(DATA_DIR / "fixtures.json") as f:
            fixtures = json.load(f)
    boot: dict = bootstrap or {}
    league_fixtures: list[dict] = fixtures or []
    short_to_id = {t["short_name"]: t["id"] for t in boot["teams"]}
    other = load_fixtures()["fixtures"]

    flags: dict[int, list[dict]] = {}
    for league in league_fixtures:
        if league.get("event") != gw or not league.get("kickoff_time"):
            continue
        kickoff = _time(league["kickoff_time"])
        for team in (league["team_h"], league["team_a"]):
            for match in other:
                if short_to_id.get(match["team"]) != team:
                    continue
                hours = (kickoff - _time(match["kickoff_utc"])).total_seconds() / 3600
                if 0 < hours <= WINDOW_HOURS:
                    flags.setdefault(team, []).append(
                        {**match, "league_kickoff": league["kickoff_time"],
                         "hours_before": round(hours, 1), "short": hours < SHORT_HOURS}
                    )
    return flags


def describe(match: dict) -> str:
    """'UEL at Real Sociedad Thu, 66h before' — the one line a reader needs."""
    where = "v" if match["venue"] == "H" else "at"
    day = _time(match["kickoff_utc"]).strftime("%a")
    short = ", short turnaround" if match["short"] else ""
    return f"{match['competition']} {where} {match['opponent']} {day}, {match['hours_before']:.0f}h before{short}"


def team_note(team: int, flags: dict[int, list[dict]]) -> str | None:
    matches = flags.get(team)
    return "; ".join(describe(m) for m in matches) if matches else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gw", type=int)
    args = parser.parse_args()

    with open(DATA_DIR / "bootstrap.json") as f:
        bootstrap = json.load(f)
    gw = args.gw or next_gw(bootstrap)
    if gw is None:
        raise SystemExit("no upcoming gameweek")
    names = {t["id"]: t["name"] for t in bootstrap["teams"]}
    flags = before_league(gw, bootstrap)

    print(f"Midweek matches within {WINDOW_HOURS}h before a GW{gw} league kick-off "
          "(display only, not in the model):\n")
    if not flags:
        print("  none recorded")
    for team, matches in sorted(flags.items(), key=lambda kv: min(m["hours_before"] for m in kv[1])):
        for match in matches:
            print(f"  {names[team]:<15} {describe(match)}")
    gaps = load_fixtures().get("known_gaps", [])
    if gaps:
        print("\nNot recorded yet, so absence is not evidence:")
        for gap in gaps:
            print(f"  - {gap}")


if __name__ == "__main__":
    main()
