from pathlib import Path
import argparse,json,hashlib,shutil,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-05';F=B/'tangent-rhs-family-preflight-02';D=B/'tangent-rhs-family-run-01';C=D/'control'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2);f.write('\n')
a=argparse.ArgumentParser();a.add_argument('--audit',type=Path,required=True);a.add_argument('--audit-sha256',required=True);args=a.parse_args()
assert sha(args.audit)==args.audit_sha256
audit=json.loads(args.audit.read_text());assert audit['passed']is True
original=F/'control/plan.json';assert sha(original)=='e6d9ddf25ab6801b9ebee8675ab9036f3595b87f5cd06facbf45e69d4ed15272';old=json.loads(original.read_text());e=json.loads(Path(old['execution']['path']).read_text());assert sha(old['execution']['path'])==old['execution']['sha256']
preflight=F/'run/preflight/result.json';result=json.loads(preflight.read_text());assert result['status']=='prepared_family_no_planned_solves'and result['plan_sha256']==sha(original)and result['planned_family_calls_executed']==0
assert result['source_bundle']==old['inputs']['source_bundle'];assert pin(result['binary']['path'])==result['binary'];assert pin(result['family_manifest']['path'])==result['family_manifest'];assert audit['family_manifest']==result['family_manifest'];assert audit['preflight_result']==pin(preflight);assert audit['preflight_plan']==pin(original);assert audit['binary']==result['binary'];assert audit['source_bundle']==old['inputs']['source_bundle']
pipeline=F/'control/pipeline.json';terminal=json.loads(pipeline.read_text());assert terminal['status']=='passed_diagnostic'and terminal['returncode']==0 and terminal['final_cleanup']['verified']is True
for name in('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(R/'source',D/'source')
for name in('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json','run_tangent_rhs_family01.py','launch_tangent_rhs_family01.py'):shutil.copy2(F/'control'/name,C/name)
for key in('driver','controller','source_freeze'):
 assert pin(C/Path(old[key]['path']).name)['sha256']==old[key]['sha256']
assert sha(F/'control/replay_tangent_rhs_family01.py')==old['worker']['sha256']
shutil.copy2(args.audit,C/'family-audit.json');assert sha(C/'family-audit.json')==args.audit_sha256
e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
binding={'source':str(F),'target':str(F)};existing=[x for x in e['read_only_bindings']if x['target']==str(F)]
if existing:assert existing==[binding]
else:e['read_only_bindings'].append(binding)
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='One frozen54-call captured-system experiment, common preflight binary and27 immutable cases. SerialCPU24/one thread/8GiB/2h. Retain numerical failures. No GROOPS propagation or fits.'
for name in('owned_driver09.py','with_correctness_namespace_09.py','replay_tangent_rhs_family02.py','run_tangent_rhs_family01.py','launch_tangent_rhs_family01.py'):e['runtime_artifacts']['tangent_family_'+name]=pin(C/name)
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
inputs={'source_bundle':old['inputs']['source_bundle'],'family_manifest':result['family_manifest'],'preflight_plan':pin(original),'preflight_result':pin(preflight),'family_audit':pin(C/'family-audit.json')}
p={'schema':old['schema'],'phase':'run','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'replay_tangent_rhs_family02.py'),'controller':pin(C/'run_tangent_rhs_family01.py'),'native':old['native'],'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/replay'),'global_lock':old['global_lock']}
save(C/'plan.json',p);save(C/'launch-pins.json',{'driver_sha256':p['controller']['sha256'],'execution_sha256':p['execution']['sha256'],'plan':pin(C/'plan.json')})
for name,v in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(v['path'],e))==v['sha256'],name
receipt={'schema':'orbit-poc-tangent-rhs-family-run-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':old['execution'],'runtime_pins_verified':len(e['runtime_artifacts']),'input_attribution':inputs,'common_binary':result['binary'],'preflight_terminal':pin(pipeline),'launch_pins':pin(C/'launch-pins.json'),'mutable_inventory':{n:[str(x)for x in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')},'planned_family_calls_executed':0,'fit_attempts':0,'groops_propagations':0}
save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
