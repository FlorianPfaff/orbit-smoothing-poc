
from pathlib import Path
import fcntl,hashlib,importlib.util,json,os,subprocess
def need(v,m):
 if not v:raise ValueError(m)
def pin(p):return {'path':str(p),'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}
def check(p,h):need(pin(p)['sha256']==h,'Pin changed: '+str(p))
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');c=B/'fit-seal-control-07'
driver=B/'validation-07/control/owned_driver09.py';check(driver,'72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd')
execution=B/'preparation-07/control/execution.json';check(execution,'b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3')
request=c/'sealing-request05.json';check(request,'26a16d943e6577c1abfb1d9db1cb13d209998231c260a01d8379f1dd0569724b')
check(c/'plan_direct_fit_sealing01.py','85d8692d3ddd8feb2c2d70c85a8146e5722fc7c416a1c0bc10185df075dd3e94')
check(c/'plan_direct_sealing_view06.py','494f84c734ef8174b0ac462e3dd748fc0c80bb324010f1d5ba29b8135e4c2288')
check(B/'direct-fit-helper-inputs-12/install-result.json','0ecd50df8f30827c2932af8175d89d28d917ca1f5715a6ee08f0ca909fcaaea3')
s=importlib.util.spec_from_file_location('owned',driver);d=importlib.util.module_from_spec(s);s.loader.exec_module(d);e=d.load_execution(execution)
lock=Path('/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock')
results=[]
with lock.open('a') as f,(B/'validation-07/run/.segmented.lock').open('rb') as st:
 fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(st,fcntl.LOCK_EX|fcntl.LOCK_NB);admission=d.admission(e)
 need(not (c/'sealing-plan05.json').exists() and not (c/'readonly-view-plan06.json').exists() and not (c/'readonly-view-plan06-parents.json').exists() and not (c/'sealed-inputs-04').exists(),'Fresh plans/output required')
 env={'PATH':'/usr/bin:/bin','HOME':'/home/florianpfaff','PYTHONDONTWRITEBYTECODE':'1','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1'}
 first=['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(c/'plan_direct_fit_sealing01.py'),'--request',str(request),'--sha256',pin(request)['sha256'],'--output',str(c/'sealing-plan05.json')]
 for index in range(2):
  argv=first if index==0 else ['/usr/bin/taskset','-c','32','/usr/bin/python3','-B',str(c/'plan_direct_sealing_view06.py'),'--sealing-plan',str(c/'sealing-plan05.json'),'--sha256',pin(c/'sealing-plan05.json')['sha256'],'--readonly-helper',str(c/'with_completed_preparation_direct02.py'),'--readonly-helper-sha256','e2d6532cb90e91694aca103e9541e5450ff7c589c62a9982fc6970e3f0f674e1','--output',str(c/'readonly-view-plan06.json')]
  r=subprocess.run(argv,env=env,text=True,capture_output=True);results.append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
  if r.returncode:break
 receipt={'schema':'orbit-poc-direct-sealing-plan-derivation-v1','status':'derived_metadata' if all(r['returncode']==0 for r in results) and len(results)==2 else 'failed','admission':admission,'environment':env,'stages':results,'native_executions':0,'fit_attempts':0}
 with (B/'direct-fit-helper-inputs-12/derivation-result.json').open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
 payload={'receipt':receipt,'receipt_pin':pin(B/'direct-fit-helper-inputs-12/derivation-result.json'),'files':{}}
 for name in ('sealing-request05.json','sealing-plan05.json','readonly-view-plan06.json','readonly-view-plan06-parents.json'):
  if (c/name).exists():payload['files'][name]={'pin':pin(c/name),'text':(c/name).read_text()}
 print(json.dumps(payload))
 if receipt['status']!='derived_metadata':raise SystemExit(1)
