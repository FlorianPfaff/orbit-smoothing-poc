"""Optional short-arc NUTS posterior check, with noncentered innovations."""
from __future__ import annotations

import numpy as np


def sample(problem, options):
    import jax
    import jax.numpy as jnp
    import numpyro
    import numpyro.distributions as dist
    from numpyro.diagnostics import summary
    from numpyro.infer import MCMC, NUTS, init_to_value
    from . import dynamics
    from .solvers import FitResult

    if problem.n > int(options.get("max_nodes", 256)):
        raise ValueError("NumPyro is a short-arc check: crop the dataset or explicitly increase max_nodes")
    prior = jnp.asarray(problem.prior)
    prior_sigma = jnp.asarray(problem.prior_sigma)
    chol = jnp.asarray(problem.chol)
    dt = jnp.asarray(problem.dt)
    nodes = jnp.asarray(problem.nodes)
    station_pos = jnp.asarray(problem.station_pos)
    station_vel = jnp.asarray(problem.station_vel)

    def model():
        initial_innovation = numpyro.sample("initial_innovation", dist.Normal(0, 1).expand([problem.d]).to_event(1))
        innovations = numpyro.sample("innovations", dist.Normal(0, 1).expand([problem.n - 1, problem.d]).to_event(2))
        first = prior + prior_sigma * initial_innovation

        def step(current, args):
            step_dt, step_chol, innovation = args
            nxt = dynamics.transition(current, step_dt, problem.spec) + step_chol @ innovation
            return nxt, nxt

        _, later = jax.lax.scan(step, first, (dt, chol, innovations))
        states = jnp.concatenate([first[None, :], later], axis=0)
        numpyro.deterministic("states", states)
        predicted = dynamics.batch_observe(states[nodes], station_pos, station_vel)
        numpyro.sample("observations", dist.Normal(predicted, jnp.asarray(problem.sigma)).to_event(2), obs=jnp.asarray(problem.y))

    start = np.asarray(options.get("initial_states", problem.reference * problem.scale)) / problem.scale
    predicted = np.asarray(dynamics.batch_transition(start[:-1], problem.dt, problem.spec))
    innovations = np.einsum("nij,nj->ni", problem.inverse_chol, start[1:] - predicted)
    kernel = NUTS(
        model, target_accept_prob=float(options.get("target_accept_prob", 0.9)),
        max_tree_depth=int(options.get("max_tree_depth", 9)),
        dense_mass=[("initial_innovation",)],
        init_strategy=init_to_value(values={
            "initial_innovation": (start[0] - problem.prior) / problem.prior_sigma,
            "innovations": innovations,
        }),
    )
    chains = int(options.get("num_chains", 4))
    warmup = int(options.get("num_warmup", 300))
    draws = int(options.get("num_samples", 300))
    sampler = MCMC(kernel, num_warmup=warmup, num_samples=draws, num_chains=chains,
                   chain_method=options.get("chain_method", "sequential"),
                   progress_bar=bool(options.get("progress_bar", False)))
    sampler.run(jax.random.PRNGKey(int(options.get("seed", 42))))
    samples = np.asarray(sampler.get_samples(group_by_chain=True)["states"])
    selected_nodes = np.arange(problem.n)
    diagnostics = summary({"states": samples}, group_by_chain=True)["states"]
    rhat = np.asarray(diagnostics["r_hat"])
    ess = np.asarray(diagnostics["n_eff"])
    finite_rhat = np.all(np.isfinite(rhat))
    finite_ess = np.all(np.isfinite(ess))
    max_rhat = float(np.max(rhat)) if finite_rhat else None
    min_ess = float(np.min(ess)) if finite_ess else None
    divergences = int(np.asarray(sampler.get_extra_fields()["diverging"]).sum())
    flattened = samples.reshape(-1, problem.n, problem.d)
    mean = flattened.mean(axis=0)
    centered = flattened - mean
    covariance = np.einsum("sni,snj->nij", centered, centered) / max(1, len(flattened) - 1)
    converged = bool(chains >= 4 and finite_rhat and finite_ess and max_rhat < 1.01 and min_ess >= 400 and divergences == 0)
    return FitResult(
        states=mean * problem.scale,
        covariance=covariance * problem.scale[None, :, None] * problem.scale[None, None, :],
        objective=problem.objective(mean), converged=converged, iterations=warmup + draws,
        elapsed_seconds=0.0,
        metadata={"solver": "numpyro", "estimate": "posterior mean", "num_chains": chains,
                  "num_warmup": warmup, "num_samples": draws, "max_rhat": max_rhat,
                  "min_ess": min_ess, "divergences": divergences,
                  "diagnostic_nodes": selected_nodes.tolist(),
                  "fixed_process_covariance": True,
                  "mass_matrix": "dense initial-state block; diagonal process innovations",
                  "posterior": "common discrete Gaussian transition approximation",
                  "objective_convention": "MAP objective evaluated at posterior mean; fixed constants omitted",
                  "diagnostics_passed": converged,
                  "diagnostic_status": "passed" if converged else "inconclusive"},
    )
