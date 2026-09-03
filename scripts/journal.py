"""Decision journal: log recommendations, mark whether taken, resolve outcomes.

The only mechanism that tells you a projection was wrong in GW12 instead of GW30.
Entries live in journal/entries.jsonl — tracked in git, unlike data/, because this is
an authored record with value for the whole season, not an API cache.

Score against the counterfactual, not zero: log the alternative that was passed over,
and `resolve` fills in what both actually scored once the gameweek settles.

Usage:
    python scripts/journal.py add --gw 3 --category captain \
        --recommendation "Captain Haaland" --reasoning "..." --confidence medium \
        [--case-against "..."] [--runner-up "Joao Pedro" --runner-up-delta -2.1] \
        [--recommended-element 351 --alternative-element 165] [--taken true]
    python scripts/journal.py mark --id gw3-1 --taken true
    python scripts/journal.py resolve --gw 3
    python scripts/journal.py show [--gw 3] [--open]
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
JOURNAL_PATH = ROOT / "journal" / "entries.jsonl"
DATA_DIR = ROOT / "data"
BASE = "https://fantasy.premierleague.com/api"


def load_entries() -> list[dict]:
    if not JOURNAL_PATH.exists():
        return []
    with open(JOURNAL_PATH) as f:
        return [json.loads(line) for line in f if line.strip()]


def save_entries(entries: list[dict]) -> None:
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(JOURNAL_PATH, "w") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def next_id(entries: list[dict], gw: int) -> str:
    seq = sum(1 for e in entries if e["gw"] == gw) + 1
    return f"gw{gw}-{seq}"


def parse_bool(v: str | None) -> bool | None:
    if v is None:
        return None
    return {"true": True, "false": False}[v.lower()]


def load_elements() -> dict[int, dict]:
    path = DATA_DIR / "bootstrap.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return {e["id"]: e for e in json.load(f)["elements"]}


def element_name(elements: dict, pid: int | None) -> str:
    if pid is None:
        return "?"
    return elements.get(pid, {}).get("web_name", f"#{pid}")


def gw_points(gw: int, player_id: int) -> float | None:
    """A player's actual points in a specific settled gameweek, from event/{gw}/live/.

    Cached after the first pull — this is the only source that gives an exact
    per-gameweek score regardless of whether the player was ever in the cached squad.
    """
    path = DATA_DIR / f"event_live_gw{gw}.json"
    if path.exists():
        with open(path) as f:
            live = json.load(f)
    else:
        resp = requests.get(f"{BASE}/event/{gw}/live/", timeout=15)
        resp.raise_for_status()
        live = resp.json()
        DATA_DIR.mkdir(exist_ok=True)
        with open(path, "w") as f:
            json.dump(live, f)
    for row in live["elements"]:
        if row["id"] == player_id:
            return row["stats"]["total_points"]
    return None


def cmd_add(args: argparse.Namespace) -> None:
    entries = load_entries()
    entry = {
        "id": next_id(entries, args.gw),
        "gw": args.gw,
        "logged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "category": args.category,
        "recommendation": args.recommendation,
        "reasoning": args.reasoning,
        "confidence": args.confidence,
        "case_against": args.case_against,
        "runner_up": args.runner_up,
        "runner_up_delta_pts": args.runner_up_delta,
        "recommended_element": args.recommended_element,
        "alternative_element": args.alternative_element,
        "taken": parse_bool(args.taken),
        "resolved_at": None,
        "actual": None,
    }
    entries.append(entry)
    save_entries(entries)
    print(f"logged {entry['id']}: {entry['recommendation']}")


def cmd_mark(args: argparse.Namespace) -> None:
    entries = load_entries()
    for e in entries:
        if e["id"] == args.id:
            e["taken"] = parse_bool(args.taken)
            save_entries(entries)
            print(f"{args.id}: taken = {e['taken']}")
            return
    raise SystemExit(f"no entry {args.id}")


def cmd_resolve(args: argparse.Namespace) -> None:
    entries = load_entries()
    elements = load_elements()

    targets = [e for e in entries if e["gw"] == args.gw and e["resolved_at"] is None]
    if not targets:
        print(f"nothing unresolved for GW{args.gw}")
        return

    for e in targets:
        actual = {
            "recommended_points": None,
            "alternative_points": None,
            "realized_delta_pts": None,
        }
        rec_id, alt_id = e.get("recommended_element"), e.get("alternative_element")
        if rec_id is not None:
            actual["recommended_points"] = gw_points(args.gw, rec_id)
        if alt_id is not None:
            actual["alternative_points"] = gw_points(args.gw, alt_id)
        if actual["recommended_points"] is not None and actual["alternative_points"] is not None:
            actual["realized_delta_pts"] = round(
                actual["recommended_points"] - actual["alternative_points"], 1
            )
        e["actual"] = actual
        e["resolved_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        line = f"resolved {e['id']}: {e['recommendation']}"
        if rec_id is not None:
            line += f"  [{element_name(elements, rec_id)} {actual['recommended_points']}"
            if alt_id is not None:
                line += f" vs {element_name(elements, alt_id)} {actual['alternative_points']}"
            line += "]"
        if actual["realized_delta_pts"] is not None:
            sign = "+" if actual["realized_delta_pts"] >= 0 else ""
            line += f"  delta {sign}{actual['realized_delta_pts']}"
        print(line)

    save_entries(entries)


def cmd_show(args: argparse.Namespace) -> None:
    entries = load_entries()
    if args.gw is not None:
        entries = [e for e in entries if e["gw"] == args.gw]
    if args.open:
        entries = [e for e in entries if e["resolved_at"] is None]
    if not entries:
        print("no entries")
        return
    for e in entries:
        status = "open" if e["resolved_at"] is None else "resolved"
        taken = {"True": "taken", "False": "declined", "None": "?"}[str(e["taken"])]
        print(
            f"[{e['id']}] GW{e['gw']} {e['category']:10s} {status:9s} {taken:9s} "
            f"conf={e['confidence']}"
        )
        print(f"    {e['recommendation']}")
        if e.get("runner_up"):
            d = e.get("runner_up_delta_pts")
            delta = f" ({d:+.1f} pts)" if d is not None else ""
            print(f"    runner-up: {e['runner_up']}{delta}")
        if e.get("case_against"):
            print(f"    case against: {e['case_against']}")
        if e["actual"] and e["actual"].get("realized_delta_pts") is not None:
            print(f"    realized delta: {e['actual']['realized_delta_pts']:+.1f} pts")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="log a recommendation")
    p_add.add_argument("--gw", type=int, required=True)
    p_add.add_argument(
        "--category", required=True, choices=["captain", "transfer", "chip", "hold", "other"]
    )
    p_add.add_argument("--recommendation", required=True)
    p_add.add_argument("--reasoning", required=True)
    p_add.add_argument("--confidence", default="medium", choices=["low", "medium", "high"])
    p_add.add_argument("--case-against")
    p_add.add_argument("--runner-up")
    p_add.add_argument("--runner-up-delta", type=float)
    p_add.add_argument("--recommended-element", type=int, help="player id, for auto-resolve")
    p_add.add_argument("--alternative-element", type=int, help="player id passed over")
    p_add.add_argument("--taken", choices=["true", "false"])
    p_add.set_defaults(func=cmd_add)

    p_mark = sub.add_parser("mark", help="record whether a recommendation was taken")
    p_mark.add_argument("--id", required=True)
    p_mark.add_argument("--taken", required=True, choices=["true", "false"])
    p_mark.set_defaults(func=cmd_mark)

    p_resolve = sub.add_parser("resolve", help="fill in realized outcomes for a settled GW")
    p_resolve.add_argument("--gw", type=int, required=True)
    p_resolve.set_defaults(func=cmd_resolve)

    p_show = sub.add_parser("show", help="print journal entries")
    p_show.add_argument("--gw", type=int)
    p_show.add_argument("--open", action="store_true", help="unresolved entries only")
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
