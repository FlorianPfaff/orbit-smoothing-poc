"""Batch orbit inference with common factors and independent sparse solvers.

All solver internals use the normalized coordinates defined by ``dynamics.scales``.
Returned states/covariances use SI units. Process covariances are computed once on
the supplied reference and held fixed: the least-squares objective is therefore
the same posterior (up to a constant) for GTSAM, IEKS, and NumPyro.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any

import numpy as np
from scipy.linalg import cho_factor, cho_solve
from scipy.optimize import least_squares


@dataclass
class FitResult:
    states: np.ndarray
    covariance: np.ndarray
    objective: float
    converged: bool
    iterations: int
    elapsed_seconds: float
    metadata: dict[str, Any] = field(default_factory=dict)


def _factor_chain(diagonal, upper):
    diagonal = np.asarray(diagonal, dtype=float)
    upper = np.asarray(upper, dtype=float)
    if diagonal.ndim != 3 or diagonal.shape[1] != diagonal.shape[2]:
        raise ValueError("diagonal must have shape (N,D,D)")
    n, d, _ = diagonal.shape
    if n == 0 or upper.shape != (n - 1, d, d):
        raise ValueError("upper must have shape (N-1,D,D), with N >= 1")
    factors, transfer = [], []
    schur = diagonal[0].copy()
    factors.append(cho_factor((schur + schur.T) / 2, lower=True))
    for i in range(n - 1):
        # transfer = S_i^{-1} H_{i,i+1}; avoid explicit inversion.
        t = cho_solve(factors[i], upper[i])
        transfer.append(t)
        schur = diagonal[i + 1] - upper[i].T @ t
        factors.append(cho_factor((schur + schur.T) / 2, lower=True))
    return factors, transfer


def solve_block_tridiagonal(diagonal, upper, rhs):
    """Solve an SPD chain system using O(N D^3) time and O(N D^2) memory."""
    factors, transfer = _factor_chain(diagonal, upper)
    rhs = np.asarray(rhs, dtype=float)
    if rhs.shape[:2] != np.asarray(diagonal).shape[:2]:
        raise ValueError("rhs must start with dimensions (N,D)")
    forward = rhs.copy()
    for i, t in enumerate(transfer):
        forward[i + 1] -= t.T @ forward[i]
    result = np.empty_like(forward)
    result[-1] = cho_solve(factors[-1], forward[-1])
    for i in range(len(factors) - 2, -1, -1):
        result[i] = cho_solve(factors[i], forward[i]) - transfer[i] @ result[i + 1]
    return result


def marginal_covariances(diagonal, upper):
    """Recover only the diagonal blocks of a chain's inverse information."""
    factors, transfer = _factor_chain(diagonal, upper)
    n, d, _ = np.asarray(diagonal).shape
    covariance = np.empty((n, d, d))
    identity = np.eye(d)
    covariance[-1] = cho_solve(factors[-1], identity)
    for i in range(n - 2, -1, -1):
        covariance[i] = (
            cho_solve(factors[i], identity)
            + transfer[i] @ covariance[i + 1] @ transfer[i].T
        )
    return (covariance + covariance.transpose(0, 2, 1)) / 2


def schur_prefix(diagonal, upper, rhs, keep_from):
    """Eliminate a prefix, retaining its exact Gaussian separator message.

    Returns the reduced diagonal, upper blocks, and information vector. This is
    exact for the supplied linearized Gaussian system, not a claim about exact
    marginalization of the original nonlinear posterior.
    """
    a, e, b = (np.array(v, dtype=float, copy=True) for v in (diagonal, upper, rhs))
    if not 0 <= keep_from < len(a):
        raise ValueError("keep_from must retain at least one state")
    for i in range(keep_from):
        c = cho_factor((a[i] + a[i].T) / 2, lower=True)
        a[i + 1] -= e[i].T @ cho_solve(c, e[i])
        b[i + 1] -= e[i].T @ cho_solve(c, b[i])
    return a[keep_from:], e[keep_from:], b[keep_from:]


def _dynamics():
    from . import dynamics
    return dynamics


def _prior(dataset, spec):
    scale = np.asarray(_dynamics().scales(spec), dtype=float)
    mean = np.zeros(len(scale))
    sigma = np.ones(len(scale))
    mean[:6] = np.asarray(dataset.prior_mean) / scale[:6]
    sigma[:6] = np.asarray(dataset.prior_sigma) / scale[:6]
    if spec.model == "colored":
        sigma[6:] = float(spec.accel_sigma) / scale[6:]
    elif len(scale) > 6:
        sigma[6:] = float(spec.sigma) / scale[6:]
    if np.any(sigma <= 0):
        raise ValueError("All prior standard deviations must be positive")
    return mean, sigma, scale


def _validate(dataset):
    times = np.asarray(dataset.times, dtype=float)
    obs = dataset.observations
    nodes = np.asarray(obs["node"], dtype=int)
    if times.ndim != 1 or len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("Dataset times must contain at least two increasing epochs")
    if np.any(nodes < 0) or np.any(nodes >= len(times)):
        raise ValueError("Observation node is outside the trajectory")
    if np.asarray(obs["y"]).shape != (len(nodes), 2):
        raise ValueError("Observations must have shape (M,2)")
    if np.any(np.asarray(obs["sigma"]) <= 0):
        raise ValueError("Measurement standard deviations must be positive")
    return times, nodes


def _rollout_function(times, spec):
    import jax
    import jax.numpy as jnp
    dynamics = _dynamics()
    dt = jnp.asarray(np.diff(times))

    @jax.jit
    def rollout(z0):
        def step(z, step_dt):
            nxt = dynamics.transition(z, step_dt, spec)
            return nxt, nxt
        _, later = jax.lax.scan(step, z0, dt)
        return jnp.concatenate((z0[None, :], later), axis=0)
    return rollout


def _deterministic(dataset, spec, options=None):
    """Batch fit of initial Cartesian state and one constant log-drag scale."""
    options = options or {}
    started = perf_counter()
    times, nodes = _validate(dataset)
    dynamics = _dynamics()
    # Infinite OU time makes the seventh state's drift exactly zero. No process
    # covariance is requested for this deterministic baseline.
    baseline_spec = replace(spec, model="density", tau=float("inf"),
                            sigma=float(options.get("baseline_drag_sigma", 1.0)))
    prior, prior_sigma, scale = _prior(dataset, baseline_spec)
    observations = dataset.observations
    y = np.asarray(observations["y"])
    sigma = np.broadcast_to(np.asarray(observations["sigma"]), y.shape)
    station_pos = np.asarray(observations["station_pos"])
    station_vel = np.asarray(observations["station_vel"])
    rollout = _rollout_function(times, baseline_spec)
    cached = {}

    def evaluate(initial):
        if "initial" in cached and np.array_equal(initial, cached["initial"]):
            return cached["residual"], cached["jacobian"]
        trajectory = np.asarray(rollout(initial))
        fs = np.asarray(dynamics.batch_transition_jacobian(trajectory[:-1], np.diff(times), baseline_spec))
        sensitivity = np.empty((len(times), len(scale), len(scale)))
        sensitivity[0] = np.eye(len(scale))
        for k in range(len(times) - 1):
            sensitivity[k + 1] = fs[k] @ sensitivity[k]
        prediction = np.asarray(dynamics.batch_observe(trajectory[nodes], station_pos, station_vel))
        hs = np.asarray(dynamics.batch_observe_jacobian(trajectory[nodes], station_pos, station_vel))
        measurement_jacobian = np.einsum("mij,mjk->mik", hs, sensitivity[nodes]) / sigma[:, :, None]
        residual = np.concatenate(((initial - prior) / prior_sigma, ((prediction - y) / sigma).ravel()))
        jacobian = np.concatenate((np.diag(1 / prior_sigma), measurement_jacobian.reshape(-1, len(scale))))
        cached.update(initial=initial.copy(), residual=residual, jacobian=jacobian,
                      trajectory=trajectory, sensitivity=sensitivity)
        return residual, jacobian

    tolerance = float(options.get("tolerance", 1e-9))
    optimized = least_squares(
        lambda p: evaluate(p)[0], prior, jac=lambda p: evaluate(p)[1],
        max_nfev=int(options.get("max_nfev", 60)), x_scale="jac",
        ftol=tolerance, xtol=tolerance, gtol=tolerance,
    )
    evaluate(optimized.x)
    initial_covariance = np.linalg.inv(optimized.jac.T @ optimized.jac)
    sensitivity = cached["sensitivity"]
    covariance = np.einsum("nik,kl,njl->nij", sensitivity, initial_covariance, sensitivity)
    return FitResult(
        states=cached["trajectory"] * scale,
        covariance=covariance * scale[None, :, None] * scale[None, None, :],
        objective=float(optimized.cost), converged=bool(optimized.success),
        iterations=int(optimized.nfev), elapsed_seconds=perf_counter() - started,
        metadata={"solver": "deterministic", "message": optimized.message,
                  "latent_forces": "one fitted constant log-drag scale",
                  "constant_log_drag": float(optimized.x[6]),
                  "covariance": "local initial-state and constant-drag Laplace propagated through dynamics"},
    )


def initialize(dataset, spec, options=None):
    """Return a normalized, observation-fitted deterministic reference trajectory."""
    result = _deterministic(dataset, spec, options)
    scale = np.asarray(_dynamics().scales(spec))
    reference = np.zeros((len(dataset.times), len(scale)))
    reference[:, :6] = result.states[:, :6] / scale[:6]
    # Common fitted Cartesian reference; colored acceleration starts at zero.
    # Density's nominal trajectory carries the fitted constant log-drag value.
    if spec.model == "density":
        reference[:, 6] = result.states[:, 6]
    return reference


class _Problem:
    def __init__(self, dataset, spec, reference):
        self.dataset, self.spec = dataset, spec
        self.times, self.nodes = _validate(dataset)
        self.dt = np.diff(self.times)
        self.prior, self.prior_sigma, self.scale = _prior(dataset, spec)
        self.n, self.d = len(self.times), len(self.scale)
        self.reference = np.asarray(reference, dtype=float)
        if self.reference.shape != (self.n, self.d):
            raise ValueError(f"reference must have normalized shape {(self.n, self.d)}")
        covariance_start = perf_counter()
        self.q = np.asarray(_dynamics().process_covariances(self.reference, self.times, spec), dtype=float)
        self.process_covariance_seconds = perf_counter() - covariance_start
        if self.q.shape != (self.n - 1, self.d, self.d):
            raise ValueError("process_covariances returned an incompatible shape")
        self.q = (self.q + self.q.transpose(0, 2, 1)) / 2
        self.chol = np.linalg.cholesky(self.q)
        self.inverse_chol = np.linalg.solve(self.chol, np.broadcast_to(np.eye(self.d), self.chol.shape))
        obs = dataset.observations
        self.y = np.asarray(obs["y"])
        self.sigma = np.broadcast_to(np.asarray(obs["sigma"]), self.y.shape)
        self.station_pos = np.asarray(obs["station_pos"])
        self.station_vel = np.asarray(obs["station_vel"])

    def residuals(self, z):
        dynamics = _dynamics()
        predictions = np.asarray(dynamics.batch_transition(z[:-1], self.dt, self.spec))
        measurements = np.asarray(dynamics.batch_observe(z[self.nodes], self.station_pos, self.station_vel))
        prior = (z[0] - self.prior) / self.prior_sigma
        process = np.einsum("nij,nj->ni", self.inverse_chol, z[1:] - predictions)
        observation = (measurements - self.y) / self.sigma
        return prior, process, observation

    def objective(self, z):
        return float(sum(np.sum(r * r) for r in self.residuals(z)) / 2)

    def linearize(self, z):
        dynamics = _dynamics()
        r_prior, r_process, r_obs = self.residuals(z)
        transition_jac = np.asarray(dynamics.batch_transition_jacobian(z[:-1], self.dt, self.spec))
        h = np.asarray(dynamics.batch_observe_jacobian(z[self.nodes], self.station_pos, self.station_vel))
        h = h / self.sigma[:, :, None]
        a = -np.einsum("nij,njk->nik", self.inverse_chol, transition_jac)
        b = self.inverse_chol
        p = np.diag(1 / self.prior_sigma)
        diagonal = np.zeros((self.n, self.d, self.d))
        gradient = np.zeros((self.n, self.d))
        diagonal[0] += p.T @ p
        gradient[0] += p.T @ r_prior
        diagonal[:-1] += np.einsum("nji,njk->nik", a, a)
        diagonal[1:] += np.einsum("nji,njk->nik", b, b)
        upper = np.einsum("nji,njk->nik", a, b)
        gradient[:-1] += np.einsum("nji,nj->ni", a, r_process)
        gradient[1:] += np.einsum("nji,nj->ni", b, r_process)
        np.add.at(diagonal, self.nodes, np.einsum("mji,mjk->mik", h, h))
        np.add.at(gradient, self.nodes, np.einsum("mji,mj->mi", h, r_obs))
        cost = float((np.sum(r_prior**2) + np.sum(r_process**2) + np.sum(r_obs**2)) / 2)
        return dict(diagonal=diagonal, upper=upper, gradient=gradient, cost=cost,
                    transition_jacobian=transition_jac, z=z,
                    p=p, a=a, b=b, h=h, r_prior=r_prior, r_process=r_process, r_obs=r_obs)


def _gtsam_graph(problem, linear, damping_diagonal=None, column_scale=None):
    try:
        import gtsam
    except ImportError as exc:
        raise ImportError("The GTSAM solver requires the optional gtsam package") from exc
    graph = gtsam.GaussianFactorGraph()
    if column_scale is None:
        column_scale = np.ones((problem.n, problem.d))
    unit = gtsam.noiseModel.Unit.Create(problem.d)
    graph.add(gtsam.JacobianFactor(0, linear["p"] * column_scale[0], -linear["r_prior"], unit))
    for k in range(problem.n - 1):
        graph.add(gtsam.JacobianFactor(k, linear["a"][k] * column_scale[k], k + 1, linear["b"][k] * column_scale[k+1], -linear["r_process"][k], unit))
    obs_unit = gtsam.noiseModel.Unit.Create(2)
    for m, k in enumerate(problem.nodes):
        graph.add(gtsam.JacobianFactor(int(k), linear["h"][m] * column_scale[k], -linear["r_obs"][m], obs_unit))
    if damping_diagonal is not None and np.any(damping_diagonal > 0):
        for k in range(problem.n):
            graph.add(gtsam.JacobianFactor(k, np.diag(np.sqrt(damping_diagonal[k]) * column_scale[k]), np.zeros(problem.d), unit))
    return graph


def _gtsam_step(problem, linear, damping_diagonal):
    import gtsam
    assembly_start = perf_counter()
    columns = 1 / np.sqrt(np.maximum(np.diagonal(linear["diagonal"], axis1=1, axis2=2), 1e-300))
    graph = _gtsam_graph(problem, linear, damping_diagonal, columns)
    linear["assembly_seconds"] = perf_counter() - assembly_start
    # Explicit chronological order keeps this chain sparse and reproducible.
    ordering = gtsam.Ordering()
    for k in range(problem.n):
        ordering.push_back(k)
    solve_start = perf_counter()
    solution = graph.optimize(ordering)
    linear["solve_seconds"] = perf_counter() - solve_start
    return np.stack([solution.at(k) for k in range(problem.n)]) * columns


def _ieks_step(problem, linear, damping_diagonal, return_covariance=False):
    """Actual linearized Kalman forward pass and Rauch--Tung--Striebel pass.

    The filtered variable is the perturbation delta about the current full
    trajectory. Dynamics are delta[k+1] = F[k] delta[k] - e[k] + noise.
    LM damping is a zero-mean pseudo-observation of delta at every epoch.
    """
    n, d = problem.n, problem.d
    identity = np.eye(d)
    predicted_mean = np.empty((n, d))
    predicted_cov = np.empty((n, d, d))
    filtered_mean = np.empty((n, d))
    filtered_cov = np.empty((n, d, d))
    predicted_mean[0] = problem.prior - linear["z"][0]
    predicted_cov[0] = np.diag(problem.prior_sigma**2)
    physical_residual = np.einsum("nij,nj->ni", problem.chol, linear["r_process"])
    grouped = [[] for _ in range(n)]
    for m, k in enumerate(problem.nodes):
        grouped[int(k)].append(m)
    for k in range(n):
        p = predicted_cov[k]
        mean = predicted_mean[k]
        # Information update only within this small state block; the temporal
        # recursion itself remains covariance-form filtering/RTS smoothing.
        precision = cho_solve(cho_factor((p + p.T) / 2, lower=True), identity)
        information = precision @ mean
        precision += np.diag(damping_diagonal[k])
        for m in grouped[k]:
            h = linear["h"][m]
            precision += h.T @ h
            information -= h.T @ linear["r_obs"][m]
        factor = cho_factor((precision + precision.T) / 2, lower=True)
        filtered_cov[k] = cho_solve(factor, identity)
        filtered_mean[k] = cho_solve(factor, information)
        if k + 1 < n:
            f = linear["transition_jacobian"][k]
            predicted_mean[k + 1] = f @ filtered_mean[k] - physical_residual[k]
            predicted_cov[k + 1] = f @ filtered_cov[k] @ f.T + problem.q[k]
    smoothed = filtered_mean.copy()
    covariance = filtered_cov.copy() if return_covariance else None
    for k in range(n - 2, -1, -1):
        f = linear["transition_jacobian"][k]
        p = predicted_cov[k + 1]
        gain = cho_solve(cho_factor((p + p.T) / 2, lower=True), f @ filtered_cov[k]).T
        smoothed[k] += gain @ (smoothed[k + 1] - predicted_mean[k + 1])
        if return_covariance:
            covariance[k] += gain @ (covariance[k + 1] - predicted_cov[k + 1]) @ gain.T
    if return_covariance:
        covariance = (covariance + covariance.transpose(0, 2, 1)) / 2
        return smoothed, covariance
    return smoothed


def _convergence_gate(step_sigma_fraction, whitened_step_squared_norm, objective,
                      roundoff_squared_bound, step_sigma_tolerance=1e-3,
                      objective_tolerance=1e-8):
    """Require both marginal and joint smallness of an undamped update.

    Strong correlations can make a marginally tiny step significant in joint
    Mahalanobis distance. Half the squared linearized-factor step is the local
    Gauss--Newton predicted objective decrease. The additive floating-point
    bound accounts only for representational precision of the process residual,
    and does not change the separate solver-agreement acceptance thresholds.
    """
    decrement_limit = roundoff_squared_bound + 2 * objective_tolerance * max(1.0, abs(objective))
    passed = (np.isfinite(step_sigma_fraction) and np.isfinite(whitened_step_squared_norm)
              and step_sigma_fraction <= step_sigma_tolerance
              and whitened_step_squared_norm <= decrement_limit)
    return bool(passed), float(decrement_limit)


def _map(problem, solver, options):
    z = np.asarray(options.get("initial_states", problem.reference * problem.scale), dtype=float) / problem.scale
    if z.shape != problem.reference.shape:
        raise ValueError("initial_states must have shape (N,D), in SI units")
    max_iterations = int(options.get("max_iterations", 40))
    step_sigma_tolerance = float(options.get("step_sigma_tolerance", 1e-3))
    objective_tolerance = float(options.get("tolerance", 1e-8))
    damping = float(options.get("initial_damping", 0.0))
    history, accepted, converged = [], 0, False
    timings = {"linearization_seconds": 0.0, "assembly_seconds": 0.0, "solve_seconds": 0.0,
               "convergence_check_seconds": 0.0}
    step_sigma_fraction, step_norm_squared = None, None
    roundoff_squared_bound, decrement_limit = None, None
    last_reason = "maximum iterations"
    iteration = 0
    for iteration in range(1, max_iterations + 1):
        linear_start = perf_counter()
        linear = problem.linearize(z)
        timings["linearization_seconds"] += perf_counter() - linear_start
        diagonal_entries = np.maximum(np.diagonal(linear["diagonal"], axis1=1, axis2=2), 1e-12)
        successful = False
        for _ in range(12):
            damping_diagonal = damping * diagonal_entries
            try:
                if solver == "gtsam":
                    delta = _gtsam_step(problem, linear, damping_diagonal)
                    timings["assembly_seconds"] += linear["assembly_seconds"]
                    timings["solve_seconds"] += linear["solve_seconds"]
                else:
                    solve_start = perf_counter()
                    delta = _ieks_step(problem, linear, damping_diagonal)
                    timings["solve_seconds"] += perf_counter() - solve_start
                # Test an UNDAMPED step in whitened factor space. A tiny damped
                # update can merely reflect huge process precision, and is not
                # sufficient evidence of convergence. This norm is the local
                # Gauss--Newton decrement without ill-conditioned H products.
                if damping == 0:
                    step_norm_squared = np.sum((linear["p"] @ delta[0])**2)
                    process_change = np.einsum("nij,nj->ni", linear["a"], delta[:-1]) + np.einsum("nij,nj->ni", linear["b"], delta[1:])
                    observation_change = np.einsum("mij,mj->mi", linear["h"], delta[problem.nodes])
                    step_norm_squared += np.sum(process_change**2) + np.sum(observation_change**2)
                    convergence_start = perf_counter()
                    _, local_covariance = _ieks_step(problem, linear, np.zeros_like(z), return_covariance=True)
                    marginal_sigma = np.sqrt(np.maximum(np.diagonal(local_covariance, axis1=1, axis2=2), 1e-300))
                    step_sigma_fraction = float(np.max(np.abs(delta) / marginal_sigma))
                    timings["convergence_check_seconds"] += perf_counter() - convergence_start
                    # Bound representational subtraction uncertainty in the
                    # normalized process residual. |L^-1| propagates component
                    # error bounds without falsely assuming uncorrelated rows.
                    # This is a roundoff allowance, not a dynamics-error model.
                    residual_roundoff = np.finfo(float).eps * (np.abs(z[:-1]) + np.abs(z[1:]))
                    whitened_roundoff = np.einsum("nij,nj->ni", np.abs(problem.inverse_chol), residual_roundoff)
                    roundoff_squared_bound = float(np.sum(whitened_roundoff**2))
                    stop, decrement_limit = _convergence_gate(
                        step_sigma_fraction, step_norm_squared, linear["cost"],
                        roundoff_squared_bound, step_sigma_tolerance, objective_tolerance,
                    )
                    if stop:
                        converged, last_reason = True, "small undamped marginal step and joint decrement"
                        successful = True
                        break
                next_cost = problem.objective(z + delta)
            except (np.linalg.LinAlgError, RuntimeError) as exc:
                if isinstance(exc, RuntimeError) and "Indeterminant" not in str(exc):
                    raise
                damping = max(damping * 10, 1e-14)
                continue
            if np.isfinite(next_cost) and next_cost < linear["cost"]:
                z += delta
                accepted += 1
                history.append(next_cost)
                damping = damping / 3
                if damping <= 1e-14:
                    damping = 0.0
                successful = True
                break
            damping = max(damping * 10, 1e-14)
        if not successful:
            # A rejected step is not itself evidence of convergence.
            last_reason = "no decreasing LM step"
            break
        if converged:
            break
    linear_start = perf_counter()
    final = problem.linearize(z)
    timings["linearization_seconds"] += perf_counter() - linear_start
    # Covariance-form recursion is more stable than subtracting nearly equal
    # huge information blocks when physical process noise is very small.
    covariance_start = perf_counter()
    _, covariance = _ieks_step(problem, final, np.zeros((problem.n, problem.d)), return_covariance=True)
    timings["covariance_seconds"] = perf_counter() - covariance_start
    return FitResult(
        states=z * problem.scale,
        covariance=covariance * problem.scale[None, :, None] * problem.scale[None, None, :],
        objective=final["cost"], converged=converged, iterations=iteration,
        elapsed_seconds=0.0,
        metadata={"solver": solver, "termination": last_reason, "accepted_steps": accepted,
                  "objective_history": history, "fixed_process_covariance": True,
                  "covariance": "local Gaussian at MAP, LM damping excluded",
                  "linear_solver": "GTSAM Gaussian factor elimination" if solver == "gtsam" else "independent Kalman forward filter and RTS backward smoother",
                  "variable_equilibration": "per-node Jacobian column norms; exact invertible change of coordinates" if solver == "gtsam" else "common physical normalization",
                  "undamped_step_max_posterior_sigma": step_sigma_fraction,
                  "step_sigma_tolerance": step_sigma_tolerance,
                  "undamped_step_whitened_squared_norm": float(step_norm_squared) if step_norm_squared is not None else None,
                  "process_roundoff_squared_bound": roundoff_squared_bound,
                  "joint_decrement_squared_limit": decrement_limit,
                  "relative_objective_tolerance": objective_tolerance,
                  "timing": timings,
                  "objective_convention": "half squared whitened residual; fixed normalizing constants omitted"},
    )


def fit(dataset, spec, solver="gtsam", options=None, reference=None):
    """Fit a retrospective orbit; ``reference`` is normalized and freezes Q.

    Supported solvers: deterministic, gtsam, ieks, numpyro. The IEKS entry uses
    a Kalman forward filter and RTS backward recursion for each Gauss--Newton
    iteration, independently of GTSAM. It is algebraically the same chain
    smoother, with shared damping/line acceptance to permit a fair comparison.
    """
    options = options or {}
    if solver == "deterministic":
        return _deterministic(dataset, spec, options)
    if solver not in {"gtsam", "ieks", "numpyro"}:
        raise ValueError(f"Unknown solver: {solver}")
    started = perf_counter()
    if reference is None:
        reference = initialize(dataset, spec, options)
    initialization_seconds = perf_counter() - started
    setup_start = perf_counter()
    problem = _Problem(dataset, spec, reference)
    setup_seconds = perf_counter() - setup_start
    if solver == "numpyro":
        from .numpyro_backend import sample
        result = sample(problem, options)
    else:
        result = _map(problem, solver, options)
    result.elapsed_seconds = perf_counter() - started
    result.metadata.setdefault("timing", {}).update(
        initialization_seconds=initialization_seconds,
        problem_setup_seconds=setup_seconds,
        process_covariance_seconds=problem.process_covariance_seconds,
    )
    return result


def separator_check(dataset, spec, states=None, reference=None, boundary_indices=None):
    """Compare full orbital Gaussian solve to retained-boundary elimination.

    GTSAM partially eliminates every interior state, solves the reduced boundary
    graph, then back-substitutes through the saved Gaussian conditionals. The
    default retains the first/last nodes and boundaries every six hours. Results
    quantify finite-precision effects under different elimination orderings.
    No information is deliberately discarded and no full covariance is formed.
    """
    import gtsam
    if reference is None:
        reference = initialize(dataset, spec)
    problem = _Problem(dataset, spec, reference)
    z = np.asarray(states) / problem.scale if states is not None else problem.reference
    started = perf_counter()
    linear = problem.linearize(z)
    linear_seconds = perf_counter() - started
    started = perf_counter()
    columns = 1 / np.sqrt(np.maximum(np.diagonal(linear["diagonal"], axis1=1, axis2=2), 1e-300))
    graph = _gtsam_graph(problem, linear, column_scale=columns)
    assembly_seconds = perf_counter() - started
    if boundary_indices is None:
        elapsed = problem.times - problem.times[0]
        targets = np.arange(0.0, elapsed[-1], 21600.0)
        boundary_indices = [int(np.argmin(np.abs(elapsed-t))) for t in targets]
        boundary_indices += [0, problem.n-1]
    boundaries = sorted(set(int(k) for k in boundary_indices))
    if not boundaries or boundaries[0] < 0 or boundaries[-1] >= problem.n:
        raise ValueError("Boundary indices must be a nonempty subset of trajectory nodes")
    interior = sorted(set(range(problem.n)) - set(boundaries))
    full_order = gtsam.Ordering()
    for k in range(problem.n):
        full_order.push_back(k)
    started = perf_counter()
    full = graph.optimize(full_order)
    full_seconds = perf_counter() - started
    partial_order = gtsam.Ordering()
    for k in interior:
        partial_order.push_back(k)
    started = perf_counter()
    conditionals, reduced = graph.eliminatePartialSequential(partial_order)
    eliminate_seconds = perf_counter() - started
    boundary_order = gtsam.Ordering()
    for k in boundaries:
        boundary_order.push_back(k)
    started = perf_counter()
    boundary_solution = reduced.optimize(boundary_order)
    boundary_seconds = perf_counter() - started
    started = perf_counter()
    recovered = conditionals.optimize(boundary_solution)
    backsub_seconds = perf_counter() - started
    full_array = np.stack([full.at(k) for k in range(problem.n)])
    reduced_array = np.stack([boundary_solution.at(k) if k in boundaries else recovered.at(k) for k in range(problem.n)])
    difference = (reduced_array - full_array) * columns * problem.scale
    full_linear_cost = float(graph.error(full))
    # optimize(given) may return only solved frontal values in some bindings.
    merged = gtsam.VectorValues()
    for k in range(problem.n):
        merged.insert(k, reduced_array[k])
    reduced_linear_cost = float(graph.error(merged))
    return {
        "nodes": problem.n, "dimension": problem.d,
        "boundary_indices": boundaries, "interior_nodes": len(interior),
        "reduced_factors": int(reduced.size()),
        "max_position_difference_m": float(np.max(np.linalg.norm(difference[:, :3], axis=1))),
        "max_velocity_difference_m_s": float(np.max(np.linalg.norm(difference[:, 3:6], axis=1))),
        "max_latent_difference": float(np.max(np.abs(difference[:, 6:]))) if problem.d > 6 else 0.0,
        "relative_linear_objective_difference": abs(full_linear_cost-reduced_linear_cost)/max(1.0,abs(full_linear_cost)),
        "linearization_seconds": linear_seconds, "assembly_seconds": assembly_seconds,
        "full_solve_seconds": full_seconds, "partial_elimination_seconds": eliminate_seconds,
        "boundary_solve_seconds": boundary_seconds, "backsubstitution_seconds": backsub_seconds,
        "interpretation": "exact Gaussian separator construction at a frozen nonlinear linearization, subject to finite precision",
    }
