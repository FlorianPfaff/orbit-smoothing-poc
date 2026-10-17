from pathlib import Path
import json,hashlib,datetime,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'shifted-diagnostic-02';C=R/'control';V=B/'validation-04'
def art(path):
 p=Path(path);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest()}
def read(p):return json.loads(Path(p).read_text())
def check(pin):assert art(pin['path'])=={k:pin[k] for k in ('path','sha256')},pin
expected={'execution.json':'8e9be3c485ae53cec8fb99c2e57bf7a04ce508b64b4dfb87d9d9def2649c7f93','plan.json':'256dc7655b6f6888dae2760d86d62d6b86f4e63662fbc0f1dd24361bbfdc8eb5','pins.json':'c43abe7cd5b397be2b069881e88526ebb841240eebecc36f3d6050d1d7df6d63'}
for name,h in expected.items():assert art(C/name)['sha256']==h
stage=read(C/'staging.json');p=read(C/'plan.json');e=read(C/'execution.json');base=read(V/'control/execution.json');freeze=read(V/'control/source-freeze.json')
assert stage['input']==read(B/'preparation-03/control/shifted02-staging-plan01.json') and art(B/'preparation-03/control/shifted02-staging-plan01.json')['sha256']=='8703269fa2755930d58729bd0e59fc1ee0381e61917b4b8298096c4e2076f7d7'
for role in ('driver','runner','diagnostic','runtime_checker','solver','source_freeze','controller','pipeline','config','execution'):check(p[role])
for role,v in p['validations'].items():check(v)
assert p['schema']=='orbit-poc-shifted-diagnostic-owned-plan-v2' and p['wall_limit_seconds']==1800 and p['global_lock']=='/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'
assert p['execution']==art(C/'execution.json') and stage['execution']==p['execution'] and stage['plan']==art(C/'plan.json') and stage['pins']==art(C/'pins.json')
assert p['source_freeze']==stage['input']['source_freeze'] and p['config']==stage['input']['config'] and p['controller']==stage['input']['controller'] and p['pipeline']==stage['input']['pipeline']
expected_paths={**base['paths'],'root':str(R),'source':str(R/'source'),'control':str(C),'wrapper':str(C/'with_correctness_namespace_09.py'),'native_source':str(R/'native-source'),'build':str(R/'build'),'binaries':str(R/'binaries'),'run':str(R/'run'),'temporary':str(R/'temporary')}
assert e['paths']==expected_paths
assert e['read_only_bindings']==base['read_only_bindings']+[{'source':str(V),'target':str(V)}]
assert {k:v for k,v in e.items() if k not in ('paths','read_only_bindings','runtime_artifacts')}=={k:v for k,v in base.items() if k not in ('paths','read_only_bindings','runtime_artifacts')}
assert len(base['runtime_artifacts'])==371
for key,value in base['runtime_artifacts'].items():assert e['runtime_artifacts'][key]==value,key
added={k:v for k,v in e['runtime_artifacts'].items() if k not in base['runtime_artifacts']}
assert set(added)=={'shifted_'+k for k in stage['input']['helpers']}|{'shifted_original_'+k for k in ('execution','controller','pipeline','source_freeze','config','launch_plan')}
for key,pin in added.items():check(pin)
for k,pin in stage['input']['helpers'].items():
 name=Path(pin['path']).name;actual=art(C/name);assert actual['sha256']==pin['sha256'] and added['shifted_'+k]==actual
spec=importlib.util.spec_from_file_location('reviewed_owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
assert d.load_execution(C/'execution.json')==e
actual_source=d.source_receipt(R/'source');assert actual_source==freeze['source']==stage['source'] and len(actual_source['files'])==384 and actual_source['sha256']=='1fe0f24166a7983a7c10eaf1712e4b5545f02c61bd38406fa9d07e70cd7d6a4e'
spec=importlib.util.spec_from_file_location('reviewed_shifted',p['runner']['path']);runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner);assert runner.load_plan(C/'plan.json',expected['plan.json'])==p
absent={k:not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in ('native_source','build','binaries','run','temporary')};assert all(absent.values())
assert not (R/'staging/runtime-smoke-01').exists() and not (C/'diagnostic-launch.json').exists()
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==e['host']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa' and socket.gethostname()==e['host']['hostname']
smoke=B/'preparation-03/control/smoke_shifted_runtime01.py';assert art(smoke)['sha256']=='d8bfc99cc66f75a4aa16d681efffc4ca42ad26357fe5f2842e0e68eeab18795b'
command=['/usr/bin/taskset','-c','24-27','/usr/bin/python3',str(smoke),'--plan',str(C/'plan.json'),'--sha256',expected['plan.json'],'--helper-sha256',art(smoke)['sha256']]
print(json.dumps({'passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':art(C/'plan.json'),'execution':art(C/'execution.json'),'pins':art(C/'pins.json'),'staging':art(C/'staging.json'),'base_execution':art(V/'control/execution.json'),'base_runtime_pins_unchanged':371,'new_runtime_pins':added,'full_source':{'sha256':actual_source['sha256'],'file_count':384},'exact_path_and_binding_delta':True,'production_outputs_absent':absent,'current_boot_id':boot,'smoke_helper':art(smoke),'smoke_command':command,'scope':'Read-only concrete packet/full copied-source audit; unchanged base runtime pins and mappings reused from just-completed independently audited full14 suite. No redundant bulk runtime rescan, namespace or numerical execution.'},indent=2))
