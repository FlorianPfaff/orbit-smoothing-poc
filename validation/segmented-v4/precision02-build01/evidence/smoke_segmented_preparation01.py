#!/usr/bin/env python3
"""Own a read-only preparation startup probe with five scratch-only mounts."""
from pathlib import Path
import argparse, copy, fcntl, hashlib, importlib.util, json, os, signal
KEYS={'schema','execution','driver','probe_plan','helper','global_lock','output'}
MUTABLE=('native_source','build','binaries','run','temporary')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise RuntimeError(why)
def checked(item):
 need(isinstance(item,dict) and set(item)=={'path','sha256'} and Path(item['path']).is_absolute() and sha(item['path'])==item['sha256'],'Changed exact artifact')
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def inspect(path,digest):
 need(sha(path)==digest,'Smoke plan changed');p=json.loads(Path(path).read_text());need(set(p)==KEYS and p['schema']=='orbit-poc-preparation-owned-startup-smoke-v1','Wrong smoke schema')
 for key in ('execution','driver','probe_plan','helper'):checked(p[key])
 need(p['helper']['sha256']==sha(__file__),'Smoke helper changed')
 e=json.loads(Path(p['execution']['path']).read_text());s=Path(p['output']);root=Path(e['paths']['root']);need(s.is_absolute() and root/'staging' in s.parents and not s.exists() and not s.is_symlink(),'Fresh root-scoped scratch required');need(Path(p['global_lock']).is_absolute(),'Global lock must be absolute')
 q=json.loads(Path(p['probe_plan']['path']).read_text());checked(q['helper']);need(q['output']==str(s/'temporary/probe-result'),'Probe output must use derived scratch')
 return p,e,q

def derive(e,s):
 n=copy.deepcopy(e)
 for key in MUTABLE:n['paths'][key]=str(Path(s)/key)
 return n

def main(argv=None):
 a=argparse.ArgumentParser();a.add_argument('--plan',type=Path,required=True);a.add_argument('--sha256',required=True);v=a.parse_args(argv);p,raw,q=inspect(v.plan,v.sha256);d=load('pinned_owned_preparation_driver',p['driver']['path']);e=d.load_execution(p['execution']['path']);s=Path(p['output']);registry=[];handlers={};journal={}
 with Path(p['global_lock']).open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);admitted=d.admission(e,registry);s.mkdir(parents=True);derived=derive(e,s);d.save(s/'execution.json',derived);derived=d.load_execution(s/'execution.json');d.prepare_writable_directories(derived['paths'])
  command=[e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',str(s/'execution.json'),'--execution-sha256',sha(s/'execution.json'),'--','/usr/bin/taskset','-c','24',e['paths']['python'],q['helper']['path'],'--plan',p['probe_plan']['path'],'--sha256',p['probe_plan']['sha256']]
  journal={'schema':'orbit-poc-preparation-owned-startup-smoke-result-v1','status':'running','plan':d.artifact(v.plan),'execution':p['execution'],'derived_execution':d.artifact(s/'execution.json'),'probe_plan':p['probe_plan'],'admission':admitted,'argv':command,'physical_propagations':0,'benchmark_fits':0}
  def save():d.save(s/'process.json',journal)
  try:
   for number in (signal.SIGINT,signal.SIGTERM):handlers[number]=signal.signal(number,d.interrupted)
   env={k:z for k,z in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(PYTHONPATH=e['paths']['source']+'/src',PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=e['paths']['prefix']+'/lib',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
   def started(pid):journal['process']=d.proc(pid);save()
   def finished(value):journal.update(value);save()
   save()
   with (s/'worker.log').open('x') as log:code=d.supervise(command,cwd=Path(e['paths']['source']),env=env,log=log,limit=900,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
   journal['returncode']=code;result=Path(q['output'])/'result.json'
   if result.exists():journal['result']=d.artifact(result)
   need(code==0,'Preparation startup dependency probe failed');value=json.loads(result.read_text());need(value['status']=='passed' and value['physical_propagations']==0 and value['benchmark_fits']==0 and value['config']==q['config'] and value['source_sha256']==q['source_sha256'],'Probe scope/identity differs');journal['status']='passed'
   for key in ('execution','driver','probe_plan','helper'):checked(p[key])
  except BaseException as error:journal.update(status='failed',error=repr(error));raise
  finally:
   with d.cleanup_signals():
    errors=[]
    for child in registry:
     try:child.cleanup(force=child.child.poll() is None)
     except BaseException as error:errors.append(repr(error))
    journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};journal['finished_at']=d.stamp()
    if errors:journal['status']='failed'
    save()
    for number,previous in handlers.items():signal.signal(number,previous)
 print(json.dumps({'status':journal['status'],'process':d.artifact(s/'process.json'),'result':journal.get('result'),'cleanup_verified':journal['final_cleanup']['verified']}));return 0 if journal['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
