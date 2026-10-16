from pathlib import Path
import json,hashlib,datetime,os
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');R=B/'validation-04';C=R/'control'
def art(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):return json.loads(Path(p).read_text())
def proc(pid):
 p=Path('/proc')/str(pid);s=p.joinpath('stat').read_text().rsplit(')',1)[1].split();cmd=p.joinpath('cmdline').read_bytes();status=dict(line.split(':',1) for line in p.joinpath('status').read_text().splitlines() if ':' in line)
 return {'pid':pid,'start_ticks':int(s[19]),'parent':int(s[1]),'state':s[0],'argv':[x.decode() for x in cmd.split(b'\0') if x],'command_sha256':hashlib.sha256(cmd).hexdigest(),'affinity':status['Cpus_allowed_list'].strip(),'pid_namespace':os.readlink(p/'ns/pid')}
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot=='95156dd4-0d4c-499d-a214-8883a2d650fa'
l=read(C/'validation-launch.json');assert l['launch_committed'] and l['start_new_session'] and l['campaign_resume']=='not_applicable'
assert l['driver_process']=={'pid':2374220,'start_ticks':111009241,'boot_id':boot}
assert l['execution_sha256']==art(C/'execution.json')['sha256']=='526e8f704650eccc69863669ac4068c1c192f38b990a5a2190eba81d4a22007d'
assert l['pins_sha256']==art(C/'launch-pins.json')['sha256']=='4b0467351c96859874e78569ad626baddda98902e3206770814516a34d14bd24'
assert l['launch_helper_sha256']==art(C/'launch_segmented_validation01.py')['sha256']=='38ac281ffd03e7ecc44c19354d41bcc464a8b112a2bd9a10189d9d6501dbdfc8'
assert art(C/'launch-plan.json')['sha256']=='0a5c65a31b0e8db192a99c29018ab391eb22d81e26f9ce66c77ea164092b07c7'
q=read(C/'launch-plan.json');e=read(C/'execution.json')
expected=[e['runtime_artifacts']['control_python']['path'],str(C/'run_segmented_validation01.py'),'--plan',str(C/'launch-plan.json'),'--sha256',art(C/'launch-plan.json')['sha256']]
d=proc(2374220);assert d['start_ticks']==111009241 and d['parent']==1 and d['argv']==l['argv']==l['observed_argv']==expected and d['command_sha256']==l['command_sha256'] and d['state']!='Z'
locks=[]
for f in (Path('/proc')/str(d['pid'])/'fd').iterdir():
 try:
  target=os.readlink(f)
  if target in (q['global_lock'],str(C/'validation-controller.lock')):
   info=(Path('/proc')/str(d['pid'])/'fdinfo'/f.name).read_text();assert 'FLOCK' in info and 'WRITE' in info and str(d['pid']) in info;locks.append({'path':target,'inode':Path(target).stat().st_ino,'fd':f.name,'fdinfo':info})
 except FileNotFoundError:pass
assert {x['path'] for x in locks}=={q['global_lock'],str(C/'validation-controller.lock')}
c=read(C/'validation-controller.json');assert c['status']=='running' and c['release_ready'] is False and c['plan']['sha256']==art(C/'launch-plan.json')['sha256']
a=c['admission'];assert a['status']=='admitted' and a['boot_id']==boot and not a['conflicting_processes'] and a['driver_identity']['pid']==d['pid'] and a['driver_identity']['start_ticks']==d['start_ticks']
assert c['source']['sha256']=='1fe0f24166a7983a7c10eaf1712e4b5545f02c61bd38406fa9d07e70cd7d6a4e'
argv=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(C/'execution.json'),'--execution-sha256',l['execution_sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python'],'-m','orbit_poc.cli','segmented','validate','--config',str(C/'segmented-v4.json')];assert c['argv']==argv
chain=[d];queue=[d['pid']]
while queue:
 pid=queue.pop(0)
 try:children=(Path('/proc')/str(pid)/'task'/str(pid)/'children').read_text().split()
 except FileNotFoundError:continue
 for x in children:
  try:v=proc(int(x))
  except FileNotFoundError:continue
  assert v['parent']==pid;chain.append(v);queue.append(v['pid'])
assert any(x['pid']==c['process']['pid'] and x['start_ticks']==c['process']['start_ticks'] for x in chain)
assert any('orbit_poc.cli' in x['argv'] and x['affinity']=='24' for x in chain)
active_paths=sorted((R/'run/validation').glob('attempt-*/pipeline.json'));assert len(active_paths)==1,active_paths
active=active_paths[0];p=read(active);latest={'pipeline':{'path':str(active)}}
assert p['schema']=='orbit-poc-segmented-validation-run-v1' and p['status']=='running'
expected_stages=['native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses']
assert [x['name'] for x in p['steps']]==expected_stages
phase='public_validation_pipeline_running';active_stage=[x['name'] for x in p['steps'] if x['status']=='running']
assert len(active_stage)<=1
completed=[]
for step in p['steps']:
 if step['status']=='passed' and step['name'] in ('native-tests','correction-tests'):
  ex=step['execution'];assert art(ex['path'])['sha256']==ex['sha256'];ev=read(ex['path']);assert ev['status']=='complete' and ev['returncode']==0 and ev['harness_execution']['owned_process_group_cleaned'] is True
  j=step['evidence']['junit'];assert art(j['path'])['sha256']==j['sha256']
  import xml.etree.ElementTree as ET
  suites=ET.parse(j['path']).getroot().findall('testsuite');counts={k:sum(int(x.attrib.get(k,0)) for x in suites) for k in ('tests','failures','errors','skipped')}
  assert counts=={'tests':106 if step['name']=='native-tests' else 51,'failures':0,'errors':0,'skipped':0};completed.append({'name':step['name'],'execution':ex,'junit':j,'counts':counts})
logtail=(C/'validation-cli.log').read_text(errors='replace')[-4000:]
assert not (R/'run/manifest.json').exists() and not (R/'run/attempts').exists()
print(json.dumps({'schema':'orbit-poc-validation04-actual-launch-independent-readback-v1','passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'launch':art(C/'validation-launch.json'),'plan':art(C/'launch-plan.json'),'controller':art(C/'validation-controller.json'),'controller_snapshot':c,'owned_chain':chain,'held_locks':locks,'validation_pipeline_snapshot':p,'pipeline_path':latest['pipeline']['path'],'observed_phase':phase,'active_stage':active_stage,'completed_test_gates':completed,'cli_log_tail':logtail,'checks':{'exact_durable_launch_plan_and_identity':True,'current_driver_orphan_adopted_by_init':True,'current_owned_chain':True,'shared_and_local_locks_held':True,'fresh_admission_no_conflicts':True,'public_cli_on_cpu24':True,'exact_fourteen_stage_pipeline_running':True,'no_benchmark_attempts':True},'scope':'Compact live attribution only; no duplicate runtime guard or scientific execution. No completed numerical gate or release claim.'},indent=2))
