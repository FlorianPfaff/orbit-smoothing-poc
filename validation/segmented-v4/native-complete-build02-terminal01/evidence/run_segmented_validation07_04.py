#!/usr/bin/env python3
"""Own one pinned real CLI validation in the existing canonical namespace.

The public CLI owns each gate's process tree and numerical acceptance. This
outer controller supplies detached lifetime, canonical read-only aliases,
source/runtime attribution and independent whole-namespace cleanup.
"""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,signal

KEYS={'schema','execution','driver','runner','source_freeze','config','native_equivalence','provenance_checker','global_lock','wall_limit_seconds'}
PINS=KEYS-{'schema','global_lock','wall_limit_seconds'}
MUTABLE=('native_source','build','binaries','run','temporary')
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def require(value,why):
    if not value:raise RuntimeError(why)
def checked(pin):
    require(isinstance(pin,dict) and set(pin)=={'path','sha256'},'Invalid artifact pin')
    require(Path(pin['path']).is_absolute() and sha(pin['path'])==pin['sha256'],'Artifact changed: '+pin['path'])
def load_plan(path,digest):
    require(sha(path)==digest,'Validation plan changed');p=json.loads(Path(path).read_text())
    require(set(p)==KEYS and p['schema']=='orbit-poc-v4-cli-validation-launch-plan-v1','Unknown validation launch plan')
    for key in PINS:checked(p[key])
    require(Path(p['global_lock']).is_absolute(),'Absolute global lock required')
    require(type(p['wall_limit_seconds']) is int and p['wall_limit_seconds']==108000,'Fixed bounded full-suite lifetime required')
    return p

def cli_command(e,plan):
    paths=e['paths']
    return [e['runtime_artifacts']['control_python']['path'],paths['wrapper'],'--execution',plan['execution']['path'],
        '--execution-sha256',plan['execution']['sha256'],'--','/usr/bin/taskset','-c','24',paths['python'],'-m','orbit_poc.cli',
        'segmented','validate','--config',plan['config']['path']]

def inspect_cli_output(paths,plan):
    root=Path(paths['run']);latest=json.loads((root/'validation/latest.json').read_text());checked(latest['pipeline'])
    pipeline_path=Path(latest['pipeline']['path']).resolve()
    require((root/'validation').resolve() in pipeline_path.parents,'CLI pipeline escapes its validation root')
    pipeline=json.loads(pipeline_path.read_text())
    require(pipeline.get('schema')=='orbit-poc-segmented-validation-run-v1' and pipeline.get('status') in {'passed','failed'},'CLI validation did not finish')
    require(tuple(step.get('name') for step in pipeline.get('steps',[]))==STAGES,'CLI validation changed ordered planned gates')
    for step in pipeline['steps']:
        require(step.get('status') in {'passed','failed','not_run','interrupted_or_failed'},'CLI gate still active')
        if step['status']=='passed':require('execution' in step,'Passed CLI gate lacks execution evidence')
        if 'execution' in step:
            checked(step['execution']);v=json.loads(Path(step['execution']['path']).read_text())
            require(v.get('harness_execution',{}).get('owned_process_group_cleaned') is True,'CLI gate cleanup unverified')
            if step['status']=='passed':require(v.get('status')=='complete' and v.get('returncode')==0,'Passed CLI gate process failed')
    if pipeline['status']=='passed':require(all(s['status']=='passed' for s in pipeline['steps']),'Passed CLI summary contains incomplete or failed gates')
    return {'status':pipeline['status'],'pipeline':latest['pipeline'],'passed':sum(s['status']=='passed' for s in pipeline['steps']),'planned':14}

def verify_native_provenance(receipt,config,freeze):
    support=Path(__file__).with_name('validation07_provenance04.py')
    spec=importlib.util.spec_from_file_location('validation07_provenance',support)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.verify_native_provenance(receipt,config,freeze,checked,STAGES)

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv)
    p=load_plan(a.plan,a.sha256);require(p['runner']['sha256']==sha(__file__),'Controller identity changed')
    spec=importlib.util.spec_from_file_location('audited_owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    e=d.load_execution(p['execution']['path']);paths={k:Path(v) for k,v in e['paths'].items()};freeze=json.loads(Path(p['source_freeze']['path']).read_text())
    config=json.loads(Path(p['config']['path']).read_text());equivalence=json.loads(Path(p['native_equivalence']['path']).read_text())
    require(e['fit_cpu']==24 and e['build_cpus']==[24,25,26,27],'CPU selection changed')
    require(config['output_dir']==str(paths['run']) and config['resources']['reserved_cpu_ids']==[24],'CLI output/CPU selection changed')
    require(all(config[k]['source_root']==str(paths['source']) for k in ('dense_runtime','segmented_runtime')),'Runtime source changed')
    require(p['provenance_checker']['path']==str(Path(__file__).with_name('validation07_provenance04.py')),'Provenance checker path differs')
    verify_native_provenance(equivalence,config,freeze)
    registry=[];handlers={};journal={};control=paths['control']
    def save():d.save(control/'validation-controller.json',journal)
    def guard():
        require(load_plan(a.plan,a.sha256)==p,'Plan changed')
        require(d.source_receipt(paths['source'])==freeze['source'],'Frozen source changed')
        for key,pin in e['runtime_artifacts'].items():require(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Runtime changed: '+key)
        return d.admission(e,registry)
    with Path(p['global_lock']).open('a') as lock,(control/'validation-controller.lock').open('a') as local:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(local,fcntl.LOCK_EX|fcntl.LOCK_NB)
        require(not (control/'validation-controller.json').exists(),'Controller already ran; preserve prior attempt')
        admitted=guard();d.prepare_writable_directories(e['paths'])
        journal={'schema':'orbit-poc-v4-cli-validation-controller-v1','status':'running','started_at':d.stamp(),'plan':d.artifact(a.plan),'source':freeze['source'],'admission':admitted,'scientific_acceptance_owner':'public segmented validate command','release_ready':False}
        try:
            for sig in (signal.SIGINT,signal.SIGTERM):handlers[sig]=signal.signal(sig,d.interrupted)
            save();argv=cli_command(e,p);journal['argv']=argv
            env={k:v for k,v in os.environ.items() if not k.startswith(('LD_','ORBIT_POC_'))}
            env.update(PYTHONPATH=str(paths['source']/'src'),PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',LD_LIBRARY_PATH=str(paths['prefix']/'lib'))
            def started(pid):journal['process']=d.proc(pid);save()
            def finished(value):journal.update(value);save()
            with (control/'validation-cli.log').open('x') as log:
                code=d.supervise(argv,cwd=paths['source'],env=env,log=log,limit=p['wall_limit_seconds'],guard_live=lambda:d.admission(e,registry),on_started=started,on_finished=finished,registry=registry)
            journal['returncode']=code;journal['cli_validation']=inspect_cli_output(paths,p)
            journal['status']='passed' if code==0 and journal['cli_validation']['status']=='passed' else 'failed'
            guard()
        except BaseException as ex:
            journal.update(status='failed',error=repr(ex));raise
        finally:
            with d.cleanup_signals():
                errors=[]
                for child in registry:
                    try:child.cleanup(force=child.child.poll() is None)
                    except BaseException as ex:errors.append(repr(ex))
                journal['final_cleanup']={'verified':not errors,'errors':errors,'commands':[x.last_cleanup for x in registry]};journal['finished_at']=d.stamp()
                if errors:journal['status']='failed'
                save()
                for sig,handler in handlers.items():signal.signal(sig,handler)
    print(json.dumps({'status':journal['status'],'cli_validation':journal.get('cli_validation'),'final_cleanup':journal['final_cleanup']}))
    return 0 if journal['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
