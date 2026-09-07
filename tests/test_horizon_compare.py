import json
from pathlib import Path

import pytest

from scripts import horizon_compare


def contains_shadow(value):
    if isinstance(value, dict):
        return any(
            str(key).startswith("shadow_") or contains_shadow(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(contains_shadow(item) for item in value)
    return False


def test_truncate_projection_is_explicit_and_does_not_mutate_source():
    source = {
        "meta": {"horizon": 6, "horizon_discount": 0.5},
        "players": {
            "1": {
                "horizon_xP": 99,
                "gameweeks": [{"xP": value} for value in (4, 2, 8, 8, 8, 8)],
            }
        },
    }

    short = horizon_compare.truncate_projection(source, 2)

    assert short["meta"]["horizon"] == 2
    assert short["players"]["1"]["horizon_xP"] == 5.0
    assert len(short["players"]["1"]["gameweeks"]) == 2
    assert source["meta"]["horizon"] == 6
    assert len(source["players"]["1"]["gameweeks"]) == 6


def test_current_workspace_comparison_never_mutates_caches_or_archives(tmp_path: Path):
    root = horizon_compare.ROOT
    if not (root / "data" / "decisions.json").exists():
        pytest.skip("live ignored analysis artifacts are unavailable")

    before = horizon_compare.protected_manifest(root)
    payload = horizon_compare.build_comparison(root, tmp_path / "comparison.json")
    after = horizon_compare.protected_manifest(root)

    assert before == after
    assert payload["meta"]["canonicalMutationCheck"] == "passed"
    assert payload["meta"]["horizons"] == [2, 6]
    assert payload["candidates"]
    assert not contains_shadow(payload)


def test_comparison_refuses_any_other_repository_output_path():
    with pytest.raises(ValueError, match="may not write"):
        horizon_compare.build_comparison(
            horizon_compare.ROOT,
            horizon_compare.ROOT / "data" / "projections.json",
        )
