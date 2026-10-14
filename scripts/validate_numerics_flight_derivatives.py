#!/usr/bin/env python3
"""Quantify omitted flight tangent terms with independently closed trajectories.

The default window is Apr24 11:45--12:15 UTC: a development case, not a new
evaluation result. No GNSS estimation, reference ephemeris or SLR is loaded.
Every perturbation rebuilds the actual full force model in fresh processes.
"""
from copy import deepcopy
from dataclasses import asdict
from decimal import Decimal
import argparse
import json
import platform
import sys
from pathlib import Path
import time
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.initialization import _field, _standalone
from orbit_poc.comparison.protocol import file_hash, write_json
from orbit_poc.numerics.backend import NativeModel, PhysicalState
from orbit_poc.numerics.config import Controls


class PropagationDiagnostic(NativeModel):
    """Reuse closure without constructing an estimator or accessing GNSS data."""

    def __init__(self, binary, directory):
        self.binary, self.root = Path(binary).resolve(), Path(directory).resolve()
        self.density = False  # Zero fixed pulses; no new physical force component.
        self.derivatives = "flight_gravity_drag_v1"
        self.controls = Controls()
        self.start = time.monotonic()
        self.executions, self.propagations, self.sequence = [], 0, 0


def crop_instrument(input_path, output_path, start, duration, expected_kind):
    """Preserve native epoch tokens/quaternions exactly, including the endpoint."""
    rows, sampling = [], None
    for line in Path(input_path).read_text().splitlines():
        tokens = line.split()
        if len(tokens) != (10 if expected_kind == -6 else 5) or line.startswith("#"):
            continue
        try:
            epoch = Decimal(tokens[0])
        except Exception:
            continue
        seconds = (epoch-start)*Decimal(86400)
        if Decimal("-0.00001") <= seconds <= Decimal(str(duration))+Decimal("0.00001"):
            rows.append(line)
    if len(rows) < 9:
        raise ValueError("Flight derivative window has insufficient native support")
    times = np.array([float((Decimal(row.split()[0])-start)*Decimal(86400)) for row in rows])
    sampling = float(np.median(np.diff(times)))
    if abs(times[0]) > 1e-5 or abs(times[-1]-duration) > 1e-5 or not np.allclose(np.diff(times), sampling, atol=2e-6, rtol=0):
        raise ValueError("Flight derivative window must retain its complete regular native grid and endpoint")
    Path(output_path).write_text(f"groops instrument version=20200123\n{expected_kind} 1\n{len(rows)}\n"+"\n".join(rows)+"\n")
    return {"epochs": len(rows), "sampling_seconds": sampling, "sha256": file_hash(output_path)}


def prepare(source_manifest, binary, directory, start_seconds, duration):
    root = Path(directory).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a new diagnostic output directory; existing evidence is never overwritten")
    root.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(Path(source_manifest).read_text())
    if manifest.get("date") != "2024-04-24" or manifest.get("arc", {}).get("time_scale") != "UTC":
        raise ValueError("This predeclared development diagnostic requires the Apr24 UTC preparation")
    model = PropagationDiagnostic(binary, root)
    source = ET.parse(manifest["configs"]["variational"]).getroot()
    template = deepcopy(source.find(".//PreprocessingVariationalEquation"))
    if template is None or template.find("inputfileAccelerometer") is not None:
        raise ValueError("Expected a modeled-force flight propagation without measured accelerometer forces")
    gravity = template.find("forces/gravityfield/potentialCoefficients/maxDegree")
    if gravity is None or int(gravity.text) != 120 or template.find("forces/miscAccelerations/atmosphericDrag") is None:
        raise ValueError("Expected actual degree120 gravity and native atmospheric drag")
    for radiation in template.findall("forces/miscAccelerations/radiationPressure"):
        _field(radiation, "orbitPocThermalMaximumStep", "0.1")
    for name in ("outputfileOrbit", "outputfileVariational", "estimatedParameters"):
        for node in list(template.findall(name)):
            template.remove(node)
    _field(template, "outputfileVariational", root / "unused-output.dat")
    inputs = root / "inputs"
    inputs.mkdir()
    converted = {}
    for key in ("orbit", "attitude"):
        config = native._file_conversion(manifest["native_paths"][key], inputs / (key+"-full.txt"), inputs / (key+"-convert.xml"))
        model.execute(ET.parse(config).getroot(), inputs, key+"-convert")
    day = Decimal(source.find("global/time[@label='timeStart']").text)
    offset = Decimal(str(manifest["arc"]["gps_start_offset_seconds"])) + Decimal(str(start_seconds))
    start = day + offset/Decimal(86400)
    for key, kind in (("orbit", -6), ("attitude", -7)):
        converted[key] = crop_instrument(inputs/(key+"-full.txt"), inputs/(key+".txt"), start, duration, kind)
    _field(template, "inputfileOrbit", inputs / "orbit.txt")
    _field(template, "inputfileStarCamera", inputs / "attitude.txt")
    global_node = deepcopy(source.find("global"))
    global_node.find("time[@label='timeEnd']").text = f"timeStart+{duration}/86400"
    global_node.find("double[@label='arcStartOffsetSeconds']").text = str(offset)
    boundaries = template.find("integrationBoundaries/uniformSampling")
    if boundaries is not None:
        _field(boundaries, "offsetSeconds", offset)
    standalone = ET.Element("groops")
    standalone.append(global_node)
    ET.SubElement(standalone, "program").append(template)
    variational = native._save_xml(standalone, inputs / "variational.xml")
    estimate = ET.Element("groops")
    # A zero-dimensional acceleration/pulse vector leaves only six physical
    # initial-state columns. No GNSS processing program is ever executed here.
    dynamic = ET.SubElement(ET.SubElement(ET.SubElement(estimate, "GnssProcessing"), "parametrization"), "leoDynamicOrbits")
    _field(dynamic, "integrationDegree", 7)
    _field(dynamic, "interpolationDegree", 7)
    estimate_path = native._save_xml(estimate, inputs / "design-config.xml")
    configured = {"configs": {"variational": str(variational), "estimate": str(estimate_path)},
                  "native_paths": {}, "date": manifest["date"]}
    _, states = native._orbit(inputs / "orbit.txt")
    state = PhysicalState(states[0].copy(), np.zeros(0), inputs / "orbit.txt")
    physical_inputs = {}
    for node in template.iter():
        if node.text and node.tag.startswith("inputfile"):
            path = Path(node.text)
            if path.is_file():
                if any(name in str(path).upper() for name in ("GNV1B", "NP2", "NP3")):
                    raise ValueError("Independent evaluation/reference input entered derivative diagnostic")
                physical_inputs[str(path)] = file_hash(path)
    receipt = {"schema": "flight-derivative-diagnostic-3.1", "status": "running",
        "profile": "flight_gravity_drag_v1", "date": manifest["date"], "start_utc_seconds": start_seconds,
        "duration_seconds": duration, "binary_sha256": file_hash(binary),
        "diagnostic_source_sha256": file_hash(__file__), "python_version": platform.python_version(),
        "python_executable": sys.executable, "numpy_version": np.__version__, "source_preparation_sha256": file_hash(source_manifest),
        "source_variational_sha256": file_hash(manifest["configs"]["variational"]), "actual_config_sha256": file_hash(variational),
        "original_geometry_sha256": {key: file_hash(manifest["native_paths"][key]) for key in ("orbit", "attitude")},
        "physical_input_hashes": physical_inputs, "cropped_geometry": converted,
        "position_perturbations_m": [200., 100.], "velocity_perturbations_m_s": [.2, .1],
        "force_configuration": "actual degree120 gravity, tides, third bodies, radiation pressure/thermal and JB2008; frozen known attitude",
        "thermal_maximum_step_seconds": .1, "closure_controls": asdict(model.controls),
        "reference_orbit_used": False, "gnss_fit_performed": False,
        "force_history_policy": "Fresh native force state initialized at window start for every propagation; this is a standalone 30-minute arc, not a slice of a warmed 24-hour trajectory",
        "scope": "One predeclared 30-minute Apr24 development window; cannot certify a complete 24-hour flight Jacobian"}
    write_json(root / "result.json", receipt)
    return model, configured, state, receipt


def run(source_manifest, binary, directory, start_seconds=42300., duration=1800.):
    model, config, state, result = prepare(source_manifest, binary, directory, start_seconds, duration)
    root = Path(directory).resolve()
    try:
        baseline = root / "baseline"
        baseline.mkdir()
        orbit, variable, _, _, epochs, states = model._close(state, deepcopy(config), baseline, True)
        # Export native Phi(t) Phi(t0)^-1, preserving the physical SI initial
        # state basis rather than comparing the archive's scaled velocity columns.
        program = ET.Element("OrbitPocStateDerivatives")
        _field(program, "inputfileVariational", variable)
        _field(program, "outputfileStateTransition", baseline / "physical-stm.txt")
        model.execute(_standalone(ET.parse(config["configs"]["variational"]).getroot(), [program], config["date"]), baseline, "export-stm")
        exported = native.read_native_table(baseline / "physical-stm.txt", 43)
        if len(exported) != len(states):
            raise ValueError("Native physical STM and closed trajectory have different support")
        phi = exported[:, 7:].reshape(-1, 6, 6)
        result["columns"] = []
        for axis in range(6):
            derivatives = []
            for step in ([200., 100.] if axis < 3 else [.2, .1]):
                perturbed = []
                for sign in (-1, 1):
                    initial = state.initial.copy()
                    initial[axis] += sign*step
                    folder = root / f"axis-{axis}-step-{step:g}-sign-{sign:+d}"
                    folder.mkdir()
                    trial = PhysicalState(initial, np.zeros(0), orbit)
                    *_, trial_epochs, trial_states = model._close(trial, deepcopy(config), folder, True)
                    if not np.array_equal(trial_epochs, epochs):
                        raise ValueError("Full nonlinear perturbation changed trajectory support")
                    perturbed.append(trial_states)
                derivatives.append((perturbed[1]-perturbed[0])/(2*step))
            coarse, fine = derivatives
            discrepancy = phi[:, :, axis]-fine
            refinement = fine-coarse
            relative = float(np.linalg.norm(refinement[:, :3])/max(np.linalg.norm(fine[:, :3]), 1e-30))
            record = {"initial_component": ("x", "y", "z", "vx", "vy", "vz")[axis],
                "column_input_unit": "m" if axis < 3 else "m/s",
                "maximum_position_jacobian_discrepancy": float(np.max(np.linalg.norm(discrepancy[:, :3], axis=1))),
                "maximum_velocity_jacobian_discrepancy": float(np.max(np.linalg.norm(discrepancy[:, 3:], axis=1))),
                "maximum_position_half_step_disagreement": float(np.max(np.linalg.norm(refinement[:, :3], axis=1))),
                "maximum_velocity_half_step_disagreement": float(np.max(np.linalg.norm(refinement[:, 3:], axis=1))),
                "relative_position_half_step_disagreement": relative,
                "step_refinement_resolved": bool(relative < 1e-5),
                "position_discrepancy_resolved_above_step_error": bool(np.max(np.linalg.norm(discrepancy[:, :3], axis=1)) > 5*np.max(np.linalg.norm(refinement[:, :3], axis=1)))}
            np.savez_compressed(root / f"axis-{axis}-derivatives.npz", epochs=epochs, native=phi[:, :, axis], coarse=coarse, fine=fine)
            result["columns"].append(record)
            write_json(root / "result.json", result)
        diagnostics = [json.loads(path.read_text()) for path in root.glob("*/closure-*/derivatives.json")]
        result["drag_finite_difference"] = {"maximum_relative_step_disagreement": max(item["drag_fd_maximum_relative_difference"] for item in diagnostics),
            "evaluations": sum(item["drag_fd_evaluations"] for item in diagnostics),
            "initial_position_step_m": diagnostics[0]["drag_fd_initial_position_step_m"],
            "accepted_position_step_range_m": [min(item["drag_fd_position_step_range_m"][0] for item in diagnostics),max(item["drag_fd_position_step_range_m"][1] for item in diagnostics)],
            "initial_velocity_step_m_s": diagnostics[0]["drag_fd_initial_velocity_step_m_s"],
            "accepted_velocity_step_range_m_s": [min(item["drag_fd_velocity_step_range_m_s"][0] for item in diagnostics),max(item["drag_fd_velocity_step_range_m_s"][1] for item in diagnostics)]}
        for name in ("drag_fd_position_derivative_floor_s_minus2","drag_fd_velocity_derivative_floor_s_minus1",
                     "drag_fd_position_absolute_tolerance_s_minus2","drag_fd_velocity_absolute_tolerance_s_minus1"):
            values={item[name] for item in diagnostics}
            if len(values)!=1:raise ValueError("Native drag finite-difference controls changed between closures")
            result["drag_finite_difference"][name.removeprefix("drag_fd_")]=values.pop()
        for name in ("drag_fd_maximum_position_absolute_difference_s_minus2","drag_fd_maximum_velocity_absolute_difference_s_minus1",
                     "drag_fd_maximum_position_unfloored_relative_difference","drag_fd_maximum_velocity_unfloored_relative_difference"):
            result["drag_finite_difference"][name.removeprefix("drag_fd_")]=max(item[name] for item in diagnostics)
        for name in ("drag_fd_position_floor_applied_columns","drag_fd_velocity_floor_applied_columns"):
            result["drag_finite_difference"][name.removeprefix("drag_fd_")]=sum(item[name] for item in diagnostics)
        result["omitted_terms"] = diagnostics[0]["omitted_terms"]
        result["status"] = "quantified" if all(item["step_refinement_resolved"] for item in result["columns"]) else "refinement_unresolved"
        result["propagations"] = model.propagations
        result["elapsed_seconds"] = time.monotonic()-model.start
        result["execution_peak_memory_bytes"] = max((item.get("peak_rss_bytes", 0) for item in model.executions), default=0)
        write_json(root / "result.json", result)
        return result
    except Exception as error:
        result["status"], result["error"] = "failed", str(error)
        result["propagations"] = model.propagations
        write_json(root / "result.json", result)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--start-seconds", type=float, default=42300.)
    parser.add_argument("--duration-seconds", type=float, default=1800.)
    args = parser.parse_args()
    print(json.dumps(run(args.prepared, args.binary, args.output, args.start_seconds, args.duration_seconds), indent=2))
