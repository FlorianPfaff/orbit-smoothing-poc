#!/usr/bin/env python3
from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control/direct-fit-helper-install12')
def sha(data):return hashlib.sha256(data).hexdigest()
plan=(C/'install-plan.json').read_bytes();archive=(C/'helpers-and-request.tar').read_bytes();inventory=(C/'preserved-control-inventory01.json').read_bytes()
for data,h in [(plan,'9ff6d42017cea589d41bdb142f72ecc28b9686ebed42a7aae8df1dbeb5471fb8'),(archive,'dd28181c2129514b3d7c5eab96b69e727dbdde192416363567782acd0abab0c2'),(inventory,'bc0192a0c59fd26e50eb03eabc7b67e4444aaa787c63bb4fcbe2db69bbffe50d')]:
 if sha(data)!=h:raise ValueError('Local packet changed')
code=r'''
from pathlib import Path
import base64,datetime,fcntl,hashlib,importlib.util,io,json,os,stat,tarfile,traceback
def need(ok,msg):
 if not ok:raise ValueError(msg)
def sha(data):return hashlib.sha256(data).hexdigest()
def pin(q):return {'path':str(q),'sha256':sha(q.read_bytes())}
def check(row):
 q=Path(row['path']);need(q.is_file() and sha(q.read_bytes())==row['sha256'],'Changed pinned file: '+str(q));return q
def write(q,data):
 with q.open('xb') as f:f.write(data)
 os.chmod(q,0o644)
def dump(v):return (json.dumps(v,indent=2,sort_keys=True)+'\n').encode()
plan=base64.b64decode(PLAN);archive=base64.b64decode(ARCHIVE);inventory=base64.b64decode(INVENTORY)
need(sha(plan)=='9ff6d42017cea589d41bdb142f72ecc28b9686ebed42a7aae8df1dbeb5471fb8','Plan changed');p=json.loads(plan)
need(sha(archive)==p['archive']['sha256'] and sha(inventory)==p['preserved_inventory']['sha256'],'Packet changed');saved=json.loads(inventory)
need(p['schema']=='orbit-poc-direct-fit-helper-install-plan-v2','Plan schema')
control=Path(p['control']['path']);root=Path(p['fresh_install_root'])
spec=importlib.util.spec_from_file_location('owned',check(p['driver']));d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d);e=d.load_execution(check(p['execution']))
need(saved['root']==str(control) and saved['fit_attempts']==saved['temporary_entries']==0,'Preserved inventory scope')
rows={r['name']:r for r in p['files']};payload={}
with tarfile.open(fileobj=io.BytesIO(archive),mode='r:') as t:
 members=t.getmembers();need(len(members)==len(rows)==5 and set(rows)=={m.name for m in members},'Archive membership')
 for m in members:
  r=rows[m.name];need(m.isfile() and '/' not in m.name and m.name not in ('.','..') and m.mode==r['mode']==0o644 and m.size==r['bytes'],'Unsafe archive member')
  data=t.extractfile(m).read();need(sha(data)==r['sha256'],'Member hash');need(str(control/m.name)==r['target'],'Target mismatch');payload[m.name]=data
def inventory_check(extra=()):
 for row in saved['entries']:
  q=Path(row['path']);s=q.lstat();need((s.st_dev,s.st_ino,stat.S_IMODE(s.st_mode))==(row['device'],row['inode'],row['mode']),'Metadata identity changed: '+str(q))
  if row['kind']=='directory':
   need(stat.S_ISDIR(s.st_mode),'Directory type changed');expected=sorted(row['children']+list(extra)) if q==control else row['children'];need(sorted(x.name for x in q.iterdir())==expected,'Directory membership changed: '+str(q))
  elif row['kind']=='symlink':need(stat.S_ISLNK(s.st_mode) and os.readlink(q)==row['target'],'Link changed')
  elif row['kind']=='file':need(stat.S_ISREG(s.st_mode) and s.st_size==row['bytes'],'File type/size changed');check(row)
  else:raise ValueError('Unsupported preserved entry')
def empty(stage):
 for k in ('attempts','temporary'):
  q=Path(stage[k]['path']);s=q.lstat();need(stat.S_ISDIR(s.st_mode) and (s.st_dev,s.st_ino)==(stage[k]['device'],stage[k]['inode']) and not any(q.iterdir()),'Fit directory changed')
def failures():
 for row in p['preserved_campaign_captures']:check(row)
 for smoke in p['preserved_smokes']:
  for row in smoke['files']:check(row)
  row=next(r for r in smoke['files'] if r['relative_path']=='execution/execution.json');v=json.loads(check(row).read_text())
  need(v['status']=='failed' and v['fit_attempts']==0 and v['cleanup']['verified'] and not v['cleanup']['live_owned_processes'],'Prior smoke not terminal/clean')
  for old in v['cleanup']['identities']:
   try:live=d.proc(old['pid'])
   except (FileNotFoundError,ProcessLookupError):live=None
   need(not live or live['start_ticks']!=old['start_ticks'] or live['state']=='Z','Prior smoke process live')
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock, (control.parent/'validation-07/run/.segmented.lock').open('rb') as slock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(slock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 admission=d.admission(e)
 os.sched_setaffinity(0,{32})
 need(not root.exists() and not root.is_symlink(),'Fresh install root required')
 inventory_check();stage=json.loads((control/'result.json').read_text());need(stage['control']==p['control'] and stage['status']=='staged_metadata','Stage identity');empty(stage);failures()
 for name in payload:need(not (control/name).exists() and not (control/name).is_symlink(),'Fresh target required')
 root.mkdir();v={'schema':'orbit-poc-direct-fit-helper-install-result-v2','status':'running','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'control':p['control'],'admission':admission,'affinity':sorted(os.sched_getaffinity(0)),'installed':[],'fit_attempts':0,'native_executions':0,'fit_execution_authorized':False}
 try:
  write(root/'install-plan.json',plan);write(root/'helpers-and-request.tar',archive);write(root/'preserved-control-inventory.json',inventory)
  for name,data in payload.items():
   q=control/name;write(q,data);need(pin(q)['sha256']==rows[name]['sha256'],'Installed hash');v['installed'].append({**pin(q),'bytes':q.stat().st_size,'mode':stat.S_IMODE(q.stat().st_mode)})
  inventory_check(payload);empty(stage);failures();check(p['driver']);check(p['execution'])
  v.update(status='installed_metadata',preserved_inventory_sha256=sha(inventory),preserved_entries=len(saved['entries']),preserved_failures=True,empty_writables_after=True)
 except BaseException as error:v.update(status='failed',error=repr(error),traceback=traceback.format_exc())
 v['finished_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();write(root/'install-result.json',dump(v));print(json.dumps({'result':v,'result_pin':pin(root/'install-result.json')}))
 need(v['status']=='installed_metadata','Metadata install failed')
'''
code='PLAN='+repr(base64.b64encode(plan).decode())+'\nARCHIVE='+repr(base64.b64encode(archive).decode())+'\nINVENTORY='+repr(base64.b64encode(inventory).decode())+'\n'+code
for n in ['remote-install01.py','install01.stdout.json','install01.stderr.log','install01-process.json','install01-result.json']:
 if (C/n).exists():raise ValueError('Fresh local receipt required: '+n)
(C/'remote-install01.py').write_text(code);start=time.time()
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env HOME=/home/florianpfaff PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(C/'install01.stdout.json').write_text(r.stdout);(C/'install01.stderr.log').write_text(r.stderr)
process={'returncode':r.returncode,'wall_seconds':time.time()-start,'script_sha256':sha(code.encode()),'native_executions':0,'fit_attempts':0};(C/'install01-process.json').write_text(json.dumps(process,indent=2)+'\n');print(json.dumps(process))
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
v=json.loads(r.stdout);(C/'install01-result.json').write_text(json.dumps(v,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':v['result']['status'],'result_pin':v['result_pin']}))
