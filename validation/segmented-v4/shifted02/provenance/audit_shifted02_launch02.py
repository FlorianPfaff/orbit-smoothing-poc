from pathlib import Path
import json,hashlib,datetime,os
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/shifted-diagnostic-02');C=R/'control'
def art(p):
 b=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):return json.loads(Path(p).read_text())
def proc(pid):
 p=Path('/proc')/str(pid);s=(p/'stat').read_text().rsplit(')',1)[1].split();raw=(p/'cmdline').read_bytes();status=dict(x.split(':',1) for x in (p/'status').read_text().splitlines() if ':' in x)
 return {'pid':pid,'start_ticks':int(s[19]),'parent':int(s[1]),'state':s[0],'argv':[x.decode() for x in raw.split(b'\0') if x],'command_sha256':hashlib.sha256(raw).hexdigest(),'affinity':status['Cpus_allowed_list'].strip()}
l=read(C/'shifted-launch.json');p=read(C/'plan.json');j=read(C/'pipeline.json');boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
assert l['driver_process']=={'pid':2408283,'start_ticks':111441604,'boot_id':boot} and boot=='95156dd4-0d4c-499d-a214-8883a2d650fa'
assert l['execution_sha256']==art(C/'execution.json')['sha256']=='8e9be3c485ae53cec8fb99c2e57bf7a04ce508b64b4dfb87d9d9def2649c7f93'
assert l['pins_sha256']==art(C/'pins.json')['sha256']=='c43abe7cd5b397be2b069881e88526ebb841240eebecc36f3d6050d1d7df6d63'
assert art(C/'plan.json')['sha256']=='256dc7655b6f6888dae2760d86d62d6b86f4e63662fbc0f1dd24361bbfdc8eb5'
assert l['launch_committed'] and l['start_new_session'] and l['launch_helper_sha256']==art(C/'launch_shifted_diagnostic03.py')['sha256']=='ccc509f25790ed415601135dd8191bca4f6909548553c3592058b0b8825a4fd0'
d=proc(2408283);assert d['start_ticks']==111441604 and d['parent']==1 and d['state']!='Z' and d['argv']==l['argv']==l['observed_argv'] and d['command_sha256']==l['command_sha256']
assert j['status']=='running' and j['physical_evaluations']==j['benchmark_attempts']==0 and not j['release_ready']
assert j['plan']['sha256']==art(C/'plan.json')['sha256'] and j['admission']['boot_id']==boot and not j['admission']['conflicting_processes']
locks=[]
for f in (Path('/proc')/str(d['pid'])/'fd').iterdir():
 try:
  target=os.readlink(f)
  if target==p['global_lock'] or target.endswith('/control/controller.lock'):
   info=(Path('/proc')/str(d['pid'])/'fdinfo'/f.name).read_text();assert 'FLOCK' in info and 'WRITE' in info and str(d['pid']) in info;locks.append({'path':target,'fd':f.name,'fdinfo':info})
 except FileNotFoundError:pass
assert p['global_lock'] in {x['path'] for x in locks}
chain=[d];queue=[d['pid']]
while queue:
 pid=queue.pop(0)
 try:children=(Path('/proc')/str(pid)/'task'/str(pid)/'children').read_text().split()
 except FileNotFoundError:continue
 for x in children:
  try:v=proc(int(x))
  except FileNotFoundError:continue
  assert v['parent']==pid;chain.append(v);queue.append(v['pid'])
actual_workers=[v for v in chain if v['argv'] and (('segmented-qr-' in Path(v['argv'][0]).name) or (len(v['argv'])>1 and Path(v['argv'][0]).name.startswith('python') and v['argv'][1].endswith(('validate_shifted_cuts.py','check_shifted_runtime01.py'))))]
assert all(v['affinity']=='24' for v in actual_workers)
print(json.dumps({'passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'launch':art(C/'shifted-launch.json'),'plan':art(C/'plan.json'),'boot_id':boot,'owned_chain':chain,'held_locks':locks,'pipeline_snapshot':j,'scope':'Live exact detached captured-row diagnostic attribution and shared lock only; no diagnostic completion, new physical propagation or benchmark claim.'},indent=2))
