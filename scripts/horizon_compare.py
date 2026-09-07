"""Build an independent 2-GW versus 6-GW decision comparison without touching caches.

The canonical six-week projection already contains the weekly forecasts needed for a
two-week decision search. This script takes an explicit two-week view of that same
projection snapshot, runs decisions.build() against a temporary data directory, and
cross-scores the union of both optimizers' candidates over both horizons.

It never calls a canonical archive command and never writes data/minutes.json,
data/projections.json or data/decisions.json. The only durable output is
data/horizon_comparison.json, written after a before/after non-mutation check.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decisions
import minutes
import projections

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
OUT = DATA_DIR / "horizon_comparison.json"
SCHEMA_VERSION = "horizon-comparison-v1"
HORIZONS = (2, 6)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_manifest(manifest: dict[str, str]) -> str:
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def protected_manifest(root: Path = ROOT) -> dict[str, str]:
    """Hash canonical mutable outputs and immutable archives.

    horizon_comparison.json is intentionally excluded: it is the one file this script
    owns. Temporary comparison directories are excluded by living under /tmp.
    """
    paths = [
        root / "data" / "minutes.json",
        root / "data" / "projections.json",
        root / "data" / "decisions.json",
    ]
    for directory_name in ("minutes", "projections", "decisions"):
        directory = root / directory_name
        if directory.exists():
            paths.extend(path for path in directory.rglob("*") if path.is_file())
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(paths)
        if path.exists()
    }


def input_manifest(root: Path = ROOT) -> dict[str, str]:
    """Hash every file the comparison itself reads."""
    data = root / "data"
    required = [
        data / "bootstrap.json",
        data / "entry.json",
        data / "history.json",
        data / "transfers.json",
        data / "projections.json",
        data / "decisions.json",
    ]
    entry = json.loads((data / "entry.json").read_text())
    required.append(data / f"picks_gw{entry.get('current_event')}.json")
    summaries = data / "element_summary"
    if summaries.exists():
        required.extend(path for path in summaries.glob("*.json") if path.is_file())
    missing = [path for path in required if not path.exists()]
    if missing:
        names = ", ".join(str(path.relative_to(root)) for path in missing)
        raise SystemExit(f"comparison inputs missing: {names}")
    return {
        str(path.relative_to(root)): _sha256(path)
        for path in sorted(required)
    }


def truncate_projection(payload: dict, horizon: int = 2) -> dict:
    """Return an explicit short-horizon view without mutating the source payload."""
    if payload.get("meta", {}).get("horizon", 0) < horizon:
        raise SystemExit(f"projection artifact does not contain {horizon} gameweeks")
    short = copy.deepcopy(payload)
    discount = float(short["meta"]["horizon_discount"])
    short["meta"]["horizon"] = horizon
    short["meta"]["comparison_view"] = (
        f"first {horizon} weekly forecasts from the canonical six-week artifact; "
        "weekly values are unchanged"
    )
    for player in short["players"].values():
        weeks = player.get("gameweeks", [])[:horizon]
        player["gameweeks"] = weeks
        player["horizon_xP"] = round(
            sum((discount**index) * float(row["xP"]) for index, row in enumerate(weeks)),
            3,
        )
    return short


def _prepare_decision_data(source: Path, target: Path, projection: dict) -> None:
    target.mkdir(parents=True)
    for name in ("bootstrap.json", "entry.json", "history.json", "transfers.json"):
        shutil.copy2(source / name, target / name)
    entry = json.loads((source / "entry.json").read_text())
    picks = f"picks_gw{entry.get('current_event')}.json"
    shutil.copy2(source / picks, target / picks)
    shutil.copytree(source / "element_summary", target / "element_summary")
    (target / "projections.json").write_text(json.dumps(projection, indent=2) + "\n")


def _short_decisions(root: Path, projection: dict, temporary: Path) -> dict:
    """Run the unchanged optimizer with all possible writes redirected to scratch."""
    decision_data = temporary / "decision-data"
    _prepare_decision_data(root / "data", decision_data, projection)

    original_decision_data, original_decision_out = decisions.DATA_DIR, decisions.OUT
    original_projection_out, original_minutes_out = projections.OUT, minutes.OUT
    try:
        decisions.DATA_DIR = decision_data
        decisions.OUT = temporary / "decisions-2.json"
        # These should not be used because the supplied projection has horizon=2. Keep
        # them redirected anyway so a future internal change cannot hit canonical files.
        projections.OUT = temporary / "projections-unexpected.json"
        minutes.OUT = temporary / "minutes-unexpected.json"
        return decisions.build(horizon=2, include_chips=False)
    finally:
        decisions.DATA_DIR, decisions.OUT = original_decision_data, original_decision_out
        projections.OUT, minutes.OUT = original_projection_out, original_minutes_out


def _all_transfer_plans(payload: dict) -> list[dict]:
    return [
        plan
        for plans in payload.get("transfers", {}).values()
        for plan in plans
    ]


def _cross_score(
    plan: dict,
    projection: dict,
    horizon: int,
    hold_xp: float,
    bootstrap: dict,
) -> dict:
    players = decisions.live_optimizer_players(projection)
    rules = {
        row["singular_name_short"]: (row["squad_min_play"], row["squad_max_play"])
        for row in bootstrap["element_types"]
        if row["singular_name_short"] != "GKP"
    }
    horizon_xp, adjusted_xp, lineups = decisions.score_squad(
        tuple(plan["squad"]), players, horizon,
        float(projection["meta"]["horizon_discount"]), rules,
    )
    hit = float(plan.get("points_hit", 0))
    return {
        "horizon_xP": horizon_xp,
        "availability_adjusted_horizon_xP": adjusted_xp,
        "gain_vs_hold": round(horizon_xp - hold_xp, 3),
        "gain_after_hits": round(horizon_xp - hold_xp - hit, 3),
        "lineups": lineups,
    }


def _candidate_rows(short_decisions: dict, long_decisions: dict, projections_by_horizon: dict[int, dict], bootstrap: dict) -> tuple[dict, list[dict]]:
    payloads = {2: short_decisions, 6: long_decisions}
    sources: dict[tuple[int, ...], dict] = {}
    source_horizons: dict[tuple[int, ...], set[int]] = {}
    for horizon, payload in payloads.items():
        for plan in _all_transfer_plans(payload):
            key = tuple(sorted(plan["squad"]))
            source_horizons.setdefault(key, set()).add(horizon)
            if key not in sources or horizon == 6:
                sources[key] = plan

    hold_plan = long_decisions["hold"]
    hold_scores = {
        str(horizon): _cross_score(
            hold_plan,
            projection,
            horizon,
            float(payloads[horizon]["hold"]["horizon_xP"]),
            bootstrap,
        )
        for horizon, projection in projections_by_horizon.items()
    }
    hold = {"id": "hold", "plan": hold_plan, "sourceHorizons": [2, 6], "scores": hold_scores}

    rows = []
    for key, plan in sources.items():
        scores = {
            str(horizon): _cross_score(
                plan,
                projection,
                horizon,
                float(payloads[horizon]["hold"]["horizon_xP"]),
                bootstrap,
            )
            for horizon, projection in projections_by_horizon.items()
        }
        fingerprint = hashlib.sha256(",".join(map(str, key)).encode()).hexdigest()[:10]
        rows.append({
            "id": f"candidate-{fingerprint}",
            "plan": plan,
            "sourceHorizons": sorted(source_horizons[key]),
            "scores": scores,
        })

    for horizon in HORIZONS:
        ordered = sorted(rows, key=lambda row: -row["scores"][str(horizon)]["gain_after_hits"])
        for rank, row in enumerate(ordered, 1):
            row.setdefault("ranks", {})[str(horizon)] = rank
    rows.sort(key=lambda row: (min(row["ranks"].values()), sum(row["ranks"].values())))
    return hold, rows


def build_comparison(root: Path = ROOT, output: Path | None = None) -> dict:
    data = root / "data"
    output = output or data / "horizon_comparison.json"
    resolved_root, resolved_output = root.resolve(), output.resolve()
    canonical_output = (data / "horizon_comparison.json").resolve()
    if resolved_output.is_relative_to(resolved_root) and resolved_output != canonical_output:
        raise ValueError("comparison may not write any in-repository path except data/horizon_comparison.json")
    before_protected = protected_manifest(root)
    before_inputs = input_manifest(root)

    projection_6 = json.loads((data / "projections.json").read_text())
    decisions_6 = json.loads((data / "decisions.json").read_text())
    target_gw = projection_6.get("meta", {}).get("gw")
    if decisions_6.get("meta", {}).get("gw") != target_gw:
        raise SystemExit("projection and decision artifacts target different gameweeks")
    if projection_6.get("meta", {}).get("horizon") != 6 or decisions_6.get("meta", {}).get("horizon") != 6:
        raise SystemExit("canonical artifacts must both use the six-gameweek horizon")

    projection_2 = truncate_projection(projection_6, 2)
    with tempfile.TemporaryDirectory(prefix="fpl-horizon-") as directory:
        decisions_2 = _short_decisions(root, projection_2, Path(directory))

    after_inputs = input_manifest(root)
    after_protected = protected_manifest(root)
    if before_inputs != after_inputs:
        raise RuntimeError("comparison inputs changed during the run; no artifact published")
    if before_protected != after_protected:
        raise RuntimeError("comparison mutated a canonical cache or archive; no artifact published")

    bootstrap = json.loads((data / "bootstrap.json").read_text())
    hold, candidates = _candidate_rows(
        decisions_2, decisions_6, {2: projection_2, 6: projection_6}, bootstrap
    )
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "meta": {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "targetGw": target_gw,
            "horizons": list(HORIZONS),
            "inputSha256": _digest_manifest(before_inputs),
            "canonicalProjectionsSha256": before_inputs["data/projections.json"],
            "canonicalDecisionsSha256": before_inputs["data/decisions.json"],
            "projectionModel": projection_6.get("meta", {}).get("model_version"),
            "minutesModel": projection_6.get("meta", {}).get("minutes_runtime_model"),
            "projectionPolicy": "same canonical weekly forecasts; explicit first-two-week view",
            "optimizationPolicy": "independent exact squad search at two and six gameweeks",
            "canonicalMutationCheck": "passed",
        },
        "hold": hold,
        "candidates": candidates,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = output.with_suffix(output.suffix + ".tmp")
    temporary_output.write_text(json.dumps(payload, indent=2) + "\n")
    temporary_output.replace(output)
    return payload


def main() -> None:
    payload = build_comparison()
    print(
        f"wrote {OUT.relative_to(ROOT)} — GW{payload['meta']['targetGw']}, "
        f"{len(payload['candidates'])} independently searched candidate squads"
    )
    leaders = {
        horizon: max(payload["candidates"], key=lambda row: row["scores"][str(horizon)]["gain_after_hits"])
        for horizon in HORIZONS
    }
    for horizon, row in leaders.items():
        plan = row["plan"]
        moves = ", ".join(item["name"] for item in plan["transfers_in"])
        gain = row["scores"][str(horizon)]["gain_after_hits"]
        print(f"  {horizon} GW leader: {moves or 'hold'} ({gain:+.2f} xP after hits vs hold)")


if __name__ == "__main__":
    main()
