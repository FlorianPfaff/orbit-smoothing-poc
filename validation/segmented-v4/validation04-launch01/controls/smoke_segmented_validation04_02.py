"""Read-only exact CLI runtime/input smoke under owned canonical aliases."""
from pathlib import Path
import hashlib,json,importlib.util,os,signal,fcntl,copy,argparse
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04');C=R/'control';S=R/'staging/namespace-smoke-01'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
ap=argparse.ArgumentParser();ap.add_argument('--execution-sha256',required=True);ap.add_argument('--config-sha256',required=True);ap.add_argument('--probe-sha256',required=True);args=ap.parse_args()
assert sha(C/'execution.json')==args.execution_sha256
assert sha(C/'segmented-v4.json')==args.config_sha256
assert sha(C/'validation04_startup_probe.py')==args.probe_sha256
assert sha(C/'owned_driver09.py')=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd'
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
e=d.load_execution(C/'execution.json');p=json.loads((C/'launch-plan.json').read_text());assert not any(Path(e['paths'][k]).exists() for k in d.MUTABLE_KEYS)
S.mkdir(parents=True);derived=copy.deepcopy(e)
for k in d.MUTABLE_KEYS:derived['paths'][k]=str(S/k);Path(derived['paths'][k]).mkdir()
d.save(S/'execution.json',derived)
argv=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(S/'execution.json'),'--execution-sha256',sha(S/'execution.json'),'--','/usr/bin/taskset','-c','24',e['paths']['python'],str(C/'validation04_startup_probe.py'),'--root',str(R),'--output',str(S/'run/probe-result')]
registry=[];handlers={};receipt={'schema':'orbit-poc-v4-cli-validation04-namespace-smoke-v1','status':'running','execution':d.artifact(C/'execution.json'),'config':d.artifact(C/'segmented-v4.json'),'derived_execution':d.artifact(S/'execution.json'),'probe':d.artifact(C/'validation04_startup_probe.py'),'helper':d.artifact(Path(__file__)),'argv':argv,'no_fit_executed':True}
def save():d.save(S/'process.json',receipt)
with Path(p['global_lock']).open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);receipt['admission']=d.admission(e,registry)
 try:
  for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,d.interrupted)
  env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(PYTHONPATH=str(R/'source/src'),PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',LD_LIBRARY_PATH=str(Path(e['paths']['prefix'])/'lib'))
  def started(pid):receipt['process']=d.proc(pid);save()
  def finished(v):receipt.update(v);save()
  with (S/'probe.log').open('x') as log:rc=d.supervise(argv,cwd=R/'source',env=env,log=log,limit=900,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
  receipt.update(returncode=rc,status='passed' if rc==0 else 'failed')
  if rc==0:receipt['result']=d.artifact(S/'run/probe-result/result.json')
 finally:
  with d.cleanup_signals():
   errors=[]
   for child in registry:
    try:child.cleanup(force=child.child.poll() is None)
    except BaseException as ex:errors.append(repr(ex))
   receipt['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]}
   if errors:receipt['status']='failed'
   receipt['production_outputs_absent']=all(not Path(e['paths'][k]).exists() for k in d.MUTABLE_KEYS)
   save()
   for sig,h in handlers.items():signal.signal(sig,h)
print(json.dumps(receipt));raise SystemExit(0 if receipt['status']=='passed' else 1)
