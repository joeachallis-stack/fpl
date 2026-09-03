"""Fetch and cache official FPL API data to data/.

Usage:
    python scripts/fetch_data.py              # fetch everything for the configured team
    python scripts/fetch_data.py --gw 3        # also fetch picks for a specific gameweek
    python scripts/fetch_data.py --skip-slow   # bootstrap/fixtures/entry only
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

import fetch_news

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"
BASE = "https://fantasy.premierleague.com/api"

# Leagues bigger than this are global/sponsor leagues — the standings are hundreds of
# pages of strangers. Only pull the ones with actual rivals in them.
LEAGUE_SIZE_LIMIT = 500

# Standings come 50 to a page; enough pages to cover LEAGUE_SIZE_LIMIT with headroom.
MAX_STANDINGS_PAGES = 12


def load_config() -> dict:
    with open(ROOT / "config.json") as f:
        return json.load(f)


def fetch(url: str) -> dict:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def save(name: str, payload: dict) -> None:
    path = DATA_DIR / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def save_snapshot(payload: dict) -> None:
    """Dated copy of bootstrap-static, kept alongside the overwritten live cache.

    Set-piece order (penalties_order, direct_freekicks_order, corners_and_
    indirect_freekicks_order) is the one input the API never backfills — it only ever
    shows the current state, and plain `save()` overwrites it every run. One snapshot a
    day is enough to catch a change; it does not need git history, just to survive being
    overwritten tomorrow.
    """
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = SNAPSHOT_DIR / f"bootstrap_{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"wrote {path.relative_to(ROOT)} ({path.stat().st_size:,} bytes)")


def fetch_standings(league_id: int) -> dict:
    """Page through a classic league's standings and merge into one payload."""
    merged = fetch(f"{BASE}/leagues-classic/{league_id}/standings/?page_standings=1")
    truncated = bool(merged["standings"].get("has_next"))
    for page in range(2, MAX_STANDINGS_PAGES + 1):
        if not truncated:
            break
        chunk = fetch(f"{BASE}/leagues-classic/{league_id}/standings/?page_standings={page}")
        merged["standings"]["results"].extend(chunk["standings"]["results"])
        truncated = bool(chunk["standings"].get("has_next"))
    # The merged payload holds every page we pulled, so page one's has_next would lie
    # to anything reading the cache.
    merged["standings"]["has_next"] = truncated
    if truncated:
        print(f"  warning: league {league_id} exceeded {MAX_STANDINGS_PAGES} pages, truncated")
    return merged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None, help="Gameweek to fetch picks for")
    parser.add_argument(
        "--skip-slow",
        action="store_true",
        help="Skip per-player summaries and league standings (many requests)",
    )
    args = parser.parse_args()

    config = load_config()
    team_id = config["team_id"]

    bootstrap = fetch(f"{BASE}/bootstrap-static/")
    save("bootstrap.json", bootstrap)
    save_snapshot(bootstrap)
    save("fixtures.json", fetch(f"{BASE}/fixtures/"))
    save("event_status.json", fetch(f"{BASE}/event-status/"))

    # Free-text FPL news (RSS headlines, not official API data). Tied to this same
    # run rather than its own schedule — see fetch_news.py's docstring for why.
    # Third-party sites are flakier than the official API; a dead feed shouldn't
    # abort the rest of the fetch.
    try:
        fetch_news.main()
    except Exception as exc:  # noqa: BLE001
        print(f"  news: fetch_news.py failed entirely ({exc}) — continuing without it")

    entry = fetch(f"{BASE}/entry/{team_id}/")
    save("entry.json", entry)
    save("history.json", fetch(f"{BASE}/entry/{team_id}/history/"))
    save("transfers.json", fetch(f"{BASE}/entry/{team_id}/transfers/"))

    current_gw = args.gw or entry.get("current_event")
    picks = None
    if current_gw:
        picks = fetch(f"{BASE}/entry/{team_id}/event/{current_gw}/picks/")
        save(f"picks_gw{current_gw}.json", picks)

    if args.skip_slow:
        return

    # Per-player fixture history + remaining fixtures, for the squad we actually own.
    if picks:
        for pick in picks["picks"]:
            pid = pick["element"]
            save(f"element_summary/{pid}.json", fetch(f"{BASE}/element-summary/{pid}/"))

    # Standings for the small leagues — rivals worth knowing about, not sponsor leagues.
    for league in entry.get("leagues", {}).get("classic", []):
        if league.get("rank_count") and league["rank_count"] <= LEAGUE_SIZE_LIMIT:
            save(f"standings_{league['id']}.json", fetch_standings(league["id"]))


if __name__ == "__main__":
    main()
