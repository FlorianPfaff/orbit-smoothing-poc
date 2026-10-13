#!/usr/bin/env python3
"""Validate 24-hour inference propagation against independently coded Tudat forces.

Run from the project root with its inference environment:
    PYTHONPATH=src scripts/runtime.sh python scripts/validate_propagation.py \
        --tudat-python /absolute/path/to/tudat-env/bin/python --output validation

The density *correction* is zero; the physical exponential atmosphere still
changes with altitude. Observation errors are evaluated only at actual visible
station/node pairs and contain no simulated measurement noise.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time

import jax
import numpy as np

from orbit_poc.config import ModelSpec
from orbit_poc.data import load_dataset
from orbit_poc.dynamics import propagate, scales
from orbit_poc.simulator import generate, geometric_observables


def checksum(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def differences(candidate, reference, dataset):
    obs = dataset.observations
    node = obs["node"]
    a = geometric_observables(candidate[node], obs["station_pos"], obs["station_vel"])
    b = geometric_observables(reference[node], obs["station_pos"], obs["station_vel"])
    delta = a - b
    return {
        "max_position_m": float(np.linalg.norm(candidate[:, :3]-reference[:, :3], axis=1).max()),
        "max_velocity_m_s": float(np.linalg.norm(candidate[:, 3:]-reference[:, 3:], axis=1).max()),
        "max_range_m": float(np.abs(delta[:, 0]).max()),
        "max_range_rate_m_s": float(np.abs(delta[:, 1]).max()),
        "rms_range_m": float(np.sqrt(np.mean(delta[:, 0]**2))),
        "rms_range_rate_m_s": float(np.sqrt(np.mean(delta[:, 1]**2))),
        "pass": bool(np.max(np.abs(delta[:, 0])) < .1 and np.max(np.abs(delta[:, 1])) < 1e-4),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tudat-python", required=True)
    parser.add_argument("--output", type=Path, default=Path("validation"))
    parser.add_argument("--space-weather-file", type=Path)
    parser.add_argument("--accepted-step", type=float, default=2.5,
                        help="Inference step to accept; 5 seconds fails the Doppler threshold in three orbits")
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    project = Path(__file__).resolve().parents[1]
    began = time.perf_counter()
    report = {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "experiment": "24-hour deterministic force/integrator equivalence, zero log-density correction",
        "interpretation": "Numerical acceptance for the controlled dynamics; not orbit-estimator performance or real-world fidelity.",
        "thresholds": {"max_range_m_strictly_below": .1, "max_range_rate_m_s_strictly_below": 1e-4},
        "selected_step_seconds": args.accepted_step,
        "reference": "Independent Tudat built-in central/J2/aerodynamic forces, fixed-step RKF78 at 10 seconds",
        "measurements": "Six prescribed rotating stations, 10-degree mask, 60-second cadence, noiseless geometric range/range-rate",
        "versions": {"python": platform.python_version(), "jax": jax.__version__, "numpy": np.__version__},
        "source_sha256": {name: checksum(project/name) for name in
                          ["src/orbit_poc/dynamics.py", "src/orbit_poc/simulator.py", "scripts/tudat_truth.py",
                           "scripts/validate_propagation.py"]},
        "cases": {},
    }
    for orbit in ["leo300", "leo500", "leo800", "eccentric"]:
        cfg = {"duration_hours": 24., "orbit": orbit, "seed": 31415,
               "atmosphere": "quiet", "coverage": "normal", "cadence": 60.,
               "truth_profile": "controlled", "truth_step_seconds": 10.,
               "density_parameters": {"offset": 0., "amplitudes": [], "periods_seconds": [], "phases": []}}
        path = destination / "propagation" / orbit
        result = generate(cfg, path, tudat_python=args.tudat_python)
        dataset = load_dataset(result["dataset"])
        with np.load(result["truth"], allow_pickle=False) as f:
            states, times = f["states"], f["times"]
            truth_meta = json.loads(str(f["metadata_json"]))
        case = {"sample_count": len(times), "visible_measurement_count": len(dataset.observations["node"]),
                "truth_sha256": checksum(result["truth"]), "tudat_version": truth_meta["tudat_version"],
                "config": cfg, "jax_against_tudat": {}}
        candidates = {}
        for step in sorted({5., 2.5, args.accepted_step, args.accepted_step/2.}, reverse=True):
            spec = ModelSpec(model="white", substep=step)
            candidate = np.asarray(propagate(states[0]/scales(spec), times, spec))*scales(spec)
            candidates[step] = candidate
            case["jax_against_tudat"][str(step)] = differences(candidate, states, dataset)
        case["jax_5s_against_2_5s"] = differences(candidates[5.], candidates[2.5], dataset)
        case["selected_against_half_step"] = differences(candidates[args.accepted_step], candidates[args.accepted_step/2.], dataset)
        # Bound error in the independent reference by halving its integration
        # step as well; comparison remains on the same 60-second output grid.
        fine = generate({**cfg, "truth_step_seconds": 5.}, path / "tudat_5s", tudat_python=args.tudat_python)
        with np.load(fine["truth"], allow_pickle=False) as f:
            case["tudat_10s_against_5s"] = differences(states, f["states"], dataset)
        report["cases"][orbit] = case
        print(json.dumps({"orbit": orbit, "selected_step": args.accepted_step,
                          "selected_result": case["jax_against_tudat"][str(args.accepted_step)]}), flush=True)

    stress_cfg = {"duration_hours": 2., "orbit": "leo500", "seed": 31416, "truth_profile": "stress",
                  "atmosphere": "disturbed", "pulse_center_hours": 1., "pulse_width_hours": .25}
    if args.space_weather_file:
        stress_cfg["space_weather_file"] = str(args.space_weather_file.resolve())
    stress = generate(stress_cfg, destination / "stress_smoke", tudat_python=args.tudat_python)
    with np.load(stress["truth"], allow_pickle=False) as f:
        meta = json.loads(str(f["metadata_json"]))
        report["stress_smoke"] = {
            "pass": bool(np.isfinite(f["states"]).all() and np.isfinite(f["density"]).all() and
                         np.all(f["density"] > 0) and all(meta["stress_flags"].values())),
            "sample_count": len(f["times"]), "min_density_kg_m3": float(f["density"].min()),
            "max_density_kg_m3": float(f["density"].max()),
            "truth_sha256": checksum(stress["truth"]),
            "force_models": meta["force_models"], "atmosphere_model": meta["atmosphere_model"],
            "space_weather_sha256": meta["space_weather_sha256"],
            "observed_weather_start": meta["observed_weather_start"],
            "observed_weather_end": meta["observed_weather_end"],
            "tudat_version": meta["tudat_version"], "config": stress_cfg,
            "interpretation": "Smoke test of the additional truth forces and archived atmosphere, not an equivalence check against simplified inference dynamics.",
        }
    report["candidate_5s_pass"] = all(case["jax_against_tudat"]["5.0"]["pass"] and
                                    case["jax_5s_against_2_5s"]["pass"] and
                                    case["tudat_10s_against_5s"]["pass"] for case in report["cases"].values())
    report["selected_step_pass"] = all(case["jax_against_tudat"][str(args.accepted_step)]["pass"] and
                                        case["selected_against_half_step"]["pass"] and
                                        case["tudat_10s_against_5s"]["pass"] for case in report["cases"].values())
    report["overall_pass"] = report["selected_step_pass"] and report["stress_smoke"]["pass"]
    report["elapsed_seconds"] = time.perf_counter() - began
    output = destination / "propagation_acceptance.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"report": str(output), "overall_pass": report["overall_pass"]}), flush=True)
    if not report["overall_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
