from pathlib import Path
import base64,hashlib,json,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');P=C/'bwrap-cap-validation-packet02';O=C/'bwrap-cap-validation-execution02'
files={'prior-build-manifest.json':C/'bwrap-cap-build-terminal01/manifest.json','validate_existing.py':P/'validate_existing.py','validation-plan.json':P/'validation-plan.json'}
payload={n:{'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'data':base64.b64encode(p.read_bytes()).decode()} for n,p in files.items()}
code=r'''
from pathlib import Path
import base64,fcntl,hashlib,importlib.util,json,signal,time,traceback
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p,h):need(pin(p)['sha256']==h,'Pin changed '+str(p))
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');i=B/'bwrap-cap-validation-inputs02';out=B/'bwrap-cap-validation-02'
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd')
execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,d.interrupted)
with Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock').open('a') as lock,(B/'validation-07/run/.segmented.lock').open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 need(not i.exists() and not out.exists(),'Fresh build namespaces required');i.mkdir();out.mkdir()
 for name,row in PAYLOAD.items():
  need(Path(name).name==name,'Unexpected payload name');data=base64.b64decode(row['data']);need(hashlib.sha256(data).hexdigest()==row['sha256'],'Transport mismatch')
  with (i/name).open('xb') as f:f.write(data)
 argv=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(i/'validate_existing.py'),'--plan',str(i/'validation-plan.json'),'--sha256',PAYLOAD['validation-plan.json']['sha256']]
 env={'PATH':'/usr/bin:/bin','HOME':str(out),'PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 receipt={'schema':'orbit-poc-bwrap-cap-owned-validation-v1','status':'running','admission':admission,'argv':argv,'environment':env,'cwd':str(out),'inputs':{n:pin(i/n) for n in PAYLOAD},'scientific_native_executions':0,'fit_attempts':0};write(out/'launch.json',receipt);registry=[];finish={}
 def started(pid):write(out/'started.json',{'identity':d.proc(pid),'started_at':d.stamp()})
 def finished(v):finish.update(v)
 try:
  with (out/'validation.log').open('x') as log:result=d.supervise(argv,cwd=out,env=env,log=log,limit=1800,guard_live=lambda:None,on_started=started,on_finished=finished,registry=registry)
  receipt.update(returncode=result,**finish);need(result==0 and finish['cleanup']['verified'] and not finish['interrupted_or_timeout'],'Build/regression failed')
  receipt.update(status='passed',result=pin(out/'result.json'))
 except BaseException as error:receipt.update(status='failed',error=repr(error),traceback=traceback.format_exc(),**finish)
 finally:
  receipt['finished_at']=d.stamp();receipt['log']=pin(out/'validation.log');write(out/'execution.json',receipt)
 print(json.dumps({'status':receipt['status'],'execution':pin(out/'execution.json'),'receipt':receipt}))
 if receipt['status']!='passed':raise SystemExit(1)
'''
code='PAYLOAD='+repr(payload)+'\n'+code
def main():
 O.mkdir();(O/'remote-run.py').write_text(code);t=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
 (O/'stdout.json').write_text(r.stdout);(O/'stderr.log').write_text(r.stderr);(O/'process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-t,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
 print(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-t}))
 if r.stdout:
  v=json.loads(r.stdout);print(json.dumps({'status':v['status'],'execution':v['execution']}))
 if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
if __name__=='__main__':main()
