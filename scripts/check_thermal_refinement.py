#!/usr/bin/env python3
"""Refine only native thermal Euler steps at fixed geometry and pressure epochs."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import json
import shutil
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison import backend
from orbit_poc.comparison.protocol import file_hash,write_json
from validate_comparison_native import frozen_binary
from check_flight_refinement import run_checked


def check(reference_config,binary,output,steps):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    binary=frozen_binary(binary,output/'bin')
    reference_config=reference_config.resolve();old=reference_config.parent
    original=ET.parse(reference_config)
    outputs={Path(node.text).resolve() for node in original.iter()
             if node.tag.startswith('outputfile') and node.text}
    tasks=[]
    for step in steps:
        if not np.isfinite(step) or step<=0:raise ValueError('Thermal step must be finite and positive')
        folder=output/f'step-{step:g}';folder.mkdir(exist_ok=True)
        tree=ET.parse(reference_config)
        for node in tree.iter():
            if node.tag.startswith('inputfile') and node.text:
                source=Path(node.text)
                if source.is_file() and source.resolve().is_relative_to(old) and source.resolve() not in outputs:
                    target=folder/source.resolve().relative_to(old);target.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copy2(source,target)
            if node.text:node.text=node.text.replace(str(old),str(folder))
        radiation=tree.findall('.//radiationPressure')
        if not radiation:raise ValueError('No native thermal radiation model in reference configuration')
        for model in radiation:
            item=model.find('orbitPocThermalMaximumStep')
            if item is None:item=ET.SubElement(model,'orbitPocThermalMaximumStep')
            item.text=str(step)
        path=backend._save_xml(tree.getroot(),folder/'evaluate.xml')
        tasks.append((folder,path,step))
    with ThreadPoolExecutor(max_workers=2) as pool:
        execution=list(pool.map(lambda task:run_checked(binary,task[1],task[0],'thermal-refinement',timeout=3600),tasks))
    rows=[]
    for (a,_,step_a),(b,_,step_b) in zip(tasks[:-1],tasks[1:]):
        metrics={}
        for filename in ('fixed_orbit.txt','offgrid_orbit.txt'):
            x=backend.read_native_table(a/filename,10);y=backend.read_native_table(b/filename,10)
            if x.shape!=y.shape or not np.array_equal(x[:,0],y[:,0]):raise ValueError('Thermal-only refinement changed query epochs')
            difference=np.linalg.norm(x[:,1:4]-y[:,1:4],axis=1)
            metrics[filename]={'maximum_position_difference_m':float(difference.max()),
                               'rms_position_difference_m':float(np.sqrt(np.mean(difference**2)))}
        rows.append({'steps_seconds':[step_a,step_b],'metrics':metrics,
                     'below_30_micrometres':all(item['maximum_position_difference_m']<3e-5 for item in metrics.values())})
    result={'status':'diagnostic_complete','complete':True,'production_accuracy_acceptance':False,
            'scope':'Only thermal maximum step varied; identical fixed initial state, physical model, geometry grid, pressure endpoints, and atmospheric quadrature. This does not certify absolute integration error or replace state-grid refinement.',
            'reference_config':str(reference_config),'reference_config_sha256':file_hash(reference_config),
            'native_binary_sha256':file_hash(binary),'steps_seconds':steps,'comparisons':rows,'execution':execution}
    write_json(output/'thermal_refinement.json',result)
    print(json.dumps({key:value for key,value in result.items() if key!='execution'}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-config',type=Path,required=True)
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--steps',type=float,nargs='+',default=[.5,.25])
    args=parser.parse_args();check(args.reference_config,args.binary,args.output,args.steps)
