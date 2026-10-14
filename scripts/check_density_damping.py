#!/usr/bin/env python3
"""Replay a retained blind density request with adaptive numerical relaxation.

This engineering diagnostic keeps the native binary, observations, common
preparation and statistical hyperparameters identical. It never invokes any
evaluation interface or opens a reference orbit.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import file_hash, read_json, source_snapshot, write_json


def run(args):
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a fresh damping diagnostic directory")
    original = read_json(args.request)
    if original.get("method") != "groops_log_drag_ou":
        raise ValueError("A retained blind density fit request is required")
    if any(key in original for key in ("evaluation_inputs", "calibration_inputs", "truth", "reference_orbit")):
        raise ValueError("Evaluation data leaked into the retained request")
    prepared = backend._preparation(original)
    native = backend._binary(original)
    identity = file_hash(native)
    snapshot = source_snapshot()
    request = deepcopy(original)
    request["source_hash"] = snapshot["sha256"]
    request["expected_native_binary_sha256"] = identity
    request["backend"]["retain_native_diagnostics"] = True
    # Defaults are source-versioned numerical controls; do not reuse a pilot's
    # artificially small iteration limit when validating the new controller.
    request.pop("numerical_controls", None)
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / "request.json", request)
    result = backend.fit_job(request, root)
    write_json(root / "result.json", result)
    if source_snapshot()["sha256"] != snapshot["sha256"] or file_hash(native) != identity:
        raise ValueError("Diagnostic source or executable changed during execution")
    backend._preparation(original)  # Prove shared converted input hashes remain valid.
    iterations = read_json(root / "outer_iterations.json")
    evidence = {"status": "complete", "passed": bool(result.get("converged") and result.get("covariance_valid")),
        "scope": "Engineering optimizer diagnostic; no calibration or scientific evaluation",
        "source_fit_request_sha256": file_hash(args.request), "source_fit_source_hash": original.get("source_hash"),
        "diagnostic_source_snapshot": snapshot, "native_binary_sha256": identity,
        "result_sha256": file_hash(root / "result.json"), "parameters": request["parameters"],
        "initialization": prepared.get("nominal_initialization"),
        "shared_input_hashes_unchanged": True, "preprocessing_audit_sha256":result.get("preprocessing_audit_sha256"),
        "controls": iterations["controls"], "iterations": iterations["iterations"],
        "converged": result.get("converged"), "covariance_valid": result.get("covariance_valid"),
        "error": result.get("error"), "elapsed_seconds": result.get("elapsed_seconds"),
        "peak_rss_bytes": result.get("peak_rss_bytes")}
    write_json(root / "density_damping.json", evidence)
    print(json.dumps({key:evidence[key] for key in ("passed", "converged", "covariance_valid", "error", "elapsed_seconds")}), flush=True)
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    raise SystemExit(run(parser.parse_args()))
