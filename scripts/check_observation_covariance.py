#!/usr/bin/env python3
"""Check small native Cartesian covariance exports using linear basis probes.

A separate native variational evaluator probes every dynamic parameter at the
nominal GNSS epochs. Python forms J P J^T from the full nuisance-marginalized
parameter covariance. This checks output epochs, column order and cross terms;
GTSAM/QR separately validates the native full inverse. It is an engineering
check of the linearized model, not a nonlinear uncertainty-calibration result.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import shutil
import xml.etree.ElementTree as ET
import numpy as np

from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import file_hash, read_json, write_json


def check(binary, fit_directory, output, maximum_parameters=128):
    fit_directory, root = Path(fit_directory).resolve(), Path(output).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a fresh covariance diagnostic directory")
    root.mkdir(parents=True, exist_ok=True)
    result = read_json(fit_directory / "result.json")
    if not result.get("converged") or not result.get("covariance_valid"):
        raise ValueError("A converged diagnostic fit with valid covariance is required")
    expected_binary_sha = result.get("native_binary_sha256")
    if not expected_binary_sha or file_hash(binary) != expected_binary_sha:
        raise ValueError("Basis probes must use the exact fitted native executable")
    fitted_path = backend._artifact(result, "native_fit_configuration")
    p_path = backend._artifact(result, "native_parameter_covariance")
    native_path = backend._artifact(result, "observation_epoch_covariance")
    variational = backend._artifact(result, "native_variational")
    parameter_covariance = backend.read_native_table(p_path)
    count = parameter_covariance.shape[0]
    if parameter_covariance.shape != (count, count) or not 1 <= count <= maximum_parameters:
        raise ValueError("This basis-probe diagnostic is restricted to small square covariance problems")
    native = backend.read_native_table(native_path, 37)
    fitted = ET.parse(fitted_path).getroot()
    gnss = fitted.find(".//GnssProcessing")
    dynamic = gnss.find("parametrization/leoDynamicOrbits")
    config = ET.Element("groops")
    config.append(deepcopy(fitted.find("global")))
    start = float(fitted.find("global/time[@label='timeStart']").text)
    job = read_json(fit_directory / "request.json")
    duration = float(job["case"].get("duration_hours", 24.))*3600
    date = job["case"].get("date", job["case"].get("epoch", ""))[:10]
    amplitude = 1e4  # The evaluator is linear; this reduces subtractive rounding.
    for index in range(count):
        for sign, label in ((-1., "minus"), (1., "plus")):
            vector = np.zeros(count); vector[index] = sign*amplitude
            vector_path = root / f"basis-{index:04d}-{label}.txt"
            vector_path.write_text(f"groops matrix version=20200123\nMatrix( {count} x 1 )\n"+
                                   "\n".join(format(x, '.17g') for x in vector)+"\n")
            program = ET.SubElement(ET.SubElement(config, "program"), "OrbitPocEvaluateVariational")
            for key, value in (("inputfileVariational", variational), ("inputfileParameters", vector_path),
                               ("outputfileOrbit", root / f"orbit-{index:04d}-{label}.txt")):
                ET.SubElement(program, key).text = str(value)
            program.append(deepcopy(gnss.find("timeSeries")))
            for key in ("ephemerides", "parametrizationAcceleration", "stochasticPulse",
                        "integrationDegree", "interpolationDegree"):
                for node in dynamic.findall(key):
                    program.append(deepcopy(node))
    for node in config.iter():
        if node.text:
            node.text = node.text.replace("{loopTime:%D}", date).replace(
                "loopTimeEnd", f"({start:.17g}+{duration:.17g}/86400)").replace("loopTime", f"{start:.17g}")
    binary_path = root / "groops"
    shutil.copy2(binary, binary_path)
    if file_hash(binary_path) != expected_binary_sha:
        raise ValueError("Native executable changed while copying for basis probes")
    configuration = backend._save_xml(config, root / "basis.xml")
    execution = backend.run_native(binary_path, configuration, root, "basis", timeout=3600.)
    design = np.empty((len(native), 6, count))
    raw_artifacts = []
    for index in range(count):
        states = []
        for label in ("minus", "plus"):
            path = root / f"orbit-{index:04d}-{label}.txt"
            epoch, state = backend._orbit(path)
            if epoch.shape != native[:, 0].shape or not np.allclose(epoch, native[:, 0], rtol=0, atol=1e-10):
                raise ValueError("Basis-probe and native observation covariance epochs differ")
            states.append(state)
            raw_artifacts.append({"path":path.name, "sha256":file_hash(path)})
        design[:, :, index] = (states[1]-states[0])/(2*amplitude)
    propagated = np.einsum('eip,pq,ejq->eij', design, parameter_covariance, design, optimize=True)
    actual = native[:, 1:].reshape(-1, 6, 6)
    scale = np.sqrt(np.diagonal(actual, axis1=1, axis2=2))
    normalized_error = (propagated-actual)/scale[:, :, None]/scale[:, None, :]
    maximum = float(np.max(np.abs(normalized_error)))
    threshold = 1e-6
    np.savez_compressed(root / "covariance_check.npz", mjd=native[:,0], design=design,
                        parameter_covariance=parameter_covariance, native=actual, propagated=propagated)
    report = {"passed":maximum < threshold, "maximum_normalized_covariance_error":maximum,
              "threshold":threshold, "normalization":"sqrt(C_ii C_jj) of native Cartesian covariance",
              "parameters":count, "epochs":len(native), "basis_amplitude_native_units":amplitude,
              "native_binary_sha256":file_hash(binary_path), "execution":execution,
              "inputs":[{"path":str(path), "sha256":file_hash(path)} for path in
                        (fit_directory / "result.json", fit_directory / "request.json",
                         fitted_path, p_path, native_path, variational)], "basis_orbits":raw_artifacts,
              "scope":__doc__.strip()}
    write_json(root / "gate.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--fit-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--maximum-parameters", type=int, default=128)
    args = parser.parse_args()
    report = check(args.binary, args.fit_directory, args.output, args.maximum_parameters)
    print({key:report[key] for key in ("passed", "parameters", "epochs", "maximum_normalized_covariance_error")})
    raise SystemExit(0 if report["passed"] else 1)
