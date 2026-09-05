"""Fetch and derive near-term EPL bookmaker-implied fixture probabilities.

The source returns decimal odds, not fair probabilities. Each bookmaker's margin is
removed within that bookmaker and market before medians are taken across bookmakers.
See docs/DATA_SOURCES.md for the interpretation contract.

Usage:
    python scripts/odds.py
    python scripts/odds.py --refresh
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ENV_PATH = ROOT / ".env"
RAW_PATH = DATA_DIR / "odds_raw.json"
DERIVED_PATH = DATA_DIR / "odds.json"

API_URL = "https://api.the-odds-api.com/v4/sports/soccer_epl/odds"
REGION = "uk"
MARKETS = "h2h,totals"
CACHE_MAX_AGE_H = 2
KICKOFF_TOLERANCE_S = 10 * 60

# The odds feed uses full club names while bootstrap-static uses FPL display names.
# Keep this explicit: fuzzy matching a plausible but wrong team is worse than refusing.
ODDS_TO_FPL_TEAM = {
    "Arsenal": "Arsenal",
    "Aston Villa": "Aston Villa",
    "Bournemouth": "Bournemouth",
    "Brentford": "Brentford",
    "Brighton and Hove Albion": "Brighton",
    "Chelsea": "Chelsea",
    "Coventry City": "Coventry City",
    "Crystal Palace": "Crystal Palace",
    "Everton": "Everton",
    "Fulham": "Fulham",
    "Hull City": "Hull City",
    "Ipswich Town": "Ipswich Town",
    "Leeds United": "Leeds",
    "Liverpool": "Liverpool",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Sunderland": "Sunderland",
    "Tottenham Hotspur": "Spurs",
}


def read_dotenv_key() -> str | None:
    """Read only THE_ODDS_API_KEY; avoid a dependency for one local secret."""
    if not ENV_PATH.exists():
        return None
    for raw_line in ENV_PATH.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "THE_ODDS_API_KEY":
            return value.strip().strip("\"'") or None
    return None


def api_key() -> str | None:
    return os.environ.get("THE_ODDS_API_KEY") or read_dotenv_key()


def is_fresh(path: Path, max_age_h: float) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) / 3600 < max_age_h


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def fetch_raw(key: str) -> dict:
    response = requests.get(
        API_URL,
        params={
            "apiKey": key,
            "regions": REGION,
            "markets": MARKETS,
            "oddsFormat": "decimal",
        },
        timeout=20,
    )
    if not response.ok:
        # requests' normal exception includes the prepared URL, including the secret.
        raise RuntimeError(f"Odds API request failed with HTTP {response.status_code}")
    return {
        "source": "the-odds-api",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "request": {"sport": "soccer_epl", "regions": REGION, "markets": MARKETS},
        "quota": {
            "last": response.headers.get("x-requests-last"),
            "used": response.headers.get("x-requests-used"),
            "remaining": response.headers.get("x-requests-remaining"),
        },
        "events": response.json(),
    }


def fair_probabilities(outcomes: list[dict], names: list[str]) -> dict[str, float] | None:
    prices = {outcome["name"]: outcome.get("price") for outcome in outcomes}
    if set(prices) != set(names) or any(not prices[name] or prices[name] <= 1 for name in names):
        return None
    implied = {name: 1 / prices[name] for name in names}
    overround = sum(implied.values())
    return {name: implied[name] / overround for name in names}


def median_distribution(rows: list[dict[str, float]], names: list[str]) -> dict[str, float]:
    medians = {name: statistics.median(row[name] for row in rows) for name in names}
    total = sum(medians.values())
    return {name: medians[name] / total for name in names}


def event_probabilities(event: dict) -> dict | None:
    home = event["home_team"]
    away = event["away_team"]
    h2h_rows = []
    totals_rows = []
    updates = []

    for bookmaker in event.get("bookmakers", []):
        for market in bookmaker.get("markets", []):
            # h2h_lay can be returned automatically; it is intentionally ignored.
            if market.get("key") == "h2h":
                row = fair_probabilities(market.get("outcomes", []), [home, "Draw", away])
                if row:
                    h2h_rows.append(row)
                    updates.append(market.get("last_update") or bookmaker.get("last_update"))
            elif market.get("key") == "totals":
                outcomes = market.get("outcomes", [])
                if outcomes and all(outcome.get("point") == 2.5 for outcome in outcomes):
                    row = fair_probabilities(outcomes, ["Over", "Under"])
                    if row:
                        totals_rows.append(row)
                        updates.append(market.get("last_update") or bookmaker.get("last_update"))

    if not h2h_rows:
        return None
    h2h = median_distribution(h2h_rows, [home, "Draw", away])
    totals = median_distribution(totals_rows, ["Over", "Under"]) if totals_rows else None
    valid_updates = sorted(update for update in updates if update)
    return {
        "home_win": h2h[home],
        "draw": h2h["Draw"],
        "away_win": h2h[away],
        "over_2_5": totals["Over"] if totals else None,
        "under_2_5": totals["Under"] if totals else None,
        "h2h_bookmakers": len(h2h_rows),
        "totals_bookmakers": len(totals_rows),
        "oldest_update": valid_updates[0] if valid_updates else None,
        "newest_update": valid_updates[-1] if valid_updates else None,
    }


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def match_fixture(event: dict, bootstrap: dict, fixtures: list[dict]) -> dict | None:
    teams_by_name = {team["name"]: team for team in bootstrap["teams"]}
    try:
        home = teams_by_name[ODDS_TO_FPL_TEAM[event["home_team"]]]
        away = teams_by_name[ODDS_TO_FPL_TEAM[event["away_team"]]]
    except KeyError:
        return None

    event_time = parse_time(event["commence_time"])
    candidates = [
        fixture
        for fixture in fixtures
        if fixture.get("team_h") == home["id"]
        and fixture.get("team_a") == away["id"]
        and fixture.get("kickoff_time")
        and abs((parse_time(fixture["kickoff_time"]) - event_time).total_seconds())
        <= KICKOFF_TOLERANCE_S
    ]
    return candidates[0] if len(candidates) == 1 else None


def derive(raw: dict, bootstrap: dict, fixtures: list[dict]) -> dict:
    derived = []
    unmatched = []
    for event in raw["events"]:
        fixture = match_fixture(event, bootstrap, fixtures)
        probabilities = event_probabilities(event)
        if not fixture or not probabilities:
            unmatched.append(
                {
                    "event_id": event.get("id"),
                    "home_team": event.get("home_team"),
                    "away_team": event.get("away_team"),
                    "commence_time": event.get("commence_time"),
                }
            )
            continue
        derived.append(
            {
                "fixture_id": fixture["id"],
                "event": fixture.get("event"),
                "kickoff_time": fixture["kickoff_time"],
                "home_team": ODDS_TO_FPL_TEAM[event["home_team"]],
                "away_team": ODDS_TO_FPL_TEAM[event["away_team"]],
                **probabilities,
            }
        )
    return {
        "source": raw["source"],
        "fetched_at": raw["fetched_at"],
        "method": "per-bookmaker de-vig, component median, renormalized",
        "fixtures": derived,
        "unmatched": unmatched,
    }


def run(bootstrap: dict, fixtures: list[dict], refresh: bool = False) -> bool:
    if is_fresh(RAW_PATH, CACHE_MAX_AGE_H) and not refresh:
        raw = json.loads(RAW_PATH.read_text())
        print(f"odds: using cached data (<{CACHE_MAX_AGE_H}h old)")
    else:
        key = api_key()
        if not key:
            print("odds: THE_ODDS_API_KEY not set — skipping optional odds refresh")
            return False
        raw = fetch_raw(key)
        write_json(RAW_PATH, raw)
        quota = raw["quota"]
        print(f"  odds credits: {quota['last']} used now, {quota['remaining']} remaining")

    payload = derive(raw, bootstrap, fixtures)
    write_json(DERIVED_PATH, payload)
    print(
        f"  odds: {len(payload['fixtures'])} fixtures matched, "
        f"{len(payload['unmatched'])} unmatched"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the 2-hour cache")
    args = parser.parse_args()
    bootstrap = json.loads((DATA_DIR / "bootstrap.json").read_text())
    fixtures = json.loads((DATA_DIR / "fixtures.json").read_text())
    run(bootstrap, fixtures, refresh=args.refresh)


if __name__ == "__main__":
    main()
