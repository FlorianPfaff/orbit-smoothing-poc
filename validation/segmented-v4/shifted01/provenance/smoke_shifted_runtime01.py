#!/usr/bin/env python3
"""One owned full-runtime check in derived scratch mounts; no numerical solve."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,signal,fcntl,copy
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise RuntimeError(why)
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def derive(e,root):
 n=copy.deepcopy(e)
 for key in ('native_source','build','binaries','run','temporary'):n['paths'][key]=str(Path(root)/key)
 return n
def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);a.add_argument('--helper-sha256',required=True);v=a.parse_args(argv)
 need(sha(__file__)==v.helper_sha256 and sha(v.plan)==v.sha256,'Smoke helper/plan changed');raw=json.loads(v.plan.read_text());need(sha(raw['runner']['path'])==raw['runner']['sha256'],'Runner changed');runner=load('pinned_shifted_runner',raw['runner']['path']);p=runner.load_plan(v.plan,v.sha256)
 d=load('pinned_owned_driver',p['driver']['path']);e=d.load_execution(p['execution']['path']);smoke=Path(e['paths']['root'])/'staging/runtime-smoke-01';need(not smoke.exists() and not smoke.is_symlink(),'Preserve prior smoke');registry=[];handlers={};journal={}
 with Path(p['global_lock']).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);admitted=d.admission(e,registry);smoke.mkdir(parents=True);new=derive(e,smoke);d.save(smoke/'execution.json',new);new=d.load_execution(smoke/'execution.json');d.prepare_writable_directories(new['paths']);q=dict(p,execution={'path':str(smoke/'execution.json'),'sha256':sha(smoke/'execution.json')});result=Path(new['paths']['run'])/'runtime-log_drag_ou-before.json'
  journal={'schema':'orbit-poc-shifted-runtime-startup-smoke-v1','status':'running','original_plan':d.artifact(v.plan),'original_execution':p['execution'],'derived_execution':q['execution'],'admission':admitted,'helper':d.artifact(__file__),'physical_evaluations':0,'constrained_solves':0};d.save(smoke/'process.json',journal)
  try:
   for number in (signal.SIGINT,signal.SIGTERM):handlers[number]=signal.signal(number,d.interrupted)
   env={k:z for k,z in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(PYTHONPATH=e['paths']['source']+'/src',PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=e['paths']['prefix']+'/lib',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
   command=runner.runtime_command(new,q,'log_drag_ou','before');journal['argv']=command
   def started(pid):journal['process']=d.proc(pid);d.save(smoke/'process.json',journal)
   def finished(x):journal.update(x);d.save(smoke/'process.json',journal)
   with (smoke/'worker.log').open('x') as log:code=d.supervise(command,cwd=Path(e['paths']['source']),env=env,log=log,limit=600,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
   journal['returncode']=code;need(code==0,'Full runtime startup failed');r=json.loads(result.read_text());need(r['status']=='passed' and r['full_runtime_verified'] is True and r['config']==p['config'] and r['solver']==p['solver'],'Runtime result attribution changed');journal.update(status='passed',result=d.artifact(result));runner.load_plan(v.plan,v.sha256)
  except BaseException as error:journal.update(status='failed',error=repr(error));raise
  finally:
   with d.cleanup_signals():
    errors=[]
    for child in registry:
     try:child.cleanup(force=child.child.poll() is None)
     except BaseException as error:errors.append(repr(error))
    journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};journal['finished_at']=d.stamp()
    if errors:journal['status']='failed'
    d.save(smoke/'process.json',journal)
    for number,old in handlers.items():signal.signal(number,old)
  need(all(not Path(e['paths'][k]).exists() and not Path(e['paths'][k]).is_symlink() for k in ('native_source','build','binaries','run','temporary')),'Production output paths were created by smoke')
 print(json.dumps({'status':journal['status'],'process':d.artifact(smoke/'process.json'),'result':journal.get('result'),'cleanup_verified':journal['final_cleanup']['verified']}));return 0 if journal['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
