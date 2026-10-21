#!/usr/bin/env python3
"""Copy only declared compact terminal records; keep native arrays external."""
from pathlib import Path
import hashlib,json,datetime,shutil
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
P=B/'preparation-03';R=B/'validation-04';F=R/'run/preparation/prefixes/753992c25b8ee35f52468f0d4439501f642bc531685eecd44942eac438ba7769';O=P/'failure-capture-01'
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for q in iter(lambda:f.read(1048576),b''):h.update(q)
 return h.hexdigest()
def pin(p):return {'path':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def need(v,m):
 if not v:raise RuntimeError(m)
controller=P/'control/pipeline.json';initial_pin=pin(controller);v=json.loads(controller.read_text())
need(v['status']=='failed_or_blocked' and v['benchmark_attempts']==0 and v['final_cleanup']['verified'] is True,'Expected preserved clean pre-fit failure')
need(not O.exists(),'Fresh capture required')
selected={}
def add(p,rel):
 need(p.is_file() and not p.is_symlink() and p.stat().st_size<3000000,'Noncompact/linked record '+str(p));need(rel not in selected,'Duplicate capture member');selected[rel]=p
for p in sorted((P/'control').iterdir()):
 if p.is_file() and p.suffix in ('.json','.log','.py'):add(p,'control/'+p.name)
for name in ('plan.json','preparation-status.json'):add(R/'run'/name,'run/'+name)
for folder in sorted((R/'run/preparation-jobs').iterdir()):
 need(folder.is_dir() and not folder.is_symlink(),'Unexpected job member')
 for name in ('request.json','execution.json','worker-result.json','supervisor.json','supervisor.plan.json','supervisor.log','worker.log'):
  p=folder/name
  if p.exists():add(p,'jobs/'+folder.name+'/'+name)
for p in sorted((F/'nominal-initialization').rglob('*')):
 if p.is_file() and p.suffix in ('.xml','.log','.json'):add(p,'failed-prefix/'+str(p.relative_to(F)))
add(F/'nominal-initialization/initial_state.txt','failed-prefix/nominal-initialization/initial_state.txt')
for p in sorted((F/'native-prepared').glob('*.xml')):add(p,'failed-prefix/native-prepared/'+p.name)
for name in ('segmented-v4.json','source-freeze.json'):add(R/'control'/name,'identity/'+name)
external=[]
for p in sorted((F/'nominal-initialization').rglob('*')):
 if p.is_file() and p not in selected.values():external.append(pin(p))
sourcefiles=['src/orbit_poc/segmented/multiday.py','src/orbit_poc/comparison/initialization.py','groops/extension/sixStateTangent.h','groops/extension/stagedVariationalBody.h']
sourcepins=[pin(R/'source'/s) for s in sourcefiles]
O.mkdir();files=[]
for rel,p in sorted(selected.items()):
 raw=p.read_bytes();q=O/rel;q.parent.mkdir(parents=True,exist_ok=True)
 with q.open('xb') as f:f.write(raw)
 files.append({'relative_path':rel,'source_path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
need(pin(controller)==initial_pin,'Controller changed during capture')
manifest={'schema':'orbit-poc-segmented-preparation-terminal-failure-capture-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'preserved_failed_preparation','capture_root':str(O),'source_controller':initial_pin,'files':files,'external_not_copied':external,'scientific_source_pins':sourcepins,'benchmark_attempts':0,'scope':'Exact compact evidence of failed preparation; native orbit/variational arrays remain external. No rerun, numerical modification or gate promotion.'}
(O/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
print(json.dumps({'manifest':pin(O/'manifest.json'),'files':len(files),'copied_bytes':sum(x['bytes'] for x in files),'external_files':len(external)}))
