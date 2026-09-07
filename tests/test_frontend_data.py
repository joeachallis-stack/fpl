import json
from pathlib import Path

from scripts import frontend_data


def contains_shadow(value):
    if isinstance(value, dict):
        return any(str(key).startswith("shadow_") or contains_shadow(item) for key, item in value.items())
    if isinstance(value, list):
        return any(contains_shadow(item) for item in value)
    return False


def test_live_only_removes_shadow_recursively():
    payload = {
        "xP": 4.2,
        "shadow_xP": 4.9,
        "nested": [{"safe": True, "shadow_variants": {"challenger": 1}}],
    }

    cleaned = frontend_data.live_only(payload)

    assert cleaned == {"xP": 4.2, "nested": [{"safe": True}]}
    assert not contains_shadow(cleaned)


def test_two_week_score_uses_existing_lineups_without_writing(tmp_path):
    plan = {
        "lineups": [
            {"planned_total_xP": 50},
            {"planned_total_xP": 40},
            {"planned_total_xP": 99},
        ]
    }
    sentinel = tmp_path / "decisions.json"
    sentinel.write_text(json.dumps({"untouched": True}))

    score = frontend_data._discounted_plan_score(plan, 2, 0.8)

    assert score == 82.0
    assert json.loads(sentinel.read_text()) == {"untouched": True}


def test_current_workspace_build_is_coherent_and_shadow_free():
    if not (frontend_data.DATA / "decisions.json").exists():
        return

    analysis = frontend_data.build_analysis()

    assert analysis["meta"]["targetGw"] == analysis["plans"][0]["lineup"]["gw"]
    assert len(analysis["plans"]) <= 4
    projection_players = json.loads(
        (frontend_data.DATA / "projections.json").read_text()
    )["players"]
    assert len(analysis["playerPool"]) == len(projection_players)
    assert len(analysis["fixtureWall"]["rows"]) == 20
    assert all(len(row["gameweeks"]) == 38 for row in analysis["fixtureWall"]["rows"])
    assert not contains_shadow(analysis["plans"])
    assert not contains_shadow(analysis["players"])


def test_independent_comparison_requires_matching_canonical_hashes(tmp_path, monkeypatch):
    projections = tmp_path / "projections.json"
    decisions = tmp_path / "decisions.json"
    projections.write_text('{"projection": true}')
    decisions.write_text('{"decision": true}')
    comparison = {
        "schemaVersion": "horizon-comparison-v1",
        "meta": {
            "targetGw": 4,
            "horizons": [2, 6],
            "canonicalProjectionsSha256": frontend_data._sha256(projections),
            "canonicalDecisionsSha256": frontend_data._sha256(decisions),
        },
    }
    (tmp_path / "horizon_comparison.json").write_text(json.dumps(comparison))
    monkeypatch.setattr(frontend_data, "DATA", tmp_path)

    assert frontend_data._load_independent_comparison(4) == comparison

    decisions.write_text('{"decision": "changed"}')
    assert frontend_data._load_independent_comparison(4) is None
