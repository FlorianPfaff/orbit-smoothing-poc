
from pathlib import Path
import base64,hashlib,json,os,stat
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');roots={'execution':B/'campaign09-recovery-execution03','control':B/'fit-campaign-control-09'}
e=json.loads((roots['execution']/'execution.json').read_text())
if e['status'] not in ('assembled_metadata','failed'):raise ValueError('Capture requires terminal assembly')
files=[];payload={}
for name,root in roots.items():
 for p in sorted(root.rglob('*')):
  s=p.lstat()
  if stat.S_ISDIR(s.st_mode):continue
  if not stat.S_ISREG(s.st_mode):raise ValueError('Unexpected capture object '+str(p))
  data=p.read_bytes();t=p.stat()
  if (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)!=(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns):raise ValueError('Capture changed '+str(p))
  rel=name+'/'+str(p.relative_to(root));files.append({'path':str(p),'relative_path':rel,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'mode':stat.S_IMODE(s.st_mode)});payload[rel]=base64.b64encode(data).decode()
print(json.dumps({'manifest':{'schema':'orbit-poc-campaign09-recovery-readback-v1','status':e['status'],'fit_attempts':0,'files':files},'payload':payload}))
