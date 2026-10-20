#!/usr/bin/env python3
"""Check inherited controls before exec of one frozen native profile.

The receipt records the actual launch-process environment. execve receives that
same environment; successful native completion remains a separate requirement.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import re
import xml.etree.ElementTree as ET

MODE='preinit_scaled_qr_v1'
PREFIX='ORBIT_POC_NUMERICS_'
THREADS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS')
DATUM=re.compile(r'qr\.datum\.([1-9][0-9]*)\.(codeBias|codeBiasZeroMean|tecBias|ambiguitySelection)\.tsv')

def require(value,message):
    if not value:raise ValueError(message)

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def pin(path):
    path=Path(path).absolute();return {'path':str(path),'sha256':digest(path),'bytes':path.stat().st_size}
def verify(record):
    require(pin(record['path'])==record,'Launch pin changed: '+record['path'])
def read(path):return json.loads(Path(path).read_text())
def save(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n');stream.flush();os.fsync(stream.fileno())

def scientific_controls(config,root):
    root=Path(root).absolute();tree=ET.parse(config).getroot();nodes=tree.findall('.//orbitPocNumerics')
    require(len(nodes)==1,'Exactly one native numerics profile required')
    require(nodes[0].findtext('outputfilePrefix')==str(root/'qr'),'XML QR prefix differs from point')
    controls={PREFIX+'QR_PREFIX':str(root/'qr'),PREFIX+'SOLVER':'scaled_qr_v1',
              PREFIX+'MODE':'profile_step',PREFIX+'LAMBDA':'0'}
    pulses=nodes[0].findall('inputfilePulseReference');require(len(pulses)<=1,'Duplicate pulse reference')
    if pulses:
        pulse=(pulses[0].text or '').strip()
        require(pulse and Path(pulse).is_absolute() and Path(pulse).is_file(),'Invalid XML pulse reference')
        controls[PREFIX+'PULSE_REFERENCE']=pulse
    return controls

def validate_environment(environment,config,root):
    expected=scientific_controls(config,root)
    for key in (*expected,PREFIX+'PULSE_REFERENCE'):
        require(environment.get(key)==expected.get(key),'Prelaunch scientific control differs: '+key)
    require(all(environment.get(key)=='1' for key in THREADS),'Prelaunch numerical thread differs')
    require(environment.get(PREFIX+'KEEP_INTERMEDIATE_FACTORS')=='1' and
            environment.get(PREFIX+'COMPRESS_ROW_PROVENANCE')=='0','Diagnostic storage controls differ')
    return expected

def launch_command(python,guard,binding):
    return ['/usr/bin/taskset','-c','0',python,'-s','-B',guard,
            '--binding',binding['path'],'--binding-sha256',binding['sha256']]

def datum_evidence(root):
    """Validate actual native datum records; these confer no convergence authority."""
    root=Path(root);records=[];sequences=[]
    for path in sorted(root.glob('qr.datum.*')):
        match=DATUM.fullmatch(path.name)
        require(match is not None and path.is_file() and not path.is_symlink(),'Invalid native datum artifact')
        sequences.append(int(match[1]));rows=[]
        for line in path.read_text().splitlines():
            values=[float(value) for value in line.split('\t')] if line else []
            require(all(math.isfinite(v) for v in values),'Nonfinite native datum evidence');rows.append(values)
        require(len({len(row) for row in rows})<=1,'Ragged native datum evidence')
        records.append({**pin(path),'kind':match[2],'rows':len(rows),'columns':len(rows[0]) if rows else None})
    require(records and sorted(sequences)==list(range(1,len(sequences)+1)),'Missing/stale native datum evidence')
    require(any(r['rows'] and r['columns'] for r in records),'No substantive native datum evidence')
    return records

def checked_launch(binding_record,receipt, *, expected_environment=None):
    verify(binding_record);binding=read(binding_record['path'])
    require(binding['schema']=='orbit-poc-nuisance-profile-launch-binding-v1' and binding['mode']==MODE,'Unknown prelaunch binding')
    for key in ('freeze','native','config','guard'):verify(binding[key])
    root=Path(binding['root']);require(Path(binding_record['path'])==root/'launch-binding.json','Launch binding root differs')
    require(binding['config']['path']==str(root/'config.xml') and binding['cpu']==0,'Launch configuration or CPU differs')
    validate_environment(binding['environment'],binding['config']['path'],root)
    if expected_environment is not None:require(binding['environment']==expected_environment,'Launch binding controls differ')
    require(receipt['schema']=='orbit-poc-nuisance-profile-native-launch-v1' and receipt['mode']==MODE
            and receipt['binding']==binding_record,'Native launch receipt binding differs')
    require(receipt['environment']==binding['environment'] and receipt['cpu_affinity']==[0], 'Actual native launch environment/CPU differs')
    require(receipt['native_command']==[binding['native']['path'],binding['config']['path']], 'Native exec command differs')
    require(type(receipt['pid']) is int and receipt['pid']>0,'Invalid native launch process identity')
    return binding

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--binding',required=True,type=Path)
    parser.add_argument('--binding-sha256',required=True);args=parser.parse_args()
    record=pin(args.binding);require(record['sha256']==args.binding_sha256,'Launch binding identity differs')
    binding=read(args.binding)
    actual={key:os.environ.get(key) for key in binding['environment']}
    require({k:v for k,v in os.environ.items() if k.startswith(('ORBIT_POC_','LD_'))}==
            {k:v for k,v in binding['environment'].items() if k.startswith(('ORBIT_POC_','LD_'))},'Unfrozen actual launch override')
    receipt={'schema':'orbit-poc-nuisance-profile-native-launch-v1','mode':MODE,'binding':record,
             'environment':actual,'cpu_affinity':sorted(os.sched_getaffinity(0)),
             'native_command':[binding['native']['path'],binding['config']['path']],'pid':os.getpid()}
    checked_launch(record,receipt)
    require(pin(__file__)==binding['guard'],'Wrong native launch guard')
    save(Path(binding['root'])/'native-launch.json',receipt)
    os.execve(receipt['native_command'][0],receipt['native_command'],dict(os.environ))

if __name__=='__main__':main()
