#!/usr/bin/env python3
"""Replay archived propagation checks on a candidate without overwriting evidence.

This validates the no-GNSS forward/derivative branch used by the archived flight
omission study. It does not attest to the QR-enabled measurement path; its signal
refinement must be rerun separately. Run under the verified readonly input mirror.
"""
from pathlib import Path
import argparse
import json
import os
import shutil
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.protocol import file_hash, write_json
from validate_numerics_flight_derivatives import PropagationDiagnostic


COMPONENTS = (
    "native_derivatives.py", "sixStateTangent.h", "stagedVariationalBody.h",
    "syntheticForceDerivatives.h", "finiteDifferenceForceJacobian.h",
    "orbitPocStateDerivatives.cpp", "orbitPocEvaluateVariational.cpp",
    "atmosphereEvents.h", "atmosphereExtraSamples.h", "atmosphereLocalEvents.h",
    "eventQuadrature.h", "integrationWindows.h", "logDensitySeries.h",
    "miscAccelerationsLogDensity.h", "miscAccelerationsSyntheticDrag.h",
    "miscAccelerationsSyntheticGravity.h", "piecewisePolynomial.h",
    "thermalIntegrationStep.h",
)


def check(binary, reference_manifest, candidate_manifest, long_arc, flight, output):
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=False)
    if os.environ.get("ORBIT_POC_NUMERICS_QR_PREFIX"):
        raise ValueError("The archived propagation studies did not enable the GNSS QR environment")
    original = json.loads(Path(reference_manifest).read_text())
    candidate = json.loads(Path(candidate_manifest).read_text())
    if file_hash(binary) != candidate["executable_sha256"]:
        raise ValueError("Candidate executable does not match its build manifest")
    same_build = ("upstream_commit", "compiler", "cmake_cache_sha256", "mpi")
    if any(original[key] != candidate[key] for key in same_build):
        raise ValueError("The candidate changed the compiler or upstream/build configuration")
    component_hashes = {}
    for name in COMPONENTS:
        before = original["extension"]["files"][name]
        after = candidate["extension"]["files"][name]
        if before != after:
            raise ValueError(f"Forward/derivative component changed: {name}")
        component_hashes[name] = after
    before_files, after_files = original["patched_source"]["files"], candidate["patched_source"]["files"]
    changes = [name for name in sorted(set(before_files) | set(after_files))
               if before_files.get(name) != after_files.get(name)]
    result = {
        "schema": "orbit-poc-derivative-replay-v1", "status": "running",
        "candidate_executable_sha256": candidate["executable_sha256"],
        "reference_executable_sha256": original["executable_sha256"],
        "candidate_build_manifest_sha256": file_hash(candidate_manifest),
        "reference_build_manifest_sha256": file_hash(reference_manifest),
        "diagnostic_source_sha256": file_hash(__file__),
        "unchanged_build_fields": list(same_build),
        "unchanged_extension_component_hashes": component_hashes,
        "changed_patched_source_files": changes,
        "environment": {"ORBIT_POC_NUMERICS_QR_PREFIX": None},
        "scope": "Archived no-GNSS forward/derivative propagation branch; excludes QR-enabled GNSS arithmetic and final-fit covariance",
        "cases": [],
    }
    write_json(root / "result.json", result)
    model = PropagationDiagnostic(binary, root)

    def replay(label, reference, scripts, copied, compared):
        reference, target = Path(reference), root / label
        target.mkdir()
        for name in copied:
            shutil.copyfile(reference / name, target / name)
        configs = []
        for name in scripts:
            source = reference / name
            tree = ET.fromstring(source.read_text().replace(str(reference), str(target)))
            destinations = [Path(node.text) for node in tree.iter()
                            if node.text and (node.tag.startswith("outputfile") or node.tag == "orbitPocDerivativeDiagnostics")]
            if not destinations or any(not path.is_relative_to(target) for path in destinations):
                raise ValueError("Replay would write outside its fresh output directory")
            folder = target / Path(name).parent
            folder.mkdir(parents=True, exist_ok=True)
            model.execute(tree, folder, Path(name).stem)
            configs.append({"source": str(source), "source_sha256": file_hash(source),
                            "actual_sha256": file_hash(folder / Path(name).name)})
        comparisons = []
        for name, columns in compared:
            a, b = reference / name, target / name
            left, right = native.read_native_table(a, columns), native.read_native_table(b, columns)
            if left.shape != right.shape:
                raise ValueError(f"Replay changes native output shape: {name}")
            comparisons.append({"file": name, "reference_sha256": file_hash(a),
                "candidate_sha256": file_hash(b), "rows": len(left), "columns": left.shape[1],
                "numerically_identical": bool(np.array_equal(left, right)),
                "maximum_absolute_difference": float(np.max(np.abs(left-right)))})
        record = {"case": label, "reference_directory": str(reference), "configurations": configs,
                  "comparisons": comparisons, "passed": all(item["numerically_identical"] for item in comparisons)}
        result["cases"].append(record)
        write_json(root / "result.json", result)

    try:
        replay("long-arc", long_arc, ["propagate.xml"], [], [("orbit.txt", 10), ("initial_design.txt", None)])
        replay("flight-baseline", flight,
            [f"closure-{index:02d}/propagate.xml" for index in range(1, 4)] + ["export-stm.xml"],
            ["fixed_force.txt", "physical_initial.txt"],
            # Closure retention may remove the redundant ASCII orbit. This
            # export preserves all six physical state components AND the STM.
            [("physical-stm.txt", 43)])
        result.update(status="complete", passed=all(case["passed"] for case in result["cases"]),
                      native_executions=len(model.executions))
        write_json(root / "result.json", result)
        return result
    except Exception as error:
        result.update(status="failed", error=str(error), native_executions=len(model.executions))
        write_json(root / "result.json", result)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "reference-manifest", "candidate-manifest", "long-arc", "flight", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = check(args.binary, args.reference_manifest, args.candidate_manifest, args.long_arc, args.flight, args.output)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
