#!/usr/bin/env python3
"""Replay retained one-hour fits to check final-only covariance scheduling.

The baseline must contain successful native fits with covariance computed at
every outer iteration. This engineering comparison does not establish campaign
accuracy or a general speedup. Both fits use the same immutable native binary.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil

import numpy as np

from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, source_snapshot, write_json


def check_fit(fit_directory, output, binary):
    original = read_json(fit_directory / "result.json")
    job = read_json(fit_directory / "request.json")
    if not all(original.get(key) for key in ("converged", "covariance_valid")):
        raise ValueError("Baseline must be a converged fit with valid covariance")
    if original["native_binary_sha256"] != file_hash(binary):
        raise ValueError("Replay binary must match the baseline native SHA256")
    if float(job["case"]["duration_hours"]) != 1.:
        raise ValueError("This bounded diagnostic expects a one-hour retained fit")
    if (output / "result.json").exists():
        raise ValueError("Choose a fresh diagnostic output directory")
    old_runtime = read_json(backend._artifact(original, "native_runtime"))
    old_estimates = [entry for entry in old_runtime["execution"] if Path(entry["log"]).name == "estimate.log"]
    if not old_estimates or not all("=== compute covariance matrix" in Path(entry["log"]).read_text() for entry in old_estimates):
        raise ValueError("Baseline did not compute covariance at every native outer estimate")
    old_fit_path = backend._artifact(original, "state_estimate")
    job["backend"] = {**job["backend"], "groops_executable":str(binary), "retain_native_diagnostics":True}
    job["expected_native_binary_sha256"] = file_hash(binary)
    job["source_hash"] = source_snapshot()["sha256"]
    write_json(output / "request.json", job)
    result = backend.fit_job(job, output)
    write_json(output / "result.json", result)
    if not all(result.get(key) for key in ("converged", "covariance_valid")):
        raise RuntimeError(f"Deferred-covariance fit failed: {result.get('error')}")
    differences = {}
    with np.load(old_fit_path) as before, np.load(backend._artifact(result, "state_estimate")) as after:
        if set(before.files) != set(after.files):
            raise ValueError("Final state-estimate archive schema changed")
        for key in before.files:
            differences[key] = {"array_equal":bool(np.array_equal(before[key], after[key])),
                "maximum_absolute_difference":float(np.max(np.abs(before[key]-after[key]), initial=0.))}
    bytes_equal = {}
    for role in ("orbit_covariance", "observation_epoch_covariance", "native_parameter_covariance",
                 "native_parameters", "estimated_orbit_native"):
        bytes_equal[role] = file_hash(backend._artifact(original, role)) == file_hash(backend._artifact(result, role))
    old_history = old_runtime["outer_iterations"]
    history = read_json(output / "outer_iterations.json")["iterations"]
    same_progress = len(old_history) == len(history) and all(
        all(old.get(key) == new.get(key) for key in ("maximum_orbit_change_m", "maximum_log_density_update"))
        for old, new in zip(old_history, history))
    computed = [entry["covariance_computed"] for entry in history]
    passed = all(entry["array_equal"] for entry in differences.values()) and all(bytes_equal.values()) and same_progress
    passed = passed and computed == [False]*(len(history)-1)+[True]
    record = {"passed":passed, "method":job["method"], "case":job["case"],
        "baseline_result":artifact_record("baseline_result", fit_directory / "result.json"),
        "baseline_request":artifact_record("baseline_request", fit_directory / "request.json"),
        "replay_result":artifact_record("replay_result", output / "result.json"),
        "baseline_source_hash":read_json(fit_directory / "request.json")["source_hash"],
        "replay_source_hash":job["source_hash"], "native_binary_sha256":file_hash(binary),
        "array_comparisons":differences, "native_output_bytes_equal":bytes_equal,
        "same_outer_update_progress":same_progress, "covariance_computed_per_iteration":computed,
        "baseline_elapsed_seconds":original["elapsed_seconds"], "replay_elapsed_seconds":result["elapsed_seconds"],
        "baseline_peak_rss_bytes":original["peak_rss_bytes"], "replay_peak_rss_bytes":result["peak_rss_bytes"],
        "memory_scope":"Final-confirmation native covariance memory requirement is unchanged",
        "scope":"Matched one-hour engineering replay; timing is unpaired across runs, not a campaign speedup estimate"}
    write_json(output / "comparison.json", record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groops", type=Path, required=True)
    parser.add_argument("--fit-directory", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    binary = root / "bin/groops"
    binary.parent.mkdir(exist_ok=True)
    if binary.exists():
        if file_hash(binary) != file_hash(args.groops): raise ValueError("Existing immutable binary differs")
    else:
        shutil.copy2(args.groops, binary)
        binary.chmod(binary.stat().st_mode | 0o111)
    snapshot = source_snapshot()
    write_json(root / "source_snapshot.json", snapshot)
    records = []
    for i, directory in enumerate(args.fit_directory):
        record = check_fit(directory.resolve(), root / f"fit-{i:02d}", binary)
        records.append(record)
        print(directory.name, record["case"]["coverage"], "passed" if record["passed"] else "FAILED", flush=True)
        write_json(root / "summary.json", {"passed":all(r["passed"] for r in records),
            "complete":len(records) == len(args.fit_directory), "records":records,
            "source_snapshot":snapshot, "scientific_comparison_complete":False})
    if not all(record["passed"] for record in records):
        raise RuntimeError("Deferred covariance changed one or more matched outputs")


if __name__ == "__main__":
    main()
