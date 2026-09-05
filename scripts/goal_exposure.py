"""Translate opponent goals and minutes states into defensive FPL points."""
from __future__ import annotations

import math

import counts
import minutes

MODEL_VERSION = "goal-exposure-v1"


def shortcut(
    scoring: dict, position: str, opponent_lam: float, p_60: float,
    expected_minutes: float,
) -> dict:
    """The former expected-minutes calculation, retained for reproducible comparison."""
    clean_sheet = scoring["clean_sheets"][position] * math.exp(-opponent_lam) * p_60
    deduction_units, _ = counts.expected_points_at_intervals(
        opponent_lam * expected_minutes / 90, 0.0, 2
    )
    goals_conceded = scoring["goals_conceded"][position] * deduction_units
    return {
        "clean_sheet_points": clean_sheet,
        "goals_conceded_points": goals_conceded,
    }


def predict(
    scoring: dict, position: str, opponent_lam: float, minutes_record: dict,
) -> dict:
    """Mix clean-sheet and goals-conceded scoring over complete minutes states."""
    states, conditional, minutes_source = minutes.projection_scenarios(minutes_record)
    clean_sheet_points = 0.0
    goals_conceded_points = 0.0
    clean_sheet_award_probability = 0.0
    expected_deduction_units = 0.0
    state_audit = {}
    for state, state_probability in states.items():
        state_minutes = conditional[state]
        exposure_lam = opponent_lam * state_minutes / 90
        clean_sheet_eligible = state_minutes >= 60 and state != "unused"
        clean_sheet_probability = math.exp(-exposure_lam) if clean_sheet_eligible else 0.0
        deduction_units, tails = counts.expected_points_at_intervals(
            exposure_lam, 0.0, 2
        )
        if state == "unused":
            deduction_units = 0.0
            tails = {threshold: 0.0 for threshold in tails}

        clean_sheet_award_probability += state_probability * clean_sheet_probability
        expected_deduction_units += state_probability * deduction_units
        clean_sheet_points += (
            state_probability * scoring["clean_sheets"][position] * clean_sheet_probability
        )
        goals_conceded_points += (
            state_probability * scoring["goals_conceded"][position] * deduction_units
        )
        state_audit[state] = {
            "probability": state_probability,
            "minutes": state_minutes,
            "exposure_goal_lambda": exposure_lam,
            "clean_sheet_eligible": clean_sheet_eligible,
            "clean_sheet_probability": clean_sheet_probability,
            "goal_conceded_threshold_probabilities": {
                threshold: tails[threshold] for threshold in (2, 4, 6)
            },
            "expected_deduction_units": deduction_units,
        }

    return {
        "clean_sheet_points": clean_sheet_points,
        "goals_conceded_points": goals_conceded_points,
        "clean_sheet_award_probability": clean_sheet_award_probability,
        "expected_goal_conceded_deduction_units": expected_deduction_units,
        "source": MODEL_VERSION,
        "minutes_scenario_source": minutes_source,
        "opponent_goal_lambda": opponent_lam,
        "state_audit": state_audit,
    }
