#!/usr/bin/env python3
"""Run one blind native v3.1 engineering request without entering the benchmark."""
import argparse
from copy import deepcopy
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import platform
import sys
import traceback

from orbit_poc.comparison.protocol import file_hash, read_json, source_snapshot, write_json
from orbit_poc.numerics.backend import fit_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path,
                        help="Pin a new engineering executable without changing the original request")
    args = parser.parse_args()
    request = read_json(args.request)
    if request.get("split") != "engineering":
        raise ValueError("Use the frozen numerical harness for benchmark attempts")
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Preserve previous attempts; choose a fresh output directory")
    args.output.mkdir(parents=True, exist_ok=True)
    original = deepcopy(request)
    snapshot = source_snapshot()
    request["preparation_source_hash"] = request["source_hash"]
    request["source_hash"] = snapshot["sha256"]
    if args.native_binary is not None:
        request["backend"]["groops_executable"] = str(args.native_binary.resolve())
        request["expected_native_binary_sha256"] = file_hash(args.native_binary)
    packages = {}
    for package in ("numpy", "scipy", "gtsam", "psutil"):
        try:
            packages[package] = version(package)
        except PackageNotFoundError:
            packages[package] = None
    write_json(args.output / "engineering_provenance.json", {
        "scope": "development only; excluded from frozen benchmark attempts",
        "original_request": {"path": str(args.request.resolve()), "sha256": file_hash(args.request)},
        "original_native_binary_sha256": original["expected_native_binary_sha256"],
        "source_at_start": snapshot, "python": sys.executable,
        "python_version": platform.python_version(), "platform": platform.platform(), "packages": packages})
    write_json(args.output / "request.json", request)
    try:
        result = fit_job(request, args.output)
    except Exception as error:
        result = {"status": "failed", "converged": False, "covariance_valid": False,
                  "error": f"{type(error).__name__}: {error}", "traceback": traceback.format_exc()}
    write_json(args.output / "result.json", result)
    write_json(args.output / "source_at_end.json", source_snapshot())
    print({key: result.get(key) for key in ("status", "numerical_status", "converged", "covariance_valid", "error")}, flush=True)
    return 0 if result.get("converged") and result.get("covariance_valid") else 1


if __name__ == "__main__":
    raise SystemExit(main())
