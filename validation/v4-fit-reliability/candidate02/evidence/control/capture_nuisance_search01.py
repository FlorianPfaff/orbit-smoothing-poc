from pathlib import Path
import json,hashlib,datetime
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes();assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
m=json.loads(b);items=[]
for a in m['attempts']:
 d=r/'attempts'/a['attempt_id']
 if not(d/'result-record.json').is_file():continue
 for p in sorted(d.glob('point-*')):
  if not p.is_dir():continue
  for f in sorted(p.glob('qr.*.nuisance_line_search.json')):
   assert f.stat().st_size<1024**2
   raw=f.read_bytes();items.append({'attempt_id':a['attempt_id'],'point':p.name,'name':f.name,'path':str(f),'sha256':hashlib.sha256(raw).hexdigest(),'content':json.loads(raw)})
print(json.dumps({'schema':'v4-nuisance-search-evidence-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'records':items}))
