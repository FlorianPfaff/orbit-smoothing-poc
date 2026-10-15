#!/usr/bin/env python3
"""Refine staged synthetic dynamics and actual native dual-frequency predictions.

The prepared engineering observations, force recipe and physical initial state
are fixed. Nonzero prescribed pulses or density knots exercise their boundaries;
no parameters, nuisance values, weights or ambiguity arcs are estimated here.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import time
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison import backend as native
from orbit_poc.comparison.groops_config import build_fit_configs
from orbit_poc.comparison.initialization import _field, _standalone
from orbit_poc.comparison.protocol import file_hash, write_json
from orbit_poc.numerics.backend import NativeModel,PhysicalState
from check_flight_refinement import resample
from validate_comparison_native import add_offgrid_interpolation
from numerics_refinement_helpers import predict_signals,compare_signals


def check(request,binary,directory):
    root=Path(directory).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError("Choose a fresh diagnostic output directory")
    root.mkdir(parents=True,exist_ok=True)
    job=json.loads(Path(request).read_text())
    if job["stage"]!="synthetic" or job.get("split")!="engineering":raise ValueError("Use a synthetic engineering request")
    job["backend"]["groops_executable"]=str(Path(binary).resolve())
    job["expected_native_binary_sha256"]=file_hash(binary)
    job["numerics_profile"]="qr_lm_staged_jacobian"
    model=NativeModel(job,root)
    initial=model.initial_state()
    prescribed=(.1*np.sin(np.arange(len(initial.force))*.27) if model.density else np.resize([40.,-30.,20.],len(initial.force)))
    state=PhysicalState(initial.initial.copy(),prescribed,initial.reference_orbit)
    native._private_data(model.prepared,root/"native")
    configured=build_fit_configs(model.prepared,root/"native",job["method"],job["parameters"])
    if model.density:
        density=root/"native/log_density.txt"
        epochs=[line.split()[0] for line in density.read_text().splitlines() if line.strip()]
        native._write_density_values(density,epochs,prescribed)
    receipt={"schema":"synthetic-staged-refinement-3.1","status":"running","method":job["method"],
        "profile":model.derivatives,"binary_sha256":file_hash(binary),"request_sha256":file_hash(request),
        "diagnostic_source_sha256":file_hash(__file__),
        "signal_diagnostic_source_sha256":file_hash(Path(__file__).with_name("numerics_refinement_helpers.py")),
        "case":job["case"],"state_grid_seconds":[5.,2.5],
        "fixed_force_units":"log density" if model.density else "micrometres per second", "fixed_force":prescribed.tolist(),
        "scope":"Engineering synthetic native numerical refinement at fixed initial state, prescribed nonzero disturbances and fixed nuisance values; no accuracy or uncertainty claim"}
    write_json(root/"result.json",receipt)
    try:
        coarse_dir=root/"coarse";coarse_dir.mkdir()
        coarse_config=deepcopy(configured)
        coarse=model._close(state,coarse_config,coarse_dir,True)
        fine_dir=root/"fine";fine_dir.mkdir()
        duration=job["case"]["duration_hours"]*3600
        source=ET.parse(configured["configs"]["variational"]).getroot()
        template=source.find(".//PreprocessingVariationalEquation")
        attitude=Path(template.find("inputfileStarCamera").text)
        sampling=ET.Element("groops")
        resample(sampling,coarse[0],fine_dir/"seed.dat",coarse[4][0],duration,2.5)
        resample(sampling,attitude,fine_dir/"attitude.dat",coarse[4][0],duration,2.5)
        model.execute(sampling,fine_dir,"resample")
        _field(template,"inputfileStarCamera",fine_dir/"attitude.dat")
        fine_config=deepcopy(configured)
        fine_config["configs"]["variational"]=str(native._save_xml(source,fine_dir/"variational.xml"))
        fine=model._close(PhysicalState(state.initial.copy(),state.force.copy(),fine_dir/"seed.dat"),fine_config,fine_dir,True)
        _,ia,ib=np.intersect1d(coarse[4],fine[4],return_indices=True)
        if len(ia)!=len(coarse[4]):raise ValueError("Refined grid omits coarse epochs")
        metrics={"aligned_position_maximum_m":float(np.max(np.linalg.norm(coarse[5][ia,:3]-fine[5][ib,:3],axis=1)))}
        offgrid=[];predictions=[]
        observation=next(item for item in job["estimation_inputs"] if item["role"]=="gnss_observations")
        for label,output,config in (("coarse",coarse,coarse_config),("fine",fine,fine_config)):
            folder=root/label
            xml=ET.parse(config["configs"]["variational"]).getroot()
            programs=model._evaluation(config,xml,output[1],folder/"fixed_orbit.dat",output[2])
            evaluate=_standalone(xml,programs,configured["date"])
            add_offgrid_interpolation(evaluate,folder,coarse[4][0],duration,5.)
            for element in evaluate.findall(".//OrbitPocEvaluateVariational"):
                for duplicate in element.findall("interpolationDegree")[1:]:element.remove(duplicate)
            model.execute(evaluate,folder,"offgrid")
            offgrid.append(native.read_native_table(folder/"offgrid_orbit.txt",10))
            predictions.append(predict_signals(model,configured["configs"]["estimate"],output[0],observation,folder/"predictions"))
        if not np.array_equal(offgrid[0][:,0],offgrid[1][:,0]):raise ValueError("Off-grid support changed under refinement")
        metrics["offgrid_position_maximum_m"]=float(np.max(np.linalg.norm(offgrid[0][:,1:4]-offgrid[1][:,1:4],axis=1)))
        signals=compare_signals(*predictions)
        receipt.update(status="complete",passed=signals["passed"] and all(value<3e-5 for value in metrics.values()),
            metrics=metrics,native_signals=signals,signal_prediction_mode="QR-enabled native Polynomial query evaluation; fixed nuisance values",offgrid_epochs=len(offgrid[0]),propagations=model.propagations,
            elapsed_seconds=time.monotonic()-model.start,initial_state_sha256=file_hash(coarse_dir/"physical_initial.txt"),
            observation_sha256=observation["sha256"],coarse_variational_config_sha256=file_hash(coarse_config["configs"]["variational"]),
            fine_variational_config_sha256=file_hash(fine_config["configs"]["variational"]))
        write_json(root/"result.json",receipt)
        return receipt
    except Exception as error:
        receipt.update(status="failed",error=str(error),propagations=model.propagations)
        write_json(root/"result.json",receipt)
        raise


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("request","binary","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args();result=check(args.request,args.binary,args.output)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["passed"] else 1)
