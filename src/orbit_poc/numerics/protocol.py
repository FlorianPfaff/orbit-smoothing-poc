"""Frozen numerical experiments, isolated runtimes and inclusive checkpoints.

This harness does not select statistical hyperparameters or open truth/reference
arrays. Historical numerical failures are fixed fixtures, never replaced by
successful fits. There is exactly one new execution per case/profile.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from orbit_poc.comparison.protocol import (canonical_hash, file_hash, read_json,
    source_snapshot, validate_estimation_inputs, validate_fit_result, write_json)
from .config import Artifact, FRESH_SEEDS, METHODS, ORBITS, PROFILES, is_digest

EVIDENCE = {
    "pulse": ("candidate03-pulse-factorization-diagnostic-20261014T0217.json", "9e0940a3058190f56fc97c6954da3f3c3ad87a4badb1aae280b8e0ef9341888c"),
    "density": ("first-density-scoring-audit-3b434b8c.json", "591db1b5e74fe84db8aa731a82cabc776bc18271e9edd53ba44bf7112e1029ef"),
    "flight": ("utc_engineering_fits_74863.json", "0df7a4924c72a005038a0ffd356fd503bcf855f682c23d181573c88f8679c068"),
}
TERMINAL = {"complete", "failed", "blocked", "timeout", "unresolved_rank",
            "nonconverged", "invalid_covariance", "interrupted", "memory_limit", "disk_limit"}
FORBIDDEN = {"truth", "evaluation_inputs", "calibration_inputs", "reference_orbit", "slr_validation"}
IDENTITIES = ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")
ATTEMPT_WALL_SECONDS = 7200.


class NotReady(RuntimeError):
    """A recorded, non-executing block; never interpreted as a fit failure."""


def project_root():
    return Path(__file__).resolve().parents[3]


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def resolve(path, project):
    p = Path(path)
    return (p if p.is_absolute() else Path(project) / p).resolve()


def verify_artifact(item, project=None):
    item = asdict(item) if isinstance(item, Artifact) else item
    if not item.get("path") or not is_digest(item.get("sha256")):
        raise NotReady("An input/runtime artifact has not been pinned")
    path = resolve(item["path"], project or project_root())
    if not path.is_file() or file_hash(path) != item["sha256"]:
        raise NotReady(f"Missing or changed pinned artifact: {path}")
    return path


def artifact(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": file_hash(path)}


def fresh_case(orbit, atmosphere, coverage):
    return {"orbit": orbit, "atmosphere": atmosphere, "coverage": coverage,
            "seed": FRESH_SEEDS[atmosphere], "arc_id": f"{orbit}-{FRESH_SEEDS[atmosphere]}",
            "epoch": "2024-05-10T00:00:00", "duration_hours": 24., "cadence": 30.,
            "mask": {"cadence_seconds": 30, "time_scale": "elapsed",
                     "intervals_seconds": [[39600, 46800]] if coverage == "blackout" else []},
            "truth_model": "tudat_independent_central_j2_exponential_gnss"}


def planned_cases(project=None):
    """Construct the fixed 18 retained + 32 prospective cases from pinned ledgers."""
    project = Path(project or project_root())
    ledgers = {}
    for kind, (name, digest) in EVIDENCE.items():
        path = verify_artifact({"path": str(project / "validation/comparison-v3" / name), "sha256": digest})
        ledgers[kind] = read_json(path)
    cases = []
    pulse = ledgers["pulse"]
    neighbors = {r["failed_job"]: r for r in pulse["same_input_neighbors"]}
    failures = sorted(pulse["records"], key=lambda r: r["case"]["seed"])
    if len(failures) != 6 or {r["case"]["seed"] for r in failures} != set(range(300000, 300006)):
        raise ValueError("Retained pulse ledger must contain the six declared seeds")
    for record in failures:
        seed = record["case"]["seed"]
        base = {"stage": "synthetic", "case": record["case"], "method": "groops_pulses"}
        cases.append({**base, "case_id": f"retained-pulse-weak-{seed}", "origin": "retained_pulse_failure",
            "parameters": record["parameters"], "historical_request": record["request"],
            "historical_result": record["result"]})
        choices = [r for r in neighbors[record["job"]]["successful_stronger_priors"]
                   if r["sigma_velocity_m_s"] == 1e-3]
        if len(choices) != 1 or not neighbors[record["job"]]["retained_inputs_identical"]:
            raise ValueError("Exactly one matching 1e-3 pulse neighbor is required")
        choice = choices[0]
        result_path = Path(record["result"]["path"]).parent.parent / choice["job"] / "result.json"
        cases.append({**base, "case_id": f"retained-pulse-neighbor-{seed}", "origin": "retained_pulse_neighbor",
            "parameters": {**record["parameters"], "sigma_velocity_m_s": 1e-3},
            "historical_result": {"path": str(result_path), "sha256": choice["result_sha256"]}})
    for record in sorted(ledgers["density"]["records"], key=lambda r: r["case"]["holdout_minutes"]):
        index = record["fit_result_record"]
        cases.append({"case_id": f"retained-density-{record['case']['holdout_minutes']}",
            "origin": "retained_slow_density", "stage": "synthetic", "case": record["case"],
            "method": record["method"], "parameters": record["parameters"],
            "historical_result": {"path": index["result_path"], "sha256": index["result_sha256"]}})
    for record in sorted(ledgers["flight"]["records"], key=lambda r: (r["method"], r["coverage"])):
        # Exact settings read from the pinned April 24 requests; never selected
        # again from current campaign outcomes.
        flight_case = {"date": "2024-04-24", "coverage": record["coverage"], "duration_hours": 24.,
            "mask": {"cadence_seconds": 30, "time_scale": "UTC",
                     "intervals_seconds": [[39600, 46800]] if record["coverage"] == "blackout" else []}}
        flight_parameters = ({"interval_seconds": 1200., "sigma_velocity_m_s": 1e-4}
            if record["method"] == "groops_pulses" else {"knot_seconds": 60., "tau_seconds": 7200.,
                "sigma_log_density": .3, "interpolation": "linear_log_density",
                "initial_prior": "stationary_ou", "empirical_acceleration": False})
        cases.append({"case_id": f"retained-april24-{record['coverage']}-{record['method']}",
            "origin": "retained_flight_control", "stage": "flight", "method": record["method"],
            "case": flight_case, "parameters": flight_parameters,
            "expected_date": "2024-04-24", "expected_coverage": record["coverage"],
            "historical_request": {"path": record["request_path"], "sha256": record["request_sha256"]},
            "historical_result": {"path": record["result_path"], "sha256": record["result_sha256"]}})
    if len(cases) != 18:
        raise ValueError("Exactly 18 retained numerical fixtures are required")
    for orbit in ORBITS:
        for atmosphere in FRESH_SEEDS:
            for coverage in ("normal", "blackout"):
                for method in METHODS:
                    parameters = ({"interval_seconds": 1200., "sigma_velocity_m_s": 1e-4, "frame": "CRF"}
                        if method == "groops_pulses" else {"knot_seconds": 60., "tau_seconds": 1800.,
                            "sigma_log_density": .1, "interpolation": "linear_log_density",
                            "initial_prior": "stationary_ou", "empirical_acceleration": False})
                    cases.append({"case_id": f"fresh-{orbit}-{atmosphere}-{coverage}-{method}",
                        "origin": "fresh", "stage": "synthetic", "case": fresh_case(orbit, atmosphere, coverage),
                        "method": method, "parameters": parameters})
    if len(cases) != 50 or len({r["case_id"] for r in cases}) != 50:
        raise ValueError("The numerical benchmark must have 50 distinct cases")
    return cases


def attempts(cases):
    # Rotate rather than always favoring one profile with a cold/warm cache.
    return [{"attempt_id": f"{case['case_id']}--{profile}", "case_id": case["case_id"],
             "profile": profile, "order": 3*i+j}
            for i, case in enumerate(cases)
            for j, profile in enumerate(PROFILES[i % 3:] + PROFILES[:i % 3])]


def verify_runtime(runtime, project):
    if not runtime.source_root or not runtime.source_sha256:
        raise NotReady("An immutable runtime source snapshot is required")
    source = resolve(runtime.source_root, project)
    if not source.is_dir() or source_snapshot(source)["sha256"] != runtime.source_sha256:
        raise NotReady(f"Runtime source differs from its frozen identity: {source}")
    python, native = (verify_artifact(item, project) for item in (runtime.python, runtime.native))
    if not os.access(python, os.X_OK) or not os.access(native, os.X_OK):
        raise NotReady("Pinned Python/native files must be executable")
    supplemental = None
    if runtime.supplemental_sources.path:
        supplemental = read_json(verify_artifact(runtime.supplemental_sources, project))
        if set(supplemental) != {"schema_version", "files"} or supplemental["schema_version"] != 1 or not supplemental["files"]:
            raise ValueError("Supplemental source inventory requires schema_version=1 and nonempty files")
        seen = set()
        for item in supplemental["files"]:
            target = verify_artifact(item, project)
            if not target.is_relative_to(source) or target in seen:
                raise ValueError("Supplemental source must occur once within its runtime source tree")
            seen.add(target)
        supplemental = artifact(verify_artifact(runtime.supplemental_sources, project))
    libraries = None
    if runtime.library_manifest.path:
        libraries = read_json(verify_artifact(runtime.library_manifest, project))
        if set(libraries) != {"directory", "files"} or not libraries["files"]:
            raise ValueError("Library manifest requires only directory and a nonempty file/hash list")
        directory = resolve(libraries["directory"], project)
        for item in libraries["files"]:
            target = verify_artifact(item, project)
            if not target.is_relative_to(directory):
                raise ValueError("A pinned library lies outside the declared library directory")
        libraries = {**libraries, "directory": str(directory)}
    # Preserve the venv invocation path: resolving its final symlink would run
    # the base interpreter and silently select a different site-packages tree.
    invocation = Path(runtime.python.path)
    if not invocation.is_absolute(): invocation = project / invocation
    invocation = invocation.parent.resolve() / invocation.name
    return {"source_root": str(source), "source_sha256": runtime.source_sha256,
            "python": {"path": str(invocation), "sha256": file_hash(invocation), "resolved_path": str(python)},
            "native": artifact(native), "libraries": libraries, "supplemental_sources": supplemental}


def resource_guard(resources, project=None, output_directory=None, *, proc_root=Path("/proc")):
    """Fail closed unless protected v3 processes have exited or disjoint CPUs."""
    project = Path(project or project_root())
    path = verify_artifact(resources.protected_process_receipt, project)
    receipt = read_json(path)
    required = {"schema_version", "pid", "start_ticks", "boot_id", "command_sha256", "scope_tokens"}
    if set(receipt) != required or receipt["schema_version"] != 1:
        raise ValueError("Unknown or incomplete protected-process identity receipt")
    if type(receipt["pid"]) is not int or receipt["pid"] < 1 or type(receipt["start_ticks"]) is not int:
        raise ValueError("Protected process PID/start ticks must be positive integers")
    if not is_digest(receipt["command_sha256"]) or not receipt["scope_tokens"] or any(
            not isinstance(x, str) or len(x) < 8 for x in receipt["scope_tokens"]):
        raise ValueError("Protected process requires command hash and specific scope tokens")
    boot = (proc_root / "sys/kernel/random/boot_id").read_text().strip()
    values = {}
    for line in (proc_root / "meminfo").read_text().splitlines():
        fields = line.split()
        if fields[0] == "MemAvailable:": values["available_bytes"] = int(fields[1])*1024
    if values.get("available_bytes", 0) < resources.minimum_available_bytes:
        raise NotReady("Insufficient available memory for the worker plus protected reserve")
    if output_directory is not None:
        values["free_output_bytes"] = shutil.disk_usage(output_directory).free
        if values["free_output_bytes"] < resources.minimum_free_output_bytes:
            raise NotReady("Insufficient output storage for the reserved numerical working space")
    if resources.physical_backing_path:
        values["free_physical_backing_bytes"] = shutil.disk_usage(resources.physical_backing_path).free
        if values["free_physical_backing_bytes"] < resources.minimum_free_backing_bytes:
            raise NotReady("Physical backing filesystem reserve would be violated")
    active = []
    import hashlib
    for entry in proc_root.glob("[0-9]*"):
        try:
            raw = (entry / "cmdline").read_bytes()
            text = raw.replace(b"\0", b" ").decode(errors="replace")
            pid = int(entry.name)
            identity_match = False
            if pid == receipt["pid"] and boot == receipt["boot_id"]:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                identity_match = int(fields[19]) == receipt["start_ticks"]
                if identity_match and hashlib.sha256(raw).hexdigest() != receipt["command_sha256"]:
                    raise NotReady("Protected PID/start identity has an unexpected command")
            if identity_match or any(token in text for token in receipt["scope_tokens"]):
                active.append(pid)
        except (FileNotFoundError, ProcessLookupError):
            continue
        except PermissionError as error:
            raise NotReady("Cannot inspect process scope safely") from error
    cpus = set(resources.reserved_cpu_ids)
    if cpus and not cpus <= set(os.sched_getaffinity(0)):
        raise NotReady("Requested CPU reservation is outside this process's allowed CPUs")
    if active:
        if not cpus:
            raise NotReady(f"Protected v3 scope is active ({len(active)} processes); benchmark execution waits")
        for pid in active:
            try:
                if cpus & set(os.sched_getaffinity(pid)):
                    raise NotReady("CPU reservation overlaps the protected v3 process tree/scope")
            except ProcessLookupError:
                continue
    return {"checked_at": timestamp(), **values, "protected_receipt": artifact(path),
            "protected_active_pids": active, "reserved_cpu_ids": sorted(cpus),
            "policy": "serial attempts; verify disjoint CPU affinity when protected scope is active; preserve memory and output-storage reserves"}


@contextmanager
def exclusive(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / "numerics.lock").open("a") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise NotReady("Another numerical prepare/run owns this output directory") from error
        yield


def _root(config, output_dir, project):
    root = resolve(output_dir or config.output_dir, project)
    # Never write benchmark results into the archived runtime or code directories.
    protected = [project / name for name in ("src", "groops", "scripts", "configs", "validation")]
    if config.legacy_runtime.source_root:
        protected.append(resolve(config.legacy_runtime.source_root, project))
    receipt = config.resources.protected_process_receipt
    if receipt.path:
        receipt_path = verify_artifact(receipt, project)
        for value in read_json(receipt_path).get("scope_tokens", []):
            if Path(value).is_absolute(): protected.append(Path(value).resolve())
    locations = [root] + [resolve(value, project) for value in (config.preparation_dir, config.archive_dir) if value]
    if any(location == p or location.is_relative_to(p) for location in locations for p in protected):
        raise ValueError("Numerics outputs must be separate from protected source/evidence")
    return root


def _freeze_plan(config, root, project):
    payload = {"schema_version": 1, "name": config.name, "config": asdict(config),
        "source": source_snapshot(project), "cases": planned_cases(project),
        "evidence": {k: {"path": str(project / "validation/comparison-v3" / n), "sha256": h}
                     for k, (n, h) in EVIDENCE.items()}}
    payload["attempts"] = attempts(payload["cases"])
    payload = json.loads(json.dumps(payload))  # Canonical persisted tuple/list representation.
    payload["plan_hash"] = canonical_hash(payload)
    path = root / "plan.json"
    if path.exists() and read_json(path) != payload:
        raise ValueError("Frozen numerical plan/source/config changed; use a new output directory")
    if not path.exists(): write_json(path, payload)
    return payload


def _verify_plan(config, root, project):
    plan = read_json(root / "plan.json")
    if plan.get("plan_hash") != canonical_hash({k: v for k, v in plan.items() if k != "plan_hash"}):
        raise ValueError("Frozen plan hash is invalid")
    if plan["config"] != json.loads(json.dumps(asdict(config))) or plan["source"] != source_snapshot(project):
        raise ValueError("Source/config differs from the frozen numerical plan")
    if plan["cases"] != planned_cases(project) or plan["attempts"] != attempts(plan["cases"]):
        raise ValueError("Frozen numerical case/profile selection changed")
    return plan


def _verify_blind_request(request):
    if FORBIDDEN.intersection(request):
        raise ValueError("Numerical fitting accepts estimation inputs only")
    validate_estimation_inputs(request["estimation_inputs"], flight=request["stage"] == "flight")
    for key in IDENTITIES:
        if not is_digest(request.get(key)):
            raise ValueError(f"Missing native input identity: {key}")
    if request["mask_hash"] != canonical_hash(request["case"].get("mask", {})):
        raise ValueError("Frozen observation mask does not match the numerical case")
    # Verify converted files and reject reference paths in the native manifest.
    from orbit_poc.comparison.backend import _preparation
    prepared = _preparation(request)
    return prepared


def _retained_request(case):
    result_path = verify_artifact(case["historical_result"])
    result = read_json(result_path)
    request_path = (verify_artifact(case["historical_request"]) if "historical_request" in case
                    else result_path.with_name("request.json"))
    request = read_json(request_path)
    if "historical_request" not in case and canonical_hash(request) != result.get("request_hash"):
        raise ValueError("Historical request differs from its pinned result")
    if request.get("method") != case["method"] or request.get("stage") != case["stage"]:
        raise ValueError("Historical method/stage mismatch")
    if "case" in case and request["case"] != case["case"]:
        raise ValueError("Historical numerical case mismatch")
    if "parameters" in case and request["parameters"] != case["parameters"]:
        raise ValueError("Historical statistical parameters changed")
    if case["origin"] == "retained_flight_control":
        if request["case"].get("date") != case["expected_date"] or request["case"].get("coverage") != case["expected_coverage"]:
            raise ValueError("April 24 fixture date/coverage changed")
    return request, {"request": artifact(request_path), "historical_result": case["historical_result"]}


def _seed_inventory(config, project):
    if not config.prior_seed_protocols:
        raise NotReady("Pin prior protocol/seed manifests before asserting that fresh seeds are unused")
    observed = set(range(42, 62)) | set(range(300000, 300006)) | set(range(400000, 400050)) | set(range(500000, 500005))
    records = []
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "seed" and type(item) is int: observed.add(item)
                elif "seeds" in key and isinstance(item, list): observed.update(x for x in item if type(x) is int)
                visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
    for item in config.prior_seed_protocols:
        path = verify_artifact(item, project); visit(read_json(path)); records.append(artifact(path))
    if observed & set(FRESH_SEEDS.values()):
        raise ValueError("A prospective numerical seed has already appeared in a pinned prior protocol")
    return {"checked_protocols": records, "fresh_seeds": FRESH_SEEDS, "overlap": [],
            "scope": "Pinned historical protocols and published v2/v3 seed ranges; not a claim about unrecorded experiments"}


WORKER = r'''
import importlib,json,os,sys,traceback
from pathlib import Path
source,request_path,output_path,module,operation,cpu_json=sys.argv[1:]
sys.path.insert(0,str(Path(source)/"src"))
cpus=json.loads(cpu_json)
if cpus: os.sched_setaffinity(0,cpus)
request=json.loads(Path(request_path).read_text())
try:
    result=getattr(importlib.import_module(module),operation)(request,Path(output_path).parent)
except Exception as error:
    result={"status":"failed","converged":False,"covariance_valid":False,
            "error":type(error).__name__+": "+str(error),"traceback":traceback.format_exc()}
temporary=Path(output_path).with_suffix(".tmp")
temporary.write_text(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n")
temporary.replace(output_path)
'''


def _execute_job(job, directory, runtime, resources, operation="fit_job"):
    """Run both new and archived code in isolated, pinned child interpreters."""
    import psutil
    directory.mkdir(parents=True, exist_ok=True)
    request_path = directory / "worker-request.json"
    output_path = directory / "worker-result.json"
    if output_path.exists(): raise ValueError("Refusing an implicit attempt retry")
    write_json(request_path, job)
    archived = job.get("numerics_profile") == "legacy_v3"
    module = "orbit_poc.comparison.backend" if archived or operation == "prepare_job" else "orbit_poc.numerics.backend"
    command = [runtime["python"]["path"], "-s", "-c", WORKER, runtime["source_root"],
               str(request_path), str(output_path), module, operation, json.dumps(resources.reserved_cpu_ids)]
    env = os.environ.copy()
    for key in list(env):
        if key not in ("PYTHONPATH", "PYTHONHOME") and not key.startswith("ORBIT_POC_"):
            continue
        env.pop(key, None)
    env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1", OPENBLAS_NUM_THREADS="1",
               OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
               VECLIB_MAXIMUM_THREADS="1", BLIS_NUM_THREADS="1", GOTO_NUM_THREADS="1")
    if runtime["libraries"]:
        env["LD_LIBRARY_PATH"] = runtime["libraries"]["directory"]
    start = time.monotonic(); peak = 0; stopped = None
    last_disk_check, minimum_free_disk = -float("inf"), shutil.disk_usage(directory).free
    minimum_free_backing = (shutil.disk_usage(resources.physical_backing_path).free
                            if resources.physical_backing_path else None)
    with (directory / "worker.log").open("wb") as log:
        process = subprocess.Popen(command, cwd=runtime["source_root"], env=env,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                try:
                    parent = psutil.Process(process.pid)
                    rss = sum(p.memory_info().rss for p in [parent, *parent.children(recursive=True)] if p.is_running())
                    peak = max(peak, rss)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
                if time.monotonic()-last_disk_check >= 1.:
                    minimum_free_disk = min(minimum_free_disk, shutil.disk_usage(directory).free)
                    if resources.physical_backing_path:
                        minimum_free_backing = min(minimum_free_backing, shutil.disk_usage(resources.physical_backing_path).free)
                    last_disk_check = time.monotonic()
                if time.monotonic()-start > ATTEMPT_WALL_SECONDS: stopped = "timeout"
                elif peak > resources.maximum_process_tree_rss_bytes: stopped = "memory_limit"
                elif minimum_free_disk < resources.reserved_output_bytes: stopped = "disk_limit"
                elif minimum_free_backing is not None and minimum_free_backing < resources.minimum_free_backing_bytes: stopped = "disk_limit"
                if stopped:
                    os.killpg(process.pid, signal.SIGTERM)
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: os.killpg(process.pid, signal.SIGKILL)
                    # SIGKILL the group even if the group leader exited first.
                    try: os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError: pass
                    break
                time.sleep(.05)
        except BaseException:
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait()
            raise
        process.wait()
    elapsed = time.monotonic()-start
    if stopped:
        result = {"status": stopped, "converged": False, "covariance_valid": False,
                  "error": "Numerical attempt exceeded its frozen execution resource limit"}
    elif process.returncode or not output_path.is_file():
        result = {"status": "failed", "converged": False, "covariance_valid": False,
                  "error": f"Isolated worker exited {process.returncode} without a valid result"}
    else:
        result = read_json(output_path)
    result["harness_execution"] = {"elapsed_seconds": elapsed, "peak_process_tree_rss_bytes": peak,
        "returncode": process.returncode, "pid": process.pid, "process_group_isolated": True,
        "runtime": runtime, "log": artifact(directory / "worker.log"),
        "resource_limit_status": stopped, "minimum_free_output_bytes": minimum_free_disk,
        "reserved_output_bytes": resources.reserved_output_bytes,
        "minimum_free_physical_backing_bytes": minimum_free_backing,
        "physical_backing_path": resources.physical_backing_path,
        "reserved_physical_backing_bytes": resources.minimum_free_backing_bytes,
        "measurement": "parent plus descendant RSS sampled at 50 ms; output filesystem free bytes sampled at 1 s"}
    return result


def _fresh_preparation(case, config, plan, root, project, runtime, catalog):
    key = canonical_hash(case)
    if catalog is not None:
        matches = [item for item in catalog["entries"] if item["case"] == case]
        if len(matches) != 1: raise NotReady("Prepared-input catalog lacks exactly one prospective case")
        if set(matches[0]) != {"case", "result", "request"}:
            raise ValueError("Catalog entries require exactly case, result and request artifacts")
        path = verify_artifact(matches[0]["result"])
        result = read_json(path)
        request = read_json(verify_artifact(matches[0]["request"]))
        if request.get("case") != case or request.get("kind") != "prepare" or result.get("request_hash") != canonical_hash(request):
            raise ValueError("Catalog preparation request/result identity does not match the prospective case")
    else:
        from orbit_poc.comparison.config import load_config
        comparison = load_config(verify_artifact(config.comparison_config, project))
        directory = (resolve(config.preparation_dir, project) if config.preparation_dir else root / "preparation") / key
        path = directory / "prepared.json"
        if path.exists():
            index = read_json(directory / "record.json")
            if index["case"] != case: raise ValueError("Prospective preparation case changed")
            verify_artifact(index["result"])
            result = read_json(path)
        else:
            resource_guard(config.resources, project, root)
            job = {"id": f"numerics-prepare-{key[:20]}", "kind": "prepare", "stage": "synthetic",
                   "split": "calibration", "case": case, "source_hash": runtime["source_sha256"],
                   "protocol_hash": plan["plan_hash"], "backend": {**asdict(comparison.backend),
                       "groops_executable": runtime["native"]["path"]},
                   "expected_native_binary_sha256": runtime["native"]["sha256"]}
            result = _execute_job(job, directory, runtime, config.resources, "prepare_job")
            # Evaluation outputs produced by generation never enter the fitting manifest.
            result = {k: v for k, v in result.items() if k not in FORBIDDEN}
            write_json(path, result)
            write_json(directory / "record.json", {"case": case, "result": artifact(path)})
    if result.get("status") != "prepared":
        raise NotReady("A prospective preparation failed; its immutable checkpoint requires a new campaign")
    return result, artifact(path)


def prepare(config, output_dir=None, *, project=None):
    config.validate(); project = Path(project or project_root()).resolve()
    root = _root(config, output_dir, project)
    with exclusive(root):
        plan = _freeze_plan(config, root, project)
        if (root / "manifest.json").exists():
            manifest = verify_manifest(config, root, project)
            return {"status": "prepared", "expected_attempts": 150, "manifest_hash": manifest["manifest_hash"]}
        try:
            legacy = verify_runtime(config.legacy_runtime, project)
            runtime = verify_runtime(config.new_runtime, project)
            guard = resource_guard(config.resources, project, root)
            seeds = _seed_inventory(config, project)
            context = artifact(verify_artifact(config.execution_context, project)) if config.execution_context.path else None
            catalog = read_json(verify_artifact(config.prepared_input_catalog, project)) if config.prepared_input_catalog.path else None
            if catalog is not None and (set(catalog) != {"schema_version", "entries"} or catalog["schema_version"] != 1):
                raise ValueError("Unknown prepared-input catalog schema")
            prepared_cache = {}; frozen_cases = []
            for case in plan["cases"]:
                if case["origin"] != "fresh":
                    request, lineage = _retained_request(case)
                else:
                    key = canonical_hash(case["case"])
                    if key not in prepared_cache:
                        prepared_cache[key] = _fresh_preparation(case["case"], config, plan, root, project, runtime, catalog)
                    prepared, reference = prepared_cache[key]
                    request = {"stage": "synthetic", "case": case["case"], "method": case["method"],
                        "parameters": case["parameters"], "estimation_inputs": prepared["estimation_inputs"],
                        **{k: prepared[k] for k in IDENTITIES}}
                    lineage = {"preparation": reference}
                prepared = _verify_blind_request(request)
                if root == Path(prepared["output_dir"]).resolve() or root.is_relative_to(Path(prepared["output_dir"]).resolve()):
                    raise ValueError("Numerics outputs overlap an immutable preparation")
                # Do not forward a historical backend/source identity into a new profile.
                fit = {k: request[k] for k in ("stage", "case", "method", "parameters", "estimation_inputs", *IDENTITIES)}
                inventory = [*fit["estimation_inputs"], *prepared.get("native_artifacts", [])]
                frozen_cases.append({**case, "fit_request": fit, "lineage": lineage,
                    "input_inventory": inventory, "input_manifest_hash": canonical_hash(inventory)})
            record = {"schema_version": 1, "plan_hash": plan["plan_hash"], "source": plan["source"],
                "profiles": list(PROFILES), "cases": frozen_cases, "attempts": plan["attempts"],
                "legacy_runtime": legacy, "new_runtime": runtime, "resource_guard": guard, "execution_context": context,
                "fresh_seed_audit": seeds, "created_at": timestamp(), "expected_cases": 50,
                "expected_attempts": 150, "truth_arrays_opened": False}
            record["manifest_hash"] = canonical_hash(record)
            # Recheck all sources and files after preparation, before publishing the freeze.
            verify_runtime(config.legacy_runtime, project); verify_runtime(config.new_runtime, project)
            _verify_plan(config, root, project)
            for item in frozen_cases:
                for file in item["input_inventory"]: verify_artifact(file)
            write_json(root / "manifest.json", record)
            status = {"status": "prepared", "expected_cases": 50, "expected_attempts": 150,
                      "manifest_hash": record["manifest_hash"]}
        except NotReady as error:
            status = {"status": "blocked", "error": str(error), "expected_cases": 50,
                      "expected_attempts": 150, "plan_hash": plan["plan_hash"]}
        write_json(root / "preparation-status.json", status)
        return status


def verify_manifest(config, root, project):
    plan = _verify_plan(config, root, project)
    manifest = read_json(root / "manifest.json")
    if manifest.get("manifest_hash") != canonical_hash({k: v for k, v in manifest.items() if k != "manifest_hash"}):
        raise ValueError("Numerical input manifest was modified")
    if manifest["plan_hash"] != plan["plan_hash"] or manifest["attempts"] != plan["attempts"]:
        raise ValueError("Numerical input freeze differs from its case/profile plan")
    if [r["case_id"] for r in manifest["cases"]] != [r["case_id"] for r in plan["cases"]]:
        raise ValueError("Numerical input freeze omitted/reordered a planned case")
    context = artifact(verify_artifact(config.execution_context, project)) if config.execution_context.path else None
    if context != manifest.get("execution_context"):
        raise ValueError("Execution-context identity differs from the frozen manifest")
    fresh_inputs = {}
    for item, planned in zip(manifest["cases"], plan["cases"]):
        if any(item.get(key) != value for key, value in planned.items()):
            raise ValueError("A frozen numerical case differs from its original plan")
        fit = item["fit_request"]
        if fit["method"] != item["method"] or fit["stage"] != item["stage"]:
            raise ValueError("Frozen fit method/stage does not match the planned case")
        if "case" in planned and fit["case"] != planned["case"]:
            raise ValueError("Frozen fit case changed")
        if "parameters" in planned and fit["parameters"] != planned["parameters"]:
            raise ValueError("Frozen statistical parameters changed")
        if canonical_hash(item["input_inventory"]) != item["input_manifest_hash"]:
            raise ValueError("Input manifest signature changed")
        for file in item["input_inventory"]: verify_artifact(file)
        for file in item["lineage"].values(): verify_artifact(file)
        _verify_blind_request(item["fit_request"])
        if item["origin"] == "fresh":
            key = canonical_hash(item["case"])
            if key in fresh_inputs and fresh_inputs[key] != item["input_manifest_hash"]:
                raise ValueError("Prospective methods do not share identical prepared inputs")
            fresh_inputs[key] = item["input_manifest_hash"]
    if verify_runtime(config.legacy_runtime, project) != manifest["legacy_runtime"] or verify_runtime(config.new_runtime, project) != manifest["new_runtime"]:
        raise ValueError("Runtime identity differs from the frozen manifest")
    return manifest


def attempt_job(config, manifest, case, attempt):
    profile = attempt["profile"]
    runtime = manifest["legacy_runtime" if profile == "legacy_v3" else "new_runtime"]
    job = {**case["fit_request"], "id": attempt["attempt_id"], "kind": "fit", "split": "numerics",
        "numerics_profile": profile, "numerics_manifest_hash": manifest["manifest_hash"],
        "input_manifest_hash": case["input_manifest_hash"], "source_hash": runtime["source_sha256"],
        "protocol_hash": manifest["manifest_hash"], "backend": {"groops_executable": runtime["native"]["path"],
            "command_timeout_seconds": 7200., "retain_native_diagnostics": True},
        "expected_native_binary_sha256": runtime["native"]["sha256"]}
    if profile != "legacy_v3": job["numerical_controls"] = asdict(config.controls)
    return job


def verify_checkpoint(directory, job):
    index = read_json(directory / "result-record.json")
    path = verify_artifact(index["result"])
    result = read_json(path)
    if (index["attempt_id"] != job["id"] or index["profile"] != job["numerics_profile"]
            or index["request_hash"] != canonical_hash(job) or read_json(directory / "request.json") != job):
        raise ValueError("Attempt request changed after checkpoint")
    if result.get("request_hash") != index["request_hash"] or result.get("status") != index["status"]:
        raise ValueError("Attempt result/index identity differs")
    for item in result.get("artifacts", []): verify_artifact(item)
    if result.get("status") == "complete": validate_complete_result(result, job)
    return result


def read_cartesian_estimate(item):
    """Validate retained SI trajectory/covariance bytes independently of status flags."""
    import numpy as np
    from zipfile import BadZipFile
    path = verify_artifact(item)
    try:
        with np.load(path, allow_pickle=False) as archive:
            values = {key: np.asarray(archive[key]) for key in ("mjd", "states", "covariance")}
    except (OSError, ValueError, KeyError, TypeError, EOFError, BadZipFile) as error:
        raise ValueError(f"Unreadable Cartesian state/covariance artifact: {error}") from error
    if any(not np.issubdtype(value.dtype, np.number) or np.iscomplexobj(value) for value in values.values()):
        raise ValueError("Cartesian arrays must contain real numeric values")
    epochs, states, covariance = (values[key] for key in ("mjd", "states", "covariance"))
    count = len(epochs) if epochs.ndim else 0
    if count == 0 or epochs.shape != (count,) or np.any(np.diff(epochs) <= 0):
        raise ValueError("State epochs must be nonempty, ordered and unique")
    if states.shape != (count, 6) or covariance.shape != (count, 6, 6):
        raise ValueError("State or covariance shape is not Cartesian 6D")
    if not all(np.isfinite(value).all() for value in values.values()):
        raise ValueError("State or covariance values are nonfinite")
    diagonal = np.diagonal(covariance, axis1=1, axis2=2)
    if np.any(diagonal <= 0) or not np.allclose(covariance, covariance.transpose(0, 2, 1), rtol=1e-9, atol=1e-14):
        raise ValueError("Cartesian covariance has a nonpositive diagonal or is asymmetric")
    sd = np.sqrt(diagonal)
    try:
        np.linalg.cholesky(covariance / sd[:, :, None] / sd[:, None, :])
    except np.linalg.LinAlgError as error:
        raise ValueError("Cartesian covariance is not positive definite") from error
    return values


def validate_complete_result(result, job):
    """A successful process is insufficient to declare a valid posterior."""
    if not validate_fit_result(result):
        raise ValueError("Complete result lacks valid marginalized covariance/convergence")
    for key in ("method", "force_model_hash", "measurement_model_hash"):
        if result.get(key) != job[key]: raise ValueError(f"Complete result differs from its frozen {key}")
    if result.get("native_binary_sha256") != job["expected_native_binary_sha256"]:
        raise ValueError("Complete result used a different native binary")
    if not is_digest(result.get("preprocessing_audit_sha256")):
        raise ValueError("Complete result lacks a frozen native preprocessing audit")
    audit_artifacts = [item for item in result["artifacts"] if item["role"] == "native_preprocessing_audit"]
    if len(audit_artifacts) != 1 or audit_artifacts[0]["sha256"] != result["preprocessing_audit_sha256"]:
        raise ValueError("Native preprocessing audit digest differs from its retained artifact")
    if result.get("metadata", {}).get("reference_inputs_used") is not False:
        raise ValueError("Complete result does not establish reference isolation")
    estimates = [item for item in result["artifacts"] if item["role"] == "state_estimate"]
    if len(estimates) != 1:
        raise ValueError("Complete result must retain exactly one Cartesian state/covariance estimate")
    read_cartesian_estimate(estimates[0])
    if job["numerics_profile"] != "legacy_v3" and not (isinstance(result.get("numerical_diagnostics"), dict)
            or any(item["role"] == "numerical_diagnostics" for item in result["artifacts"])):
        raise ValueError("A new numerical profile must retain its optimization diagnostics")
    return True


def attach_legacy_phase_diagnostic(result, job, directory):
    """Index an existing archived-backend output without changing that runtime."""
    if job["numerics_profile"] != "legacy_v3" or result.get("status") != "complete":
        return
    if any(item["role"] == "phase_recovery" for item in result.get("artifacts", [])):
        return
    try:
        configurations = [item for item in result["artifacts"] if item["role"] == "native_fit_configuration"]
        if len(configurations) != 1:
            raise ValueError("No unique retained native fit configuration")
        tree = ET.parse(verify_artifact(configurations[0]))
        names = {node.text for node in tree.findall(".//outputfilePhaseRecovery") if node.text}
        if len(names) != 1:
            raise ValueError("No unique phase recovery output in the archived configuration")
        date = job["case"].get("date", job["case"].get("epoch", "")[:10])
        name = names.pop().replace("{loopTime:%D}", date).replace("{station}", "gracefo1")
        if "{" in name:
            raise ValueError("Unresolved phase recovery output variables")
        path = Path(name)
        if not path.is_absolute(): path = Path(directory) / path
        path = path.resolve()
        if not path.is_relative_to(Path(directory).resolve()) or not path.is_file():
            raise ValueError("Phase recovery output is missing or outside this isolated attempt")
        result["artifacts"].append({"role": "phase_recovery", **artifact(path),
            "indexed_by": "numerical harness; archived runtime output unchanged"})
        result.setdefault("diagnostic_availability", {})["carrier_phase_predictions"] = "retained"
    except (OSError, KeyError, ValueError, ET.ParseError) as error:
        result.setdefault("diagnostic_availability", {})["carrier_phase_predictions"] = {
            "status": "unavailable", "reason": str(error)}


def run(config, output_dir=None, *, project=None, max_attempts=None):
    config.validate(); project = Path(project or project_root()).resolve()
    if max_attempts is not None and (type(max_attempts) is not int or max_attempts < 0):
        raise ValueError("max_attempts must be a nonnegative integer")
    root = _root(config, output_dir, project); started = 0
    with exclusive(root):
        if not (root / "manifest.json").exists():
            return {"status": "blocked", "error": "Complete input preparation/freeze before any benchmark attempt", "jobs_started": 0}
        manifest = verify_manifest(config, root, project)
        cases = {c["case_id"]: c for c in manifest["cases"]}
        def archive_saved(entry):
            if not config.archive_dir: return
            from .storage import archive_attempt
            directory = root / "attempts" / entry["attempt_id"]
            receipt = root / "archive-index" / (entry["attempt_id"] + ".json")
            try:
                archive_attempt(directory, resolve(config.archive_dir, project), receipt,
                                reserve_bytes=config.resources.reserved_output_bytes)
            except (OSError, ValueError) as error:
                raise NotReady("Terminal attempt archival remains recoverable: " + str(error)) from error
        # Finish any copy/publication interrupted after its terminal checkpoint.
        for entry in manifest["attempts"]:
            receipt = root / "archive-index" / (entry["attempt_id"] + ".json")
            if config.archive_dir and receipt.exists(): archive_saved(entry)
        audits = {}
        # Audit all existing complete profiles even when a new bounded launch
        # stops before reaching their position in the queue.
        for entry in manifest["attempts"]:
            saved_dir = root / "attempts" / entry["attempt_id"]
            if (saved_dir / "result-record.json").exists():
                saved_job = attempt_job(config, manifest, cases[entry["case_id"]], entry)
                saved = verify_checkpoint(saved_dir, saved_job)
                if saved.get("status") == "complete":
                    audit = saved["preprocessing_audit_sha256"]
                    if entry["case_id"] in audits and audits[entry["case_id"]] != audit:
                        raise ValueError("Saved profiles disagree on frozen observation support/weights")
                    audits[entry["case_id"]] = audit
        try:
            for attempt in manifest["attempts"]:
                case = cases[attempt["case_id"]]; job = attempt_job(config, manifest, case, attempt)
                directory = root / "attempts" / attempt["attempt_id"]
                if (directory / "result-record.json").exists():
                    verify_checkpoint(directory, job); archive_saved(attempt); continue
                if directory.exists() and any(directory.iterdir()):
                    raise NotReady("An interrupted attempt has no terminal checkpoint; preserve it and use an explicit recovery review")
                if max_attempts is not None and started >= max_attempts: break
                guard = resource_guard(config.resources, project, root)
                runtime = manifest["legacy_runtime" if attempt["profile"] == "legacy_v3" else "new_runtime"]
                verify_runtime(config.legacy_runtime if attempt["profile"] == "legacy_v3" else config.new_runtime, project)
                _verify_blind_request(job)
                directory.mkdir(parents=True, exist_ok=True)
                write_json(directory / "request.json", job); write_json(directory / "resource-guard.json", guard)
                started += 1
                result = _execute_job(job, directory, runtime, config.resources)
                attach_legacy_phase_diagnostic(result, job, directory)
                if result.get("status") not in TERMINAL:
                    result = {**result, "backend_reported_status": result.get("status"),
                              "backend_error": result.get("error"), "status": "failed", "converged": False, "covariance_valid": False,
                              "error": "Backend returned an unregistered terminal status"}
                if result["status"] == "complete":
                    try:
                        validate_complete_result(result, job)
                        audit = result["preprocessing_audit_sha256"]
                        if case["case_id"] in audits and audits[case["case_id"]] != audit:
                            raise ValueError("Profiles disagree on frozen observation support/weights")
                        audits[case["case_id"]] = audit
                    except (OSError, RuntimeError, ValueError) as error:
                        result.update(status="failed", converged=False, covariance_valid=False,
                            error="Invalid complete result: " + str(error))
                result.update(request_hash=canonical_hash(job), numerics_profile=attempt["profile"],
                    numerics_manifest_hash=manifest["manifest_hash"], input_manifest_hash=case["input_manifest_hash"])
                # A changed input/source invalidates the attempt, never silently creates a new freeze.
                try:
                    _verify_blind_request(job)
                    verify_runtime(config.legacy_runtime if attempt["profile"] == "legacy_v3" else config.new_runtime, project)
                    for item in result.get("artifacts", []): verify_artifact(item)
                except (NotReady, ValueError) as error:
                    result.update(status="failed", converged=False, covariance_valid=False,
                                  error="Post-execution provenance violation: " + str(error))
                from .retention import compact_attempt
                compact_attempt(directory, result, attempt["profile"])
                path = directory / "result.json"; write_json(path, result)
                write_json(directory / "result-record.json", {"attempt_id": attempt["attempt_id"],
                    "case_id": case["case_id"], "profile": attempt["profile"], "status": result["status"],
                    "request_hash": canonical_hash(job), "result": artifact(path)})
                archive_saved(attempt)
            count = sum((root / "attempts" / a["attempt_id"] / "result-record.json").is_file() for a in manifest["attempts"])
            status = {"status": "complete" if count == 150 else "partial", "jobs_started": started,
                      "terminal_attempts": count, "expected_attempts": 150, "manifest_hash": manifest["manifest_hash"]}
        except NotReady as error:
            status = {"status": "blocked", "error": str(error), "jobs_started": started,
                      "expected_attempts": 150, "manifest_hash": manifest["manifest_hash"]}
        write_json(root / "run-status.json", status)
        return status
