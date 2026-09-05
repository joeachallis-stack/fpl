"""Pretty-print the cached squad + team summary. Run fetch_data.py first."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PRICE_WATCH_LIKELIHOOD = 4


def load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def price_watch_line(element: dict) -> str | None:
    """Summarise the earliest strong native FPL price-change projection."""
    projections = element.get("price_change_projections") or []
    actionable = [
        projection
        for projection in projections
        if abs(projection.get("likelihood", 0)) >= PRICE_WATCH_LIKELIHOOD
    ]
    if not actionable:
        return None

    projection = min(actionable, key=lambda item: item["offset"])
    likelihood = projection["likelihood"]
    direction = "rise" if likelihood > 0 else "fall"
    timing = "today" if projection["offset"] == 0 else f"+{projection['offset']}d"
    net_transfers = element.get("transfers_in_event", 0) - element.get(
        "transfers_out_event", 0
    )
    locked_until = element.get("price_change_locked_until")
    lock_note = f" | locked until {locked_until}" if locked_until else ""

    return (
        f"  {element['web_name']:20s} £{element['now_cost'] / 10:.1f}m  "
        f"{direction} {timing}: {float(projection['projected_percent']):+.1f}% "
        f"(likelihood {likelihood:+d}) | net transfers {net_transfers:+,}{lock_note}"
    )


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

    price_watch = [
        line
        for pick in picks["picks"]
        if (line := price_watch_line(elements[pick["element"]])) is not None
    ]
    if price_watch:
        print(f"\nPrice watch (official FPL projection, |likelihood| >= {PRICE_WATCH_LIKELIHOOD}):")
        print("\n".join(price_watch))


if __name__ == "__main__":
    main()
