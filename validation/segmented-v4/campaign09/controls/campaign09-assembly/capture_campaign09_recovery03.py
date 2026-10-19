from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');O=C/'campaign09-recovery-readback03'
code=r"""
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
"""
O.mkdir();start=time.time()
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/taskset -c 32 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(O/'capture-command.py').write_text(code);(O/'capture-stderr.log').write_text(r.stderr)
if r.returncode:raise RuntimeError(r.stderr)
v=json.loads(r.stdout)
for row in v['manifest']['files']:
 p=O/row['relative_path'];p.parent.mkdir(parents=True,exist_ok=True);data=base64.b64decode(v['payload'][row['relative_path']]);
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Capture mismatch')
 p.write_bytes(data)
(O/'manifest.json').write_text(json.dumps(v['manifest'],indent=2,sort_keys=True)+'\n')
receipt={'returncode':r.returncode,'elapsed_seconds':time.time()-start,'manifest_sha256':hashlib.sha256((O/'manifest.json').read_bytes()).hexdigest(),'files':len(v['manifest']['files']),'bytes':sum(x['bytes'] for x in v['manifest']['files'])}
(O/'capture-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
