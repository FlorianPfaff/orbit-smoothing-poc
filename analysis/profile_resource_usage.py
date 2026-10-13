"""Fresh-process resource profiles of saved scaling cases, without retuning.

Run from the project root with PYTHONPATH=src. Original inputs and fits are read
only. Each child regenerates its observation-fitted reference in its new output
directory, using the saved parameters and options unchanged. GNU time captures
the whole child's peak RSS, including Python, JAX compilation and output I/O.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def worker(record_path, output_dir):
    import resource
    import numpy as np
    from orbit_poc.benchmark import fit_one, provenance
    from orbit_poc.config import ModelSpec

    original = json.loads(record_path.read_text())
    request = original["request"]
    dataset_path = Path(original["dataset"])
    output_dir.mkdir(parents=True, exist_ok=True)
    if hashlib.sha256(dataset_path.read_bytes()).hexdigest() != request["dataset_sha256"]:
        raise ValueError("Original scaling dataset hash has changed")
    if provenance()["source_sha256"] != request["source_sha256"]:
        raise ValueError("Current production source differs from the scaling source")
    with np.load(dataset_path, allow_pickle=False) as arrays:
        nodes = len(arrays["times"])
        observations = len(arrays["obs_node"])
        duration_hours = float((arrays["times"][-1] - arrays["times"][0]) / 3600)
    started = perf_counter()
    fitted = fit_one(
        dataset_path, request["parameters"], output_dir / "fit",
        solver=request["solver"], options=dict(request["options"]), resume=False,
        truth_path=original.get("truth"), reference_path=output_dir / "reference.npy",
        run_context={**original.get("context", {}), "stage": "resource_profile"},
    )
    call_seconds = perf_counter() - started
    with np.load(Path(fitted["fit"]), allow_pickle=False) as new_arrays, np.load(record_path.with_name("fit.npz"), allow_pickle=False) as old_arrays:
        difference = new_arrays["states"] - old_arrays["states"]
        position_difference = float(np.max(np.linalg.norm(difference[:, :3], axis=1)))
        velocity_difference = float(np.max(np.linalg.norm(difference[:, 3:6], axis=1)))
    usage = resource.getrusage(resource.RUSAGE_SELF)
    result = {
        "purpose": "Performance profile only; no new scientific selection",
        "original_fit_record": str(record_path.resolve()),
        "dataset": str(dataset_path), "dataset_sha256": request["dataset_sha256"],
        "source_sha256": request["source_sha256"],
        "parameters_recorded": request["parameters"],
        "parameters_resolved": ModelSpec(**request["parameters"]).to_dict(),
        "options": request["options"], "solver": request["solver"],
        "duration_hours": duration_hours, "nodes": nodes, "observations": observations,
        "converged": fitted["converged"],
        "fit_elapsed_seconds": fitted["elapsed_seconds"],
        "solver_seconds": fitted.get("solver_seconds"),
        "fit_one_call_wall_seconds": call_seconds,
        "worker_peak_rss_kib_before_exit": usage.ru_maxrss,
        "worker_user_cpu_seconds_before_exit": usage.ru_utime,
        "worker_system_cpu_seconds_before_exit": usage.ru_stime,
        "cpu_affinity": sorted(os.sched_getaffinity(0)),
        "objective": fitted["objective"], "original_objective": original["objective"],
        "max_position_difference_from_original_m": position_difference,
        "max_velocity_difference_from_original_m_s": velocity_difference,
        "reference_sha256": fitted.get("reference_sha256"),
        "original_reference_sha256": original.get("reference_sha256"),
        "reference_policy": "Recomputed from observations in the new profile output directory; original files unchanged",
    }
    write_json(output_dir / "fit_resource_details.json", result)


def parse_time(path):
    fields = {}
    for line in path.read_text().splitlines():
        if ": " in line:
            key, value = line.strip().rsplit(": ", 1)
            fields[key] = value
    elapsed_string = fields["Elapsed (wall clock) time (h:mm:ss or m:ss)"]
    elapsed = 0.0
    for component in elapsed_string.split(":"):
        elapsed = 60 * elapsed + float(component)
    peak_kib = int(fields["Maximum resident set size (kbytes)"])
    return {
        "whole_process_wall_seconds": elapsed,
        "whole_process_user_cpu_seconds": float(fields["User time (seconds)"]),
        "whole_process_system_cpu_seconds": float(fields["System time (seconds)"]),
        "whole_process_peak_rss_kib": peak_kib,
        "whole_process_peak_rss_bytes": peak_kib * 1024,
        "whole_process_peak_rss_mib": peak_kib / 1024,
        "exit_status": int(fields["Exit status"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scaling", type=Path, default=Path("runs/v2/scaling"))
    parser.add_argument("--output", type=Path, default=Path("validation/resource_usage"))
    parser.add_argument("--worker-record", type=Path)
    args = parser.parse_args()
    # Set before any numerical-library import; children inherit this ceiling.
    cores = sorted(os.sched_getaffinity(0))[:2]
    os.sched_setaffinity(0, cores)
    if args.worker_record is not None:
        worker(args.worker_record, args.output)
        return

    args.output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                        "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                        "JAX_PLATFORMS": "cpu", "JAX_ENABLE_X64": "true",
                        "XLA_PYTHON_CLIENT_PREALLOCATE": "false"})
    rows = []
    for hours in (6, 12, 24):
        output = args.output / f"{hours}h"
        output.mkdir(parents=True, exist_ok=True)
        original = (args.scaling / f"{hours}h/fit/fit.json").resolve()
        command = ["/usr/bin/time", "-v", "-o", str(output / "gnu_time.txt"),
                   sys.executable, str(Path(__file__).resolve()),
                   "--worker-record", str(original), "--output", str(output.resolve())]
        with (output / "process.log").open("w") as log:
            completed = subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
        timed = parse_time(output / "gnu_time.txt")
        write_json(output / "process_resources.json", timed)
        if completed.returncode:
            raise RuntimeError(f"{hours}h resource profile failed; see {output / 'process.log'}")
        detail = json.loads((output / "fit_resource_details.json").read_text())
        rows.append({"duration_hours": hours, "nodes": detail["nodes"],
                     "observations": detail["observations"], **timed,
                     "fit_elapsed_seconds": detail["fit_elapsed_seconds"],
                     "solver_seconds": detail["solver_seconds"],
                     "converged": detail["converged"],
                     "max_position_difference_from_original_m": detail["max_position_difference_from_original_m"],
                     "max_velocity_difference_from_original_m_s": detail["max_velocity_difference_from_original_m_s"]})
        print(json.dumps(rows[-1]), flush=True)
    cpu_model = next((line.split(":", 1)[1].strip() for line in Path("/proc/cpuinfo").read_text().splitlines() if line.startswith("model name")), "unknown")
    summary = {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "hostname": platform.node(), "cpu_model": cpu_model,
        "cpu_affinity": cores, "jax_platform": "cpu", "blas_threads": 1,
        "method": "Three sequential, fresh child processes, one existing scaling case each; GNU /usr/bin/time -v captures complete child lifetime",
        "source_sha256": detail["source_sha256"],
        "profiler_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_fits_preserved": True, "rows": rows,
        "interpretation": [
            "Peak RSS includes Python, imported libraries, JAX/XLA compilation, deterministic initialization, inference, diagnostics and output I/O; it is not graph storage alone.",
            "The fresh-process measurements include compilation. Fit and solver timing cover narrower parts of the same child workload.",
            "Each arc length was measured once on a shared host; process startup and compilation overhead can dominate differences.",
            "These three measurements do not establish an asymptotic memory or time complexity law and are not repeated-run confidence intervals.",
            "The original recorded density-model parameters and solver options were unchanged; these runs were not used for scientific model selection or the main comparison.",
        ],
    }
    write_json(args.output / "summary.json", summary)


if __name__ == "__main__":
    main()
