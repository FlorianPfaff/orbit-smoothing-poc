#!/usr/bin/env python3
"""Serial owned controller for one frozen, non-fitting single-propagation replay."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,signal

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(pin):
 if set(pin)!={'path','sha256'} or sha(pin['path'])!=pin['sha256']:raise ValueError('Pinned artifact changed')
def validate_plan(p):
 if set(p)!={'schema','execution','driver','worker','controller','native','source_freeze','inputs','output','global_lock'} or p['schema']!='orbit-poc-nominal-complete-single-replay-plan-v1':raise ValueError('Unknown diagnostic plan')
 if set(p['inputs'])!={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield','original_log','build_result','build_audit'}:raise ValueError('Exact diagnostic input inventory required')
 for key in ('output','global_lock'):
  if not Path(p[key]).is_absolute() or '..' in Path(p[key]).parts:raise ValueError('Canonical absolute paths required')

def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);q=a.parse_args(argv)
 if sha(q.plan)!=q.sha256:raise ValueError('Plan changed')
 p=json.loads(q.plan.read_text());validate_plan(p)
 for k in ('execution','driver','worker','controller','native','source_freeze'):check(p[k])
 if p['controller']['sha256']!=sha(__file__):raise ValueError('Controller changed')
 spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d);e=d.load_execution(p['execution']['path']);paths=e['paths'];control=Path(paths['control']);registry=[];handlers={};j={}
 def guard():
  if sha(q.plan)!=q.sha256:raise ValueError('Plan changed')
  for k in ('execution','driver','worker','controller','native','source_freeze'):check(p[k])
  for pin in e['runtime_artifacts'].values():
   if sha(d.resolved_host_path(pin['path'],e))!=pin['sha256']:raise ValueError('Runtime artifact changed '+pin['path'])
  for pin in p['inputs'].values():
   if sha(d.resolved_host_path(pin['path'],e))!=pin['sha256']:raise ValueError('Diagnostic input changed')
  if d.source_receipt(Path(paths['source']))!=json.loads(Path(p['source_freeze']['path']).read_text())['source']:raise ValueError('Frozen source changed')
  return d.admission(e,registry)
 def save():d.save(control/'pipeline.json',j)
 def live():
  admitted=d.admission(e,registry);rss=0
  for owned in registry:
   for pid,identity in owned.known.items():
    try:
     now=d.proc(pid)
     if now['start_ticks']!=identity['start_ticks']:continue
     for line in (Path('/proc')/str(pid)/'status').read_text().splitlines():
      if line.startswith('VmRSS:'):rss+=1024*int(line.split()[1])
    except (FileNotFoundError,ProcessLookupError):pass
  j['peak_owned_rss_bytes']=max(j.get('peak_owned_rss_bytes',0),rss)
  if rss>8589934592:raise RuntimeError('Owned diagnostic process tree exceeded8GiB')
  return admitted
 with Path(p['global_lock']).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if (control/'pipeline.json').exists() or Path(p['output']).exists():raise ValueError('Preserve previous attempt')
  admitted=guard();j={'schema':'orbit-poc-owned-nominal-complete-single-replay-v1','status':'running','started_at':d.stamp(),'plan':d.artifact(q.plan),'admission':admitted,'fit_attempts':0,'release_evidence':False}
  try:
   for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,d.interrupted)
   save();argv=[e['runtime_artifacts']['control_python']['path'],paths['wrapper'],'--execution',p['execution']['path'],'--execution-sha256',p['execution']['sha256'],'--','/usr/bin/taskset','-c','24',paths['python'],p['worker']['path'],'--plan',str(q.plan),'--sha256',q.sha256]
   env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(HOME='/home/florianpfaff',PYTHONPATH=paths['source']+'/src',PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=paths['prefix']+'/lib',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
   j['argv']=argv;save()
   def started(pid):j['process']=d.proc(pid);save()
   def finished(value):j.update(value);save()
   with (control/'native-replay.log').open('x') as log:code=d.supervise(argv,cwd=Path(paths['source']),env=env,log=log,limit=7200,guard_live=live,on_started=started,on_finished=finished,registry=registry)
   j.update(returncode=code,status='passed_diagnostic' if code==0 else 'failed_diagnostic');guard()
  except BaseException as er:j.update(status='failed',error=repr(er));raise
  finally:
   with d.cleanup_signals():
    errors=[]
    for owned in registry:
     try:owned.cleanup(force=owned.child.poll() is None)
     except BaseException as er:errors.append(repr(er))
    j['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};j['finished_at']=d.stamp()
    if errors:j['status']='failed'
    save()
    for sig,handler in handlers.items():signal.signal(sig,handler)
 return 0 if j['status']=='passed_diagnostic' else 1
if __name__=='__main__':raise SystemExit(main())
