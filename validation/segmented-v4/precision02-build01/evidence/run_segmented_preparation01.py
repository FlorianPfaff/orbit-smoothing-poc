#!/usr/bin/env python3
"""Own public data preparation only, after the unchanged14 gates and audit."""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,signal
KEYS={'schema','execution','driver','runner','source_freeze','config','checker','validation_audit','controller','pipeline','global_lock','control_root','check_output_root','wall_limit_seconds'}
PINS=KEYS-{'schema','global_lock','control_root','check_output_root','wall_limit_seconds'}
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def need(ok,why):
 if not ok:raise RuntimeError(why)
def checked(pin):
 need(isinstance(pin,dict) and set(pin)=={'path','sha256'},'Invalid exact artifact pin');need(Path(pin['path']).is_absolute() and sha(pin['path'])==pin['sha256'],'Artifact changed: '+pin['path'])
def same(a,b):return a.get('path')==b['path'] and a.get('sha256')==b['sha256'] and ('bytes' not in a or a['bytes']==Path(b['path']).stat().st_size)
def load_plan(path,digest):
 need(sha(path)==digest,'Plan changed');p=json.loads(Path(path).read_text())
 need(set(p)==KEYS and p['schema']=='orbit-poc-segmented-preparation-owned-plan-v1','Unknown preparation plan')
 for key in PINS:checked(p[key])
 for key in ('global_lock','control_root','check_output_root'):need(Path(p[key]).is_absolute(),'Absolute control paths required')
 need(type(p['wall_limit_seconds']) is int and p['wall_limit_seconds']==129600,'Fixed36hour outer lifetime required')
 c=json.loads(Path(p['controller']['path']).read_text());v=json.loads(Path(p['pipeline']['path']).read_text());a=json.loads(Path(p['validation_audit']['path']).read_text());freeze=json.loads(Path(p['source_freeze']['path']).read_text());config=json.loads(Path(p['config']['path']).read_text())
 need(c.get('status')=='passed' and c.get('final_cleanup',{}).get('verified') is True and same(c['cli_validation']['pipeline'],p['pipeline']),'Original validation not terminal, attributed and clean')
 need(v.get('status')=='passed' and tuple(s['name'] for s in v['steps'])==STAGES and all(s['status']=='passed' for s in v['steps']),'Prescribed14gates not passed')
 need(a.get('schema')=='orbit-poc-segmented-validation-terminal-independent-review-v1' and a.get('consistency_passed') is True and a.get('scientific_status')=='passed_scoped_checks' and a.get('cleanup_verified') is True,'Independent14gate audit is not a scoped pass')
 for name in ('controller','cli_pipeline','validation_context','validation_plan','run_plan','config','source_freeze','launch_plan','launch_pins'):
  value=a['artifacts'][name];checked({k:value[k] for k in ('path','sha256')});need('bytes' not in value or value['bytes']==Path(value['path']).stat().st_size,'Audit artifact size differs')
 for name,key in (('controller','controller'),('cli_pipeline','pipeline'),('config','config'),('source_freeze','source_freeze')):need(same(a['artifacts'][name],p[key]),'Independent audit artifact differs: '+name)
 need(same(a['artifacts']['launch_plan'],{k:c['plan'][k] for k in ('path','sha256')}),'Audit original launch plan differs')
 identity=a['identity'];need(identity['full_source_sha256']==freeze['source']['sha256'] and identity['comparison_source_sha256']==freeze['comparison_source']['sha256']==config['segmented_runtime']['source_sha256']==config['dense_runtime']['source_sha256'],'Independent source identity differs')
 need(identity['native_sha256']==config['segmented_runtime']['native']['sha256'] and identity['solver_sha256']==config['segmented_runtime']['segmented_solver']['sha256'],'Independent runtime identity differs')
 return p

def prefix(e,p):return [e['runtime_artifacts']['control_python']['path'],e['paths']['wrapper'],'--execution',p['execution']['path'],'--execution-sha256',p['execution']['sha256'],'--','/usr/bin/taskset','-c','24',e['paths']['python']]
def command(e,p):return prefix(e,p)+['-m','orbit_poc.cli','segmented','prepare','--config',p['config']['path']]
def check_command(e,p,phase):return prefix(e,p)+[p['checker']['path'],'--config',p['config']['path'],'--config-sha256',p['config']['sha256'],'--source-sha256',json.loads(Path(p['source_freeze']['path']).read_text())['comparison_source']['sha256'],'--phase',phase,'--output',str(Path(p['check_output_root'])/(phase+'.json'))]
def inspect_check(p,phase):
 path=Path(p['check_output_root'])/(phase+'.json');v=json.loads(path.read_text())
 need(v.get('schema')=='orbit-poc-segmented-preparation-state-check-v1' and v.get('status')=='passed' and v.get('phase')==phase and v.get('config')==p['config'],'Preparation check attribution differs')
 need(same(v['validation']['pipeline'],p['pipeline']) and v['validation']['status']=='passed','Preparation changed original validation')
 if phase=='after':need(v['prepared']['cases']==28 and v['prepared']['attempts']==68 and v['prepared']['benchmark_fit_count']==0,'Preparation incomplete or ran fits')
 return {'path':str(path),'sha256':sha(path)}

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv);p=load_plan(a.plan,a.sha256);need(p['runner']['sha256']==sha(__file__),'Controller changed')
 spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
 e=d.load_execution(p['execution']['path']);paths={k:Path(v) for k,v in e['paths'].items()};freeze=json.loads(Path(p['source_freeze']['path']).read_text());config=json.loads(Path(p['config']['path']).read_text());control=Path(p['control_root']);checks=Path(p['check_output_root']);registry=[];handlers={};journal={}
 need(e['fit_cpu']==24 and config['resources']['reserved_cpu_ids']==[24] and config['output_dir']==str(paths['run']),'Frozen CPU/output changed')
 need(paths['temporary'] in checks.parents and control!=paths['control'] and not control.is_symlink(),'Separate preparation control/check directories required')
 need(control.is_dir() and not checks.exists() and not checks.is_symlink(),'Fresh preparation checks required')
 def save():d.save(control/'pipeline.json',journal)
 def guard():
  need(load_plan(a.plan,a.sha256)==p,'Plan changed');need(d.source_receipt(paths['source'])==freeze['source'],'Source changed')
  for pin in e['runtime_artifacts'].values():need(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Pinned runtime changed')
  return d.admission(e,registry)
 with Path(p['global_lock']).open('a') as lock,(control/'controller.lock').open('a') as local:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(local,fcntl.LOCK_EX|fcntl.LOCK_NB);need(not (control/'pipeline.json').exists(),'Preserve prior preparation attempt')
  admitted=guard();checks.mkdir()
  journal={'schema':'orbit-poc-segmented-preparation-owned-run-v1','status':'running','started_at':d.stamp(),'plan':d.artifact(a.plan),'admission':admitted,'benchmark_attempts':0,'checks':[],'release_ready':False,'resource_scope':'36h outer data-preparation lifetime; each public component retains its frozen2h/8GiB/one-thread limits'}
  try:
   for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,d.interrupted)
   save();env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))};env.update(PYTHONPATH=str(paths['source']/'src'),PYTHONDONTWRITEBYTECODE='1',LD_LIBRARY_PATH=str(paths['prefix']/'lib'),OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1')
   def execute(row,name,argv,limit):
    row.update(status='running',argv=argv);save()
    def started(pid):row['process']=d.proc(pid);save()
    def finished(value):row.update(value);save()
    with (control/(name+'.log')).open('x') as log:code=d.supervise(argv,cwd=paths['source'],env=env,log=log,limit=limit,guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
    row.update(returncode=code,status='complete' if code==0 else 'failed');save();return code
   before={'phase':'before'};journal['checks'].append(before);need(execute(before,'check-before',check_command(e,p,'before'),1800)==0,'Pre-preparation validation failed');before['result']=inspect_check(p,'before');save();guard()
   row={};journal['preparation']=row;code=execute(row,'prepare-cli',command(e,p),p['wall_limit_seconds'])
   # Public prepare may return0 with status blocked. Always inspect original
   # outputs through frozen verify_manifest/require_passed before accepting it.
   after={'phase':'after'};journal['checks'].append(after);check_code=execute(after,'check-after',check_command(e,p,'after'),1800)
   if check_code==0:after['result']=inspect_check(p,'after')
   journal['status']='prepared' if code==0 and check_code==0 else 'failed_or_blocked';save();guard()
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
    for sig,handler in handlers.items():signal.signal(sig,handler)
 return 0 if journal['status']=='prepared' else 1
if __name__=='__main__':raise SystemExit(main())
