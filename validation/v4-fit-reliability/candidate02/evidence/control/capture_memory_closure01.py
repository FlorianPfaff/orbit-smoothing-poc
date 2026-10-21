from pathlib import Path
import json,hashlib,datetime
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes();assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
m=json.loads(b);out=[]
for a in m['attempts']:
 d=r/'attempts'/a['attempt_id'];rec=d/'result-record.json'
 if not rec.is_file() or json.loads(rec.read_text())['status']!='memory_limit':continue
 row={'attempt_id':a['attempt_id'],'directories':[],'json':{}}
 point=d/'point-001-initial'
 for f in point.glob('qr.*.profile.json'):
  if f.stat().st_size<131072:row['json'][f.name]=json.loads(f.read_text())
 for p in sorted(point.glob('closure-*')):
  if not p.is_dir():continue
  item={'name':p.name,'files':[{'name':f.name,'bytes':f.stat().st_size} for f in p.iterdir() if f.is_file()],'logs':{}}
  for name in ['propagate.log','propagate.execution.json','derivatives.json']:
   f=p/name
   if not f.is_file():continue
   size=f.stat().st_size
   with f.open('rb') as inp:head=inp.read(4096);inp.seek(max(0,size-12000));tail=inp.read(12000)
   item['logs'][name]={'bytes':size,'head':head.decode(errors='replace'),'tail':tail.decode(errors='replace')}
  row['directories'].append(item)
 out.append(row)
print(json.dumps({'schema':'v4-memory-closure-details-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attempts':out}))
