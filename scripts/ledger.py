"""Which videos have been extracted, recorded explicitly rather than inferred.

Reading a transcript is the expensive step in this whole project — a week of long-form
is ~250KB, and an extraction agent costs more than everything else combined. So a video
is read once, ever, and the record of that is a first-class file rather than something
guessed from whatever findings happen to be on disk.

Inferring it from findings has a specific failure: an agent that dies halfway leaves
partial findings behind, and the video then looks finished. Two of four batches died on
a session limit mid-run, which is exactly how that happens. The ledger records the
outcome of an extraction, so a partial one is visible as partial.

It also carries the spec version. The extraction spec keeps improving — the Tzolis trap
and 40-odd aliases were added after the first real run — and a video read under an older
spec may be worth re-reading. That is a judgment call, not automatic, but it can't even
be made if nothing records which version was used.

Usage:
    python scripts/ledger.py show
    python scripts/ledger.py record --video ABC123 --gw 3 --findings 42 --model sonnet
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "news" / "extracted.jsonl"
SPEC_PATH = ROOT / ".claude" / "skills" / "gameweek-brief" / "extraction_spec.md"


def spec_version() -> str:
    """Short hash of the extraction spec, so a run is attributable to the rules it used."""
    if not SPEC_PATH.exists():
        return "unknown"
    return hashlib.sha256(SPEC_PATH.read_bytes()).hexdigest()[:12]


def load() -> dict[str, dict]:
    if not LEDGER_PATH.exists():
        return {}
    entries: dict[str, dict] = {}
    with open(LEDGER_PATH) as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                entries[row["video_id"]] = row  # later record supersedes earlier
    return entries


def record(video_id: str, gw: int, findings: int, model: str, status: str = "complete") -> None:
    row = {
        "video_id": video_id,
        "gw": gw,
        "findings": findings,
        "model": model,
        "status": status,
        "spec_version": spec_version(),
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a") as f:
        f.write(json.dumps(row) + "\n")


def is_done(video_id: str, entries: dict[str, dict] | None = None) -> bool:
    entry = (entries if entries is not None else load()).get(video_id)
    return bool(entry) and entry["status"] == "complete"


def backfill_from_findings() -> int:
    """Seed the ledger from findings already on disk, for videos extracted before it existed."""
    from collections import Counter

    counts: Counter = Counter()
    gws: dict[str, int] = {}
    for path in (ROOT / "news" / "findings").glob("gw*_*.jsonl"):
        # The gameweek lives in the filename, not the findings — a finding records what
        # was said, not which gameweek's brief it was gathered for.
        match = re.match(r"gw(\d+)_", path.name)
        gw = int(match.group(1)) if match else 0
        with open(path) as f:
            for line in f:
                if line.strip():
                    row = json.loads(line)
                    counts[row["video_id"]] += 1
                    gws[row["video_id"]] = gw

    existing = load()
    added = 0
    for video_id, n in counts.items():
        if video_id in existing:
            continue
        record(video_id, gws[video_id], n, model="opus", status="complete")
        added += 1
    return added


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("show")
    sub.add_parser("backfill", help="seed from findings extracted before the ledger existed")
    p_rec = sub.add_parser("record")
    p_rec.add_argument("--video", required=True)
    p_rec.add_argument("--gw", type=int, required=True)
    p_rec.add_argument("--findings", type=int, required=True)
    p_rec.add_argument("--model", default="sonnet")
    p_rec.add_argument("--status", default="complete", choices=["complete", "partial", "failed"])
    args = parser.parse_args()

    if args.command == "record":
        record(args.video, args.gw, args.findings, args.model, args.status)
        print(f"recorded {args.video}")
        return
    if args.command == "backfill":
        print(f"backfilled {backfill_from_findings()} videos from existing findings")
        return

    entries = load()
    if not entries:
        print("ledger empty")
        return
    current = spec_version()
    print(f"{len(entries)} videos extracted   (current spec {current})\n")
    print(f"{'video':<14}{'gw':>3}{'found':>7}  {'model':<8}{'status':<10}spec")
    for row in sorted(entries.values(), key=lambda r: (r["gw"], r["video_id"])):
        stale = "" if row["spec_version"] == current else "  <- older spec"
        print(f"{row['video_id']:<14}{row['gw']:>3}{row['findings']:>7}  "
              f"{row['model']:<8}{row['status']:<10}{row['spec_version'][:8]}{stale}")


if __name__ == "__main__":
    main()
