#!/usr/bin/env python3
"""Reproduce bounded native synthetic validation, independently of production.

Requires the patched GROOPS executable, Tudat environment, and official example
and auxiliary inputs described in docs/comparison-native-validation.md.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, localcontext
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, source_snapshot, write_json
from orbit_poc.comparison.synthetic import NOISE_MODEL, configure_synthetic_forces, write_truth_instruments
from orbit_poc.simulator import generate


METHODS = {
    "groops_pulses": {"interval_seconds": 1200., "sigma_velocity_m_s": 1e-4},
    "groops_log_drag_ou": {"knot_seconds": 60., "tau_seconds": 7200.,
        "sigma_log_density": .3, "interpolation": "linear_log_density",
        "initial_prior": "stationary_ou", "empirical_acceleration": False},
}


def frozen_binary(executable, directory):
    source = Path(executable).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / "groops"
    if target.exists():
        if file_hash(source) != file_hash(target):
            raise ValueError("Existing frozen binary differs; choose a fresh output directory")
    else:
        shutil.copy2(source, target)
        target.chmod(target.stat().st_mode | 0o111)
    return target


def compact_fit(result):
    return {key: result.get(key) for key in ("status", "converged", "covariance_valid",
        "covariance_scope", "elapsed_seconds", "peak_rss_bytes", "metadata",
        "force_model_hash", "measurement_model_hash", "native_binary_sha256", "error")}


def prepare_existing_observations(manifest, job, root):
    """Re-mask a verified unchanged generated realization; never reuse bootstrap."""
    from orbit_poc.comparison.groops_config import build_day_configs
    raw = read_json(manifest)
    if raw.get("status") != "observations_ready":
        raise ValueError("Reuse requires a completed synthetic observation-generation manifest")
    for key in ("epoch", "seed", "orbit", "atmosphere", "duration_hours"):
        if raw["case"][key] != job["case"][key]:
            raise ValueError("Generated observation case differs from the requested diagnostic")
    noise = raw["native_simulation"]["noise"]
    if any(noise.get(key) != value for key, value in NOISE_MODEL.items()):
        raise ValueError("Generated observations do not use the final synthetic noise specification")
    if raw["native_simulation"].get("simulation_wavelength_factor") != 1.:
        raise ValueError("Generated observations must use coherent full-cycle ambiguity injections")
    for item in raw["estimation_inputs"] + raw["evaluation_inputs"]:
        if file_hash(item["path"]) != item["sha256"]:
            raise ValueError("A generated observation artifact changed before reuse")
    native = job["backend"]
    configured = build_day_configs(raw, native["example_directory"], native["auxiliary_dir"],
        root / "native-prepared", method="groops_pulses", mask=job["case"]["mask"],
        duration_hours=job["case"]["duration_hours"])
    configured = configure_synthetic_forces(configured, job["case"], native)
    reused = backend._link_cached_transmitters(raw, configured, native["groops_executable"])
    execution = [reused] if reused else [backend.run_native(native["groops_executable"],
        configured["configs"]["convert_gnss"], configured["output_dir"], "convert_gnss")]
    execution.append(backend.run_native(native["groops_executable"], configured["configs"]["convert_receiver"],
                                       configured["output_dir"], "convert_receiver"))
    backend._verify_transmitters(configured)
    execution.extend(backend._close_prepared_nominal_reference(configured,
        native["groops_executable"], root, timeout=float(native.get("command_timeout_seconds", 3600.0))))
    blind = root / "native_preparation.json"
    write_json(blind, backend._blind_record(configured))
    return {"status": "prepared", "estimation_inputs": [*configured["estimation_inputs"],
        artifact_record("force_auxiliary", blind, metadata={"kind": "native_preparation"})],
        "evaluation_inputs": configured.get("evaluation_inputs", []),
        "calibration_inputs": configured.get("calibration_inputs", []),
        **{key: configured[key] for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")},
        "native_execution": execution, "nominal_initialization": configured["nominal_initialization"],
        "native_binary_sha256": file_hash(native["groops_executable"]),
        "reused_generation": artifact_record("synthetic_generation", manifest)}


def run_fits(args):
    root = args.output.resolve()
    if any((root / label).exists() for label in ("normal", "masked")):
        raise ValueError("Fit output already exists; choose a fresh output directory")
    binary = frozen_binary(args.groops, root / "bin")
    native = {"groops_executable": str(binary), "tudat_python": str(args.tudat_python.resolve()),
        "retain_native_diagnostics": True,
        "example_directory": str(args.example_directory.resolve()),
        "auxiliary_dir": str(args.auxiliary_dir.resolve()), "cache_dir": str(args.cache_dir.resolve())}
    source = source_snapshot()["sha256"]
    case = {"orbit": args.orbit, "atmosphere": args.atmosphere, "coverage": "normal",
        "seed": args.seed, "duration_hours": args.duration_hours, "cadence": 30,
        "epoch": args.epoch, "truth_model": "tudat_independent_central_j2_exponential_gnss"}
    start, stop = args.mask_seconds
    if not 0 < start < stop < args.duration_hours * 3600:
        raise ValueError("The diagnostic holdout must be inside the generated arc")
    records = []
    for label, intervals in (("normal", []), ("masked", [[start, stop]])):
        folder = root / label
        current = {**case, "coverage": "blackout" if intervals else "normal",
            "mask": {"intervals_seconds": intervals, "cadence_seconds": 30, "time_scale": "elapsed"}}
        preparation_job = {"stage": "synthetic", "case": current, "backend": native}
        write_json(folder / "preparation_request.json", preparation_job)
        prepared = (prepare_existing_observations(args.reuse_observations, preparation_job, folder / "prepare")
                    if args.reuse_observations else backend.prepare_job(preparation_job, folder / "prepare"))
        write_json(folder / "preparation_result.json", prepared)
        if prepared.get("status") != "prepared":
            raise RuntimeError(f"Native preparation did not complete: {prepared}")
        for method, parameters in METHODS.items():
            fitdir = folder / method
            # Held-out values and truth cross only the post-fit evaluation API.
            job = {**preparation_job, "method": method, "parameters": parameters,
                "source_hash": source, "estimation_inputs": prepared["estimation_inputs"],
                **{key: prepared[key] for key in ("force_model_hash", "measurement_model_hash",
                                                "preprocessing_hash", "mask_hash")}}
            write_json(fitdir / "request.json", job)
            result = backend.fit_job(job, fitdir)
            write_json(fitdir / "result.json", result)
            record = {"case": label, "method": method, **compact_fit(result)}
            if result.get("converged") and result.get("covariance_valid"):
                evaluation_job = {**job, "split": "calibration" if intervals else "evaluation",
                    "calibration_inputs": prepared.get("calibration_inputs", []),
                    "evaluation_inputs": prepared.get("evaluation_inputs", [])}
                evaluation = backend.evaluate_job(evaluation_job, result, fitdir / "evaluation")
                write_json(fitdir / "evaluation_result.json", evaluation)
                record["evaluation_status"] = evaluation.get("status")
                if intervals:
                    record["calibration_score"] = evaluation.get("calibration_score")
                else:
                    record["position_rmse_m"] = evaluation.get("metrics", {}).get("position_rmse_m")
            records.append(record)
            write_json(root / "functional_gate.json", {"scope": "Diagnostic synthetic pipeline, not production comparison",
                "source_hash": source, "records": records, "complete": len(records) == 4,
                "nuisance_recovery": "Requires the separately documented physical-observable recovery check"})
            print(label, method, record["status"], record.get("evaluation_status"), flush=True)
    passed = all(r.get("converged") and r.get("covariance_valid") and
                 r.get("evaluation_status") == "complete" for r in records)
    if not passed:
        raise RuntimeError("One or more diagnostic fits or evaluations failed; inspect saved results")


def save_matrix(path, values):
    values = np.asarray(values).reshape(-1)
    path.write_text(f"groops matrix version=20200123\nMatrix( {len(values)} x 1 )\n" +
                    "\n".join(f"{x:.18e}" for x in values) + "\n")


def run_compact(args):
    """Exercise production retention against the retained diagnostic fits."""
    root = args.output.resolve()
    binary = frozen_binary(args.groops, root / "bin")
    prepared = read_json(args.fit_directory / "preparation_result.json")
    if not prepared.get("calibration_inputs"):
        raise ValueError("Compact validation requires the masked diagnostic fit directory")
    records = []
    for method in METHODS:
        original = read_json(args.fit_directory / method / "result.json")
        job = read_json(args.fit_directory / method / "request.json")
        if any(key in job for key in ("evaluation_inputs", "calibration_inputs", "truth", "reference_orbit")):
            raise ValueError("Diagnostic fitting request is not blind")
        job["backend"] = {**job["backend"], "groops_executable": str(binary), "retain_native_diagnostics": False}
        job["expected_native_binary_sha256"] = file_hash(binary)
        job["split"] = "calibration"
        job["source_hash"] = source_snapshot()["sha256"]
        directory = root / method
        if (directory / "result.json").exists():
            raise ValueError("Compact check output already exists; use a fresh directory")
        write_json(directory / "request.json", job)
        result = backend.fit_job(job, directory)
        write_json(directory / "result.json", result)
        evaluation = backend.evaluate_job({**job, "calibration_inputs": prepared["calibration_inputs"]},
                                         result, directory / "evaluation")
        write_json(directory / "evaluation_result.json", evaluation)
        files = [{item["role"]: item["path"] for item in value["artifacts"]} for value in (original, result)]
        with np.load(files[0]["state_estimate"]) as before, np.load(files[1]["state_estimate"]) as after:
            identical = all(np.array_equal(before[key], after[key]) for key in ("times", "mjd", "states", "covariance"))
        retention = read_json(files[1]["retention_audit"])
        artifacts_valid = all(file_hash(item["path"]) == item["sha256"] for item in result["artifacts"])
        passed = (result.get("converged") and result.get("covariance_valid") and identical and artifacts_valid
                  and result["metadata"].get("reference_inputs_used") is False
                  and result["metadata"].get("retain_native_diagnostics") is False
                  and bool(retention["deleted_outputs"])
                  and all(not Path(item["path"]).exists() for item in retention["deleted_outputs"])
                  and evaluation.get("status") == "complete")
        records.append({"method": method, **compact_fit(result), "passed": bool(passed),
            "state_and_covariance_bitwise_equal": identical, "retained_artifacts_verified": artifacts_valid,
            "pruned_outputs": len(retention["deleted_outputs"]),
            "evaluation_status": evaluation.get("status"), "calibration_score": evaluation.get("calibration_score")})
        write_json(root / "compact_retention.json", {"records": records, "complete": len(records) == len(METHODS),
            "scope": "Production compact retention on the same small blind masked GNSS fits; not a calibration campaign"})
        print(method, "compact retention passed", bool(passed), flush=True)
    if not all(record["passed"] for record in records):
        raise RuntimeError("Compact retention did not preserve the fitted result and held-out prediction")


def resolve_daily_variables(node, date, mjd, duration):
    for child in node.iter():
        if child.text:
            child.text = child.text.replace("{loopTime:%D}", date).replace(
                "loopTimeEnd", f"({mjd:.16g}+{duration:.16g}/86400)").replace("loopTime", f"{mjd:.16g}")


def add_offgrid_interpolation(tree, folder, mjd, stop, coarse_step):
    """Exercise the native shared boundary-aware LEO interpolation helper."""
    knots = np.arange(0., stop + 1e-6, 60.)
    times = np.unique(np.r_[knots, knots - .123, knots + .123,
                           np.arange(0., stop, coarse_step) + .5 * coarse_step])
    times = times[(times > 0) & (times < stop)]
    # Diagnostic arcs begin on an exact native second (UTC midnight is GPS
    # midnight + 18 s in 2024). Do not preserve the float-MJD rounding error.
    day = int(mjd)
    offset = round((mjd - day) * 86400)
    path = folder / "offgrid_epochs.txt"
    with path.open("w") as stream, localcontext() as context:
        context.prec = 35
        stream.write(f"groops instrument version=20200123\n-3 1\n{len(times)}\n")
        for second in times:
            value = Decimal(day) + (Decimal(offset) + Decimal(str(second))) / Decimal(86400)
            stream.write(f"{value:.18f} 0\n")
    interpolation = deepcopy(tree.find(".//OrbitPocEvaluateVariational"))
    interpolation.find("outputfileOrbit").text = str(folder / "offgrid_orbit.txt")
    if interpolation.find("outputfileParameters") is not None:
        interpolation.remove(interpolation.find("outputfileParameters"))
    ET.SubElement(interpolation, "interpolationDegree").text = "7"
    ET.SubElement(ET.SubElement(ET.SubElement(interpolation, "timeSeries"), "instrument"),
                  "inputfileInstrument").text = str(path)
    boundaries = ET.SubElement(ET.SubElement(interpolation, "interpolationBoundaries"), "uniformSampling")
    for tag, value in (("timeStart", str(day)), ("offsetSeconds", str(offset)),
                      ("timeEnd", f"{day}+{np.ceil(stop/60)*60}/86400"), ("sampling", "60/86400")):
        ET.SubElement(boundaries, tag).text = value
    ET.SubElement(tree, "program").append(interpolation)


def run_refinement(args):
    root = args.output.resolve()
    binary = frozen_binary(args.groops, root / "bin")
    fitroot = args.fit_directory.resolve()
    common_job = read_json(fitroot / "groops_pulses/request.json")
    case = common_job["case"]
    date = case["epoch"][:10]
    duration = float(case["duration_hours"]) * 3600
    references = {}
    # No interpolated coarse truth: both reference grids are independently
    # propagated by Tudat with identical physical parameters and seed.
    steps = ((args.coarse_step, "coarse"), (args.fine_step, "fine"))
    if not 0 < args.fine_step < args.coarse_step or any(60 / s != round(60 / s) for s, _ in steps):
        raise ValueError("Positive fine < coarse steps must divide each 60-second density segment")
    for step, label in steps:
        truth_config = {**case, "cadence": step, "truth_step_seconds": step,
                        "truth_profile": "controlled", "coverage": "normal"}
        references[label] = generate(truth_config, root / "reference" / label,
            truth_backend="tudat", tudat_python=str(args.tudat_python.resolve()))["truth"]
    results = []
    for method in METHODS:
        private = fitroot / method
        result = read_json(private / "result.json")
        if not result.get("converged") or not result.get("covariance_valid"):
            raise ValueError("Refinement requires a converged native fit and valid covariance")
        artifacts = {x["role"]: x for x in result["artifacts"]}
        for item in artifacts.values():
            if file_hash(item["path"]) != item["sha256"]:
                raise ValueError("A fitted artifact changed before refinement")
        with np.load(artifacts["state_estimate"]["path"]) as fit:
            target = fit["states"][0].copy()
            stop = float(fit["times"][-1])
            mjd = float(fit["mjd"][0])
        model = ET.parse(artifacts["native_fit_configuration"]["path"]).getroot().find(".//leoDynamicOrbits")
        values = backend.read_native_table(artifacts["native_parameters"]["path"], 1).reshape(-1)
        outputs, offgrid, evidence = [], [], []
        for step, label in steps:
            folder = root / method / label
            folder.mkdir(parents=True, exist_ok=True)
            with np.load(references[label]) as truth:
                keep = truth["times"] <= stop + 1e-6
                np.savez(folder / "reference.npz", times=truth["times"][keep], states=truth["states"][keep])
            instruments = write_truth_instruments(folder / "reference.npz", folder, case["epoch"])
            save_matrix(folder / "initial.txt", target)
            save_matrix(folder / "parameters.txt", values if method == "groops_pulses" else np.zeros_like(values))
            tree = ET.Element("groops")
            program = deepcopy(ET.parse(artifacts["native_variational_configuration"]["path"]).getroot().find(
                ".//PreprocessingVariationalEquation"))
            program.find("outputfileVariational").text = str(folder / "variational.dat")
            program.find("inputfileOrbit").text = instruments["orbit"]
            program.find("inputfileStarCamera").text = instruments["attitude"]
            for density in program.findall(".//inputfileLogDensity"):
                density.text = artifacts["posterior_log_density"]["path"]
            resolve_daily_variables(program, date, mjd, duration)
            ET.SubElement(tree, "program").append(program)
            helper = ET.SubElement(ET.SubElement(tree, "program"), "OrbitPocEvaluateVariational")
            for tag, filename in (("inputfileVariational", "variational.dat"), ("outputfileOrbit", "fixed_orbit.txt"),
                ("inputfileParameters", "parameters.txt"), ("inputfileInitialState", "initial.txt"),
                ("outputfileParameters", "reanchored_parameters.txt")):
                ET.SubElement(helper, tag).text = str(folder / filename)
            for tag in ("parametrizationAcceleration", "stochasticPulse", "ephemerides", "integrationDegree"):
                element = model.find(tag)
                if element is not None:
                    element = deepcopy(element)
                    resolve_daily_variables(element, date, mjd, duration)
                    for density in element.findall(".//inputfileLogDensity"):
                        density.text = artifacts["posterior_log_density"]["path"]
                    helper.append(element)
            add_offgrid_interpolation(tree, folder, mjd, stop, args.coarse_step)
            ET.indent(tree)
            ET.ElementTree(tree).write(folder / "evaluate.xml", encoding="utf-8", xml_declaration=True)
            backend.run_native(binary, folder / "evaluate.xml", folder, "refinement")
            orbit = backend.read_native_table(folder / "fixed_orbit.txt", 10)
            seconds = np.rint((orbit[:, 0] - mjd) * 86400 * 2) / 2
            outputs.append(orbit[np.isclose(seconds % 30, 0, atol=1e-5)])
            offgrid.append(backend.read_native_table(folder / "offgrid_orbit.txt", 10))
            for name in ("evaluate.xml", "reference.npz", "initial.txt", "parameters.txt",
                         "reanchored_parameters.txt", "fixed_orbit.txt", "refinement.execution.json",
                         "offgrid_epochs.txt", "offgrid_orbit.txt"):
                evidence.append({"path": str((folder / name).relative_to(root)), "sha256": file_hash(folder / name)})
        coarse, fine = outputs
        if coarse.shape != fine.shape or not np.allclose(coarse[:, 0], fine[:, 0], rtol=0, atol=1e-10):
            raise ValueError("Refinement outputs do not share the same observation epochs")
        position = float(np.linalg.norm(coarse[:, 1:4] - fine[:, 1:4], axis=1).max())
        if offgrid[0].shape != offgrid[1].shape or not np.allclose(offgrid[0][:, 0], offgrid[1][:, 0], rtol=0, atol=1e-10):
            raise ValueError("Off-grid interpolation outputs do not share identical requested epochs")
        offgrid_position = float(np.linalg.norm(offgrid[0][:, 1:4] - offgrid[1][:, 1:4], axis=1).max())
        results.append({"method": method, "epochs": len(coarse), "coarse_seconds": args.coarse_step,
            "fine_seconds": args.fine_step,
            "max_position_difference_m": position,
            "max_velocity_difference_m_s": float(np.linalg.norm(coarse[:, 4:7]-fine[:, 4:7], axis=1).max()),
            "initial_state_difference_max": float(np.max(np.abs(coarse[0, 1:7]-fine[0, 1:7]))),
            "offgrid_epochs": len(offgrid[0]), "offgrid_max_position_difference_m": offgrid_position,
            "offgrid_max_velocity_difference_m_s": float(np.linalg.norm(offgrid[0][:, 4:7]-offgrid[1][:, 4:7], axis=1).max()),
            "phase_geometry_bound_m": max(position, offgrid_position), "phase_threshold_m": 3e-5, "code_threshold_m": .003,
            "passed": max(position, offgrid_position) < 3e-5, "artifacts": evidence})
        print(method, "maximum aligned/off-grid position difference", position, offgrid_position, "m", flush=True)
    passed = all(x["passed"] for x in results)
    write_json(root / "refinement.json", {"status": "passed" if passed else "failed", "results": results,
        "source_hash": source_snapshot()["sha256"], "native_binary_sha256": file_hash(binary), "case": case,
        "production_numerical_gate_complete": False,
        "scope": "Native force integration and variational evaluation at a fixed fitted physical initial state "
                 "and fixed posterior density/pulses. State reanchoring is linearized. Nearly identical "
                 "Tudat reference geometry is used only for this numerical diagnostic, never fitting. "
                 "Euclidean position difference bounds common geometric code/carrier range with fixed nuisance parameters."})
    if not passed:
        raise RuntimeError("Native refinement exceeds the phase accuracy threshold")


def run_physics(args):
    """Broader force/interpolation diagnostic, without a GNSS accuracy claim."""
    root = args.output.resolve()
    binary = frozen_binary(args.groops, root / "bin")
    templates = args.fit_directory.resolve()
    steps = ((args.coarse_step, "coarse"), (args.fine_step, "fine"))
    if not 0 < args.fine_step < args.coarse_step or any(60 / s != round(60 / s) for s, _ in steps):
        raise ValueError("Positive fine < coarse steps must divide each 60-second density segment")
    stop = args.duration_hours * 3600 - args.coarse_step
    records = []
    for orbit in args.orbits:
        for atmosphere in args.atmospheres:
            cell = root / f"{orbit}-{atmosphere}"
            case = {"orbit": orbit, "atmosphere": atmosphere, "duration_hours": args.duration_hours,
                    "epoch": args.epoch, "seed": args.seed, "coverage": "normal", "truth_profile": "controlled"}
            references = {}
            for step, label in steps:
                references[label] = generate({**case, "cadence": step, "truth_step_seconds": step},
                    cell / "truth" / label, truth_backend="tudat", tudat_python=str(args.tudat_python.resolve()))["truth"]
            with np.load(references["coarse"]) as truth:
                target = truth["states"][0].copy()
                sample = np.rint(np.arange(0., args.duration_hours * 3600 + 1e-6, 60.) / args.coarse_step).astype(int)
                log_density = truth["log_density_correction"][sample]
            for method in METHODS:
                baseline = read_json(templates / method / "result.json")
                artifact = {item["role"]: item["path"] for item in baseline["artifacts"]}
                model = ET.parse(artifact["native_fit_configuration"]).getroot().find(".//leoDynamicOrbits")
                outputs, queries, evidence = [], [], []
                for step, label in steps:
                    folder = cell / method / label
                    folder.mkdir(parents=True, exist_ok=True)
                    with np.load(references[label]) as truth:
                        keep = truth["times"] <= stop + 1e-6
                        np.savez(folder / "reference.npz", times=truth["times"][keep], states=truth["states"][keep])
                    instruments = write_truth_instruments(folder / "reference.npz", folder, args.epoch)
                    mjd = instruments["mjd_start"]
                    gfile = folder / "prescribed_log_density.txt"
                    with gfile.open("w") as stream:
                        for second, value in zip(np.arange(len(log_density)) * 60., log_density):
                            epoch = np.longdouble(mjd) + np.longdouble(second) / 86400
                            stream.write(np.format_float_positional(epoch, precision=18) + f" {value:.18e}\n")
                    program = deepcopy(ET.parse(artifact["native_variational_configuration"]).getroot().find(
                        ".//PreprocessingVariationalEquation"))
                    program.find("outputfileVariational").text = str(folder / "variational.dat")
                    program.find("inputfileOrbit").text = instruments["orbit"]
                    program.find("inputfileStarCamera").text = instruments["attitude"]
                    for node in program.findall(".//inputfileLogDensity"):
                        node.text = str(gfile)
                    resolve_daily_variables(program, args.epoch[:10], mjd, args.duration_hours * 3600)
                    tree = ET.Element("groops")
                    ET.SubElement(tree, "program").append(program)
                    helper = ET.SubElement(ET.SubElement(tree, "program"), "OrbitPocEvaluateVariational")
                    pulse_count = max(0, int(args.duration_hours * 3600 / 1200) - 1)
                    if method == "groops_pulses":
                        coefficients = np.zeros(3 * pulse_count + 6)
                        rng = np.random.default_rng(np.random.SeedSequence([args.seed, 782]))
                        coefficients[:-6] = args.pulse_amplitude_m_s * 1e6 * rng.uniform(-1, 1, 3 * pulse_count)
                        pulse = deepcopy(model.find("stochasticPulse"))
                        resolve_daily_variables(pulse, args.epoch[:10], mjd, args.duration_hours * 3600)
                        helper.append(pulse)
                    else:
                        # The prescribed nonlinear density curve is already in
                        # the force model; no density increment is added again.
                        coefficients = np.zeros(6)
                    save_matrix(folder / "parameters.txt", coefficients)
                    save_matrix(folder / "initial.txt", target)
                    for tag, name in (("inputfileVariational", "variational.dat"), ("outputfileOrbit", "fixed_orbit.txt"),
                        ("inputfileParameters", "parameters.txt"), ("inputfileInitialState", "initial.txt")):
                        ET.SubElement(helper, tag).text = str(folder / name)
                    for tag in ("ephemerides", "integrationDegree"):
                        helper.append(deepcopy(model.find(tag)))
                    add_offgrid_interpolation(tree, folder, mjd, stop, args.coarse_step)
                    ET.indent(tree)
                    ET.ElementTree(tree).write(folder / "evaluate.xml", encoding="utf-8", xml_declaration=True)
                    backend.run_native(binary, folder / "evaluate.xml", folder, "physics")
                    propagated = backend.read_native_table(folder / "fixed_orbit.txt", 10)
                    seconds = np.rint((propagated[:, 0] - mjd) * 86400 * 2) / 2
                    outputs.append(propagated[np.isclose(seconds % 30, 0, atol=1e-5)])
                    queries.append(backend.read_native_table(folder / "offgrid_orbit.txt", 10))
                    for name in ("evaluate.xml", "parameters.txt", "initial.txt", "prescribed_log_density.txt",
                                 "fixed_orbit.txt", "offgrid_epochs.txt", "offgrid_orbit.txt", "physics.execution.json"):
                        evidence.append({"path": str((folder / name).relative_to(root)), "sha256": file_hash(folder / name)})
                maxima = []
                for pair in (outputs, queries):
                    if pair[0].shape != pair[1].shape or not np.allclose(pair[0][:, 0], pair[1][:, 0], rtol=0, atol=1e-10):
                        raise ValueError("Native physical refinement has unmatched epochs")
                    maxima.append(float(np.linalg.norm(pair[0][:, 1:4] - pair[1][:, 1:4], axis=1).max()))
                record = {"orbit": orbit, "atmosphere": atmosphere, "method": method,
                    "duration_hours": args.duration_hours, "aligned_epochs": len(outputs[0]), "offgrid_epochs": len(queries[0]),
                    "max_aligned_position_difference_m": maxima[0], "max_offgrid_position_difference_m": maxima[1],
                    "coarse_seconds": args.coarse_step, "fine_seconds": args.fine_step,
                    "prescribed_pulse_amplitude_m_s": args.pulse_amplitude_m_s if method == "groops_pulses" else None,
                    "phase_threshold_m": 3e-5, "passed": max(maxima) < 3e-5, "artifacts": evidence}
                records.append(record)
                write_json(root / "physics_refinement.json", {"records": records, "complete": len(records) ==
                    2 * len(args.orbits) * len(args.atmospheres), "native_binary_sha256": file_hash(binary),
                    "scope": "Prescribed-force native integration and shared boundary-aware interpolation, not fitted posterior "
                        "validation, GNSS corrections, or operational orbit accuracy. Same fixed physical initial state "
                        "and pulse vector or density curve at both resolutions; state reanchoring is linearized.",
                    "production_numerical_gate_complete": False})
                print(orbit, atmosphere, method, maxima, "passed", record["passed"], flush=True)
    if not all(r["passed"] for r in records):
        raise RuntimeError("Some prescribed-force interpolation checks exceeded the carrier-phase threshold")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("fits", "refine", "physics", "compact"):
        sub = commands.add_parser(name)
        sub.add_argument("--groops", type=Path, required=True, help="Patched native executable, copied before execution")
        if name != "compact":
            sub.add_argument("--tudat-python", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        if name == "fits":
            for flag in ("example-directory", "auxiliary-dir", "cache-dir"):
                sub.add_argument("--" + flag, type=Path, required=True)
            sub.add_argument("--epoch", default="2024-04-24T00:00:00")
            sub.add_argument("--seed", type=int, default=300000)
            sub.add_argument("--duration-hours", type=float, default=1.)
            sub.add_argument("--orbit", choices=("leo300", "leo500", "leo800", "eccentric"), default="leo500")
            sub.add_argument("--atmosphere", choices=("quiet", "disturbed"), default="quiet")
            sub.add_argument("--mask-seconds", nargs=2, type=int, default=(1200, 1800))
            sub.add_argument("--reuse-observations", type=Path,
                help="Verified existing synthetic data_manifest.json; re-mask and rebuild bootstrap for both cases")
        else:
            sub.add_argument("--fit-directory", type=Path, required=True,
                help="Directory containing the two method subdirectories, e.g. FIT_OUTPUT/normal")
            if name != "compact":
                sub.add_argument("--coarse-step", type=float, default=5.)
                sub.add_argument("--fine-step", type=float, default=2.5)
            if name == "physics":
                sub.add_argument("--orbits", nargs="+", choices=("leo300", "leo500", "leo800", "eccentric"),
                                 default=("leo300", "leo500", "leo800", "eccentric"))
                sub.add_argument("--atmospheres", nargs="+", choices=("quiet", "disturbed"), default=("quiet", "disturbed"))
                sub.add_argument("--duration-hours", type=float, default=24.)
                sub.add_argument("--epoch", default="2024-04-24T00:00:00")
                sub.add_argument("--seed", type=int, default=300000)
                sub.add_argument("--pulse-amplitude-m-s", type=float, default=.01)
    args = parser.parse_args(argv)
    {"fits": run_fits, "refine": run_refinement, "physics": run_physics, "compact": run_compact}[args.command](args)


if __name__ == "__main__":
    main()
