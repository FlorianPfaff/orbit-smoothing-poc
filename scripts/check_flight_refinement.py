#!/usr/bin/env python3
"""Refine full flight dynamics at fixed fitted state/forces; never fit SLR.

The same smooth native reference supplies linearization geometry on both grids.
This checks numerical convergence of the implemented model, not orbit accuracy.
"""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import argparse
from decimal import Decimal, localcontext
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison import backend, groops_config, slr
from orbit_poc.comparison.protocol import artifact_record, file_hash, read_json, write_json
from validate_comparison_native import frozen_binary, save_matrix, resolve_daily_variables, add_offgrid_interpolation


def program(tree, name):
    return ET.SubElement(ET.SubElement(tree,"program"),name)


def field(parent,name,value):
    ET.SubElement(parent,name).text=str(value)


def run_checked(binary, config, directory, label, **kwargs):
    """Resume only successful commands with identical executable and XML."""
    record=Path(directory)/(label+".execution.json")
    if record.exists():
        old=read_json(record)
        if old.get("returncode")==0 and old.get("config_sha256")==file_hash(config) and old.get("native_binary_sha256")==file_hash(binary):
            outputs=[Path(node.text) for node in ET.parse(config).iter()
                     if node.tag.startswith("outputfile") and node.text]
            if all(path.is_file() for path in outputs):
                return {**old,"reused_completed_execution":True}
    return backend.run_native(binary,config,directory,label,**kwargs)


def resample(tree, source, target, mjd, stop, step, degree=7):
    p=program(tree,"InstrumentResample")
    field(p,"inputfileInstrument",source);field(p,"outputfileInstrument",target)
    method=ET.SubElement(ET.SubElement(p,"method"),"polynomial")
    for name,value in (("polynomialDegree",degree),("maxDataPointRange",-(degree+1.1)),("maxExtrapolationDistance",-1.1)):
        field(method,name,value)
    series=ET.SubElement(ET.SubElement(p,"timeSeries"),"uniformSampling")
    offset=round((mjd-int(mjd))*86400.)
    for name,value in (("timeStart",int(mjd)),("offsetSeconds",offset),("timeEnd",f"{int(mjd)}+({stop}+{step}*0.25)/86400"),("sampling",f"{step}/86400")):
        field(series,name,value)


def check(args):
    root=args.output.resolve();root.mkdir(parents=True,exist_ok=True)
    binary=frozen_binary(args.binary,root/"bin")
    prediction_binary=frozen_binary(args.prediction_binary,root/"prediction-bin") if getattr(args,"prediction_binary",None) else binary
    evaluation=read_json(args.evaluation_request)
    date=evaluation["case"]["date"]
    records=[]
    for result_file in (args.pulse_result,args.density_result):
        result=read_json(result_file); method=result["method"]
        artifacts={item["role"]:item["path"] for item in result["artifacts"]}
        for item in result["artifacts"]:
            if file_hash(item["path"])!=item["sha256"]:raise ValueError("Changed pilot artifact")
        folder=root/method;folder.mkdir(exist_ok=True)
        with np.load(artifacts["state_estimate"]) as fit:
            initial=fit["states"][0].copy();mjd=float(fit["mjd"][0]);stop=round(float(fit["times"][-1]))
        model=ET.parse(artifacts["native_fit_configuration"]).getroot().find(".//leoDynamicOrbits")
        fitted_tree=ET.parse(artifacts["native_variational_configuration"]).getroot()
        density=method=="groops_log_drag_ou"
        fixed_density=None
        if density:
            values=backend.read_native_table(artifacts["posterior_log_density"],2)[:,1]
            fixed_density=folder/"fixed_density.txt"
            with localcontext() as context:
                context.prec=35
                offset=round((mjd-int(mjd))*86400.)
                epochs=[f"{Decimal(int(mjd))+Decimal(offset+i*60)/Decimal(86400):.18f}" for i in range(len(values))]
            backend._write_density_values(fixed_density,epochs,values)
        # Retrieve the force-only native reference already used by the pilot.
        # Six-state-only evaluation excludes fitted impulses from the reference
        # interpolator; impulses are applied explicitly in each numerical grid.
        tree=ET.Element("groops");p=program(tree,"OrbitPocEvaluateVariational")
        field(p,"inputfileVariational",artifacts["native_variational"])
        field(p,"outputfileOrbit",folder/"smooth_reference.dat")
        p.append(deepcopy(model.find("ephemerides")))
        path=backend._save_xml(tree,folder/"reference.xml")
        reference_execution=run_checked(binary,path,folder,"reference",timeout=1800)
        tasks=[]
        for label,step,force_step in (("coarse",5.,1.),("fine",2.5,1.),("force_fine",2.5,.5)):
            sub=folder/label;sub.mkdir(exist_ok=True)
            save_matrix(sub/"initial.txt",initial)
            values=np.zeros(6) if density else backend.read_native_table(artifacts["native_parameters"],1).reshape(-1)
            save_matrix(sub/"parameters.txt",values)
            tree=ET.Element("groops")
            global_variables=fitted_tree.find("global")
            if global_variables is not None:tree.append(deepcopy(global_variables))
            resample(tree,folder/"smooth_reference.dat",sub/"reference.dat",mjd,stop,step)
            resample(tree,artifacts["native_attitude"],sub/"attitude.dat",mjd,stop,step)
            p=deepcopy(fitted_tree.find(".//PreprocessingVariationalEquation"))
            p.find("inputfileOrbit").text=str(sub/"reference.dat")
            p.find("inputfileStarCamera").text=str(sub/"attitude.dat")
            p.find("outputfileVariational").text=str(sub/"variational.dat")
            if density:
                for node in p.findall(".//inputfileLogDensity"):node.text=str(fixed_density)
            # Older retained pilot configurations predate the event-aware native
            # integrator. Duplicate exactly the fitted atmospheric component.
            old=p.find("orbitPocAtmosphericForce")
            if old is not None:p.remove(old)
            component=next((wrapper[0] for wrapper in p.findall("forces/miscAccelerations")
                            if len(wrapper) and wrapper[0].tag in ("atmosphericDrag","logDensity")),None)
            if component is None:raise ValueError("Flight refinement lacks its atmospheric force")
            ET.SubElement(p,"orbitPocAtmosphericForce").append(deepcopy(component))
            old=p.find("orbitPocAtmosphericHasDensityKnots")
            if old is not None:p.remove(old)
            field(p,"orbitPocAtmosphericHasDensityKnots",1 if density else 0)
            old=p.find("orbitPocAtmosphericQuadratureStep")
            if old is not None:p.remove(old)
            field(p,"orbitPocAtmosphericQuadratureStep",force_step)
            if getattr(args,"thermal_maximum_step",None) is not None:
                for radiation in p.findall(".//radiationPressure"):
                    item=radiation.find("orbitPocThermalMaximumStep")
                    if item is None:item=ET.SubElement(radiation,"orbitPocThermalMaximumStep")
                    item.text=str(args.thermal_maximum_step)
            resolve_daily_variables(p,date,mjd,stop+5)
            ET.SubElement(tree,"program").append(p)
            p=program(tree,"OrbitPocEvaluateVariational")
            for name,value in (("inputfileVariational",sub/"variational.dat"),("outputfileOrbit",sub/"fixed_orbit.dat"),
                               ("inputfileParameters",sub/"parameters.txt"),("inputfileInitialState",sub/"initial.txt"),
                               ("outputfileParameters",sub/"reanchored_parameters.txt")):
                field(p,name,value)
            for name in ("stochasticPulse","ephemerides","integrationDegree"):
                node=model.find(name)
                if node is not None:
                    node=deepcopy(node);resolve_daily_variables(node,date,mjd,stop+5);p.append(node)
            # Density is a fixed prescribed force here; no unnecessary latent
            # sensitivity columns are allocated for a numerical integration test.
            add_offgrid_interpolation(tree,sub,mjd,stop,5.)
            convert=program(tree,"FileConvert")
            field(convert,"inputfile",sub/"fixed_orbit.dat");field(convert,"outputfile",sub/"fixed_orbit.txt")
            path=backend._save_xml(tree,sub/"evaluate.xml")
            tasks.append((sub,path,step))
        with ThreadPoolExecutor(max_workers=2) as pool:
            execution=list(pool.map(lambda task:run_checked(binary,task[1],task[0],"refinement",timeout=3600),tasks))
        if getattr(args,"propagation_only",False):
            propagated=[]
            for sub,_,step in tasks:
                orbit=backend.read_native_table(sub/"fixed_orbit.txt",10)
                seconds=np.rint((orbit[:,0]-mjd)*86400*2)/2
                propagated.append({"orbit":orbit[np.isclose(seconds%30,0,atol=1e-5)],
                                   "offgrid":backend.read_native_table(sub/"offgrid_orbit.txt",10)})
            comparisons=[]
            for label,a,b in (("state_grid_5_to_2p5_seconds",propagated[0],propagated[1]),
                              ("atmosphere_quadrature_1_to_0p5_seconds",propagated[1],propagated[2])):
                item={"comparison":label}
                for key in ("orbit","offgrid"):
                    if a[key].shape!=b[key].shape or not np.array_equal(a[key][:,0],b[key][:,0]):
                        raise ValueError("Propagation epoch mismatch")
                    item[key+"_maximum_position_difference_m"]=float(np.max(np.linalg.norm(a[key][:,1:4]-b[key][:,1:4],axis=1)))
                comparisons.append(item)
            record={"method":method,"comparisons":comparisons,"execution":[reference_execution,*execution]}
            records.append(record)
            write_json(root/"propagation_refinement.json",{"status":"predictions_pending","complete":False,
                "records":records,"native_binary_sha256":file_hash(binary)})
            print(json.dumps({key:value for key,value in record.items() if key!="execution"}),flush=True)
            continue
        raw_request=read_json(Path(result_file).parent/"request.json")
        observation=next(item for item in raw_request["estimation_inputs"] if item["role"]=="gnss_observations")
        # Reusing development observations is solely a numerical difference
        # check. These are not represented as held-out predictive validation.
        code_input={**observation,"role":"heldout_gnss_code"}
        slr_input=next(item for item in evaluation["evaluation_inputs"] if item["role"]=="slr_validation")
        # Older retained development fits predate the explicit canonical
        # attitude provenance field. Add only that known immutable input to a
        # private numerical-check configuration, without changing fitted forces.
        prediction_fit=ET.parse(artifacts["native_fit_configuration"])
        global_fields=prediction_fit.getroot().find("global")
        canonical=global_fields.find("filename[@label='orbitPocCanonicalAttitude']")
        if canonical is None:canonical=ET.SubElement(global_fields,"filename",label="orbitPocCanonicalAttitude")
        canonical.text=artifacts["native_attitude"]
        prediction_fit_path=backend._save_xml(prediction_fit.getroot(),folder/"prediction_fit.xml")
        outputs=[]
        for sub,_,step in tasks:
            code=groops_config.build_prediction_config(prediction_fit_path,sub/"fixed_orbit.dat",[code_input],sub/"code")
            for name,path in code["configs"].items():
                execution.append(run_checked(prediction_binary,path,sub/"code",name,timeout=1800))
            laser=slr.build_slr_configs(date,slr_input["path"],sub/"fixed_orbit.dat",sub/"attitude.dat",
                evaluation["backend"]["auxiliary_dir"],sub/"slr",fit_config_path=artifacts["native_fit_configuration"],
                parameter_covariance_path=artifacts["native_parameter_covariance"],variational_path=artifacts["native_variational"])
            tree=ET.parse(laser["configs"]["predict_slr"])
            p=tree.getroot().find(".//OrbitPocPredictSlr")
            for name in ("outputfilePredictiveCovariance","inputfileParameterCovariance","inputfileVariational"):
                node=p.find(name)
                if node is not None:p.remove(node)
            if density:
                for node in p.findall(".//inputfileLogDensity"):node.text=str(fixed_density)
            backend._save_xml(tree.getroot(),laser["configs"]["predict_slr"])
            for name,path in laser["configs"].items():
                execution.append(run_checked(prediction_binary,path,sub/"slr",name,timeout=1800))
            orbit=backend.read_native_table(sub/"fixed_orbit.txt",10)
            seconds=np.rint((orbit[:,0]-mjd)*86400*2)/2
            outputs.append({"orbit":orbit[np.isclose(seconds%30,0,atol=1e-5)],
                "offgrid":backend.read_native_table(sub/"offgrid_orbit.txt",10),
                "code":backend.read_native_table(code["predictions"],8),"slr":backend.read_native_table(laser["predictions"],14)})
        comparison_records=[]
        for label,a,b in (("state_grid_5_to_2p5_seconds",outputs[0],outputs[1]),
                          ("atmosphere_quadrature_1_to_0p5_seconds",outputs[1],outputs[2])):
            for key,columns in (("orbit",[0]),("offgrid",[0]),("code",[0,1]),("slr",[0,1,2])):
                if a[key].shape!=b[key].shape or not np.array_equal(a[key][:,columns],b[key][:,columns]):
                    raise ValueError(f"Refinement {key} prediction rows do not correspond exactly")
            aligned=float(np.max(np.linalg.norm(a["orbit"][:,1:4]-b["orbit"][:,1:4],axis=1)))
            offgrid=float(np.max(np.linalg.norm(a["offgrid"][:,1:4]-b["offgrid"][:,1:4],axis=1)))
            code_difference=float(np.max(np.abs(a["code"][:,2]-b["code"][:,2])))
            slr_difference=np.abs(a["slr"][:,3]-b["slr"][:,3])
            slr_sigma=np.minimum(a["slr"][:,4],b["slr"][:,4])
            item={"method":method,"passed":max(aligned,offgrid)<3e-5 and code_difference<.003 and bool(np.all(slr_difference<.01*slr_sigma)),
                "duration_hours":24,"fixed_fitted_initial_state_and_forces":True,"no_refitting":True,
                "aligned_maximum_position_difference_m":aligned,"offgrid_maximum_position_difference_m":offgrid,
                "gnss_native_if_code_maximum_difference_m":code_difference,"gnss_code_threshold_m":.003,
                "carrier_geometric_bound_m":max(aligned,offgrid),"carrier_geometry_threshold_m":3e-5,
                "carrier_limitation":"Carrier is assessed by geometric range bound; this predictor exports native IF code, not a phase residual",
                "slr_native_maximum_difference_m":float(slr_difference.max()),
                "slr_minimum_per_observation_threshold_m":float((.01*slr_sigma).min()),
                "slr_maximum_fraction_of_measurement_sigma":float((slr_difference/slr_sigma).max()),
                "slr_points":len(slr_difference),"gnss_satellite_epochs":len(a['code']),
                "execution":[]}
            item["comparison"]=label
            item.pop("execution")
            comparison_records.append(item)
        record=dict(comparison_records[0])
        record.pop("comparison")
        record["passed"]=all(item["passed"] for item in comparison_records)
        for key in ("aligned_maximum_position_difference_m","offgrid_maximum_position_difference_m",
                    "gnss_native_if_code_maximum_difference_m","carrier_geometric_bound_m",
                    "slr_native_maximum_difference_m","slr_maximum_fraction_of_measurement_sigma"):
            record[key]=max(item[key] for item in comparison_records)
        record.update(comparisons=comparison_records,execution=[reference_execution,*execution],
            atmosphere_quadrature_steps_seconds=[1.,.5],canonical_attitude_support_seconds=5.,
            state_grid_steps_seconds=[5.,2.5],thermal_maximum_step_seconds=getattr(args,"thermal_maximum_step",None) or 1.,
            slr_attitude_policy="Same canonical 5 s curve resampled to each state grid for upstream synchronized-input requirement; subsequent interpolation is part of numerical refinement")
        records.append(record)
        write_json(root/"flight_refinement.json",{"passed":all(x['passed'] for x in records),"complete":len(records)==2,
            "records":records,"native_binary_sha256":file_hash(binary),
            "prediction_binary_sha256":file_hash(prediction_binary),
            "scope":"Apr24 development numerical convergence at fixed fitted parameters; no orbit accuracy or calibrated-uncertainty claim"})
        print(json.dumps({k:v for k,v in record.items() if k!='execution'}),flush=True)
    return True if getattr(args,"propagation_only",False) else all(record["passed"] for record in records)


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("binary","pulse-result","density-result","evaluation-request","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--thermal-maximum-step",type=float,help="Shared explicit thermal maximum step for every physical propagation")
    parser.add_argument("--prediction-binary",type=Path,help="Optional separately hashed native predictor executable; propagation executable remains frozen")
    parser.add_argument("--propagation-only",action="store_true",help="Run genuine numerical propagations and save provisional differences; omit prediction claims")
    raise SystemExit(0 if check(parser.parse_args()) else 1)
