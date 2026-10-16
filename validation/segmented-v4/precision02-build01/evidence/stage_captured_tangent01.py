from pathlib import Path
import json,hashlib,shutil,importlib.util,xml.etree.ElementTree as ET,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-04';P=B/'preparation-03';D=B/'tangent-standalone-01';C=D/'control';BAD='753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2);f.write('\n')
base=P/'control/execution.json';assert sha(base)=='d2297c51648d9ba1f3644cbdae36ba5a95ad289d941ec4823aca6817af923236';e=json.loads(base.read_text())
assert sha(P/'control/pipeline.json')=='af054964670e6f978bde7db205dc9933ab269825e3ed176e2ca9cd251abc0ae3'
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(R/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json'):shutil.copy2(R/'control'/name,C/name)
e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'))
e['read_only_bindings'] += [{'source':str(R),'target':str(R)},{'source':str(B/'tangent-capture-03'),'target':str(B/'tangent-capture-03')},{'source':str(B/'tangent-telemetry-02'),'target':str(B/'tangent-telemetry-02')}]
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='One pinned standalone diagnostic compiled and executed onCPU24/one thread/8GiB/2h. Captured physical operator remains read-only. No GROOPS propagation/fits; protected6000 and original150WSL untouched.'
for name in ('owned_driver09.py','with_correctness_namespace_09.py','run_captured_tangent01.py','replay_captured_tangent01.py'):e['runtime_artifacts']['tangent_replay_'+name]=pin(C/name)
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
inputs={}
for name,relative in [('capture',str(B/'tangent-telemetry-02/run/replay/captured-system.bin')),('capture_result',str(B/'tangent-telemetry-02/run/replay/result.json')),('build_result',str(B/'tangent-capture-03/run/build-result/result.json')),('reader_source',str(C/'reader/replay.cpp')),('reader_manifest',str(C/'reader/include/manifest.json')),('reader_tangent',str(C/'reader/include/sixStateTangent.h')),('reader_force',str(C/'reader/include/syntheticForceDerivatives.h')),('reader_quadrature',str(C/'reader/include/eventQuadrature.h'))]:inputs[name]=pin(relative)
assert inputs['capture']['sha256']=='b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2'
built=json.loads(Path(inputs['build_result']['path']).read_text());assert built['status']=='built_diagnostic_only';native=Path(built['native']['path']);assert pin(native)==built['native']
p={'schema':'orbit-poc-captured-tangent-plan-v1','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'replay_captured_tangent01.py'),'controller':pin(C/'run_captured_tangent01.py'),'native':pin(native),'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/replay'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'}
save(C/'plan.json',p)
for name,value in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(value['path'],e))==value['sha256'],name
receipt={'schema':'orbit-poc-captured-tangent-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':pin(base),'input_attribution':inputs,'runtime_pins_verified':len(e['runtime_artifacts']),'mutable_inventory':{name:[str(x) for x in(D/name).iterdir()]for name in ('native_source','build','binaries','run','temporary')},'semantic_delta':'Standalone reader diagnostic against the exact preserved physical operator; no native GROOPS propagation or fits. Source, limits and every failure remain explicit.','original_failure':pin(P/'control/pipeline.json'),'native_runs':0}
save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
