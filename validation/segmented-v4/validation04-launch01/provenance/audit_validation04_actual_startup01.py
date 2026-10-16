from pathlib import Path
import json,hashlib,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-04';C=R/'control';S=R/'staging/namespace-smoke-01'
def art(p):
 p=Path(p);return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
def check(x):
 a=art(x['path']);assert a['sha256']==x['sha256'] and ('bytes' not in x or a['bytes']==x['bytes']),x;return a
def read(x):check(x);return json.loads(Path(x['path']).read_text())
p=read({'path':str(S/'process.json'),'sha256':'b10a1a891bbf712502d6837ce7574d5a0b9b258b53162951fb9c0302b91892ce'})
r=read(p['result']);assert p['result']['sha256']=='aa482a356f18b1b987faa1a8c868bfa4d63c1b5c3224752a7135fe4759311b64'
a=read({'path':str(C/'validation04-startup-addendum01.json'),'sha256':'ff370480ea3250346a5b559c8af08b9a58231c70198807649339673693dddb46'})
for x in list(a['base'].values())+list(a['helpers'].values())+[a['preserved_probe'],a['preserved_smoke']]:check(x)
for k in ('execution','config'):
 assert {q:p[k][q] for q in ('path','sha256')}==a['base'][k]
for k,h in [('probe','validation04_startup_probe.py'),('helper','smoke_segmented_validation04_02.py')]:assert {q:p[k][q] for q in ('path','sha256')}==a['helpers'][h]
e=read(p['execution']);d=read(p['derived_execution']);mutable=('native_source','build','binaries','run','temporary')
assert {k:v for k,v in e.items() if k!='paths'}=={k:v for k,v in d.items() if k!='paths'}
for k,v in e['paths'].items():assert d['paths'][k]==(str(S/k) if k in mutable else v)
assert p['argv']==[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(S/'execution.json'),'--execution-sha256',p['derived_execution']['sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python'],str(C/'validation04_startup_probe.py'),'--root',str(R),'--output',str(S/'run/probe-result')]
assert p['status']==r['status']=='passed' and p['returncode']==0 and p['interrupted_or_timeout'] is False and p['elapsed_seconds']<900
assert p['no_fit_executed'] and p['production_outputs_absent'] and p['final_cleanup']['verified'] and not p['final_cleanup']['errors']
assert p['cleanup']['verified'] and not p['cleanup']['live_owned_processes'] and p['cleanup']['returncode']==0 and p['cleanup']['forced'] is False
assert r['fit_or_numerical_gate_executed'] is False and r['full_runtime_verified'] and r['source_read_only'] and r['gtsam_version']=='4.2' and r['native_startup_only']=='--help'
assert (r['original_inputs'],r['dependencies'],r['data_directories'])==(14,589,3)
assert r['comparison_source_sha256']=='68e17e5b5ebe6fe22a47b9c6213c89397cfb80e25cc5e033da2621fc0aa44474'
expected={'dense':'f36bb698ea715a7fc3201c71f823315d493d943ecfb8e7ecad8fbb348ba61625','segmented':'a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'}
for k,h in expected.items():assert r['runtimes'][k]['native']['sha256']==h and r['runtimes'][k]['source_sha256']==r['comparison_source_sha256']
rows=r['last_six_stage_startup'];assert [x['stage'] for x in rows]==['nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses']
assert rows[0]['source_profile']['sha256']=='902923d3d84ce30cee1f0cb8484784aae62aafb69097f2d431c373913ac8aca0'
assert rows[1]['source_profile']['sha256']=='3440617770eae3177d6a87b8b743e79603ac9b0e9245da0d84f3016177eb1ed8'
logs=[]
for i,x in enumerate(rows):
 assert x['returncode']==0 and x['scope']=='Dependency/startup only; original gate not executed';logs.append(check(x['log']))
 if i in (2,3):assert x['collected']==x['expected_collection']==(3 if i==2 else 303) and x['command'][-1]=='--collect-only'
 else:assert x['command'][-1]=='--help'
assert rows[4]['request']['sha256']=='2189944cfb519b5ca0730e6e02ee9cb809145a0845f66846931a8fb199694dfd' and rows[5]['request']['sha256']=='9de707ae51e5031a5b13f1d02ab5ec5a67e996195840de6c5c7e81457a74c9f5'
assert rows[4]['initial_state']==rows[5]['initial_state'] and rows[4]['initial_state']['sha256']=='61b08f300902d38357b3ea6889711818a3ae590af74de05375121ac05dc403ea'
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot==p['admission']['boot_id']=='95156dd4-0d4c-499d-a214-8883a2d650fa'
assert p['admission']['status']=='admitted' and not p['admission']['conflicting_processes'] and p['admission']['fit_cpu']==24
ids={(x['pid'],x['start_ticks']):x for x in [p['admission']['driver_identity'],p['process'],*p['cleanup']['identities'],*(x for command in p['final_cleanup']['commands'] for x in command['identities'])]};absent=[]
for (pid,ticks),x in ids.items():
 f=Path('/proc')/str(pid)/'stat'
 try:
  fields=f.read_text().rsplit(')',1)[1].split();actual=int(fields[19]);assert actual!=ticks,(pid,ticks);absent.append({'pid':pid,'start_ticks':ticks,'current_start_ticks':actual})
 except FileNotFoundError:absent.append({'pid':pid,'start_ticks':ticks,'absent':True})
absence={k:not Path(e['paths'][k]).exists() for k in mutable};assert all(absence.values())
for k in ('pipeline.json','validation-launch.json'):assert not (C/k).exists()
plan=read(a['base']['launch_plan']);assert plan['wall_limit_seconds']==108000 and plan['global_lock']=='/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'
for k in ('driver','runner','native_equivalence','source_freeze','execution','config'):check(plan[k])
assert art(S/'process.json')['sha256']=='b10a1a891bbf712502d6837ce7574d5a0b9b258b53162951fb9c0302b91892ce'
print(json.dumps({'schema':'orbit-poc-validation04-actual-startup-independent-readback-v1','passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'process':art(S/'process.json'),'result':art(S/'run/probe-result/result.json'),'addendum':art(C/'validation04-startup-addendum01.json'),'launch_plan':art(C/'launch-plan.json'),'elapsed_seconds':p['elapsed_seconds'],'current_boot_id':boot,'owned_process_absence':absent,'actual_log_pins':logs,'production_outputs_absent':absence,'checks':{'exact_actual_process_result_plan_and_helper_attribution':True,'only_five_mutable_scratch_directories_rebound':True,'current_host_owned_successful_cleanup':True,'source_readonly_and_14_inputs_589_dependencies':True,'distinct_original_replays_and_dense_segmented_binaries':True,'native_three_structural_303_collection_only':True,'gnss_linearization_inputs_and_gtsam42':True,'native_launch_plan_unchanged':True},'scope':'Actual read-only startup only. No native numerical gate, propagation or fit performed by this audit. Unchanged full14 validation launch requires its live admission/shared lock.'},indent=2))
