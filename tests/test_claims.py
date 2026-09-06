from scripts import claims


def record(*, goals=0):
    return {
        "minutes": 90,
        "yellow_cards": 0,
        "red_cards": 0,
        "goals_scored": goals,
        "assists": 0,
        "clean_sheets": 0,
    }


def test_scored_points_is_not_read_as_scored_goal(monkeypatch):
    monkeypatch.setattr(claims, "load_history", lambda element, gw: record())

    assert claims.check("Kinsky scored six points on the bench", 1, 3) == []


def test_plain_scored_claim_remains_checkable(monkeypatch):
    monkeypatch.setattr(claims, "load_history", lambda element, gw: record())

    result = claims.check("Kinsky scored in GW3", 1, 3)

    assert result[0]["assertion"] == "scored"
    assert result[0]["verdict"] == "CONTRADICTED"
