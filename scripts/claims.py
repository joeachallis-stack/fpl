"""Fourth layer: check what an extractor CLAIMS against what the data records.

The first three layers — constrained vocabulary, roster validation, unresolved report —
all police *names*. They cannot catch the failure that actually matters most.

The case that proved it: auto-captions rendered Tzolis as "Solanke". Both are real
players on the roster, so every name check passed, and two extraction runs confidently
attributed the same event to different people. The FPL data settles it outright —

    Tzolis  (Arsenal MID)  GW2: 45 min, started, yellow card   <- hooked at half time
    Solanke (Spurs FWD)    GW2: 15 min off the bench, no card

— because "taken off at half time with a yellow card" is a falsifiable statement and we
hold per-gameweek minutes, cards, goals and assists for all 652 players.

So the deterministic layer referees the narrative layer. A claim that contradicts the
record is flagged; the reader sees the contradiction rather than inheriting it.

Deliberately conservative. It only judges plainly factual past-tense claims, and only
where a miss would be meaningful. Anything hypothetical ("he could score"), anything
about the future, and anything ambiguous is left alone — a false contradiction would
train the reader to ignore the flags, which is worse than staying quiet.

Usage:
    python scripts/claims.py --self-test
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Each rule: a pattern that means a factual assertion, and a test against the player's
# record for the gameweek in question. Patterns are kept narrow on purpose — "benched"
# is absent because in FPL commentary it usually means the manager's own FPL bench, not
# the club's, and the two are not distinguishable from the text.
CLAIM_RULES: list[tuple[str, str, str]] = [
    (r"\b(?:taken off|subbed|hooked|came off)\s+(?:at\s+)?half[\s-]?time\b",
     "subbed at half time", "minutes_around_45"),
    (r"\b(?:yellow card|booked|got a yellow)\b", "booked", "has_yellow"),
    (r"\b(?:red card|sent off)\b", "sent off", "has_red"),
    (r"\bplayed (?:the full |all )?90\b", "played 90 minutes", "played_90"),
    (r"\b(?:scored|got a goal|goal against)\b", "scored", "has_goal"),
    (r"\b(?:assisted|got an assist|an assist)\b", "assisted", "has_assist"),
    (r"\bclean sheet\b", "kept a clean sheet", "has_clean_sheet"),
]

# Language that makes a sentence hypothetical, predictive or second-hand. If any of this
# is present the claim is not treated as an assertion of fact.
HEDGES = re.compile(
    r"\b(?:could|would|might|may|should|if|expect|predict|likely|unlikely|hope|think|"
    r"probably|maybe|rumou?r|apparently|going to|will|chance|risk|doubts?|doubtful|"
    r"uncertain|unsure|concerns?|worried|worry|despite|questions?)\b",
    re.I,
)


def load_history(element: int, gw: int) -> dict | None:
    path = DATA_DIR / f"element_summary/{element}.json"
    if not path.exists():
        return None
    with open(path) as f:
        rows = [h for h in json.load(f)["history"] if h["round"] == gw]
    if not rows:
        return None
    # A double gameweek gives two rows; sum the countable fields.
    merged = dict(rows[0])
    for extra in rows[1:]:
        for key in ("minutes", "yellow_cards", "red_cards", "goals_scored",
                    "assists", "clean_sheets"):
            merged[key] += extra[key]
    return merged


def test_claim(test: str, record: dict) -> bool:
    if test == "minutes_around_45":
        return 35 <= record["minutes"] <= 55
    if test == "has_yellow":
        return record["yellow_cards"] > 0
    if test == "has_red":
        return record["red_cards"] > 0
    if test == "played_90":
        return record["minutes"] >= 90
    if test == "has_goal":
        return record["goals_scored"] > 0
    if test == "has_assist":
        return record["assists"] > 0
    if test == "has_clean_sheet":
        return record["clean_sheets"] > 0
    raise ValueError(f"unknown test {test}")


# Negation flips what a claim asserts, and matching keywords alone cannot see it. The
# first run flagged "Maguire losing his clean sheet" as contradicted because the record
# showed no clean sheet — which is exactly what the claim said. A checker that cries wolf
# teaches the reader to skip its output, so an apparent negation means stay quiet.
NEGATIONS = re.compile(
    r"\b(?:no|not|never|without|lost|losing|lose|failed|fails|miss(?:ed|es)?|"
    r"didn't|doesn't|wasn't|hasn't|denied|conceded|instead of|rather than)\b",
    re.I,
)


def check(text: str, element: int, gw: int) -> list[dict]:
    """Check one claim about one player in one gameweek. Empty list means nothing to say."""
    if HEDGES.search(text) or NEGATIONS.search(text):
        return []
    record = load_history(element, gw)
    if record is None:
        return []
    results = []
    for pattern, label, test in CLAIM_RULES:
        if not re.search(pattern, text, re.I):
            continue
        holds = test_claim(test, record)
        results.append({
            "assertion": label,
            "verdict": "consistent" if holds else "CONTRADICTED",
            "record": {
                "minutes": record["minutes"], "goals": record["goals_scored"],
                "assists": record["assists"], "yellow": record["yellow_cards"],
                "clean_sheet": record["clean_sheets"],
            },
        })
    return results


def self_test() -> None:
    """Run the real Tzolis/Solanke case, which is why this module exists."""
    import roster

    players = {p["web_name"]: p for p in roster.load_players()}
    text = "Solanke, yellow card, taken off at half-time for Eze"
    print(f'claim: "{text}"   (gameweek 2)\n')
    for name in ("Tzolis", "Solanke"):
        player = players[name]
        for result in check(text, player["element"], 2):
            r = result["record"]
            print(f"  attributed to {name:<9} ({player['team']:<8}) "
                  f"{result['assertion']:<20} {result['verdict']:<14} "
                  f"[{r['minutes']}min, {r['yellow']} yellow]")
    print("\nThe name check passes for both — only the record separates them.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()


# --- target gameweek -------------------------------------------------------------

# Videos are about a gameweek, not about a date. A livestream published six days ago is
# not "slightly stale current advice" — it is a settled gameweek's captaincy calls, team
# news and bench decisions, and reading it as current pulls an entire week of dead
# advice into the present. Filtering by publish date alone did exactly that.
_GW_IN_TITLE = re.compile(r"\b(?:GW|GAMEWEEK|GAME\s?WEEK)\s*(\d{1,2})\b", re.I)

# Not FPL. World Cup Fantasy is a different game with different players and rules, and
# these creators cover both on the same channel.
_OFF_TOPIC = re.compile(r"\bWORLD CUP FANTASY\b|\bDRAFT PREMIER LEAGUE\b", re.I)


def is_off_topic(title: str) -> bool:
    return bool(_OFF_TOPIC.search(title))


def target_gameweek(title: str, published: str, events: list[dict]) -> tuple[int | None, str]:
    """Which gameweek a video is advising on, and how confidently we know.

    The title says so 79% of the time and is the better signal — a video published on
    Monday can be previewing Saturday's gameweek. The rest fall back to the next
    deadline after publication, which is what "advice published at time T" usually means.
    """
    match = _GW_IN_TITLE.search(title)
    if match:
        return int(match.group(1)), "title"

    upcoming = [e for e in events if e["deadline_time"] > published]
    if upcoming:
        return min(upcoming, key=lambda e: e["deadline_time"])["id"], "published_date"
    return None, "unknown"


def relevance(title: str, published: str, events: list[dict]) -> dict:
    """Whether a video is worth reading now, and why not if it isn't.

    A gameweek number on its own does not identify a gameweek. The corpus holds videos
    titled "FPL Gameweek 13" published in November 2024 — two seasons back — which by
    label alone look like advice 10 weeks into the future. The publish date against this
    season's first deadline is what separates them.
    """
    if is_off_topic(title):
        return {"verdict": "off_topic", "gw": None, "reason": "not Fantasy Premier League"}

    season_start = min(e["deadline_time"] for e in events)
    if published < season_start:
        return {"verdict": "prior_season", "gw": None,
                "reason": f"published {published[:10]}, before this season began"}

    gw, how = target_gameweek(title, published, events)
    current = next((e["id"] for e in events if e.get("is_next")), None)
    if gw is None or current is None:
        return {"verdict": "unknown", "gw": gw, "reason": "no gameweek could be determined"}
    if gw < current:
        return {"verdict": "settled", "gw": gw,
                "reason": f"advises on GW{gw}, which has been played"}
    return {"verdict": "current", "gw": gw, "reason": f"advises on GW{gw}", "source": how}
