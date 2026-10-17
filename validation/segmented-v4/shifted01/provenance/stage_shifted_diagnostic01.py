#!/usr/bin/env python3
"""Stage a separate captured-row diagnostic; never run a solver or propagation."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil
KEYS={'schema','execution','source_freeze','controller','pipeline','config','helpers','output_root'}
HELPERS={'runner':'run_shifted_diagnostic03.py','driver':'owned_driver09.py','wrapper':'with_correctness_namespace_09.py','runtime_checker':'check_shifted_runtime01.py','diagnostic':'validate_shifted_cuts.py','launcher':'launch_shifted_diagnostic03.py'}
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
def need(ok,why):
 if not ok:raise ValueError(why)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def checked(p):
 need(set(p)=={'path','sha256'} and Path(p['path']).is_absolute() and pin(p['path'])==p,'Pinned staging artifact differs');return json.loads(Path(p['path']).read_text())
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def load(path):
 s=importlib.util.spec_from_file_location('pinned_shifted_stage_driver',path);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);return d
def stage(p):
 need(set(p)==KEYS and p['schema']=='orbit-poc-shifted-stage-input-v1' and set(p['helpers'])==set(HELPERS),'Unexpected diagnostic staging contract')
 e=checked(p['execution']);freeze=checked(p['source_freeze']);controller=checked(p['controller']);pipeline=checked(p['pipeline']);config=checked(p['config'])
 for h in p['helpers'].values():need(set(h)=={'path','sha256'} and Path(h['path']).is_absolute() and pin(h['path'])==h,'Helper changed')
 d=load(p['helpers']['driver']['path']);old=Path(e['paths']['root']);root=Path(p['output_root']);need(root.is_absolute() and root!=old and old not in root.parents and root not in old.parents,'Separate diagnostic root required')
 need(not root.exists() and not root.is_symlink(),'Preserve prior diagnostic output')
 need(controller['status']=='passed' and controller['final_cleanup']['verified'] is True and controller['cli_validation']['pipeline']==p['pipeline'],'Required suite is not clean, passed and attributed')
 need(pipeline['status']=='passed' and tuple(x['name'] for x in pipeline['steps'])==STAGES and all(x['status']=='passed' for x in pipeline['steps']),'All14 gates must pass')
 need(d.source_receipt(Path(e['paths']['source']))==freeze['source'],'Original frozen source differs')
 need(config['segmented_runtime']['source_root']==e['paths']['source'] and config['dense_runtime']['source_root']==e['paths']['source'],'Original source/config mapping differs')
 root.mkdir();control=root/'control';control.mkdir();source=root/'source';shutil.copytree(e['paths']['source'],source)
 need(d.source_receipt(source)==freeze['source'],'Copied frozen source differs')
 helpers={}
 for key,name in HELPERS.items():
  target=control/name;shutil.copyfile(p['helpers'][key]['path'],target);need(pin(target)['sha256']==p['helpers'][key]['sha256'],'Copied helper differs');helpers[key]=pin(target)
 original_paths=e['paths'];e['paths']={**original_paths,'root':str(root),'source':str(source),'control':str(control),'wrapper':helpers['wrapper']['path'],'native_source':str(root/'native-source'),'build':str(root/'build'),'binaries':str(root/'binaries'),'run':str(root/'run'),'temporary':str(root/'temporary')}
 e['read_only_bindings'].append({'source':str(old),'target':str(old)})
 for key,value in helpers.items():e['runtime_artifacts']['shifted_'+key]=value
 for key in ('execution','controller','pipeline','source_freeze','config'):e['runtime_artifacts']['shifted_original_'+key]=p[key]
 save(control/'execution.json',e);execution=pin(control/'execution.json');d.load_execution(execution['path'])
 original_launch=json.loads(Path(controller['plan']['path']).read_text());validations={}
 for method in ('log_drag_ou','pulses'):
  rows=[x for x in pipeline['steps'] if x['name']=='linearization-'+method];need(len(rows)==1,'Missing captured method');validations[method]=rows[0]['evidence']['result'];checked(validations[method])
 plan={'schema':'orbit-poc-shifted-diagnostic-owned-plan-v2','execution':execution,'driver':helpers['driver'],'runner':helpers['runner'],'source_freeze':p['source_freeze'],'config':p['config'],'runtime_checker':helpers['runtime_checker'],'diagnostic':helpers['diagnostic'],'solver':config['segmented_runtime']['segmented_solver'],'controller':p['controller'],'pipeline':p['pipeline'],'validations':validations,'global_lock':original_launch['global_lock'],'wall_limit_seconds':1800}
 save(control/'plan.json',plan);pins={'driver_sha256':helpers['runner']['sha256'],'execution_sha256':execution['sha256'],'plan':pin(control/'plan.json')};save(control/'pins.json',pins)
 for key in ('execution','controller','pipeline','source_freeze','config'):checked(p[key])
 need(d.source_receipt(Path(original_paths['source']))==freeze['source'],'Original source changed during staging')
 fresh=[e['paths'][k] for k in ('native_source','build','binaries','run','temporary')];need(all(not Path(x).exists() and not Path(x).is_symlink() for x in fresh),'Diagnostic mutable paths must remain absent')
 receipt={'schema':'orbit-poc-shifted-staging-v1','status':'staged_unexecuted','input':p,'execution':execution,'plan':pin(control/'plan.json'),'pins':pin(control/'pins.json'),'source':freeze['source'],'fresh_mutable_paths':fresh,'helper':pin(__file__),'scope':'Separate byte-identical source/control staging only; no workload, physical evaluation or solver invoked. Independent full14 audit plus concrete plan review remain launch prerequisites.'};save(control/'staging.json',receipt);return receipt
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);v=a.parse_args();need(pin(v.plan)['sha256']==v.sha256,'Staging plan changed');print(json.dumps(stage(json.loads(v.plan.read_text()))))
