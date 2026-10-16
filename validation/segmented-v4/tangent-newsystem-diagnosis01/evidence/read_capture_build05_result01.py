from pathlib import Path
import json,hashlib,datetime
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-capture-05';C=D/'control'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
 raw=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'value':json.loads(raw)}
p=read(C/'pipeline.json');r=read(D/'run/build-result/result.json');launch=read(C/'capture-build-launch.json')
assert p['value']['status']=='passed_diagnostic' and p['value']['returncode']==0 and p['value']['final_cleanup']['verified'] and not p['value']['final_cleanup']['errors']
assert r['value']['status']=='built_diagnostic_only' and r['value']['baseline_relinked_sha256']=='eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'
for key in ('native','reader'):assert sha(r['value'][key]['path'])==r['value'][key]['sha256']
identities={}
def walk(x):
 if isinstance(x,dict):
  if isinstance(x.get('pid'),int) and 'start_ticks'in x:identities[(x['pid'],x['start_ticks'])]=x
  for v in x.values():walk(v)
 elif isinstance(x,list):
  for v in x:walk(v)
walk(p['value']);walk(launch['value']);current=[]
for (pid,start),identity in sorted(identities.items()):
 path=Path('/proc')/str(pid)/'stat';actual=None
 try:
  fields=path.read_text().rsplit(')',1)[1].strip().split();actual={'start_ticks':int(fields[19]),'state':fields[0]}
 except FileNotFoundError:pass
 current.append({'pid':pid,'expected_start_ticks':start,'current':actual,'same_live_identity':actual is not None and actual['start_ticks']==start and actual['state']!='Z'})
assert not any(x['same_live_identity']for x in current)
print(json.dumps({'schema':'independent-capture-build05-terminal-readback-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'pipeline':p,'result':r,'launch':launch,'owned_identity_checks':current,'scientific_workloads_launched':0},indent=2))
