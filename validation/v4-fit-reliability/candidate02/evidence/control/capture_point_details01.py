from pathlib import Path
import json,hashlib,datetime
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes();assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
m=json.loads(b);out=[]
def js(p):
 if not p.is_file():return None
 size=p.stat().st_size
 if size>512*1024:return {'path':str(p),'bytes':size,'omitted':'size bound'}
 raw=p.read_bytes();return {'path':str(p),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'content':json.loads(raw)}
def lg(p):
 if not p.is_file():return None
 size=p.stat().st_size
 with p.open('rb') as f:
  head=f.read(4096);f.seek(max(0,size-16000));tail=f.read(16000)
 return {'path':str(p),'bytes':size,'head':head.decode(errors='replace'),'tail':tail.decode(errors='replace')}
for a in m['attempts']:
 d=r/'attempts'/a['attempt_id']
 if not (d/'result-record.json').is_file():continue
 row={'attempt_id':a['attempt_id'],'points':[]}
 for p in sorted(d.glob('point-*')):
  if not p.is_dir():continue
  item={'point':p.name,'files':[],'json':{},'logs':{}}
  for f in p.iterdir():
   if f.is_file():item['files'].append({'name':f.name,'bytes':f.stat().st_size})
  for name in ['profile.execution.json','qr.profile.json','closure.json','timing.json']:
   v=js(p/name)
   if v:item['json'][name]=v
  for name in ['profile.log','propagate.log','closure.log']:
   v=lg(p/name)
   if v:item['logs'][name]=v
  row['points'].append(item)
 out.append(row)
print(json.dumps({'schema':'v4-terminal-point-details-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'manifest_hash':m['manifest_hash'],'attempts':out}))
