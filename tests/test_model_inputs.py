import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import minutes
import projections
import train_defcon


class CompletedHistoryTests(unittest.TestCase):
    def test_only_completed_fixture_rows_are_evidence(self):
        fixtures = [
            {"id": 1, "finished": True, "finished_provisional": False},
            {"id": 2, "finished": False, "finished_provisional": True},
            {"id": 3, "started": True, "finished": False, "finished_provisional": False},
            {"id": 4, "started": False, "finished": False, "finished_provisional": False},
        ]
        history = [{"fixture": fixture_id} for fixture_id in range(1, 5)]
        self.assertEqual(
            [row["fixture"] for row in minutes.completed_history(history, fixtures)],
            [1, 2],
        )

    def test_trained_minutes_freezes_prior_and_peer_weights(self):
        model = {
            "model_version": "test-v1",
            "_artifact_sha256": "model-hash",
            "training_season": "2025/26",
            "gameweeks_sha256": "abc",
            "selected": {
                "decay_halflife_gws": 3.0,
                "peer_prior_weight": 0.5,
                "probability_floor": 0.01,
                "state_probability_floor": 0.001,
                "state_driven_outputs": True,
                "club_change_retention": 0.5,
                "offseason_gap_gws": 4,
            },
            "peer_priors": {
                "group": {"MID_7": {
                    "bands": {"p_zero": 0.1, "p_1_59": 0.2, "p_60_plus": 0.7},
                    "role_states": {
                        "unused": 0.1, "cameo_1_29": 0.05, "cameo_30_59": 0.05,
                        "cameo_60_plus": 0.0, "starter_1_59": 0.1,
                        "starter_60_74": 0.1, "starter_75_89": 0.2,
                        "starter_90_plus": 0.4,
                    },
                    "conditional_minutes_by_state": minutes.train_minutes.STATE_DEFAULT_MINUTES,
                    "exp_minutes": 65.0,
                }},
                "position": {},
            },
        }
        prior = {123: [{
            "minutes": 90, "starts": 1, "gw": 38, "team": "Old Club",
            "prior_season": True,
        }]}
        result = minutes.trained_prediction(
            {"code": 123, "now_cost": 75},
            [{"minutes": 80, "starts": 1, "round": 2}],
            4,
            "New Club",
            "MID",
            (model, prior),
        )
        self.assertAlmostEqual(sum(result["bands"].values()), 1.0)
        self.assertEqual(result["prior_n_obs"], 1)
        self.assertEqual(result["audit"]["peer_effective_weight"], 0.5)
        self.assertGreater(result["audit"]["current_effective_weight"], 0)
        self.assertGreater(result["audit"]["prior_season_effective_weight"], 0)
        self.assertAlmostEqual(
            result["p_start"] + result["p_cameo"] + result["role_states"]["unused"],
            1.0,
        )


class PriorTests(unittest.TestCase):
    def test_previous_rate_and_weights_are_auditable(self):
        rate, audit = projections.prior_season_rate(
            {"season_name": "2025/26", "minutes": 900, "expected_goals": "9"},
            "expected_goals",
            0.3,
        )
        self.assertAlmostEqual(rate, 0.7)
        self.assertEqual(audit["effective_prior_minutes"], 900)
        self.assertEqual(audit["position_prior_minutes"], 450)
        self.assertEqual(audit["raw_per_90"], 0.9)


class FdrTests(unittest.TestCase):
    def test_isotonic_fit_never_gets_easier_as_fdr_rises(self):
        fitted = projections.isotonic_decreasing(
            [2.0, 1.5, 1.8, 1.1, 0.8],
            [5, 5, 2, 5, 5],
        )
        self.assertTrue(all(left >= right for left, right in zip(fitted, fitted[1:])))


class DefconTests(unittest.TestCase):
    def test_clean_sheet_still_requires_sixty_minutes(self):
        scoring = {"clean_sheets": {"DEF": 4}}
        self.assertEqual(
            projections.expected_clean_sheet_points(scoring, "DEF", 1.0, 0.0),
            0.0,
        )

    def test_role_state_mixture_is_not_expected_minutes_shortcut(self):
        target = {
            "element": 1, "position": "DEF", "team": "A", "opponent": "B",
            "home": True, "gw": 4,
        }
        common = {
            "halflife": 6.0,
            "player_prior_minutes": 450.0, "dispersion": 0.1,
            "fixture_mode": "none", "opponent_prior_minutes": 1800.0,
            "position_rates": {"DEF": 12.0, "MID": 12.0, "FWD": 6.0},
            "fixture_tables": ({}, {}),
        }
        lumpy, _ = train_defcon.predict_probability(
            target,
            [],
            {
                "role_states": {"unused": 0.5, "starter_90_plus": 0.5},
                "conditional_minutes_by_state": {"unused": 0.0, "starter_90_plus": 90.0},
            },
            [],
            **common,
        )
        steady, _ = train_defcon.predict_probability(
            target,
            [],
            {
                "role_states": {"starter_1_59": 1.0},
                "conditional_minutes_by_state": {"starter_1_59": 45.0},
            },
            [],
            **common,
        )
        self.assertGreater(lumpy, steady)

    def test_sub_sixty_state_can_score_defcon(self):
        probability, _ = train_defcon.predict_probability(
            {"element": 1, "position": "DEF", "team": "A", "opponent": "B",
             "home": True, "gw": 4},
            [],
            {
                "role_states": {"cameo_30_59": 1.0},
                "conditional_minutes_by_state": {"cameo_30_59": 50.0},
            },
            [],
            halflife=6.0,
            player_prior_minutes=450.0,
            dispersion=0.1,
            fixture_mode="none",
            opponent_prior_minutes=1800.0,
            position_rates={"DEF": 20.0, "MID": 12.0, "FWD": 6.0},
            fixture_tables=({}, {}),
        )
        self.assertGreater(probability, train_defcon.PROBABILITY_FLOOR)

    def test_fitted_challenger_and_role_states_beat_ablations(self):
        artifact = json.loads((ROOT / "models" / "defcon_params.json").read_text())
        selected = artifact["metrics"]["contenders"]
        old = artifact["baselines"]["current_hit_rate_times_p60"]["contenders"]
        collapsed = artifact["minutes_ablation"]["single_expected_minutes"]["contenders"]
        self.assertLess(selected["log_loss"], old["log_loss"])
        self.assertLess(selected["brier"], old["brier"])
        self.assertLess(selected["log_loss"], collapsed["log_loss"])


if __name__ == "__main__":
    unittest.main()
