#!/usr/bin/env python3
"""Measure native atmospheric finite-difference roundoff before choosing FD steps.

The force is evaluated with GROOPS SimulateAccelerometer, using the actual
spacecraft and atmospheric model. Output-frame rotation is fixed for each epoch,
so derivative-column norms are unchanged. This is not an orbit-accuracy gate.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import re
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison import backend as native
from orbit_poc.comparison.initialization import _field, _standalone
from orbit_poc.comparison.protocol import file_hash, write_json
from validate_numerics_flight_derivatives import prepare


def run(prepared, binary, directory, failure_log=None):
    model, config, _, receipt = prepare(prepared,binary,directory,42300.,1800.)
    root=Path(directory).resolve()
    source=ET.parse(config["configs"]["variational"]).getroot()
    template=source.find(".//PreprocessingVariationalEquation")
    orbit=native.read_native_table(template.find("inputfileOrbit").text,10)[::10]
    attitude=native.read_native_table(template.find("inputfileStarCamera").text,5)[::10]
    extra=None
    if failure_log is not None:
        match=re.search(r"GPS MJD=([0-9.e+-]+), position=([0-9.e+,-]+), velocity=([0-9.e+,-]+)",Path(failure_log).read_text())
        if match is None:raise ValueError("Failure log has no native derivative state")
        state=np.array([float(match[1]),*map(float,match[2].split(',')),*map(float,match[3].split(',')),0.,0.,0.])
        canonical=native.read_native_table(template.find("inputfileStarCamera").text,5)
        nearest=np.sort(np.argsort(abs(canonical[:,0]-state[0]))[:8])
        seconds=(canonical[nearest,0]-state[0])*86400
        quaternion=np.array([np.polynomial.Polynomial.fit(seconds,canonical[nearest,j],7)(0) for j in range(1,5)])
        quaternion/=np.linalg.norm(quaternion)
        orbit=np.vstack((orbit,state));attitude=np.vstack((attitude,np.r_[state[0],quaternion]))
        extra={"failure_log_sha256":file_hash(failure_log),"state":state.tolist(),
               "fixed_attitude":quaternion.tolist(),"attitude_interpolation":"Normalized degree7 quaternion polynomial on eight nearest actual epochs"}
    rows,stars,metadata=[],[],[]
    steps_by_dimension=([1000.,500.,250.,100.,50.,25.,10.,5.,2.,1.,.5,.25,.125,.0625],
                        [1.,.5,.2,.1,.05,.02,.01,.005,.002,.001,.0005,.00025,.000125,.0000625])
    for epoch,(state,star) in enumerate(zip(orbit,attitude)):
        for column in range(6):
            for step in steps_by_dimension[column//3]:
                for sign in (-1,1):
                    row=state.copy();row[column+1]+=sign*step
                    rows.append(row);stars.append(star);metadata.append((epoch,column,step))
    for name,kind,values in (("perturbed-orbit",-6,rows),("fixed-attitude",-7,stars)):
        with (root/(name+".txt")).open("w") as stream:
            stream.write(f"groops instrument version=20200123\n{kind} 1\n{len(values)}\n")
            np.savetxt(stream,values,fmt="%.18e")
    node=ET.Element("SimulateAccelerometer")
    for field in ("inputfileSatelliteModel","earthRotation","ephemerides"):
        node.append(deepcopy(template.find(field)))
    for name,value in (("inputfileOrbit",root/"perturbed-orbit.txt"),("inputfileStarCamera",root/"fixed-attitude.txt"),
                       ("outputfileAccelerometer",root/"drag.txt")):_field(node,name,value)
    wrapper=ET.SubElement(ET.SubElement(node,"forces"),"miscAccelerations")
    wrapper.append(deepcopy(template.find("forces/miscAccelerations/atmosphericDrag")))
    model.execute(_standalone(source,[node],config["date"]),root,"evaluate")
    accelerations=native.read_native_table(root/"drag.txt",4)[:,1:]
    columns=[]
    for column in range(6):
        derivatives={}
        for i in range(0,len(metadata),2):
            _,c,step=metadata[i]
            if c==column:derivatives.setdefault(step,[]).append((accelerations[i+1]-accelerations[i])/(2*step))
        comparisons=[]
        steps=sorted(derivatives,reverse=True)
        for previous,step in zip(steps[:-1],steps[1:]):
            coarse,fine=np.array(derivatives[previous]),np.array(derivatives[step])
            discrepancy=np.linalg.norm(fine-coarse,axis=1)/np.maximum(np.linalg.norm(fine,axis=1),1e-20 if column<3 else 1e-17)
            worst=int(np.argmax(discrepancy))
            comparisons.append({"steps":[previous,step],"maximum_relative_disagreement":float(discrepancy[worst]),
                "worst_epoch_mjd":float(orbit[worst,0]),"derivative_norm":float(np.linalg.norm(fine[worst]))})
        columns.append({"initial_component":("x","y","z","vx","vy","vz")[column],"comparisons":comparisons})
    for unused in ("position_perturbations_m","velocity_perturbations_m_s","closure_controls","thermal_maximum_step_seconds"):
        receipt.pop(unused,None)
    receipt.update(schema="native-drag-step-diagnostic-3.1",status="complete",profile="native_atmospheric_component_step_study",diagnostic_source_sha256=file_hash(__file__),
        scope="37 Apr24 development epochs, optionally augmented by a recorded failed auxiliary state; native atmospheric component only; fixed attitude; no full trajectory propagation or inference",
        force_configuration="Native atmosphericDrag using actual JB2008, HWM and spacecraft geometry",
        sampled_epochs=len(orbit),additional_failed_epoch=extra,results=columns,
        perturbed_orbit_sha256=file_hash(root/"perturbed-orbit.txt"),fixed_attitude_sha256=file_hash(root/"fixed-attitude.txt"),
        acceleration_sha256=file_hash(root/"drag.txt"),actual_config_sha256=file_hash(root/"evaluate.xml"))
    write_json(root/"result.json",receipt)
    return receipt


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("prepared","binary","output"):parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--failure-log",type=Path)
    args=parser.parse_args()
    print(json.dumps(run(args.prepared,args.binary,args.output,args.failure_log),indent=2))
