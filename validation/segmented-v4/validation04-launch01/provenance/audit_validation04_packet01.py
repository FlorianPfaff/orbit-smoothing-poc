from pathlib import Path
from copy import deepcopy
import datetime,hashlib,importlib.util,json,tarfile
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-04';C=R/'control';OLD=B/'validation-03'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_bytes())
def check(r):assert sha(r['path'])==r['sha256'],r;return Path(r['path'])
expected={'execution.json':'526e8f704650eccc69863669ac4068c1c192f38b990a5a2190eba81d4a22007d',
 'segmented-v4.json':'e23eb3a1b4eafc6c1c279183292513b87e64a366061ac6ef645987700c193fac',
 'launch-plan.json':'0a5c65a31b0e8db192a99c29018ab391eb22d81e26f9ce66c77ea164092b07c7',
 'launch-pins.json':'4b0467351c96859874e78569ad626baddda98902e3206770814516a34d14bd24',
 'source-freeze.json':'87ad55dcd0c4329cb4e37a37adfe3871cb85d3fb88e8a46b3cff388aa17e9f29'}
for name,value in expected.items():assert sha(C/name)==value
s=read(C/'staging.json');assert s['status']=='passed' and s['native_work_started'] is False
check(s['archive']);check(s['admission']);check(s['native_equivalence'])
e=read(C/'execution.json');old=read(B/'preparation-02/control05/execution05.json')
spec=importlib.util.spec_from_file_location('owned_validation04',C/'owned_driver09.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
assert d.load_execution(C/'execution.json')==e
assert e['host']==old['host'] and e['fit_cpu']==old['fit_cpu']==24 and e['build_cpus']==old['build_cpus']==[24,25,26,27]
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==e['host']['boot_id']
newkeys={'validation04_'+n for n in ('run_segmented_validation01.py','launch_segmented_validation01.py','validation03_startup_probe.py','smoke_segmented_validation04.py','stage_segmented_validation04.py','assemble_validation04_packet.py','owned_driver09.py','with_correctness_namespace_09.py','profile-fix-independent-review.json','profile-fix-pins.json','native-input-equivalence.json')}
assert set(e['runtime_artifacts'])-set(old['runtime_artifacts'])==newkeys
assert all(e['runtime_artifacts'][k]==v for k,v in old['runtime_artifacts'].items())
verified=[]
for key,value in e['runtime_artifacts'].items():
 actual=d.resolved_host_path(value['path'],e);assert sha(actual)==value['sha256'],key
 verified.append({'name':key,'pin':value,'physical_path':str(actual)})
freeze=read(C/'source-freeze.json');previous=read(check(freeze['previous_source']))
assert d.source_receipt(R/'source')==freeze['source'] and len(freeze['source']['files'])==384
assert freeze['source']['sha256']=='1fe0f24166a7983a7c10eaf1712e4b5545f02c61bd38406fa9d07e70cd7d6a4e'
assert freeze['comparison_source']['sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474' and len(freeze['comparison_source']['files'])==304
changes={k for k in set(freeze['source']['files'])|set(previous['source']['files']) if freeze['source']['files'].get(k)!=previous['source']['files'].get(k)}
allowed={'src/orbit_poc/segmented/multiday.py','tests/test_segmented_multiday.py','tests/test_comparison_initialization.py'}
assert changes==allowed==set(freeze['allowed_changed_paths'])
review=read(check(freeze['patch_review']));assert review['passed'] is True and sha(C/'profile-fix-independent-review.json')=='3f16bde08e1c9d5993292a061ead4279184100545593bc58247f1a203e4319b3'
patch=read(C/'profile-fix-pins.json');assert sha(C/'profile-fix-pins.json')==review['candidate_files']['sha256']
assert {x['relative']:{'path':x['path'],'sha256':x['sha256']} for x in patch}==review['patched_files']
for item in patch:assert sha(R/'source'/item['relative'])==item['sha256'] and (R/'source'/item['relative']).stat().st_size==item['bytes']
equiv=read(C/'native-input-equivalence.json');eng=read(check(equiv['engineering02_source']))
native={k:v for k,v in freeze['source']['files'].items() if k.startswith('groops/') or k=='scripts/build_groops.py'}
assert equiv['status']=='passed' and equiv['all_native_inputs_byte_identical'] is True and equiv['native_input_count']==len(native)==70 and equiv['files']==native
assert {k:v for k,v in eng['source']['files'].items() if k.startswith('groops/') or k=='scripts/build_groops.py'}==native
cfg=read(C/'segmented-v4.json');oldcfg=read(OLD/'control/segmented-v4.json');compare=deepcopy(cfg)
assert cfg['output_dir']==str(R/'run') and cfg['preparation']['cache_dir']==str(R/'cache')
compare['output_dir']=oldcfg['output_dir'];compare['preparation']['cache_dir']=oldcfg['preparation']['cache_dir']
for key in ('dense_runtime','segmented_runtime'):
 assert cfg[key]['source_root']==str(R/'source') and cfg[key]['source_sha256']==freeze['comparison_source']['sha256']
 assert cfg[key]['native']['sha256']==equiv['native_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
 compare[key]['source_root']=oldcfg[key]['source_root'];compare[key]['source_sha256']=oldcfg[key]['source_sha256']
assert cfg['segmented_runtime']['segmented_solver']['sha256']==equiv['solver_sha256']=='2c8481050806ce9d4c89d4c605fd9036bed3cdfb97010efeb359213aa0dbc223'
assert cfg['resources']['admission']==s['admission'];compare['resources']['admission']=oldcfg['resources']['admission']
assert compare==oldcfg
assert e['read_only_bindings'][:len(old['read_only_bindings'])]==old['read_only_bindings']
extra=e['read_only_bindings'][len(old['read_only_bindings']):]
wanted=[{'source':str(OLD),'target':str(OLD)}]
for key in d.MUTABLE_KEYS:wanted.append({'source':str(B/'preparation-02/backings'/key),'target':old['paths'][key]})
wanted.append({'source':str(OLD/'run/validation'),'target':str(OLD/'run/validation')});assert extra==wanted
assert all(not Path(e['paths'][k]).exists() for k in d.MUTABLE_KEYS)
assert not (R/'staging/namespace-smoke-01').exists()
assert not (C/'validation-controller.json').exists() and not (C/'launch.json').exists()
plan=read(C/'launch-plan.json');launch=read(C/'launch-pins.json')
for key in ('execution','driver','runner','source_freeze','config','native_equivalence'):check(plan[key])
assert plan['global_lock']=='/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock' and plan['wall_limit_seconds']==108000
assert launch=={'driver_sha256':sha(C/'run_segmented_validation01.py'),'execution_sha256':sha(C/'execution.json'),'plan':pin(C/'launch-plan.json')}
spec=importlib.util.spec_from_file_location('validation_runner',C/'run_segmented_validation01.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
assert runner.load_plan(C/'launch-plan.json',sha(C/'launch-plan.json'))==plan
assert len(runner.STAGES)==14 and freeze['source']['files']['src/orbit_poc/segmented/validation.py']==previous['source']['files']['src/orbit_poc/segmented/validation.py']
command=runner.cli_command(e,plan);assert 'segmented' in command and 'validate' in command and 'run' not in command
assert sha(C/'smoke_segmented_validation04.py')==e['runtime_artifacts']['validation04_smoke_segmented_validation04.py']['sha256']
print(json.dumps({'schema':'orbit-poc-validation04-packet-independent-review-v1','passed':True,
 'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_freeze':pin(C/'source-freeze.json'),'execution':pin(C/'execution.json'),'config':pin(C/'segmented-v4.json'),'launch_plan':pin(C/'launch-plan.json'),'launch_pins':pin(C/'launch-pins.json'),'staging':pin(C/'staging.json'),
 'full_source_sha256':freeze['source']['sha256'],'comparison_source_sha256':freeze['comparison_source']['sha256'],'source_file_count':384,'comparison_file_count':304,'changed_files':sorted(changes),'source_review':freeze['patch_review'],
 'native_equivalence':pin(C/'native-input-equivalence.json'),'native_input_count':70,'runtime_pin_count':len(verified),'runtime_pins':verified,'unchanged_all_other_config_fields':True,'read_only_binding_delta':extra,'production_outputs_absent':True,'startup_absent':True,
 'stages':list(runner.STAGES),'planned_native_validation_command':command,
 'scope':'Exact new source/config/control packet; only reviewed synthetic adapter plus two tests differ, all70 native inputs and all other scientific settings unchanged. Fresh full14 gate execution is required, without previous result inheritance. Approved for the existing owned read-only startup smoke after current-host admission; no native workload was launched by this review.'},sort_keys=True))
