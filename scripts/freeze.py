"""Keep the measurement record correct without anyone remembering to: freeze, then resolve.

Run this on a timer, not by hand. A projection archived after a deadline has seen the
result: element_summary gains the played gameweek, the minutes model retrains on it,
odds move, prices change. The archives refuse to overwrite for that reason, so a missed
deadline is a permanent hole in the track record rather than a slightly worse forecast.

The fixture calendar cannot be written as a crontab — GW5 is 18 Sep and GW6 is 10 Oct —
so this does the opposite: it runs often and almost always does nothing. Each run reads
the next deadline, exits immediately if it is far away, and otherwise archives only what
is missing. Repeated runs are safe, and a run missed while the laptop slept costs
nothing because the next one catches up.

Running from FREEZE_LEAD_HOURS out means the *latest successful* attempt is what gets
kept. Freezing at T-11h on staler team news is worse than freezing at T-2h, and far
better than not freezing at all.

Two phases, with opposite timing constraints.

The freeze must happen *before* a deadline and can never be redone, so it is the reason
this runs on a timer at all. Resolving is the mirror image: it can only happen *after* a
gameweek finalizes, and is safe to run late or repeatedly. Both are here because
automating only the freeze produces the failure this project already had — a pile of
perfect frozen forecasts that nothing ever scores, and an empty evaluation.

Usage:
    python scripts/freeze.py                 # what the timer runs: freeze, then resolve
    python scripts/freeze.py --status        # report only, change nothing
    python scripts/freeze.py --force         # ignore the lead window (still no overwrite)
    python scripts/freeze.py --resolve-only  # skip the freeze phase
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import state

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LOG_PATH = DATA_DIR / "freeze.log"

# Start trying half a day out. Long enough to survive a closed laptop, late enough that
# most team news has landed.
FREEZE_LEAD_HOURS = 12
# Refresh inputs when the cache is older than this, so the deadline we read is honest and
# the observation ledger keeps up with finalized gameweeks.
CACHE_MAX_AGE_H = 6

# Each archive command and the file it is responsible for creating.
STEPS = (
    ("minutes", "minutes.py", lambda gw: ROOT / "minutes" / f"gw{gw:02d}.jsonl"),
    ("projections", "projections.py", lambda gw: ROOT / "projections" / f"gw{gw:02d}.json"),
    ("decisions", "decisions.py", lambda gw: ROOT / "decisions" / f"gw{gw:02d}.json"),
)


def log(message: str) -> None:
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    line = f"{stamp}  {message}"
    print(line)
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a") as handle:
        handle.write(line + "\n")


def cache_age_hours() -> float:
    path = DATA_DIR / "bootstrap.json"
    if not path.exists():
        return float("inf")
    age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
    return age / 3600


def run_script(script: str, *args: str) -> tuple[bool, str]:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    output = (result.stdout + result.stderr).strip()
    return result.returncode == 0, output


def next_deadline() -> tuple[int, datetime] | None:
    bootstrap = json.loads((DATA_DIR / "bootstrap.json").read_text())
    event = state.next_event(bootstrap)
    if not event:
        return None
    deadline = datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00"))
    return event["id"], deadline


def missing_steps(gw: int) -> list[tuple[str, str]]:
    return [(name, script) for name, script, path in STEPS if not path(gw).exists()]


def finalized_gameweeks() -> list[int]:
    """Gameweeks FPL considers settled — same test observations.py uses to append."""
    bootstrap = json.loads((DATA_DIR / "bootstrap.json").read_text())
    return sorted(
        event["id"] for event in bootstrap["events"]
        if event.get("finished") and event.get("data_checked")
    )


def _json_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def minutes_unresolved(gw: int) -> bool:
    path = ROOT / "minutes" / f"gw{gw:02d}.jsonl"
    if not path.exists():
        return False
    # resolve() cannot fill every row — a player with no history stays None — so the
    # question is whether it has run at all, not whether every row is populated.
    return not any(row.get("actual_minutes") is not None for row in _json_rows(path))


def projections_unresolved(gw: int) -> bool:
    path = ROOT / "projections" / f"gw{gw:02d}.json"
    if not path.exists():
        return False
    payload = json.loads(path.read_text())
    return not any("actual_points" in row for row in payload.get("players", {}).values())


def journal_unresolved(gw: int) -> bool:
    path = ROOT / "journal" / "entries.jsonl"
    if not path.exists():
        return False
    return any(row.get("gw") == gw and row.get("resolved_at") is None
               for row in _json_rows(path))


RESOLVE_STEPS = (
    ("minutes", "minutes.py", minutes_unresolved),
    ("projections", "projections.py", projections_unresolved),
    ("journal", "journal.py", journal_unresolved),
)


def pending_resolves() -> list[tuple[int, str, str]]:
    return [
        (gw, name, script)
        for gw in finalized_gameweeks()
        for name, script, unresolved in RESOLVE_STEPS
        if unresolved(gw)
    ]


def resolve_settled() -> bool:
    """Score every finalized gameweek that still has an unresolved record."""
    pending = pending_resolves()
    if not pending:
        return False
    for gw, name, script in pending:
        ok, output = run_script(script, "resolve", "--gw", str(gw))
        if ok:
            log(f"  resolved {name} GW{gw}")
        else:
            log(f"  resolve {name} GW{gw} FAILED — "
                f"{output.splitlines()[-1] if output else 'no output'}")
    ok, output = run_script("evaluate.py")
    log("  refreshed data/evaluation.json" if ok
        else f"  evaluate FAILED — {output.splitlines()[-1] if output else 'no output'}")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true", help="report only, change nothing")
    parser.add_argument("--force", action="store_true", help="ignore the lead-hours window")
    parser.add_argument("--resolve-only", action="store_true", help="skip the freeze phase")
    args = parser.parse_args()

    if not (DATA_DIR / "bootstrap.json").exists():
        log("no bootstrap cache — running a full fetch first")
        run_script("fetch_data.py")

    upcoming = next_deadline()
    if not upcoming:
        log("no upcoming deadline (season over or awaiting finalization) — nothing to do")
        return
    gw, deadline = upcoming
    hours = (deadline - datetime.now(timezone.utc)).total_seconds() / 3600

    outstanding = missing_steps(gw)
    if args.status:
        done = [name for name, _, path in STEPS if path(gw).exists()]
        pending = pending_resolves()
        print(f"GW{gw} deadline {deadline:%a %d %b %H:%M} UTC ({hours:.1f}h away)")
        print(f"  archived: {', '.join(done) if done else 'none'}")
        print(f"  missing:  {', '.join(n for n, _ in outstanding) if outstanding else 'none'}")
        print(f"  cache age: {cache_age_hours():.1f}h")
        print(f"  finalized gameweeks: "
              f"{', '.join(str(g) for g in finalized_gameweeks()) or 'none'}")
        print(f"  awaiting resolve: "
              f"{', '.join(f'{n} GW{g}' for g, n, _ in pending) if pending else 'none'}")
        return

    if args.resolve_only or hours < 0 or not outstanding or (
        hours > FREEZE_LEAD_HOURS and not args.force
    ):
        # Nothing to freeze — either too early, already done, or too late. Resolving has
        # no deadline, so it still gets its turn.
        if hours < 0 and outstanding and not args.resolve_only:
            log(f"GW{gw} deadline has passed — refusing to archive after the fact")
        if resolve_settled():
            log("resolved settled gameweeks")
        return

    log(f"GW{gw} deadline in {hours:.1f}h — freezing {', '.join(n for n, _ in outstanding)}")

    age = cache_age_hours()
    if age > CACHE_MAX_AGE_H:
        ok, output = run_script("fetch_data.py")
        if not ok:
            # Freezing on a stale cache still beats no archive at all.
            log(f"fetch_data failed, continuing on a {age:.1f}h-old cache: {output[-300:]}")
        else:
            log(f"refreshed inputs (cache was {age:.1f}h old)")

    for name, script in outstanding:
        ok, output = run_script(script, "archive")
        if ok:
            log(f"  {name}: archived")
        else:
            # One refusal must not block the others — projections declines a partial
            # gameweek of odds, and a minutes archive is still worth having.
            log(f"  {name}: FAILED — {output.splitlines()[-1] if output else 'no output'}")

    still_missing = [name for name, _ in missing_steps(gw)]
    if still_missing:
        log(f"GW{gw} still missing: {', '.join(still_missing)} — will retry next run")
    else:
        log(f"GW{gw} fully frozen")

    if resolve_settled():
        log("resolved settled gameweeks")


if __name__ == "__main__":
    main()
