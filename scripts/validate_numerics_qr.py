#!/usr/bin/env python3
"""Run the native original-row QR gates and save a hashed validation receipt."""
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


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    native = args.native.resolve(strict=True)
    build = json.loads(args.build_manifest.read_text())
    if build.get("executable_sha256") != sha256(native):
        raise ValueError("Native executable does not match the recorded build")
    extension = build.get("extension") or {}
    if extension.get("extension_profile") != "numerics_v31" or not build.get("patched_source"):
        raise ValueError("QR validation requires a v3.1 build with actual patched-source hashes")
    for name in ("scaledRowQr.h", "native_row_qr.py", "orbitPocQrSolve.cpp", "triangularQrWrapper.f", "artifactReceipt.h", "nuisanceLineSearch.h", "gnssRangeResidual.h", "relativeQueryInterpolation.py", "positionRemainder.py"):
        if extension.get("files", {}).get(name) != sha256(root / "groops/extension" / name):
            raise ValueError(f"Native build does not include current {name}")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    xml = output / "pytest.xml"
    command = [sys.executable, "-m", "pytest", "tests/test_numerics_native_qr.py", "-q",
               "-o", "junit_family=xunit1", f"--basetemp={output / 'fixtures'}", f"--junitxml={xml}"]
    environment = dict(os.environ, ORBIT_POC_V31_NATIVE=str(native), PYTHONPATH=str(root / "src"),
                       OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    binary_hash = sha256(native)
    start = time.monotonic()
    with (output / "pytest.log").open("w") as log:
        result = subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT)
    cases = []
    if xml.exists():
        for case in ET.parse(xml).iter("testcase"):
            status = next((name for name in ("failure", "error", "skipped") if case.find(name) is not None), "passed")
            cases.append({"name": case.get("name"), "status": status, "seconds": float(case.get("time", 0)),
                          "metrics": {value.get("name"): float(value.get("value"))
                                      for value in case.findall("properties/property")}})
    passed = result.returncode == 0 and bool(cases) and all(case["status"] == "passed" for case in cases)
    receipt = {"schema": "orbit-poc-native-qr-validation-v1", "passed": passed,
               "executable_sha256": binary_hash, "binary_unchanged": sha256(native) == binary_hash,
               "build_manifest_sha256": sha256(args.build_manifest),
               "patched_source_sha256": build["patched_source"]["sha256"],
               "validation_seconds": time.monotonic() - start, "returncode": result.returncode,
               "tests": cases, "packages": {name: importlib.metadata.version(name)
                                               for name in ("numpy", "scipy", "pytest", "gtsam")},
               "source_hashes": {name: sha256(root / name) for name in (
                   "groops/extension/scaledRowQr.h", "groops/extension/native_row_qr.py",
                   "groops/extension/orbitPocQrSolve.cpp", "groops/extension/triangularQrWrapper.f",
                   "groops/extension/artifactReceipt.h", "groops/extension/nuisanceLineSearch.h",
                   "groops/extension/gnssRangeResidual.h", "groops/extension/relativeQueryInterpolation.py", "groops/extension/positionRemainder.py", "tests/test_numerics_native_qr.py")},
               "limits": {"map_discrepancy_posterior_standard_deviations": 1e-7,
                          "relative_covariance_error": 1e-8},
               "scope": "Small native original-row systems; does not certify the GNSS pipeline, derivative accuracy, or benchmark completion"}
    receipt["passed"] = receipt["passed"] and receipt["binary_unchanged"]
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": receipt["passed"], "cases": len(cases), "receipt": str(output / "receipt.json")}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
