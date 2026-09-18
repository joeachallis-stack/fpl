import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import creator_minutes  # noqa: E402
import midweek  # noqa: E402


BOOT = {"teams": [{"id": 3, "short_name": "BOU", "name": "Bournemouth"},
                  {"id": 14, "short_name": "LIV", "name": "Liverpool"}]}
LEAGUE = [{"event": 5, "team_h": 3, "team_a": 14, "kickoff_time": "2026-09-20T13:00:00Z"}]


def test_thursday_away_before_sunday_is_a_short_turnaround(monkeypatch):
    monkeypatch.setattr(midweek, "load_fixtures", lambda: {"fixtures": [
        {"team": "BOU", "competition": "UEL", "opponent": "Real Sociedad", "venue": "A",
         "kickoff_utc": "2026-09-17T19:00:00Z"},
        # Five days out: outside the window, so Liverpool is not flagged.
        {"team": "LIV", "competition": "EFL Cup R3", "opponent": "Tottenham", "venue": "H",
         "kickoff_utc": "2026-09-15T12:00:00Z"},
    ]})

    flags = midweek.before_league(5, BOOT, LEAGUE)

    assert list(flags) == [3]
    assert flags[3][0]["hours_before"] == 66.0 and flags[3][0]["short"]
    assert midweek.team_note(3, flags) == "UEL at Real Sociedad Thu, 66h before, short turnaround"


def test_a_match_after_the_league_game_is_not_flagged(monkeypatch):
    monkeypatch.setattr(midweek, "load_fixtures", lambda: {"fixtures": [
        {"team": "BOU", "competition": "UEL", "opponent": "Sturm Graz", "venue": "H",
         "kickoff_utc": "2026-09-22T19:00:00Z"},
    ]})

    assert midweek.before_league(5, BOOT, LEAGUE) == {}


PLAYERS = [{"element": 10, "web_name": "Cherki", "team": "Man City", "position": "MID"},
           {"element": 11, "web_name": "Foden", "team": "Man City", "position": "MID"}]


def finding(call, published="2026-09-14", video="v1", source="focal"):
    return {"source": source, "video_id": video, "published": published, "claim": "c",
            "minutes_call": call}


def test_disagreement_is_scored_against_actual_minutes(monkeypatch):
    monkeypatch.setattr(creator_minutes.findings, "load", lambda gw: [
        finding({"Cherki (Man City, MID)": "starts", "Foden (Man City, MID)": None}),
    ])
    monkeypatch.setattr(creator_minutes, "deadline", lambda gw: None)
    monkeypatch.setattr(creator_minutes, "load_archive", lambda gw: {
        10: {"bands": {"p_60_plus": 0.3}, "actual_minutes": 90},
        11: {"bands": {"p_60_plus": 0.0}, "actual_minutes": 0},
    })

    result = creator_minutes.score(5, PLAYERS)

    # The null call on Foden is not a call at all.
    assert [r["player"] for r in result["calls"]] == ["Cherki"]
    row = result["calls"][0]
    assert row["disagree"] and row["creator_right"] and not row["model_right"]
    summary = creator_minutes.summarise(result["calls"])
    assert summary["disagreements_creator_right"] == 1 and summary["disagreements_model_right"] == 0


def test_self_contradicting_video_and_post_deadline_calls_are_dropped(monkeypatch):
    from datetime import datetime, timezone

    monkeypatch.setattr(creator_minutes.findings, "load", lambda gw: [
        finding({"Cherki (Man City, MID)": "starts"}),
        finding({"Cherki (Man City, MID)": "benched"}),
        finding({"Foden (Man City, MID)": "out"}, published="2026-09-19", video="v2"),
    ])
    monkeypatch.setattr(creator_minutes, "deadline",
                        lambda gw: datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc))

    calls, skipped = creator_minutes.collect_calls(5, PLAYERS)

    assert calls == []
    assert skipped == {"self-contradicting video": 1, "published after deadline": 1}
