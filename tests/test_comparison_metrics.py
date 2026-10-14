import json
import numpy as np
import pytest

from orbit_poc.comparison.metrics import (
    aggregate_clock_scores, clock_nullspace_nll, fixed_epoch_coverage,
    flight_residual_metrics, gaussian_score, paired_seed_statistics, position_metrics,
    wilson_interval,
)
from orbit_poc.comparison.report import create_report


def test_clock_nullspace_invariance_and_full_predictive_logdet():
    residual = np.array([1., -2., 3.])
    r = np.diag([4., 9., 16.])
    h = np.array([[1., 0.], [0., 1.], [1., 1.]])
    p = np.array([[2., .2], [.2, 3.]])
    score = clock_nullspace_nll(residual, r, h, p)
    shifted = clock_nullspace_nll(residual + 40000., r, h, p)
    assert score["valid"] and score["retained_dimensions"] == 2
    assert shifted["nll"] == pytest.approx(score["nll"], abs=1e-10)
    basis = np.asarray(score["projection_basis"])
    np.testing.assert_allclose(basis.T @ np.ones(3), 0., atol=3e-16)
    np.testing.assert_allclose(basis.T @ basis, np.eye(2), atol=3e-16)
    predictive = basis.T @ (r + h @ p @ h.T) @ basis
    np.testing.assert_allclose(score["projected_covariance"], predictive)
    np.testing.assert_allclose(score["projected_residual"], basis.T @ residual)
    expected = gaussian_score(basis.T @ residual, predictive)
    assert score["nll"] == pytest.approx(expected["nll"])
    zero = clock_nullspace_nll(np.zeros(3), r)
    broad = clock_nullspace_nll(np.zeros(3), 4 * r)
    assert broad["nll"] - zero["nll"] == pytest.approx(np.log(4))


def test_one_satellite_has_no_clock_free_information_and_bad_covariance_fails():
    score = clock_nullspace_nll([42.], [[1.]])
    assert not score["valid"] and not score["informative"]
    assert score["retained_dimensions"] == 0 and score["nll"] is None
    bad = clock_nullspace_nll([1., 2.], [[-1., 0.], [0., -1.]], np.eye(2), np.eye(2)*10)
    assert not bad["valid"]


def test_score_normalization_is_epoch_then_arc_and_failures_are_explicit():
    scores = [{"arc_id": "a", "valid": True, "informative": True, "retained_dimensions": d,
               "nll_per_dimension": n} for d, n in [(2, 1.), (7, 3.)]]
    scores += [{"arc_id": "b", "valid": True, "informative": True, "retained_dimensions": 1,
                "nll_per_dimension": 8.}]
    result = aggregate_clock_scores(scores)
    assert result["mean_nll"] == 5.  # mean(mean(1,3),8), not dimension weighting
    assert result["retained_dimensions"] == 10
    scores.append({"arc_id": "b", "informative": True, "valid": False})
    assert aggregate_clock_scores(scores)["mean_nll"] is None


def test_position_rtn_nees_gap_and_fixed_epoch_coverage():
    times = np.array([0., 39600., 43200., 46800., 86400.])
    truth = np.tile([7e6, 0., 0., 0., 7500., 0.], (5, 1))
    states = truth.copy(); states[:, :3] += [1., 2., 3.]
    covariance = np.tile(np.diag([4., 9., 16., 1., 1., 1.]), (5, 1, 1))
    result = position_metrics(times, states, truth, covariance, [False, True, True, True, False])
    assert result["position_rmse_m"] == pytest.approx(np.sqrt(14))
    assert result["gap_position_rmse_m"] == result["position_rmse_m"]
    np.testing.assert_allclose(result["whole_arc"]["rtn_rmse_m"], [1., 2., 3.])
    assert result["position_nees"] == pytest.approx(1/4 + 4/9 + 9/16)
    np.testing.assert_allclose(result["whole_arc"]["mean_marginal_95_width_rtn_m"],
                               2 * 1.959963984540054 * np.array([2., 3., 4.]))
    np.testing.assert_allclose(result["gap"]["mean_joint_95_ellipsoid_semiaxes_m"],
                               np.sqrt(7.814727903251179) * np.array([2., 3., 4.]))
    assert all(row["covered"] for row in result["fixed_epoch_coverage"])
    covariance[2, 0, 0] = -1
    invalid = position_metrics(times, states, truth, covariance)
    assert not invalid["covariance_valid"] and invalid["position_nll"] is None


def _records():
    rows = []
    for seed in range(8):
        for method, value in [("first", 1.), ("new-third-party-method", 3.)]:
            rows.append({"method_id": method, "cell_id": "primary", "seed": seed, "status": "complete",
                         "converged": True, "covariance_valid": True,
                         "metrics": {"gap_position_rmse_m": value,
                             "fixed_epoch_coverage": [{"hours_since_start": h, "valid": True, "covered": seed < 7} for h in (11,12,13)]}})
    return rows


def test_seed_bootstrap_wilson_failures_and_duplicate_rejection():
    rows = _records()
    rows[-1].update(status="failed", converged=False)
    pair = paired_seed_statistics(rows)[0]
    assert pair["valid_seed_pairs"] == 7 and pair["failed_or_missing_seed_pairs"] == 1
    np.testing.assert_allclose(pair["bootstrap_95_interval"], [-2., -2.])
    assert pair["bootstrap_unit"] == "paired independent seed"
    coverage = fixed_epoch_coverage(rows)
    assert len(coverage) == 6
    assert coverage[0]["trials"] == 8
    assert wilson_interval(0, 0)["interval"] is None
    interval = wilson_interval(7, 8)["interval"]
    assert interval[0] < 7/8 < interval[1]
    with pytest.raises(ValueError, match="Duplicate fit"):
        paired_seed_statistics(rows + [rows[0]])


def test_flight_predictive_residuals_are_separate_from_reference_agreement():
    result = flight_residual_metrics([.01, -.02], sigma=.01,
                                    predictive_covariance=np.eye(2)*.0004,
                                    reference_error=np.array([[1.,2.,3.]]))
    assert result["predictive"]["valid"]
    assert not result["truth_error_claim"] and not result["slr_used_in_fit"]
    assert result["reference_agreement"]["position_rms_m"] == pytest.approx(np.sqrt(14))
    assert "not known truth" in result["reference_agreement"]["interpretation"]


def test_report_unknown_method_and_incomplete_failures_do_not_support_claims(tmp_path):
    rows = _records()
    rows[-1].update(status="failed", converged=False, error="covariance unavailable")
    manifest = {"stage": "synthetic", "methods": ["first", "new-third-party-method"],
                "runs": rows, "status": "incomplete", "complete": False, "expected_fits": 100,
                "calibration": {"status": "complete_boundary_limited", "selections": {"first": {"sigma": .1}},
                    "runs": [{"method": "new-third-party-method", "case": {"arc_id": "independent-calibration"},
                              "status": "complete", "evaluation_status": "failed", "valid": False,
                              "score": None, "error": "heldout covariance rank deficiency"}]}}
    paths = create_report(manifest, tmp_path)
    result = json.loads((tmp_path / "report.json").read_text())
    html = (tmp_path / "index.html").read_text()
    assert "new-third-party-method" in html and "covariance unavailable" in html
    assert "comparison is incomplete" in html
    assert "independent-calibration" in html and "heldout covariance rank deficiency" in html
    assert result["calibration"]["runs"][0]["evaluation_status"] == "failed"
    assert result["observed_fits"] == 16 and len(result["failures"]) == 1
    assert not result["superiority_claim_issued"] and not result["all_fits_valid"]
    assert paths["scientific_acceptance"] is False


def test_report_completed_fit_without_completed_evaluation_stays_incomplete(tmp_path):
    manifest = {"stage":"synthetic", "complete":True, "methods":["method"],
                "runs":[{"method":"method", "case":{"seed":0},
                         "fit":{"status":"complete", "converged":True, "covariance_valid":True}}]}
    result = create_report(manifest, tmp_path)
    summary = json.loads((tmp_path / "report.json").read_text())
    assert not result["all_fits_valid"]
    assert len(summary["failures"]) == 1


def test_planned_denominators_include_a_seed_missing_from_both_methods(tmp_path):
    rows = _records()[:-2]
    planned = [{"cell_id": "primary", "method_id": method, "seed": seed, "coverage": "blackout"}
               for seed in range(8) for method in ("first", "new-third-party-method")]
    pair = paired_seed_statistics(rows, planned_records=planned)[0]
    assert pair["planned_seed_pairs"] == 8 and pair["attempted_seed_pairs"] == 7
    assert pair["valid_seed_pairs"] == 7 and pair["failed_or_missing_seeds"] == [7]
    assert not pair["complete"]
    for row in fixed_epoch_coverage(rows, planned_records=planned):
        assert row["planned_seeds"] == 8 and row["trials"] == 7
        assert row["failed_or_unavailable_seeds"] == 1
    missing = paired_seed_statistics([], planned_records=planned)[0]
    assert missing["planned_seed_pairs"] == missing["failed_or_missing_seed_pairs"] == 8
    assert missing["attempted_seed_pairs"] == 0


def test_report_uses_frozen_plan_and_normal_gap_is_not_applicable(tmp_path):
    methods = ["first", "second"]
    cases = [{"orbit": "leo500", "atmosphere": "disturbed", "coverage": coverage, "seed": seed}
             for coverage in ("normal", "blackout") for seed in range(8)]
    rows = [{"case": case, "method": method, "status": "complete", "converged": True,
             "covariance_valid": True, "metrics": {
                 "gap_position_rmse_m": 1. if case["coverage"] == "blackout" else None,
                 "gap": {"epochs": 240 if case["coverage"] == "blackout" else 0,
                         "position_rmse_m": 1. if case["coverage"] == "blackout" else None}}}
            for case in cases for method in methods
            if not (case["coverage"] == "blackout" and case["seed"] == 7)]
    manifest = {"stage": "synthetic", "status": "complete", "complete": True,
                "methods": methods, "planned_cases": cases, "expected_fits": 32, "runs": rows}
    create_report(manifest, tmp_path)
    report = json.loads((tmp_path / "report.json").read_text())
    assert not report["all_fits_valid"] and not report["planned_design_complete"]
    assert report["missing_planned_fits"] == 2
    normal = next(row for row in report["paired_seed_comparisons"] if row["cell_id"].endswith("normal"))
    assert normal["status"] == "not_applicable" and normal["failed_or_missing_seed_pairs"] == 0
    blackout = next(row for row in report["paired_seed_comparisons"] if row["cell_id"].endswith("blackout"))
    assert blackout["planned_seed_pairs"] == 8 and blackout["failed_or_missing_seed_pairs"] == 1
    assert "not applicable to normal-coverage" in (tmp_path / "index.html").read_text()
