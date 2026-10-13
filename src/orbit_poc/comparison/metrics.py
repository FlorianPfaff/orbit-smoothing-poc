"""Predictive scores and seed-level uncertainty summaries with explicit failures."""
from __future__ import annotations

from itertools import combinations
from statistics import NormalDist

import numpy as np
from scipy.linalg import null_space, solve_triangular

CHI2_POSITION_95 = 7.814727903251179


def _covariance(value, size):
    result = np.asarray(value, dtype=float)
    if result.ndim == 0:
        result = np.eye(size) * result
    elif result.ndim == 1:
        result = np.diag(result)
    if result.shape != (size, size) or not np.isfinite(result).all():
        raise ValueError("Covariance must be a finite square matrix of the required dimension")
    if not np.allclose(result, result.T, rtol=1e-10, atol=1e-14):
        raise ValueError("Covariance is not symmetric")
    return (result + result.T) / 2


def gaussian_score(residual, covariance):
    """Gaussian NLL including normalization/log determinant; never repair a covariance."""
    residual = np.asarray(residual, dtype=float)
    if residual.ndim != 1 or not np.isfinite(residual).all() or not len(residual):
        return {"valid": False, "nll": None, "nees": None, "logdet": None,
                "dimensions": int(residual.size), "reason": "Nonempty finite residual required"}
    try:
        covariance = _covariance(covariance, len(residual))
        root = np.linalg.cholesky(covariance)
        whitened = solve_triangular(root, residual, lower=True)
        nees = float(whitened @ whitened)
        logdet = float(2 * np.log(np.diag(root)).sum())
        nll = 0.5 * (nees + logdet + len(residual) * np.log(2 * np.pi))
        if not np.isfinite([nees, logdet, nll]).all():
            raise ValueError("Nonfinite Gaussian score")
        return {"valid": True, "nll": float(nll), "nees": nees, "logdet": logdet,
                "dimensions": len(residual), "nll_per_dimension": float(nll / len(residual))}
    except (ValueError, np.linalg.LinAlgError) as error:
        return {"valid": False, "nll": None, "nees": None, "logdet": None,
                "dimensions": len(residual), "reason": str(error)}


def clock_nullspace_nll(residual, measurement_covariance, design=None,
                        parameter_covariance=None, clock_design=None):
    """Score held-out code after projecting out an unobserved receiver clock.

    B has orthonormal columns spanning null(clock_design.T). The full predictive
    covariance is B.T @ (R + H P H.T) @ B. By default clock_design is an all-ones
    column, so m satellites retain m-1 dimensions. One satellite supplies no
    clock-free information and cannot be used to select a hyperparameter.
    ``measurement_covariance`` contains variances, not standard deviations.
    """
    residual = np.asarray(residual, dtype=float)
    if residual.ndim != 1 or not np.isfinite(residual).all():
        raise ValueError("Finite one-dimensional held-out residual required")
    m = len(residual)
    clocks = np.ones((m, 1)) if clock_design is None else np.asarray(clock_design, dtype=float)
    if clocks.ndim != 2 or clocks.shape[0] != m or not np.isfinite(clocks).all():
        raise ValueError("clock_design must have one finite row per observation")
    basis = null_space(clocks.T)
    retained = basis.shape[1]
    common = {"satellites": m, "retained_dimensions": retained,
              "clock_rank": m - retained, "projection_basis": basis.tolist(),
              "informative": retained > 0}
    if retained == 0:
        return {**common, "valid": False, "status": "no_information", "nll": None,
                "nll_per_dimension": None, "logdet": None,
                "reason": "No residual dimensions remain after clock projection"}
    try:
        predictive = _covariance(measurement_covariance, m)
        np.linalg.cholesky(predictive)
        if (design is None) != (parameter_covariance is None):
            raise ValueError("Supply both the predictive design and parameter covariance")
        if design is not None:
            design = np.asarray(design, dtype=float)
            if design.ndim != 2 or design.shape[0] != m or not np.isfinite(design).all():
                raise ValueError("Predictive design must have one finite row per observation")
            covariance = _covariance(parameter_covariance, design.shape[1])
            # A posterior covariance must itself be positive definite; projecting
            # it must not hide an invalid nuisance/state covariance.
            np.linalg.cholesky(covariance)
            predictive = predictive + design @ covariance @ design.T
        projected_residual = basis.T @ residual
        projected_covariance = basis.T @ predictive @ basis
        score = gaussian_score(projected_residual, projected_covariance)
        return {**common, **score, "projected_residual": projected_residual.tolist(),
                "projected_covariance": projected_covariance.tolist(),
                "status": "complete" if score["valid"] else "invalid_covariance"}
    except (ValueError, np.linalg.LinAlgError) as error:
        return {**common, "valid": False, "status": "invalid_covariance", "nll": None,
                "nll_per_dimension": None, "logdet": None, "reason": str(error)}


def aggregate_clock_scores(scores):
    """Normalize per retained dimension, average epochs within arcs, then arcs equally.

    Each item includes ``arc_id`` and a clock_nullspace_nll result. Invalid
    informative epochs invalidate the aggregate. Uninformative one-satellite
    epochs are explicitly counted and excluded from score denominators.
    """
    arcs, invalid, uninformative, dimensions = {}, [], 0, 0
    for index, row in enumerate(scores):
        arc = str(row.get("arc_id", "0"))
        arcs.setdefault(arc, [])
        if not row.get("informative", row.get("retained_dimensions", 0) > 0):
            uninformative += 1
        elif (not row.get("valid") or not isinstance(row.get("nll_per_dimension"), (int, float))
              or not np.isfinite(row["nll_per_dimension"])):
            invalid.append(index)
        else:
            arcs[arc].append(float(row["nll_per_dimension"]))
            dimensions += int(row["retained_dimensions"])
    arc_means = {arc: float(np.mean(values)) if values else None for arc, values in arcs.items()}
    valid = bool(arcs and not invalid and all(value is not None for value in arc_means.values()))
    return {"valid": valid, "mean_nll": float(np.mean(list(arc_means.values()))) if valid else None,
            "dimensions": dimensions, "retained_dimensions": dimensions,
            "arc_count": len(arcs), "arc_mean_nll": arc_means,
            "invalid_epoch_indices": invalid, "uninformative_epochs": uninformative,
            "normalization": "NLL per retained dimension; equal epoch weight within each arc; equal arc weight"}


def rtn_errors(states, truth):
    states, truth = np.asarray(states, dtype=float), np.asarray(truth, dtype=float)
    if states.ndim != 2 or truth.shape != states.shape or states.shape[1] < 6:
        raise ValueError("Matching state and truth arrays with Cartesian position and velocity required")
    r, v = truth[:, :3], truth[:, 3:6]
    radial_norm = np.linalg.norm(r, axis=1)
    h = np.cross(r, v)
    normal_norm = np.linalg.norm(h, axis=1)
    if np.any(radial_norm == 0) or np.any(normal_norm == 0):
        raise ValueError("RTN axes are undefined for zero radius or angular momentum")
    radial, normal = r / radial_norm[:, None], h / normal_norm[:, None]
    transverse = np.cross(normal, radial)
    basis = np.stack((radial, transverse, normal), axis=1)
    return np.einsum("nij,nj->ni", basis, states[:, :3] - truth[:, :3])


def position_metrics(times, states, truth, covariance=None, gap_mask=None,
                     coverage_epochs=(39600.0, 43200.0, 46800.0)):
    """Synthetic-only position errors and marginal Gaussian uncertainty diagnostics.

    The three default coverage epochs are 11,12,13 h from the arc start. Wilson
    intervals are subsequently computed *across seeds* at each fixed epoch.
    Time samples from one trajectory are not independent coverage trials.
    """
    times, states, truth = np.asarray(times, dtype=float), np.asarray(states, dtype=float), np.asarray(truth, dtype=float)
    if (times.ndim != 1 or len(times) == 0 or states.shape != truth.shape or states.shape[0] != len(times)
            or states.ndim != 2 or states.shape[1] < 6 or np.any(np.diff(times) <= 0)
            or not all(np.isfinite(item).all() for item in (times, states, truth))):
        raise ValueError("Finite, time-aligned six-dimensional states and strictly ordered epochs required")
    gap = np.zeros(len(times), dtype=bool) if gap_mask is None else np.asarray(gap_mask, dtype=bool)
    if gap.shape != times.shape:
        raise ValueError("gap_mask must match epochs")
    error = states[:, :3] - truth[:, :3]
    rtn = rtn_errors(states, truth)

    def errors(mask):
        return {"epochs": int(mask.sum()),
                "position_rmse_m": float(np.sqrt(np.mean(np.sum(error[mask] ** 2, axis=1)))) if mask.any() else None,
                "rtn_rmse_m": np.sqrt(np.mean(rtn[mask] ** 2, axis=0)).tolist() if mask.any() else None}

    full = errors(np.ones(len(times), dtype=bool))
    gap_errors = errors(gap)
    result = {"valid": True, "interpretation": "synthetic truth error", "whole_arc": full, "gap": gap_errors,
              "position_rmse_m": full["position_rmse_m"], "gap_position_rmse_m": gap_errors["position_rmse_m"],
              "fixed_epoch_coverage": [], "covariance_valid": None}
    if covariance is None:
        return result
    covariance = np.asarray(covariance, dtype=float)
    if covariance.ndim != 3 or covariance.shape[0] != len(times) or covariance.shape[1] != covariance.shape[2] or covariance.shape[1] < 3:
        raise ValueError("One Cartesian marginal covariance per epoch required")
    scores = [gaussian_score(e, p[:3, :3]) for e, p in zip(error, covariance)]
    valid = np.array([score["valid"] for score in scores])
    result["covariance_valid"] = bool(valid.all())
    result["invalid_covariance_epochs"] = np.flatnonzero(~valid).tolist()
    result["uncertainty_interpretation"] = (
        "Local Gaussian covariance conditional on selected hyperparameters and fixed measurement weights; "
        "marginal interval widths use 1.959964 standard deviations on each side, "
        "joint ellipsoid semiaxes use the chi-square(3) 95% quantile. "
        "Model-selection uncertainty is excluded.")
    r, v = truth[:, :3], truth[:, 3:6]
    radial = r / np.linalg.norm(r, axis=1)[:, None]
    normal = np.cross(r, v)
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    basis = np.stack((radial, np.cross(normal, radial), normal), axis=1)
    rtn_covariance = np.einsum("nij,njk,nlk->nil", basis, covariance[:, :3, :3], basis)
    z = NormalDist().inv_cdf(.975)
    for mask, key in ((np.ones(len(times), dtype=bool), "whole_arc"), (gap, "gap")):
        usable = mask.any() and bool(valid[mask].all())
        result[key].update(position_nll=float(np.mean([scores[i]["nll"] for i in np.flatnonzero(mask)])) if usable else None,
                           position_nees=float(np.mean([scores[i]["nees"] for i in np.flatnonzero(mask)])) if usable else None)
        result[key].update(mean_marginal_95_width_crf_m=None, mean_marginal_95_width_rtn_m=None,
                           mean_joint_95_ellipsoid_semiaxes_m=None, maximum_joint_95_semimajor_axis_m=None)
        if usable:
            blocks = covariance[mask, :3, :3]
            semiaxes = np.sqrt(CHI2_POSITION_95 * np.linalg.eigvalsh(blocks))
            result[key].update(
                mean_marginal_95_width_crf_m=(2*z*np.sqrt(np.diagonal(blocks, axis1=1, axis2=2))).mean(axis=0).tolist(),
                mean_marginal_95_width_rtn_m=(2*z*np.sqrt(np.diagonal(rtn_covariance[mask], axis1=1, axis2=2))).mean(axis=0).tolist(),
                mean_joint_95_ellipsoid_semiaxes_m=semiaxes.mean(axis=0).tolist(),
                maximum_joint_95_semimajor_axis_m=float(semiaxes[:, -1].max()))
    result["position_nll"] = result["whole_arc"]["position_nll"]
    result["position_nees"] = result["whole_arc"]["position_nees"]
    relative_times = times - times[0]
    for epoch in coverage_epochs:
        matching = np.flatnonzero(np.isclose(relative_times, epoch, rtol=0, atol=1e-6))
        row = {"seconds_since_start": float(epoch), "hours_since_start": float(epoch / 3600), "covered": None, "valid": False}
        if len(matching):
            i = int(matching[0])
            row.update(valid=scores[i]["valid"], nees=scores[i]["nees"],
                       covered=bool(scores[i]["nees"] <= CHI2_POSITION_95) if scores[i]["valid"] else None)
        else:
            row["reason"] = "The fixed epoch is not present on this trajectory grid"
        result["fixed_epoch_coverage"].append(row)
    return result


def wilson_interval(successes, trials, confidence=0.95):
    if trials < 0 or successes < 0 or successes > trials or not 0 < confidence < 1:
        raise ValueError("Valid binomial counts and confidence level required")
    if trials == 0:
        return {"successes": 0, "trials": 0, "estimate": None, "interval": None}
    z = NormalDist().inv_cdf(0.5 + confidence / 2)
    p = successes / trials
    denominator = 1 + z * z / trials
    center = (p + z * z / (2 * trials)) / denominator
    half = z / denominator * np.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return {"successes": int(successes), "trials": int(trials), "estimate": p,
            "interval": [max(0.0, float(center - half)), min(1.0, float(center + half))], "confidence": confidence}


def _valid_run(row):
    return (row.get("status") == "complete" and bool(row.get("converged", False))
            and bool(row.get("covariance_valid", False)))


def _metric(row, name):
    value = row.get("metrics", {})
    for part in name.split("."):
        if isinstance(value, (list, tuple)) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        elif isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value if isinstance(value, (int, float)) and np.isfinite(value) else None


def _planned_runs(records, planned_records=None):
    """Index the immutable design as well as observed rows; never infer missing seeds."""
    def index(rows):
        result = {}
        for row in rows:
            key = (str(row.get("cell_id", row.get("cell", "all"))),
                   str(row.get("method_id", row.get("method", "unknown"))), row.get("seed"))
            if key in result:
                raise ValueError(f"Duplicate fit for {key}")
            result[key] = row
        return result
    actual = index(records)
    planned = index(planned_records) if planned_records is not None else actual
    if planned_records is not None and set(actual) - set(planned):
        raise ValueError("Observed fits lie outside the frozen planned cases")
    return actual, planned


def paired_seed_statistics(records, metric="gap_position_rmse_m", *, bootstrap_draws=10000,
                           bootstrap_seed=1729, minimum_seeds=5, planned_records=None):
    """Paired bootstrap across seeds, retaining failure/missing counts explicitly."""
    groups, planned = _planned_runs(records, planned_records)
    rng = np.random.default_rng(bootstrap_seed)
    output = []
    for cell in sorted({key[0] for key in planned}):
        methods = sorted({key[1] for key in planned if key[0] == cell})
        for first, second in combinations(methods, 2):
            keys = [key for key in planned if key[0] == cell and key[1] in (first, second)]
            seeds = sorted({key[2] for key in keys}, key=str)
            applicable = not ((metric == "gap_position_rmse_m" or metric.startswith("gap."))
                              and all(planned[key].get("coverage") == "normal" for key in keys))
            differences, failed = [], []
            for seed in seeds:
                if not applicable:
                    continue
                a, b = groups.get((cell, first, seed)), groups.get((cell, second, seed))
                av, bv = _metric(a or {}, metric), _metric(b or {}, metric)
                if a and b and _valid_run(a) and _valid_run(b) and av is not None and bv is not None:
                    differences.append(float(av - bv))
                else:
                    failed.append(seed)
            interval = None
            if len(differences) >= minimum_seeds:
                draws = rng.choice(differences, size=(bootstrap_draws, len(differences)), replace=True).mean(axis=1)
                interval = np.quantile(draws, [0.025, 0.975]).tolist()
            output.append({"cell_id": cell, "method_a": first, "method_b": second, "metric": metric,
                           "planned_seed_pairs": len(seeds),
                           "attempted_seed_pairs": len({key[2] for key in groups if key[0] == cell and key[1] in (first, second)}),
                           "valid_seed_pairs": len(differences), "applicable": applicable,
                           "status": "not_applicable" if not applicable else "complete" if not failed else "incomplete",
                           "not_applicable_seed_pairs": len(seeds) if not applicable else 0,
                           "failed_or_missing_seed_pairs": len(failed), "failed_or_missing_seeds": failed,
                           "mean_difference_a_minus_b": float(np.mean(differences)) if differences else None,
                           "bootstrap_95_interval": interval, "bootstrap_unit": "paired independent seed",
                           "minimum_seeds_for_interval": minimum_seeds,
                           "complete": not failed, "interpretation": "Negative favors method_a for an error metric; failed fits are not counted as successes."})
    return output


def fixed_epoch_coverage(records, epochs_hours=(11.0, 12.0, 13.0), *, planned_records=None):
    output = []
    actual, planned = _planned_runs(records, planned_records)
    cells_methods = sorted({key[:2] for key in planned})
    for cell, method in cells_methods:
        keys = [key for key in planned if key[:2] == (cell, method)]
        rows = [actual[key] for key in keys if key in actual]
        seeds = [r.get("seed") for r in rows]
        if len(set(seeds)) != len(seeds):
            raise ValueError("Coverage trials must be unique independent seeds")
        for hour in epochs_hours:
            outcomes = []
            for row in rows:
                epoch = next((e for e in row.get("metrics", {}).get("fixed_epoch_coverage", [])
                              if np.isclose(e.get("hours_since_start", -1), hour)), None)
                if _valid_run(row) and epoch and epoch.get("valid") and isinstance(epoch.get("covered"), (bool, np.bool_)):
                    outcomes.append(bool(epoch["covered"]))
            output.append({"cell_id": cell, "method_id": method, "hours_since_start": hour,
                           **wilson_interval(sum(outcomes), len(outcomes)), "attempted_seeds": len(rows),
                           "planned_seeds": len(keys),
                           "failed_or_unavailable_seeds": len(keys) - len(outcomes),
                           "trial_unit": "one independent seed at this fixed epoch"})
    return output


def flight_residual_metrics(residual, sigma=None, predictive_covariance=None, reference_error=None):
    """Independent SLR predictive checks; flight reference agreement is never truth."""
    residual = np.asarray(residual, dtype=float)
    if residual.ndim != 1 or not np.isfinite(residual).all():
        raise ValueError("Finite scalar SLR residuals required")
    n = len(residual)
    result = {"kind": "independent flight SLR residuals", "observations": n,
              "mean_m": float(residual.mean()) if n else None,
              "rms_m": float(np.sqrt(np.mean(residual ** 2))) if n else None,
              "std_m": float(residual.std(ddof=1)) if n > 1 else None,
              "median_m": float(np.median(residual)) if n else None,
              "slr_used_in_fit": False, "truth_error_claim": False}
    if sigma is not None:
        sigma = np.broadcast_to(np.asarray(sigma, dtype=float), residual.shape)
        if np.any(sigma <= 0) or not np.isfinite(sigma).all():
            raise ValueError("Positive finite SLR measurement standard deviations required")
        result["measurement_normalized_rms"] = float(np.sqrt(np.mean((residual / sigma) ** 2))) if n else None
    if predictive_covariance is not None:
        score = gaussian_score(residual, predictive_covariance)
        result["predictive"] = score
        if score["valid"]:
            diagonal = np.diag(_covariance(predictive_covariance, n))
            result["predictive"]["marginal_95_fraction"] = float(np.mean(np.abs(residual) <= NormalDist().inv_cdf(0.975) * np.sqrt(diagonal)))
            result["predictive"]["coverage_note"] = "Descriptive correlated-observation fraction; no independent-trial confidence interval"
    if reference_error is not None:
        difference = np.asarray(reference_error, dtype=float)
        if difference.ndim != 2 or difference.shape[1] < 3 or not np.isfinite(difference).all():
            raise ValueError("Finite Cartesian differences to the flight reference required")
        result["reference_agreement"] = {"position_rms_m": float(np.sqrt(np.mean(np.sum(difference[:, :3] ** 2, axis=1)))),
                                         "interpretation": "agreement with an external reference; not known truth"}
    return result
