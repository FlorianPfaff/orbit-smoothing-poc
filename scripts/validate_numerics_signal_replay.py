#!/usr/bin/env python3
"""Replay saved coarse/fine native signals without rerunning closed trajectories.

This checks the default measurement arithmetic after a control-only change or
addition of inactive diagnostic branches. It does not validate those branches,
optimizer convergence, or covariance. Run under the readonly input mirror.
"""
import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.protocol import file_hash, write_json
from validate_numerics_derivative_replay import COMPONENTS
from validate_numerics_flight_derivatives import PropagationDiagnostic


def check(binary, reference_manifest, candidate_manifest, references, output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    if "ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE" in os.environ:
        raise ValueError("Default signal replay requires the arithmetic audit environment to be absent")
    before = json.loads(Path(reference_manifest).read_text())
    after = json.loads(Path(candidate_manifest).read_text())
    if file_hash(binary) != after["executable_sha256"]:
        raise ValueError("Candidate executable differs from its build manifest")
    build_fields = ("upstream_commit", "compiler", "cmake_cache_sha256", "mpi")
    if any(before[key] != after[key] for key in build_fields):
        raise ValueError("Candidate changes the pinned upstream or build configuration")
    components = (*COMPONENTS, "orbitPocPredictSignals.cpp")
    identity = {}
    for name in components:
        old = before["extension"]["files"][name]
        new = after["extension"]["files"][name]
        if old != new:
            raise ValueError(f"Forward/tangent/exporter component changed: {name}")
        identity[name] = new
    result = {
        "schema": "orbit-poc-default-signal-replay-v1", "status": "running",
        "reference_executable_sha256": before["executable_sha256"],
        "candidate_executable_sha256": after["executable_sha256"],
        "reference_build_manifest_sha256": file_hash(reference_manifest),
        "candidate_build_manifest_sha256": file_hash(candidate_manifest),
        "diagnostic_source_sha256": file_hash(__file__),
        "unchanged_build_fields": list(build_fields),
        "unchanged_forward_tangent_exporter_components": identity,
        "changed_patched_source_files": [name for name in sorted(set(before["patched_source"]["files"]) | set(after["patched_source"]["files"]))
            if before["patched_source"]["files"].get(name) != after["patched_source"]["files"].get(name)],
        "arithmetic_audit_mode": None,
        "scope": "Exact default native prediction replay on saved closed coarse/fine trajectories; no new propagation, nuisance fitting, final covariance, or benchmark timing claim",
        "cases": [],
    }
    write_json(root / "result.json", result)
    model = PropagationDiagnostic(binary, root)
    try:
        for index, reference in enumerate(references):
            reference = Path(reference).resolve()
            receipt_path = reference / "result.json"
            receipt = json.loads(receipt_path.read_text())
            if receipt.get("status") != "complete" or receipt.get("passed") is not True or receipt["binary_sha256"] != before["executable_sha256"]:
                raise ValueError("Saved refinement lacks a passing reference-binary receipt")
            for resolution in ("coarse", "fine"):
                source = reference / resolution / "predictions"
                target = root / f"case-{index:02d}" / resolution
                target.mkdir(parents=True)
                config_path = source / "predict_signals.xml"
                tree = ET.parse(config_path).getroot()
                programs = tree.findall("program")
                if len(programs) != 1 or len(programs[0]) != 1 or programs[0][0].tag != "OrbitPocPredictSignals":
                    raise ValueError("Replay only accepts the saved native signal-export program")
                input_hashes = {node.text: file_hash(node.text) for node in tree.iter()
                    if node.tag.startswith("inputfile") and node.text and Path(node.text).is_file()}
                outputs = {}
                for node in tree.iter():
                    if node.tag.startswith("outputfile") and node.text:
                        if node.tag in outputs:
                            raise ValueError("Ambiguous repeated native output destination")
                        outputs[node.tag] = target / (node.tag + ".txt")
                        node.text = str(outputs[node.tag])
                if not {"outputfilePredictions", "outputfileSupport"} <= outputs.keys():
                    raise ValueError("Signal replay lacks explicit prediction/support outputs")
                environment = {"ORBIT_POC_NUMERICS_QR_PREFIX": str(target / "interpolation-audit"),
                               "ORBIT_POC_NUMERICS_SOLVER": "scaled_qr_v1"}
                actual = model.execute(tree, target, "predict_signals", environment)
                old_signal, new_signal = source / "signals.txt", outputs["outputfilePredictions"]
                old_support, new_support = source / "signal_support.txt", outputs["outputfileSupport"]
                a, b = native.read_native_table(old_signal, 8), native.read_native_table(new_signal, 8)
                numeric_equal = a.shape == b.shape and np.array_equal(a, b)
                support_equal = old_support.read_bytes() == new_support.read_bytes()
                item = {
                    "reference_directory": str(reference), "resolution": resolution,
                    "reference_receipt_sha256": file_hash(receipt_path),
                    "reference_config_sha256": file_hash(config_path), "actual_config_sha256": file_hash(actual),
                    "direct_input_file_sha256": input_hashes,
                    "reference_signal_sha256": file_hash(old_signal), "candidate_signal_sha256": file_hash(new_signal),
                    "reference_support_sha256": file_hash(old_support), "candidate_support_sha256": file_hash(new_support),
                    "rows": len(a), "columns": a.shape[1], "signals_numerically_identical": numeric_equal,
                    "signals_byte_identical": file_hash(old_signal) == file_hash(new_signal),
                    "support_byte_identical": support_equal,
                    "maximum_absolute_difference": float(np.max(np.abs(a-b))) if a.shape == b.shape else None,
                    "environment": environment, "passed": numeric_equal and support_equal,
                }
                result["cases"].append(item)
                write_json(root / "result.json", result)
        result.update(status="complete", passed=all(item["passed"] for item in result["cases"]),
                      native_executions=len(model.executions))
        write_json(root / "result.json", result)
        return result
    except Exception as error:
        result.update(status="failed", error=str(error), native_executions=len(model.executions))
        write_json(root / "result.json", result)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "reference-manifest", "candidate-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--reference", type=Path, action="append", required=True)
    args = parser.parse_args()
    result = check(args.binary, args.reference_manifest, args.candidate_manifest, args.reference, args.output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
