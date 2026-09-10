"""Price rises and falls, from FPL's own projections.

The official API publishes this and we were not reading it. `bootstrap-static`
carries, per player:

    price_change_percent        progress toward a change; +-100 is the threshold
    price_change_projections    projected percent at +0, +1 and +2 days, each with a
                                likelihood from -5 (certain fall) to +5 (certain rise)
    price_change_hourly_rate    current momentum
    price_change_locked_until   set when a player cannot change yet
    price_change_calibrating    set while FPL has not established a baseline

This is the same data the popular price-prediction sites render — one of them says so
outright — so there is no third-party source to add and no scraping to do. The whole
feature is a read of a cache `fetch_data.py` already refreshes every run.

Why it matters for decisions: a transfer plan that buys a player crossing tonight pays
0.1m more for waiting, and one that holds a player about to fall loses 0.1m of squad
value. Neither changes expected points, which is why `decisions.py` correctly ignores
prices for scoring — but both change what it costs to execute the same plan, and that is
worth seeing before pressing the button rather than after.

Usage:
    python scripts/prices.py                 # your squad, plus the sharpest movers
    python scripts/prices.py --watch Palmer --watch Tavernier
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# |percent| at or above this means the threshold is crossed and the change is due.
THRESHOLD = 100.0

# FPL's own scale. The sign gives direction, the magnitude how sure they are.
CONFIDENT = 4


def load_bootstrap() -> dict:
    with open(DATA_DIR / "bootstrap.json") as f:
        return json.load(f)


def outlook(element: dict) -> dict:
    """When this player's price is projected to change, and how firmly.

    `when` is a day offset: 0 is the next nightly change, None means not within the
    three days FPL projects. Reported rather than predicted — the arithmetic is FPL's,
    not ours, and inventing a confidence on top of theirs would only add noise.
    """
    percent = float(element.get("price_change_percent") or 0.0)
    projections = element.get("price_change_projections") or []
    direction = "rise" if percent > 0 else "fall" if percent < 0 else "flat"

    when, likelihood = None, 0
    if abs(percent) >= THRESHOLD:
        when = 0
    for row in sorted(projections, key=lambda r: r["offset"]):
        value = float(row["projected_percent"])
        if when is None and abs(value) >= THRESHOLD:
            when = row["offset"]
        if row["offset"] == 0:
            likelihood = row["likelihood"]
    if projections and when is not None:
        match = next((r for r in projections if r["offset"] == when), None)
        if match:
            likelihood = match["likelihood"]

    return {
        "element": element["id"],
        "name": element.get("web_name"),
        "now_cost": element.get("now_cost"),
        "percent": round(percent, 1),
        "hourly_rate": element.get("price_change_hourly_rate") or 0,
        "direction": direction,
        "when": when,
        "likelihood": likelihood,
        "confident": abs(likelihood) >= CONFIDENT,
        "locked_until": element.get("price_change_locked_until"),
        "calibrating": bool(element.get("price_change_calibrating")),
        "projections": [
            {"offset": r["offset"], "percent": round(float(r["projected_percent"]), 1),
             "likelihood": r["likelihood"]}
            for r in sorted(projections, key=lambda r: r["offset"])
        ],
    }


def by_element(bootstrap: dict | None = None) -> dict[int, dict]:
    bootstrap = bootstrap or load_bootstrap()
    return {row["id"]: outlook(row) for row in bootstrap["elements"]}


def label(row: dict) -> str:
    """One short phrase for a table cell."""
    if row["calibrating"]:
        return "calibrating"
    if row["when"] is None:
        return "—"
    arrow = "up" if row["direction"] == "rise" else "down"
    horizon = {0: "tonight", 1: "1 day", 2: "2 days"}.get(row["when"], f"{row['when']}d")
    return f"{arrow} {horizon}" + ("" if row["confident"] else "?")


def owned_squad(bootstrap: dict) -> set[int]:
    current = json.load(open(DATA_DIR / "entry.json")).get("current_event")
    path = DATA_DIR / f"picks_gw{current}.json"
    if not path.exists():
        return set()
    with open(path) as f:
        return {row["element"] for row in json.load(f)["picks"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watch", action="append", default=[],
                        help="extra player by web name or id; repeatable")
    parser.add_argument("--top", type=int, default=10, help="how many sharpest movers")
    args = parser.parse_args()

    bootstrap = load_bootstrap()
    rows = by_element(bootstrap)
    elements = {row["id"]: row for row in bootstrap["elements"]}
    owned = owned_squad(bootstrap)

    watch: set[int] = set()
    for value in args.watch:
        if value.isdigit():
            watch.add(int(value))
            continue
        hits = [e for e in bootstrap["elements"] if e["web_name"].casefold() == value.casefold()]
        if len(hits) == 1:
            watch.add(hits[0]["id"])
        elif not hits:
            print(f"  (no player called {value!r})")
        else:
            print(f"  ({value!r} is ambiguous: " +
                  ", ".join(f"{h['web_name']} id={h['id']}" for h in hits) + ")")

    def table(title: str, ids) -> None:
        selected = [rows[i] for i in ids if i in rows]
        if not selected:
            return
        selected.sort(key=lambda r: -abs(r["percent"]))
        print(f"\n{title}")
        print(f"  {'player':14}{'£':>5}{'now%':>8}{'/hr':>7}  {'due':<12} projections")
        for row in selected:
            proj = " ".join(f"+{p['offset']}d {p['percent']:>6.1f}%" for p in row["projections"])
            print(f"  {row['name']:14}{row['now_cost'] / 10:5.1f}{row['percent']:8.1f}"
                  f"{row['hourly_rate']:7}  {label(row):<12} {proj}")

    table("YOUR SQUAD", owned)
    if watch:
        table("WATCHING", watch)

    movers = [r for r in rows.values()
              if r["when"] is not None and r["element"] not in owned | watch
              and elements[r["element"]]["minutes"] > 0]
    movers.sort(key=lambda r: (-abs(r["likelihood"]), -abs(r["percent"])))
    table(f"SHARPEST MOVERS ELSEWHERE (top {args.top})",
          [r["element"] for r in movers[:args.top]])

    print("\nFPL's own projections. Changes are applied nightly; offsets are days ahead.")
    print("A '?' means FPL's likelihood is below 4 of 5 — direction without conviction.")


if __name__ == "__main__":
    main()
