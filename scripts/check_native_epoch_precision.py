#!/usr/bin/env python3
"""Verify native Time preservation and reconstruct an old fitted binary orbit.

This evaluates the same final variational equations at the same complete native
parameter vector. It does not estimate parameters or access evaluation data.
The diagnostic compares native split-day Time values, never double MJD values.
"""
from copy import deepcopy
import argparse
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison.backend import _save_xml, _file_conversion, _orbit, read_native_table, run_native
from orbit_poc.comparison.protocol import read_json, write_json, file_hash, artifact_record


def run_gate(binary, fit_result, output, sampling=5.):
    result = read_json(fit_result)
    artifacts = {item["role"]:item for item in result["artifacts"]}
    for role in ("native_fit_configuration", "native_variational", "native_parameters", "estimated_orbit"):
        if file_hash(artifacts[role]["path"]) != artifacts[role]["sha256"]:
            raise ValueError(f"Changed fitted artifact: {role}")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a fresh epoch-regression directory")
    output.mkdir(parents=True)
    frozen = output / "groops"; shutil.copy2(binary, frozen)
    model = ET.parse(artifacts["native_fit_configuration"]["path"]).getroot().find(".//leoDynamicOrbits")
    if model is None:
        raise ValueError("Native LEO configuration required")
    execution = []
    for label, reference in (("ascii", artifacts["estimated_orbit"]["path"]),
                             ("binary", str(output / "reconstructed.dat"))):
        root = ET.Element("groops")
        program = ET.SubElement(ET.SubElement(root,"program"),"OrbitPocEvaluateVariational")
        for key,value in {"inputfileVariational":artifacts["native_variational"]["path"],
                          "inputfileParameters":artifacts["native_parameters"]["path"],
                          "outputfileOrbit":str(output / ("reconstructed.dat" if label=="ascii" else "roundtrip.dat")),
                          "inputfileEpochReference":reference,
                          "outputfileEpochDifferences":str(output / f"{label}_offsets.txt"),
                          "epochSamplingSeconds":str(sampling),
                          "outputfileBoundaryEpochDifferences":str(output / f"{label}_boundaries.txt")}.items():
            ET.SubElement(program,key).text=value
        for key in ("parametrizationAcceleration","stochasticPulse","ephemerides","integrationDegree","interpolationDegree"):
            node=model.find(key)
            if node is not None: program.append(deepcopy(node))
        config=_save_xml(root,output / f"{label}.xml")
        execution.append(run_native(frozen,config,output,label,timeout=1800))
    config=_file_conversion(output/"reconstructed.dat",output/"reconstructed.txt",output/"convert.xml")
    execution.append(run_native(frozen,config,output,"convert",timeout=120))
    _, before=_orbit(artifacts["estimated_orbit"]["path"])
    _, after=_orbit(output/"reconstructed.txt")
    position=float(np.max(np.linalg.norm(after[:,:3]-before[:,:3],axis=1)))
    velocity=float(np.max(np.linalg.norm(after[:,3:]-before[:,3:],axis=1)))
    ascii_error=float(np.max(np.abs(read_native_table(output/"ascii_offsets.txt",3)[:,1])))
    binary_offsets=read_native_table(output/"binary_offsets.txt",3)
    binary_error=float(np.max(np.abs(binary_offsets[:,1])))
    grid_error=float(np.max(np.abs(binary_offsets[:,2])))
    boundary_error=float(np.max(np.abs(read_native_table(output/"binary_boundaries.txt",2)[:,1])))
    report={"passed":binary_error==0 and grid_error<1e-9 and boundary_error<1e-9 and position<1e-6 and velocity<1e-9,
            "native_time_subtraction":True,"binary_maximum_epoch_error_seconds":binary_error,
            "ascii_maximum_epoch_error_seconds":ascii_error,
            "uniform_grid_maximum_error_seconds":grid_error,
            "model_boundaries_maximum_grid_error_seconds":boundary_error,
            "nominal_sampling_seconds":sampling,
            "maximum_state_reconstruction_position_m":position,
            "maximum_state_reconstruction_velocity_m_s":velocity,
            "thresholds":{"binary_epoch_error_seconds":0,"grid_and_boundary_error_seconds":1e-9,
                          "position_m":1e-6,"velocity_m_s":1e-9},
            "native_binary_sha256":file_hash(frozen),"source_fit_result_sha256":file_hash(fit_result),
            "execution":execution,"reconstructed_orbit":artifact_record("estimated_orbit_native",output/"reconstructed.dat"),
            "interpretation":"Same fitted state and parameters, exact native epochs; no fitting or truth access"}
    write_json(output/"epoch_precision.json",report)
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--fit-result",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--sampling",type=float,default=5.)
    args=parser.parse_args()
    report=run_gate(args.binary,args.fit_result,args.output,args.sampling)
    print(json.dumps({key:value for key,value in report.items() if key not in ("execution",)},indent=2))
    raise SystemExit(0 if report["passed"] else 1)
