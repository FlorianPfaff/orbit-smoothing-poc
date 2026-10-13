"""Read-only timing of the actual short-arc noncentered posterior gradient.

Run separately with JAX_PLATFORMS=cpu or cuda. This scratch profiler does not
alter estimator source, data, references, fit artifacts, or the posterior.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job", type=Path, required=True)
    parser.add_argument("--cpu-cores", type=int, default=0)
    parser.add_argument("--evaluations", type=int, default=5)
    args = parser.parse_args()
    if args.cpu_cores:
        allowed = sorted(os.sched_getaffinity(0))
        os.sched_setaffinity(0, allowed[: args.cpu_cores])

    import numpy as np
    import jax
    import jax.numpy as jnp
    from orbit_poc import dynamics
    from orbit_poc.config import ModelSpec, config_hash
    from orbit_poc.data import load_dataset
    from orbit_poc.solvers import _Problem

    setup_start = perf_counter()
    job = json.loads(args.job.read_text())
    fit_record = json.loads((args.job.parent / "fit.json").read_text())
    request = fit_record["request"]
    reference_hash = config_hash(
        {"dataset": request["dataset_sha256"], "model": job["parameters"],
         "options": job["options"], "source": request["source_sha256"]}
    )
    dataset_path = Path(job["dataset"])
    reference_path = dataset_path.parent / f"reference-{reference_hash[:16]}.npy"
    reference = np.load(reference_path, allow_pickle=False)
    dataset = load_dataset(dataset_path)
    spec = ModelSpec(**job["parameters"])
    problem = _Problem(dataset, spec, reference)
    prior, prior_sigma = jnp.asarray(problem.prior), jnp.asarray(problem.prior_sigma)
    dt, chol = jnp.asarray(problem.dt), jnp.asarray(problem.chol)
    nodes = jnp.asarray(problem.nodes)
    station_pos, station_vel = jnp.asarray(problem.station_pos), jnp.asarray(problem.station_vel)
    observations, sigma = jnp.asarray(problem.y), jnp.asarray(problem.sigma)

    def states_from_flat(flat):
        innovation = flat.reshape(problem.n, problem.d)
        first = prior + prior_sigma * innovation[0]

        def step(current, inputs):
            step_dt, step_chol, increment = inputs
            nxt = dynamics.transition(current, step_dt, problem.spec) + step_chol @ increment
            return nxt, nxt

        _, tail = jax.lax.scan(step, first, (dt, chol, innovation[1:]))
        return jnp.concatenate((first[None, :], tail), axis=0)

    def negative_log_posterior(flat):
        states = states_from_flat(flat)
        prediction = dynamics.batch_observe(states[nodes], station_pos, station_vel)
        residual = (prediction - observations) / sigma
        # Constants are fixed; this is exactly the NumPyro posterior potential
        # in its initial and process innovation coordinates, up to a constant.
        return 0.5 * (jnp.vdot(flat, flat) + jnp.vdot(residual, residual))

    predicted = np.asarray(dynamics.batch_transition(reference[:-1], problem.dt, spec))
    process_innovation = np.einsum("nij,nj->ni", problem.inverse_chol, reference[1:] - predicted)
    initial_innovation = (reference[0] - problem.prior) / problem.prior_sigma
    flat = jnp.asarray(np.concatenate((initial_innovation[None, :], process_innovation)).ravel())
    jax.block_until_ready(flat)
    setup_seconds = perf_counter() - setup_start
    value_and_gradient = jax.jit(jax.value_and_grad(negative_log_posterior))
    started = perf_counter()
    compiled = value_and_gradient.lower(flat).compile()
    compile_seconds = perf_counter() - started
    started = perf_counter()
    result = compiled(flat)
    jax.block_until_ready(result)
    warmup_seconds = perf_counter() - started
    timings = []
    for _ in range(args.evaluations):
        started = perf_counter()
        result = compiled(flat)
        jax.block_until_ready(result)
        timings.append(perf_counter() - started)
    value, gradient = result
    result = {
        "platform": jax.default_backend(), "devices": [str(d) for d in jax.devices()],
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "dataset": str(dataset_path), "reference": str(reference_path),
        "source_sha256": request["source_sha256"], "parameters": spec.to_dict(),
        "duration_seconds": float(dataset.times[-1] - dataset.times[0]),
        "nodes": problem.n, "dimension": problem.d,
        "observations": len(problem.nodes), "innovation_parameters": int(flat.size),
        "setup_seconds": setup_seconds, "compile_seconds": compile_seconds,
        "warmup_execution_seconds": warmup_seconds, "gradient_evaluation_seconds": timings,
        "median_gradient_seconds": float(np.median(timings)),
        "value": float(value), "gradient_l2_norm": float(jnp.linalg.norm(gradient)),
        "finite_gradient": bool(jnp.all(jnp.isfinite(gradient))),
        "jax_version": jax.__version__, "jax_x64_enabled": bool(jax.config.jax_enable_x64),
    }
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
