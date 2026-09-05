"""Append finalized player-fixture facts to the immutable observation ledger."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
LEDGER = ROOT / "observations" / "player_fixtures.jsonl"

STAT_FIELDS = (
    "minutes", "starts", "total_points", "goals_scored", "assists", "clean_sheets",
    "goals_conceded", "own_goals", "penalties_saved", "penalties_missed",
    "yellow_cards", "red_cards", "saves", "bonus", "bps", "tackles",
    "recoveries", "clearances_blocks_interceptions", "defensive_contribution",
    "expected_goals", "expected_assists", "expected_goal_involvements",
    "expected_goals_conceded",
)


def load_json(path: Path) -> dict | list:
    return json.loads(path.read_text())


def key(row: dict) -> tuple[str, int, int]:
    return row["season"], row["fixture_id"], row["element"]


def build_rows() -> list[dict]:
    bootstrap = load_json(DATA_DIR / "bootstrap.json")
    config = load_json(ROOT / "config.json")
    fixtures = {row["id"]: row for row in load_json(DATA_DIR / "fixtures.json")}
    finalized = {
        event["id"] for event in bootstrap["events"]
        if event.get("finished") and event.get("data_checked")
    }
    types = {row["id"]: row["singular_name_short"] for row in bootstrap["element_types"]}
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for player in bootstrap["elements"]:
        path = DATA_DIR / f"element_summary/{player['id']}.json"
        if not path.exists():
            continue
        for history in load_json(path)["history"]:
            if history["round"] not in finalized:
                continue
            fixture = fixtures.get(history["fixture"])
            if not fixture or not fixture.get("finished"):
                continue
            position = types[player["element_type"]]
            threshold = 10 if position == "DEF" else 12
            actions = history.get("tackles", 0) + history.get("clearances_blocks_interceptions", 0)
            if position in {"MID", "FWD"}:
                actions += history.get("recoveries", 0)
            row = {
                "season": config["season"],
                "gw": history["round"],
                "fixture_id": history["fixture"],
                "element": player["id"],
                "element_code": player["code"],
                "web_name": player["web_name"],
                "position": position,
                "team": fixture["team_h"] if history["was_home"] else fixture["team_a"],
                "opponent_team": history["opponent_team"],
                "was_home": history["was_home"],
                "kickoff_time": history["kickoff_time"],
                "reached_60": history["minutes"] >= 60,
                "defcon_actions": actions if position != "GKP" else 0,
                "defcon_threshold": threshold if position != "GKP" else None,
                "defcon_hit": actions >= threshold if position != "GKP" else False,
                "recorded_at": recorded_at,
                "revision": 1,
            }
            row.update({field: history.get(field) for field in STAT_FIELDS})
            rows.append(row)
    return sorted(rows, key=key)


def append_finalized() -> tuple[int, int]:
    existing = [json.loads(line) for line in LEDGER.read_text().splitlines()] if LEDGER.exists() else []
    latest = {}
    for row in existing:
        latest[key(row)] = row
    additions = []
    for row in build_rows():
        previous = latest.get(key(row))
        if previous is None:
            additions.append(row)
            latest[key(row)] = row
            continue
        comparable = {k: v for k, v in row.items() if k not in {"recorded_at", "revision"}}
        prior_comparable = {k: v for k, v in previous.items() if k not in {"recorded_at", "revision"}}
        if comparable != prior_comparable:
            row["revision"] = previous["revision"] + 1
            row["supersedes_revision"] = previous["revision"]
            additions.append(row)
            latest[key(row)] = row
    if additions:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        with LEDGER.open("a") as handle:
            for row in additions:
                handle.write(json.dumps(row) + "\n")
    print(f"observations: appended {len(additions)}, {len(latest)} finalized player-fixtures total")
    return len(additions), len(latest)


if __name__ == "__main__":
    append_finalized()
