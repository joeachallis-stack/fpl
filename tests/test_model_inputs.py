import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import minutes
import projections


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


if __name__ == "__main__":
    unittest.main()
