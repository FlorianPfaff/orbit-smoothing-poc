import numpy as np
import pytest
from scipy.linalg import block_diag
from scipy.stats import multivariate_normal

from orbit_poc.comparison.density import (
    density_knots, density_multiplier, independent_linear_gate, interpolation_weights,
    jacobian_gate, ou_covariance, ou_logpdf, ou_prior_factor, ou_residuals, qr_map_covariance,
    native_trace_gate,
)


def test_exact_stationary_ou_prior_and_normalization():
    times = np.array([0., 60., 120., 300.])
    factor, offset = ou_prior_factor(times, 7200., .3, mean=.2)
    covariance = ou_covariance(times, 7200., .3)
    np.testing.assert_allclose(np.linalg.inv((factor.T @ factor).toarray()), covariance, rtol=1e-12)
    values = np.array([.1, .12, .13, .04])
    np.testing.assert_allclose(factor @ values - offset, ou_residuals(values, times, 7200., .3, .2))
    assert ou_logpdf(values, times, 7200., .3, .2) == pytest.approx(
        multivariate_normal.logpdf(values, mean=np.full(4, .2), cov=covariance), rel=1e-11)
    assert factor[0, 0] == pytest.approx(1 / .3)


def test_ou_small_interval_remains_finite_and_stationary_mean_has_zero_innovation():
    factor, _ = ou_prior_factor([0., 1e-12], 1e8, .3, mean=7.)
    assert np.isfinite(factor.data).all()
    np.testing.assert_array_equal(ou_residuals([7., 7.], [0., 1e-12], 1e8, .3, mean=7.), [0., 0.])
    assert factor[1, 1] == pytest.approx(1 / (.3 * np.sqrt(2e-20)))
    assert ou_logpdf([0.], [0.], 7200., .3) == pytest.approx(-np.log(.3 * np.sqrt(2*np.pi)))


def test_interpolated_log_density_and_acceleration_jacobian():
    knots = density_knots(0., 130.)
    np.testing.assert_array_equal(knots, [0., 60., 120., 130.])
    queries = np.array([0., 30., 90., 130.])
    values = np.log([1., 4., 9., 16.])
    result, derivative = density_multiplier(values, knots, queries, True)
    np.testing.assert_allclose(result, [1., 2., 6., 16.])
    weights = interpolation_weights(knots, queries)
    np.testing.assert_allclose(np.asarray(weights.sum(axis=1)).ravel(), 1.)
    # Test actual acceleration components, whose accepted absolute error is SI.
    base_acceleration = np.array([-1.2e-6, 2e-7, 8e-8, -3e-7])
    gate = jacobian_gate(lambda x: base_acceleration * density_multiplier(x, knots, queries),
                         lambda x: base_acceleration[:, None] * density_multiplier(x, knots, queries, True)[1].toarray(), values)
    assert gate["passed"]
    assert gate["maximum_absolute_error"] < 1e-12
    with pytest.raises(ValueError, match="extrapolation"):
        interpolation_weights(knots, [-1.])
    with pytest.raises(FloatingPointError):
        density_multiplier(np.full(4, 1000.), knots, queries)


def test_qr_nuisance_marginal_is_not_conditional_covariance():
    design = np.array([[1., 1.], [0., .1], [.2, 0.]])
    _, covariance = qr_map_covariance(design, np.ones(3))
    assert covariance[0, 0] > 10 / np.sum(design[:, 0] ** 2)
    with pytest.raises(ValueError, match="rank deficient"):
        qr_map_covariance(np.ones((3, 2)), np.zeros(3))


def test_real_gtsam_against_independent_qr_with_ou_clock_and_ambiguity_nuisance():
    pytest.importorskip("gtsam")
    rng = np.random.default_rng(1821)
    observations = rng.normal(size=(25, 9))
    # State(3), log-density(4), clock(1), float ambiguity(1), all proper.
    ou, _ = ou_prior_factor(np.arange(4) * 60., 1800., .3)
    priors = block_diag(np.eye(3) / 100., ou.toarray(), np.array([[1/30.]]), np.array([[1/10.]]))
    design = np.vstack((observations, priors))
    target = np.r_[rng.normal(size=25), np.zeros(9)]
    gate = independent_linear_gate(design, target, [0, 1, 2])
    assert gate["passed"]
    assert gate["normalized_map_discrepancy"] < 1e-7
    assert gate["relative_covariance_error"] < 1e-8
    assert gate["nuisance_parameter_count"] == 6


def test_native_trace_reader_validates_ordering_and_full_inverse(tmp_path):
    pytest.importorskip("gtsam")
    # Parser fixture only; actual native assembly acceptance uses exported runs.
    rng = np.random.default_rng(58)
    design = rng.normal(size=(12, 4)); target = rng.normal(size=12)
    mean, covariance = qr_map_covariance(design, target)
    stem = tmp_path / "linear.1"
    names = ["sat:arc0.position0.x::", "sat:logDensity::", "sat:clock::", "sat:ambiguity::"]
    (tmp_path / "linear.1.parameters.tsv").write_text("".join(f"{i}\t0\t{name}\n" for i,name in enumerate(names)))
    row,col = np.indices(design.shape)
    np.savetxt(str(stem)+".design.tsv",np.column_stack([row.ravel(),col.ravel(),design.ravel()]))
    np.savetxt(str(stem)+".rhs.tsv",np.column_stack([np.arange(len(target)),target]))
    np.savetxt(str(stem)+".delta.txt",mean)
    row,col = np.triu_indices(4)
    upper = np.column_stack([row,col,covariance[row,col]])
    np.savetxt(str(stem)+".covariance.tsv",upper)
    result = native_trace_gate(stem)
    assert result["passed"] and result["dynamic_indices"] == [0,1]
    assert set(result["native_checks"]) == {"native_map","native_covariance"}
    np.savetxt(str(stem)+".covariance.tsv",upper[:-1])
    with pytest.raises(ValueError,match="every upper"):
        native_trace_gate(stem)
