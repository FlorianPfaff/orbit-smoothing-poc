
from pathlib import Path
import base64,datetime,hashlib,json,stat
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');A=B/'validation-07/run/attempts/leo500-quiet-normal-groops_pulses-24h--dense_corrected'
files=[];payload={}
for name,expected in [('request.json','0fd71929a448587a00574216c3ebc79b9453de314beb989b9c8d4b32d333bbf1'),('supervisor.plan.json','1eff35e3e66653ac42ab80c8c588b34d9ee8055d63627d8202b44d8959af2531'),('point-001-initial/profile.xml',None)]:
 p=A/name;s=p.stat()
 if p.is_symlink() or not stat.S_ISREG(s.st_mode) or s.st_size>1024*1024:raise ValueError('Unexpected immutable attempt artifact')
 data=p.read_bytes();t=p.stat();h=hashlib.sha256(data).hexdigest()
 if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns):raise ValueError('Attempt artifact changed during capture')
 if expected is not None and h!=expected:raise ValueError('Attempt artifact identity differs')
 files.append({'path':str(p),'relative_path':name,'sha256':h,'bytes':len(data),'device':s.st_dev,'inode':s.st_ino});payload[name]=base64.b64encode(data).decode()
print(json.dumps({'manifest':{'schema':'orbit-poc-campaign09-first-attempt-immutable-capture-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attempt_id':A.name,'frozen_manifest':{'path':str(B/'validation-07/run/manifest.json'),'sha256':'4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6','manifest_hash':'63f3010564c6da76c0f92a007ed1fbe057d610d44cccb6b5e4f509afafbf2251','identity_source':'Previously verified actual snapshot05; manifest not rehashed during this bounded capture'},'files':files,'scope':'Only three immutable first-attempt request/control artifacts; no native executable or growing log read'},'payload':payload}))
