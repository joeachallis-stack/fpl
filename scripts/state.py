"""Derived state for the weekly loop: banked free transfers, chip windows, deadlines.

Everything here is reconstructed from cached API responses. There is no hand-maintained
state file, so nothing can drift out of date — re-run fetch_data.py and the numbers move
with it. The rules are read from bootstrap (game_settings, chips) rather than hardcoded,
because FPL reparameterizes them between seasons.

Usage:
    python scripts/state.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Transfers made under these chips are free and leave banked transfers untouched.
UNLIMITED_TRANSFER_CHIPS = {"wildcard", "freehit"}

CHIP_LABELS = {
    "wildcard": "Wildcard",
    "freehit": "Free Hit",
    "bboost": "Bench Boost",
    "3xc": "Triple Captain",
}


def load(name: str) -> dict:
    with open(DATA_DIR / name) as f:
        return json.load(f)


def free_transfers(history: dict, game_settings: dict) -> tuple[int, list[dict]]:
    """Walk the season forward to get transfers banked for the next gameweek.

    The rolling rules are deterministic, so the count never needs to be tracked by hand:
    start on one, spend what was used, accrue one a week up to the cap. Transfers made
    on a wildcard or free hit are free and do not touch the bank.
    """
    cap = 1 + game_settings["max_extra_free_transfers"]
    chip_by_event = {c["event"]: c["name"] for c in history["chips"]}

    banked = 1
    walk = []
    for row in history["current"]:
        gw = row["event"]
        chip = chip_by_event.get(gw)
        used = row["event_transfers"]
        if chip in UNLIMITED_TRANSFER_CHIPS:
            spent = 0
        else:
            spent = min(banked, used)
            banked = max(0, banked - used)
        banked = min(cap, banked + 1)
        walk.append(
            {
                "event": gw,
                "chip": chip,
                "transfers": used,
                "spent_free": spent,
                "hit": row["event_transfers_cost"],
                "banked_after": banked,
            }
        )
    return banked, walk


def chip_windows(bootstrap: dict, history: dict) -> list[dict]:
    """Every chip the season grants, matched against the ones already played."""
    windows = [
        {
            "name": c["name"],
            "start": c["start_event"],
            "stop": c["stop_event"],
            "played_gw": None,
        }
        for c in bootstrap["chips"]
    ]
    for played in history["chips"]:
        for w in windows:
            if (
                w["name"] == played["name"]
                and w["start"] <= played["event"] <= w["stop"]
                and w["played_gw"] is None
            ):
                w["played_gw"] = played["event"]
                break
    return windows


def next_event(bootstrap: dict) -> dict | None:
    for event in bootstrap["events"]:
        if event.get("is_next"):
            return event
    # Season over, or between the last deadline and the final results being finalized.
    return next((e for e in bootstrap["events"] if not e["finished"]), None)


def main() -> None:
    boot = load("bootstrap.json")
    history = load("history.json")

    event = next_event(boot)
    banked, walk = free_transfers(history, boot["game_settings"])
    windows = chip_windows(boot, history)

    if event:
        deadline = datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00"))
        remaining = deadline - datetime.now(timezone.utc)
        hours = remaining.total_seconds() / 3600
        when = f"in {hours:.0f}h" if hours >= 0 else f"{-hours:.0f}h ago (PASSED)"
        print(f"Next: {event['name']}  deadline {deadline:%a %d %b %H:%M} UTC  ({when})")
    else:
        print("No upcoming gameweek.")

    played = history["current"]
    if played:
        latest = played[-1]
        print(
            f"After GW{latest['event']}: {latest['total_points']} pts  |  "
            f"OR {latest['overall_rank']:,}  |  squad £{latest['value'] / 10:.1f}m  "
            f"+ £{latest['bank'] / 10:.1f}m bank"
        )

    cap = 1 + boot["game_settings"]["max_extra_free_transfers"]
    print(f"\nFree transfers banked: {banked} (cap {cap})")
    for row in walk:
        chip = f" [{CHIP_LABELS.get(row['chip'], row['chip'])}]" if row["chip"] else ""
        hit = f"  -{row['hit']} pts" if row["hit"] else ""
        print(
            f"  GW{row['event']:<2d} used {row['transfers']}{chip}"
            f"  -> {row['banked_after']} banked{hit}"
        )

    print("\nChips:")
    for w in windows:
        label = CHIP_LABELS.get(w["name"], w["name"])
        half = f"GW{w['start']}-{w['stop']}"
        if w["played_gw"]:
            print(f"  {label:<15s} {half:<10s} used in GW{w['played_gw']}")
        else:
            expiry = ""
            if event and w["start"] > event["id"]:
                expiry = f"  (window opens GW{w['start']})"
            elif event and w["stop"] >= event["id"]:
                left = w["stop"] - event["id"] + 1
                expiry = f"  ({left} GWs left, expires after GW{w['stop']})"
            elif event:
                expiry = "  EXPIRED"
            print(f"  {label:<15s} {half:<10s} available{expiry}")


if __name__ == "__main__":
    main()
