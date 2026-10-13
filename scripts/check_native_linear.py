#!/usr/bin/env python3
"""Replay a small native fit and check actual weighted rows with GTSAM/QR.

Example:
  PYTHONPATH=src python scripts/check_native_linear.py --binary /path/to/groops \
    --fit-directory /path/to/finished/native-fit --output work/native-linear

The fit inputs are read-only. All diagnostic outputs, the frozen executable and
raw trace arrays live in the requested work directory. No truth is accessed.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from orbit_poc.comparison.backend import run_native
from orbit_poc.comparison.density import native_trace_gate
from orbit_poc.comparison.protocol import file_hash, write_json


def run_gate(binary, fit_directory, output, timeout=600.):
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty diagnostic output directory")
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "groops"
    shutil.copy2(binary, frozen)
    tree = ET.parse(Path(fit_directory) / "estimate.xml")
    processing = tree.getroot().find(".//GnssProcessing")
    if processing is None:
        raise ValueError("The completed native fit has no GnssProcessing configuration")
    for node in list(processing.findall("processingStep")):
        processing.remove(node)
    native_output = output / "native-output"; native_output.mkdir()
    for node in processing.iter():
        if node.tag.startswith("outputfile") and node.text:
            node.text = str(native_output / Path(node.text).name)
    model = processing.find(".//leoDynamicOrbits")
    if model is not None:
        native = model.find("outputfileOrbitNative")
        if native is None:
            native = ET.SubElement(model, "outputfileOrbitNative")
        native.text = str(native_output / "fitted_orbit.dat")
    def step(choice, fields=None):
        parent = ET.SubElement(ET.SubElement(processing, "processingStep"), choice)
        for key, value in (fields or {}).items():
            ET.SubElement(parent, key).text = str(value)
    step("selectNormalsBlockStructure", {"keepEpochNormalsInMemory":1})
    step("estimate", {"computeResiduals":0, "computeWeights":0, "adjustSigma0":0, "maxIterationCount":1})
    step("computeCovarianceMatrix")
    step("writeResults")
    step("writeAprioriSolution", {"outputfileAprioriSolution":str(output / "final_solution.txt"),
                                 "outputfileParameterNames":str(output / "parameter_names.txt")})
    configuration = output / "trace.xml"
    ET.indent(tree, space="  ")
    tree.write(configuration, encoding="utf-8", xml_declaration=True)
    previous = os.environ.get("ORBIT_POC_LINEAR_TRACE")
    os.environ["ORBIT_POC_LINEAR_TRACE"] = str(output / "linear")
    try:
        execution = run_native(frozen, configuration, output, "native-trace", timeout=timeout)
    finally:
        if previous is None:
            os.environ.pop("ORBIT_POC_LINEAR_TRACE", None)
        else:
            os.environ["ORBIT_POC_LINEAR_TRACE"] = previous
    snapshots = []
    for path in sorted(output.glob("linear.*.rhs.tsv")):
        stem = Path(str(path).removesuffix(".rhs.tsv"))
        if Path(str(stem)+".delta.txt").exists() or Path(str(stem)+".covariance.tsv").exists():
            snapshots.append(native_trace_gate(stem, configuration=configuration))
    checks = {name for snapshot in snapshots for name in snapshot["native_checks"]}
    complete = {"native_map", "native_covariance", "native_prior_rows"} <= checks
    result = {"passed":complete and all(snapshot["passed"] for snapshot in snapshots),
              "all_required_checks_present":complete, "snapshots":snapshots, "execution":execution,
              "native_binary_sha256":file_hash(frozen), "source_fit_directory":str(Path(fit_directory).resolve()),
              "interpretation":"Native weighted rows before normal-equation assembly; exact nuisance marginalization; no truth used"}
    write_json(output / "gate.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--fit-directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=600.)
    args = parser.parse_args()
    result = run_gate(args.binary, args.fit_directory, args.output, args.timeout)
    print(json.dumps({"passed":result["passed"], "report":str((args.output / "gate.json").resolve())}, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
