from pathlib import Path
import json,hashlib,datetime
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes()
assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
m=json.loads(b)
items=[]
def read(p,limit=3*1024**2):
 if not p.is_file():return None
 n=p.stat().st_size
 if n>limit:return {'path':str(p),'bytes':n,'omitted':'size limit'}
 b=p.read_bytes();return {'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'content':json.loads(b)}
for a in m['attempts']:
 p=r/'attempts'/a['attempt_id']; rec=read(p/'result-record.json')
 if rec is None:continue
 row={'attempt':a,'record':rec,'result':read(p/'result.json'),'top_entries':sorted(f.name for f in p.iterdir())}
 for name in ['supervisor.json','resource.json','resources.json','execution.json']:
  v=read(p/name)
  if v:row[name]=v
 row['log_tails']={}
 for name in ['worker.log','stderr.log','stdout.log','fit.log']:
  f=p/name
  if f.is_file():
   with f.open('rb') as inp:inp.seek(max(0,f.stat().st_size-16384));tail=inp.read(16384)
   row['log_tails'][name]={'bytes':f.stat().st_size,'tail':tail.decode(errors='replace')}
 items.append(row)
print(json.dumps({'schema':'v4-terminal-readonly-detail-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'manifest_hash':m['manifest_hash'],'attempts':items}))
