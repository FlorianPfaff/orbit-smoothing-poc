from pathlib import Path
import json,hashlib,shutil,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-05';P=B/'preparation-04';D=B/'tangent-rhs-family-01';C=D/'control'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2);f.write('\n')
base=P/'control/execution.json';assert sha(base)=='98e9ea204c22d176e271141b993338579430df9354bcde5f74a44fb9476efe77';e=json.loads(base.read_text())
for name in('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(R/'source',D/'source')
for name in('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json'):shutil.copy2(R/'control'/name,C/name)
e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
for root in(R,B/'tangent-precision-02',B/'tangent-telemetry-02',B/'tangent-telemetry-03',B/'tangent-telemetry-04'):
 binding={'source':str(root),'target':str(root)};existing=[x for x in e['read_only_bindings']if x['target']==str(root)]
 if existing:assert existing==[binding],existing
 else:e['read_only_bindings'].append(binding)
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='Preflight only: compile a common baseline/wide diagnostic reader, focused fixtures, and freeze27 captured RHS cases. CPU24,one thread,8GiB,2h; stop before all54 planned calls. No native GROOPS propagation or fits.'
for name in('owned_driver09.py','with_correctness_namespace_09.py','run_tangent_rhs_family01.py','replay_tangent_rhs_family01.py','launch_tangent_rhs_family01.py'):e['runtime_artifacts']['tangent_family_'+name]=pin(C/name)
manifest=C/'reader/generation.json';assert sha(manifest)=='6615014643a2332a9f706c9b3275f07c65b9872d534edbcc661f4320c8ef71f2';m=json.loads(manifest.read_text());files={}
for row in m['source_files']:
 p=C/'reader'/row['path'];assert sha(p)==row['sha256']and p.stat().st_size==row['bytes'];files[row['path']]=pin(p);e['runtime_artifacts']['tangent_family_source_'+row['path']]=pin(p)
e['runtime_artifacts']['tangent_family_generation']=pin(manifest)
save(C/'source-bundle.json',{'schema':'orbit-poc-tangent-rhs-source-bundle-v1','source_manifest':pin(manifest),'files':files});save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
inputs={'source_bundle':pin(C/'source-bundle.json')}
for name,root,h in [('historical_large','tangent-telemetry-02','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'),('current_small','tangent-telemetry-03','f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044'),('current_large','tangent-telemetry-04','b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3')]:
 inputs['anchor_'+name]=pin(B/root/'run/replay/captured-system.bin');assert inputs['anchor_'+name]['sha256']==h
native=pin(B/'tangent-precision-02/binaries/groops-precision-25661fd88779c009');assert native['sha256']=='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
p={'schema':'orbit-poc-tangent-rhs-family-plan-v1','phase':'prepare','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'replay_tangent_rhs_family01.py'),'controller':pin(C/'run_tangent_rhs_family01.py'),'native':native,'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/preflight'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'}
save(C/'plan.json',p);save(C/'launch-pins.json',{'driver_sha256':p['controller']['sha256'],'execution_sha256':p['execution']['sha256'],'plan':pin(C/'plan.json')})
for name,v in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(v['path'],e))==v['sha256'],name
receipt={'schema':'orbit-poc-tangent-rhs-family-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'source_bundle':pin(C/'source-bundle.json'),'base_execution':pin(base),'runtime_pins_verified':len(e['runtime_artifacts']),'input_attribution':inputs,'launch_pins':pin(C/'launch-pins.json'),'mutable_inventory':{n:[str(x)for x in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')},'planned_family_calls_executed':0,'fit_attempts':0,'groops_propagations':0}
save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
