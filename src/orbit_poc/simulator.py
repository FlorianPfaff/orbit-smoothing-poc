"""Synthetic tracking experiments. Truth is never included in the estimator dataset.

The default backend is an external TudatPy process with its own force models.
``scipy`` is a deliberately labelled diagnostic fallback, never an automatic fallback.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

MU = 3.986004418e14
RADIUS = 6378137.0
J2 = 0.00108262668
OMEGA = 7.2921150e-5
STATIONS_DEG = [(45, 0), (45, 120), (45, -120), (-35, 60), (-35, 180), (-35, -60)]


def initial_state(orbit: str) -> np.ndarray:
    """Start at the ascending node/perigee, 53 degrees inclination, RAAN zero."""
    if orbit == "eccentric":
        rp, ra = RADIUS + 300e3, RADIUS + 800e3
    elif orbit in {"leo300", "leo500", "leo800"}:
        rp = ra = RADIUS + float(orbit[3:]) * 1e3
    else:
        raise ValueError(f"Unknown orbit {orbit!r}")
    speed = np.sqrt(MU * (2.0 / rp - 2.0 / (rp + ra)))
    inclination = np.deg2rad(53.0)
    return np.array([rp, 0.0, 0.0, 0.0, speed * np.cos(inclination), speed * np.sin(inclination)])


def density_parameters(seed: int) -> dict:
    rng = np.random.default_rng(np.random.SeedSequence([seed, 4812]))
    return {"periods_seconds": [28800., 5820., 1860.],
            "amplitudes": [0.10, 0.04, 0.025],
            "phases": rng.uniform(0., 2 * np.pi, 3).tolist(),
            "offset": float(rng.normal(0., 0.025))}


def log_density_correction(times, atmosphere: str, parameters: dict):
    t = np.asarray(times)
    q = np.full_like(t, parameters["offset"], dtype=float)
    for amplitude, period, phase in zip(parameters["amplitudes"], parameters["periods_seconds"], parameters["phases"]):
        q += amplitude * np.sin(2 * np.pi * t / period + phase)
    if atmosphere == "disturbed":
        q += np.log(2.) * np.exp(-0.5 * ((t - parameters.get("pulse_center_seconds", 43200.)) /
                                        parameters.get("pulse_width_seconds", 3600.)) ** 2)
    elif atmosphere != "quiet":
        raise ValueError(f"Unknown atmosphere {atmosphere!r}")
    return q


def station_states(times: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (N,6,3) station positions and velocities in the controlled inertial frame."""
    lat, lon = np.deg2rad(np.asarray(STATIONS_DEG)).T
    theta = np.asarray(times)[:, None] * OMEGA + lon[None, :]
    p = RADIUS * np.stack([np.cos(lat)[None, :] * np.cos(theta),
                           np.cos(lat)[None, :] * np.sin(theta),
                           np.broadcast_to(np.sin(lat), theta.shape)], axis=-1)
    v = np.cross(np.array([0., 0., OMEGA]), p)
    return p, v


def geometric_observables(states, station_pos, station_vel):
    delta = states[..., :3] - station_pos
    distance = np.linalg.norm(delta, axis=-1)
    rate = np.sum(delta * (states[..., 3:] - station_vel), axis=-1) / distance
    return np.stack([distance, rate], axis=-1)


def _scipy_truth(config: dict, times: np.ndarray, parameters: dict) -> tuple[np.ndarray, np.ndarray, dict]:
    if config["truth_profile"] != "controlled":
        raise ValueError("Stress truth requires TudatPy; the SciPy diagnostic backend cannot supply it.")

    def derivative(t, x):
        r, v = x[:3], x[3:]
        rn = np.linalg.norm(r)
        z2 = (r[2] / rn) ** 2
        a = -MU * r / rn ** 3
        a += 1.5 * J2 * MU * RADIUS ** 2 / rn ** 5 * r * np.array([5*z2-1, 5*z2-1, 5*z2-3])
        rho = 5e-13 * np.exp(-(rn - RADIUS - 500e3) / 60000. +
                              log_density_correction(t, config["atmosphere"], parameters))
        rel = v - np.cross([0., 0., OMEGA], r)
        a -= .5 * rho * 2.2 / 100. * np.linalg.norm(rel) * rel
        return np.concatenate([v, a])

    solution = solve_ivp(derivative, (0., times[-1]), initial_state(config["orbit"]),
                         method="DOP853", t_eval=times, rtol=2e-12,
                         atol=np.array([1e-6]*3 + [1e-9]*3), max_step=30.)
    if not solution.success:
        raise RuntimeError(solution.message)
    states = solution.y.T
    rho = 5e-13 * np.exp(-(np.linalg.norm(states[:, :3], axis=1) - RADIUS - 500e3) / 60000. +
                         log_density_correction(times, config["atmosphere"], parameters))
    return states, rho, {"backend": "scipy-diagnostic", "integrator": "DOP853",
                          "benchmark_truth": False, "force_models": ["central", "J2", "corotating_drag"],
                          "atmosphere_model": "synthetic_exponential_with_multiscale_correction"}


def generate(config: dict, output_dir: Path, truth_backend: str = "tudat", tudat_python=None) -> dict:
    """Generate one independent truth trajectory and noisy six-station dataset.

    ``blackout_hours`` defaults to [11,13]; a short arc does not move the blackout.
    A stress run requires an existing archived ``space_weather_file`` or explicitly
    selected Tudat resource file, and records its SHA256 in truth metadata.
    """
    from .data import Dataset, save_dataset

    cfg = {"duration_hours": 24., "orbit": "leo500", "seed": 42,
           "atmosphere": "quiet", "coverage": "normal", "cadence": 60.,
           "epoch": "2024-05-10T00:00:00", "truth_profile": "controlled", **config}
    if cfg["truth_profile"] not in {"controlled", "stress"}:
        raise ValueError("truth_profile must be controlled or stress")
    if cfg["coverage"] not in {"normal", "blackout"}:
        raise ValueError("coverage must be normal or blackout")
    duration, cadence = float(cfg["duration_hours"]) * 3600., float(cfg["cadence"])
    if duration <= 0. or cadence <= 0. or not np.isclose(duration / cadence, round(duration / cadence)):
        raise ValueError("duration must be positive and an integer multiple of cadence")
    times = np.arange(round(duration / cadence) + 1, dtype=float) * cadence
    parameters = dict(cfg.get("density_parameters", density_parameters(int(cfg["seed"]))))
    parameters["pulse_center_seconds"] = float(cfg.get("pulse_center_hours", 12.)) * 3600.
    parameters["pulse_width_seconds"] = float(cfg.get("pulse_width_hours", 1.)) * 3600.
    if parameters["pulse_width_seconds"] <= 0:
        raise ValueError("pulse_width_hours must be positive")
    lengths = [len(parameters[key]) for key in ("periods_seconds", "amplitudes", "phases")]
    if len(set(lengths)) != 1 or np.any(np.asarray(parameters["periods_seconds"]) <= 0):
        raise ValueError("density_parameters require equal-length amplitudes, phases, and positive periods_seconds")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    truth_path, data_path = output_dir / "truth.npz", output_dir / "dataset.npz"
    if truth_backend == "tudat":
        script = Path(__file__).resolve().parents[2] / "scripts" / "tudat_truth.py"
        input_path = output_dir / "truth_input.json"
        input_path.write_text(json.dumps({"config": cfg, "times": times.tolist(),
                                         "initial_state": initial_state(cfg["orbit"]).tolist(),
                                         "density_parameters": parameters}, indent=2))
        command = [str(tudat_python or sys.executable), str(script), str(input_path), str(truth_path)]
        result = subprocess.run(command, capture_output=True, text=True)
        (output_dir / "truth_generation.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError("Tudat truth generation failed; no fallback was used. " + result.stderr[-6000:])
        with np.load(truth_path, allow_pickle=False) as truth:
            states, density = truth["states"], truth["density"]
            truth_metadata = json.loads(str(truth["metadata_json"]))
            if not np.array_equal(truth["times"], times):
                raise RuntimeError("Tudat output grid differs from requested node times")
    elif truth_backend in {"scipy", "scipy-diagnostic"}:
        states, density, truth_metadata = _scipy_truth(cfg, times, parameters)
        np.savez_compressed(truth_path, times=times, states=states, density=density,
                            log_density_correction=log_density_correction(times, cfg["atmosphere"], parameters),
                            metadata_json=json.dumps({**truth_metadata, "config": cfg, "density_parameters": parameters}))
    else:
        raise ValueError("truth_backend must be tudat or scipy (explicit diagnostic fallback)")

    p, v = station_states(times)
    delta = states[:, None, :3] - p
    elevation_sine = np.sum(delta * (p / RADIUS), axis=2) / np.linalg.norm(delta, axis=2)
    visible = elevation_sine >= np.sin(np.deg2rad(10.))
    if cfg["coverage"] == "blackout":
        left, right = cfg.get("blackout_hours", [11., 13.])
        visible[(times >= float(left)*3600.) & (times <= float(right)*3600.), :] = False
    node, station = np.nonzero(visible)
    clean = geometric_observables(states[node], p[node, station], v[node, station])
    sigma = np.array([10., .01])
    noise_rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), 912]))
    # Draw on the full node/station grid so a blackout removes observations
    # without changing the noise on any surviving observation in a paired run.
    full_noise = noise_rng.normal(size=(len(times), len(STATIONS_DEG), 2)) * sigma
    noisy = clean + full_noise[node, station]
    prior_sigma = np.array([1000.] * 3 + [1.] * 3)
    prior_rng = np.random.default_rng(np.random.SeedSequence([int(cfg["seed"]), 913]))
    prior_mean = states[0] + prior_rng.normal(size=6) * prior_sigma
    metadata = {"config": cfg, "truth_backend": truth_metadata["backend"],
                "benchmark_truth": truth_metadata["benchmark_truth"],
                "force_models": truth_metadata["force_models"],
                "atmosphere_model": truth_metadata["atmosphere_model"],
                "frame": "Earth-centered inertial, fixed z pole; synthetic Earth angle zero at arc start",
                "units": "SI", "stations_lat_lon_deg": STATIONS_DEG,
                "elevation_mask_deg": 10., "measurement_model": "instantaneous geometric one-way range and range-rate",
                "measurement_count": int(len(node)), "random_streams": "density4812,noise912,prior913"}
    dataset = Dataset(times=times, observations={"node": node.astype(np.int64),
                      "station_pos": p[node, station], "station_vel": v[node, station],
                      "y": noisy, "sigma": sigma}, prior_mean=prior_mean,
                      prior_sigma=prior_sigma, metadata=metadata)
    save_dataset(dataset, data_path)
    manifest_path = output_dir / "manifest.json"
    manifest = {"dataset": str(data_path), "truth": str(truth_path), "manifest": str(manifest_path),
                "metadata": metadata}
    manifest_path.write_text(json.dumps(manifest, indent=2))
    return manifest
