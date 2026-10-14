#!/usr/bin/env python3
"""Record the targeted small-native acceptance gates omitted by generic QR tests."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    executable = args.native.resolve(strict=True)
    build_manifest = args.build_manifest.resolve(strict=True)
    build = json.loads(build_manifest.read_text())
    binary_hash = digest(executable)
    if build.get("executable_sha256") != binary_hash:
        raise ValueError("Executable does not match the supplied pinned build")
    extension = build.get("extension", {})
    if extension.get("extension_profile") != "numerics_v31" or not build.get("patched_source"):
        raise ValueError("Actual patched-source v3.1 build is required")
    native_files = ("scaledRowQr.h", "native_row_qr.py", "orbitPocQrSolve.cpp", "triangularQrWrapper.f")
    for name in native_files:
        if extension.get("files", {}).get(name) != digest(root / "groops/extension" / name):
            raise ValueError(f"Pinned executable does not include current {name}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    junit = output / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "tests/test_numerics_acceptance.py", "-q",
               "-o", "junit_family=xunit1", f"--basetemp={output / 'fixtures'}", f"--junitxml={junit}"]
    environment = dict(os.environ, ORBIT_POC_V31_NATIVE=str(executable), PYTHONPATH=str(root / "src"),
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    start = time.monotonic()
    with (output / "pytest.log").open("w") as log:
        execution = subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
    cases = []
    if junit.exists():
        for case in ET.parse(junit).iter("testcase"):
            status = next((tag for tag in ("failure", "error", "skipped") if case.find(tag) is not None), "passed")
            cases.append({"name": case.get("name"), "status": status, "seconds": float(case.get("time", 0)),
                          "metrics": {entry.get("name"): float(entry.get("value"))
                                      for entry in case.findall("properties/property")}})
    sources = [f"groops/extension/{name}" for name in native_files] + [
        "tests/test_numerics_acceptance.py", "scripts/validate_numerics_acceptance.py",
        "src/orbit_poc/comparison/density.py", "src/orbit_poc/numerics/report.py"]
    unchanged = digest(executable) == binary_hash
    receipt = {
        "schema": "orbit-poc-native-targeted-acceptance-v1",
        "passed": execution.returncode == 0 and len(cases) == 4 and all(case["status"] == "passed" for case in cases) and unchanged,
        "executable_sha256": binary_hash, "binary_unchanged": unchanged,
        "build_manifest_sha256": digest(build_manifest),
        "patched_source_sha256": build["patched_source"]["sha256"],
        "validation_seconds": time.monotonic() - start, "returncode": execution.returncode,
        "tests": cases, "source_hashes": {name: digest(root / name) for name in sources},
        "packages": {name: importlib.metadata.version(name) for name in ("numpy", "scipy", "pytest", "gtsam")},
        "limits": {"map_discrepancy_posterior_standard_deviations": 1e-7,
                   "relative_covariance_error": 1e-8,
                   "relative_dynamic_nuisance_cross_covariance_error": 1e-8},
        "artifacts": {"junit": {"path": str(junit), "sha256": digest(junit)} if junit.exists() else None,
                      "log": {"path": str(output / "pytest.log"), "sha256": digest(output / "pytest.log")}},
        "scope": "Structured small weighted-row systems through the actual native QR kernel. Direct GTSAM MAP/covariance at nonzero pulse and OU reference parameters, analytic stationary OU covariance, missing initial OU constraint rejection, and original-observation phase-report invariance under ambiguity recentering.",
        "limitations": ["These rows are supplied explicitly; native pulse/OU constraint generation and full nonlinear nuisance profiling require the separate actual-objective gate.",
                        "Does not certify flight Jacobian completeness or frozen benchmark completion."]}
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": receipt["passed"], "cases": len(cases), "receipt": str(output / "receipt.json")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
