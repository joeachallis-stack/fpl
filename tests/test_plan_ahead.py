import json

import pytest

from scripts import plan_ahead


def current_target():
    return json.loads((plan_ahead.DATA / "projections.json").read_text())["meta"]["gw"]


def base_plan(**changes):
    target = current_target()
    plan = {
        "name": "Test route",
        "baseGw": target,
        "baseAnalysisRunId": "test-run",
        "events": [],
        "ideas": [],
    }
    plan.update(changes)
    return plan


def test_empty_route_matches_hold_and_returns_every_forecast_week():
    result = plan_ahead.evaluate_plan(base_plan())
    projection = json.loads((plan_ahead.DATA / "projections.json").read_text())

    assert len(result["weeks"]) == projection["meta"]["horizon"]
    assert result["edgeVsHold"] == 0
    assert result["totalHits"] == 0
    assert all(len(week["squad"]) == 15 for week in result["weeks"])
    assert all(len(week["lineup"]["starters"]) == 11 for week in result["weeks"])


def test_transfer_cascades_and_uses_live_free_transfer_rules():
    decisions = json.loads((plan_ahead.DATA / "decisions.json").read_text())
    candidate = decisions["transfers"]["1"][0]
    move = {"out": candidate["transfers_out"][0]["element"], "in": candidate["transfers_in"][0]["element"]}
    target = current_target()

    result = plan_ahead.evaluate_plan(base_plan(events=[{"gw": target, "chip": None, "transfers": [move]}]))

    first = result["weeks"][0]
    assert move["out"] not in first["squad"]
    assert move["in"] in first["squad"]
    assert all(move["in"] in week["squad"] for week in result["weeks"])
    assert first["hit"] == max(0, 1 - first["freeTransfersBefore"]) * 4


def test_future_wildcard_keeps_banked_transfers_and_scores_the_route():
    target = current_target()
    wildcard_gw = min(max(target, 2), 19)
    result = plan_ahead.evaluate_plan(
        base_plan(events=[{"gw": wildcard_gw, "chip": "wildcard", "transfers": []}])
    )
    week = next(row for row in result["weeks"] if row["gw"] == wildcard_gw)

    assert week["hit"] == 0
    assert week["freeTransfersAfter"] >= week["freeTransfersBefore"]


def test_invalid_duplicate_week_is_rejected():
    target = current_target()
    with pytest.raises(plan_ahead.PlanError, match="appears more than once"):
        plan_ahead.evaluate_plan(base_plan(events=[
            {"gw": target, "chip": None, "transfers": []},
            {"gw": target, "chip": "wildcard", "transfers": []},
        ]))


def test_old_draft_rebases_on_current_official_squad_without_replaying_past_moves():
    target = current_target()
    result = plan_ahead.evaluate_plan(base_plan(baseGw=target - 1, events=[
        {"gw": target - 1, "chip": "wildcard", "transfers": []},
    ]))

    assert result["forecastStartGw"] == target
    assert result["edgeVsHold"] == 0
    assert any("past plan event" in note for note in result["assumptions"])


def test_save_upserts_one_named_draft_without_touching_canonical_file(tmp_path):
    path = tmp_path / "drafts.json"
    saved, evaluation = plan_ahead.save_plan(base_plan(ideas=[{"text": "Watch the press conference"}]), path)
    updated, _ = plan_ahead.save_plan({**saved, "name": "Renamed route"}, path)
    payload = json.loads(path.read_text())

    assert evaluation["edgeVsHold"] == 0
    assert saved["id"] == updated["id"]
    assert len(payload["plans"]) == 1
    assert payload["plans"][0]["name"] == "Renamed route"
    assert payload["plans"][0]["ideas"][0]["text"] == "Watch the press conference"
