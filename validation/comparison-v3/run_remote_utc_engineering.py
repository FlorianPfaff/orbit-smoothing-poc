"""Prepare blind UTC inputs; fit only with a separate accepted numerical gate.

This is engineering validation, not calibration or flight evaluation. The
script never invokes evaluate_job and never reads reference/SLR measurements.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import time
import traceback

os.environ.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")

METHODS = {
    "groops_pulses": {"interval_seconds": 1200., "sigma_velocity_m_s": 1e-4},
    "groops_log_drag_ou": {"knot_seconds": 60., "tau_seconds": 7200.,
                          "sigma_log_density": .3, "interpolation": "linear_log_density",
                          "initial_prior": "stationary_ou", "empirical_acceleration": False},
}


def api(project):
    sys.path.insert(0, str(Path(project) / "src"))
    from orbit_poc.comparison import backend
    from orbit_poc.comparison.protocol import read_json, write_json, file_hash, source_snapshot
    return backend, read_json, write_json, file_hash, source_snapshot


def perform(task):
    os.sched_setaffinity(0, task["cpus"])
    backend, read, write, hash_file, snapshot = api(task["project"])
    folder = Path(task["folder"])
    result_file = folder / "result.json"
    if result_file.exists():
        raise ValueError(f"Refusing to overwrite a prior status: {result_file}")
    folder.mkdir(parents=True, exist_ok=True)
    request = deepcopy(task["request"])
    write(folder / "request.json", request)
    started = time.monotonic()
    try:
        if snapshot()["sha256"] != task["source_sha256"]:
            raise ValueError("Source changed after the engineering inputs were frozen")
        if task["kind"] == "prepare":
            result = backend.prepare_job(request, folder / "inputs")
        else:
            if any(key in request for key in ("evaluation_inputs", "calibration_inputs", "reference_orbit", "truth")):
                raise ValueError("Evaluation input leaked into an engineering fit request")
            result = backend.fit_job(request, folder)
    except Exception as error:
        result = {"status": "failed", "error": str(error), "traceback": traceback.format_exc()}
    result["engineering_execution"] = {"elapsed_seconds": time.monotonic() - started,
        "cpu_affinity": sorted(os.sched_getaffinity(0)), "threads": 1,
        "kind": task["kind"], "evaluation_performed": False}
    write(result_file, result)
    record = {"label": task["label"], "status": result.get("status"),
              "converged": result.get("converged"), "covariance_valid": result.get("covariance_valid"),
              "error": result.get("error"), "result": str(result_file),
              "result_sha256": hash_file(result_file), "elapsed_seconds": time.monotonic() - started}
    history_path = folder / "outer_iterations.json"
    if history_path.exists():
        history = read(history_path)["iterations"]
        audits = [row.get("preprocessing_audit_sha256") for row in history]
        record.update(iterations=len(history), audit_sha256=audits[-1] if audits else None,
            audit_stable_across_outer_iterations=bool(audits) and None not in audits and len(set(audits)) == 1)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "fit"])
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--expected-native-sha256", required=True)
    parser.add_argument("--workers", type=int, default=2, choices=[1, 2, 3, 4])
    parser.add_argument("--acceptance-record", type=Path,
                        help="Fit only: explicit passed full-flight gate receipt with binary SHA and hashed evidence")
    args = parser.parse_args()
    backend, read, write, hash_file, snapshot = api(args.project)
    if hash_file(args.binary) != args.expected_native_sha256:
        raise ValueError("Requested native executable does not match its SHA256")
    args.output.mkdir(parents=True, exist_ok=True)
    env_library = str((args.runtime / "native/lib").resolve())
    os.environ["LD_LIBRARY_PATH"] = env_library + (":" + os.environ["LD_LIBRARY_PATH"] if os.environ.get("LD_LIBRARY_PATH") else "")
    cpus = sorted(os.sched_getaffinity(0))
    if len(cpus) < args.workers:
        raise ValueError("Not enough permitted CPU cores for the requested worker count")
    # At most four cores total, one serial BLAS/OpenMP thread per native process.
    groups = [[cpus[index]] for index in range(args.workers)]
    project_source = snapshot()
    freeze_path = args.output / "engineering_inputs.json"
    tasks = []
    if args.mode == "prepare":
        if freeze_path.exists():
            raise ValueError("Use a fresh output directory; engineering_inputs.json already exists")
        frozen = {"scope": "Engineering only; no calibration, GNV, SLR or scientific evaluation",
            "date": "2024-04-24", "arc_time_scale": "UTC", "duration_hours": 24.,
            "source": project_source, "native_binary_sha256": args.expected_native_sha256,
            "native_binary": str(args.binary.resolve()), "methods": METHODS,
            "fits_authorized": False, "evaluation_authorized": False}
        write(freeze_path, frozen)
        for label, intervals in (("normal", []), ("blackout", [[39600, 46800]])):
            request = {"stage": "flight", "split": "engineering",
                "case": {"date": "2024-04-24", "duration_hours": 24., "coverage": label,
                         "mask": {"intervals_seconds": intervals, "cadence_seconds": 30, "time_scale": "UTC"}},
                "backend": {"groops_executable": str(args.binary.resolve()),
                    "auxiliary_dir": str((args.runtime / "inputs/auxiliary").resolve()),
                    "cache_dir": str((args.runtime / "inputs/cache").resolve()),
                    "example_directory": str((args.runtime / "inputs/example").resolve()),
                    "retain_native_diagnostics": True, "command_timeout_seconds": 7200.},
                "expected_native_binary_sha256": args.expected_native_sha256}
            tasks.append({"kind": "prepare", "label": label, "folder": str(args.output / label / "preparation"),
                          "request": request})
    else:
        frozen = read(freeze_path)
        if frozen["source"]["sha256"] != project_source["sha256"]:
            raise ValueError("Source differs from prepared engineering inputs; prepare a fresh directory")
        if frozen["native_binary_sha256"] != args.expected_native_sha256:
            raise ValueError("Native executable differs from the one used for preparation")
        if args.acceptance_record is None:
            raise ValueError("Numerical fits are disabled without --acceptance-record")
        acceptance = read(args.acceptance_record)
        if acceptance.get("passed") is not True or acceptance.get("native_binary_sha256") != args.expected_native_sha256:
            raise ValueError("Acceptance record must explicitly pass this native executable")
        if not acceptance.get("evidence"):
            raise ValueError("Acceptance record must cite numerical gate evidence")
        for evidence in acceptance["evidence"]:
            if hash_file(evidence["path"]) != evidence["sha256"]:
                raise ValueError("Numerical gate evidence changed")
        write(args.output / "fit_authorization.json", {"record": acceptance,
            "acceptance_record_sha256": hash_file(args.acceptance_record), "evaluation_authorized": False})
        for label in ("normal", "blackout"):
            preparation = args.output / label / "preparation"
            prepared = read(preparation / "result.json")
            if prepared.get("status") != "prepared":
                raise ValueError(f"Input preparation did not complete: {label}")
            base = read(preparation / "request.json")
            for method, parameters in METHODS.items():
                request = {**base, "method": method, "parameters": parameters,
                    "source_hash": project_source["sha256"], "estimation_inputs": prepared["estimation_inputs"],
                    **{key: prepared[key] for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")}}
                tasks.append({"kind": "fit", "label": f"{label}/{method}",
                    "folder": str(args.output / label / method), "request": request})
    for index, task in enumerate(tasks):
        task.update(project=str(args.project.resolve()), source_sha256=project_source["sha256"],
                    cpus=groups[index % len(groups)])
    report = {"mode": args.mode, "scope": frozen["scope"], "complete": False, "records": [],
              "workers": args.workers, "cpu_groups": groups, "evaluation_performed": False,
              "native_binary_sha256": args.expected_native_sha256, "source_sha256": project_source["sha256"]}
    report_path = args.output / f"{args.mode}_status.json"
    write(report_path, report)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        pending = {executor.submit(perform, task): task["label"] for task in tasks}
        for future in as_completed(pending):
            try:
                record = future.result()
            except Exception as error:
                record = {"label": pending[future], "status": "failed", "error": str(error)}
            report["records"].append(record)
            write(report_path, report)
            print(json.dumps(record, sort_keys=True), flush=True)
    report["complete"] = True
    if args.mode == "fit":
        groups = {label: [row for row in report["records"] if row["label"].startswith(label + "/")]
                  for label in ("normal", "blackout")}
        report["same_audit_across_methods"] = {label: len(rows) == 2 and
            len({row.get("audit_sha256") for row in rows}) == 1 and rows[0].get("audit_sha256") is not None
            for label, rows in groups.items()}
        report["passed"] = all(row.get("converged") and row.get("covariance_valid") and
            row.get("audit_stable_across_outer_iterations") for row in report["records"]) and all(report["same_audit_across_methods"].values())
    else:
        report["passed"] = len(report["records"]) == 2 and all(row["status"] == "prepared" for row in report["records"])
    write(report_path, report)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
