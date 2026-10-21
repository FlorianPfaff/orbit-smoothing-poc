from pathlib import Path
import argparse,base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control')
a=argparse.ArgumentParser();a.add_argument('--label',required=True);x=a.parse_args()
if not x.label.isalnum():raise ValueError('Simple fresh label required')
O=C/('campaign09-transition-'+x.label)
code=r'''
from pathlib import Path
import base64,datetime,hashlib,json,os,stat
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');H=B/'fit-campaign-control-09';T=B/'validation-07/temporary/fit-private/campaign-control'
def check(v,m):
 if not v:raise ValueError(m)
def sha(b):return hashlib.sha256(b).hexdigest()
check(sha((H/'host-plan.json').read_bytes())=='c545c3d958fc3ab68cc3ce721fd257bf4981fa90b2138d21f0702c02504e938b','Host plan changed')
files=[];payload={};missing=[]
for name,p in [('campaign-launch.json',H/'campaign-launch.json'),('prelaunch-probe.json',T/'prelaunch-probe.json'),('prefix-before.json',T/'prefix-before.json')]:
 if not p.exists():missing.append(str(p));continue
 s=p.stat();check(stat.S_ISREG(s.st_mode) and not p.is_symlink() and s.st_size<8*1024*1024,'Unexpected transition file');data=p.read_bytes();t=p.stat();check((s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)==(t.st_dev,t.st_ino,t.st_size,t.st_mtime_ns),'Transition file changed while captured');json.loads(data);files.append({'path':str(p),'relative_path':name,'sha256':sha(data),'bytes':len(data)});payload[name]=base64.b64encode(data).decode()
log=H/'workload.log';records=[]
if log.exists():
 with log.open('rb') as f:
  for i in range(2):
   raw=f.readline(262145)
   if not raw:break
   check(len(raw)<=262144 and raw.endswith(b'\n'),'Bounded header incomplete');v=json.loads(raw);check(v.get('schema') in ('orbit-poc-segmented-fit-namespace-exec-v1','orbit-poc-private-dev-bootstrap-result-v1'),'Unexpected header schema '+str(v.get('schema')));name='workload-header-'+str(i+1)+'.json';files.append({'path':str(log),'relative_path':name,'sha256':sha(raw),'bytes':len(raw),'scope':'Exact bounded header line; growing log not hashed'});payload[name]=base64.b64encode(raw).decode();records.append(v)
print(json.dumps({'manifest':{'schema':'orbit-poc-campaign09-transition-capture-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host_plan_sha256':'c545c3d958fc3ab68cc3ce721fd257bf4981fa90b2138d21f0702c02504e938b','files':files,'missing':missing,'header_count':len(records),'no_growing_log_hash':True},'payload':payload}))
'''
O.mkdir();(O/'capture-command.py').write_text(code);start=time.monotonic()
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/taskset -c 32 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(O/'stderr.log').write_text(r.stderr)
if r.returncode:(O/'stdout.log').write_text(r.stdout);raise RuntimeError(r.stderr)
v=json.loads(r.stdout)
for row in v['manifest']['files']:
 data=base64.b64decode(v['payload'][row['relative_path']]);
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Capture mismatch')
 (O/row['relative_path']).write_bytes(data)
(O/'manifest.json').write_text(json.dumps(v['manifest'],indent=2,sort_keys=True)+'\n')
print(json.dumps({'path':str(O),'elapsed_seconds':time.monotonic()-start,'manifest_sha256':hashlib.sha256((O/'manifest.json').read_bytes()).hexdigest(),'files':len(v['manifest']['files']),'missing':v['manifest']['missing'],'header_count':v['manifest']['header_count']}))
