#!/usr/bin/env python3
"""Standalone TudatPy truth process: JSON request -> NPZ, no estimator imports.

Controlled: built-in degree-2/order-0 gravity and aerodynamic acceleration.
Stress: built-in degree-4/order-4 Earth gravity, Sun/Moon, SRP, and archived
NRLMSISE-00 space weather. Stress is not claimed to reproduce actual ephemerides.
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path
import numpy as np


def run(input_path: Path, output_path: Path):
    import tudatpy
    from tudatpy.dynamics import environment_setup, propagation_setup, simulator
    from tudatpy.interface import spice
    from tudatpy.astro.time_representation import DateTime
    from datetime import datetime, timedelta

    request = json.loads(input_path.read_text())
    cfg, times = request["config"], np.asarray(request["times"], dtype=float)
    parameters = request["density_parameters"]
    stress = cfg["truth_profile"] == "stress"
    spice.load_standard_kernels()
    epoch = datetime.fromisoformat(cfg["epoch"].replace("Z", "+00:00"))
    t0 = DateTime(epoch.year, epoch.month, epoch.day, epoch.hour, epoch.minute,
                  epoch.second + epoch.microsecond / 1e6).epoch()
    body_settings = environment_setup.get_default_body_settings(
        ["Earth", "Sun", "Moon"] if stress else ["Earth"], "Earth", "J2000")
    earth = body_settings.get("Earth")
    # Keep synthetic station geometry and wind corotation exactly reproducible.
    earth.rotation_model_settings = environment_setup.rotation_model.simple(
        "J2000", "IAU_Earth", np.eye(3), t0, 7.2921150e-5)
    earth.shape_settings = environment_setup.shape.spherical(6378137.)
    if not stress:
        c, s = np.zeros((3, 3)), np.zeros((3, 3))
        c[0, 0], c[2, 0] = 1., -0.00108262668 / np.sqrt(5.)
        earth.gravity_field_settings = environment_setup.gravity_field.spherical_harmonic(
            3.986004418e14, 6378137., c, s, "IAU_Earth")

    def log_scale(seconds):
        value = parameters["offset"]
        for amplitude, period, phase in zip(parameters["amplitudes"], parameters["periods_seconds"], parameters["phases"]):
            value += amplitude * np.sin(2 * np.pi * seconds / period + phase)
        if cfg["atmosphere"] == "disturbed":
            value += np.log(2.) * np.exp(-.5 * ((seconds - parameters.get("pulse_center_seconds", 43200.)) /
                                              parameters.get("pulse_width_seconds", 3600.)) ** 2)
        return value

    weather_metadata = {}
    if stress:
        weather = cfg.get("space_weather_file")
        if not weather:
            from tudatpy import data
            weather = str(Path(data.get_space_weather_path()) / "sw19571001.txt")
        weather_path = Path(weather).expanduser().resolve()
        if not weather_path.is_file():
            raise FileNotFoundError(f"Stress requires archived space-weather data: {weather_path}")
        weather_bytes = weather_path.read_bytes()
        # Reproducibility alone is insufficient: reject predictive/out-of-range
        # weather when claiming retrospective archived observations.
        observed_dates = []
        in_observed = False
        for line in weather_bytes.decode("ascii", errors="replace").splitlines():
            if "BEGIN OBSERVED" in line:
                in_observed = True
                continue
            if "END OBSERVED" in line:
                in_observed = False
            fields = line.split()
            if in_observed and len(fields) >= 3:
                try:
                    observed_dates.append(datetime(*map(int, fields[:3])).date())
                except (ValueError, TypeError):
                    pass
        start_date = epoch.date()
        end_date = (epoch + timedelta(seconds=float(times[-1]))).date()
        if not observed_dates or min(observed_dates) > start_date - timedelta(days=3) or max(observed_dates) < end_date:
            raise ValueError("Archived OBSERVED weather does not cover the full arc and preceding three days; supply space_weather_file explicitly.")
        archived_weather = output_path.parent / "space_weather_archive.txt"
        archived_weather.write_bytes(weather_bytes)
        base_atmosphere = environment_setup.atmosphere.nrlmsise00(str(archived_weather), use_storm_conditions=True)
        earth.atmosphere_settings = environment_setup.atmosphere.scaled_by_function(
            base_atmosphere, lambda epoch_seconds: float(np.exp(log_scale(epoch_seconds - t0))), False)
        weather_metadata = {"space_weather_file": str(archived_weather),
                            "space_weather_sha256": hashlib.sha256(weather_bytes).hexdigest(),
                            "space_weather_original": str(weather_path),
                            "observed_weather_start": str(min(observed_dates)),
                            "observed_weather_end": str(max(observed_dates)),
                            "space_weather_selection": "explicit" if cfg.get("space_weather_file") else "bundled Tudat archive"}
    else:
        def density_function(altitude, longitude, latitude, epoch_seconds):
            return float(5e-13 * np.exp(-(altitude - 500e3) / 60000. + log_scale(epoch_seconds - t0)))
        earth.atmosphere_settings = environment_setup.atmosphere.custom_four_dimensional_constant_temperature(
            density_function, 1000.)

    body_settings.add_empty_settings("Satellite")
    vehicle = body_settings.get("Satellite")
    vehicle.constant_mass = 100.
    vehicle.aerodynamic_coefficient_settings = environment_setup.aerodynamic_coefficients.constant(1., [2.2, 0., 0.])
    if stress:
        vehicle.radiation_pressure_target_settings = environment_setup.radiation_pressure.cannonball_radiation_target(
            1., 1.2, {"Sun": ["Earth"]})
    bodies = environment_setup.create_system_of_bodies(body_settings)
    acc = {"Earth": [propagation_setup.acceleration.spherical_harmonic_gravity(4, 4) if stress else
                      propagation_setup.acceleration.spherical_harmonic_gravity(2, 0),
                      propagation_setup.acceleration.aerodynamic()]}
    if stress:
        acc["Sun"] = [propagation_setup.acceleration.point_mass_gravity(), propagation_setup.acceleration.radiation_pressure()]
        acc["Moon"] = [propagation_setup.acceleration.point_mass_gravity()]
    accelerations = propagation_setup.create_acceleration_models(bodies, {"Satellite": acc}, ["Satellite"], ["Earth"])
    # A fixed 10s RKF78 grid nests inside the 60s observation grid. An override
    # permits convergence checks without interpolating the state history.
    step = float(cfg.get("truth_step_seconds", 10.))
    cadence = times[1] - times[0]
    if step <= 0. or not np.isclose(cadence / step, round(cadence / step)):
        raise ValueError("truth_step_seconds must divide the observation cadence")
    integrator = propagation_setup.integrator.runge_kutta_fixed_step(
        step, coefficient_set=propagation_setup.integrator.CoefficientSets.rkf_78)
    termination = propagation_setup.propagator.time_termination(t0 + times[-1], terminate_exactly_on_final_condition=True)
    dependent = [propagation_setup.dependent_variable.density("Satellite", "Earth")]
    settings = propagation_setup.propagator.translational(
        ["Earth"], accelerations, ["Satellite"], np.asarray(request["initial_state"]),
        t0, integrator, termination, output_variables=dependent)
    simulation = simulator.create_dynamics_simulator(bodies, settings)
    history = simulation.propagation_results.state_history
    dependent_history = simulation.propagation_results.dependent_variable_history
    epochs = np.array(sorted(history.keys()))
    indices = np.searchsorted(epochs, t0 + times)
    indices = np.minimum(indices, len(epochs)-1)
    for i in range(len(indices)):
        if indices[i] > 0 and abs(epochs[indices[i]-1] - t0 - times[i]) < abs(epochs[indices[i]] - t0 - times[i]):
            indices[i] -= 1
    if np.max(np.abs(epochs[indices] - t0 - times)) > 1e-5:
        raise RuntimeError("Integrator did not produce all requested truth epochs")
    states = np.array([history[epochs[i]] for i in indices])
    density = np.array([dependent_history[epochs[i]][0] for i in indices])
    if states.shape != (len(times), 6) or not np.isfinite(states).all() or not np.isfinite(density).all():
        raise RuntimeError("Tudat produced invalid truth values")
    metadata = {"backend": "tudat", "benchmark_truth": True,
                "tudat_version": getattr(tudatpy, "__version__", "unknown"),
                "integrator": "fixed-step RKF78", "step_seconds": step,
                "force_models": ["Earth SH4x4", "Sun gravity", "Moon gravity", "SRP", "corotating_drag"] if stress else
                                ["central", "J2", "corotating_drag"],
                "atmosphere_model": "NRLMSISE-00_with_synthetic_multiscale_multiplier" if stress else
                                    "synthetic_exponential_with_multiscale_correction",
                "epoch_j2000_seconds": t0, "config": cfg, "density_parameters": parameters,
                "epoch_calendar_scale": "Tudat DateTime calendar epoch",
                "density_correction_reference": "5e-13*exp(-(geocentric_altitude_m-500000)/60000)",
                "gravity_model": "Tudat default Earth gravity truncated at degree/order4" if stress else "controlled exact J2",
                "stress_flags": {"higher_gravity": stress, "sun_moon": stress, "srp": stress, "nrlmsise00": stress},
                **weather_metadata}
    reference_density = 5e-13 * np.exp(-(np.linalg.norm(states[:, :3], axis=1) - 6378137. - 500e3) / 60000.)
    np.savez_compressed(output_path, times=times, states=states, density=density,
                        log_density_correction=np.log(density / reference_density),
                        synthetic_log_multiplier=np.asarray([log_scale(t) for t in times]),
                        metadata_json=json.dumps(metadata))
    print(json.dumps({"truth": str(output_path), "samples": len(times), "metadata": metadata}))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: tudat_truth.py input.json output.npz")
    run(Path(sys.argv[1]), Path(sys.argv[2]))
