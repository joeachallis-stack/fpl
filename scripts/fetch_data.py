"""Fetch and cache official FPL API data to data/.

Usage:
    python scripts/fetch_data.py              # fetch everything for the configured team
    python scripts/fetch_data.py --gw 3        # also fetch picks for a specific gameweek
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
BASE = "https://fantasy.premierleague.com/api"


def load_config() -> dict:
    with open(ROOT / "config.json") as f:
        return json.load(f)


def fetch(url: str) -> dict:
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return resp.json()


def save(name: str, payload: dict) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / name
    with open(path, "w") as f:
        json.dump(payload, f)
    print(f"wrote {path} ({path.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, default=None, help="Gameweek to fetch picks for")
    args = parser.parse_args()

    config = load_config()
    team_id = config["team_id"]

    save("bootstrap.json", fetch(f"{BASE}/bootstrap-static/"))
    save("fixtures.json", fetch(f"{BASE}/fixtures/"))
    entry = fetch(f"{BASE}/entry/{team_id}/")
    save("entry.json", entry)
    save("history.json", fetch(f"{BASE}/entry/{team_id}/history/"))
    save("transfers.json", fetch(f"{BASE}/entry/{team_id}/transfers/"))

    current_gw = args.gw or entry.get("current_event")
    if current_gw:
        save(
            f"picks_gw{current_gw}.json",
            fetch(f"{BASE}/entry/{team_id}/event/{current_gw}/picks/"),
        )


if __name__ == "__main__":
    main()
