"""Blind native GROOPS execution and separately authorized post-fit evaluation.

Preparation, estimation and evaluation have distinct interfaces. No truth,
reference orbit or held-out observation path is forwarded to ``fit_job``.
All numerical fits invoke the configured native executable; preparation alone
never produces a fitted result.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np

from .density import density_knots
from .metrics import aggregate_clock_scores, clock_nullspace_nll, position_metrics, flight_residual_metrics
from .protocol import artifact_record, canonical_hash, file_hash, read_json, write_json, validate_estimation_inputs


class NativeExecutionError(RuntimeError):
    def __init__(self, message, execution=None):
        super().__init__(message)
        self.execution = execution


def _binary(job):
    if "expected_native_binary_sha256" in job and job["expected_native_binary_sha256"] is None:
        raise FileNotFoundError("Protocol was frozen without a native executable; create a new freeze after installation")
    requested = str(job.get("backend", {}).get("groops_executable", "groops"))
    found = shutil.which(requested)
    if found is None or not os.access(found, os.X_OK):
        raise FileNotFoundError(f"Native GROOPS executable is unavailable: {requested}")
    binary = Path(found).resolve()
    if ("expected_native_binary_sha256" in job and
            file_hash(binary) != job["expected_native_binary_sha256"]):
        raise ValueError("Native executable SHA256 differs from the frozen protocol")
    return binary


def run_native(binary, config, output_dir, label, *, timeout=3600.0, threads=1):
    """Execute a genuine native command with bounded lifetime and measured RSS."""
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    log = output_dir / f"{label}.log"
    command = [str(Path(binary).resolve()), str(Path(config).resolve())]
    if not np.isfinite(timeout) or timeout <= 0:
        raise ValueError("A positive finite native command timeout is required")
    if isinstance(threads, bool) or int(threads) != threads or threads < 1:
        raise ValueError("Native BLAS/OpenMP thread count must be a positive integer")
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS=str(threads), OMP_NUM_THREADS=str(threads))
    binary_sha = file_hash(binary)
    start = time.monotonic()
    peak_rss = 0
    timed_out = False
    with log.open("w") as stream:
        process = subprocess.Popen(command, cwd=output_dir, env=environment, stdout=stream, stderr=subprocess.STDOUT)
        while process.poll() is None:
            try:
                status = Path(f"/proc/{process.pid}/status").read_text()
                for line in status.splitlines():
                    if line.startswith(("VmHWM:", "VmRSS:")):
                        peak_rss = max(peak_rss, int(line.split()[1]) * 1024)
            except (FileNotFoundError, ProcessLookupError):
                pass
            if time.monotonic() - start >= timeout:
                timed_out = True
                process.kill()
                break
            time.sleep(0.05)
        code = process.wait()
    record = {"command": command, "pid": process.pid, "returncode": code,
              "timed_out": timed_out, "elapsed_seconds": time.monotonic() - start,
              "peak_rss_bytes": peak_rss, "memory_measurement": "Linux process VmHWM/VmRSS sampled at50ms; serial native process",
              "log": str(log), "config_sha256": file_hash(config)}
    record.update(native_binary_sha256=binary_sha, blas_openmp_threads=int(threads))
    write_json(output_dir / f"{label}.execution.json", record)
    if timed_out or code:
        raise NativeExecutionError(f"Native {label} {'timed out' if timed_out else 'exited '+str(code)}; see {log}", execution=record)
    return record


def read_native_table(path, columns=None):
    """Read numeric rows from GROOPS ASCII matrix/instrument files, not binary .dat."""
    path = Path(path)
    if path.suffix.lower() == ".dat":
        raise ValueError("Convert native binary artifacts to ASCII before numerical inspection")
    rows = []
    for line in path.read_text().splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        try:
            values = [float(word.replace("D", "E").replace("d", "e")) for word in text.split()]
        except ValueError:
            continue
        if columns is None or len(values) == columns:
            rows.append(values)
    if not rows or any(len(row) != len(rows[0]) for row in rows):
        raise ValueError(f"No consistent numeric table in {path}")
    result = np.asarray(rows, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"Nonfinite native output: {path}")
    return result


def _orbit(path):
    try:
        result = read_native_table(path, 10)
    except ValueError:
        result = read_native_table(path, 7)
    if np.any(np.diff(result[:, 0]) <= 0):
        raise ValueError("Native orbit epochs must be strictly increasing on one arc")
    return result[:, 0], result[:, 1:7]


def _covariance(path, mjd):
    raw = read_native_table(path, 37)
    if np.any(np.diff(raw[:, 0]) <= 0):
        raise ValueError("Native covariance epochs must be strictly increasing")
    if len(raw) != len(mjd) or not np.allclose(raw[:, 0], mjd, rtol=0, atol=1e-9):
        raise ValueError("Native orbit and covariance epochs do not match")
    covariance = raw[:, 1:].reshape(-1, 6, 6)
    invalid = []
    for index, block in enumerate(covariance):
        diagonal = np.diag(block)
        if np.any(diagonal <= 0) or not np.allclose(block, block.T, rtol=1e-9, atol=1e-14):
            invalid.append(index)
            continue
        try:
            sd = np.sqrt(diagonal)
            np.linalg.cholesky(block / sd[:, None] / sd[None, :])
        except np.linalg.LinAlgError:
            invalid.append(index)
    return covariance, invalid


def _save_xml(root, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def _file_conversion(source, destination, xml):
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "FileConvert")
    ET.SubElement(program, "inputfile").text = str(source)
    ET.SubElement(program, "outputfile").text = str(destination)
    return _save_xml(root, xml)


def _write_density_values(path, epoch_tokens, values):
    """Preserve decimal GPS epoch strings while updating floating log density."""
    values = np.asarray(values, dtype=float)
    if len(epoch_tokens) != len(values) or not np.isfinite(values).all():
        raise ValueError("Density knots and finite coefficients must correspond")
    with Path(path).open("w") as stream:
        for epoch, value in zip(epoch_tokens, values):
            stream.write(f"{epoch} {value:.17e}\n")


def _blind_record(prepared):
    allowed = ("schema_version", "date", "arc", "duration_hours", "output_dir", "configs", "native_paths", "result_paths", "preprocessing_orbit_path",
               "estimation_inputs", "force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash", "nominal_initialization")
    result = {key: prepared[key] for key in allowed if key in prepared}
    files = {Path(value).resolve() for key, value in prepared.get("native_paths", {}).items()
             if key in ("receiver", "orbit", "attitude", "attitude_integration", "receiver_orbit", "receiver_attitude") and Path(value).is_file()}
    if prepared.get("output_dir") and prepared.get("date"):
        day = Path(prepared["output_dir"]) / "data" / prepared["date"]
        for name in ("orbit", "attitude", "clock", "signalBias"):
            files.update(path.resolve() for path in (day / name).glob("*.G??.*") if path.is_file())
    result["native_artifacts"] = [artifact_record("converted_estimation_input", path) for path in sorted(files)]
    # These generated XML documents define the model that build_fit_configs
    # clones. Protect them with the same immutable-input verification as data.
    configured_files = {Path(value).resolve() for value in prepared.get("configs", {}).values()
                        if Path(value).is_file()}
    result["native_artifacts"].extend(artifact_record("configured_estimation_input", path)
                                      for path in sorted(configured_files))
    if prepared.get("nominal_initialization"):
        initialization = prepared["nominal_initialization"]
        result["native_artifacts"].append(artifact_record(
            "nominal_initialization", initialization["record_path"]))
        result["native_artifacts"].extend(initialization["reproducibility_inputs"])
    result["metadata"] = {"kind": "native_preparation", "native_execution_verified": True,
                          "bootstrap_provenance": "gnss_only", "reference_inputs_used": False}
    return result


def _close_prepared_nominal_reference(configured, binary, root, *, timeout=3600.0):
    """Close shared dynamics and retain the same provenance for all preparation paths."""
    from .initialization import close_nominal_reference
    initialization_dir = Path(root) / "nominal-initialization"
    initialization = close_nominal_reference(configured, binary, initialization_dir,
        timeout=float(timeout))
    configured["nominal_initialization"] = {
        "record_path": str(initialization_dir / "initialization.json"),
        "converged": initialization["converged"],
        "iterations": len(initialization["iterations"]),
        "scope": initialization["scope"],
        "reproducibility_inputs": [initialization["bootstrap_snapshot"],
            artifact_record("fixed_initial_state", initialization_dir / "initial_state.txt"),
            initialization["source_closed_orbit"]]}
    return initialization["executions"]


def prepare_job(job: dict, job_dir: Path):
    """Fetch/generate data, mask before bootstrap, and run native conversion."""
    from . import data, groops_config
    root = Path(job_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    try:
        binary = _binary(job)
    except FileNotFoundError as error:
        return {"status": "blocked", "error": str(error)}
    case, backend = job["case"], job["backend"]
    if job["stage"] == "synthetic":
        from .synthetic import prepare_synthetic_case
        raw = prepare_synthetic_case(case, root / "observations", backend)
        if raw.get("status") != "observations_ready":
            return raw
    elif job["stage"] == "flight":
        raw = data.prepare_flight_day(case["date"], backend["cache_dir"], root / "observations",
                    allow_frozen_evaluation=bool(job.get("frozen_evaluation")), download=True)
    else:
        raise ValueError("Unknown preparation stage")
    if raw.get("status") == "excluded":
        screening_path = root / "excluded_screening.json"
        write_json(screening_path, raw)
        return {"status":"excluded", "reason":raw.get("reason", raw.get("error", "Excluded by prespecified metadata screening")),
                "screening":raw.get("screening", raw),
                "artifacts":[artifact_record("metadata_screening", screening_path)]}
    auxiliary = Path(backend["auxiliary_dir"]).resolve()
    scenario = backend.get("example_directory")
    data.fetch_example_auxiliary(scenario, auxiliary)
    groops_config.fetch_flight_auxiliary(auxiliary)
    configured = groops_config.build_day_configs(raw, scenario, auxiliary, root / "native-prepared",
        method="groops_pulses", mask=case.get("mask"), duration_hours=case.get("duration_hours", 24.))
    # A synthetic generator must supply its matching nominal-force modifier. It
    # cannot silently fall through to the mission's high-fidelity flight forces.
    if job["stage"] == "synthetic":
        from .synthetic import configure_synthetic_forces
        configured = configure_synthetic_forces(configured, case, backend)
    execution = []
    cached_transmitters = _link_cached_transmitters(raw, configured, binary) if job["stage"] == "synthetic" else None
    for label in ("convert_gnss", "convert_receiver"):
        if label == "convert_gnss" and cached_transmitters:
            execution.append(cached_transmitters)
            continue
        execution.append(run_native(binary, configured["configs"][label], configured["output_dir"], label,
                                    timeout=float(backend.get("command_timeout_seconds", 3600.0))))
    for key in ("receiver", "orbit", "attitude", "attitude_integration", "receiver_orbit", "receiver_attitude"):
        if key not in configured["native_paths"]:
            if key in ("attitude_integration", "receiver_orbit", "receiver_attitude"):
                continue
            raise ValueError(f"Required native input missing: {key}")
        path = Path(configured["native_paths"][key])
        if not path.is_file() or path.stat().st_size == 0:
            raise NativeExecutionError(f"Native preprocessing output is missing: {key}")
    _verify_transmitters(configured)
    # Close a common physical trajectory before introducing either disturbance
    # model. A gap-filled GNSS bootstrap is only a numerical starting point;
    # freezing its force-evaluation error would bias the first nonlinear solve.
    # Receiver geometry used by observation preprocessing remains immutable.
    execution.extend(_close_prepared_nominal_reference(configured, binary, root,
        timeout=float(backend.get("command_timeout_seconds", 3600.0))))
    prepared = {**configured, "status": "prepared", "native_execution": execution}
    blind = _blind_record(prepared)
    path = root / "native_preparation.json"
    write_json(path, blind)
    estimation = [*configured["estimation_inputs"], artifact_record("force_auxiliary", path, metadata={"kind": "native_preparation"})]
    validate_estimation_inputs(estimation, flight=job["stage"] == "flight")
    return {"status": "prepared", "estimation_inputs": estimation, "arc":configured.get("arc"),
            "evaluation_inputs": configured.get("evaluation_inputs", []),
            "calibration_inputs": configured.get("calibration_inputs", []),
            **{key: configured[key] for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")},
            "native_execution": execution, "nominal_initialization": configured["nominal_initialization"],
            "native_binary_sha256": file_hash(binary)}


def _preparation(job):
    validate_estimation_inputs(job["estimation_inputs"], flight=job["stage"] == "flight")
    matches = [item for item in job["estimation_inputs"] if item["role"] == "force_auxiliary"
               and item.get("metadata", {}).get("kind") == "native_preparation"]
    if len(matches) != 1:
        raise ValueError("Exactly one verified blind native-preparation artifact is required")
    record = read_json(matches[0]["path"])
    if any(key in record for key in ("evaluation_inputs", "calibration_inputs", "truth", "reference_orbit", "slr_validation")):
        raise ValueError("Evaluation paths leaked into the native fitting manifest")
    for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash"):
        if record.get(key) != job.get(key):
            raise ValueError(f"Native preparation differs from frozen {key}")
    for item in record.get("native_artifacts", []):
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Native converted estimation input changed after preparation")
    return record


def _private_data(prepared, private_root):
    source = Path(prepared["output_dir"]).resolve()
    private_root = Path(private_root).resolve()
    if source == private_root:
        raise ValueError("Fits require a private native data directory")
    orbit = Path(prepared["native_paths"]["orbit"]).resolve()
    for path in sorted((source / "data").rglob("*")):
        destination = private_root / path.relative_to(source)
        if path.is_symlink() and path.is_dir():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError(f"Refusing to reuse native transmitter path: {destination}")
            destination.symlink_to(path.resolve(), target_is_directory=True)
        elif path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists() or destination.is_symlink():
                raise ValueError(f"Refusing to reuse mutable native work directory: {destination}")
            if path.resolve() == orbit:
                shutil.copy2(path, destination)
            elif path.resolve() != Path(prepared["native_paths"]["variational"]).resolve():
                destination.symlink_to(path.resolve())


def _link_cached_transmitters(raw, configured, binary):
    entry = raw.get("native_simulation", {}).get("transmitter_cache", {})
    if not entry.get("shared_cache"):
        return None
    path = Path(entry["shared_cache"])
    record = read_json(path)
    if record.get("identity", {}).get("executable_sha256") != file_hash(binary):
        raise ValueError("Native transmitter cache used a different executable")
    for item in record.get("artifacts", []):
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Modified native transmitter cache artifact")
    source = path.parent / "data" / configured["date"]
    target = Path(configured["output_dir"]) / "data" / configured["date"]
    target.mkdir(parents=True, exist_ok=True)
    for name in ("orbit", "attitude", "clock", "signalBias"):
        if not (source / name).is_dir():
            raise ValueError("Incomplete native transmitter cache")
        destination = target / name
        if destination.exists() or destination.is_symlink():
            raise ValueError("Refusing to replace existing prepared transmitter directory")
        destination.symlink_to((source / name).resolve(), target_is_directory=True)
    _verify_transmitters(configured)
    return {"label":"convert_gnss", "reused_verified_native_conversion":str(path),
            "cache_sha256":file_hash(path), "native_binary_sha256":file_hash(binary),
            "original_execution":record.get("execution")}


def _verify_transmitters(configured):
    """Native converters may exit zero while omitting unavailable products."""
    root = Path(configured["output_dir"]) / "data" / configured["date"]
    available = []
    for folder in ("orbit", "attitude", "clock", "signalBias"):
        available.append({path.name.split(".")[-2] for path in (root / folder).glob("*.G??.*")
                          if path.stat().st_size > 0})
    common = set.intersection(*available)
    if len(common) < 5:
        raise NativeExecutionError("Native conversion has fewer than five complete GPS transmitter products")
    return sorted(common)


def _map_only_config(estimate_path, output_path):
    """Keep the primary MAP sequence, omitting only uncertainty computation.

    Native covariance exporters require an inverse from the same process, so
    removing the processing step alone is insufficient. The final-confirmation
    configuration remains untouched and retains all requested covariance output.
    """
    tree = ET.parse(estimate_path)
    for processing in tree.findall(".//GnssProcessing"):
        for step in list(processing.findall("processingStep")):
            if step.find("computeCovarianceMatrix") is not None:
                processing.remove(step)
        for dynamic in processing.findall("parametrization/leoDynamicOrbits"):
            for tag in ("outputfileCovariance", "outputfileParameterCovariance",
                        "outputfileCovarianceObservationEpochs"):
                for node in list(dynamic.findall(tag)):
                    dynamic.remove(node)
    _save_xml(tree.getroot(), output_path)
    return str(output_path)


def fit_job(job: dict, job_dir: Path):
    from .groops_config import build_fit_configs
    root = Path(job_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if any(key in job for key in ("evaluation_inputs", "calibration_inputs", "truth", "reference_orbit")):
        raise ValueError("Fitting accepts estimation inputs only")
    try:
        binary = _binary(job)
    except FileNotFoundError as error:
        return {"status": "blocked", "error": str(error)}
    prepared = _preparation(job)
    method, parameters = job["method"], job["parameters"]
    if method not in ("groops_pulses", "groops_pulses_ar", "groops_log_drag_ou"):
        raise ValueError(f"Unsupported native model: {method}")
    private = root / "native-fit"
    _private_data(prepared, private)
    config = build_fit_configs(prepared, private, method, parameters)
    retain_native = bool(job.get("backend", {}).get("retain_native_diagnostics", False)
                         or (job["stage"] == "flight" and job.get("split") != "calibration"))
    if not retain_native:
        # The full dynamic inverse is still computed internally to propagate
        # Cartesian marginals. Its quadratic-size ASCII export is needed only
        # by native diagnostics and flight SLR prediction.
        tree = ET.parse(config["configs"]["estimate"])
        for parent in tree.iter():
            for node in list(parent):
                if node.tag in ("outputfileParameterCovariance", "outputfilePhaseRecovery"):
                    parent.remove(node)
        _save_xml(tree.getroot(), config["configs"]["estimate"])
        config["result_paths"].pop("parameter_covariance", None)
        config["result_paths"].pop("phase_recovery", None)
    deferred_covariance = method != "groops_pulses_ar"
    map_config = (_map_only_config(config["configs"]["estimate"], private / "estimate_map.xml")
                  if deferred_covariance else config["configs"]["estimate"])
    density_file = private / "log_density.txt"
    density = method == "groops_log_drag_ou"
    if density:
        log_density = read_native_table(density_file, 2)
        density_epochs = [line.split()[0] for line in density_file.read_text().splitlines()
                          if line.strip() and not line.lstrip().startswith("#")]
    else:
        log_density = None
    controls = {"maximum_outer_iterations": 32 if density else 12, "maximum_log_density_update": 1e-4,
                "maximum_orbit_change_m": 3e-5, "maximum_accepted_log_density_increment": .5,
                "opposing_density_direction_cosine": -.25, "opposing_density_step_scale": .5}
    supplied_controls = job.get("numerical_controls", {})
    if set(supplied_controls) - set(controls):
        raise ValueError("Unknown native numerical controls: " + ", ".join(sorted(set(supplied_controls)-set(controls))))
    controls.update(supplied_controls)
    from .density_step import DensityStepController, damped_orbit_config
    step_controller = DensityStepController(controls["maximum_accepted_log_density_increment"],
        controls["opposing_density_direction_cosine"], controls["opposing_density_step_scale"]) if density else None
    if (isinstance(controls["maximum_outer_iterations"], bool)
        or int(controls["maximum_outer_iterations"]) != controls["maximum_outer_iterations"]
        or controls["maximum_outer_iterations"] < 1):
        raise ValueError("At least one whole outer iteration is required")
    for key in ("maximum_log_density_update", "maximum_orbit_change_m"):
        if not np.isfinite(controls[key]) or controls[key] <= 0:
            raise ValueError(f"A positive finite convergence threshold is required: {key}")
    timeout = float(job.get("backend", {}).get("command_timeout_seconds", 3600.0))
    history, execution = [], []
    preprocessing_audit_sha = None
    previous_states = previous_mjd = None
    converged, final_confirmation = False, False
    covariance = prediction_covariance = prediction_mjd = None
    invalid = invalid_prediction = None
    last_map = None
    binary_sha = file_hash(binary)
    binary_stat = binary.stat()
    start = time.monotonic()
    try:
        for iteration in range(1, int(controls["maximum_outer_iterations"]) + 2):
            if iteration > controls["maximum_outer_iterations"] and not final_confirmation:
                break
            iteration_root = root / f"iteration-{iteration:02d}"
            iteration_root.mkdir(parents=True, exist_ok=True)
            if density:
                shutil.copy2(density_file, iteration_root / "reference_log_density.txt")
            compute_covariance = final_confirmation or not deferred_covariance
            if compute_covariance:
                # Require covariance from this execution, even if a failed job
                # is retried in a directory containing older native outputs.
                for key in ("covariance", "covariance_observations", "parameter_covariance"):
                    if config["result_paths"].get(key):
                        output = Path(config["result_paths"][key])
                        output.resolve().relative_to(private.resolve())
                        output.unlink(missing_ok=True)
            for label in ("variational", "estimate"):
                path = (map_config if label == "estimate" and not compute_covariance
                        else config["configs"][label])
                execution.append(run_native(binary, path, iteration_root, label, timeout=timeout))
            outputs = config["result_paths"]
            if method != "groops_pulses_ar":
                audit = Path(outputs["preprocessing_audit"])
                current_audit_sha = file_hash(audit)
                if preprocessing_audit_sha is not None and current_audit_sha != preprocessing_audit_sha:
                    raise NativeExecutionError("Common native preprocessing changed between outer iterations")
                preprocessing_audit_sha = current_audit_sha
            mjd, states = _orbit(outputs["orbit"])
            vector = read_native_table(outputs["parameters"]).ravel()
            density_count = len(log_density) if density else 0
            if density and len(vector) != density_count + 6:
                raise ValueError("Native density parameter order/count differs from [log-density knots, six initial-state components]")
            if not density and (len(vector) < 6 or (len(vector) - 6) % 3):
                raise ValueError("Native pulse parameter count differs from [three components per pulse, six initial-state components]")
            last_map = {"iteration": iteration, "mjd": mjd, "states": states, "parameters": vector}
            if compute_covariance:
                covariance, invalid = _covariance(outputs["covariance"], mjd)
                prediction_mjd, prediction_covariance, invalid_prediction = mjd, covariance, invalid
                if outputs.get("covariance_observations"):
                    prediction_mjd = read_native_table(outputs["covariance_observations"], 37)[:, 0]
                    prediction_covariance, invalid_prediction = _covariance(outputs["covariance_observations"], prediction_mjd)
                    if prediction_mjd[0] < mjd[0]-1e-9 or prediction_mjd[-1] > mjd[-1]+1e-9:
                        raise ValueError("Prediction covariance lies outside the fitted dynamic arc")
            dg = vector[:density_count] if density else np.empty(0)
            update = float(np.max(np.abs(dg), initial=0))
            step = step_controller.choose(dg, confirmation=final_confirmation) if density else {"scale": 1.}
            change = None
            if previous_mjd is not None:
                if mjd.shape != previous_mjd.shape or not np.allclose(mjd, previous_mjd, rtol=0, atol=1e-9):
                    raise ValueError("Native output epochs changed during outer iteration")
                change = float(np.max(np.linalg.norm(states[:, :3] - previous_states[:, :3], axis=1)))
            map_small = bool(change is not None and change < controls["maximum_orbit_change_m"]
                             and update < controls["maximum_log_density_update"])
            covariance_valid = bool(compute_covariance and not invalid and not invalid_prediction)
            small = map_small and (covariance_valid if compute_covariance else True)
            history.append({"iteration": iteration, "maximum_orbit_change_m": change,
                            "maximum_log_density_update": update, "invalid_covariance_epochs": invalid,
                            "invalid_prediction_covariance_epochs": invalid_prediction,
                            "covariance_computed": compute_covariance,
                            "covariance_valid": covariance_valid if compute_covariance else None,
                            "preprocessing_audit_sha256":preprocessing_audit_sha,
                            "final_confirmation": final_confirmation, "criteria_met": small,
                            "density_step": step if density else None,
                            "convergence_update_scope": "Full undamped native proposal"})
            write_json(root / "outer_iterations.json", {"controls":controls, "iterations":history,
                "native_binary_sha256":binary_sha, "status":"running", "final_confirmation_pending":small})
            # Native files are overwritten at the next iteration. Record exact
            # output hashes and retain small parameter snapshots, rather than
            # duplicating dense covariance/orbit arrays at every outer solve.
            output_audit = []
            for key, value in outputs.items():
                if not compute_covariance and key in ("covariance", "covariance_observations", "parameter_covariance"):
                    continue  # Never attribute a leftover covariance file to a MAP-only solve.
                output = Path(value)
                if output.is_file():
                    output_audit.append({"kind":key, "path":str(output),
                        "sha256":file_hash(output), "bytes":output.stat().st_size,
                        "retention":"final native output only; superseded contents not retained"})
                    if key == "parameters":
                        shutil.copy2(output, iteration_root / output.name)
            write_json(iteration_root / "output_hashes.json", {"iteration":iteration, "outputs":output_audit})
            if final_confirmation:
                converged = small
                break
            if small:
                final_confirmation = True
            if iteration == controls["maximum_outer_iterations"] and not final_confirmation:
                break
            accepted_orbit = outputs.get("orbit_native")
            if density and step["scale"] < 1.:
                if previous_states is None:
                    # The first accepted initial state comes from the common
                    # closed nominal preparation, never from held-out data.
                    seed = iteration_root / "previous_orbit.txt"
                    conversion = _file_conversion(config["native_paths"]["orbit"], seed,
                        iteration_root / "read_previous_orbit.xml")
                    execution.append(run_native(binary, conversion, iteration_root,
                        "read_previous_orbit", timeout=timeout))
                    _, previous_input_states = _orbit(seed)
                    prior_initial = previous_input_states[0]
                else:
                    prior_initial = previous_states[0]
                target_initial = prior_initial + step["scale"] * (states[0]-prior_initial)
                accept_path, accepted_orbit = damped_orbit_config(config, iteration_root,
                    vector, target_initial, step["scale"])
                execution.append(run_native(binary, accept_path, iteration_root, "accept_step", timeout=timeout))
                accepted_mjd, accepted_states = _orbit(accepted_orbit.with_suffix(".txt"))
                if accepted_mjd.shape != mjd.shape or not np.allclose(accepted_mjd, mjd, rtol=0, atol=1e-9):
                    raise ValueError("Native damped trajectory changed the state epochs")
                states = accepted_states
                write_json(iteration_root / "accepted_step.json", {
                    **step, "initial_state_si": target_initial.tolist(),
                    "native_orbit_sha256": file_hash(accepted_orbit),
                    "scope": "Scaled density increment and physical initial state; native re-evaluation at unchanged reference force"})
            if density:
                log_density[:, 1] += step["scale"] * dg
                _write_density_values(density_file, density_epochs, log_density[:, 1])
            previous_mjd, previous_states = mjd.copy(), states.copy()
            # Extension determines archive format. A .txt orbit must be converted,
            # never copied byte-for-byte into a .dat native input filename.
            if accepted_orbit:
                shutil.copy2(accepted_orbit, config["native_paths"]["orbit"])
            else:
                conversion = _file_conversion(outputs["orbit"], config["native_paths"]["orbit"], iteration_root / "refresh_orbit.xml")
                execution.append(run_native(binary, conversion, iteration_root, "refresh_orbit", timeout=timeout))
        if binary.stat().st_mtime_ns != binary_stat.st_mtime_ns or binary.stat().st_size != binary_stat.st_size:
            raise ValueError("Native executable changed during fitting")
        if not converged:
            raise NativeExecutionError("Outer iterations ended without a converged final covariance confirmation")
        estimate_path = root / "fit.npz"
        np.savez_compressed(estimate_path, times=(mjd - mjd[0])*86400., mjd=mjd, states=states, covariance=covariance,
                            prediction_mjd=prediction_mjd, prediction_covariance=prediction_covariance)
        runtime = {"execution": execution, "outer_iterations": history, "controls": controls,
                   "elapsed_seconds": time.monotonic()-start, "peak_rss_bytes": max((x["peak_rss_bytes"] for x in execution), default=0),
                   "native_binary_sha256": binary_sha, "source_hash": job["source_hash"]}
        runtime_path = root / "native_runtime.json"
        write_json(runtime_path, runtime)
        write_json(root / "outer_iterations.json", {"controls":controls, "iterations":history,
            "native_binary_sha256":binary_sha, "status":"complete", "converged":converged})
        compact = converged and not retain_native and bool(config["result_paths"].get("orbit_native"))
        artifacts = [artifact_record("state_estimate", estimate_path), artifact_record("native_runtime", runtime_path),
                     artifact_record("native_fit_configuration", config["configs"]["estimate"]),
                     artifact_record("native_parameters", config["result_paths"]["parameters"])]
        if deferred_covariance:
            artifacts.append(artifact_record("native_intermediate_fit_configuration", map_config))
        if not compact:
            artifacts.append(artifact_record("estimated_orbit", config["result_paths"]["orbit"]))
            artifacts.append(artifact_record("orbit_covariance", config["result_paths"]["covariance"]))
            if config["result_paths"].get("covariance_observations"):
                artifacts.append(artifact_record("observation_epoch_covariance", config["result_paths"]["covariance_observations"],
                    metadata={"scope":"Full-inverse dynamic covariance propagated through variational designs at nominal GNSS epochs, including withheld epochs"}))
        if config["result_paths"].get("orbit_native"):
            artifacts.append(artifact_record("estimated_orbit_native", config["result_paths"]["orbit_native"],
                metadata={"epoch_precision":"native split-day Time; no double-MJD roundtrip"}))
        if "parameter_covariance" in config["result_paths"]:
            parameter_covariance_path = config["result_paths"]["parameter_covariance"]
            parameter_covariance = read_native_table(parameter_covariance_path)
            if parameter_covariance.shape != (len(vector), len(vector)):
                raise ValueError("Native parameter covariance does not match full dynamic parameter ordering")
            artifacts.append(artifact_record("native_parameter_covariance", parameter_covariance_path,
                metadata={"scope":"full dynamic block of full native inverse", "parameter_order":"acceleration globals, pulse components in native um/s, six initial-state components"}))
        if not compact:
            artifacts.append(artifact_record("native_variational", config["native_paths"]["variational"]))
            if preprocessing_audit_sha:
                artifacts.append(artifact_record("native_preprocessing_audit", config["result_paths"]["preprocessing_audit"]))
        artifacts.extend([artifact_record("native_variational_configuration", config["configs"]["variational"]),
                          artifact_record("native_attitude", config["native_paths"]["attitude"])])
        for key, role in (("apriori_solution", "full_native_solution"), ("parameter_names", "native_parameter_names")):
            if key in config["result_paths"]:
                artifacts.append(artifact_record(role, config["result_paths"][key],
                    metadata={"export_stage":"after final native estimation and covariance", "includes_gnss_nuisance_parameters":True}))
        if density:
            posterior_density = log_density.copy()
            posterior_density[:, 1] += dg
            posterior_path = root / "posterior_log_density.txt"
            _write_density_values(posterior_path, density_epochs, posterior_density[:, 1])
            artifacts.append(artifact_record("posterior_log_density", posterior_path))
            artifacts.append(artifact_record("linearization_log_density", density_file,
                metadata={"usage":"Reference log density actually used to integrate final variational design and marginalized covariance"}))
        retention = {"retain_native_diagnostics":retain_native,
                     "cartesian_marginals":"Preserved losslessly in state_estimate NPZ",
                     "superseded_iterations":"Logs, convergence records, parameters and output SHA256 only",
                     "deleted_outputs":[]}
        if compact:
            for value in (config["result_paths"]["orbit"], config["result_paths"]["covariance"], config["result_paths"].get("residuals"),
                          config["native_paths"]["variational"], config["native_paths"]["orbit"], config["result_paths"].get("preprocessing_audit"),
                          config["result_paths"].get("covariance_observations")):
                if value is None:
                    continue
                path = Path(value)
                if path.is_file() and not path.is_symlink():
                    path.resolve().relative_to(private.resolve())  # Never prune shared prepared data.
                    retention["deleted_outputs"].append({"path":str(path), "sha256":file_hash(path),
                        "bytes":path.stat().st_size, "status":"deleted_after_successful_final_fit",
                        "reason":"redundant with retained state/covariance or reproducible native configuration"})
                    path.unlink()
        retention_path = root / "retention.json"
        write_json(retention_path, retention)
        artifacts.append(artifact_record("retention_audit", retention_path))
        return {"status": "complete", "method": method, "converged": converged, "arc":prepared.get("arc"),
                "preprocessing_audit_sha256":preprocessing_audit_sha,
                "covariance_valid": converged and final_confirmation and not invalid and not invalid_prediction, "covariance_scope": "marginalized",
                "parameter_blocks": ["log_density_knots" if density else "velocity_pulses", "initial_cartesian_state", "receiver_clocks", "receiver_signal_biases", "resolved_ambiguities" if method == "groops_pulses_ar" else "float_ambiguities"],
                "artifacts": artifacts, "native_binary_sha256": binary_sha,
                "force_model_hash": job["force_model_hash"], "measurement_model_hash": job["measurement_model_hash"],
                "metadata": {"states_frame": "CRF", "states_units": "m,m/s", "orbit_epochs": len(mjd),
                    "outer_iterations": len(history), "convergence_controls": controls,
                    "prediction_covariance_epochs": len(prediction_mjd),
                    "final_covariance_confirmation": final_confirmation and converged,
                    "covariance_schedule": "final_confirmation_only" if deferred_covariance else "every_iteration_native_ar",
                    "retain_native_diagnostics":retain_native,
                    "nuisance_marginalization": "Full native inverse includes clocks and other retained nuisance parameters; all dynamic columns propagated",
                    "ambiguity_policy": "conditional on native resolved integer ambiguities" if method == "groops_pulses_ar" else "jointly estimated float ambiguities",
                    "ionosphere_policy":"Slant ionosphere is eliminated locally by the native GNSS observation model, rather than retained as a global parameter block",
                    "pulse_reference": ("Official secondary AR configuration retains the stock pulse initializer and ambiguity-resolution sequence"
                        if method == "groops_pulses_ar" else
                        "Every primary full pulse solve uses a force-only six-state initializer; coefficients are not accumulated into unregularized offsets"),
                    "reference_inputs_used": False},
                "elapsed_seconds": runtime["elapsed_seconds"], "peak_rss_bytes": runtime["peak_rss_bytes"]}
    except (NativeExecutionError, ValueError, OSError, np.linalg.LinAlgError) as error:
        if isinstance(error, NativeExecutionError) and error.execution is not None:
            execution.append(error.execution)
        error_text = f"{type(error).__name__}: {error}"
        elapsed = time.monotonic()-start
        peak_rss = max((x["peak_rss_bytes"] for x in execution), default=None)
        write_json(root / "native_runtime.json", {"execution": execution, "outer_iterations": history,
                   "elapsed_seconds": elapsed, "peak_rss_bytes": peak_rss,
                   "memory_scope":"peak native process RSS; excludes Python wrapper and filesystem caches",
                   "native_binary_sha256":binary_sha, "source_hash":job["source_hash"], "error": error_text})
        write_json(root / "outer_iterations.json", {"controls":controls, "iterations":history,
            "native_binary_sha256":binary_sha, "status":"failed", "converged":False, "error":error_text})
        artifacts = [artifact_record("native_runtime", root / "native_runtime.json"),
                     artifact_record("outer_iteration_diagnostics", root / "outer_iterations.json")]
        if last_map is not None:
            diagnostic_path = root / "last_map.npz"
            np.savez_compressed(diagnostic_path, times=(last_map["mjd"]-last_map["mjd"][0])*86400.,
                                mjd=last_map["mjd"], states=last_map["states"], parameters=last_map["parameters"])
            artifacts.append(artifact_record("last_map_diagnostics", diagnostic_path,
                metadata={"iteration":last_map["iteration"], "covariance_included":False,
                          "scope":"Last readable native MAP states/parameters; not an accepted fitted posterior"}))
        return {"status": "failed", "method": method, "converged": False, "covariance_valid": False,
                "elapsed_seconds":elapsed, "peak_rss_bytes":peak_rss,
                "native_binary_sha256":binary_sha,
                "error": error_text, "artifacts": artifacts}


def _artifact(result, role):
    items = [item for item in result.get("artifacts", []) if item["role"] == role]
    if len(items) != 1 or file_hash(items[0]["path"]) != items[0]["sha256"]:
        raise ValueError(f"Exactly one unchanged fitted artifact required: {role}")
    return Path(items[0]["path"])


def _prediction_orbit(result):
    """Prefer native Time precision; retain compatibility with old pilot artifacts."""
    native = any(item["role"] == "estimated_orbit_native" for item in result.get("artifacts", []))
    return _artifact(result, "estimated_orbit_native" if native else "estimated_orbit")


def _prediction_support(predictions, path=None):
    """Describe the actual scored support; a candidate may not drop hard rows."""
    keys = [(float(row[0]), int(row[1])) for row in predictions]
    if any(row[1] != int(row[1]) or not 1 <= int(row[1]) <= 32 for row in predictions):
        raise ValueError("Predictive support requires integer GPS PRNs")
    if len(set(keys)) != len(keys):
        raise ValueError("Duplicate prediction epoch/PRN rows")
    if path is None:
        return [[epoch, prn] for epoch, prn in sorted(keys)]
    support = []
    for line in Path(path).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 4:
            raise ValueError("Native predictive support needs epoch, PRN and two signal types")
        epoch, prn = float(fields[0]), int(fields[1])
        support.append([epoch, prn, fields[2], fields[3]])
    if len(support) != len(keys) or [(row[0], row[1]) for row in support] != keys:
        raise ValueError("Native predictive signal support does not match prediction rows")
    return sorted(support)


def score_native_predictions(predictions, fit_mjd, fit_covariance, arc_id="0", support_path=None):
    """Native corrected IF-code residuals and CRF Jacobians, scored by epoch."""
    predictions = np.asarray(predictions, dtype=float)
    fit_mjd, fit_covariance = np.asarray(fit_mjd), np.asarray(fit_covariance)
    if predictions.ndim != 2 or predictions.shape[1] != 8 or not np.isfinite(predictions).all():
        raise ValueError("Prediction rows must be MJD,PRN,residual,variance,Jx,Jy,Jz,Jclock")
    support = _prediction_support(predictions, support_path)
    scores = []
    for epoch in np.unique(predictions[:, 0]):
        rows = predictions[predictions[:, 0] == epoch]
        index = int(np.argmin(np.abs(fit_mjd - epoch)))
        if abs(fit_mjd[index] - epoch)*86400 > 1e-3:
            raise ValueError("Prediction epoch does not match a native orbit covariance epoch; propagate covariance before scoring")
        score = clock_nullspace_nll(rows[:, 2], rows[:, 3], rows[:, 4:7], fit_covariance[index, :3, :3],
                                   clock_design=rows[:, 7:8])
        scores.append({**score, "arc_id": arc_id, "mjd": float(epoch)})
    return {"calibration_score": aggregate_clock_scores(scores), "epoch_scores": scores,
            "predictive_support_sha256": canonical_hash(support), "predictive_support": support,
            "predictive_support_columns": ["GPSMJD", "PRN", "first_code_type", "second_code_type"]
                if support_path is not None else ["GPSMJD", "PRN"]}


def evaluate_job(job: dict, result: dict, job_dir: Path):
    """Post-fit evaluation; no evaluation artifact is ever sent back to fitting."""
    root = Path(job_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if not result.get("converged") or not result.get("covariance_valid"):
        return {"status": "failed", "error": "Evaluation requires a converged fit with valid marginalized covariance"}
    with np.load(_artifact(result, "state_estimate")) as archive:
        times, mjd, states, covariance = [archive[key].copy() for key in ("times", "mjd", "states", "covariance")]
        # Old synthetic pilot datasets have coincident observation/dynamics
        # epochs. New UTC flight datasets store explicitly propagated marginals
        # at nominal GNSS epochs; strict matching below still rejects misuse.
        prediction_mjd = archive["prediction_mjd"].copy() if "prediction_mjd" in archive else mjd
        prediction_covariance = archive["prediction_covariance"].copy() if "prediction_covariance" in archive else covariance
    if job["split"] == "calibration":
        return evaluate_native_code(job, result, root, prediction_mjd, prediction_covariance)
    if job["stage"] == "flight":
        return evaluate_native_slr(job, result, root, mjd, states)
    truth_records = [item for item in job.get("evaluation_inputs", []) if item["role"] == "truth"]
    if len(truth_records) != 1 or file_hash(truth_records[0]["path"]) != truth_records[0]["sha256"]:
        raise ValueError("One unchanged independently generated synthetic truth artifact is required")
    with np.load(truth_records[0]["path"]) as archive:
        truth = archive["states"]
        truth_times = archive["mjd"] if "mjd" in archive else archive["times"] / 86400. + mjd[0]
    if len(truth_times) != len(mjd) or not np.allclose(truth_times, mjd, rtol=0, atol=1e-9):
        if np.any(np.diff(truth_times) <= 0):
            raise ValueError("Independent truth epochs must increase strictly")
        right = np.clip(np.searchsorted(truth_times, mjd), 0, len(truth_times)-1)
        left = np.maximum(right-1, 0)
        indices = np.where(np.abs(truth_times[left]-mjd) < np.abs(truth_times[right]-mjd), left, right)
        if not np.allclose(truth_times[indices], mjd, rtol=0, atol=1e-9):
            raise ValueError("Independent truth must cover fitted epochs exactly; implicit trajectory interpolation is not accepted")
        truth = truth[indices]
    gap = np.zeros(len(times), dtype=bool)
    for start, stop in job["case"].get("mask", {}).get("intervals_seconds", []):
        gap |= (times >= start) & (times <= stop)
    metrics = position_metrics(times, states, truth[:, :6], covariance, gap)
    path = root / "metrics.json"
    write_json(path, metrics)
    return {"status": "complete", "metrics": metrics, "artifacts": [artifact_record("evaluation_metrics", path)]}


def evaluate_native_code(job, result, root, mjd, covariance):
    """Native predictor integration is explicit; absent support cannot pass tuning."""
    from .groops_config import build_prediction_config
    calibration = job.get("calibration_inputs", [])
    if not calibration:
        raise ValueError("Calibration evaluation lacks separately supplied held-out code")
    for item in calibration:
        if item["role"] != "heldout_gnss_code" or file_hash(item["path"]) != item["sha256"]:
            raise ValueError("Held-out calibration artifact is missing, modified or incorrectly classified")
    binary = _binary(job)
    prediction = build_prediction_config(_artifact(result, "native_fit_configuration"),
        _prediction_orbit(result), calibration, root)
    execution = []
    for label, config in prediction["configs"].items():
        execution.append(run_native(binary, config, root, label,
            timeout=float(job.get("backend", {}).get("command_timeout_seconds", 3600.0))))
    scored = score_native_predictions(read_native_table(prediction["predictions"], 8), mjd, covariance,
                                     arc_id=str(job["case"].get("seed", job["case"].get("date", "0"))),
                                     support_path=prediction["predictive_support"])
    score_path = root / "predictive_code_score.json"
    write_json(score_path, {**scored, "execution": execution,
        "corrections": "same native GNSS observation model as fitting",
        "noise_assumption": "Conditional on fixed native nominal GNSS code noise, fixed transmitter products and correction models; per-epoch receiver clock/IF bias is projected out using the native clock Jacobian"})
    valid = scored["calibration_score"]["valid"]
    return {"status": "complete" if valid else "failed", **scored,
            "artifacts": [artifact_record("calibration_score", score_path), artifact_record("native_code_predictions", prediction["predictions"]),
                          artifact_record("native_predictive_support", prediction["predictive_support"])],
            **({"error": "Held-out code has invalid covariance or no clock-free information"} if not valid else {})}


def _reference_agreement(job, result, root, mjd, states, binary):
    """Independent post-fit GNV comparison, expressly not known flight truth."""
    records = [item for item in job.get("evaluation_inputs", []) if item["role"] == "reference_orbit"]
    if not records or any(file_hash(item["path"]) != item["sha256"] for item in records):
        raise ValueError("Flight reference agreement requires unchanged evaluation-only orbit files")
    reference_path = Path(root) / "reference_crf.txt"
    config = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(config, "program"), "GraceL1b2Orbit")
    ET.SubElement(program, "outputfileOrbit").text = str(reference_path)
    for item in sorted(records, key=lambda item: item["path"]):
        ET.SubElement(program, "inputfile").text = item["path"]
    fitted_config = ET.parse(_artifact(result, "native_fit_configuration")).getroot()
    rotation = fitted_config.find(".//GnssProcessing/earthRotation")
    if rotation is None:
        raise ValueError("Native fitted Earth-rotation model is missing")
    program.append(deepcopy(rotation))
    config_path = _save_xml(config, Path(root) / "convert_reference.xml")
    execution = run_native(binary, config_path, root, "convert_reference",
        timeout=float(job.get("backend", {}).get("command_timeout_seconds", 3600.)))
    reference_mjd, reference_states = _orbit(reference_path)
    # UTC-day preparation can require two adjacent GPS-day reference files.
    # Only the fitted arc is scored; these files remain evaluation-only.
    within_arc = (reference_mjd >= mjd[0]-1e-3/86400.) & (reference_mjd <= mjd[-1]+1e-3/86400.)
    reference_mjd, reference_states = reference_mjd[within_arc], reference_states[within_arc]
    if not len(reference_mjd):
        raise ValueError("No flight-reference epochs inside the fitted arc")
    right = np.clip(np.searchsorted(reference_mjd, mjd), 0, len(reference_mjd)-1)
    left = np.maximum(right-1, 0)
    indices = np.where(abs(reference_mjd[left]-mjd) < abs(reference_mjd[right]-mjd), left, right)
    matched = abs(reference_mjd[indices]-mjd)*86400. < 1e-3
    if not np.any(matched):
        raise ValueError("No common epochs for native flight-reference comparison")
    difference = states[matched] - reference_states[indices[matched]]
    score = {"position_rms_m":float(np.sqrt(np.mean(np.sum(difference[:, :3]**2, axis=1)))),
             "velocity_rms_m_s":float(np.sqrt(np.mean(np.sum(difference[:, 3:]**2, axis=1)))),
             "matched_epochs":int(matched.sum()), "unmatched_fit_epochs":int((~matched).sum()),
             "interpretation":"agreement with an external reference; not known truth",
             "frame":"CRF through the same native Earth-rotation model", "reference_used_in_fit":False}
    score["reference_input_files"] = len(records)
    return score, execution, artifact_record("evaluation_reference_crf", reference_path)


def _flight_without_slr(job, result, root, mjd, states, reason, execution=()):
    """SLR availability must not erase independently available flight evidence."""
    reference, reference_execution, reference_artifact = _reference_agreement(
        job, result, root, mjd, states, _binary(job))
    metrics = {"reference_agreement":reference,
               "native_slr":{"status":"unavailable", "reason":str(reason)},
               "formal_prediction":{"status":"unavailable", "observations":0},
               "predictive":{"valid":False, "status":"unavailable", "nll":None,
                             "reason":str(reason)}}
    path = Path(root) / "flight_metrics.json"
    write_json(path, {"metrics":metrics, "execution":[*execution, reference_execution],
                      "slr_used_in_fit":False, "slr_unavailable_reason":str(reason)})
    return {"status":"incomplete", "error":str(reason), "metrics":metrics,
            "slr_used_in_fit":False,
            "artifacts":[artifact_record("evaluation_metrics", path), reference_artifact]}


def evaluate_native_slr(job, result, root, mjd, states):
    """Corrected independent SLR and exact propagated dynamic uncertainty."""
    from .slr import build_slr_configs, summarize_slr, SlrPrerequisiteError, frozen_slr_auxiliary
    records = [item for item in job.get("evaluation_inputs", []) if item["role"] == "slr_validation"]
    if len(records) != 1 or file_hash(records[0]["path"]) != records[0]["sha256"]:
        raise ValueError("SLR requires one unchanged evaluation-only normal-point artifact")
    frozen_corrections = (frozen_slr_auxiliary(job, root, records[0]["path"])
                          if job.get("frozen_evaluation") else None)
    try:
        prepared = build_slr_configs(job["case"]["date"], records[0]["path"],
            _prediction_orbit(result), _artifact(result, "native_attitude"),
            job["backend"]["auxiliary_dir"], root,
            allow_frozen_evaluation=bool(job.get("frozen_evaluation")),
            download=frozen_corrections is None, frozen_auxiliary=frozen_corrections,
            fit_config_path=_artifact(result, "native_fit_configuration"),
            parameter_covariance_path=_artifact(result, "native_parameter_covariance"),
            variational_path=_artifact(result, "native_variational"))
    except SlrPrerequisiteError as error:
        return _flight_without_slr(job, result, root, mjd, states, error)
    binary = _binary(job)
    execution = []
    for label, config_path in prepared["configs"].items():
        try:
            execution.append(run_native(binary, config_path, root, label,
                timeout=float(job.get("backend", {}).get("command_timeout_seconds", 3600.))))
        except NativeExecutionError:
            log = Path(root) / (label + ".log")
            if log.is_file() and "no usable withheld SLR observations" in log.read_text(errors="replace"):
                failed = Path(root) / (label + ".execution.json")
                if failed.is_file(): execution.append(read_json(failed))
                return _flight_without_slr(job, result, root, mjd, states,
                    "No usable withheld SLR observations after native selection", execution)
            raise
    try:
        predictions = read_native_table(prepared["predictions"])
    except ValueError as error:
        if str(error).startswith("No consistent numeric table"):
            return _flight_without_slr(job, result, root, mjd, states,
                "Native SLR produced an empty observation table", execution)
        raise
    if predictions.shape[1] not in (14, 15):
        raise ValueError("Unsupported native SLR output schema")
    predictive_covariance = read_native_table(prepared["predictive_covariance"])
    if predictive_covariance.shape != (len(predictions), len(predictions)):
        raise ValueError("Full native SLR predictive covariance does not match prediction rows")
    valid_rows = predictions[:, 9] == 1
    retained = predictions[valid_rows]
    metrics = flight_residual_metrics(retained[:, 3], sigma=retained[:, 4])
    formal_stations = {int(value) for value in prepared.get("formal_prediction_stations", [])}
    formal_rows = valid_rows & np.isin(predictions[:, 1].astype(int), list(formal_stations))
    formal = predictions[formal_rows]
    # Add each external bias uncertainty once as a shared station covariance,
    # before selecting any formal principal submatrix or grouped summaries.
    predictive_covariance = predictive_covariance.copy()
    for station in formal_stations:
        policy = prepared["station_bias_policy"][str(station)]
        sigma_bias = policy.get("range_bias_sigma_m")
        if sigma_bias is None or not np.isfinite(sigma_bias) or sigma_bias < 0:
            raise ValueError("Formal SLR scoring requires externally calibrated station-bias uncertainty")
        selected = predictions[:, 1].astype(int) == station
        predictive_covariance[np.ix_(selected, selected)] += sigma_bias**2
    if len(formal):
        formal_covariance = predictive_covariance[np.ix_(formal_rows, formal_rows)].copy()
        formal_metrics = flight_residual_metrics(formal[:, 3], sigma=formal[:, 4],
                                                predictive_covariance=formal_covariance)
        metrics["predictive"] = formal_metrics["predictive"]
        metrics["formal_prediction"] = {"status":"complete", "observations":len(formal),
            "stations":sorted(formal_stations), "selection":"fixed external ILRS calibration availability; no residual selection",
            "station_bias_uncertainty":"shared station-common covariance from published external calibration"}
    else:
        metrics["predictive"] = {"valid":False, "status":"unavailable", "nll":None,
                                 "reason":"No physically usable points from externally calibrated stations"}
        metrics["formal_prediction"] = {"status":"unavailable", "observations":0, "stations":[]}
    metrics["native_slr"] = summarize_slr(prepared["predictions"],
        predictive_covariance=predictive_covariance, formal_prediction_stations=formal_stations,
        pass_sessions=prepared["quality_control"]["sessions"],
        pass_source_sha256=prepared["quality_control"]["source_sha256"])
    metrics["predictive_covariance_scope"] = "Full H P_dynamic H' plus native observation noise and shared external station-bias uncertainty, including cross-observation correlations; P_dynamic is marginalized over GNSS nuisance parameters"
    metrics["predictive_conditioning"] = "Conditional on fixed station, reflector, atmosphere, Earth-rotation and known-bias corrections; model-systematic uncertainties are not fitted to SLR"
    reference, reference_execution, reference_artifact = _reference_agreement(job, result, root, mjd, states, binary)
    metrics["reference_agreement"] = reference
    execution.append(reference_execution)
    path = Path(root) / "flight_metrics.json"
    write_json(path, {"metrics":metrics, "execution":execution,
                      "quality_control":prepared.get("quality_control"),
                      "station_bias_policy":prepared.get("station_bias_policy"),
                      "slr_auxiliary_freeze_hash":prepared.get("slr_auxiliary_freeze_hash"),
                      "corrections":prepared.get("corrections"), "limitations":prepared.get("limitations"),
                      "slr_used_in_fit":False})
    valid = bool(metrics.get("predictive", {}).get("valid")) and len(formal) > 0
    return {"status":"complete" if valid else "incomplete" if not len(formal) else "failed", "metrics":metrics,
            "artifacts":[artifact_record("evaluation_metrics", path),
                         artifact_record("independent_slr_predictions", prepared["predictions"]),
                         artifact_record("independent_slr_predictive_covariance", prepared["predictive_covariance"]),
                         reference_artifact],
            **({"error":"Invalid or empty independent SLR predictive distribution"} if not valid else {})}
