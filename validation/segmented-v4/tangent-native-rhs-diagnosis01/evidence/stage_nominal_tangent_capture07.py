from pathlib import Path
import json,hashlib,shutil,importlib.util,xml.etree.ElementTree as ET,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-05';P=B/'preparation-04';D=B/'tangent-telemetry-04';C=D/'control';BAD='753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769'
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
for path in (R,B/'validation-04',B/'tangent-capture-06',B/'tangent-compensation-single-01',B/'tangent-precision-02'):
 matches=[x for x in e['read_only_bindings']if x['target']==str(path)]
 if matches:assert matches==[{'source':str(path),'target':str(path)}]
 else:e['read_only_bindings'].append({'source':str(path),'target':str(path)})
e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='One exact72h telemetry-only operator capture plus standalone diagnostic onCPU24/one thread/8GiB/2h. Separate capture binary with mandatory original-object baseline byte match; original inputs/profile/thresholds. No fits. Protected6000 and original150WSL untouched.'
for name in ('owned_driver09.py','with_correctness_namespace_09.py','run_nominal_tangent_capture03.py','replay_nominal_tangent_capture03.py'):e['runtime_artifacts']['tangent_replay_'+name]=pin(C/name)
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
baseline_plan=B/'tangent-compensation-single-01/control/plan.json';baseline=json.loads(baseline_plan.read_text());inputs={k:baseline['inputs'][k]for k in ('template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield')}
inputs['original_log']=pin(B/'tangent-compensation-single-01/run/replay/single-evaluation/propagate.log');inputs['baseline_plan']=pin(baseline_plan);inputs['baseline_replay']=pin(B/'tangent-compensation-single-01/run/replay/result.json')
t=ET.parse(inputs['template']['path']).getroot()
for name,tag in [('attitude','inputfileStarCamera'),('satellite_model','inputfileSatelliteModel'),('eop','inputfileEOP'),('ephemerides','inputfileEphemerides'),('gravityfield','inputfilePotentialCoefficients')]:
 canonical=t.find('.//'+tag).text;src=o.resolved_host_path(canonical,e);inputs[name]={'path':canonical,'sha256':sha(src)}
build_result=B/'tangent-capture-06/run/build-result/result.json';built=json.loads(build_result.read_text());assert built['status']=='built_diagnostic_only' and built['baseline_relinked_sha256']=='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2';native=Path(built['native']['path']);assert pin(native)==built['native'];inputs['reader']=built['reader'];assert pin(inputs['reader']['path'])==inputs['reader'];inputs['build_result']=pin(build_result)
fixture_root=B/'tangent-capture-06/control';fixture_names=['replay.cpp','probe.cpp','test_quad.py','test_compensation.py','include/manifest.json','include/sixStateTangent.h','include/syntheticForceDerivatives.h','include/eventQuadrature.h'];fixture={'schema':'orbit-poc-tangent09-fixture-pins-v1','files':{name:pin(fixture_root/'reader'/name)for name in fixture_names}};fixture['files']['base_test_replay.py']=pin(fixture_root/'tangent72-diagnostic01/test_replay.py');save(C/'fixture-pins.json',fixture);inputs['fixture_manifest']=pin(C/'fixture-pins.json')
p={'schema':'orbit-poc-nominal-tangent-current-capture-plan-v1','execution':pin(C/'execution.json'),'driver':pin(C/'owned_driver09.py'),'worker':pin(C/'replay_nominal_tangent_capture03.py'),'controller':pin(C/'run_nominal_tangent_capture03.py'),'native':pin(native),'source_freeze':pin(C/'source-freeze.json'),'inputs':inputs,'output':str(D/'run/replay'),'global_lock':'/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'}
save(C/'plan.json',p)
for name,value in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(value['path'],e))==value['sha256'],name
receipt={'schema':'orbit-poc-nominal-tangent-capture-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':pin(base),'input_attribution':inputs,'runtime_pins_verified':len(e['runtime_artifacts']),'mutable_inventory':{name:[str(x) for x in(D/name).iterdir()]for name in ('native_source','build','binaries','run','temporary')},'semantic_delta':'Capture-only native diagnostic on the original fixed72h inputs, followed by separately instrumented standalone solver telemetry. Same limits and mathematical operator; no correction, fitting or acceptance promotion.','original_failure':pin(B/'tangent-compensation-single-01/control/pipeline.json'),'native_runs':0}
save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
