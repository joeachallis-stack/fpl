"""Pretty-print the cached squad + team summary. Run fetch_data.py first."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"


def load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def main() -> None:
    entry = load("entry.json")
    boot = load("bootstrap.json")

    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t["name"] for t in boot["teams"]}
    types = {t["id"]: t["singular_name_short"] for t in boot["element_types"]}

    current_gw = entry["current_event"]
    picks_path = DATA_DIR / f"picks_gw{current_gw}.json"
    if not picks_path.exists():
        print(f"No cached picks for GW{current_gw}. Run: python scripts/fetch_data.py")
        return
    with open(picks_path) as f:
        picks = json.load(f)

    print(f"{entry['player_first_name']} {entry['player_last_name']} — {entry['name']}")
    print(f"Overall rank: {entry['summary_overall_rank']:,}  |  Total points: {entry['summary_overall_points']}")
    hist = picks["entry_history"]
    value = hist["value"] / 10
    bank = hist["bank"] / 10
    print(f"Squad value: £{value:.1f}m  |  Bank: £{bank:.1f}m  |  Free transfers used this GW: {hist['event_transfers']}")
    if picks.get("active_chip"):
        print(f"Active chip: {picks['active_chip']}")
    print()

    for p in picks["picks"]:
        el = elements[p["element"]]
        tag = " (C)" if p["is_captain"] else " (VC)" if p["is_vice_captain"] else ""
        bench = " [BENCH]" if p["position"] > 11 else ""
        print(
            f"{p['position']:2d} {types[el['element_type']]:3s} {el['web_name']:20s} "
            f"{teams[el['team']]:15s} £{el['now_cost'] / 10:.1f}m{tag}{bench}"
        )


if __name__ == "__main__":
    main()
