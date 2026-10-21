from pathlib import Path
import base64,hashlib,json,subprocess
C=Path('/mnt/d/orbit-segmented-v4/control');source=C/'public-verifier-closure-census01/summary01.json';data=source.read_bytes();digest='1cf15d472fb1f1cc9e7f89e0b434a2011a34f2a47984fefb151280027ca3da12'
if hashlib.sha256(data).hexdigest()!=digest:raise ValueError('Exact independently audited census summary changed')
code=r'''
from pathlib import Path
import base64,datetime,fcntl,hashlib,importlib.util,json,os
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');out=B/'normalization-support-census-01'
def need(v,m):
 if not v:raise ValueError(m)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p,h):need(sha(p)==h,'Changed pin '+str(p))
def write(p,data):
 with p.open('xb') as f:f.write(data)
body=base64.b64decode(DATA);need(hashlib.sha256(body).hexdigest()==DIGEST,'Transport changed')
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd');execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e);os.sched_setaffinity(0,{32})
 terminal=B/'direct-sealing-execution-06/execution.json';v=json.loads(terminal.read_text());need(v['status']=='sealed_metadata' and v['cleanup']['verified'] and not v['cleanup']['live_owned_processes'],'Successful terminal seal cleanup required')
 for old in v['cleanup']['identities']:
  try:now=d.proc(old['pid'])
  except (FileNotFoundError,ProcessLookupError):now=None
  need(not now or now['start_ticks']!=old['start_ticks'] or now['state']=='Z','Seal process remains live')
 need(not out.exists() and not out.is_symlink(),'Fresh census evidence directory required')
 for q in (B/'validation-07/run/attempts',B/'validation-07/temporary/fit-private'):need(q.is_dir() and not q.is_symlink() and not any(q.iterdir()),'Fit boundary changed')
 out.mkdir();write(out/'census.json',body);check(out/'census.json',DIGEST)
 receipt={'schema':'orbit-poc-normalization-census-metadata-stage-v1','status':'staged_exact_metadata','source':{'path':SOURCE,'sha256':DIGEST},'target':{'path':str(out/'census.json'),'sha256':DIGEST},'bytes':len(body),'control':{'path':str(out),'device':out.stat().st_dev,'inode':out.stat().st_ino},'admission':admission,'affinity':sorted(os.sched_getaffinity(0)),'seal_execution':{'path':str(terminal),'sha256':sha(terminal)},'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'fit_attempts':0,'native_executions':0,'empty_writables':True}
 write(out/'staging.json',(json.dumps(receipt,indent=2,sort_keys=True)+'\n').encode());print(json.dumps({'receipt':receipt,'receipt_pin':{'path':str(out/'staging.json'),'sha256':sha(out/'staging.json')}}))
'''
code='DATA='+repr(base64.b64encode(data).decode())+'\nDIGEST='+repr(digest)+'\nSOURCE='+repr(str(source))+'\n'+code
out=C/'normalization-census-stage01';out.mkdir();(out/'remote-stage.py').write_text(code)
r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env HOME=/home/florianpfaff PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(out/'stdout.json').write_text(r.stdout);(out/'stderr.log').write_text(r.stderr);(out/'process.json').write_text(json.dumps({'returncode':r.returncode,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
if r.returncode:raise RuntimeError(r.stderr)
v=json.loads(r.stdout);(out/'result.json').write_text(json.dumps(v,indent=2,sort_keys=True)+'\n');print(json.dumps({'status':v['receipt']['status'],'target':v['receipt']['target'],'receipt':v['receipt_pin']}))
