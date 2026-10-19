from pathlib import Path
import json,hashlib,subprocess,time
C=Path('/mnt/d/orbit-segmented-v4/control');O=C/'direct-sealing06-execution01'
code=r'''
from pathlib import Path
import fcntl,hashlib,importlib.util,json,os,signal,time,traceback
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p,h):need(pin(p)['sha256']==h,'Pin changed: '+str(p))
def write(p,v):
 with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');c=B/'fit-seal-control-07';out=B/'direct-sealing-execution-06'
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd')
execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
view=c/'readonly-view-plan06.json';check(view,'489f4752ab6129496ff2e61ee8d5f5f524cc9f140f4f7fe8878095a68f383e99')
wrapper=c/'with_completed_preparation_direct02.py';check(wrapper,'e2d6532cb90e91694aca103e9541e5450ff7c589c62a9982fc6970e3f0f674e1')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,d.interrupted)
lock=Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock')
with lock.open('a') as f,(B/'validation-07/run/.segmented.lock').open('rb') as st:
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(st,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 need(not out.exists() and not (c/'sealed-inputs-04').exists(),'Fresh execution/output required');out.mkdir()
 argv=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(wrapper),'--plan',str(view),'--sha256',pin(view)['sha256']]
 env={'PATH':'/usr/bin:/bin','HOME':'/home/florianpfaff','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 receipt={'schema':'orbit-poc-direct-sealing-owned-execution-v1','status':'running','view':pin(view),'wrapper':pin(wrapper),'execution':pin(execution),'admission':admission,'argv':argv,'environment':env,'cwd':str(c),'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False}
 write(out/'launch.json',receipt);registry=[];finish={}
 def started(pid):write(out/'started.json',{'pid':pid,'identity':d.proc(pid),'started_at':d.stamp()})
 def finished(v):finish.update(v)
 try:
  with (out/'sealing.log').open('x') as log:
   result=d.supervise(argv,cwd=c,env=env,log=log,limit=1800,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
  receipt.update(returncode=result,**finish);need(result==0,'Metadata sealer failed')
  need(finish['cleanup']['verified'] and not finish['interrupted_or_timeout'],'Cleanup incomplete')
  receipt.update(status='sealed_metadata',result=pin(c/'sealed-inputs-04/result.json'))
 except BaseException as error:
  receipt.update(status='failed',error=repr(error),traceback=traceback.format_exc(),**finish)
 finally:
  receipt['finished_at']=d.stamp();receipt['log']=pin(out/'sealing.log');write(out/'execution.json',receipt)
 print(json.dumps({'status':receipt['status'],'execution':pin(out/'execution.json'),'receipt':receipt}))
 if receipt['status']!='sealed_metadata':raise SystemExit(1)
'''
def main():
 O.mkdir();(O/'remote-run.py').write_text(code)
 start=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
 (O/'stdout.json').write_text(r.stdout);(O/'stderr.log').write_text(r.stderr)
 (O/'process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
 print(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-start}))
 if r.stdout:
  v=json.loads(r.stdout);print(json.dumps({'status':v['status'],'execution':v['execution']}))
 if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
if __name__=='__main__':main()
