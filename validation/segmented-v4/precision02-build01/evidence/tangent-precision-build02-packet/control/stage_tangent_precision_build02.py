from pathlib import Path
import json,hashlib,shutil,importlib.util,xml.etree.ElementTree as ET,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-05';P=B/'preparation-04';D=B/'tangent-precision-02';C=D/'control';BAD='753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2);f.write('\n')
base=P/'control/execution.json';assert sha(base)=='98e9ea204c22d176e271141b993338579430df9354bcde5f74a44fb9476efe77';e=json.loads(base.read_text())
assert sha(P/'control/pipeline.json')=='7f3e029b2314dde54ebab75892f2193adb474f9caa1bb15225b58d041f7e8241'
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(R/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json'):shutil.copy2(R/'control'/name,C/name)
e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
assert not any(x['target']==str(R)for x in e['read_only_bindings'])
e['read_only_bindings'] += [{'source':str(R),'target':str(R)}]
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='One separate precision-candidate build onCPU24/one thread/8GiB/2h. Rebuild all27 native header dependents, preserve original source/build/executable, no fitting. Protected6000 and original150WSL untouched.'
for name in ('owned_driver09.py','with_correctness_namespace_09.py','run_tangent_precision_build01.py','build_tangent_precision01.py'):e['runtime_artifacts']['tangent_replay_'+name]=pin(C/name)
for name in ('captured-outcome-review.json','candidate-source-review.json','sixStateTangent-compensated-native01.h'):
 e['runtime_artifacts']['precision_candidate_'+name]=pin(C/name)
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
inputs={}
for name,relative in [('original_build_manifest','/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/build/build-manifest.json'),('recipe_inspection',str(C/'precision-recipes.json')),('link_inspection',str(C/'link-inspection.json')),('candidate_header',str(C/'sixStateTangent-compensated-native01.h'))]:inputs[name]=pin(relative)

native=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/binaries/groops-a66949456ad67b81');assert sha(native)=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
p={'schema':'orbit-poc-tangent-precision-build-plan-v1','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'build_tangent_precision01.py'),'controller':pin(C/'run_tangent_precision_build01.py'),'native':pin(native),'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/build-result'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'}
save(C/'plan.json',p)
for name,value in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(value['path'],e))==value['sha256'],name
receipt={'schema':'orbit-poc-tangent-precision-build-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':pin(base),'input_attribution':inputs,'runtime_pins_verified':len(e['runtime_artifacts']),'mutable_inventory':{name:[str(x) for x in(D/name).iterdir()]for name in ('native_source','build','binaries','run','temporary')},'semantic_delta':'Separate native compensated-quadrature candidate: preserve prior wide affine update and original GMRES control/limits, change only stored-weight quadrature accumulation; all27 dependent translation units recompiled. Existing installed export hook and all original artifacts preserved. Frozen Python runtime remains unchanged; full numerical validation is separate.','original_failure':pin(P/'control/pipeline.json'),'native_runs':0}
save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
