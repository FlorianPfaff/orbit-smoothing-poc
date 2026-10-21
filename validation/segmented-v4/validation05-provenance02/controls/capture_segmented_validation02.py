#!/usr/bin/env python3
"""Lossless compact transfer of one terminal validation; never evaluates gates."""
from pathlib import Path
import argparse,gzip,hashlib,json,os,tarfile
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
MAX_FILE=128*1024*1024
MAX_TOTAL=512*1024*1024
TOP=('execution.json','segmented-v4.json','launch-plan.json','launch-pins.json','source-freeze.json','native-input-equivalence.json','native-rebuild-provenance.json','admission.json','staging.json','validation-launch.json','validation-controller.json','validation-cli.log','validation-driver.log')

def require(ok,message):
    if not ok:raise ValueError(message)
def sha(data):return hashlib.sha256(data).hexdigest()
def file_sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1048576),b''):h.update(block)
    return h.hexdigest()
def artifact(path):
    p=Path(path);return {'path':str(p),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
def checked(pin):
    p=Path(pin['path']);require(p.is_absolute() and not p.is_symlink() and p.is_file(),'Artifact is not a regular absolute file')
    b=p.read_bytes();require(sha(b)==pin['sha256'] and ('bytes' not in pin or len(b)==pin['bytes']),'Changed artifact: '+str(p));return p,b

def inspect(root,execution_sha256,launch_sha256):
    root=Path(root).resolve();c=root/'control'
    ep,eb=checked({'path':str(c/'execution.json'),'sha256':execution_sha256});e=json.loads(eb)
    lp,lb=checked({'path':str(c/'validation-launch.json'),'sha256':launch_sha256});launch=json.loads(lb)
    require(e['paths']['root']==str(root) and e['paths']['control']==str(c),'Wrong execution root')
    require(launch.get('launch_committed') is True and launch['execution_sha256']==execution_sha256,'Launch attribution changed')
    controller=json.loads((c/'validation-controller.json').read_bytes())
    require(controller['status'] in ('passed','failed') and controller.get('final_cleanup',{}).get('verified') is True,'Controller not terminal and clean')
    planpath,pb=checked(controller['plan']);plan=json.loads(pb)
    require(planpath==c/'launch-plan.json' and plan['execution']=={'path':str(ep),'sha256':execution_sha256},'Controller plan attribution changed')
    argv=launch.get('argv');require(isinstance(argv,list) and argv[-4:]==['--plan',str(planpath),'--sha256',sha(pb)],'Launch command plan attribution changed')
    require(launch.get('observed_argv',argv)==argv,'Observed launch command differs')
    checked(plan['config']);checked(plan['source_freeze']);checked(plan['native_equivalence'])
    require(controller['source']==json.loads(Path(plan['source_freeze']['path']).read_bytes())['source'],'Source attribution changed')
    admitted=controller['admission']['driver_identity'];identity=launch['driver_process']
    require(all(admitted[k]==identity[k] for k in ('pid','start_ticks')) and controller['admission']['boot_id']==identity['boot_id'],'Launch/controller process mismatch')
    run=Path(e['paths']['run']);require(run==root/'run','Unexpected run root')
    latest=json.loads((run/'validation/latest.json').read_bytes());pp,raw=checked(latest['pipeline'])
    require(pp.resolve().parent.parent==run/'validation' and pp.name=='pipeline.json','Pipeline outside one validation attempt')
    v=json.loads(raw);require(v['schema']=='orbit-poc-segmented-validation-run-v1' and v['status'] in ('passed','failed'),'Nonterminal CLI pipeline')
    require(tuple(s['name'] for s in v['steps'])==STAGES,'Changed planned gate inventory')
    require(controller.get('cli_validation',{}).get('pipeline')==latest['pipeline'],'Controller/CLI pipeline attribution mismatch')
    for s in v['steps']:
        require(s['status'] in ('passed','failed','not_run','interrupted_or_failed'),'Active gate')
        require(Path(s['directory'])==pp.parent/s['name'],'Gate directory attribution mismatch')
        if s['status']=='passed':require('execution' in s,'Passed gate lacks execution')
        if 'execution' in s:
            xp,xb=checked(s['execution']);require(xp==pp.parent/s['name']/'execution.json','Foreign gate execution')
            x=json.loads(xb);require(x.get('harness_execution',{}).get('owned_process_group_cleaned') is True,'Gate cleanup unverified')
            if s['status']=='passed':require(x.get('status')=='complete' and x.get('returncode')==0,'Passed gate execution failed')
    if v['status']=='passed':require(all(s['status']=='passed' for s in v['steps']),'Inconsistent passed CLI status')
    if controller['status']=='passed':require(v['status']=='passed' and controller.get('returncode')==0,'Inconsistent passed controller status')
    return {'root':root,'run':run,'pipeline_path':pp,'controller':controller,'pipeline':v,'execution':e}

def selected(path,attempt):
    r=path.relative_to(attempt);parts=r.parts
    if any(x in {'pytest-temp','__pycache__'} for x in parts):return False
    # Retain raw control/result/QR history data, but never numerical row spools.
    return path.suffix in {'.json','.xml','.log'} or path.name in {'stdout','stderr'}

def capture(root,execution_sha256,launch_sha256,output):
    state=inspect(root,execution_sha256,launch_sha256);root=state['root'];output=Path(output)
    require(not output.exists() and not output.is_symlink(),'Output already exists')
    require(output.is_absolute() and root/'run' not in output.parents and root/'control' not in output.parents,'Output overlaps evidence')
    candidates=[root/'control'/n for n in TOP if (root/'control'/n).is_file()]
    candidates += [x for parent in (root/'run',root/'run/validation') for x in parent.iterdir() if x.is_file() and x.suffix=='.json']
    attempt=state['pipeline_path'].parent
    candidates += [x for x in attempt.rglob('*') if x.is_file() and selected(x,attempt)]
    candidates=sorted(set(candidates));records=[];external=[];total=0
    for p in candidates:
        require(not p.is_symlink(),'Refuse symlink evidence: '+str(p))
        size=p.stat().st_size
        if size>MAX_FILE:
            external.append({'path':str(p),'sha256':file_sha(p),'bytes':size,'reason':'over individual compact-transfer bound; raw remote evidence retained'});continue
        total+=size;require(total<=MAX_TOTAL,'Compact raw evidence exceeds transfer bound')
        records.append((p,p.read_bytes()))
    output.mkdir(parents=True)
    inventory=[]
    for p,raw in records:
        rel=str(p.relative_to(root));compress=len(raw)>65536;stored=gzip.compress(raw,mtime=0) if compress else raw
        destination=output/(rel+'.gz' if compress else rel);destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(stored)
        inventory.append({'source':{'path':str(p),'sha256':sha(raw),'bytes':len(raw)},'stored':{'path':str(destination.relative_to(output)),'sha256':sha(stored),'bytes':len(stored)},'encoding':'gzip' if compress else 'identity'})
    require(inspect(root,execution_sha256,launch_sha256,)==state,'Evidence changed during transfer')
    for p,raw in records:require(p.read_bytes()==raw,'Evidence changed during transfer: '+str(p))
    for p in external:require(Path(p['path']).stat().st_size==p['bytes'] and file_sha(p['path'])==p['sha256'],'External evidence changed during transfer')
    bench=root/'run/attempts'; benchmark_outputs={'manifest_present':(root/'run/manifest.json').exists() or (root/'run/manifest.json').is_symlink(),'attempts_directory_present':bench.exists() or bench.is_symlink(),'attempt_entries':sorted(x.name for x in bench.iterdir()) if bench.is_dir() and not bench.is_symlink() else [],'scope':'Terminal filesystem metadata only; no benchmark execution is performed by this capture'}
    manifest={'benchmark_outputs':benchmark_outputs,'schema':'orbit-poc-v4-terminal-validation-capture-v1','scope':'Lossless compact raw evidence transfer; no gate recomputation or scientific status promotion','execution':artifact(root/'control/execution.json'),'launch':artifact(root/'control/validation-launch.json'),'controller':artifact(root/'control/validation-controller.json'),'pipeline':artifact(state['pipeline_path']),'controller_status':state['controller']['status'],'pipeline_status':state['pipeline']['status'],'planned_gates':[{'name':s['name'],'status':s['status']} for s in state['pipeline']['steps']],'final_owned_cleanup_verified':True,'records':inventory,'external_not_copied':external,'raw_bytes':total,'helper':artifact(__file__)}
    (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--execution-sha256',required=True);p.add_argument('--launch-sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    m=capture(a.root,a.execution_sha256,a.launch_sha256,a.output);print(json.dumps({'manifest':artifact(a.output/'manifest.json'),'files':len(m['records']),'raw_bytes':m['raw_bytes'],'external_not_copied':len(m['external_not_copied'])}))
if __name__=='__main__':main()
