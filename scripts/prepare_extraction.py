"""Work out what still needs extracting, and write the agents' inputs.

Everything here exists to stop agents doing work that doesn't pay. In order of what
it saves:

  relevance    two thirds of the corpus is a settled gameweek, a prior season, or World
               Cup Fantasy. Reading it costs the same as reading current advice and is
               worth nothing — worse than nothing, since stale captaincy calls read as
               current ones.
  already done a video is extracted once, ever. After the first run only new uploads
               cost anything.
  shorts       11 of 20 GW3 videos are Shorts, but they are 8% of the text. Spread
               across batches they each pay ~5k tokens of spec-and-roster overhead to
               read 2KB. Grouped into one agent they pay it once.
  roster trim  261 of 652 players have no minutes and under 1% ownership. Nobody
               discusses them, and they are 40% of the roster file every agent reads.

Usage:
    python scripts/prepare_extraction.py --gw 3
    python scripts/prepare_extraction.py --gw 3 --out /tmp/scratch
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import claims
import ledger
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FINDINGS_DIR = ROOT / "news" / "findings"

# Below this a transcript is a Short — a 60-second clip, often a near-verbatim excerpt
# of the creator's long-form video from the same day.
SHORT_BYTES = 3000

# A player with no minutes and negligible ownership is not being discussed by anyone.
ROSTER_MIN_OWNED = 1.0

# Roughly balanced batches of long-form. More batches means more repeated overhead, so
# this stays small.
LONG_BATCHES = 3


def already_extracted() -> set[str]:
    """Ask the ledger, not the findings files.

    Inferring "done" from findings on disk mistakes a half-finished batch for a finished
    one — an agent that dies mid-run leaves partial findings behind, and the videos it
    never reached look identical to the ones it did. Two batches died on a session limit
    exactly that way. The ledger records outcomes, so partial is visible as partial.
    """
    entries = ledger.load()
    return {vid for vid, row in entries.items() if row["status"] == "complete"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gw", type=int, required=True)
    parser.add_argument("--out", default=None, help="Where to write roster.txt (default: news/)")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else ROOT / "news"
    out_dir.mkdir(parents=True, exist_ok=True)

    with open(DATA_DIR / "bootstrap.json") as f:
        events = json.load(f)["events"]

    entries = []
    with open(ROOT / "news" / "entries.jsonl") as f:
        for line in f:
            row = json.loads(line)
            if row.get("transcript_file") and os.path.exists(row["transcript_file"]):
                entries.append(row)

    done = already_extracted()
    skipped = {"not_current": 0, "already_done": 0}
    todo = []
    for row in entries:
        verdict = claims.relevance(row["title"], row["published"], events)
        if verdict["verdict"] != "current" or verdict["gw"] != args.gw:
            skipped["not_current"] += 1
            continue
        if row["video_id"] in done:
            skipped["already_done"] += 1
            continue
        todo.append((os.path.getsize(row["transcript_file"]), row))

    print(f"corpus: {len(entries)} transcripts")
    print(f"  skipped, not GW{args.gw}: {skipped['not_current']}")
    print(f"  skipped, already extracted: {skipped['already_done']}")
    print(f"  to extract: {len(todo)}")
    if not todo:
        print("\nnothing to do.")
        return

    players = roster.load_players()
    kept = [p for p in players if p["minutes"] > 0 or p["owned"] >= ROSTER_MIN_OWNED]
    roster_path = out_dir / "roster.txt"
    roster_path.write_text("\n".join(roster.roster_names(kept)) + "\n")
    print(f"\nwrote {roster_path} — {len(kept)} of {len(players)} players "
          f"({roster_path.stat().st_size / 1024:.0f}KB)")

    shorts = [(s, r) for s, r in todo if s < SHORT_BYTES]
    longs = sorted([(s, r) for s, r in todo if s >= SHORT_BYTES], reverse=True)

    bins: list[list[tuple[int, dict]]] = [[] for _ in range(LONG_BATCHES)]
    totals = [0] * LONG_BATCHES
    for size, row in longs:
        i = totals.index(min(totals))
        bins[i].append((size, row))
        totals[i] += size

    batches = [b for b in bins if b]
    if shorts:
        batches.append(shorts)  # all Shorts together — they pay the overhead once

    print(f"\n{len(batches)} batches:")
    for n, batch in enumerate(batches, 1):
        kb = sum(s for s, _ in batch) / 1024
        kind = "shorts" if batch is shorts else "long-form"
        print(f"\n  BATCH {n} ({kind}): {len(batch)} videos, {kb:.0f}KB")
        for size, row in batch:
            print(f"     {row['transcript_file']} | {row['video_id']} | {row['source']} "
                  f"| {row['published'][:10]} | {row['title'][:46]}")


if __name__ == "__main__":
    main()
