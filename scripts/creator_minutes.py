"""Score creators' team-news calls against the frozen minutes model, player by player.

CLAUDE.md asks whether an LLM/news override layer for minutes is worth building. That
question has exactly one honest answer path: take the calls creators made before a
deadline, take what the minutes model froze for the same players before the same
deadline, and see who was right, above all when they disagreed. Agreement is cheap —
both sides say Haaland starts. Disagreement is where an override would change a number.

Both inputs are already tracked in git (`news/findings/`, `minutes/gwNN.jsonl`), so this
script stores nothing of its own and can re-score any gameweek at any time. It only has
to exist before enough weeks pile up to be worth reading.

Calls come from each finding's `minutes_call` field: starts / benched / out / doubt per
player, or null for no call. That is deliberately not `stance`, which is sentiment and
happily marks "played the full 90 last week" as positive.

The binary target is 60+ league minutes, matching the model's `p_60_plus` band and FPL's
appearance-points threshold. `starts` predicts yes; `benched` and `out` predict no;
`doubt` makes no binary call and is only counted. A start that ends at 55 minutes counts
against `starts` — deliberately, because that is what it costs in FPL points.

Usage:
    python scripts/creator_minutes.py              # every gameweek with calls
    python scripts/creator_minutes.py --gw 5       # one gameweek (before resolve: open disagreements)
"""
from __future__ import annotations

import argparse
import collections
import json
from datetime import datetime
from pathlib import Path

import findings
import roster

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MINUTES_DIR = ROOT / "minutes"
OUT_PATH = DATA_DIR / "creator_minutes.json"

PLAYS_60 = {"starts": True, "benched": False, "out": False}


def deadline(gw: int) -> datetime | None:
    with open(DATA_DIR / "bootstrap.json") as f:
        event = next((e for e in json.load(f)["events"] if e["id"] == gw), None)
    return datetime.fromisoformat(event["deadline_time"].replace("Z", "+00:00")) if event else None


def load_archive(gw: int) -> dict[int, dict]:
    path = MINUTES_DIR / f"gw{gw:02d}.jsonl"
    if not path.exists():
        return {}
    with open(path) as f:
        return {row["element"]: row for row in map(json.loads, filter(str.strip, f))}


def collect_calls(gw: int, players: list[dict]) -> tuple[list[dict], collections.Counter]:
    """One call per (creator, player): the latest pre-deadline one, dropped if a single
    video contradicts itself."""
    skipped: collections.Counter = collections.Counter()
    cutoff = deadline(gw)
    latest: dict[tuple[str, int], dict] = {}
    conflicted: set[tuple[str, int]] = set()

    for row in findings.load(gw):
        calls = row.get("minutes_call")
        if not isinstance(calls, dict):
            continue
        published = str(row.get("published", ""))[:10]
        # Publish dates are day-precision. A deadline-day video is kept: it is almost
        # always pre-deadline team selection, and dropping it would lose the best evidence.
        if cutoff and published and published > cutoff.date().isoformat():
            skipped["published after deadline"] += 1
            continue
        for line, call in calls.items():
            if call is None:
                continue
            player = roster.resolve_line(line, players)
            if player is None:
                skipped["unresolved player"] += 1
                continue
            key = (row["source"], player["element"])
            entry = {"gw": gw, "source": row["source"], "element": player["element"],
                     "player": player["web_name"], "team": player["team"], "call": call,
                     "published": published, "video_id": row.get("video_id"),
                     "claim": row.get("claim", "")}
            prior = latest.get(key)
            if prior and prior["video_id"] == entry["video_id"] and prior["call"] != call:
                conflicted.add(key)
            if not prior or published >= prior["published"]:
                latest[key] = entry

    for key in conflicted:
        latest.pop(key, None)
        skipped["self-contradicting video"] += 1
    return list(latest.values()), skipped


def score(gw: int, players: list[dict]) -> dict:
    calls, skipped = collect_calls(gw, players)
    archive = load_archive(gw)
    rows = []
    for call in calls:
        frozen = archive.get(call["element"])
        if frozen is None:
            skipped["no frozen model prediction"] += 1
            continue
        p60 = frozen["bands"]["p_60_plus"]
        actual = frozen.get("actual_minutes")
        creator_60 = PLAYS_60.get(call["call"])
        row = {**call, "model_p60": round(p60, 3), "actual_minutes": actual,
               "disagree": creator_60 is not None and creator_60 != (p60 >= 0.5)}
        if actual is not None and creator_60 is not None:
            played_60 = actual >= 60
            row["creator_right"] = creator_60 == played_60
            row["model_right"] = (p60 >= 0.5) == played_60
        rows.append(row)
    return {"gw": gw, "archived": bool(archive),
            "resolved": any(r.get("actual_minutes") is not None for r in archive.values()),
            "skipped": dict(skipped), "calls": rows}


def summarise(rows: list[dict]) -> dict:
    scored = [r for r in rows if "creator_right" in r]
    split = [r for r in scored if r["disagree"]]
    return {
        "calls": len(rows),
        "scored": len(scored),
        "creator_accuracy": round(sum(r["creator_right"] for r in scored) / len(scored), 3) if scored else None,
        "model_accuracy": round(sum(r["model_right"] for r in scored) / len(scored), 3) if scored else None,
        "disagreements": len(split),
        "disagreements_creator_right": sum(r["creator_right"] for r in split),
        "disagreements_model_right": sum(r["model_right"] for r in split),
    }


def print_report(results: list[dict]) -> None:
    every = [r for result in results for r in result["calls"]]
    for result in results:
        rows = result["calls"]
        state = ("resolved" if result["resolved"] else
                 "frozen, awaiting resolve" if result["archived"] else "no frozen minutes archive yet")
        print(f"GW{result['gw']}: {len(rows)} creator calls matched to the model ({state})")
        if result["skipped"]:
            print("  skipped: " + ", ".join(f"{k} {v}" for k, v in result["skipped"].items()))
        s = summarise(rows)
        if s["scored"]:
            print(f"  60+ minutes calls scored: {s['scored']}  creator right "
                  f"{s['creator_accuracy']:.0%}  model right {s['model_accuracy']:.0%}")
            print(f"  disagreements: {s['disagreements']}  creator right "
                  f"{s['disagreements_creator_right']}  model right {s['disagreements_model_right']}")
        split = sorted((r for r in rows if r["disagree"]), key=lambda r: r["player"])
        for r in split:
            outcome = ("" if r.get("actual_minutes") is None else
                       f"  -> {r['actual_minutes']} min, "
                       f"{'creator' if r['creator_right'] else 'model'} right")
            print(f"    {r['player']:<14} {r['source']:<18} says {r['call']:<8} "
                  f"model p60 {r['model_p60']:.2f}{outcome}")
        print()

    if len(results) > 1:
        s = summarise(every)
        print(f"ALL: {s['scored']} scored calls, {s['disagreements']} disagreements — "
              f"creator right {s['disagreements_creator_right']}, "
              f"model right {s['disagreements_model_right']}")
        by_creator = collections.defaultdict(list)
        for r in every:
            by_creator[r["source"]].append(r)
        for source, rows in sorted(by_creator.items(), key=lambda kv: -len(kv[1])):
            cs = summarise(rows)
            if cs["scored"]:
                print(f"  {source:<20} {cs['scored']:>3} scored  right {cs['creator_accuracy']:.0%}"
                      f"  disagreements {cs['disagreements']} (won {cs['disagreements_creator_right']})")
    print("\nSmall samples: a disagreement tally only means something across several gameweeks.")


def gameweeks_with_calls() -> list[int]:
    gws = {int(p.name[2:4]) for p in findings.FINDINGS_DIR.glob("gw*_*.jsonl")}
    return sorted(gw for gw in gws
                  if any(isinstance(r.get("minutes_call"), dict) for r in findings.load(gw)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gw", type=int)
    args = parser.parse_args()

    players = roster.load_players()
    gws = [args.gw] if args.gw else gameweeks_with_calls()
    results = [score(gw, players) for gw in gws]
    print_report(results)

    if not args.gw:
        with open(OUT_PATH, "w") as f:
            json.dump({"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                       "summary": summarise([r for res in results for r in res["calls"]]),
                       "gameweeks": results}, f, indent=2, ensure_ascii=False)
        print(f"wrote {OUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
