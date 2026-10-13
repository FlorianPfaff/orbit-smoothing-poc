#!/usr/bin/env python3
"""Compare a native density design column with nonlinear fixed-state propagation.

This is an April development diagnostic, not orbit-accuracy validation. Each
finite-difference trajectory reevaluates every force until its reference closes;
it never uses the density design to produce the perturbed trajectory. The native
design retains GROOPS' low-degree gravity-only state-transition approximation.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
import argparse
import json
from pathlib import Path
import shutil
import time
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, write_json
from validate_comparison_native import frozen_binary, save_matrix


def field(parent, name, value):
    ET.SubElement(parent, name).text = str(value)


def program(tree, name):
    return ET.SubElement(ET.SubElement(tree, "program"), name)


def evaluate(tree, variational, output, initial, ephemerides, *, model=None, parameters=None):
    node = program(tree, "OrbitPocEvaluateVariational")
    for name, value in (("inputfileVariational", variational), ("outputfileOrbit", output),
                        ("inputfileInitialState", initial)):
        field(node, name, value)
    node.append(deepcopy(ephemerides))
    if model is not None:
        node.append(deepcopy(model))
    if parameters is not None:
        field(node, "inputfileParameters", parameters)
    return node


def convert(tree, source, output):
    node = program(tree, "FileConvert")
    field(node, "inputfile", source)
    field(node, "outputfile", output)


def standalone_tree(source_tree):
    """Keep the fitted native time origin and expressions without a float roundtrip."""
    global_node = source_tree.find("global")
    if global_node is None or any(global_node.find(f"time[@label='{name}']") is None
                                  for name in ("timeStart", "timeEnd")):
        raise ValueError("The source configuration must retain its native loop time globals")
    tree = ET.Element("groops")
    tree.append(deepcopy(global_node))
    return tree


def resolve_source_loop(node, date):
    # The source loop origin is GPS midnight even for a UTC-day state arc.
    # Its explicit offsetSeconds supplies +18 s exactly once. Replacing loopTime
    # with the first state MJD instead would silently double this offset.
    for child in node.iter():
        if child.text:
            child.text = child.text.replace("{loopTime:%D}", date).replace(
                "loopTimeEnd", "timeEnd").replace("loopTime", "timeStart")


def checked_binary(executable, result, directory):
    expected = result.get("native_binary_sha256")
    if not expected or file_hash(executable) != expected:
        raise ValueError("The derivative diagnostic must use the exact fitted native executable")
    binary = frozen_binary(executable, directory)
    if file_hash(binary) != expected:
        raise ValueError("Native executable changed while copying for the derivative diagnostic")
    return binary


def run(args):
    root = args.output.resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a fresh density derivative diagnostic directory")
    root.mkdir(parents=True, exist_ok=True)
    result = read_json(args.result)
    if result.get("method") != "groops_log_drag_ou" or not result.get("converged"):
        raise ValueError("A converged retained development density fit is required")
    binary = checked_binary(args.binary, result, root / "bin")
    artifacts = {item["role"]: item for item in result["artifacts"]}
    required = ("state_estimate", "native_variational", "native_variational_configuration",
                "native_fit_configuration", "native_attitude", "posterior_log_density", "native_runtime")
    for name in required:
        if file_hash(artifacts[name]["path"]) != artifacts[name]["sha256"]:
            raise ValueError(f"Changed source-fit artifact: {name}")
    with np.load(artifacts["state_estimate"]["path"]) as fit:
        initial = fit["states"][0].copy()
        first_mjd = float(fit["mjd"][0])
        duration = float(np.rint(fit["times"][-1]))
    fit_tree = ET.parse(artifacts["native_fit_configuration"]["path"]).getroot()
    model = fit_tree.find(".//leoDynamicOrbits")
    source_tree = ET.parse(artifacts["native_variational_configuration"]["path"]).getroot()
    template = deepcopy(source_tree.find(".//PreprocessingVariationalEquation"))
    # The fitted configuration supplies geometry, g and numerical controls;
    # the nonlinear force and its density design must use the same event path.
    atmosphere = template.find("forces/miscAccelerations/logDensity")
    if atmosphere is None:
        raise ValueError("Expected the shared flight log-density force")
    for node in template.findall("orbitPocAtmosphericForce"):
        template.remove(node)
    ET.SubElement(template, "orbitPocAtmosphericForce").append(deepcopy(atmosphere))
    knot_flag = template.find("orbitPocAtmosphericHasDensityKnots")
    if knot_flag is None:
        knot_flag = ET.SubElement(template, "orbitPocAtmosphericHasDensityKnots")
    knot_flag.text = "1"
    density_model = deepcopy(model.find("parametrizationAcceleration"))
    density_node = density_model.find("logDensity")
    if density_node is None:
        raise ValueError("Expected the native log-density design")
    event = density_node.find("orbitPocAtmosphereEvents")
    if event is None:
        event = ET.SubElement(density_node, "orbitPocAtmosphereEvents")
    event.text = "1"
    density_path = Path(artifacts["posterior_log_density"]["path"])
    density_rows = [line.split() for line in density_path.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    epochs = [row[0] for row in density_rows]
    density = np.array([float(row[1]) for row in density_rows])
    seconds = np.array([float((Decimal(epoch)-Decimal(epochs[0]))*86400) for epoch in epochs])
    column = int(np.argmin(np.abs(seconds-args.knot_hours*3600)))
    if not 0 < column < len(density)-1:
        raise ValueError("Choose an interior density knot")
    date = args.date
    resolve_source_loop(template, date)
    resolve_source_loop(density_model, date)
    save_matrix(root / "initial.txt", initial)
    initial_path = root / "initial.txt"
    ephemerides = model.find("ephemerides")
    tree = standalone_tree(source_tree)
    evaluate(tree, artifacts["native_variational"]["path"], root / "seed_orbit.dat",
             initial_path, ephemerides)
    path = backend._save_xml(tree, root / "seed.xml")
    seed_execution = backend.run_native(binary, path, root, "seed", timeout=args.timeout)

    def close_trajectory(label, displacement, reference):
        folder = root / label
        folder.mkdir(exist_ok=True)
        local_density = density.copy()
        local_density[column] += displacement
        backend._write_density_values(folder / "log_density.txt", epochs, local_density)
        shutil.copy2(reference, folder / "reference.dat")
        prior = None
        history = []
        start = time.monotonic()
        for iteration in range(1, args.maximum_iterations+1):
            step = folder / f"iteration-{iteration:02d}"
            step.mkdir(exist_ok=True)
            tree = standalone_tree(source_tree)
            node = deepcopy(template)
            for name, value in (("inputfileOrbit", folder / "reference.dat"),
                                ("inputfileStarCamera", artifacts["native_attitude"]["path"]),
                                ("outputfileVariational", folder / "variational.dat")):
                node.find(name).text = str(value)
            for item in node.findall(".//inputfileLogDensity"):
                item.text = str(folder / "log_density.txt")
            ET.SubElement(tree, "program").append(node)
            # No acceleration parameters or design columns occur in this path.
            evaluate(tree, folder / "variational.dat", folder / "propagated.dat",
                     initial_path, ephemerides)
            convert(tree, folder / "propagated.dat", folder / "propagated.txt")
            path = backend._save_xml(tree, step / "propagate.xml")
            execution = backend.run_native(binary, path, step, "propagate", timeout=args.timeout)
            table = backend.read_native_table(folder / "propagated.txt", 10)
            states = table[:, 1:7]
            delta = states-prior if prior is not None else None
            position_change = float(np.max(np.linalg.norm(delta[:, :3], axis=1))) if delta is not None else None
            velocity_change = float(np.max(np.linalg.norm(delta[:, 3:], axis=1))) if delta is not None else None
            closed = (delta is not None and position_change < args.closure_position_m
                      and velocity_change < args.closure_velocity_m_s)
            history.append({"iteration": iteration, "maximum_position_change_m": position_change,
                            "maximum_velocity_change_m_s": velocity_change, "closed": bool(closed),
                            "execution": execution})
            write_json(folder / "closure.json", {"label": label, "displacement": displacement,
                "closed": bool(closed), "iterations": history})
            print(json.dumps({"label": label, **{k:v for k,v in history[-1].items() if k!='execution'}}), flush=True)
            if closed:
                break
            prior = states.copy()
            shutil.copy2(folder / "propagated.dat", folder / "reference.dat")
        if not closed:
            raise RuntimeError(f"Nonlinear trajectory did not close: {label}")
        np.savez_compressed(folder / "states.npz", mjd=table[:, 0], states=states)
        return {"label": label, "displacement": displacement, "closed": True,
                "iterations": len(history), "elapsed_seconds": time.monotonic()-start,
                "final_position_change_m": position_change,
                "final_velocity_change_m_s": velocity_change, "states": states,
                "orbit": folder / "propagated.dat", "variational": folder / "variational.dat"}

    nominal = close_trajectory("nominal", 0., root / "seed_orbit.dat")
    # Reuse the converged nominal reference as an initial guess only. Every
    # perturbed branch evaluates all forces repeatedly on its own trajectory.
    tasks = [("plus", args.step), ("minus", -args.step),
             ("plus_half", .5*args.step), ("minus_half", -.5*args.step)]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        perturbed = list(pool.map(lambda item: close_trajectory(*item, nominal["orbit"]), tasks))
    branches = {item["label"]: item for item in perturbed}
    folder = root / "native_design"
    folder.mkdir(exist_ok=True)
    tree = standalone_tree(source_tree)
    for node in density_model.findall(".//inputfileLogDensity"):
        node.text = str(root / "nominal/log_density.txt")
    for label, amplitude in (("zero", 0.), ("column", 1.)):
        parameters = np.zeros(len(density)+6)
        parameters[column] = amplitude
        save_matrix(folder / f"{label}_parameters.txt", parameters)
        evaluate(tree, nominal["variational"], folder / f"{label}.dat", initial_path,
                 ephemerides, model=density_model, parameters=folder / f"{label}_parameters.txt")
        convert(tree, folder / f"{label}.dat", folder / f"{label}.txt")
    path = backend._save_xml(tree, folder / "evaluate.xml")
    design_execution = backend.run_native(binary, path, folder, "evaluate", timeout=args.timeout)
    design = (backend.read_native_table(folder / "column.txt", 10)[:, 1:7]
              -backend.read_native_table(folder / "zero.txt", 10)[:, 1:7])
    fd = (branches["plus"]["states"]-branches["minus"]["states"])/(2*args.step)
    half = (branches["plus_half"]["states"]-branches["minus_half"]["states"])/args.step
    extrapolated = (4*half-fd)/3
    # A fixed-initial-state derivative must vanish before the knot's support.
    # Observed pre-support values measure cancellation/closure noise directly.
    nominal_mjd = np.load(root / "nominal/states.npz")["mjd"]
    before_support = (nominal_mjd-nominal_mjd[0])*86400 < seconds[column-1]-.01
    metrics = {}
    for name, columns in (("position", slice(0, 3)), ("velocity", slice(3, 6))):
        error = np.linalg.norm(design[:, columns]-extrapolated[:, columns], axis=1)
        signal = np.linalg.norm(extrapolated[:, columns], axis=1)
        step_error = np.linalg.norm(fd[:, columns]-half[:, columns], axis=1)
        key = "final_position_change_m" if name == "position" else "final_velocity_change_m_s"
        coarse_noise = (branches["plus"][key]+branches["minus"][key])/(2*args.step)
        half_noise = (branches["plus_half"][key]+branches["minus_half"][key])/args.step
        metrics[name] = {"native_vs_fd_maximum_absolute_per_unit_log_density": float(error.max()),
            "native_vs_fd_relative_maximum_norm": float(error.max()/signal.max()),
            "native_vs_fd_relative_frobenius_norm": float(np.linalg.norm(design[:,columns]-extrapolated[:,columns])/np.linalg.norm(extrapolated[:,columns])),
            "fd_maximum_norm_per_unit_log_density": float(signal.max()),
            "fd_step_halving_maximum_difference": float(step_error.max()),
            "fd_step_halving_relative_maximum_norm": float(step_error.max()/signal.max()),
            "fd_richardson_correction_maximum_norm": float(np.max(np.linalg.norm(extrapolated[:,columns]-half[:,columns],axis=1))),
            "closure_change_proxy_per_unit_log_density": (4*half_noise+coarse_noise)/3,
            "pre_support_fd_maximum_norm": float(np.max(np.linalg.norm(extrapolated[before_support,columns],axis=1)))}
    np.savez_compressed(root / "derivatives.npz", native=design, finite_difference=fd,
                        finite_difference_half_step=half, finite_difference_richardson=extrapolated)
    records = [{k: v for k, v in item.items() if k not in ("states", "orbit", "variational")}
               for item in (nominal, *perturbed)]
    if file_hash(binary) != result["native_binary_sha256"]:
        raise ValueError("The frozen native executable changed during the derivative diagnostic")
    source_runtime = read_json(artifacts["native_runtime"]["path"])
    summary = {"status": "complete", "scope": "One April development density knot, fixed physical initial state, full-flight native forces",
        "scientific_acceptance": "Diagnostic only; no automatic exact-derivative or covariance acceptance",
        "approximation": "Native transition uses low-degree gravity-only state gradient; full drag, other force position/velocity gradients are omitted. The FD repropagates all nonlinear forces.",
        "native_binary_sha256": file_hash(binary), "source_result_sha256": file_hash(args.result),
        "source_fit_source_hash": source_runtime.get("source_hash"),
        "diagnostic_timing": "Post-fit diagnostic; its script revision may be newer than the source-fit revision, while the native executable is identical",
        "source_arc": result.get("arc"), "first_state_gps_mjd": first_mjd,
        "state_arc_duration_seconds": duration,
        "source_loop_globals": ET.tostring(source_tree.find("global"), encoding="unicode"),
        "thermal_maximum_step_seconds": float(template.findtext("forces/miscAccelerations/radiationPressure/orbitPocThermalMaximumStep", "1")),
        "atmospheric_quadrature_step_seconds": float(template.findtext("orbitPocAtmosphericQuadratureStep", "0")),
        "script_sha256": file_hash(__file__), "knot_index": column,
        "validation_helper_sha256": file_hash(Path(__file__).with_name("validate_comparison_native.py")),
        "seed_execution": seed_execution, "native_design_execution": design_execution,
        "knot_hours": seconds[column]/3600, "step": args.step,
        "comparison_derivative": "Central differences at h and h/2; (4 D(h/2)-D(h))/3 removes leading O(h^2) truncation",
        "precision_limitation": "The propagated last-iteration closure changes are an empirical derivative-noise proxy, not a mathematically certified error bound. Pre-support FD values provide a separate observed cancellation floor.",
        "state_gradient_maximum_degree": template.findtext("gradientfield/potentialCoefficients/maxDegree"),
        "force_gravity_maximum_degree": template.findtext("forces/gravityfield/potentialCoefficients/maxDegree"),
        "closure_position_tolerance_m": args.closure_position_m,
        "closure_velocity_tolerance_m_s": args.closure_velocity_m_s,
        "records": records, "metrics": metrics,
        "artifacts": [artifact_record("derivatives", root / "derivatives.npz")]}
    write_json(root / "density_trajectory_derivative.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "result", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    parser.add_argument("--date", default="2024-04-24")
    parser.add_argument("--knot-hours", type=float, default=6.)
    parser.add_argument("--step", type=float, default=.05)
    parser.add_argument("--maximum-iterations", type=int, default=10)
    parser.add_argument("--closure-position-m", type=float, default=2e-6)
    parser.add_argument("--closure-velocity-m-s", type=float, default=3e-9)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=3600.)
    args = parser.parse_args()
    if (not np.isfinite(args.step) or args.step <= 0 or not 1 <= args.workers <= 4
        or args.maximum_iterations < 2 or args.closure_position_m <= 0 or args.closure_velocity_m_s <= 0):
        parser.error("Positive step/closure limits, at least two iterations, and 1–4 workers are required")
    run(args)
