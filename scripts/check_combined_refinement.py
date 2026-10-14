#!/usr/bin/env python3
"""Compare simultaneously tightened state/thermal numerics with audited inputs."""
from pathlib import Path
import argparse
import json
import xml.etree.ElementTree as ET
import numpy as np
from orbit_poc.comparison.backend import read_native_table
from orbit_poc.comparison.protocol import file_hash,write_json


def signature(folder):
    tree=ET.parse(folder/'evaluate.xml')
    force=tree.find('.//PreprocessingVariationalEquation/forces')
    def node_key(node):
        text=(node.text or '').strip()
        if node.tag=='inputfileLogDensity':text='sha256:'+file_hash(text)
        return [node.tag,sorted(node.attrib.items()),text,[node_key(child) for child in node if child.tag!='orbitPocThermalMaximumStep']]
    inputs={}
    for label,path in (('initial_state',tree.find('.//inputfileInitialState').text),
                       ('fitted_parameters',tree.find('.//inputfileParameters').text)):
        inputs[label]=file_hash(path)
    for label,node in zip(('smooth_reference','canonical_attitude'),tree.findall('.//InstrumentResample')[:2]):
        inputs[label]=file_hash(node.find('inputfileInstrument').text)
    inputs['physical_force_model']=node_key(force)
    inputs['atmospheric_step']=tree.find('.//orbitPocAtmosphericQuadratureStep').text
    return inputs


def check(coarse,fine,output):
    coarse,fine=coarse.resolve(),fine.resolve()
    source_a,source_b=signature(coarse),signature(fine)
    if source_a!=source_b:raise ValueError('Combined refinement physical inputs differ beyond the specified numerical controls')
    metrics={}
    for filename in ('fixed_orbit.txt','offgrid_orbit.txt'):
        a=read_native_table(coarse/filename,10);b=read_native_table(fine/filename,10)
        if filename.startswith('offgrid'):
            if a.shape!=b.shape or not np.array_equal(a[:,0],b[:,0]):raise ValueError('Off-grid query sets differ')
        else:
            times,ia,ib=np.intersect1d(a[:,0],b[:,0],return_indices=True)
            if len(times)!=len(a):raise ValueError('The refined grid omits a coarse epoch')
            a,b=a[ia],b[ib]
        delta=np.linalg.norm(a[:,1:4]-b[:,1:4],axis=1)
        metrics[filename]={'epochs':len(a),'maximum_position_difference_m':float(delta.max()),
                           'rms_position_difference_m':float(np.sqrt(np.mean(delta**2)))}
    result={'passed':all(item['maximum_position_difference_m']<3e-5 for item in metrics.values()),
            'scope':'Combined state-grid and thermal-step geometric refinement; complements separate atmosphere and thermal checks and native prediction comparisons',
            'threshold_m':3e-5,'coarse':str(coarse),'fine':str(fine),'matching_physical_input_signature':source_a,
            'coarse_config_sha256':file_hash(coarse/'evaluate.xml'),'fine_config_sha256':file_hash(fine/'evaluate.xml'),
            'metrics':metrics}
    write_json(output,result);print(json.dumps({k:v for k,v in result.items() if k!='matching_physical_input_signature'}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('coarse','fine','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();raise SystemExit(0 if check(args.coarse,args.fine,args.output)['passed'] else 1)
