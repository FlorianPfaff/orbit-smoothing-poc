#!/usr/bin/env python3
"""Owned serial post-suite captured-row solves; no physical evaluation."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,signal
KEYS={'schema','execution','driver','runner','source_freeze','diagnostic','solver','controller','pipeline','validations','global_lock','wall_limit_seconds'}
PINKEYS=KEYS-{'schema','validations','global_lock','wall_limit_seconds'}
METHODS=('log_drag_ou','pulses')
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def require(ok,why):
 if not ok:raise RuntimeError(why)
def checked(pin):
 require(isinstance(pin,dict) and set(pin)=={'path','sha256'},'Invalid artifact pin')
 require(Path(pin['path']).is_absolute() and sha(pin['path'])==pin['sha256'],'Artifact changed')
def load_plan(path,digest):
 require(sha(path)==digest,'Plan changed');p=json.loads(Path(path).read_text())
 require(set(p)==KEYS and p['schema']=='orbit-poc-shifted-diagnostic-owned-plan-v1','Wrong plan schema')
 for key in PINKEYS:checked(p[key])
 require(set(p['validations'])==set(METHODS),'Changed method inventory')
 for pin in p['validations'].values():checked(pin)
 require(p['wall_limit_seconds']==1800 and Path(p['global_lock']).is_absolute(),'Changed bounds/lock')
 controller=json.loads(Path(p['controller']['path']).read_text());pipeline=json.loads(Path(p['pipeline']['path']).read_text())
 require(controller['status']=='passed' and controller.get('final_cleanup',{}).get('verified') is True,'Required suite not terminal and clean')
 require(controller['cli_validation']['pipeline']==p['pipeline'],'Required suite pipeline attribution differs')
 require(pipeline['status']=='passed' and tuple(s['name'] for s in pipeline['steps'])==STAGES and all(s['status']=='passed' for s in pipeline['steps']),'Required14gates not passed')
 for method,pin in p['validations'].items():
  rows=[s for s in pipeline['steps'] if s['name']=='linearization-'+method]
  require(len(rows)==1 and rows[0]['evidence']['result']==pin,'Wrong captured gate artifact')
 return p

def command(e,p,method):
 return [e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',p['execution']['path'],'--execution-sha256',p['execution']['sha256'],'--','/usr/bin/taskset','-c','24','/usr/bin/prlimit','--as=8589934592','--',e['paths']['python'],p['diagnostic']['path'],
  '--controller',p['controller']['path'],'--controller-sha256',p['controller']['sha256'],'--pipeline',p['pipeline']['path'],'--pipeline-sha256',p['pipeline']['sha256'],'--validation',p['validations'][method]['path'],'--validation-sha256',p['validations'][method]['sha256'],
  '--source',e['paths']['source'],'--source-sha256',json.loads(Path(p['source_freeze']['path']).read_text())['comparison_source']['sha256'],'--solver',p['solver']['path'],'--solver-sha256',p['solver']['sha256'],'--output',str(Path(e['paths']['run'])/method)]

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv);p=load_plan(a.plan,a.sha256)
 require(p['runner']['sha256']==sha(__file__),'Runner changed')
 spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
 e=d.load_execution(p['execution']['path']);paths={k:Path(v) for k,v in e['paths'].items()};freeze=json.loads(Path(p['source_freeze']['path']).read_text());registry=[];handlers={};journal={}
 require(e['fit_cpu']==24,'FrozenCPU changed')
 def save():d.save(paths['control']/'pipeline.json',journal)
 def guard():
  require(load_plan(a.plan,a.sha256)==p,'Plan changed');require(d.source_receipt(paths['source'])==freeze['source'],'Source changed')
  for pin in e['runtime_artifacts'].values():require(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Runtime changed')
  return d.admission(e,registry)
 with Path(p['global_lock']).open('a') as lock,(paths['control']/'controller.lock').open('a') as local:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(local,fcntl.LOCK_EX|fcntl.LOCK_NB)
  require(not (paths['control']/'pipeline.json').exists(),'Preserve prior diagnostic attempt')
  admitted=guard();d.prepare_writable_directories(e['paths'])
  journal={'schema':'orbit-poc-shifted-diagnostic-owned-run-v1','status':'running','started_at':d.stamp(),'plan':d.artifact(a.plan),'admission':admitted,'physical_evaluations':0,'benchmark_attempts':0,'release_ready':False,'resource_note':'CPU24;1800s per method; inherited per-process8GiB address-space limit, not aggregate treeRSS guarantee','steps':[{'method':x,'status':'not_run'} for x in METHODS]}
  try:
   for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,d.interrupted)
   save();env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(PYTHONPATH=str(paths['source']/'src'),PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=str(paths['prefix']/'lib'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
   for step in journal['steps']:
    guard();step.update(status='running',argv=command(e,p,step['method']),started_at=d.stamp());save()
    def started(pid):step['process']=d.proc(pid);save()
    def finished(value):step.update(value);save()
    with (paths['control']/(step['method']+'.log')).open('x') as log:
     code=d.supervise(step['argv'],cwd=paths['source'],env=env,log=log,limit=p['wall_limit_seconds'],guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
    step.update(returncode=code,finished_at=d.stamp());result=paths['run']/step['method']/'validation.json'
    if result.exists():
     value=json.loads(result.read_text());step.update(result=d.artifact(result),diagnostic_status=value.get('status'))
     require(value.get('physical_evaluations')==0 and value.get('nuisance_profile_evaluations')==0 and value.get('fit_covariance_authorized') is False,'Diagnostic changed scope')
     step['status']='passed' if code==0 and value.get('passed') is True else 'failed_or_coverage_inadequate'
    else:step['status']='failed_missing_result'
    save();guard()
   journal['status']='passed' if all(s['status']=='passed' for s in journal['steps']) else 'failed_or_coverage_inadequate'
  except BaseException as error:
   journal.update(status='failed',error=repr(error));raise
  finally:
   with d.cleanup_signals():
    errors=[]
    for child in registry:
     try:child.cleanup(force=child.child.poll() is None)
     except BaseException as error:errors.append(repr(error))
    journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};journal['finished_at']=d.stamp()
    if errors:journal['status']='failed'
    save()
    for sig,handler in handlers.items():signal.signal(sig,handler)
 return 0 if journal['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
