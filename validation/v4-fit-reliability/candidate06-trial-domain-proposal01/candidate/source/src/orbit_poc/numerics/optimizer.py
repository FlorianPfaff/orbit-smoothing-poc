"""Objective-checked variable-projection LM on native whitened QR factors.

The model adapter owns physical propagation and nuisance profiling. It returns
immutable evaluated points; a rejected point is never installed as the next
reference. Damping rows restrict a step and never enter posterior covariance.
"""
from dataclasses import dataclass, field
import time
from typing import Protocol

import numpy as np
from scipy.linalg import qr, solve_triangular, svdvals

from .config import Controls


INEXACT_PROFILE_FORCING_RATIO = 1e-3


class NumericalFailure(RuntimeError):
    def __init__(self, reason, message):
        super().__init__(message)
        self.reason = reason


class PhysicalTrialDomainFailure(NumericalFailure):
    """An evidenced forward-domain failure, recoverable only inside a trial."""

    def __init__(self, message, evidence):
        super().__init__("physical_trial_domain", message)
        self.evidence = evidence


class LinearSystem(Protocol):
    """Optional numerical representation of the same native linearization.

    The original-chart factor remains the statistical rank certificate.  An
    implementation may use different auxiliary coordinates to solve, but must
    return corrections/covariance in the original native coordinates.  It does
    not own the nonlinear objective, accepted physical state or convergence.
    """

    def validate(self, point): ...
    def certify_rank(self, point): ...
    def proposal(self, point, damping=0.): ...
    def selected_covariance(self, point, design): ...


@dataclass(frozen=True)
class Linearization:
    factor: np.ndarray
    rhs: np.ndarray
    scales: np.ndarray
    dynamic: np.ndarray
    effective_rows: int
    objective: float
    residual_energy: float
    support_hash: str
    state: object
    objective_floor: float = 0.
    metadata: dict = field(default_factory=dict)
    linear_system: LinearSystem | None = None

    def validate(self):
        r, b, s, d = self.factor, self.rhs, self.scales, self.dynamic
        n = len(s)
        if (r.shape != (n, n) or b.shape != (n,) or d.shape != (n,)
                or d.dtype != np.bool_ or not d.any() or self.effective_rows < n
                or not all(np.isfinite(v).all() for v in (r, b, s))
                or np.any(s <= 0) or not self.support_hash):
            raise NumericalFailure("invalid_linearization", "Invalid native QR factor or coordinate map")
        if not np.allclose(r, np.triu(r), rtol=0, atol=1e-13 * max(1., np.max(np.abs(r)))):
            raise NumericalFailure("invalid_linearization", "Native QR factor must be upper triangular")
        if not np.isfinite([self.objective, self.residual_energy, self.objective_floor]).all() or min(
                self.objective, self.residual_energy, self.objective_floor) < 0:
            raise NumericalFailure("invalid_objective", "Native objective and residual energy must be finite and nonnegative")
        if self.linear_system is not None:
            self.linear_system.validate(self)
        return self


def certify_rank(point):
    if point.linear_system is not None:
        return point.linear_system.certify_rank(point)
    return _dense_certify_rank(point)


def _dense_certify_rank(point):
    singular = svdvals(point.factor, check_finite=False)
    threshold = np.finfo(float).eps * max(point.effective_rows, len(singular)) * singular[0]
    rank = int(np.sum(singular > threshold))
    status = "full_rank" if singular[-1] > 10 * threshold else (
        "rank_deficient" if singular[-1] <= threshold else "unresolved_rank")
    result = {"status": status, "rank": rank, "columns": len(singular),
              "effective_rows": point.effective_rows, "threshold": float(threshold),
              "minimum_singular_value": float(singular[-1]), "maximum_singular_value": float(singular[0]),
              "condition_number": float(singular[0]/singular[-1]) if singular[-1] else None}
    if status != "full_rank":
        raise NumericalFailure(status, f"Undamped QR factor is {status}: {result}")
    return result


def proposal(point, damping=0.):
    """Return a step in native coordinates and its undamped predicted reduction."""
    if point.linear_system is not None:
        return point.linear_system.proposal(point, damping)
    return _dense_proposal(point, damping)


def _dense_proposal(point, damping=0.):
    if not np.isfinite(damping) or damping < 0:
        raise ValueError("Damping must be finite and nonnegative")
    r, b = point.factor, point.rhs
    if damping:
        penalty = np.eye(len(b))[point.dynamic] * np.sqrt(damping)
        q, augmented = qr(np.vstack((r, penalty)), mode="economic", check_finite=False)
        z = solve_triangular(augmented, q.T @ np.r_[b, np.zeros(len(penalty))], check_finite=False)
    else:
        z = solve_triangular(r, b, check_finite=False)
    change = r @ z
    predicted = float(b @ change - .5 * (change @ change))
    gradient = float(np.max(np.abs(r.T @ b)) / max(1., np.sqrt(2 * point.objective)))
    return point.scales * z, predicted, gradient


def selected_covariance(point, design):
    """G P G.T from the full retained QR, with global nuisances marginalized."""
    if point.linear_system is not None:
        return point.linear_system.selected_covariance(point, design)
    return _dense_selected_covariance(point, design)


def _dense_selected_covariance(point, design):
    _dense_certify_rank(point)
    design = np.asarray(design, dtype=float)
    if design.ndim != 2 or design.shape[1] != len(point.scales) or not np.isfinite(design).all():
        raise ValueError("Finite requested design with one column per retained parameter required")
    y = solve_triangular(point.factor.T, point.scales[:, None] * design.T, lower=True)
    return y.T @ y


class DenseLinearSystem:
    """Explicit adapter for the unchanged corrected v3.1 QR operations."""

    def validate(self, point):
        return None  # Linearization.validate already checks the native factor.

    def certify_rank(self, point):
        return _dense_certify_rank(point)

    def proposal(self, point, damping=0.):
        return _dense_proposal(point, damping)

    def selected_covariance(self, point, design):
        return _dense_selected_covariance(point, design)


def minimize(model, initial, *, controls=None, clock=time.monotonic, emit=None, started_at=None):
    """Adapter: evaluate(state,label,tighter=False), trial(point,step), finish(point).

    trial returns (candidate_state, {position_change_m,density_update,
    pulse_update_m_s}). evaluate closes the actual nonlinear trajectory and
    profiles nuisances. finish must independently re-evaluate the accepted point
    and export undamped covariance; it never applies a proposed final step.
    An optional accept(point) hook protects the installed factor during audited
    storage maintenance; rejected trial states never receive that protection.
    started_at shares the adapter's monotonic deadline, including initialization.
    """
    controls = controls or Controls()
    start = clock() if started_at is None else started_at
    accepted_count, trials, damping, multiplier = 0, 0, controls.initial_damping, 2.
    history = []
    confirmation_checks = []
    point = None
    floor_iteration = 0
    floor_measurement = None
    confirmation_refresh = None

    def remaining():
        if clock() - start >= controls.wall_time_seconds:
            raise NumericalFailure("timeout", "Per-fit wall time exceeded")

    def check(value):
        value.validate()
        if point is not None and value.support_hash != point.support_hash:
            raise NumericalFailure("changed_support", "Observations, weights or nuisance arcs changed during optimization")
        return value

    def install(value):
        nonlocal point
        point = value
        if hasattr(model, "accept"):
            model.accept(value)

    def small_correction(metrics):
        return (metrics["position_change_m"] < controls.maximum_position_change_m
                and metrics.get("density_update", 0.) < controls.maximum_density_update
                and metrics.get("pulse_update_m_s", 0.) < controls.maximum_pulse_update_m_s)

    def small(metrics, gradient):
        return small_correction(metrics) and gradient < controls.normalized_gradient_tolerance

    def limited_profile(value):
        return value.metadata.get("nuisance_floor_limited", False)

    def log(record):
        history.append(record)
        if emit:
            emit({"status": "running", "accepted_iterations": accepted_count,
                  "trial_evaluations": trials, "history": history,
                  "confirmation_checks": confirmation_checks})

    try:
        remaining()
        install(check(model.evaluate(initial, "initial")))
        repeated = check(model.evaluate(point.state, "repeat"))
        refined = check(model.evaluate(point.state, "closure-refinement", tighter=True))
        measured_floor = max(point.objective_floor, 10 * abs(repeated.objective-point.objective),
                             10 * abs(refined.objective-point.objective))
        install(refined)
        while True:
            remaining()
            floor = max(measured_floor, point.objective_floor,
                        8 * np.finfo(float).eps * abs(point.objective))
            rank = certify_rank(point)
            raw, _, gradient = proposal(point)
            _, raw_metrics = model.trial(point, raw)
            if small(raw_metrics, gradient) and not limited_profile(point):
                confirmed = check(model.evaluate(point.state, "confirmation", tighter=True))
                remaining()
                confirmation_rank = certify_rank(confirmed)
                correction, _, final_gradient = proposal(confirmed)
                _, final_metrics = model.trial(confirmed, correction)
                confirmation_checks.append({"accepted_iteration": accepted_count, "trial_evaluations": trials,
                    "physical_parameters_unchanged": True, "objective_before": point.objective,
                    "objective_refreshed": confirmed.objective, "rank": confirmation_rank,
                    "normalized_gradient": final_gradient, "raw_correction": final_metrics,
                    "nuisance_floor_limited": limited_profile(confirmed),
                    "stationary": small(final_metrics, final_gradient) and not limited_profile(confirmed)})
                if not small(final_metrics, final_gradient) or limited_profile(confirmed):
                    # A new representation of the same physical parameters
                    # can expose a correction hidden by closure/profiling
                    # roundoff. Continue from its fresh factor; do not count
                    # this as a physical update or accept covariance.
                    confirmation_refresh = {"physical_parameters_unchanged": True,
                        "objective_before": point.objective, "objective_refreshed": confirmed.objective,
                        "normalized_gradient": final_gradient, "raw_correction": final_metrics,
                        "reason": ("fresh_nuisance_profile_resolution_limited" if limited_profile(confirmed)
                                   else "fresh_undamped_correction_not_converged")}
                    install(confirmed)
                    continue
                result = model.finish(confirmed)
                remaining()
                log({"accepted": True, "confirmation": True, "objective": confirmed.objective,
                     "normalized_gradient": final_gradient, "raw_correction": final_metrics, "rank": confirmation_rank,
                     **({"confirmation_refresh": confirmation_refresh} if confirmation_refresh is not None else {}),
                     **({"floor_measurement": floor_measurement} if floor_measurement is not None else {})})
                return {"status": "complete", "converged": True, "result": result,
                        "accepted_iterations": accepted_count, "trial_evaluations": trials,
                        "objective_floor": floor, "history": history,
                        "confirmation_checks": confirmation_checks, "elapsed_seconds": clock()-start}
            if accepted_count >= controls.maximum_accepted_iterations or trials >= controls.maximum_trial_evaluations:
                raise NumericalFailure("iteration_limit", "Undamped convergence not reached within the frozen budget")
            step, prediction, _ = proposal(point, damping)
            if accepted_count != floor_iteration and (prediction <= 10*floor or small_correction(raw_metrics)):
                # An absolute floor measured at a poor initial orbit can be
                # much larger than the floor near the solution. Remeasure at
                # this accepted physical state before rejecting a small gain.
                repeated = check(model.evaluate(point.state, "repeat-floor"))
                refined = check(model.evaluate(point.state, "refine-floor", tighter=True))
                remaining()
                measured_floor = max(point.objective_floor, 10*abs(repeated.objective-point.objective),
                                     10*abs(refined.objective-point.objective))
                floor = max(measured_floor, 8*np.finfo(float).eps*abs(point.objective))
                floor_iteration = accepted_count
                floor_measurement = {"objective": point.objective,
                    "objective_repeat": repeated.objective, "objective_refined": refined.objective,
                    "physical_parameters_unchanged": True,
                    "objective_floor": floor}
                # The physical parameters are unchanged. Use their more
                # accurately closed trajectory and fresh undamped factor for
                # stationarity and subsequent proposals; retaining the old
                # factor can otherwise stall on its propagation roundoff.
                install(refined)
                continue
            candidate, metrics = model.trial(point, step)
            trials += 1
            record = {"trial": trials, "accepted_iteration": accepted_count,
                      "damping": damping, "objective_before": point.objective,
                      "predicted_reduction": prediction, "normalized_gradient": gradient,
                      "raw_correction": raw_metrics, "trial_correction": metrics, "rank": rank,
                      "nuisance_floor_limited_before": limited_profile(point),
                      "objective_floor": floor}
            if floor_measurement is not None:
                record["floor_measurement"] = floor_measurement
                floor_measurement = None
            if confirmation_refresh is not None:
                record["confirmation_refresh"] = confirmation_refresh
                confirmation_refresh = None
            if prediction <= 0 or not np.isfinite(prediction):
                actual, ratio, accepted = None, None, False
                record["reason"] = "nonpositive_prediction"
            else:
                try:
                    candidate_point = check(model.evaluate(candidate, f"trial-{trials:03d}"))
                    candidate_rank = certify_rank(candidate_point)
                except NumericalFailure as error:
                    # A failed candidate never installs an orbit or force cache.
                    # Support violations and execution budgets remain fatal;
                    # stronger damping can resolve a physically invalid trial.
                    if not isinstance(error, PhysicalTrialDomainFailure) and error.reason not in {
                            "closure_failed", "nuisance_failure", "invalid_objective",
                            "rank_deficient", "unresolved_rank"}:
                        raise
                    candidate_point = None
                    record.update(reason=error.reason, trial_error=str(error))
                    if isinstance(error, PhysicalTrialDomainFailure):
                        record["trial_domain_evidence"] = error.evidence
                remaining()
                if candidate_point is None:
                    actual, ratio, accepted = None, None, False
                else:
                    actual = point.objective - candidate_point.objective
                    ratio = actual / prediction
                    accepted = actual > 0 and ratio > controls.minimum_gain_ratio
                    profile_resolution = (point.objective_floor + candidate_point.objective_floor
                        if limited_profile(point) or limited_profile(candidate_point) else 0.)
                    record.update(objective_trial=candidate_point.objective, trial_rank=candidate_rank,
                        nuisance_floor_limited_trial=limited_profile(candidate_point),
                        nuisance_resolution_sum=profile_resolution,
                        objective_reduction_numerically_resolved=(abs(actual) > max(floor, candidate_point.objective_floor)))
                    if not accepted:
                        record["reason"] = "nonpositive_actual_reduction" if actual <= 0 else "insufficient_gain_ratio"
                    elif profile_resolution:
                        record["inexact_profile_forcing_ratio"] = INEXACT_PROFILE_FORCING_RATIO
                        record["gain_ratio_after_profile_resolution"] = (actual-profile_resolution)/prediction
                        if (profile_resolution > INEXACT_PROFILE_FORCING_RATIO*prediction
                                or (actual-profile_resolution)/prediction <= controls.minimum_gain_ratio):
                            accepted = False
                            record["reason"] = "unresolved_nuisance_profile_reduction"
            record.update(actual_reduction=actual, gain_ratio=ratio, accepted=accepted)
            if accepted:
                install(candidate_point)
                accepted_count += 1
                damping *= max(1/3, 1-(2*ratio-1)**3)
                multiplier = 2.
            else:
                damping *= multiplier
                multiplier *= 2
            log(record)
            if not np.isfinite(damping) or damping > 1e30:
                raise NumericalFailure("step_stalled", "No objective-checked step at the numerical floor")
    except NumericalFailure as error:
        return {"status": error.reason, "converged": False, "covariance_valid": False,
                "error": str(error), "accepted_iterations": accepted_count,
                "trial_evaluations": trials, "history": history,
                "confirmation_checks": confirmation_checks, "elapsed_seconds": clock()-start}
