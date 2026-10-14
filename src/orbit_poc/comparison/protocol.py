"""Frozen v3 protocol, blind job contracts, and resumable backend orchestration.

Backends do the numerical work. Queued/prepared jobs never certify a scientific
result. Estimation inputs and post-fit evaluation inputs cross separate APIs.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import importlib
import itertools
import json
import math
import os
import platform
import shutil
from pathlib import Path
import time
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Protocol

from .config import ComparisonConfig, METHODS, METHOD_REGISTRY

ESTIMATION_ROLES = frozenset({"gnss_observations", "attitude", "spacecraft_metadata",
    "gnss_orbits", "gnss_clocks", "gnss_biases", "gnss_attitudes", "earth_orientation",
    "space_weather", "force_auxiliary", "bootstrap_orbit"})
EVALUATION_ROLES = frozenset({"truth", "reference_orbit", "slr_validation"})
CALIBRATION_ROLES = frozenset({"heldout_gnss_code"})


class Backend(Protocol):
    def prepare_job(self, job: dict, job_dir: Path) -> dict: ...
    def fit_job(self, job: dict, job_dir: Path) -> dict: ...
    def evaluate_job(self, job: dict, result: dict, job_dir: Path) -> dict: ...


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _file_identity(path):
    info = Path(path).stat()
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@lru_cache(maxsize=16384)
def _hash_unchanged_file(path, identity):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    if _file_identity(path) != identity:
        raise ValueError(f"Artifact changed while hashing: {path}")
    return digest.hexdigest()


def file_hash(path):
    """SHA256 with process-local caching invalidated by file identity/size/times.

    Immutable multi-gigabyte physical models recur in every fit. A new process
    rehashes bytes; every reuse checks inode, size, modification and change times.
    This optimization assumes a trusted filesystem, not an adversary preserving
    metadata while changing bytes.
    """
    path = str(Path(path).resolve())
    return _hash_unchanged_file(path, _file_identity(path))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    temporary.replace(path)


def execution_platform():
    """Public runtime characteristics, excluding hostnames and user identities."""
    import importlib.metadata
    cpu = "unavailable"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        cpu = next((line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
                    if line.startswith("model name")), cpu)
    packages = {}
    for name in ("numpy", "scipy", "gtsam"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {"system": platform.system(), "release": platform.release(),
            "architecture": platform.machine(), "python": platform.python_version(),
            "cpu_model": cpu, "logical_cpus": os.cpu_count(), "packages": packages}


def read_json(path):
    return json.loads(Path(path).read_text())


def read_result_record(record):
    """Load a per-job result only after checking its recorded exact bytes."""
    path, expected = record.get("result_path"), record.get("result_sha256")
    if not path or not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("A compact result record requires its path and SHA256")
    if file_hash(path) != expected:
        raise ValueError(f"Job result bytes changed after checkpoint: {path}")
    result = read_json(path)
    if (result.get("request_hash") != record.get("request_hash") or
            result.get("status") != record.get("status")):
        raise ValueError("Compact result identity/status differs from its stored result")
    return result


def result_record(result):
    """Return the compact, verified index saved alongside a terminal result."""
    path = Path(result["record_path"])
    record = read_json(path.with_name("result-record.json"))
    if record.get("result_path") != str(path) or file_hash(path) != record.get("result_sha256"):
        raise ValueError("Job result bytes changed after checkpoint")
    return record


def source_snapshot(project=None):
    project = Path(project or Path(__file__).resolve().parents[3])
    files = {}
    for directory in ("src", "scripts", "groops/extension", "groops/templates", "configs"):
        for path in sorted((project / directory).rglob("*")):
            if path.is_file() and path.suffix in {".py", ".cpp", ".h", ".hpp", ".sh", ".xml", ".json", ".yaml", ".yml", ".txt"}:
                files[str(path.relative_to(project))] = file_hash(path)
    for name in ("pyproject.toml", "tudat-linux-64.lock.txt", "groops/linux-64.lock.txt",
                 "groops/python-requirements.lock.txt"):
        path = project / name
        if path.is_file():
            files[name] = file_hash(path)
    return {"sha256": canonical_hash(files), "files": files}


def freeze_protocol(config, output_dir):
    config.validate()
    executable = shutil.which(config.backend.groops_executable)
    native = ({"path": str(Path(executable).resolve()), "sha256": file_hash(executable)}
              if executable is not None else None)
    record = {"schema_version": 3, "config": asdict(config), "source": source_snapshot(),
              "native_binary": native}
    record["protocol_hash"] = canonical_hash(record)
    path = Path(output_dir) / "protocol.json"
    if path.exists() and canonical_hash(read_json(path)) != canonical_hash(record):
        raise ValueError("Frozen protocol/source differs; use a new output directory")
    if not path.exists():
        write_json(path, record)
    return record


def artifact_record(role, path, **metadata):
    path = Path(path).resolve()
    return {"role": role, "path": str(path), "sha256": file_hash(path), **metadata}


def _verify_artifacts(records, allowed=None):
    if not isinstance(records, list) or not records:
        raise ValueError("Verified artifact records are required")
    for item in records:
        if not isinstance(item, dict) or not {"role", "path", "sha256"} <= item.keys():
            raise ValueError("Artifacts require role, path, and sha256")
        if allowed is not None and item["role"] not in allowed:
            raise ValueError(f"Disallowed estimation/evaluation role: {item['role']}")
        path = Path(item["path"])
        if not path.is_file() or file_hash(path) != item["sha256"]:
            raise ValueError(f"Missing or modified artifact: {path}")


def validate_estimation_inputs(records, *, flight=False):
    _verify_artifacts(records, ESTIMATION_ROLES)
    required = {"gnss_observations", "gnss_orbits", "gnss_clocks", "bootstrap_orbit"}
    if flight:
        required |= {"attitude", "spacecraft_metadata", "earth_orientation", "force_auxiliary"}
    if not required <= {item["role"] for item in records}:
        raise ValueError("Required blind GNSS/bootstrap/force inputs are missing")
    for item in records:
        name = Path(item["path"]).name.lower()
        if name.startswith(("gnv", "truth", "reference_orbit")):
            raise ValueError("Truth/GNV/reference products cannot enter estimation")
        if item["role"] == "bootstrap_orbit":
            origin = item.get("provenance", item.get("metadata", {}).get("provenance"))
            if origin != "gnss_only":
                raise ValueError("Bootstrap must carry verified GNSS-only provenance")


def validate_prepared(record, job):
    if record.get("status") != "prepared":
        return False
    validate_estimation_inputs(record.get("estimation_inputs"), flight=job["stage"] == "flight")
    if record.get("evaluation_inputs"):
        _verify_artifacts(record["evaluation_inputs"], EVALUATION_ROLES)
    if job["split"] == "calibration":
        _verify_artifacts(record.get("calibration_inputs"), CALIBRATION_ROLES)
    for name in ("force_model_hash", "measurement_model_hash", "preprocessing_hash"):
        value = record.get(name)
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"Prepared input must record {name} as SHA256")
    if record.get("mask_hash") != canonical_hash(job["case"].get("mask", {})):
        raise ValueError("Prepared bootstrap/preprocessing does not match requested mask")
    return True


def validate_fit_result(record, *, calibration=False):
    if record.get("status") != "complete":
        return False
    _verify_artifacts(record.get("artifacts"))
    if record.get("covariance_scope") != "marginalized":
        raise ValueError("Orbit covariance must marginalize dynamic, clock, and ambiguity parameters")
    if not isinstance(record.get("parameter_blocks"), list) or not record["parameter_blocks"]:
        raise ValueError("Fitted parameter blocks must be declared")
    valid = record.get("converged") is True and record.get("covariance_valid") is True
    if calibration and valid:
        valid = valid_calibration_score(record.get("calibration_score", {}))
    return bool(valid)


def valid_calibration_score(score):
    return (score.get("valid") is True and isinstance(score.get("mean_nll"), (int, float))
            and not isinstance(score.get("mean_nll"), bool) and math.isfinite(score["mean_nll"])
            and score.get("retained_dimensions", 0) > 0)


def initial_candidates(config, method):
    if method == "groops_pulses":
        return [{"interval_seconds": dt, "sigma_velocity_m_s": sigma, "frame": "CRF"}
                for dt, sigma in itertools.product(config.pulses.intervals_seconds, config.pulses.sigma_velocity_m_s)]
    if method == "groops_log_drag_ou":
        return [{"knot_seconds": config.density.knot_seconds, "tau_seconds": tau,
                 "sigma_log_density": sigma, "interpolation": "linear_log_density",
                 "initial_prior": "stationary_ou", "empirical_acceleration": False}
                for tau, sigma in itertools.product(config.density.tau_seconds, config.density.sigma_log_density)]
    raise ValueError(f"Unregistered method: {method}")


def expand_candidates(method, candidates, scores, tolerance=1e-6):
    """Shift each improving boundary by one grid interval; retain four per axis.

    Returns a full next grid and diagnostics. Hard limits prevent nonsensical
    knot/pulse spacing; reaching one leaves the comparison unresolved.
    """
    axes = (("interval_seconds", 60., 14400.), ("sigma_velocity_m_s", 1e-8, 1.)) if method == "groops_pulses" else (
        ("tau_seconds", 60., 86400.), ("sigma_log_density", 1e-4, 3.))
    eligible = [(p, scores.get(canonical_hash(p))) for p in candidates]
    eligible = [(p, score) for p, score in eligible if score is not None and math.isfinite(score)]
    if not eligible:
        return [], {"adequate": False, "reason": "No candidate has all required valid arcs", "boundaries": []}
    winner, best = min(eligible, key=lambda pair: pair[1])
    axis_values, diagnoses = [], []
    for key, lower, upper in axes:
        values = sorted({p[key] for p in candidates})
        profile = {v: min((score for p, score in eligible if p[key] == v), default=math.inf) for v in values}
        chosen = winner[key]
        edge = "lower" if chosen == values[0] else "upper" if chosen == values[-1] else "interior"
        neighbor = values[1] if edge == "lower" else values[-2] if edge == "upper" else chosen
        improving = edge != "interior" and profile[neighbor] - best > tolerance
        revised = values[:]
        if improving:
            if edge == "lower":
                revised = [max(lower, values[0] ** 2 / values[1]), *values[:-1]]
            else:
                revised = [*values[1:], min(upper, values[-1] ** 2 / values[-2])]
        limited = len(set(revised)) != len(values)
        if limited:
            revised = values
        diagnoses.append({"parameter": key, "selected": chosen, "edge": edge,
                          "improving": improving, "hard_limit": limited,
                          "profile": [{"value": v, "mean_nll": profile[v] if math.isfinite(profile[v]) else None} for v in values]})
        axis_values.append(revised)
    next_grid = [{**winner, axes[0][0]: a, axes[1][0]: b} for a, b in itertools.product(*axis_values)]
    return next_grid, {"adequate": not any(d["improving"] for d in diagnoses), "boundaries": diagnoses,
                       "winner": winner, "mean_nll": best}


def case_matrix(config, stage, split):
    if stage not in {"synthetic", "flight"} or split not in {"calibration", "evaluation"}:
        raise ValueError("Unknown comparison stage/split")
    calibration = split == "calibration"
    cases = []
    if stage == "synthetic":
        s = config.synthetic
        rows = ([(orbit, "quiet" if index % 2 == 0 else "disturbed", "normal", seed)
                 for orbit in s.orbits for index, seed in enumerate(s.calibration_seeds)]
                if calibration else itertools.product(s.orbits, s.atmospheres, s.coverages, s.evaluation_seeds))
        for orbit, atmosphere, coverage, seed in rows:
            cases.append({"orbit": orbit, "atmosphere": atmosphere, "coverage": coverage, "seed": seed,
                          "duration_hours": s.duration_hours, "cadence": s.cadence_seconds,
                          "epoch": s.epoch, "truth_model": s.truth_model,
                          "arc_id": f"{orbit}-{seed}"})
        gap, scale, cadence = s.blackout_hours, "elapsed", s.cadence_seconds
    else:
        f = config.flight
        dates = f.development_dates if calibration else f.evaluation_dates
        coverages = ("normal",) if calibration else f.coverages
        cases = [{"spacecraft": f.spacecraft, "date": date, "coverage": coverage,
                  "duration_hours": 24.0, "cadence": 30.0, "ambiguity_policy": f.ambiguity_policy,
                  "force_recipe": f.force_recipe, "bootstrap": f.bootstrap,
                  "arc_id": f"{f.spacecraft}-{date}"}
                 for date, coverage in itertools.product(dates, coverages)]
        gap, scale, cadence = f.blackout_hours, "UTC", 30
    number = lambda x: int(x) if float(x).is_integer() else float(x)
    variants = config.tuning.holdout_blocks_hours if calibration else (gap,)
    return [{**case, **({"holdout_minutes": number(60 * (bounds[1] - bounds[0]))} if calibration else {}),
             "mask": {"intervals_seconds": [[number(3600 * h) for h in bounds]]
                      if calibration or case["coverage"] == "blackout" else [],
                      "cadence_seconds": number(cadence), "time_scale": scale}}
            for case in cases for bounds in variants]


def _job(frozen, stage, split, kind, case, **extra):
    record = {"kind": kind, "stage": stage, "split": split, "case": case,
              "protocol_hash": frozen["protocol_hash"], "source_hash": frozen["source"]["sha256"],
              "backend": frozen["config"]["backend"],
              "expected_native_binary_sha256": (frozen.get("native_binary") or {}).get("sha256"), **extra}
    record["id"] = f"{stage}-{split}-{kind}-{canonical_hash(record)[:20]}"
    return record


class BudgetExhausted(Exception):
    pass


class BackendBlocked(Exception):
    pass


class Runner:
    def __init__(self, output_dir, backend=None, *, max_jobs=None, budget_hours=12., resume=True, workers=1):
        if max_jobs is not None and (isinstance(max_jobs, bool) or max_jobs < 0):
            raise ValueError("max_jobs must be nonnegative")
        if not math.isfinite(budget_hours) or budget_hours <= 0:
            raise ValueError("budget_hours must be finite and positive")
        if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1:
            raise ValueError("workers must be a positive integer")
        self.root, self.backend = Path(output_dir).resolve(), backend
        self.maximum, self.deadline = max_jobs, time.monotonic() + 3600 * budget_hours
        self.started, self.resume, self.records = 0, resume, []
        self.workers, self.lock = workers, Lock()
        self.preprocessing_audits = {}
        self.predictive_support_audits = {}

    def map(self, function, items):
        if self.workers == 1:
            yield from map(function, items)
        else:
            # Only numerical jobs use this map. Preparation remains sequential
            # because native product caches and downloads can be shared.
            with ThreadPoolExecutor(max_workers=self.workers) as pool:
                yield from pool.map(function, items)

    def execute(self, job):
        directory = self.root / "jobs" / job["id"]
        request_path, result_path = directory / "request.json", directory / "result.json"
        index_path = directory / "result-record.json"
        fingerprint = canonical_hash(job)
        write_json(request_path, job)
        if self.resume and result_path.exists():
            index = read_json(index_path) if index_path.is_file() else None
            cached = read_result_record(index) if index is not None else read_json(result_path)
            if cached.get("request_hash") != fingerprint:
                raise ValueError("Job request hash differs from checkpoint")
            if index is not None and (index.get("id") != job["id"] or index.get("request_hash") != fingerprint):
                raise ValueError("Compact job index differs from checkpoint request")
            if cached.get("status") in {"prepared", "complete", "failed", "excluded"} or (
                    job["kind"] == "evaluate" and cached.get("status") == "incomplete"):
                if index is None:
                    raise ValueError("Terminal job result lacks its saved SHA256 index; it cannot be safely resumed")
                self._validate(cached, job)
                self.records.append(index)
                return cached
        # A queued/running/blocked job may be retried, but its previous bytes
        # were verified above before replacing the incomplete checkpoint.
        index_path.unlink(missing_ok=True)
        with self.lock:
            if (self.maximum is not None and self.started >= self.maximum) or time.monotonic() >= self.deadline:
                write_json(result_path, {"status": "queued", "request_hash": fingerprint})
                raise BudgetExhausted("No further backend job started within this invocation's budget")
            self.started += 1
        started = time.monotonic()
        write_json(result_path, {"status": "running", "request_hash": fingerprint})
        try:
            backend = self.backend or importlib.import_module("orbit_poc.comparison.backend")
            function = getattr(backend, job["kind"] + "_job")
            if job["kind"] == "evaluate":
                result = function(job, job["fit_result"], directory)
            else:
                result = function(job, directory)
            if not isinstance(result, dict) or result.get("status") not in {"prepared", "complete", "blocked", "failed", "excluded", "incomplete"}:
                raise ValueError("Backend must return an explicit prepared/complete/blocked/failed result")
            self._validate(result, job)
        except (ImportError, AttributeError) as error:
            result = {"status": "blocked", "error": f"Backend unavailable: {error}"}
        except Exception as error:
            result = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        result = {**result, "request_hash": fingerprint, "elapsed_seconds": time.monotonic() - started,
                  "record_path": str(result_path), "concurrent_workers": self.workers}
        write_json(result_path, result)
        index = {"schema_version": 1, "id": job["id"], "kind": job["kind"],
                 "stage": job.get("stage"), "split": job.get("split"), "method": job.get("method"),
                 "request_hash": fingerprint, "result_path": str(result_path),
                 "result_sha256": file_hash(result_path),
                 **{key: result[key] for key in ("status", "elapsed_seconds", "peak_rss_bytes",
                    "converged", "covariance_valid", "error", "reason") if key in result}}
        write_json(index_path, index)
        self.records.append(index)
        if result["status"] == "blocked":
            raise BackendBlocked(result.get("error", "Backend preparation is blocked"))
        return result

    @staticmethod
    def _validate(result, job):
        if result.get("status") == "incomplete":
            if job["kind"] != "evaluate" or job["stage"] != "flight" or not isinstance(result.get("metrics"), dict):
                raise ValueError("Incomplete numerical output is reserved for flight evaluation with explicit unavailable metrics")
            _verify_artifacts(result.get("artifacts"))
            return
        if job["kind"] == "prepare":
            if result.get("status") == "complete":
                raise ValueError("Data preparation cannot claim scientific completion")
            if result.get("status") == "excluded":
                if not result.get("reason") or job["stage"] != "flight":
                    raise ValueError("Only fixed, metadata-screened flight exclusions are supported")
                _verify_artifacts(result.get("artifacts"))
                return
            validate_prepared(result, job)
        elif job["kind"] == "fit":
            if result.get("status") == "prepared":
                raise ValueError("Fit backend cannot return a preparation status")
            validate_fit_result(result)
        elif result.get("status") == "complete":
            _verify_artifacts(result.get("artifacts"))
            if job["split"] == "calibration":
                if not valid_calibration_score(result.get("calibration_score", {})):
                    raise ValueError("Calibration evaluation requires a finite informative projected-code score")
            elif not isinstance(result.get("metrics"), dict):
                raise ValueError("Completed evaluation requires metrics")
        elif result.get("status") == "prepared":
            raise ValueError("Evaluation cannot return a preparation status")


def _prepared(runner, frozen, stage, split, case, frozen_evaluation=False):
    job = _job(frozen, stage, split, "prepare", case, frozen_evaluation=frozen_evaluation)
    result = runner.execute(job)
    if result.get("status") == "excluded":
        return result
    if not validate_prepared(result, job):
        raise BackendBlocked(result.get("error", "Required input preparation failed"))
    return result


def _fit(runner, frozen, stage, split, case, prepared, method, parameters):
    # Intentionally reconstruct the request from an allowlist: the complete
    # prepared record contains evaluation-only files and must never be forwarded.
    job = _job(frozen, stage, split, "fit", case, method=method, parameters=parameters,
        estimation_inputs=prepared["estimation_inputs"], calibration=split == "calibration",
        force_model_hash=prepared["force_model_hash"], measurement_model_hash=prepared["measurement_model_hash"],
        preprocessing_hash=prepared["preprocessing_hash"], mask_hash=prepared["mask_hash"])
    validate_estimation_inputs(job["estimation_inputs"], flight=stage == "flight")
    result = runner.execute(job)
    if result.get("status") == "complete" and result.get("native_binary_sha256") and method in METHODS:
        audit = result.get("preprocessing_audit_sha256")
        legacy_audit = result.get("metadata", {}).get("preprocessing_audit_sha256")
        if "preprocessing_audit_sha256" not in result:
            audit = legacy_audit
        elif legacy_audit is not None and legacy_audit != audit:
            raise BackendBlocked("Conflicting top-level and metadata preprocessing audits")
        if not isinstance(audit, str) or len(audit) != 64 or any(c not in "0123456789abcdef" for c in audit):
            raise BackendBlocked("A complete primary native fit requires a retained-observation/weight preprocessing audit")
        key = canonical_hash({"stage": stage, "split": split, "case": case})
        with runner.lock:
            previous = runner.preprocessing_audits.setdefault(key, audit)
        if previous != audit:
            raise BackendBlocked("Common preprocessing differs across primary methods or tuning candidates; comparison is blocked")
    return result


def _selection_payload(record):
    return {name: record[name] for name in ("protocol_hash", "selections", "evidence",
            "calibration_adequate", "calibration_disclosures", "boundary_diagnostics")}


def _check_predictive_support(runner, stage, case, prepared, result):
    """A candidate must score exactly the same held-out observations as its peers."""
    support = result.get("predictive_support_sha256")
    if not isinstance(support, str) or len(support) != 64 or any(c not in "0123456789abcdef" for c in support):
        raise BackendBlocked("A complete calibration score requires verified predictive support")
    key = canonical_hash({"stage": stage, "case": case,
                          "calibration_inputs": [(item["role"], item["sha256"])
                                                 for item in prepared["calibration_inputs"]]})
    with runner.lock:
        previous = runner.predictive_support_audits.setdefault(key, support)
    if previous != support:
        raise BackendBlocked("Held-out predictive support differs across methods or tuning candidates; calibration is blocked")


def _selection(config, root, frozen, stage):
    path = Path(root) / f"calibration-{stage}.json"
    if not path.exists():
        raise ValueError("Complete and freeze calibration before evaluation")
    record = read_json(path)
    if not record.get("complete") or record.get("protocol_hash") != frozen["protocol_hash"]:
        raise ValueError("Calibration is incomplete or belongs to another frozen protocol")
    payload = _selection_payload(record)
    if record.get("selection_hash") != canonical_hash(payload):
        raise ValueError("Frozen calibration selection has been modified")
    for evidence in record["evidence"]:
        if file_hash(evidence["path"]) != evidence["sha256"]:
            raise ValueError("Calibration evidence changed after selection")
        result = read_json(evidence["path"])
        for key in ("artifacts", "estimation_inputs", "calibration_inputs", "evaluation_inputs"):
            if result.get(key):
                _verify_artifacts(result[key])
    return record


def _manifest(kind, stage, frozen):
    return {"schema_version": 3, "kind": kind, "stage": stage, "protocol_hash": frozen["protocol_hash"],
            "source_hash": frozen["source"]["sha256"], "methods": list(METHODS),
            "primary_cell": list(frozen["config"]["primary_cell"]),
            "status": "running", "complete": False, "runs": []}


def _finish(record, runner, path):
    record["jobs"] = list(runner.records)
    record["jobs_started"] = runner.started
    record["concurrent_workers"] = runner.workers
    record["execution_platform"] = execution_platform()
    write_json(path, record)
    return record


def prepare(config, output_dir=None, *, stage="synthetic", split="calibration", **options):
    root = Path(output_dir or config.output_dir)
    frozen = freeze_protocol(config, root)
    if split == "evaluation":
        _selection(config, root, frozen, stage)
    runner = Runner(root, **options)
    manifest = _manifest("prepare", stage, frozen)
    cases = case_matrix(config, stage, split)
    manifest["expected_jobs"] = len(cases)
    try:
        for case in cases:
            result = _prepared(runner, frozen, stage, split, case, split == "evaluation")
            manifest["runs"].append({"case": case, "status": result["status"]})
        manifest.update(status="prepared", inputs_prepared=all(row["status"] == "prepared" for row in manifest["runs"]),
                        excluded_cases=sum(row["status"] == "excluded" for row in manifest["runs"]))
    except (BudgetExhausted, BackendBlocked) as error:
        manifest.update(status="incomplete" if isinstance(error, BudgetExhausted) else "blocked", error=str(error))
    # complete deliberately remains False: preparation is not an experiment.
    return _finish(manifest, runner, root / f"prepare-{stage}-{split}.json")


def calibrate(config, output_dir=None, *, stage="synthetic", **options):
    root = Path(output_dir or config.output_dir)
    frozen = freeze_protocol(config, root)
    from .gates import validate_gates
    acceptance = validate_gates(root, frozen)
    runner = Runner(root, **options)
    manifest = _manifest("calibration", stage, frozen)
    manifest["gates"] = acceptance["gates"]
    manifest["acceptance_evidence_hash"] = acceptance["evidence_hash"]
    manifest.update(selections={}, boundary_diagnostics={}, evidence=[], calibration_adequate=False,
                    calibration_disclosures=[],
                    score_weighting="equal across 30-minute and 2-hour holdouts within each arc, then equal across six independent arcs")
    cases = case_matrix(config, stage, "calibration")
    groups = sorted({case.get("orbit", case.get("spacecraft")) for case in cases})
    path = root / f"calibration-{stage}.json"
    try:
        for group in groups:
            arcs = [c for c in cases if c.get("orbit", c.get("spacecraft")) == group]
            prepared = [_prepared(runner, frozen, stage, "calibration", case) for case in arcs]
            manifest["selections"][group], manifest["boundary_diagnostics"][group] = {}, {}
            for method in METHODS:
                candidates = initial_candidates(config, method)
                round_diagnostics = []
                for expansion in range(config.tuning.boundary_expansion_rounds + 1):
                    scores = {}
                    candidate_arcs = {canonical_hash(parameters): {} for parameters in candidates}
                    def score_arc(item):
                        parameters, case, data = item
                        if data.get("status") == "excluded":
                            return {"case": case, "method": method, "parameters": parameters,
                                "expansion_round": expansion, "status": "excluded", "valid": False,
                                "reason": data["reason"], "screening": data.get("screening"), "score": None}
                        result = _fit(runner, frozen, stage, "calibration", case, data, method, parameters)
                        valid = validate_fit_result(result)
                        score = None
                        scored_result = result
                        evaluation_status = "not_run"
                        error = result.get("error")
                        if valid:
                            evaluation = _job(frozen, stage, "calibration", "evaluate", case,
                                method=method, fit_result=result,
                                calibration_inputs=data["calibration_inputs"])
                            scored_result = runner.execute(evaluation)
                            if scored_result.get("status") == "complete":
                                _check_predictive_support(runner, stage, case, data, scored_result)
                            evaluation_status = scored_result["status"]
                            error = scored_result.get("error")
                            score = scored_result.get("calibration_score")
                            valid = scored_result.get("status") == "complete" and valid_calibration_score(score or {})
                        return {"case": case, "method": method, "parameters": parameters,
                                "expansion_round": expansion, "status": result["status"], "valid": valid,
                                "evaluation_status": evaluation_status, "error": error,
                                "score": score, "result_path": scored_result["record_path"],
                                "result_record": result_record(scored_result)}
                    # Queue one entire expansion round so workers can span
                    # candidates. map yields the original candidate/arc order,
                    # preserving deterministic histories and tie-breaking.
                    work = ((parameters, case, data) for parameters in candidates
                            for case, data in zip(arcs, prepared))
                    for row in runner.map(score_arc, work):
                        manifest["runs"].append(row)
                        if row["valid"]:
                            arc_scores = candidate_arcs[canonical_hash(row["parameters"])]
                            case = row["case"]
                            arc_scores.setdefault(case["arc_id"], {})[case["holdout_minutes"]] = row["score"]["mean_nll"]
                    for parameters in candidates:
                        arc_scores = candidate_arcs[canonical_hash(parameters)]
                        complete_arcs = [sum(values.values()) / len(values) for values in arc_scores.values()
                                         if set(values) == {30, 120}]
                        scores[canonical_hash(parameters)] = (sum(complete_arcs) / len(complete_arcs)
                            if len(complete_arcs) == config.tuning.minimum_valid_arcs else None)
                    next_candidates, diagnosis = expand_candidates(method, candidates, scores, config.tuning.boundary_improvement_nats)
                    diagnosis["expansion_round"] = expansion
                    round_diagnostics.append(diagnosis)
                    manifest["boundary_diagnostics"][group][method] = diagnosis
                    if diagnosis["adequate"]:
                        break
                    if not next_candidates or next_candidates == candidates:
                        break
                    candidates = next_candidates
                    _finish(manifest, runner, path)
                eligible = [item for item in round_diagnostics if "winner" in item]
                if eligible:
                    # A finite search limit restricts claims, but does not discard
                    # a candidate scored on every required independent arc.
                    chosen = min(eligible, key=lambda item: (item["mean_nll"], not item["adequate"]))
                    manifest["selections"][group][method] = chosen["winner"]
                    diagnosis = {**diagnosis, "selected_parameters": chosen["winner"],
                        "selected_mean_nll": chosen["mean_nll"], "round_history": round_diagnostics,
                        "adequate": bool(diagnosis["adequate"] and diagnosis["winner"] == chosen["winner"])}
                    manifest["boundary_diagnostics"][group][method] = diagnosis
                    if not diagnosis["adequate"]:
                        manifest["calibration_disclosures"].append({"group": group, "method": method,
                            "reason": "Improving boundary or incomplete expanded grid remains after the allowed search",
                            "claim_restriction": "Results describe the tested tuning range; withhold method-superiority claims"})
        complete = all(len(manifest["selections"].get(group, {})) == len(METHODS) for group in groups)
        adequate = complete and not manifest["calibration_disclosures"]
        manifest.update(complete=complete, calibration_adequate=adequate,
                        status=("complete" if adequate else "complete_boundary_limited") if complete else "inconclusive_calibration")
        if complete:
            evidence_paths = sorted({r["result_path"] for r in runner.records})
            manifest["evidence"] = [{"path": p, "sha256": file_hash(p)} for p in evidence_paths]
            manifest["selection_hash"] = canonical_hash(_selection_payload(manifest))
    except (BudgetExhausted, BackendBlocked) as error:
        manifest.update(status="incomplete" if isinstance(error, BudgetExhausted) else "blocked", error=str(error))
    return _finish(manifest, runner, path)


def run(config, output_dir=None, *, stage="synthetic", campaign="primary", **options):
    root = Path(output_dir or config.output_dir)
    frozen = freeze_protocol(config, root)
    selection = _selection(config, root, frozen, stage)
    from .gates import validate_gates
    acceptance = validate_gates(root, frozen)
    if campaign not in {"primary", "stress", "flight_ar_reference"}:
        raise ValueError("Unknown campaign")
    if campaign == "stress" and stage != "synthetic" or campaign == "flight_ar_reference" and stage != "flight":
        raise ValueError("Secondary campaign does not belong to the requested stage")
    runner = Runner(root, **options)
    manifest = _manifest("evaluation", stage, frozen)
    manifest["gates"] = {**acceptance["gates"], "calibration_freeze": {
        "passed": True, "selection_hash": selection["selection_hash"],
        "calibration_adequate": selection["calibration_adequate"],
        "conditional_covariance": "Selected hyperparameters; excludes model-selection uncertainty"}}
    manifest["acceptance_evidence_hash"] = acceptance["evidence_hash"]
    manifest.update(campaign=campaign, primary=campaign == "primary")
    manifest["selection_hash"] = selection["selection_hash"]
    manifest["calibration_adequate"] = selection["calibration_adequate"]
    manifest["calibration_disclosures"] = selection["calibration_disclosures"]
    cases = case_matrix(config, stage, "evaluation")
    methods = METHODS
    if campaign == "stress":
        cases = [{**case, "seed": 500000 + case["seed"] - config.synthetic.evaluation_seeds[0], "truth_model": "tudat_mixed_force_stress_gnss"}
                 for case in cases if case["orbit"] == "leo500"
                 and case["atmosphere"] == "disturbed" and case["seed"] in config.synthetic.evaluation_seeds[:5]]
    elif campaign == "flight_ar_reference":
        cases = [{**case, "ambiguity_policy": "integer"} for case in cases if case["coverage"] == "normal"]
        methods = ("groops_pulses_ar",)
    manifest["methods"] = list(methods)
    manifest["planned_cases"] = cases
    manifest["expected_fits"] = len(cases) * len(methods)
    output_name = f"run-{stage}" if campaign == "primary" else f"run-{campaign}"
    def run_case(item):
        case, prepared = item
        rows = []
        group = case.get("orbit", case.get("spacecraft"))
        for method in methods:
            if prepared.get("status") == "excluded":
                rows.append({"case": case, "method": method, "status": "excluded", "valid": False,
                    "error": prepared["reason"], "screening": prepared.get("screening"),
                    "fit_record": result_record(prepared)})
                continue
            parameters = ({"recipe": "official_native_ar"} if method == "groops_pulses_ar" else
                          selection["selections"][group][method])
            fitted = _fit(runner, frozen, stage, "evaluation", case, prepared, method, parameters)
            valid = validate_fit_result(fitted)
            row = {"case": case, "method": method, "parameters": parameters, "fit_record": result_record(fitted),
                   "status": fitted["status"], "valid": valid, "result_path": fitted["record_path"]}
            if valid:
                evaluation_job = _job(frozen, stage, "evaluation", "evaluate", case, method=method,
                    fit_result=fitted, evaluation_inputs=prepared.get("evaluation_inputs", []), frozen_evaluation=True)
                evaluated = runner.execute(evaluation_job)
                row.update(evaluation_record=result_record(evaluated),
                           valid=evaluated.get("status") == "complete")
            rows.append(row)
        return rows
    try:
        for start in range(0, len(cases), runner.workers):
            batch = cases[start:start+runner.workers]
            prepared = [_prepared(runner, frozen, stage, "evaluation", case, True) for case in batch]
            for rows in runner.map(run_case, zip(batch, prepared)):
                manifest["runs"].extend(rows)
                _finish(manifest, runner, root / f"{output_name}.json")
        complete = len(manifest["runs"]) == manifest["expected_fits"]
        manifest.update(complete=complete, all_fits_valid=complete and all(r["valid"] for r in manifest["runs"]),
                        status="complete" if complete else "incomplete")
        manifest["scientific_acceptance"] = "requires_reported_accuracy_and_uncertainty_checks"
    except (BudgetExhausted, BackendBlocked) as error:
        manifest.update(status="incomplete" if isinstance(error, BudgetExhausted) else "blocked", error=str(error))
    return _finish(manifest, runner, root / f"{output_name}.json")


def report(config, output_dir=None, *, stage="synthetic", campaign="primary"):
    root = Path(output_dir or config.output_dir)
    frozen = freeze_protocol(config, root)
    name = stage if campaign == "primary" else campaign
    path = root / f"run-{name}.json"
    manifest = read_json(path) if path.exists() else _manifest("evaluation", stage, frozen)
    calibration = None
    if path.exists():
        if (manifest.get("protocol_hash") != frozen["protocol_hash"] or
                manifest.get("source_hash") != frozen["source"]["sha256"]):
            raise ValueError("Run report belongs to another protocol/source snapshot")
        if manifest.get("stage") != stage or manifest.get("campaign") != campaign:
            raise ValueError("Run report belongs to another stage/campaign")
        # Every evaluation, including a partial run, starts from a completed
        # frozen selection. Verify its evidence before combining report inputs.
        calibration = _selection(config, root, frozen, stage)
        if manifest.get("selection_hash") != calibration["selection_hash"]:
            raise ValueError("Run report uses another frozen calibration selection")
    else:
        manifest.update(status="not_run", complete=False)
        from .gates import read_gates
        manifest["gates"] = read_gates(root).get("gates", {})
    calibration_path = root / f"calibration-{stage}.json"
    if calibration_path.exists():
        calibration = calibration or read_json(calibration_path)
        if (calibration.get("protocol_hash") != frozen["protocol_hash"] or
                calibration.get("source_hash") != frozen["source"]["sha256"]):
            raise ValueError("Calibration report belongs to another protocol/source snapshot")
        if calibration.get("complete") and calibration.get("selection_hash") != canonical_hash(_selection_payload(calibration)):
            raise ValueError("Frozen calibration selection has been modified")
        manifest["calibration"] = {key: calibration.get(key) for key in (
            "status", "complete", "selection_hash", "calibration_adequate", "selections",
            "boundary_diagnostics", "calibration_disclosures", "score_weighting", "runs")}
    from .report import create_report
    return create_report(manifest, root / f"report-{name}")
