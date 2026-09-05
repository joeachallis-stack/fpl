"""Penalty duty: who takes them, what it is worth, and when it changes.

`penalties_order` has been snapshotted daily since 2026-09-03 precisely because the API
never backfills it, and until now nothing read it. That is a real omission rather than a
missing refinement, because the projection allocates team goals by each player's xG share
and **official xG already includes penalties**. Three things follow:

- A player who has just taken over penalty duty gets no credit for it at all, because his
  history contains no penalty xG.
- A player who has just lost it keeps credit he no longer earns.
- An established taker is credited only diffusely, through an inflated share, rather than
  through the separate and much more predictable mechanism that actually generates it.

So this module splits the team's goal expectation in two. Penalties are modelled
explicitly and assigned to whoever is currently on duty; the remaining open-play
expectation is allocated by xG with the estimated penalty component removed, which is
what stops an established taker being paid twice.

How the rate was obtained: the API records `penalties_missed` but has no
`penalties_scored` field anywhere — not in `history`, not in `history_past`. Missed
volume plus a conversion rate implies taken volume. Across both cached seasons that gives
14 and 15 missed penalties over 760 team-matches each, so at 79% conversion roughly 0.088
and 0.094 penalties per team-match. Consistent, but resting on ~15 events, so the
sampling error is wide — treat the rate as approximate and recalibrate when the current
season adds evidence.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
SNAPSHOT_DIR = DATA_DIR / "snapshots"

# Penalties awarded per team-match, implied by missed volume at PENALTY_CONVERSION.
# 2024/25 gives 0.088 and 2025/26 gives 0.094 on ~15 observed misses apiece.
PENALTY_RATE_PER_TEAM_MATCH = 0.094
# Long-run Premier League penalty conversion. Used both to infer the rate above and to
# turn awarded penalties into expected goals, so the two stay consistent.
PENALTY_CONVERSION = 0.79
# League baseline team goals per match, for scaling the penalty rate by attacking
# strength. Teams that attack more win more penalties; the proportionality is an
# assumption, not a measurement.
LEAGUE_GOALS_PER_TEAM_MATCH = 1.375
# Only the first few names in the order matter in practice.
MAX_TAKERS = 3

# The three declared set-piece orders. Penalties are modelled numerically above; the other
# two are tracked but deliberately NOT given a separate expectation. Measured on 291
# players with 900+ minutes last season, designated corner takers carry 2.26x (DEF) and
# 2.45x (MID) the xA per 90 of non-takers, and direct free-kick takers 2.52x and 1.88x.
# Those look compelling and cannot be used, for two reasons:
#
#   - They are confounded. Creative players are chosen to take corners, so the ratio mixes
#     the effect of the duty with the selection into it. Separating them needs within-player
#     duty changes, and set-piece order has only been snapshotted since 2026-09-03.
#   - There is no rate to derive. penalties_missed let the penalty rate be recovered from
#     our own data; nothing counts corners or free kicks taken, so any allocation would rest
#     on an invented number, double-counted against an xA rate that already contains it.
#
# Direct free kicks also contribute essentially nothing to goals: 0.73x for defenders and
# 1.14x for midfielders, neither meaningfully above one.
#
# What is left is genuine and cheap: a change of duty means a player's own history
# misrepresents him, and that is worth surfacing even when it cannot be priced.
ORDER_FIELDS = {
    "penalties": "penalties_order",
    "direct_free_kicks": "direct_freekicks_order",
    "corners": "corners_and_indirect_freekicks_order",
}


def load_takers(bootstrap: dict) -> dict[int, list[int]]:
    """Element ids per team, ordered by declared penalty duty (first choice first)."""
    ordered: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for element in bootstrap["elements"]:
        order = element.get("penalties_order")
        if order is None:
            continue
        ordered[element["team"]].append((order, element["id"]))
    return {
        team: [element_id for _, element_id in sorted(rows)[:MAX_TAKERS]]
        for team, rows in ordered.items()
    }


def taker_probabilities(order: list[int], on_pitch: dict[int, float]) -> dict[int, float]:
    """Probability each listed player takes a penalty the team is awarded.

    The first choice takes it when he is on the pitch; otherwise it falls to the second,
    and so on. `on_pitch` is each player's expected share of the match, so this reuses the
    minutes model rather than assuming everyone plays ninety minutes.

    Probabilities deliberately do not sum to one: when nobody on the list is playing,
    someone still takes the penalty and we do not know who. The caller returns that
    remainder to the open-play pool rather than inventing a taker.
    """
    probabilities: dict[int, float] = {}
    remaining = 1.0
    for element_id in order:
        share = max(0.0, min(1.0, on_pitch.get(element_id, 0.0)))
        probabilities[element_id] = remaining * share
        remaining *= 1 - share
    return probabilities


def team_penalty_goals(team_goal_lambda: float) -> float:
    """Expected goals from penalties for a team in one fixture.

    Scaled by attacking strength on the assumption that teams creating more also win more
    penalties. That proportionality is untested — the alternative, a flat league rate, is
    one line away if it ever fails an ablation.
    """
    scale = team_goal_lambda / LEAGUE_GOALS_PER_TEAM_MATCH if LEAGUE_GOALS_PER_TEAM_MATCH else 1.0
    return PENALTY_RATE_PER_TEAM_MATCH * max(scale, 0.0) * PENALTY_CONVERSION


def penalty_xg_per_90(taker_probability: float) -> float:
    """Penalty xG already inside a player's official per-90 xG, to be removed from it.

    Assumes current duty held across the history the rate was measured over. That is
    wrong exactly when duty has changed, which is why `order_changes` exists — a change
    is the signal to distrust this correction for that player.
    """
    return PENALTY_RATE_PER_TEAM_MATCH * PENALTY_CONVERSION * taker_probability


def split_team_lambda(
    team_goal_lambda: float, order: list[int], on_pitch: dict[int, float],
) -> dict:
    """Divide a team's goal expectation into assigned penalties and open play.

    Total is conserved: whatever cannot be assigned to a known taker goes back into the
    open-play pool, so no expectation is created or lost.
    """
    penalty_goals = team_penalty_goals(team_goal_lambda)
    probabilities = taker_probabilities(order, on_pitch)
    assigned_fraction = sum(probabilities.values())
    assigned = penalty_goals * assigned_fraction
    return {
        "penalty_goals_total": penalty_goals,
        "penalty_goals_assigned": assigned,
        "open_play_lambda": max(team_goal_lambda - assigned, 0.0),
        "taker_probabilities": probabilities,
        "assigned_fraction": assigned_fraction,
        "by_player": {
            element_id: penalty_goals * probability
            for element_id, probability in probabilities.items()
        },
    }


def duty(bootstrap: dict) -> dict[int, dict[str, int | None]]:
    """Every declared set-piece order for every player, as displayed context."""
    return {
        element["id"]: {
            name: element.get(field) for name, field in ORDER_FIELDS.items()
        }
        for element in bootstrap["elements"]
        if any(element.get(field) is not None for field in ORDER_FIELDS.values())
    }


def order_changes(limit: int = 30, kinds: tuple[str, ...] | None = None) -> list[dict]:
    """Set-piece duty changes visible across the dated bootstrap snapshots.

    This is the payoff for snapshotting: the live API only ever shows today's order, so a
    change of duty is invisible without a record of yesterday. A player who has just
    gained or lost a set-piece role is exactly the case where his own xG or xA history
    misrepresents him — and for corners and free kicks, flagging that is all we can
    honestly do, because the size of the effect is not identifiable from this data.
    """
    kinds = kinds or tuple(ORDER_FIELDS)
    snapshots = sorted(SNAPSHOT_DIR.glob("bootstrap_*.json"))[-limit:]
    if len(snapshots) < 2:
        return []
    changes = []
    previous_order: dict[tuple[str, int], int | None] = {}
    previous_date = None
    for path in snapshots:
        payload = json.loads(path.read_text())
        names = {team["id"]: team["name"] for team in payload["teams"]}
        current = {
            (kind, element["id"]): element.get(ORDER_FIELDS[kind])
            for kind in kinds
            for element in payload["elements"]
        }
        labels = {
            element["id"]: (element["web_name"], names.get(element["team"], "?"))
            for element in payload["elements"]
        }
        date = path.stem.replace("bootstrap_", "")
        if previous_order:
            for key, order in current.items():
                kind, element_id = key
                was = previous_order.get(key)
                if key in previous_order and was != order:
                    name, team = labels.get(element_id, ("?", "?"))
                    changes.append({
                        "date": date, "previous_date": previous_date, "kind": kind,
                        "element": element_id, "web_name": name, "team": team,
                        "from": was, "to": order,
                    })
        previous_order = current
        previous_date = date
    return changes


def main() -> None:
    bootstrap = json.loads((DATA_DIR / "bootstrap.json").read_text())
    names = {team["id"]: team["name"] for team in bootstrap["teams"]}
    labels = {element["id"]: element["web_name"] for element in bootstrap["elements"]}
    takers = load_takers(bootstrap)

    print(f"penalty duty — {len(takers)}/{len(bootstrap['teams'])} teams declared")
    for team_id in sorted(takers, key=lambda t: names[t]):
        listed = ", ".join(labels[element_id] for element_id in takers[team_id])
        print(f"  {names[team_id]:16s} {listed}")

    example = PENALTY_RATE_PER_TEAM_MATCH * PENALTY_CONVERSION
    print(f"\nfirst-choice taker playing 90 minutes is worth {example:.3f} goals/match "
          f"from penalties alone")

    changes = order_changes()
    snapshots = len(sorted(SNAPSHOT_DIR.glob("bootstrap_*.json")))
    print(f"\nset-piece duty changes across {snapshots} snapshots: {len(changes)}")
    for change in changes[-25:]:
        print(f"  {change['date']}  {change['kind']:18s} {change['team']:16s} "
              f"{change['web_name']:14s} {change['from']} -> {change['to']}")


if __name__ == "__main__":
    main()
