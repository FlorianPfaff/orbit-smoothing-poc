#!/usr/bin/env python3
"""Check full nonzero priors and a profiled native objective directional derivative.

Use a small blind synthetic engineering request. This executes actual GROOPS
propagation/nuisance fits and does not count as a frozen benchmark attempt.
"""
import argparse
import csv
import gzip
from dataclasses import replace
from pathlib import Path
import traceback

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, source_snapshot, write_json
from orbit_poc.numerics.backend import NativeModel
from orbit_poc.numerics.optimizer import certify_rank, proposal


def profile_evidence(point, label):
    """Keep numerical profiling qualifications alongside every objective value."""
    receipt = read_json(Path(point.metadata["folder"]) / "qr.profile.json")
    return {"label": label, "objective": point.objective,
            "nuisance_converged": receipt["nuisance_converged"],
            "nuisance_floor_limited": point.metadata.get("nuisance_floor_limited", False),
            "empirical_objective_resolution": point.objective_floor,
            "nuisance_predicted_reduction": receipt["nuisance_predicted_reduction"],
            "receipt": str(Path(point.metadata["folder"]) / "qr.profile.json")}


def prior_check(point, model):
    path = Path(point.metadata["factor_prefix"] + ".rows.tsv")
    label = "constraint.logDensityOu" if model.density else "constraint.pulses"
    with (path.open() if path.exists() else gzip.open(str(path)+".gz", "rt")) as stream:
        rows = list(csv.DictReader(stream, delimiter="\t"))
    selected = [row for row in rows if row["source"] == label]
    if not selected:
        raise AssertionError(f"No native {label} rows found: {sorted({r['source'] for r in rows})}")
    actual = np.array([float(row["rhs"]) for row in selected])
    force = point.state.force
    parameters = model.job["parameters"]
    if model.density:
        # Match the force/prior's native knot epochs, including their finite
        # representation, rather than silently substituting nominal cadence.
        data = np.loadtxt(Path(point.metadata["folder"]) / "native/log_density.txt")
        dt = np.diff(data[:, 0])*86400.
        tau, sigma = parameters["tau_seconds"], parameters["sigma_log_density"]
        expected = -np.r_[force[0]/sigma,
            (force[1:]-np.exp(-dt/tau)*force[:-1])/(sigma*np.sqrt(-np.expm1(-2*dt/tau)))]
        tolerance = 2e-8  # MJD text/native Time reconstruction can differ by sub-microseconds.
    else:
        expected = -force/(parameters["sigma_velocity_m_s"]*1e6)
        tolerance = 1e-12
    if actual.shape != expected.shape:
        raise AssertionError(f"Full prior row count differs: {actual.shape} versus {expected.shape}")
    discrepancy = float(np.max(np.abs(actual-expected)))
    if discrepancy > tolerance:
        raise AssertionError(f"Native full-parameter prior mismatch {discrepancy} > {tolerance}")
    prior_cost = .5*float(expected@expected)
    if prior_cost <= 0 or point.objective < prior_cost:
        raise AssertionError("Actual objective must contain the nonzero full prior penalty")
    return {"rows": len(actual), "cost": prior_cost, "maximum_residual_difference": discrepancy,
            "absolute_tolerance": tolerance, "objective": point.objective, "source": label}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--initial-state-from", type=Path,
                        help="Optional six-component physical_initial.txt from a preserved blind engineering iterate; never benchmark initialization")
    args = parser.parse_args()
    request = read_json(args.request)
    if request["split"] != "engineering" or request["stage"] != "synthetic":
        raise ValueError("This gate requires a blind synthetic engineering fixture")
    if request["numerics_profile"] != "qr_lm_staged_jacobian":
        raise ValueError("This gate tests the complete synthetic derivative profile")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Choose a new output directory; previous checks are preserved")
    args.output.mkdir(parents=True, exist_ok=True)
    request["preparation_source_hash"] = request["source_hash"]
    snapshot = source_snapshot()
    request["source_hash"] = snapshot["sha256"]
    request["backend"]["groops_executable"] = str(args.native_binary.resolve())
    request["expected_native_binary_sha256"] = file_hash(args.native_binary)
    write_json(args.output / "request.json", request)
    write_json(args.output / "source.json", snapshot)
    receipt = {"schema_version": 1, "scope": "native synthetic correctness gate; no evaluation truth",
               "passed": False, "relative_derivative_tolerance": 1e-4,
               "profile_evaluations": [],
               "resolution_scope": "empirical arithmetic spread, not a rigorous error bound or nuisance convergence",
               "derivative_refinement_policy": {"maximum_scales": 9, "ratio": .5,
                    "required_consecutive_passing_scales": 2, "physical_repeat_allowance_multiplier": 10},
               "initialization_policy": ("preserved_blind_engineering_initial_state" if args.initial_state_from
                                         else "original_retained_observation_bootstrap"),
               "native_binary_sha256": request["expected_native_binary_sha256"],
               "source_hash": request["source_hash"]}
    try:
        model = NativeModel(request, args.output)
        initial = model.initial_state()
        if args.initial_state_from is not None:
            physical_initial = native.read_native_table(args.initial_state_from).ravel()
            if physical_initial.shape != (6,) or not np.isfinite(physical_initial).all():
                raise ValueError("A finite six-component physical initial state is required")
            receipt["state_input"] = artifact_record("blind_engineering_physical_initial", args.initial_state_from)
            initial = replace(initial, initial=physical_initial)
        amplitude = (.2*request["parameters"]["sigma_log_density"] if model.density else
                     .2e6*request["parameters"]["sigma_velocity_m_s"])
        force = amplitude*np.cos(.37*np.arange(len(initial.force)))
        point = model.evaluate(replace(initial, force=force), "nonzero-full-prior", tighter=True)
        receipt["profile_evaluations"].append(profile_evidence(point, "nonzero-full-prior"))
        receipt["rank"] = certify_rank(point)
        receipt["prior"] = prior_check(point, model)
        repeated = model.evaluate(point.state, "repeat", tighter=True)
        receipt["profile_evaluations"].append(profile_evidence(repeated, "repeat"))
        if point.support_hash != repeated.support_hash:
            raise AssertionError("Repeated fixed-parameter evaluation changed observation support")
        receipt["objective_repeat_difference"] = abs(point.objective-repeated.objective)
        physical_resolution = 10*receipt["objective_repeat_difference"]
        receipt["empirical_physical_objective_resolution"] = physical_resolution
        direction, _, _ = proposal(point)
        direction[~point.dynamic] = 0.
        _, size = model.trial(point, direction)
        if size["position_change_m"] <= 0:
            raise AssertionError("Nonzero physical objective direction required")
        direction *= .05/size["position_change_m"]
        receipt["initial_direction_scale"] = .05/size["position_change_m"]
        receipt["raw_direction_metrics"] = size
        derivative = -float(point.rhs @ (point.factor @ (direction/point.scales)))
        values = []
        receipt["directional_derivatives"] = values
        passing_streak = 0
        for exponent in range(receipt["derivative_refinement_policy"]["maximum_scales"]):
            scale = .5**exponent
            costs, resolutions, endpoint_checks = [], [], []
            for sign in (-1, 1):
                state, _ = model.trial(point, direction*(sign*scale))
                value = model.evaluate(state, f"direction-{scale}-{sign}", tighter=True)
                receipt["profile_evaluations"].append(profile_evidence(value, f"direction-{scale}-{sign}"))
                if value.support_hash != point.support_hash:
                    raise AssertionError("Directional perturbation changed observation support or weights")
                repeated_value = model.evaluate(value.state, f"direction-{scale}-{sign}-repeat", tighter=True)
                receipt["profile_evaluations"].append(profile_evidence(repeated_value, f"direction-{scale}-{sign}-repeat"))
                if repeated_value.support_hash != point.support_hash:
                    raise AssertionError("Repeated directional perturbation changed observation support or weights")
                repeat_difference = abs(value.objective-repeated_value.objective)
                endpoint_resolution = (max(physical_resolution, 10*repeat_difference)
                    + max(value.objective_floor, repeated_value.objective_floor))
                costs.append(value.objective)
                resolutions.append(endpoint_resolution)
                endpoint_checks.append({"sign": sign, "repeat_cost": repeated_value.objective,
                    "repeat_difference": repeat_difference, "empirical_resolution": endpoint_resolution})
            numerical = (costs[1]-costs[0])/(2*scale)
            denominator = max(abs(numerical), abs(derivative), 1e-12)
            relative = abs(numerical-derivative)/denominator
            resolution_fraction = sum(resolutions)/(2*scale*denominator)
            passed_scale = relative+resolution_fraction <= receipt["relative_derivative_tolerance"]
            values.append({"scale": scale, "negative_cost": costs[0], "positive_cost": costs[1],
                           "finite_difference": numerical, "native_derivative": derivative,
                           "relative_difference": relative,
                           "empirical_resolution_fraction": resolution_fraction,
                           "relative_difference_plus_resolution": relative+resolution_fraction,
                           "endpoint_resolution_checks": endpoint_checks,
                           "passes_unchanged_tolerance": passed_scale})
            passing_streak = passing_streak+1 if passed_scale else 0
            if passing_streak == 2:
                break
        if passing_streak != 2:
            raise AssertionError("Repropagated nuisance-profiled objective derivative did not pass two consecutive refinements")
        receipt["accepted_derivative_scales"] = [value["scale"] for value in values[-2:]]
        receipt["passed"] = True
    except Exception as error:
        receipt.update(error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
    write_json(args.output / "validation.json", receipt)
    print({key: receipt[key] for key in ("passed", "error") if key in receipt}, flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
