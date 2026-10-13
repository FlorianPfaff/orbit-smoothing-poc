"""Statistical/orchestration tests do not require Tudat, GTSAM, or JAX."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from orbit_poc.benchmark import (
    Budget, _observations_subset, calibration_boundary_diagnostics, calibration_candidates, cell_matrix,
    choose_seed_count, config_hash, heldout_predictive_score,
    merge_calibrations, paired_statistics, solver_equivalence, trajectory_metrics, validate_calibration, write_json,
)
from orbit_poc.data import Dataset
from orbit_poc.report import make_report


class BenchmarkTests(unittest.TestCase):
    def test_hash_is_order_independent_but_changes_with_parameters(self):
        self.assertEqual(config_hash({"a": 1, "b": 2}), config_hash({"b": 2, "a": 1}))
        self.assertNotEqual(config_hash({"tau": 7200}), config_hash({"tau": 1800}))

    def test_full_cell_matrix_is_paired_and_disjoint(self):
        cells = cell_matrix({}, 5)
        self.assertEqual(len(cells), 4 * 2 * 2 * 5)
        self.assertEqual(len({tuple(sorted(cell.items())) for cell in cells}), len(cells))
        for orbit in ("leo300", "leo500", "leo800", "eccentric"):
            self.assertEqual({row["seed"] for row in cells if row["orbit"] == orbit}, set(range(42, 47)))
        with self.assertRaisesRegex(ValueError, "disjoint"):
            cell_matrix({"evaluation_seeds": [10000]}, 1)

    def test_seed_list_cannot_silently_truncate(self):
        with self.assertRaisesRegex(ValueError, "provides"):
            cell_matrix({"evaluation_seeds": [42, 43]}, 5)
        with self.assertRaisesRegex(ValueError, "distinct"):
            cell_matrix({"evaluation_seeds": [42, 42]}, 2)

    def test_budget_never_starts_excess_jobs(self):
        budget = Budget(max_jobs=2)
        self.assertTrue(budget.start_job())
        self.assertTrue(budget.start_job())
        self.assertFalse(budget.start_job())
        self.assertEqual(budget.jobs, 2)
        self.assertFalse(Budget(hours=0).start_job())

    def test_pilot_chooses_only_prespecified_affordable_seed_counts(self):
        self.assertIsNone(choose_seed_count([100], 1)["seeds"])
        self.assertEqual(choose_seed_count([1], 1000, cells_per_seed=10)["seeds"], 20)
        self.assertEqual(choose_seed_count([10], 1000, cells_per_seed=10)["seeds"], 5)
        self.assertIsNone(choose_seed_count([], 10000)["seeds"])

    def test_hyperparameter_grid_counts_and_noise_dimensions(self):
        self.assertEqual(len(calibration_candidates("white")), 7)
        self.assertEqual(len(calibration_candidates("colored")), 21)
        self.assertEqual(len(calibration_candidates("density")), 9)
        first = calibration_candidates("white", nominal_drag=2, cadence=60)[0]
        self.assertAlmostEqual(first["q_acc"], 0.2 ** 2 * 60)
        self.assertEqual(sum(len(calibration_candidates(model)) for model in ("white", "colored", "density")), 37)
        candidates = calibration_candidates("white", nominal_drag=2, cadence=60)
        np.testing.assert_allclose([np.sqrt(item["q_acc"] / 60) / 2 for item in candidates], [0.1, 0.3, 1, 3, 10, 30, 100])

    def test_boundary_flag_blocks_truncated_amplitude_tuning(self):
        entries = [{"candidate": candidate, "scores": [{"valid": True, "nll": 10 - index}] * 5}
                   for index, candidate in enumerate(calibration_candidates("white"))]
        diagnosis = calibration_boundary_diagnostics("white", entries[-1], entries)
        self.assertTrue(diagnosis["upper_amplitude_boundary"])
        self.assertTrue(diagnosis["upper_boundary_improving"])
        self.assertAlmostEqual(diagnosis["upper_boundary_nll_improvement"], 1)
        self.assertIn("extend independent calibration", diagnosis["boundary_warning"])
        entries[3]["scores"] = [{"valid": True, "nll": 0}] * 5
        diagnosis = calibration_boundary_diagnostics("white", entries[3], entries)
        self.assertEqual(diagnosis["grid_boundaries"]["q_acc"], "interior")
        self.assertFalse(diagnosis["upper_boundary_improving"])

    def test_colored_boundary_diagnostic_profiles_over_tau(self):
        entries = [{"candidate": candidate, "scores": [{"valid": True, "nll": 10 - index}] * 5}
                   for index, candidate in enumerate(calibration_candidates("colored"))]
        diagnosis = calibration_boundary_diagnostics("colored", entries[-1], entries)
        self.assertEqual(diagnosis["grid_boundaries"], {"tau": "upper", "accel_sigma": "upper"})
        self.assertTrue(diagnosis["upper_boundary_improving"])
        self.assertEqual(len(diagnosis["profiled_amplitude_nll"]), 7)

    def test_unresolved_calibration_boundary_cannot_certify_comparison(self):
        with self.assertRaisesRegex(ValueError, "upper amplitude boundary"):
            validate_calibration({"complete": True, "comparison_grid_adequate": False}, {}, "tudat")

    @staticmethod
    def dataset(sigma=None):
        return Dataset(times=np.arange(3) * 60.0,
            observations={"node": np.array([0, 1, 2]), "station_pos": np.zeros((3, 3)),
                          "station_vel": np.zeros((3, 3)), "y": np.array([[1.0, 0.0]] * 3),
                          "sigma": np.array([2.0, 0.1]) if sigma is None else sigma},
            prior_mean=np.array([1, 0, 0, 0, 1, 0]), prior_sigma=np.ones(6))

    def test_holdout_split_preserves_broadcast_observation_noise(self):
        data = self.dataset()
        selected = _observations_subset(data, np.array([True, False, True]))
        np.testing.assert_array_equal(selected.observations["node"], [0, 2])
        np.testing.assert_array_equal(selected.observations["sigma"], [2.0, 0.1])
        self.assertEqual(len(data.observations["node"]), 3)
        data = self.dataset(np.ones((3, 2)))
        selected = _observations_subset(data, np.array([True, False, True]))
        self.assertEqual(selected.observations["sigma"].shape, (2, 2))

    def test_predictive_score_includes_trajectory_uncertainty(self):
        observations = self.dataset().observations
        states = np.tile([1.0, 0, 0, 0, 1.0, 0], (3, 1))
        covariance = np.zeros((3, 6, 6))
        score = heldout_predictive_score(states, covariance, observations)
        self.assertTrue(score["valid"])
        expected = np.log(2 * np.pi) + np.log(2 * 0.1)
        self.assertAlmostEqual(score["nll"], expected)
        biased = states.copy()
        biased[:, 0] += 10
        overconfident = heldout_predictive_score(biased, covariance, observations)
        covariance[:, 0, 0] = 100
        uncertain = heldout_predictive_score(biased, covariance, observations)
        self.assertLess(uncertain["nll"], overconfident["nll"])

    def test_metrics_separate_gap_and_validate_covariance(self):
        truth = np.tile([7e6, 0, 0, 0, 7500, 0], (3, 1)).astype(float)
        states = truth.copy()
        states[:, 0] += [1, 4, 1]
        covariance = np.tile(np.eye(6), (3, 1, 1))
        metrics, epoch = trajectory_metrics(states, covariance, truth, np.array([0, 3600, 7200]), gap_hours=[0.5, 1.5])
        self.assertEqual(metrics["gap_position_rmse_m"], 4)
        self.assertEqual(metrics["outside_gap_position_rmse_m"], 1)
        self.assertEqual(metrics["invalid_covariance_epochs"], 0)
        np.testing.assert_array_equal(epoch["gap"], [False, True, False])
        covariance[1, 0, 0] = -1
        metrics, _ = trajectory_metrics(states, covariance, truth, np.array([0, 3600, 7200]))
        self.assertEqual(metrics["invalid_covariance_epochs"], 1)

    def test_paired_statistics_use_only_common_valid_seeds(self):
        runs = []
        for model, values in (("white", [4, 5, 6, 7, 8]), ("density", [1, 2, 3, 4, 5])):
            for seed, value in enumerate(values):
                runs.append({"context": {"orbit": "leo500", "atmosphere": "disturbed", "coverage": "normal",
                                          "model": model, "solver": "gtsam", "seed": seed},
                             "valid_for_comparison": True, "metrics": {"position_rmse_m": value}})
        rows = paired_statistics(runs)
        self.assertEqual(rows[0]["paired_seed_count"], 5)
        self.assertEqual(rows[0]["mean_difference_a_minus_b"], -3)
        self.assertEqual(rows[0]["bootstrap_95_interval"], [-3, -3])
        runs[-1]["valid_for_comparison"] = False
        self.assertIsNone(paired_statistics(runs)[0]["bootstrap_95_interval"])

    def test_merge_preserves_incomplete_status_and_rejects_duplicates(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifests = []
            for index, complete in enumerate((True, False)):
                path = root / f"source-{index}.json"
                write_json(path, {"complete": complete, "quick": False,
                    "provenance": {"source_sha256": "same"}, "config": {},
                    "selections": {f"orbit{index}": {}}, "runs": [], "expected_fits": 1})
                manifests.append(path)
            self.assertFalse(merge_calibrations(manifests, root / "merged")["complete"])
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                merge_calibrations([manifests[0], manifests[0]], root / "duplicate")

    def test_missing_benchmark_report_cannot_claim_completion(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = make_report(temporary, plots=False)
            self.assertFalse(result["valid_benchmark"])
            self.assertEqual(result["observed_fit_count"], 0)
            self.assertIn("incomplete", Path(result["html"]).read_text())
            self.assertFalse(json.loads((Path(result["html"]).parent / "summary.json").read_text())["valid_benchmark"])

    def test_equivalence_requires_all_pairs_and_posterior_scaled_tolerance(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            runs = []
            for solver in ("gtsam", "ieks"):
                path = root / solver / "fit.json"
                write_json(path, {"objective": 100.0, "reference_sha256": "identical"})
                states = np.zeros((3, 7))
                if solver == "ieks":
                    states[1, 0] = 0.005
                np.savez(path.parent / "fit.npz", states=states, covariance=np.tile(np.eye(7), (3, 1, 1)))
                runs.append({"path": str(path), "valid_for_comparison": True,
                             "context": {"orbit": "leo500", "atmosphere": "quiet", "coverage": "normal",
                                         "model": "density", "seed": 42, "solver": solver}})
            self.assertTrue(solver_equivalence(runs, 1)["passed"])
            self.assertFalse(solver_equivalence(runs, 2)["passed"])
            self.assertFalse(solver_equivalence(runs[:1], 1)["passed"])
            states[1, 0] = 0.02
            np.savez(root / "ieks" / "fit.npz", states=states, covariance=np.tile(np.eye(7), (3, 1, 1)))
            self.assertFalse(solver_equivalence(runs, 1)["passed"])


if __name__ == "__main__":
    unittest.main()
