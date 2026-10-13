"""Resumable experiment orchestration; incomplete experiments never pass as results.

Simulator and solver imports are lazy so plan/report commands work without Tudat,
GTSAM, JAX, or NumPyro. Every numerical run has an immutable configuration hash.
"""
from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import math
import os
import platform
import subprocess
import time
import traceback
from pathlib import Path
from typing import Any, Callable

import numpy as np

ORBIT_NAMES = ("leo300", "leo500", "leo800", "eccentric")
ATMOSPHERE_NAMES = ("quiet", "disturbed")
COVERAGE_NAMES = ("normal", "blackout")
MODEL_NAMES = ("white", "colored", "density")
WHITE_AMPLITUDE_FACTORS = (0.1, 0.3, 1.0, 3.0, 10.0, 30.0, 100.0)
COLORED_AMPLITUDE_FACTORS = WHITE_AMPLITUDE_FACTORS
OU_CORRELATION_HOURS = (0.5, 2.0, 6.0)
DENSITY_STATIONARY_SIGMAS = (0.1, 0.3, 1.0)
SCHEMA_VERSION = 1
CHI2_95_3 = 7.814727903251179
CHI2_95_6 = 12.591587243743977


def _plain(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _plain(dataclasses.asdict(value))
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return _plain(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def config_hash(config: dict) -> str:
    payload = json.dumps(_plain(config), sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def write_json(path: str | Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(_plain(value), indent=2, sort_keys=True, allow_nan=False) + "\n")
    os.replace(tmp, path)


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def provenance() -> dict:
    """Only record versions and hardware details, never environment credentials."""
    import importlib.metadata
    packages = {}
    for name in ("numpy", "scipy", "jax", "jaxlib", "gtsam", "numpyro", "tudatpy"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    source = Path(__file__).parent
    source_hash = hashlib.sha256()
    project = source.parent.parent
    paths = [*source.glob("*.py"), *(project / "scripts").glob("*.py")]
    for path in sorted(paths):
        source_hash.update(str(path.relative_to(project)).encode())
        source_hash.update(path.read_bytes())
    return {
        "schema_version": SCHEMA_VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "packages": packages,
        "source_sha256": source_hash.hexdigest(),
    }


class Budget:
    """Soft batch deadline: never start another job after the deadline.

    A solver already running finishes and is checkpointed. Use the CLI's
    --job-timeout for a hard per-job timeout in an isolated subprocess.
    """
    def __init__(self, hours: float | None = None, max_jobs: int | None = None):
        self.started = time.monotonic()
        self.seconds = None if hours is None else max(0.0, hours * 3600)
        self.max_jobs = max_jobs
        self.jobs = 0

    @property
    def exhausted(self) -> bool:
        return ((self.seconds is not None and time.monotonic() - self.started >= self.seconds)
                or (self.max_jobs is not None and self.jobs >= self.max_jobs))

    def start_job(self) -> bool:
        if self.exhausted:
            return False
        self.jobs += 1
        return True

    def snapshot(self) -> dict:
        return {"elapsed_seconds": time.monotonic() - self.started,
                "allowed_seconds": self.seconds, "started_jobs": self.jobs,
                "max_jobs": self.max_jobs, "exhausted": self.exhausted}


def generate_one(config: dict, output_dir: str | Path, *, truth_backend="tudat",
                 tudat_python=None, resume=True) -> dict:
    from .simulator import generate
    config = {**config.get("defaults", {}), **config}
    destination = Path(output_dir).resolve()
    request = {"config": config, "truth_backend": truth_backend,
               "source_sha256": provenance()["source_sha256"]}
    fingerprint = config_hash(request)
    checkpoint = destination / "generation.json"
    if resume and checkpoint.exists():
        cached = read_json(checkpoint)
        if (cached.get("request_hash") == fingerprint and cached.get("status") == "complete"
                and Path(cached.get("dataset", "__missing__")).is_file()
                and Path(cached.get("truth", "__missing__")).is_file()
                and cached.get("dataset_sha256") == _sha256_file(Path(cached["dataset"]))
                and cached.get("truth_sha256") == _sha256_file(Path(cached["truth"]))):
            return cached
    destination.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    record = {"request_hash": fingerprint, "request": request, "status": "running"}
    write_json(checkpoint, record)
    try:
        generated = generate(config, destination, truth_backend=truth_backend,
                             tudat_python=tudat_python)
        record.update(_plain(generated))
        record.update(status="complete", elapsed_seconds=time.monotonic() - started)
        record["dataset_sha256"] = _sha256_file(Path(record["dataset"]))
        record["truth_sha256"] = _sha256_file(Path(record["truth"]))
    except Exception as error:
        record.update(status="failed", error=f"{type(error).__name__}: {error}",
                      traceback=traceback.format_exc(), elapsed_seconds=time.monotonic() - started)
        write_json(checkpoint, record)
        raise
    write_json(checkpoint, record)
    return record


def _model_spec(parameters: dict):
    from .config import ModelSpec
    allowed = {field.name for field in dataclasses.fields(ModelSpec)}
    return ModelSpec(**{key: value for key, value in parameters.items() if key in allowed})


def _truth_for_dataset(dataset_path: Path) -> Path | None:
    adjacent = dataset_path.parent / "truth.npz"
    if adjacent.exists():
        return adjacent
    return None


def trajectory_metrics(states: np.ndarray, covariance: np.ndarray,
                       truth: np.ndarray, times: np.ndarray, *,
                       gap_hours=None, log_density_truth=None, model=None) -> tuple[dict, dict]:
    """Metrics use SI units and retain epoch errors for ensemble coverage plots."""
    if len(states) != len(truth):
        raise ValueError("Truth and fitted state epochs differ")
    errors = np.asarray(states[:, :6] - truth[:, :6], dtype=float)
    cov = np.asarray(covariance[:, :6, :6], dtype=float)
    radius = truth[:, :3]
    velocity = truth[:, 3:6]
    rhat = radius / np.linalg.norm(radius, axis=1)[:, None]
    nhat = np.cross(radius, velocity)
    nhat /= np.linalg.norm(nhat, axis=1)[:, None]
    that = np.cross(nhat, rhat)
    rotation = np.stack((rhat, that, nhat), axis=1)
    rtn_error = np.einsum("nij,nj->ni", rotation, errors[:, :3])
    pos_cov = np.einsum("nij,njk,nlk->nil", rotation, cov[:, :3, :3], rotation)
    diagonal = np.diagonal(cov, axis1=1, axis2=2)
    valid_diag = np.isfinite(diagonal) & (diagonal >= 0)
    covered = np.where(valid_diag, np.abs(errors) <= 1.959963984540054 * np.sqrt(np.maximum(diagonal, 0)), np.nan)
    nees = np.full(len(errors), np.nan)
    position_nees = np.full(len(errors), np.nan)
    for index, (error, matrix) in enumerate(zip(errors, cov)):
        if not np.isfinite(matrix).all():
            continue
        try:
            factor = np.linalg.cholesky((matrix + matrix.T) / 2)
            nees[index] = np.sum(np.linalg.solve(factor, error) ** 2)
            pfactor = np.linalg.cholesky((matrix[:3, :3] + matrix[:3, :3].T) / 2)
            position_nees[index] = np.sum(np.linalg.solve(pfactor, error[:3]) ** 2)
        except np.linalg.LinAlgError:
            pass
    elapsed = np.asarray(times) - times[0]
    gap = np.zeros(len(times), dtype=bool)
    if gap_hours is not None:
        gap = (elapsed >= 3600 * gap_hours[0]) & (elapsed <= 3600 * gap_hours[1])
    def rmse(mask, start, stop):
        return (float(np.sqrt(np.mean(np.sum(errors[mask, start:stop] ** 2, axis=1))))
                if np.any(mask) else None)
    all_epochs = np.ones(len(times), dtype=bool)
    metrics = {
        "position_rmse_m": rmse(all_epochs, 0, 3),
        "velocity_rmse_m_s": rmse(all_epochs, 3, 6),
        "rtn_position_rmse_m": np.sqrt(np.mean(rtn_error ** 2, axis=0)).tolist(),
        "gap_position_rmse_m": rmse(gap, 0, 3),
        "outside_gap_position_rmse_m": rmse(~gap, 0, 3),
        "coordinate_95_coverage": float(np.nanmean(covered)) if np.any(valid_diag) else None,
        "position_joint_95_coverage": float(np.mean(position_nees[np.isfinite(position_nees)] <= CHI2_95_3)) if np.isfinite(position_nees).any() else None,
        "state_joint_95_coverage": float(np.mean(nees[np.isfinite(nees)] <= CHI2_95_6)) if np.isfinite(nees).any() else None,
        "mean_nees_6": float(np.nanmean(nees)) if np.isfinite(nees).any() else None,
        "invalid_covariance_epochs": int(np.count_nonzero(~np.isfinite(nees))),
        "epoch_count": len(times),
    }
    epoch = {"times": np.asarray(times), "errors": errors, "rtn_errors": rtn_error,
             "rtn_position_sigma": np.sqrt(np.maximum(np.diagonal(pos_cov, axis1=1, axis2=2), 0)),
             "coordinate_covered": covered, "nees": nees, "position_nees": position_nees,
             "gap": gap}
    if model == "density" and states.shape[1] > 6 and log_density_truth is not None:
        b_error = states[:, 6] - np.asarray(log_density_truth)
        b_variance = covariance[:, 6, 6]
        b_valid = np.isfinite(b_variance) & (b_variance >= 0)
        b_covered = np.where(b_valid, np.abs(b_error) <= 1.959963984540054 * np.sqrt(np.maximum(b_variance, 0)), np.nan)
        metrics["log_density_rmse"] = float(np.sqrt(np.mean(b_error ** 2)))
        metrics["log_density_95_coverage"] = float(np.nanmean(b_covered)) if b_valid.any() else None
        epoch.update(log_density_error=b_error, log_density_covered=b_covered)
    return _plain(metrics), epoch


def fit_one(dataset_path: str | Path, parameters: dict, output_dir: str | Path, *,
            solver="gtsam", options=None, resume=True, truth_path=None,
            reference_path=None, run_context=None) -> dict:
    from .data import load_dataset
    from .solvers import fit, initialize
    destination = Path(output_dir).resolve()
    dataset_path = Path(dataset_path).resolve()
    options = dict(options or {})
    resolved_truth = Path(truth_path) if truth_path else _truth_for_dataset(dataset_path)
    request = {"dataset_sha256": _sha256_file(dataset_path), "parameters": parameters,
               "solver": solver, "options": options,
               "truth_sha256": _sha256_file(resolved_truth) if resolved_truth is not None else None,
               "explicit_reference_sha256": _sha256_file(Path(reference_path)) if reference_path and Path(reference_path).exists() else None,
               "source_sha256": provenance()["source_sha256"]}
    fingerprint = config_hash(request)
    checkpoint = destination / "fit.json"
    if resume and checkpoint.exists():
        cached = read_json(checkpoint)
        if (cached.get("request_hash") == fingerprint and cached.get("status") == "complete"
                and (destination / "fit.npz").exists()):
            cached["fit"] = str(destination / "fit.npz")
            cached["dataset"] = str(dataset_path)
            return cached
    destination.mkdir(parents=True, exist_ok=True)
    record = {"request_hash": fingerprint, "request": request, "status": "running",
              "context": run_context or {}, "dataset": str(dataset_path)}
    write_json(checkpoint, record)
    started = time.monotonic()
    try:
        dataset = load_dataset(dataset_path)
        spec = _model_spec(parameters)
        reference = None
        if solver != "deterministic":
            reference_path = Path(reference_path) if reference_path else dataset_path.parent / f"reference-{config_hash({'dataset': request['dataset_sha256'], 'model': parameters, 'options': options, 'source': request['source_sha256']})}.npy"
            if reference_path.exists():
                reference = np.load(reference_path, allow_pickle=False)
            else:
                reference = initialize(dataset, spec, options=options)
                reference_path.parent.mkdir(parents=True, exist_ok=True)
                np.save(reference_path, np.asarray(reference), allow_pickle=False)
            record["reference_sha256"] = _sha256_file(reference_path)
        result = fit(dataset, spec, solver=solver, options=options, reference=reference)
        np.savez_compressed(destination / "fit.npz", times=dataset.times,
                            states=result.states, covariance=result.covariance)
        record.update(status="complete", objective=float(result.objective),
                      converged=bool(result.converged), iterations=int(result.iterations),
                      solver_seconds=float(result.elapsed_seconds),
                      elapsed_seconds=time.monotonic() - started,
                      metadata=_plain(result.metadata), fit=str(destination / "fit.npz"))
        truth_path = resolved_truth
        if truth_path is not None:
            with np.load(truth_path, allow_pickle=False) as truth:
                truth_states = truth["states"]
                truth_times = truth["times"]
                indices = np.searchsorted(truth_times, dataset.times)
                if np.any(indices >= len(truth_times)) or not np.allclose(truth_times[indices], dataset.times, atol=1e-6, rtol=0):
                    raise ValueError("Truth epochs do not align with dataset epochs")
                meta = dataset.metadata or {}
                gap = meta.get("blackout_hours", (run_context or {}).get("blackout_hours"))
                if (run_context or {}).get("coverage") == "blackout" and gap is None:
                    gap = [11, 13]
                correction = truth["log_density_correction"][indices] if "log_density_correction" in truth else None
                metrics, epochs = trajectory_metrics(result.states, result.covariance,
                    truth_states[indices], dataset.times, gap_hours=gap,
                    log_density_truth=correction, model=parameters.get("model"))
            record["metrics"] = metrics
            record["truth"] = str(truth_path)
            np.savez_compressed(destination / "epoch_metrics.npz", **epochs)
        record["valid_for_comparison"] = bool(result.converged and np.isfinite(result.objective)
            and np.isfinite(result.states).all()
            and (record.get("metrics", {}).get("invalid_covariance_epochs", 0) == 0))
        if solver == "numpyro":
            record["valid_for_comparison"] = bool(record["valid_for_comparison"]
                and result.metadata.get("diagnostics_passed", result.metadata.get("diagnostics_pass",
                    result.metadata.get("diagnostic_status") == "passed")))
    except Exception as error:
        record.update(status="failed", valid_for_comparison=False,
                      error=f"{type(error).__name__}: {error}", traceback=traceback.format_exc(),
                      elapsed_seconds=time.monotonic() - started)
        write_json(checkpoint, record)
        raise
    write_json(checkpoint, record)
    return record


def _observations_subset(dataset, mask):
    observations = {key: (np.asarray(value).copy() if key == "sigma" and np.asarray(value).ndim == 1
                          else np.asarray(value)[mask]) for key, value in dataset.observations.items()}
    if dataclasses.is_dataclass(dataset):
        return dataclasses.replace(dataset, observations=observations)
    import copy
    copied = copy.copy(dataset)
    copied.observations = observations
    return copied


def heldout_predictive_score(states: np.ndarray, covariance: np.ndarray, observations: dict) -> dict:
    """Gaussian held-out predictive NLL with observation and trajectory variance."""
    nodes = np.asarray(observations["node"], dtype=int)
    station_position = np.asarray(observations["station_pos"])
    station_velocity = np.asarray(observations["station_vel"])
    y = np.asarray(observations["y"])
    sigma = np.asarray(observations["sigma"])
    scores = []
    for row, node in enumerate(nodes):
        delta = states[node, :3] - station_position[row]
        speed = states[node, 3:6] - station_velocity[row]
        radius = np.linalg.norm(delta)
        unit = delta / radius
        radial_speed = np.dot(unit, speed)
        prediction = np.array([radius, radial_speed])
        jacobian = np.zeros((2, covariance.shape[-1]))
        jacobian[0, :3] = unit
        jacobian[1, :3] = (speed - radial_speed * unit) / radius
        jacobian[1, 3:6] = unit
        measurement_sigma = sigma[row] if sigma.ndim > 1 else sigma
        predictive = jacobian @ covariance[node] @ jacobian.T + np.diag(measurement_sigma ** 2)
        difference = y[row] - prediction
        sign, logdet = np.linalg.slogdet(predictive)
        if sign <= 0 or not np.isfinite(predictive).all():
            return {"nll": None, "observation_count": len(nodes), "valid": False}
        scores.append(0.5 * (2 * math.log(2 * math.pi) + logdet + difference @ np.linalg.solve(predictive, difference)))
    return {"nll": float(np.mean(scores)) if scores else None,
            "observation_count": len(scores), "valid": bool(scores and np.isfinite(scores).all())}


def calibration_candidates(model: str, nominal_drag: float = 1e-6, cadence: float = 60) -> list[dict]:
    """Independent tuning grid, with white noise broad enough for perigee drag.

    White acceleration RMS factors are 0.1, 0.3, 1, 3, 10, 30, 100 times
    representative nominal drag, with q = acceleration**2 * node cadence.
    Colored acceleration uses the same seven factors and OU times 0.5, 2, 6 h.
    Density uses log standard deviations 0.1, 0.3, 1 and the same OU times.
    """
    nominal_drag = max(abs(nominal_drag), 1e-12)
    if model == "white":
        return [{"model": model, "q_acc": (scale * nominal_drag) ** 2 * cadence}
                for scale in WHITE_AMPLITUDE_FACTORS]
    if model == "colored":
        return [{"model": model, "tau": hours * 3600,
                 "accel_sigma": scale * nominal_drag}
                for hours, scale in itertools.product(OU_CORRELATION_HOURS, COLORED_AMPLITUDE_FACTORS)]
    if model == "density":
        return [{"model": model, "tau": hours * 3600, "sigma": sigma}
                for hours, sigma in itertools.product(OU_CORRELATION_HOURS, DENSITY_STATIONARY_SIGMAS)]
    raise ValueError(f"Unknown stochastic model: {model}")


def calibration_boundary_diagnostics(model: str, winner: dict, entries: list[dict]) -> dict:
    """Profile calibration NLL over the nuisance grid and flag truncated tuning.

    A better upper amplitude endpoint than the next lower profiled amplitude by
    >1e-6 nats/held-out observation blocks a fair final comparison. This small
    numerical tolerance is not a claim of statistical significance. Correlation
    time endpoints are reported for inspection without imposing this gate.
    """
    keys = {"white": ("q_acc",), "colored": ("tau", "accel_sigma"), "density": ("tau", "sigma")}[model]
    amplitude_key = keys[-1]
    boundaries = {}
    for key in keys:
        values = sorted({float(entry["candidate"][key]) for entry in entries})
        chosen = float(winner["candidate"][key])
        boundaries[key] = ("single" if len(values) == 1 else "upper" if chosen == values[-1]
                           else "lower" if chosen == values[0] else "interior")
    eligible = [entry for entry in entries if entry.get("scores") and all(score.get("valid") for score in entry["scores"])]
    profile = {}
    for entry in eligible:
        amplitude = float(entry["candidate"][amplitude_key])
        nll = float(np.mean([score["nll"] for score in entry["scores"]]))
        profile[amplitude] = min(profile.get(amplitude, math.inf), nll)
    selected = float(winner["candidate"][amplitude_key])
    lower = [value for value in profile if value < selected]
    improvement = None
    if boundaries[amplitude_key] == "upper" and lower:
        improvement = profile[max(lower)] - profile[selected]
    improving = bool(improvement is not None and improvement > 1e-6)
    warning = (f"Selected {amplitude_key} is the upper grid endpoint and improves profiled held-out NLL "
               f"by {improvement:.6g} nats/observation versus the next lower amplitude; extend independent calibration."
               if improving else None)
    return {"grid_boundaries": boundaries, "amplitude_parameter": amplitude_key,
            "upper_amplitude_boundary": boundaries[amplitude_key] == "upper",
            "upper_boundary_improving": improving,
            "upper_boundary_nll_improvement": improvement,
            "profiled_amplitude_nll": [{"amplitude": value, "mean_predictive_nll": profile[value]}
                                       for value in sorted(profile)],
            "boundary_warning": warning}


def _nominal_drag(config: dict, generation: dict) -> float:
    # Representative equatorial circular speed at the prescribed orbit altitude.
    # This scale uses the known model, never simulated truth or test observations.
    from .config import AREA, CD, EARTH_RADIUS, MASS, MU, OMEGA, RHO_500, SCALE_HEIGHT
    altitude = {"leo300": 300e3, "leo500": 500e3, "leo800": 800e3, "eccentric": 550e3}[config["orbit"]]
    radius = EARTH_RADIUS + altitude
    density = RHO_500 * np.exp(-(altitude - 500e3) / SCALE_HEIGHT)
    relative_speed = np.sqrt(MU / radius) - OMEGA * radius
    return float(0.5 * CD * AREA / MASS * density * relative_speed ** 2)


def calibrate(config: dict, output_dir: str | Path, *, truth_backend="tudat", tudat_python=None,
              budget_hours=None, max_jobs=None, quick=False, resume=True,
              solver_options=None) -> dict:
    from .data import load_dataset, save_dataset
    config = {**config.get("defaults", {}), **config}
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    budget = Budget(budget_hours, max_jobs)
    seed_count = 1 if quick else 5
    calibration_seeds = config.get("calibration", {}).get("seeds", list(range(10000, 10005)))
    if len(calibration_seeds) < seed_count:
        raise ValueError("Calibration requires five distinct seeds")
    if len(set(calibration_seeds)) != len(calibration_seeds):
        raise ValueError("Calibration seeds must be distinct")
    orbits = config.get("orbits", list(ORBIT_NAMES))
    candidates_per_seed = sum(1 if quick else len(calibration_candidates(model)) for model in MODEL_NAMES)
    manifest = {"kind": "calibration", "config": config, "quick": quick,
                "provenance": provenance(), "status": "running", "selections": {},
                "runs": [], "expected_fits": len(orbits) * seed_count * candidates_per_seed,
                "candidate_counts": {model: 1 if quick else len(calibration_candidates(model)) for model in MODEL_NAMES},
                "grid_definition": {"white_amplitude_factors": list(WHITE_AMPLITUDE_FACTORS),
                                    "colored_amplitude_factors": list(COLORED_AMPLITUDE_FACTORS),
                                    "ou_correlation_hours": list(OU_CORRELATION_HOURS),
                                    "density_stationary_sigmas": list(DENSITY_STATIONARY_SIGMAS),
                                    "white_psd_rule": "q_acc = (factor * nominal_drag_m_s2)**2 * cadence_seconds"},
                "truth_backend": truth_backend, "calibration_seeds": calibration_seeds[:seed_count],
                "integration_substep_seconds": float(config.get("substep", 2.5))}
    checkpoint = destination / "calibration.json"
    for orbit in orbits:
        scores = {model: {} for model in MODEL_NAMES}
        for seed_index in range(seed_count):
            if budget.exhausted:
                break
            case = {**config, "orbit": orbit, "atmosphere": "disturbed" if seed_index % 2 else "quiet",
                    "coverage": "normal", "duration_hours": 6.0,
                    "truth_profile": "controlled", "seed": int(calibration_seeds[seed_index]),
                    "pulse_center_hours": 3.0, "pulse_width_hours": 0.5}
            case = {key: value for key, value in case.items() if key not in
                    ("orbits", "atmospheres", "coverages", "models", "defaults", "calibration", "stress", "evaluation_seeds")}
            data_dir = destination / "data" / f"{orbit}-seed{case['seed']}"
            try:
                generated = generate_one(case, data_dir, truth_backend=truth_backend,
                                         tudat_python=tudat_python, resume=resume)
                dataset = load_dataset(generated["dataset"])
                observation_count = len(dataset.observations["node"])
                if observation_count < 10:
                    raise ValueError("Calibration requires at least 10 observations for train/holdout split")
                holdout = np.arange(observation_count) % 5 == 4
                train = _observations_subset(dataset, ~holdout)
                train_path = data_dir / "train.npz"
                save_dataset(train, train_path)
                heldout = _observations_subset(dataset, holdout).observations
                # Freeze candidate scales from the first calibration arc, never test data.
                scale_file = destination / f"{orbit}-nominal-drag.json"
                if scale_file.exists():
                    nominal_drag = read_json(scale_file)["nominal_drag_m_s2"]
                else:
                    nominal_drag = _nominal_drag(case, generated)
                    write_json(scale_file, {"nominal_drag_m_s2": nominal_drag,
                                           "source_dataset": generated["dataset"]})
            except Exception as error:
                manifest["runs"].append({"orbit": orbit, "seed": case["seed"], "status": "failed",
                                         "error": f"{type(error).__name__}: {error}"})
                write_json(checkpoint, manifest)
                continue
            for model in MODEL_NAMES:
                candidates = calibration_candidates(model, nominal_drag, config.get("cadence", 60))
                if quick:
                    candidates = [candidates[len(candidates) // 2]]
                for candidate in candidates:
                    candidate["substep"] = float(config.get("substep", 2.5))
                    key = config_hash(candidate)
                    target = destination / "fits" / orbit / model / key / f"seed{case['seed']}"
                    score_path = target / "predictive_score.json"
                    score_record = None
                    score_hash = config_hash({"dataset_sha256": _sha256_file(train_path),
                                              "candidate": candidate, "options": solver_options or {},
                                              "source_sha256": manifest["provenance"]["source_sha256"]})
                    if resume and score_path.exists():
                        cached = read_json(score_path)
                        if cached.get("request_hash") == score_hash:
                            score_record = cached
                    if score_record is None:
                        if not budget.start_job():
                            break
                        try:
                            fitted = fit_one(train_path, candidate, target, options=solver_options,
                                             resume=resume, truth_path=generated["truth"],
                                             run_context={"orbit": orbit, "model": model, "seed": case["seed"], "stage": "calibration"})
                            with np.load(fitted["fit"], allow_pickle=False) as arrays:
                                score_record = heldout_predictive_score(arrays["states"], arrays["covariance"], heldout)
                            score_record["valid"] = bool(score_record["valid"] and fitted["converged"])
                            score_record.update(candidate=candidate, fit=str(target / "fit.json"),
                                                request_hash=score_hash,
                                                source_sha256=manifest["provenance"]["source_sha256"])
                            write_json(score_path, score_record)
                        except Exception as error:
                            score_record = {"valid": False, "nll": None, "candidate": candidate,
                                            "error": f"{type(error).__name__}: {error}"}
                    scores[model].setdefault(key, {"candidate": candidate, "scores": []})["scores"].append(score_record)
                    manifest["runs"].append({"orbit": orbit, "model": model, "seed": case["seed"],
                                             "candidate_hash": key, **score_record})
                    manifest["budget"] = budget.snapshot()
                    write_json(checkpoint, manifest)
                if budget.exhausted:
                    break
        selection = {}
        for model, entries in scores.items():
            eligible = [entry for entry in entries.values()
                        if len(entry["scores"]) == seed_count and all(score["valid"] for score in entry["scores"])]
            if eligible:
                winner = min(eligible, key=lambda entry: np.mean([s["nll"] for s in entry["scores"]]))
                selection[model] = {"parameters": winner["candidate"],
                                    "mean_predictive_nll": float(np.mean([s["nll"] for s in winner["scores"]])),
                                    "calibration_seeds": seed_count,
                                    "full_grid_complete": len(entries) == len(calibration_candidates(model))
                                        and all(len(e["scores"]) == seed_count for e in entries.values())}
                selection[model].update(calibration_boundary_diagnostics(model, winner,
                    [entry for entry in entries.values() if len(entry["scores"]) == seed_count]))
        manifest["selections"][orbit] = selection
        write_json(checkpoint, manifest)
    manifest["budget"] = budget.snapshot()
    manifest["invalid_candidate_runs"] = sum(not run.get("valid", False) for run in manifest["runs"])
    manifest["complete"] = (not quick and len(manifest["runs"]) == manifest["expected_fits"]
                            and all(len(s) == 3 and all(v["full_grid_complete"] for v in s.values())
                                    for s in manifest["selections"].values()))
    manifest["boundary_warnings"] = [{"orbit": orbit, "model": model, "warning": selected["boundary_warning"]}
        for orbit, selections in manifest["selections"].items() for model, selected in selections.items()
        if selected.get("boundary_warning")]
    manifest["comparison_grid_adequate"] = bool(manifest["complete"] and not manifest["boundary_warnings"])
    manifest["status"] = "complete" if manifest["complete"] else "incomplete"
    write_json(checkpoint, manifest)
    return manifest


def cell_matrix(config: dict, seeds: int) -> list[dict]:
    seed_values = config.get("evaluation_seeds", list(range(int(config.get("test_seed_offset", 42)), int(config.get("test_seed_offset", 42)) + seeds)))
    if len(seed_values) < seeds:
        raise ValueError(f"Configuration provides {len(seed_values)} evaluation seeds but {seeds} were requested")
    seed_values = seed_values[:seeds]
    if len(set(seed_values)) != len(seed_values):
        raise ValueError("Evaluation seeds must be distinct")
    calibration_seeds = config.get("calibration", {}).get("seeds", list(range(10000, 10005)))
    if set(seed_values) & set(calibration_seeds):
        raise ValueError("Evaluation and calibration seeds must be disjoint")
    cells = []
    for orbit, atmosphere, coverage, seed in itertools.product(
            config.get("orbits", ORBIT_NAMES), config.get("atmospheres", ATMOSPHERE_NAMES),
            config.get("coverages", COVERAGE_NAMES), seed_values):
        cells.append({"orbit": orbit, "atmosphere": atmosphere, "coverage": coverage,
                      "seed": int(seed)})
    return cells


def choose_seed_count(pilot_seconds: list[float], remaining_seconds: float, workers=1,
                      cells_per_seed=64, reserve_fraction=0.25, fixed_jobs=0) -> dict:
    """Choose among prespecified counts; no partial count is silently promoted."""
    successful = np.asarray([value for value in pilot_seconds if value > 0 and np.isfinite(value)])
    if successful.size == 0:
        return {"seeds": None, "reason": "No successful pilot timings", "affordable": False}
    seconds_per_job = float(np.quantile(successful, 0.9))
    usable = max(0.0, remaining_seconds * (1 - reserve_fraction))
    estimates = {str(n): (n * cells_per_seed + fixed_jobs) * seconds_per_job / max(1, workers) for n in (5, 10, 20)}
    affordable = [n for n in (5, 10, 20) if estimates[str(n)] <= usable]
    chosen = max(affordable) if affordable else None
    return {"seeds": chosen, "affordable": bool(affordable), "estimated_seconds": estimates,
            "pilot_p90_seconds": seconds_per_job, "usable_seconds": usable,
            "assumed_workers": workers,
            "reason": "Largest prespecified count fitting reserved budget" if affordable else "Budget does not cover five seeds; keep pilot labeled incomplete"}


def validate_calibration(calibration, config, truth_backend, source_sha256=None):
    """Reject stale, diagnostic-only, integrator-mismatched, or leaked selection."""
    config = {**config.get("defaults", {}), **config}
    if not calibration.get("complete", False):
        raise ValueError("Calibration is incomplete; finish it or omit it for exploratory defaults")
    if calibration.get("comparison_grid_adequate") is False:
        raise ValueError("Calibration still improves at an upper amplitude boundary; extend independent tuning before final comparisons")
    if calibration.get("truth_backend") != truth_backend:
        raise ValueError("Calibration truth backend does not match this benchmark")
    expected_source = source_sha256 or provenance()["source_sha256"]
    if calibration.get("provenance", {}).get("source_sha256") != expected_source:
        raise ValueError("Calibration source snapshot differs from this benchmark")
    substep = float(config.get("substep", 2.5))
    if calibration.get("integration_substep_seconds") != substep:
        raise ValueError("Calibration integration substep differs from this benchmark")
    used_seeds = calibration.get("calibration_seeds")
    if used_seeds is None or len(set(used_seeds)) < 5:
        raise ValueError("Calibration must record five independent calibration seeds")
    evaluation = config.get("evaluation_seeds", range(int(config.get("test_seed_offset", 42)), int(config.get("test_seed_offset", 42)) + 20))
    if set(used_seeds) & set(evaluation):
        raise ValueError("Calibration and evaluation seed sets overlap")
    for orbit in config.get("orbits", ORBIT_NAMES):
        for model in config.get("models", MODEL_NAMES):
            selection = calibration.get("selections", {}).get(orbit, {}).get(model)
            if not selection or not selection.get("full_grid_complete", False):
                raise ValueError(f"Calibration is missing a completed {orbit}/{model} selection")
            if selection.get("parameters", {}).get("substep", substep) != substep:
                raise ValueError(f"Selected {orbit}/{model} integrator differs from this benchmark")
    return True


def benchmark(config: dict, output_dir: str | Path, *, calibration_path=None,
              truth_backend="tudat", tudat_python=None, seeds=5, pilot=False,
              budget_hours=12.0, max_jobs=None, resume=True, solver_options=None,
              include_ieks=True, job_timeout=None, workers=1) -> dict:
    """Run bounded independent shards; cache JIT kernels within each worker."""
    config = {**config.get("defaults", {}), **config}
    if workers > 1:
        return _parallel_benchmark(config, output_dir, calibration_path=calibration_path,
            truth_backend=truth_backend, tudat_python=tudat_python, seeds=seeds, pilot=pilot,
            budget_hours=budget_hours, max_jobs=max_jobs, resume=resume,
            solver_options=solver_options, include_ieks=include_ieks, job_timeout=job_timeout,
            workers=workers)
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    budget = Budget(budget_hours, max_jobs)
    calibration = read_json(calibration_path) if calibration_path else None
    if calibration is not None:
        validate_calibration(calibration, config, truth_backend)
    count = 2 if pilot else int(seeds)
    if not pilot and count not in (5, 10, 20):
        raise ValueError("Final benchmark seeds must be one of 5, 10, 20; use --pilot for two seeds")
    cells = cell_matrix(config, count)
    equivalence_seeds = sorted({cell["seed"] for cell in cells})[:2]
    shard_count = int(config.get("shard_count", 1))
    shard_index = int(config.get("shard_index", 0))
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be in [0, shard_count)")
    cells = [cell for index, cell in enumerate(cells) if index % shard_count == shard_index]
    models = config.get("models", list(MODEL_NAMES))
    metadata = provenance()
    manifest = {"kind": "benchmark", "config": config, "provenance": metadata,
                "status": "running", "pilot": pilot, "seed_count": count,
                "calibrated": calibration is not None, "runs": [], "datasets": [],
                "expected_primary_runs": len(cells) * (len(models) + 1),
                "expected_ieks_pairs": sum(cell["seed"] in equivalence_seeds for cell in cells) * len(models),
                "truth_backend": truth_backend, "workers_hint": workers,
                "actual_workers": 1, "shard_index": shard_index, "shard_count": shard_count,
                "calibration": str(calibration_path) if calibration_path else None}
    manifest["calibration_sha256"] = _sha256_file(Path(calibration_path)) if calibration_path else None
    checkpoint = destination / "benchmark.json"
    base_config = {key: value for key, value in config.items() if key not in
                   ("orbits", "atmospheres", "coverages", "models", "test_seed_offset", "shard_count", "shard_index",
                    "defaults", "calibration", "stress", "evaluation_seeds")}
    fit_durations = []
    for cell in cells:
        if budget.exhausted:
            break
        case = {**base_config, **cell}
        case_id = f"{cell['orbit']}-{cell['atmosphere']}-{cell['coverage']}-seed{cell['seed']}"
        data_dir = destination / "data" / case_id
        try:
            generated = generate_one(case, data_dir, truth_backend=truth_backend,
                                     tudat_python=tudat_python, resume=resume)
            manifest["datasets"].append({"case": cell, "dataset": generated["dataset"],
                                          "metadata": generated.get("metadata", {}), "status": "complete"})
        except Exception as error:
            manifest["datasets"].append({"case": cell, "status": "failed",
                                          "error": f"{type(error).__name__}: {error}"})
            write_json(checkpoint, manifest)
            continue
        jobs = [("baseline", "deterministic")]
        jobs.extend((model, "gtsam") for model in models)
        # IEKS equivalence subset: first two seeds in every scientific cell.
        if include_ieks and cell["seed"] in equivalence_seeds:
            jobs.extend((model, "ieks") for model in models)
        for model, solver in jobs:
            parameters = {"model": "white" if model == "baseline" else model,
                          "substep": float(config.get("substep", 2.5))}
            if calibration is not None and model != "baseline":
                parameters.update(calibration["selections"][cell["orbit"]][model]["parameters"])
            run_context = {**cell, "model": model, "solver": solver,
                           "truth_profile": case.get("truth_profile", "controlled"),
                           "duration_hours": case.get("duration_hours", 24.0),
                           "blackout_hours": case.get("blackout_hours", [11, 13]) if cell["coverage"] == "blackout" else None}
            run_dir = destination / "fits" / case_id / f"{model}-{solver}"
            # Completed cached jobs do not consume the numerical-job budget.
            existing = run_dir / "fit.json"
            cached = read_json(existing) if resume and existing.exists() else None
            if cached and cached.get("status") == "complete" and cached.get("request", {}).get("source_sha256") == metadata["source_sha256"] and cached.get("request", {}).get("parameters") == parameters and cached.get("request", {}).get("dataset_sha256") == generated.get("dataset_sha256") and cached.get("request", {}).get("truth_sha256") == generated.get("truth_sha256") and cached.get("request", {}).get("options") == dict(solver_options or {}) and (run_dir / "fit.npz").exists():
                fitted = cached
            else:
                if not budget.start_job():
                    break
                try:
                    if job_timeout is None:
                        fitted = fit_one(generated["dataset"], parameters, run_dir, solver=solver,
                                         options=solver_options, resume=resume, truth_path=generated["truth"],
                                         run_context=run_context)
                    else:
                        fitted = _fit_subprocess(generated["dataset"], parameters, run_dir, solver,
                                                 solver_options, generated["truth"], run_context, job_timeout)
                except Exception as error:
                    fitted = read_json(existing) if existing.exists() else {
                        "status": "failed", "valid_for_comparison": False,
                        "error": f"{type(error).__name__}: {error}", "context": run_context}
            if fitted.get("status") == "complete" and solver == "gtsam":
                fit_durations.append(fitted.get("elapsed_seconds", 0))
            manifest["runs"].append({"path": str(existing), "context": run_context,
                                      "status": fitted.get("status"), "converged": fitted.get("converged", False),
                                      "valid_for_comparison": fitted.get("valid_for_comparison", False),
                                      "elapsed_seconds": fitted.get("elapsed_seconds"),
                                      "metrics": fitted.get("metrics", {}), "error": fitted.get("error")})
            manifest["budget"] = budget.snapshot()
            write_json(checkpoint, manifest)
        write_json(checkpoint, manifest)
    primary = [run for run in manifest["runs"] if run["context"]["solver"] != "ieks"]
    manifest["primary_complete"] = (len(primary) == manifest["expected_primary_runs"]
                                     and all(run["status"] == "complete" for run in primary))
    manifest["all_primary_converged"] = bool(primary and all(run["valid_for_comparison"] for run in primary))
    manifest["solver_equivalence"] = solver_equivalence(manifest["runs"], manifest["expected_ieks_pairs"])
    manifest["valid_benchmark"] = bool(manifest["primary_complete"] and manifest["all_primary_converged"]
                                        and manifest["calibrated"] and not pilot and shard_count == 1
                                        and truth_backend == "tudat" and manifest["solver_equivalence"]["passed"])
    manifest["status"] = "complete" if manifest["primary_complete"] else "incomplete"
    manifest["budget"] = budget.snapshot()
    if pilot:
        manifest["seed_recommendation"] = choose_seed_count(fit_durations,
            max(0, budget_hours * 3600 - manifest["budget"]["elapsed_seconds"]),
            workers=1, cells_per_seed=len(cell_matrix(config, 1)) * (len(models) + 1),
            fixed_jobs=manifest["expected_ieks_pairs"])
    write_json(checkpoint, manifest)
    return manifest


def _worker_resource_limits():
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["JAX_PLATFORMS"] = "cpu"
    os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    if hasattr(os, "sched_getaffinity"):
        import multiprocessing
        cpus = sorted(os.sched_getaffinity(0))
        identity = multiprocessing.current_process()._identity
        index = (identity[-1] - 1) if identity else 0
        selected = [cpus[(2 * index) % len(cpus)], cpus[(2 * index + 1) % len(cpus)]]
        os.sched_setaffinity(0, selected)


def _benchmark_worker(payload):
    return benchmark(**payload)


def _parallel_benchmark(config, output_dir, *, workers, **options):
    import concurrent.futures
    import multiprocessing
    destination = Path(output_dir).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    workers = int(workers)
    if workers < 1 or workers > 8:
        raise ValueError("workers must be between 1 and 8 on a shared host")
    # Apply before spawn so numerical libraries honor these at import time.
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["JAX_PLATFORMS"] = "cpu"
    os.environ["XLA_PYTHON_CLIENT_PREALLOCATE"] = "false"
    results = []
    failures = []
    started = time.monotonic()
    parent_shard = int(config.get("shard_index", 0))
    parent_count = int(config.get("shard_count", 1))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers,
            mp_context=multiprocessing.get_context("spawn"), initializer=_worker_resource_limits) as pool:
        futures = {}
        for index in range(workers):
            child_options = dict(options)
            if options.get("max_jobs") is not None:
                child_options["max_jobs"] = options["max_jobs"] // workers + (index < options["max_jobs"] % workers)
            child_config = {**config, "shard_index": parent_shard * workers + index,
                            "shard_count": parent_count * workers}
            payload = {"config": child_config, "output_dir": str(destination / f"worker-{index:02d}"),
                       "workers": 1, **child_options}
            futures[pool.submit(_benchmark_worker, payload)] = index
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                failures.append({"worker": index, "error": f"{type(error).__name__}: {error}"})
            write_json(destination / "benchmark.json", {"kind": "benchmark", "status": "running",
                "config": config, "worker_count": workers, "completed_workers": len(results),
                "worker_failures": failures, "runs": [run for result in results for run in result["runs"]],
                "valid_benchmark": False})
    primary_count = sum(result["expected_primary_runs"] for result in results)
    all_runs = [run for result in results for run in result["runs"]]
    all_datasets = [row for result in results for row in result["datasets"]]
    complete = len(results) == workers and all(result["primary_complete"] for result in results)
    calibrated = bool(results and all(result["calibrated"] for result in results))
    converged = bool(results and all(result["all_primary_converged"] for result in results))
    expected_pairs = sum(result["expected_ieks_pairs"] for result in results)
    equivalence = solver_equivalence(all_runs, expected_pairs)
    manifest = {"kind": "benchmark", "config": config, "status": "complete" if complete else "incomplete",
                "provenance": provenance(), "runs": all_runs, "datasets": all_datasets,
                "pilot": options["pilot"], "seed_count": 2 if options["pilot"] else options["seeds"],
                "calibrated": calibrated, "calibration": str(options.get("calibration_path")),
                "calibration_sha256": _sha256_file(Path(options["calibration_path"])) if options.get("calibration_path") else None,
                "primary_complete": complete, "all_primary_converged": converged,
                "expected_primary_runs": primary_count, "actual_workers": workers,
                "expected_ieks_pairs": expected_pairs, "solver_equivalence": equivalence,
                "worker_failures": failures, "truth_backend": options["truth_backend"],
                "shard_count": parent_count, "shard_index": parent_shard,
                "valid_benchmark": bool(complete and calibrated and converged and not options["pilot"]
                                        and parent_count == 1 and options["truth_backend"] == "tudat" and equivalence["passed"]),
                "budget": {"elapsed_seconds": time.monotonic() - started,
                           "allowed_seconds": options["budget_hours"] * 3600,
                           "started_jobs": sum(result["budget"]["started_jobs"] for result in results),
                           "max_jobs": options.get("max_jobs")}}
    if options["pilot"]:
        timings = [run["elapsed_seconds"] for run in all_runs if run["status"] == "complete"
                   and run["context"]["solver"] == "gtsam" and run.get("elapsed_seconds")]
        manifest["seed_recommendation"] = choose_seed_count(timings,
            max(0, options["budget_hours"] * 3600 - manifest["budget"]["elapsed_seconds"]),
            workers=workers, cells_per_seed=len(cell_matrix(config, 1)) * (len(config.get("models", MODEL_NAMES)) + 1),
            fixed_jobs=expected_pairs)
    write_json(destination / "benchmark.json", manifest)
    return manifest


def _fit_subprocess(dataset, parameters, output_dir, solver, options, truth, context, timeout):
    import sys
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    request = {"dataset": str(dataset), "parameters": parameters, "solver": solver,
               "options": options or {}, "truth": str(truth), "context": context}
    path = destination / "job.json"
    write_json(path, request)
    command = [sys.executable, "-m", "orbit_poc.cli", "_fit-job", "--job", str(path),
               "--output-dir", str(destination)]
    try:
        with (destination / "solver.log").open("w") as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                                       timeout=float(timeout), check=False)
        if completed.returncode != 0:
            raise RuntimeError(f"Solver exited with code {completed.returncode}; see {destination / 'solver.log'}")
    except subprocess.TimeoutExpired:
        write_json(destination / "fit.json", {"status": "timeout", "valid_for_comparison": False,
                   "error": f"Per-job deadline of {timeout}s exceeded", "context": context,
                   "elapsed_seconds": float(timeout)})
        raise
    return read_json(destination / "fit.json")


def paired_statistics(runs: list[dict], metric="position_rmse_m", seed=731) -> list[dict]:
    """Paired seed bootstrap; time samples are never treated as independent seeds."""
    groups = {}
    for run in runs:
        context = run.get("context", {})
        if not run.get("valid_for_comparison") or context.get("solver") not in ("gtsam", "deterministic"):
            continue
        value = run.get("metrics", {}).get(metric)
        if value is None:
            continue
        key = tuple(context.get(key) for key in ("orbit", "atmosphere", "coverage"))
        groups.setdefault(key, {}).setdefault(context.get("model"), {})[context.get("seed")] = value
    rng = np.random.default_rng(seed)
    rows = []
    for key, models in groups.items():
        for first, second in itertools.combinations(sorted(models), 2):
            common = sorted(set(models[first]) & set(models[second]))
            differences = np.array([models[first][s] - models[second][s] for s in common])
            if not len(differences):
                continue
            interval = None
            if len(differences) >= 5:
                draws = rng.choice(differences, size=(2000, len(differences)), replace=True).mean(axis=1)
                interval = np.quantile(draws, [0.025, 0.975]).tolist()
            rows.append({"orbit": key[0], "atmosphere": key[1], "coverage": key[2],
                         "model_a": first, "model_b": second, "metric": metric,
                         "paired_seed_count": len(common), "mean_difference_a_minus_b": float(differences.mean()),
                         "bootstrap_95_interval": interval,
                         "interpretation": "Negative favors model_a for an error metric; descriptive bootstrap, no multiple-comparison claim"})
    return rows


def solver_equivalence(runs, expected_pairs):
    pairs = {}
    for row in runs:
        context = row.get("context", {})
        if context.get("solver") not in ("gtsam", "ieks"):
            continue
        key = tuple(context.get(k) for k in ("orbit", "atmosphere", "coverage", "model", "seed"))
        pairs.setdefault(key, {})[context["solver"]] = row
    results = []
    for key, entries in pairs.items():
        if "ieks" not in entries:
            continue
        row = dict(zip(("orbit", "atmosphere", "coverage", "model", "seed"), key))
        row.update(both_valid=False, passed=False)
        if set(entries) == {"gtsam", "ieks"}:
            row["both_valid"] = all(value.get("valid_for_comparison") for value in entries.values())
            if row["both_valid"]:
                try:
                    gpath, ipath = Path(entries["gtsam"]["path"]), Path(entries["ieks"]["path"])
                    ga, ie = read_json(gpath), read_json(ipath)
                    with np.load(gpath.parent / "fit.npz") as g, np.load(ipath.parent / "fit.npz") as i:
                        difference = g["states"] - i["states"]
                        variance = np.maximum(np.diagonal(g["covariance"], axis1=1, axis2=2),
                                              np.diagonal(i["covariance"], axis1=1, axis2=2))
                        if np.any(variance <= 0) or not np.isfinite(variance).all():
                            raise ValueError("Posterior standard deviations must be finite and positive")
                        row["maximum_posterior_sigma_difference"] = float(np.max(np.abs(difference) / np.sqrt(variance)))
                        row["maximum_position_difference_m"] = float(np.max(np.linalg.norm(difference[:, :3], axis=1)))
                        row["maximum_velocity_difference_m_s"] = float(np.max(np.linalg.norm(difference[:, 3:6], axis=1)))
                    row["relative_objective_difference"] = float(abs(ga["objective"] - ie["objective"]) / max(1, abs(ga["objective"])))
                    row["same_reference"] = bool(ga.get("reference_sha256") and ga["reference_sha256"] == ie.get("reference_sha256"))
                    row["passed"] = bool(row["same_reference"] and row["maximum_posterior_sigma_difference"] < 0.01
                                          and row["relative_objective_difference"] < 1e-4)
                except Exception as error:
                    row["error"] = f"{type(error).__name__}: {error}"
        results.append(row)
    passing = sum(row["passed"] for row in results)
    return {"expected_pairs": int(expected_pairs), "observed_pairs": len(results), "passing_pairs": passing,
            "complete": len(results) == expected_pairs, "passed": expected_pairs > 0 and passing == expected_pairs,
            "thresholds": {"posterior_sigma_difference": 0.01, "relative_objective_difference": 1e-4},
            "pairs": results}


def relocate_run_paths(runs, source):
    """Resolve copied host artifacts by their unique case/model filename suffix."""
    source = Path(source).resolve()
    candidates = None
    relocated = []
    for original in runs:
        row = dict(original)
        supplied = Path(row.get("path", "__missing__"))
        if not supplied.exists():
            if candidates is None:
                candidates = list(source.rglob("fit.json"))
            matches = [path for path in candidates if path.parts[-3:] == supplied.parts[-3:]]
            if len(matches) == 1:
                row["path"] = str(matches[0])
        relocated.append(row)
    return relocated


def merge_benchmarks(paths, output_dir):
    records = []
    for item in paths:
        path = Path(item).resolve()
        path = path / "benchmark.json" if path.is_dir() else path
        record = read_json(path)
        record["runs"] = relocate_run_paths(record.get("runs", []), path.parent)
        records.append(record)
    if not records:
        raise ValueError("At least one benchmark manifest is required")
    signatures = {(item.get("provenance", {}).get("source_sha256"), item.get("calibration_sha256"),
                   item.get("seed_count"), item.get("truth_backend"), item.get("pilot")) for item in records}
    if len(signatures) != 1:
        raise ValueError("Benchmark source, calibration, seeds, truth backend, or stage differs")
    science_keys = ("duration_hours", "cadence", "truth_profile", "substep", "atmospheres", "coverages", "models", "evaluation_seeds")
    if len({config_hash({key: item.get("config", {}).get(key) for key in science_keys}) for item in records}) != 1:
        raise ValueError("Scientific configurations differ across benchmark parts")
    seen = set()
    runs = []
    for item in records:
        for run in item["runs"]:
            context = run.get("context", {})
            key = tuple(context.get(k) for k in ("orbit", "atmosphere", "coverage", "seed", "model", "solver"))
            if key in seen:
                raise ValueError(f"Duplicate benchmark case: {key}")
            seen.add(key)
            runs.append(run)
    config = dict(records[0].get("config", {}))
    config["orbits"] = sorted({orbit for item in records for orbit in item.get("config", {}).get("orbits", ORBIT_NAMES)})
    expected_primary = sum(item["expected_primary_runs"] for item in records)
    expected_pairs = sum(item["expected_ieks_pairs"] for item in records)
    equivalence = solver_equivalence(runs, expected_pairs)
    complete = all(item.get("primary_complete", False) for item in records)
    converged = all(item.get("all_primary_converged", False) for item in records)
    calibrated = all(item.get("calibrated", False) for item in records)
    result = {"kind": "benchmark", "config": config, "provenance": records[0]["provenance"],
              "seed_count": records[0]["seed_count"], "pilot": records[0]["pilot"],
              "truth_backend": records[0]["truth_backend"], "calibration_sha256": records[0].get("calibration_sha256"),
              "calibrated": calibrated, "primary_complete": complete, "all_primary_converged": converged,
              "expected_primary_runs": expected_primary, "expected_ieks_pairs": expected_pairs,
              "solver_equivalence": equivalence, "runs": runs,
              "datasets": [row for item in records for row in item.get("datasets", [])],
              "status": "complete" if complete else "incomplete",
              "sources": [str(Path(path).resolve()) for path in paths],
              "valid_benchmark": bool(complete and converged and calibrated and equivalence["passed"]
                                      and not records[0]["pilot"] and records[0]["truth_backend"] == "tudat")}
    write_json(Path(output_dir) / "benchmark.json", result)
    return result


def merge_calibrations(paths, output_dir) -> dict:
    """Merge disjoint per-orbit calibration jobs without weakening completeness."""
    inputs = [read_json(Path(path) / "calibration.json" if Path(path).is_dir() else path) for path in paths]
    if not inputs:
        raise ValueError("At least one calibration manifest is required")
    source_hashes = {item.get("provenance", {}).get("source_sha256") for item in inputs}
    if len(source_hashes) != 1:
        raise ValueError("Calibration sources differ; rerun with a consistent source snapshot")
    compatibility = {(item.get("truth_backend"), item.get("integration_substep_seconds"),
                      tuple(item.get("calibration_seeds", []))) for item in inputs}
    if len(compatibility) != 1:
        raise ValueError("Calibration truth backend, integration substep, or seeds differ")
    selections = {}
    for item in inputs:
        for orbit, selection in item.get("selections", {}).items():
            if orbit in selections:
                raise ValueError(f"Duplicate calibration orbit: {orbit}")
            selections[orbit] = selection
    complete = all(item.get("complete", False) for item in inputs)
    merged = {"kind": "calibration", "status": "complete" if complete else "incomplete",
              "complete": complete, "quick": any(item.get("quick") for item in inputs),
              "provenance": inputs[0]["provenance"],
              "truth_backend": inputs[0].get("truth_backend"),
              "integration_substep_seconds": inputs[0].get("integration_substep_seconds"),
              "calibration_seeds": inputs[0].get("calibration_seeds", []),
              "config": {**inputs[0]["config"], "orbits": sorted(selections)},
              "selections": selections, "runs": [run for item in inputs for run in item["runs"]],
              "expected_fits": sum(item["expected_fits"] for item in inputs),
              "invalid_candidate_runs": sum(item.get("invalid_candidate_runs", 0) for item in inputs),
              "comparison_grid_adequate": all(item.get("comparison_grid_adequate", item.get("complete", False)) for item in inputs),
              "boundary_warnings": [warning for item in inputs for warning in item.get("boundary_warnings", [])],
              "candidate_counts": inputs[0].get("candidate_counts"),
              "grid_definition": inputs[0].get("grid_definition"),
              "sources": [str(Path(path).resolve()) for path in paths]}
    write_json(Path(output_dir) / "calibration.json", merged)
    return merged


def run_scaling(config: dict, output_dir: str | Path, *, truth_backend="tudat", tudat_python=None,
                solver_options=None, budget_hours=2.0, resume=True) -> dict:
    destination = Path(output_dir).resolve()
    budget = Budget(budget_hours)
    rows = []
    for duration in (6.0, 12.0, 24.0):
        if not budget.start_job():
            break
        case = {**config, "orbit": "leo500", "atmosphere": "disturbed", "coverage": "normal",
                "seed": 300001, "duration_hours": duration, "truth_profile": "controlled"}
        try:
            generated = generate_one(case, destination / f"{duration:g}h" / "data",
                                     truth_backend=truth_backend, tudat_python=tudat_python, resume=resume)
            fitted = fit_one(generated["dataset"], {"model": "density"}, destination / f"{duration:g}h" / "fit",
                             options=solver_options, truth_path=generated["truth"], resume=resume,
                             run_context={"stage": "scaling", "duration_hours": duration, "model": "density"})
            from .data import load_dataset
            from .solvers import separator_check, initialize
            dataset = load_dataset(generated["dataset"])
            spec = _model_spec({"model": "density"})
            with np.load(fitted["fit"], allow_pickle=False) as arrays:
                separator = separator_check(dataset, spec, states=arrays["states"],
                                            reference=initialize(dataset, spec))
            write_json(destination / f"{duration:g}h" / "separator.json", separator)
            rows.append({"duration_hours": duration, "status": fitted["status"],
                         "elapsed_seconds": fitted["elapsed_seconds"], "metadata": fitted["metadata"],
                         "converged": fitted["converged"], "separator": separator})
        except Exception as error:
            rows.append({"duration_hours": duration, "status": "failed", "error": str(error)})
        write_json(destination / "scaling.json", {"runs": rows, "complete": False, "budget": budget.snapshot()})
    result = {"runs": rows, "complete": len(rows) == 3 and all(r.get("converged") for r in rows), "budget": budget.snapshot()}
    write_json(destination / "scaling.json", result)
    return result


def schur_check(seed=193, nodes=12, dimension=7) -> dict:
    """Verify exact Gaussian elimination around a retained boundary, no trajectory approximation."""
    from .solvers import solve_block_tridiagonal, schur_prefix
    rng = np.random.default_rng(seed)
    upper = rng.normal(size=(nodes - 1, dimension, dimension)) * 0.05
    diagonal = np.broadcast_to(2 * np.eye(dimension), (nodes, dimension, dimension)).copy()
    rhs = rng.normal(size=(nodes, dimension))
    full = solve_block_tridiagonal(diagonal.copy(), upper.copy(), rhs.copy())
    keep = nodes // 2
    reduced = schur_prefix(diagonal.copy(), upper.copy(), rhs.copy(), keep_from=keep)
    if isinstance(reduced, dict):
        suffix = solve_block_tridiagonal(reduced["diagonal"], reduced["upper"], reduced["rhs"])
    else:
        suffix = solve_block_tridiagonal(*reduced[:3])
    maximum = float(np.max(np.abs(np.asarray(full)[keep:] - np.asarray(suffix))))
    return {"kind": "linear_gaussian_boundary_elimination", "maximum_absolute_error": maximum,
            "passed": bool(maximum < 1e-10), "nodes": nodes, "dimension": dimension,
            "note": "Checks a linear Gaussian system only; does not establish exact nonlinear chunking."}


def run_posterior_checks(config: dict, output_dir: str | Path, *, truth_backend="tudat",
                         tudat_python=None, solver_options=None, budget_hours=4.0,
                         max_jobs=None, resume=True, num_warmup=500, num_samples=500,
                         job_timeout=3600) -> dict:
    """Five prespecified 2-hour model/scenario checks with four-chain NUTS gates."""
    config = {**config.get("defaults", {}), **config}
    destination = Path(output_dir).resolve()
    budget = Budget(budget_hours, max_jobs)
    rows = []
    cases = (("leo500", "quiet", "normal", "white"), ("leo500", "quiet", "normal", "colored"),
             ("leo500", "quiet", "normal", "density"), ("leo500", "disturbed", "blackout", "density"),
             ("leo800", "quiet", "normal", "density"))
    for index, (orbit, atmosphere, coverage, model) in enumerate(cases):
        if budget.exhausted:
            break
        case = {**config, "orbit": orbit, "atmosphere": atmosphere, "coverage": coverage,
                "duration_hours": 2.0, "cadence": 60.0, "seed": 40000 + index,
                "truth_profile": "controlled", "pulse_center_hours": 1.0,
                "pulse_width_hours": 0.25, "blackout_hours": [0.75, 1.25]}
        target = destination / f"{index + 1}-{orbit}-{atmosphere}-{coverage}-{model}"
        try:
            generated = generate_one(case, target / "data", truth_backend=truth_backend,
                                     tudat_python=tudat_python, resume=resume)
        except Exception as error:
            rows.append({"case": case, "status": "failed", "error": str(error)})
            continue
        comparison = {"case": {"orbit": orbit, "atmosphere": atmosphere, "coverage": coverage, "model": model}, "fits": []}
        for solver in ("gtsam", "numpyro"):
            if not budget.start_job():
                break
            parameters = {"model": model, "tau": 7200.0, "sigma": 0.3}
            options = dict(solver_options or {})
            if solver == "numpyro":
                options.update(num_warmup=num_warmup, num_samples=num_samples, num_chains=4,
                               chain_method="sequential", seed=41000 + index)
            context = {"orbit": orbit, "atmosphere": atmosphere, "coverage": coverage,
                       "seed": case["seed"], "model": model, "solver": solver,
                       "blackout_hours": case["blackout_hours"] if coverage == "blackout" else None,
                       "stage": "posterior", "duration_hours": 2.0}
            fit_dir = target / solver
            try:
                if solver == "numpyro" and job_timeout is not None:
                    fitted = _fit_subprocess(generated["dataset"], parameters, fit_dir, solver,
                                             options, generated["truth"], context, job_timeout)
                else:
                    fitted = fit_one(generated["dataset"], parameters, fit_dir, solver=solver,
                                     options=options, truth_path=generated["truth"], resume=resume,
                                     run_context=context)
                comparison["fits"].append({"solver": solver, "path": str(fit_dir / "fit.json"),
                    "status": fitted["status"], "valid_for_comparison": fitted["valid_for_comparison"],
                    "metadata": fitted["metadata"], "metrics": fitted.get("metrics", {})})
            except Exception as error:
                comparison["fits"].append({"solver": solver, "status": "failed",
                    "valid_for_comparison": False, "error": f"{type(error).__name__}: {error}"})
        comparison["complete"] = len(comparison["fits"]) == 2
        comparison["posterior_reference_valid"] = bool(comparison["complete"]
            and all(row["valid_for_comparison"] for row in comparison["fits"]))
        rows.append(comparison)
        write_json(destination / "posterior.json", {"cases": rows, "complete": False,
                                                    "budget": budget.snapshot()})
    result = {"cases": rows, "complete": len(rows) == 5 and all(row.get("complete") for row in rows),
              "all_diagnostics_passed": len(rows) == 5 and all(row.get("posterior_reference_valid") for row in rows),
              "budget": budget.snapshot(),
              "note": "A failed diagnostic or deadline leaves that posterior comparison inconclusive."}
    write_json(destination / "posterior.json", result)
    return result
