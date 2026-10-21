from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');P=C/'campaign08-recovery-packet01';O=C/'campaign08-recovery-execution01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
if sha(P/'staging-plan.json')!='7f5cb501095f545b4ccb1daa4a5463e4406b69d16eab04387ea8b0069e5513f2':raise ValueError('Staging plan changed')
plan=json.loads((P/'staging-plan.json').read_text());payload={}
for row in plan['files']:
 data=Path(row['local']).read_bytes()
 if hashlib.sha256(data).hexdigest()!=row['sha256']:raise ValueError('Payload changed')
 payload[row['target']]={'data':base64.b64encode(data).decode(),'sha256':row['sha256']}
code=r'''
from pathlib import Path
import base64,fcntl,hashlib,importlib.util,json,os,signal,time,traceback
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');H=B/'fit-campaign-control-08';out=B/'campaign08-recovery-execution01'
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p,h):need(pin(p)['sha256']==h,'Pin changed '+str(p))
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd')
execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,d.interrupted)
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 need(PLAN['control']=={'path':str(H),'device':2048,'inode':239602380},'Control identity request changed')
 st=H.stat();need(H.is_dir() and not H.is_symlink() and H.resolve()==H and (st.st_dev,st.st_ino)==(2048,239602380) and not any(H.iterdir()),'Fresh control identity/membership changed')
 parent=Path(PLAN['wrapper_parent']);need(parent==B/'bwrap-cap-01/controls' and parent.parent.resolve()==parent.parent,'Wrapper parent changed')
 need(not parent.exists() and not parent.is_symlink(),'Wrapper control directory already exists')
 need(not out.exists() and not out.is_symlink(),'Execution namespace exists')
 need(set(PAYLOAD)=={row['target'] for row in PLAN['files']},'Payload membership changed')
 for path,row in PAYLOAD.items():
  p=Path(path);need(p.parent==H or p==parent/'with_segmented_fit_namespace03.py','Unexpected target');need(not p.exists() and not p.is_symlink(),'Preserve existing target');data=base64.b64decode(row['data']);need(hashlib.sha256(data).hexdigest()==row['sha256'],'Transport mismatch')
 check(B/'bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384','7983e8f9ac3c68f072b4ea7884f4d3ce87c2086a1198412649663614113fc3f4')
 out.mkdir();parent.mkdir()
 for path,row in PAYLOAD.items():
  with Path(path).open('xb') as f:f.write(base64.b64decode(row['data']))
 for path,row in PAYLOAD.items():check(path,row['sha256'])
 staging={'schema':'orbit-poc-campaign08-recovery-staged-v1','admission':admission,'control':PLAN['control'],'wrapper_parent':{'path':str(parent),'device':parent.stat().st_dev,'inode':parent.stat().st_ino},'payload':{p:pin(p) for p in PAYLOAD},'staged_at':d.stamp(),'fit_attempts':0,'scientific_native_executions':0};write(out/'staging.json',staging)
 request=PLAN['request'];check(request['path'],request['sha256']);argv=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(H/'derive_campaign08_transport02.py'),'--request',request['path'],'--sha256',request['sha256']]
 env={'PATH':'/usr/bin:/bin','HOME':'/home/florianpfaff','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 receipt={'schema':'orbit-poc-campaign08-recovery-owned-execution-v1','status':'running','admission':admission,'argv':argv,'environment':env,'cwd':str(H),'staging':pin(out/'staging.json'),'fit_attempts':0,'scientific_native_executions':0};write(out/'launch.json',receipt);registry=[];finish={}
 def started(pid):write(out/'started.json',{'identity':d.proc(pid),'started_at':d.stamp()})
 def finished(v):finish.update(v)
 try:
  with (out/'recovery.log').open('x') as log:result=d.supervise(argv,cwd=H,env=env,log=log,limit=1800,guard_live=lambda:None,on_started=started,on_finished=finished,registry=registry)
  receipt.update(returncode=result,**finish);need(result==0 and finish['cleanup']['verified'] and not finish['interrupted_or_timeout'],'Metadata recovery failed')
  for path,row in PAYLOAD.items():check(path,row['sha256'])
  receipt.update(status='assembled_metadata',result=pin(H/'recovery.json'))
 except BaseException as error:receipt.update(status='failed',error=repr(error),traceback=traceback.format_exc(),**finish)
 finally:
  receipt['finished_at']=d.stamp();receipt['log']=pin(out/'recovery.log');write(out/'execution.json',receipt)
 print(json.dumps({'status':receipt['status'],'execution':pin(out/'execution.json'),'receipt':receipt}))
 if receipt['status']!='assembled_metadata':raise SystemExit(1)
'''
code='PLAN='+repr(plan)+'\nPAYLOAD='+repr(payload)+'\n'+code
O.mkdir();(O/'remote-run.py').write_text(code);start=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(O/'stdout.json').write_text(r.stdout);(O/'stderr.log').write_text(r.stderr);(O/'process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
print(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start}))
if r.stdout:
 v=json.loads(r.stdout);print(json.dumps({'status':v['status'],'execution':v['execution']}))
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
