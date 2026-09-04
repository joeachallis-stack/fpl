"""Merge extracted findings, validate them, and print a consensus brief.

The extraction agents produce claims. This is where those claims meet the data:

    1. every player name is resolved against the roster (scripts/roster.py)
    2. every checkable claim is tested against the record (scripts/claims.py)
    3. what survives is grouped by player, so agreement and disagreement are visible

Point 3 is the reason for doing any of this. One creator liking a player is an opinion;
six creators independently liking him, with one dissenting strongly, is information — and
that only shows up once the claims are lined up next to each other.

Usage:
    python scripts/consolidate.py --gw 3
    python scripts/consolidate.py --gw 3 --owned      # only the current squad
"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

import claims
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FINDINGS_DIR = ROOT / "news" / "findings"

STANCE_MARK = {"positive": "+", "negative": "-", "neutral": "="}


def load_findings(gw: int) -> list[dict]:
    rows = []
    for path in sorted(FINDINGS_DIR.glob(f"gw{gw:02d}_*.jsonl")):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def owned_elements() -> set[int]:
    with open(DATA_DIR / "entry.json") as f:
        current = json.load(f).get("current_event")
    path = DATA_DIR / f"picks_gw{current}.json"
    if not path.exists():
        return set()
    with open(path) as f:
        return {p["element"] for p in json.load(f)["picks"]}


def annotate(rows: list[dict], gw: int) -> tuple[list[dict], list[str]]:
    """Resolve names and check claims. Returns annotated findings and unresolved names."""
    players = roster.load_players()
    unresolved: list[str] = []

    for row in rows:
        resolved = []
        for name in row.get("players", []):
            player = roster.resolve_line(name, players)
            if player is None:
                unresolved.append(name)
                continue
            resolved.append(player)
        row["resolved"] = resolved
        row["unresolved"] = row.get("unresolved", [])

        # The claim check runs against the PREVIOUS gameweek, because a factual claim in
        # pre-deadline advice is describing what already happened, not what is to come.
        row["checks"] = []
        for player in resolved:
            for result in claims.check(row.get("claim", ""), player["element"], gw - 1):
                row["checks"].append({"player": player["web_name"], **result})

        unresolved.extend(row["unresolved"])
    return rows, unresolved


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    parser.add_argument("--owned", action="store_true", help="Only the current squad")
    args = parser.parse_args()

    rows = load_findings(args.gw)
    if not rows:
        raise SystemExit(f"no findings in {FINDINGS_DIR}/gw{args.gw:02d}_*.jsonl")
    rows, unresolved = annotate(rows, args.gw)

    owned = owned_elements()
    sources = {r["source"] for r in rows}
    print(f"GW{args.gw}: {len(rows)} findings from {len(sources)} creators "
          f"across {len({r['video_id'] for r in rows})} videos\n")

    contradictions = [c for r in rows for c in r["checks"] if c["verdict"] == "CONTRADICTED"]
    if contradictions:
        print(f"!! {len(contradictions)} claims contradicted by the record — "
              f"likely misattributed. Check these before trusting them:")
        for row in rows:
            for check in row["checks"]:
                if check["verdict"] == "CONTRADICTED":
                    rec = check["record"]
                    print(f"   {check['player']:<14} claimed '{check['assertion']}' but "
                          f"GW{args.gw - 1} record is {rec['minutes']}min, "
                          f"{rec['goals']}g {rec['assists']}a, {rec['yellow']} yellow")
                    print(f"      \"{row['claim'][:88]}\"")
        print()

    # Group by player so agreement is visible rather than buried in a list of quotes.
    by_player: dict[int, list[tuple[dict, dict]]] = collections.defaultdict(list)
    for row in rows:
        for player in row["resolved"]:
            by_player[player["element"]].append((player, row))

    def sort_key(item):
        element, entries = item
        is_owned = element in owned
        return (not is_owned, -len({r["source"] for _, r in entries}), -len(entries))

    for element, entries in sorted(by_player.items(), key=sort_key):
        if args.owned and element not in owned:
            continue
        player = entries[0][0]
        creators = {r["source"] for _, r in entries}
        if len(entries) < 2 and not args.owned:
            continue
        stances = collections.Counter(r.get("stance") for _, r in entries)
        tag = " [OWNED]" if element in owned else ""
        split = " ".join(f"{STANCE_MARK.get(k, '?')}{v}" for k, v in stances.most_common())
        print(f"{player['web_name']} ({player['team']}, {player['position']}) "
              f"£{player['now_cost']}m{tag}")
        print(f"   {len(entries)} mentions, {len(creators)} creators   {split}")
        for _, row in sorted(entries, key=lambda e: e[1].get("published", ""), reverse=True)[:4]:
            mark = STANCE_MARK.get(row.get("stance"), "?")
            print(f"     {mark} [{row['source']}/{row.get('conviction', '?')}] {row['claim'][:96]}")
        print()

    if unresolved:
        counts = collections.Counter(unresolved)
        print(f"unresolved names ({len(counts)} distinct) — candidates for news/aliases.json:")
        for name, n in counts.most_common(12):
            print(f"   {n:>2}x  {name[:70]}")


if __name__ == "__main__":
    main()
