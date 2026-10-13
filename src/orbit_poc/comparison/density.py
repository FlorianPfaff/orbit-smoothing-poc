"""Stationary log-density OU prior and independent small-system validation.

The prior is exact at its knots. Between knots the *log* multiplier is linearly
interpolated; this is a specified discrete model, not an OU bridge approximation.
No jitter or clipping is added to either the prior or exp(log-density).
"""
from __future__ import annotations

import numpy as np
from scipy import sparse
from scipy.linalg import qr, solve_triangular


def _times(value, name="times"):
    result = np.asarray(value, dtype=float)
    if result.ndim != 1 or result.size == 0 or not np.isfinite(result).all():
        raise ValueError(f"{name} must be a nonempty finite one-dimensional array")
    if np.any(np.diff(result) <= 0):
        raise ValueError(f"{name} must be strictly increasing")
    return result


def density_knots(start, stop, spacing=60.0):
    """Include both arc endpoints; only a final partial interval may be shorter."""
    if not np.isfinite([start, stop, spacing]).all() or stop < start or spacing <= 0:
        raise ValueError("Finite ordered endpoints and positive knot spacing required")
    knots = float(start) + float(spacing) * np.arange(int(np.floor((stop - start) / spacing)) + 1)
    if knots[-1] < stop - 8 * np.finfo(float).eps * max(1.0, abs(stop)):
        knots = np.append(knots, float(stop))
    else:
        knots[-1] = float(stop)
    return knots


def ou_prior_factor(times, tau, sigma, mean=0.0):
    """Return CSR W and offset c with residual W @ log_g - c.

    log_g[0] ~ N(mean,sigma²), followed by exact OU transitions with
    phi=exp(-dt/tau) and variance=sigma²[-expm1(-2dt/tau)]. The initial stationary
    prior is part of the model, including for a one-knot arc.
    """
    times = _times(times)
    if not np.isfinite([tau, sigma, mean]).all() or tau <= 0 or sigma <= 0:
        raise ValueError("Finite positive tau and sigma and a finite mean are required")
    phi = np.exp(-np.diff(times) / tau)
    sd = sigma * np.sqrt(-np.expm1(-2.0 * np.diff(times) / tau))
    if np.any(sd <= 0) or not np.isfinite(sd).all():
        raise ValueError("OU transition variance is outside floating-point range")
    diagonal = np.r_[1.0 / sigma, 1.0 / sd]
    factor = sparse.diags((-phi / sd, diagonal), (-1, 0), shape=(len(times), len(times)), format="csr")
    # Use the exact drift expression: 1-exp(-dt/tau) would lose small increments.
    offset = np.r_[mean / sigma, mean * (-np.expm1(-np.diff(times) / tau)) / sd]
    return factor, offset


def ou_covariance(times, tau, sigma):
    times = _times(times)
    if not np.isfinite([tau, sigma]).all() or tau <= 0 or sigma <= 0:
        raise ValueError("Finite positive tau and sigma required")
    return sigma ** 2 * np.exp(-np.abs(times[:, None] - times[None, :]) / tau)


def ou_logpdf(log_g, times, tau, sigma, mean=0.0):
    factor, offset = ou_prior_factor(times, tau, sigma, mean)
    log_g = np.asarray(log_g, dtype=float)
    if log_g.shape != (factor.shape[1],) or not np.isfinite(log_g).all():
        raise ValueError("One finite log-density value per knot required")
    residual = ou_residuals(log_g, times, tau, sigma, mean)
    return float(-0.5 * residual @ residual + np.log(factor.diagonal()).sum()
                 - 0.5 * len(log_g) * np.log(2.0 * np.pi))


def ou_residuals(log_g, times, tau, sigma, mean=0.0):
    """Stable OU innovations, avoiding cancellation of nearly equal phi*g values."""
    times = _times(times)
    ou_prior_factor(times, tau, sigma, mean)  # identical parameter validation
    values = np.asarray(log_g, dtype=float)
    if values.shape != times.shape or not np.isfinite(values).all():
        raise ValueError("One finite log-density value per knot required")
    ratio = np.diff(times) / tau
    sd = sigma * np.sqrt(-np.expm1(-2 * ratio))
    innovation = np.diff(values) + (-np.expm1(-ratio)) * (values[:-1] - mean)
    return np.r_[(values[0] - mean) / sigma, innovation / sd]


def interpolation_weights(knots, times):
    """CSR derivative of interpolated log-density with respect to knot values."""
    knots = _times(knots, "knots")
    query = np.asarray(times, dtype=float)
    if query.ndim != 1 or not np.isfinite(query).all():
        raise ValueError("Query times must be a finite one-dimensional array")
    if np.any(query < knots[0]) or np.any(query > knots[-1]):
        raise ValueError("Density extrapolation outside the knot interval is not defined")
    if len(knots) == 1:
        return sparse.csr_matrix(np.ones((len(query), 1)))
    left = np.clip(np.searchsorted(knots, query, side="right") - 1, 0, len(knots) - 2)
    weight = (query - knots[left]) / (knots[left + 1] - knots[left])
    rows = np.repeat(np.arange(len(query)), 2)
    cols = np.column_stack((left, left + 1)).ravel()
    values = np.column_stack((1.0 - weight, weight)).ravel()
    result = sparse.csr_matrix((values, (rows, cols)), shape=(len(query), len(knots)))
    result.eliminate_zeros()
    return result


def density_multiplier(log_g, knots, times, return_jacobian=False):
    weights = interpolation_weights(knots, times)
    log_g = np.asarray(log_g, dtype=float)
    if log_g.shape != (weights.shape[1],) or not np.isfinite(log_g).all():
        raise ValueError("One finite log-density value per knot required")
    with np.errstate(over="raise", invalid="raise"):
        multiplier = np.exp(weights @ log_g)
    if np.any(multiplier == 0):
        raise FloatingPointError("Density multiplier underflow; logarithmic parameters are outside representable range")
    if return_jacobian:
        return multiplier, sparse.diags(multiplier) @ weights
    return multiplier


def jacobian_gate(function, analytic, point, *, relative_tolerance=1e-5,
                  absolute_tolerance=1e-12, relative_step=1e-5):
    """Central finite differences, with explicit componentwise acceptance bounds."""
    point = np.asarray(point, dtype=float)
    if point.ndim != 1 or not np.isfinite(point).all() or relative_step <= 0:
        raise ValueError("A finite parameter vector and positive finite-difference step are required")
    exact = np.asarray(analytic(point) if callable(analytic) else analytic, dtype=float)
    numerical = np.empty_like(exact)
    for j, value in enumerate(point):
        step = relative_step * max(1.0, abs(value))
        plus, minus = point.copy(), point.copy()
        plus[j] += step
        minus[j] -= step
        numerical[:, j] = (np.asarray(function(plus)) - np.asarray(function(minus))) / (2.0 * step)
    difference = np.abs(exact - numerical)
    bound = absolute_tolerance + relative_tolerance * np.abs(numerical)
    finite = bool(np.isfinite(exact).all() and np.isfinite(numerical).all())
    return {"passed": finite and bool(np.all(difference <= bound)),
            "maximum_absolute_error": float(difference.max(initial=0)),
            "relative_frobenius_error": float(np.linalg.norm(difference) / max(np.linalg.norm(numerical), np.finfo(float).tiny)),
            "relative_tolerance": relative_tolerance, "absolute_tolerance": absolute_tolerance,
            "relative_step": relative_step, "finite": finite}


def qr_map_covariance(design, target):
    """Independent pivoted-QR solution and full covariance of a proper Gaussian."""
    design, target = np.asarray(design, dtype=float), np.asarray(target, dtype=float)
    if (design.ndim != 2 or target.shape != (design.shape[0],)
            or design.shape[0] < design.shape[1] or design.shape[1] == 0
            or not np.isfinite(design).all() or not np.isfinite(target).all()):
        raise ValueError("A finite, overdetermined design and matching target are required")
    column_norm = np.linalg.norm(design, axis=0)
    if np.any(column_norm == 0):
        raise ValueError("Improper Gaussian: design is rank deficient; an unobserved parameter needs an explicit proper prior")
    scales = 1. / column_norm
    q, r, permutation = qr(design * scales, mode="economic", pivoting=True)
    tolerance = np.finfo(float).eps * max(design.shape) * abs(r[0, 0])
    if np.any(np.abs(np.diag(r)) <= tolerance):
        raise ValueError("Improper Gaussian: design is rank deficient; supply proper clock/ambiguity gauges")
    pivot_solution = solve_triangular(r, q.T @ target)
    inverse_r = solve_triangular(r, np.eye(r.shape[0]))
    solution = np.empty(design.shape[1])
    solution[permutation] = pivot_solution
    covariance = np.empty((design.shape[1], design.shape[1]))
    covariance[np.ix_(permutation, permutation)] = inverse_r @ inverse_r.T
    return solution * scales, covariance * scales[:, None] * scales[None, :]


def independent_linear_gate(design, target, state_indices, thresholds=None):
    """Compute joint MAP and nuisance-marginal state covariance by GTSAM and QR.

    All rows must already be whitened. All proper priors, OU initial/transition
    factors and nuisance gauge rows must be present in ``design``. GTSAM performs
    its own nuisance elimination; this does not compare an implementation with a
    copy of its covariance. An unavailable GTSAM installation is an explicit error.
    """
    import gtsam

    design, target = np.asarray(design, dtype=float), np.asarray(target, dtype=float)
    qr_mean, qr_covariance = qr_map_covariance(design, target)
    selected = np.asarray(state_indices, dtype=int)
    if (selected.ndim != 1 or len(selected) == 0 or len(np.unique(selected)) != len(selected)
            or np.any(selected < 0) or np.any(selected >= design.shape[1])):
        raise ValueError("state_indices must be a nonempty unique set of parameter columns")
    nuisance = np.setdiff1d(np.arange(design.shape[1]), selected)
    scales = 1. / np.linalg.norm(design, axis=0)
    equilibrated = design * scales
    noise = gtsam.noiseModel.Unit.Create(len(target))
    if len(nuisance):
        factor = gtsam.JacobianFactor(0, equilibrated[:, selected], 1, equilibrated[:, nuisance], target, noise)
        order = gtsam.Ordering(); order.push_back(1)
        nuisance_conditional, reduced = factor.eliminate(order)
    else:
        reduced = gtsam.JacobianFactor(0, equilibrated[:, selected], target, noise)
    order = gtsam.Ordering(); order.push_back(0)
    state_conditional, _ = reduced.eliminate(order)
    values = state_conditional.solve(gtsam.VectorValues())
    if len(nuisance):
        values.insert(nuisance_conditional.solve(values))
    mean = np.empty_like(qr_mean)
    mean[selected] = values.at(0) * scales[selected]
    if len(nuisance):
        mean[nuisance] = values.at(1) * scales[nuisance]
    # JacobianFactor.eliminate performs square-root QR directly. Eliminate the
    # nuisance key first; the remaining R is the marginal state factor.
    root_information = state_conditional.R() / state_conditional.get_model().sigmas()[:, None]
    inverse_root = solve_triangular(root_information, np.eye(len(selected)))
    gtsam_covariance = (inverse_root @ inverse_root.T) * scales[selected, None] * scales[None, selected]
    reference_covariance = qr_covariance[np.ix_(selected, selected)]
    map_error = float(np.max(np.abs(mean - qr_mean) / np.sqrt(np.diag(qr_covariance))))
    covariance_error = float(np.linalg.norm(gtsam_covariance - reference_covariance)
                             / np.linalg.norm(reference_covariance))
    limits = {"normalized_map_discrepancy": 1e-7, "relative_covariance_error": 1e-8,
              **(thresholds or {})}
    return {"passed": map_error < limits["normalized_map_discrepancy"]
                      and covariance_error < limits["relative_covariance_error"],
            "normalized_map_discrepancy": map_error, "relative_covariance_error": covariance_error,
            "thresholds": limits, "parameter_count": design.shape[1], "state_parameter_count": len(selected),
            "nuisance_parameter_count": len(nuisance), "covariance_scope": "fully marginalized over nuisance parameters",
            "gtsam_map": mean.tolist(), "qr_map": qr_mean.tolist(),
            "qr_marginal_standard_deviations": np.sqrt(np.diag(qr_covariance)).tolist(),
            "factorization": "GTSAM JacobianFactor QR nuisance elimination versus independent column-equilibrated pivoted SciPy QR",
            "gtsam_state_covariance": gtsam_covariance.tolist(), "qr_state_covariance": reference_covariance.tolist(),
            "gtsam_objective": float(0.5 * np.sum((design @ mean - target) ** 2)),
            "qr_objective": float(0.5 * np.sum((design @ qr_mean - target) ** 2))}


def native_trace_gate(stem, thresholds=None, configuration=None):
    """Compare actual pre-normal-equation native rows with GTSAM and pivoted QR.

    A snapshot has a native update, a full native inverse, or both. Each check
    uses its own frozen linearization. Native normal matrices are never square
    rooted to construct the independent design.
    """
    from pathlib import Path
    from scipy.sparse import coo_matrix
    from .protocol import file_hash

    stem = Path(stem)
    path = lambda suffix: Path(str(stem) + suffix)
    records = [line.split("\t", 2) for line in path(".parameters.tsv").read_text().splitlines() if line.strip()]
    indices = np.array([int(row[0]) for row in records])
    if not np.array_equal(indices, np.arange(len(records))):
        raise ValueError("Native parameter ordering is incomplete or duplicated")
    names = [row[2] for row in records]
    rhs = np.loadtxt(path(".rhs.tsv"), ndmin=2)
    if rhs.shape[1] != 2 or not np.array_equal(rhs[:, 0], np.arange(len(rhs))):
        raise ValueError("Native RHS row ordering is incomplete or duplicated")
    entries = np.loadtxt(path(".design.tsv"), ndmin=2)
    if entries.shape[1] != 3 or np.any(entries[:, :2] != np.floor(entries[:, :2])):
        raise ValueError("Invalid native sparse-design indices")
    if len(rhs)*len(records) > 100_000_000:
        raise ValueError("Native independent gate exceeds the bounded small-system memory budget")
    design = coo_matrix((entries[:, 2], (entries[:, 0].astype(int), entries[:, 1].astype(int))),
                        shape=(len(rhs), len(records))).toarray()
    selected = np.array([i for i, name in enumerate(names) if any(
        key in name for key in ("logDensity", "stochasticPulse.", "position0.", "velocity0."))], dtype=int)
    # The stock native initial-state labels use stateVector.*.
    selected = np.unique(np.r_[selected, [i for i, name in enumerate(names) if "stateVector." in name]]).astype(int)
    if not len(selected):
        raise ValueError("No identifiable native dynamic parameter columns")
    result = independent_linear_gate(design, rhs[:, 1], selected, thresholds)
    reference_map = np.asarray(result["qr_map"])
    reference_covariance = np.asarray(result["qr_state_covariance"])
    standard_deviations = np.asarray(result["qr_marginal_standard_deviations"])
    checks = {}
    if configuration is not None:
        checks["native_prior_rows"] = _native_prior_rows(design, rhs[:, 1], records, configuration)
    files = [path(suffix) for suffix in (".parameters.tsv", ".rhs.tsv", ".design.tsv")]
    if configuration is not None:
        import xml.etree.ElementTree as ET
        files.append(Path(configuration))
        prior_node = ET.parse(configuration).getroot().find(".//parametrization/logDensityOu")
        if prior_node is not None:
            reference_path = Path(prior_node.findtext("inputfileLogDensity"))
            if not reference_path.is_absolute():
                reference_path = Path(configuration).resolve().parent / reference_path
            files.append(reference_path)
    if path(".delta.txt").exists():
        native_map = np.loadtxt(path(".delta.txt"), ndmin=1)
        if native_map.shape != reference_map.shape or not np.isfinite(native_map).all():
            raise ValueError("Native increment does not match the exported parameter ordering")
        error = float(np.max(abs(native_map-reference_map)/standard_deviations))
        checks["native_map"] = {"passed":error < result["thresholds"]["normalized_map_discrepancy"],
                                "normalized_discrepancy":error, "scope":"all dynamic and nuisance parameters"}
        files.append(path(".delta.txt"))
    if path(".covariance.tsv").exists():
        rows = np.loadtxt(path(".covariance.tsv"), ndmin=2)
        count = len(records)
        expected = count*(count+1)//2
        if rows.shape != (expected, 3) or np.any(rows[:, :2] != np.floor(rows[:, :2])):
            raise ValueError("Native full inverse must export every upper-triangular entry")
        covariance = np.zeros((count, count))
        row, col = rows[:, 0].astype(int), rows[:, 1].astype(int)
        if np.any(row > col) or len(np.unique(row*count+col)) != expected:
            raise ValueError("Native full inverse has missing or duplicate entries")
        covariance[row, col] = rows[:, 2]; covariance[col, row] = rows[:, 2]
        marginal = covariance[np.ix_(selected, selected)]
        error = float(np.linalg.norm(marginal-reference_covariance)/np.linalg.norm(reference_covariance))
        checks["native_covariance"] = {"passed":error < result["thresholds"]["relative_covariance_error"],
                                      "relative_error":error, "scope":"dynamic parameter block marginalized over all GNSS nuisance parameters"}
        files.append(path(".covariance.tsv"))
    if not checks:
        raise ValueError("Native trace has neither a solved increment nor a full inverse")
    return {"passed":result["passed"] and all(check["passed"] for check in checks.values()),
            "native_checks":checks, "independent_comparison":result,
            "dynamic_indices":selected.tolist(), "dynamic_names":[names[i] for i in selected],
            "rows":len(rhs), "columns":len(records),
            "source":"native whitened sparse rows exported before A'A accumulation; constraints and proper gauges included",
            "snapshot":str(stem.resolve()), "artifacts":[{"path":str(p.resolve()), "sha256":file_hash(p)} for p in files]}


def _native_prior_rows(design, target, records, configuration):
    """Check exported native prior factors against independent analytic priors."""
    import xml.etree.ElementTree as ET
    from pathlib import Path
    names = [row[2] for row in records]
    apriori = np.array([float(row[1]) for row in records])
    tree = ET.parse(configuration).getroot()
    prior = tree.find(".//parametrization/logDensityOu")
    if prior is not None:
        columns = np.array([i for i,name in enumerate(names) if ":logDensity:" in name])
        reference_path = Path(prior.findtext("inputfileLogDensity"))
        if not reference_path.is_absolute():
            reference_path = Path(configuration).resolve().parent / reference_path
        reference = np.loadtxt(reference_path, ndmin=2, dtype=np.longdouble)
        if reference.shape != (len(columns),2):
            raise ValueError("Native OU reference file does not match ordered density columns")
        tau, sigma = float(prior.findtext("tau")), float(prior.findtext("sigma"))
        # Read the actual decimal MJD knot locations, including their finite
        # representation, rather than silently replacing them with ideal times.
        times = np.asarray((reference[:, 0]-reference[0, 0])*np.longdouble(86400), dtype=float)
        expected, _ = ou_prior_factor(times, tau, sigma)
        expected = expected.toarray()
        expected_target = -expected @ (np.asarray(reference[:, 1], dtype=float)+apriori[columns])
        model = "stationary initial OU plus exact transition rows on full reference g + current increment"
        details = {"tau_seconds":tau,"sigma_log_density":sigma,"knots":len(columns),
                   "reference_log_density_included":True}
    else:
        columns = np.array([i for i,name in enumerate(names) if ":stochasticPulse." in name])
        prior = next((node for node in tree.findall(".//parametrization/constraints")
                      if node.findtext("name") == "constraint.pulses"), None)
        if prior is None or not len(columns):
            raise ValueError("Native gate requires explicit full-value pulse or OU priors")
        if prior.findtext("relativeToApriori", "0") != "0":
            raise ValueError("Pulse prior constrains increments instead of full pulse values")
        sigma = float(prior.findtext("sigma")); bias = float(prior.findtext("bias", "0"))
        expected = np.eye(len(columns))/sigma
        expected_target = (bias-apriori[columns])/sigma
        model = "independent full-value CRF pulse rows with native micrometre/second units"
        details = {"native_sigma_um_s":sigma,"physical_sigma_velocity_m_s":sigma*1e-6,
                   "pulse_components":len(columns),"full_apriori_value_included":True}
    other = np.setdiff1d(np.arange(design.shape[1]), columns)
    selected_rows = np.flatnonzero(np.any(design[:,columns] != 0,axis=1) & ~np.any(design[:,other] != 0,axis=1))
    if len(selected_rows) != len(columns):
        raise ValueError("Native prior rows are missing, duplicated or mixed with observations")
    actual = design[np.ix_(selected_rows,columns)]
    actual_target = target[selected_rows]
    coefficient_error = float(np.max(abs(actual-expected)))
    target_error = float(np.max(abs(actual_target-expected_target)))
    # Decimal MJD round trips can affect sub-microsecond knot spacing; both
    # coefficient and residual tolerances remain explicit and independent of fit.
    rtol, atol = 1e-10, 1e-12
    passed = np.allclose(actual,expected,rtol=rtol,atol=atol) and np.allclose(actual_target,expected_target,rtol=rtol,atol=atol)
    return {"passed":bool(passed),"model":model,**details,"maximum_coefficient_error":coefficient_error,
            "maximum_target_error":target_error,"relative_tolerance":rtol,"absolute_tolerance":atol,
            "native_rows":selected_rows.tolist()}
