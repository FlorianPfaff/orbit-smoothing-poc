from pathlib import Path
import argparse,hashlib,json,subprocess,time
ap=argparse.ArgumentParser();ap.add_argument('--directory',required=True);ap.add_argument('--request-sha256',required=True);a=ap.parse_args();C=Path(a.directory);request=json.loads((C/'assembly-request05.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
if sha(C/'assembly-request05.json')!=a.request_sha256:raise ValueError('Reviewed assembly request changed')
request_pin={'path':request['host_control']['path']+'/assembly-request05.json','sha256':a.request_sha256}
stage=json.loads((C/'staging-plan.json').read_text())
code=r'''
from pathlib import Path
import fcntl,hashlib,importlib.util,json,subprocess
p=json.loads(REQUEST_JSON);stage=json.loads(STAGE_JSON)
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p):need(pin(p['path'])['sha256']==p['sha256'],'Pin changed '+p['path'])
for r in (REQUEST_PIN,p['helper'],stage['driver'],stage['execution'],p['sealed_result']):check(r)
s=importlib.util.spec_from_file_location('owned',stage['driver']['path']);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(stage['execution']['path'])
H=Path(p['host_control']['path']);receipt_path=H/'assembly-execution01.json';need(not receipt_path.exists(),'Fresh assembly receipt required')
with Path(stage['shared_lock']).open('a') as lock,Path(stage['statistical_lock']).open('rb') as stat:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(stat,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 for r in (REQUEST_PIN,p['helper'],stage['driver'],stage['execution'],p['sealed_result']):check(r)
 argv=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',p['helper']['path'],'--request',REQUEST_PIN['path'],'--sha256',REQUEST_PIN['sha256']]
 env={'PATH':'/usr/bin:/bin','HOME':'/home/florianpfaff','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 r=subprocess.run(argv,cwd=H,env=env,text=True,capture_output=True)
 receipt={'schema':'orbit-poc-direct-campaign-assembly-owned-execution-v1','status':'assembled_metadata' if r.returncode==0 else 'failed','argv':argv,'environment':env,'cwd':str(H),'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'admission':admission,'request':REQUEST_PIN,'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False}
 with receipt_path.open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
 files={}
 for name in ('assembly-request05.json','host-plan.json','launch-pins.json','host-view-plan.json','assembly.json','failure.json','assembly-execution01.json','evidence-extension-result01.json'):
  q=H/name
  if q.exists():files[name]={'pin':pin(q),'text':q.read_text()}
 print(json.dumps({'status':receipt['status'],'receipt':pin(receipt_path),'files':files}))
 if r.returncode:raise SystemExit(r.returncode)
'''
code='REQUEST_JSON='+repr(json.dumps(request))+'\nSTAGE_JSON='+repr(json.dumps(stage))+'\nREQUEST_PIN='+repr(request_pin)+'\n'+code
(C/'remote-assembly01.py').write_text(code);t=time.time();r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','env PYTHONDONTWRITEBYTECODE=1 /usr/bin/taskset -c 32 /usr/bin/python3 -B -'],input=code,text=True,capture_output=True)
(C/'assembly.stdout.json').write_text(r.stdout);(C/'assembly.stderr.log').write_text(r.stderr);(C/'assembly-process.json').write_text(json.dumps({'returncode':r.returncode,'elapsed_seconds':time.time()-t,'script_sha256':hashlib.sha256(code.encode()).hexdigest()},indent=2)+'\n')
if r.stdout:
 v=json.loads(r.stdout);out=C/'actual-readback';out.mkdir()
 for name,row in v['files'].items():
  (out/name).write_text(row['text'])
  if sha(out/name)!=row['pin']['sha256']:raise ValueError('Readback changed')
 print(json.dumps({'status':v['status'],'receipt':v['receipt'],'files':{k:q['pin'] for k,q in v['files'].items()}}))
if r.returncode:print(r.stderr);raise SystemExit(r.returncode)
