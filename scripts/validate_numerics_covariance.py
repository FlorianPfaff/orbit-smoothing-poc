#!/usr/bin/env python3
"""Check native covariance export against the original-row QR at a fixed orbit.

This is a blind engineering check. A successful check verifies file/coordinate
plumbing and nuisance marginalization, not convergence of a physical fit.
"""
import argparse
from pathlib import Path
import traceback

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, source_snapshot, write_json
from orbit_poc.numerics.backend import NativeModel, PhysicalState
from orbit_poc.numerics.optimizer import certify_rank, selected_covariance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--state-from", type=Path, required=True,
                        help="Completed blind engineering point containing physical_initial.txt and fixed_force.txt")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = read_json(args.request)
    if request.get("split") != "engineering":
        raise ValueError("This check requires a blind engineering request")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Choose a new directory; previous attempts are preserved")
    args.output.mkdir(parents=True, exist_ok=True)
    snapshot = source_snapshot()
    request["preparation_source_hash"] = request["source_hash"]
    request["source_hash"] = snapshot["sha256"]
    request["backend"]["groops_executable"] = str(args.native_binary.resolve())
    request["expected_native_binary_sha256"] = file_hash(args.native_binary)
    write_json(args.output / "request.json", request)
    write_json(args.output / "source.json", snapshot)
    receipt = {"schema_version": 1, "passed": False, "accepted_fit_covariance": False,
               "scope": "Fixed blind engineering orbit: export and marginalized covariance agreement only",
               "native_binary_sha256": request["expected_native_binary_sha256"],
               "relative_covariance_tolerance": 1e-8}
    try:
        model = NativeModel(request, args.output)
        initial = model.initial_state()
        initial_path = args.state_from / "physical_initial.txt"
        force_path = (args.state_from / "native/log_density.txt" if model.density else
                      args.state_from / "fixed_force.txt")
        force = (np.loadtxt(force_path)[:, 1] if model.density else
                 native.read_native_table(force_path).ravel()[:-6])
        receipt["state_inputs"] = [artifact_record("physical_initial", initial_path),
                                   artifact_record("full_force_parameters", force_path)]
        state = PhysicalState(native.read_native_table(initial_path).ravel(), force, initial.reference_orbit)
        if state.initial.shape != (6,) or state.force.shape != initial.force.shape:
            raise ValueError("Engineering state and request parameter dimensions differ")
        point = model.evaluate(state, "covariance-export", tighter=True, covariance=True)
        receipt["rank"] = certify_rank(point)
        outputs = point.metadata["config"]["result_paths"]
        count = int(point.dynamic.sum())
        selector = np.eye(len(point.scales))[point.dynamic]
        expected = selected_covariance(point, selector)
        actual = native.read_native_table(outputs["parameter_covariance"])
        if actual.shape != (count, count):
            raise AssertionError("Exported dynamic covariance has unexpected dimensions")
        parameter_error = float(np.linalg.norm(actual-expected)/np.linalg.norm(expected))
        design = native.read_native_table(point.metadata["design"])
        initial_covariance = selected_covariance(point, design @ selector)
        mjd, states = native._orbit(outputs["orbit"])
        orbital, invalid = native._covariance(outputs["covariance"], mjd)
        prediction_mjd = native.read_native_table(outputs["covariance_observations"], 37)[:, 0]
        predictions, invalid_predictions = native._covariance(outputs["covariance_observations"], prediction_mjd)
        initial_error = float(np.linalg.norm(orbital[0]-initial_covariance)/np.linalg.norm(initial_covariance))
        receipt.update(parameter_covariance_relative_error=parameter_error,
                       initial_cartesian_covariance_relative_error=initial_error,
                       orbital_epochs=len(mjd), prediction_epochs=len(prediction_mjd),
                       invalid_orbital_covariances=invalid, invalid_prediction_covariances=invalid_predictions,
                       objective=point.objective, nuisance_converged=True,
                       initial_export_difference_si=(states[0]-state.initial).tolist(),
                       parameter_covariance=artifact_record("native_dynamic_covariance", outputs["parameter_covariance"]))
        if invalid or invalid_predictions or max(parameter_error, initial_error) >= 1e-8:
            raise AssertionError("Native export disagrees with nuisance-marginalized undamped QR covariance")
        receipt["passed"] = True
    except Exception as error:
        receipt.update(error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc())
    write_json(args.output / "validation.json", receipt)
    print({key: receipt[key] for key in ("passed", "error") if key in receipt}, flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
