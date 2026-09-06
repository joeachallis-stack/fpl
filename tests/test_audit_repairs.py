import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate
import freeze
import decisions
import projections
import set_pieces


class FreezeStateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.original_root = freeze.ROOT
        self.original_data = freeze.DATA_DIR
        freeze.ROOT = self.root
        freeze.DATA_DIR = self.root / "data"

    def tearDown(self):
        freeze.ROOT = self.original_root
        freeze.DATA_DIR = self.original_data
        self.directory.cleanup()

    def test_null_projection_actuals_are_unresolved(self):
        path = self.root / "projections" / "gw04.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "meta": {"gw": 4},
            "players": {"1": {"actual_points": None}},
        }))
        self.assertTrue(freeze.projections_unresolved(4))

        payload = json.loads(path.read_text())
        payload["meta"]["resolved_at"] = "2026-09-20T00:00:00+00:00"
        path.write_text(json.dumps(payload))
        self.assertFalse(freeze.projections_unresolved(4))

    def test_resolution_markers_distinguish_missing_actuals_from_not_run(self):
        path = self.root / "minutes" / "gw04.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"element": 1, "actual_minutes": None}) + "\n")
        self.assertTrue(freeze.minutes_unresolved(4))
        path.write_text(json.dumps({
            "element": 1,
            "actual_minutes": None,
            "resolved_at": "2026-09-20T00:00:00+00:00",
        }) + "\n")
        self.assertFalse(freeze.minutes_unresolved(4))

    def test_status_with_no_cache_never_fetches(self):
        with mock.patch.object(sys, "argv", ["freeze.py", "--status"]), \
                mock.patch.object(freeze, "run_script") as run:
            freeze.main()
        run.assert_not_called()

    def test_stale_state_refreshes_even_when_no_freeze_is_due(self):
        freeze.DATA_DIR.mkdir(parents=True)
        (freeze.DATA_DIR / "bootstrap.json").write_text("{}")
        with mock.patch.object(sys, "argv", ["freeze.py"]), \
                mock.patch.object(freeze, "cache_age_hours", return_value=7.0), \
                mock.patch.object(freeze, "run_script", return_value=(True, "")) as run, \
                mock.patch.object(freeze, "next_deadline", return_value=None), \
                mock.patch.object(freeze, "resolve_settled", return_value=False):
            freeze.main()
        run.assert_called_once_with("fetch_data.py", "--skip-slow", "--skip-optional")

    def test_past_deadline_never_runs_an_archive_command(self):
        freeze.DATA_DIR.mkdir(parents=True)
        (freeze.DATA_DIR / "bootstrap.json").write_text("{}")
        deadline = datetime.now(timezone.utc) - timedelta(minutes=1)
        with mock.patch.object(sys, "argv", ["freeze.py"]), \
                mock.patch.object(freeze, "cache_age_hours", return_value=0.0), \
                mock.patch.object(freeze, "next_deadline", return_value=(4, deadline)), \
                mock.patch.object(freeze, "missing_steps", return_value=[("minutes", "minutes.py")]), \
                mock.patch.object(freeze, "resolve_settled", return_value=False), \
                mock.patch.object(freeze, "run_script") as run:
            freeze.main()
        run.assert_not_called()

    def test_resolve_refreshes_complete_player_inputs_before_scoring(self):
        pending = [(4, "projections", "projections.py")]
        with mock.patch.object(freeze, "pending_resolves", side_effect=[pending, pending]), \
                mock.patch.object(
                    freeze, "run_script",
                    side_effect=[(True, "refreshed"), (True, "resolved"), (True, "evaluated")],
                ) as run:
            self.assertTrue(freeze.resolve_settled())
        self.assertEqual(
            [call.args for call in run.call_args_list],
            [
                ("fetch_data.py", "--refresh-summaries", "--skip-optional"),
                ("projections.py", "resolve", "--gw", "4"),
                ("evaluate.py",),
            ],
        )

    def test_projection_resolver_refuses_an_unfinalized_gameweek(self):
        archive_dir = self.root / "projections"
        archive_dir.mkdir(parents=True)
        (archive_dir / "gw04.json").write_text(json.dumps({"meta": {}, "players": {}}))
        freeze.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (freeze.DATA_DIR / "bootstrap.json").write_text(json.dumps({
            "events": [{"id": 4, "finished": False, "data_checked": False}]
        }))
        old_archive, old_data = projections.ARCHIVE_DIR, projections.DATA_DIR
        projections.ARCHIVE_DIR, projections.DATA_DIR = archive_dir, freeze.DATA_DIR
        try:
            with self.assertRaises(SystemExit):
                projections.resolve(4)
        finally:
            projections.ARCHIVE_DIR, projections.DATA_DIR = old_archive, old_data

    def test_projection_resolver_writes_explicit_completion_marker(self):
        archive_dir = self.root / "projections"
        archive_dir.mkdir(parents=True)
        archive = archive_dir / "gw04.json"
        archive.write_text(json.dumps({
            "meta": {},
            "players": {"1": {
                "element": 1, "xP": 1.0, "calibration_weight": 0.0,
                "actual_points": None,
            }},
        }))
        freeze.DATA_DIR.mkdir(parents=True, exist_ok=True)
        (freeze.DATA_DIR / "bootstrap.json").write_text(json.dumps({
            "events": [{"id": 4, "finished": True, "data_checked": True}]
        }))
        (freeze.DATA_DIR / "fixtures.json").write_text(json.dumps([
            {"id": 1, "finished": True, "finished_provisional": False}
        ]))
        summaries = freeze.DATA_DIR / "element_summary"
        summaries.mkdir()
        (summaries / "1.json").write_text(json.dumps({
            "history": [{"round": 4, "fixture": 1, "total_points": 2}]
        }))
        old_archive, old_data = projections.ARCHIVE_DIR, projections.DATA_DIR
        projections.ARCHIVE_DIR, projections.DATA_DIR = archive_dir, freeze.DATA_DIR
        projections.history_for.cache_clear()
        try:
            projections.resolve(4)
        finally:
            projections.ARCHIVE_DIR, projections.DATA_DIR = old_archive, old_data
            projections.history_for.cache_clear()
        payload = json.loads(archive.read_text())
        self.assertIsNotNone(payload["meta"]["resolved_at"])
        self.assertEqual(payload["players"]["1"]["actual_points"], 2)


class PenaltyModelTests(unittest.TestCase):
    def test_taker_context_separates_minutes_from_conditional_duty(self):
        context = set_pieces.taker_context([1, 2], {1: 0.6, 2: 0.5})
        self.assertAlmostEqual(context[1]["conditional_taker_probability"], 1.0)
        self.assertAlmostEqual(context[1]["taker_probability"], 0.6)
        self.assertAlmostEqual(context[2]["conditional_taker_probability"], 0.4)
        self.assertAlmostEqual(context[2]["taker_probability"], 0.2)

    def test_first_choice_penalty_xg_is_exposed_to_minutes_once(self):
        share = 0.6
        per_90 = set_pieces.penalty_xg_per_90(1.0)
        expected_removed = per_90 * share
        league_penalty_xg = (
            set_pieces.PENALTY_RATE_PER_TEAM_MATCH * set_pieces.PENALTY_CONVERSION
        )
        self.assertAlmostEqual(expected_removed, league_penalty_xg * share)

    def test_goal_conservation_and_assist_exclusion_are_separate(self):
        team_lambda = set_pieces.LEAGUE_GOALS_PER_TEAM_MATCH
        split = set_pieces.split_team_lambda(team_lambda, [1], {1: 0.6})
        assigned = sum(split["by_player"].values())
        self.assertAlmostEqual(split["goal_allocation_lambda"] + assigned, team_lambda)
        self.assertAlmostEqual(
            split["assistable_lambda"] + split["penalty_goals_total"],
            team_lambda,
        )
        self.assertLess(split["assistable_lambda"], split["goal_allocation_lambda"])

    def test_penalty_misses_are_assigned_to_the_taker(self):
        split = set_pieces.split_team_lambda(1.5, [1], {1: 1.0})
        self.assertAlmostEqual(
            split["misses_by_player"][1], split["penalty_misses_total"]
        )


class PriorShadowTests(unittest.TestCase):
    def test_live_prior_stays_flat_and_shadow_scales(self):
        self.assertEqual(projections.prior_weight(3065), 900)
        self.assertEqual(projections.evidence_prior_weight(3065), 2700)
        self.assertEqual(projections.evidence_prior_weight(480), 930)


class DecisionBoundaryTests(unittest.TestCase):
    def test_shadow_fields_never_reach_the_optimizer(self):
        common = {
            "players": {
                "1": {
                    "element": 1,
                    "xP": 4.0,
                    "shadow_variants": {"challenger": {"xP": 4000.0}},
                    "gameweeks": [{
                        "gw": 4,
                        "xP": 4.0,
                        "shadow_variants": {"challenger": {"xP": 4000.0}},
                    }],
                    "prior_audit": {"shadow_prior_audit": {"weight": 2700}},
                }
            }
        }
        extreme = json.loads(json.dumps(common))
        extreme["players"]["1"]["shadow_variants"]["challenger"]["xP"] = -4000.0
        extreme["players"]["1"]["gameweeks"][0]["shadow_variants"]["challenger"]["xP"] = -4000.0

        live = decisions.live_optimizer_players(common)
        self.assertEqual(live, decisions.live_optimizer_players(extreme))
        self.assertNotIn("shadow_variants", live[1])
        self.assertNotIn("shadow_variants", live[1]["gameweeks"][0])
        self.assertNotIn("shadow_prior_audit", live[1]["prior_audit"])

    def test_decision_archive_keeps_first_success(self):
        original = decisions.ARCHIVE_DIR
        with tempfile.TemporaryDirectory() as directory:
            decisions.ARCHIVE_DIR = Path(directory)
            try:
                decisions.archive({"meta": {"gw": 4}, "sentinel": "first"})
                decisions.archive({"meta": {"gw": 4}, "sentinel": "later"})
                archived = json.loads((Path(directory) / "gw04.json").read_text())
            finally:
                decisions.ARCHIVE_DIR = original
        self.assertEqual(archived["sentinel"], "first")


class EvaluationSchemaTests(unittest.TestCase):
    SCORING = {
        "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
        "assists": 3,
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "yellow_cards": -1,
        "red_cards": -3,
        "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
        "bonus": 1,
        "saves": 1,
        "own_goals": -2,
        "penalties_saved": 5,
        "penalties_missed": -2,
    }

    def test_legacy_archive_keeps_penalty_miss_in_residual(self):
        row = {
            "position": "MID", "minutes": 0, "goals_scored": 0, "assists": 0,
            "clean_sheets": 0, "goals_conceded": 0, "yellow_cards": 0,
            "red_cards": 0, "defcon_hit": False, "bonus": 0, "saves": 0,
            "own_goals": 0, "penalties_saved": 0, "penalties_missed": 1,
            "total_points": -2,
        }
        legacy = tuple(
            component for component in evaluate.FORECAST_COMPONENTS
            if component != "penalties_missed"
        )
        old = evaluate.aggregate_actual([row], self.SCORING, legacy)
        new = evaluate.aggregate_actual([row], self.SCORING)
        self.assertEqual(old["residual"], -2)
        self.assertEqual(new["residual"], 0)
        self.assertEqual(new["modeled_total"], -2)

    def test_shadow_comparison_is_paired_against_live(self):
        rows = [
            {
                "calibration_weight": 1.0,
                "season": "test",
                "forecast_gw": 4,
                "forecast_total": 4.0,
                "forecast_components": {"goals": 2.0},
                "modeled_components": ("goals",),
                "actual": {
                    "official_total": 2.0,
                    "components": {"goals": 1.0},
                },
                "shadow_variants": {
                    "candidate": {"xP": 3.0, "components": {"goals": 1.5}}
                },
            }
        ]
        result = evaluate.shadow_variant_metrics(rows, weighted=True)["candidate"]
        self.assertEqual(result["live_mae"], 2.0)
        self.assertEqual(result["shadow_mae"], 1.0)
        self.assertEqual(result["delta_mae"], -1.0)
        self.assertEqual(result["component_delta_mae"]["goals"], -0.5)


if __name__ == "__main__":
    unittest.main()
