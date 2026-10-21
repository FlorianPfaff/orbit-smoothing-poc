#!/usr/bin/env python3
"""Own one pinned real CLI validation in the existing canonical namespace.

The public CLI owns each gate's process tree and numerical acceptance. This
outer controller supplies detached lifetime, canonical read-only aliases,
source/runtime attribution and independent whole-namespace cleanup.
"""
from pathlib import Path
import argparse,fcntl,hashlib,importlib.util,json,os,signal

KEYS={'schema','execution','driver','runner','source_freeze','config','native_equivalence','global_lock','wall_limit_seconds'}
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
    require(receipt.get('schema')=='orbit-poc-v4-native-rebuild-provenance-v1' and receipt.get('status')=='verified_actual_rebuild','Unknown native rebuild provenance')
    for k in ('previous_source','previous_config','actual_build_result','runtime_provenance'):checked(receipt[k])
    old=json.loads(Path(receipt['previous_source']['path']).read_text())
    previous=json.loads(Path(receipt['previous_config']['path']).read_text())
    build=json.loads(Path(receipt['actual_build_result']['path']).read_text())
    runtime=json.loads(Path(receipt['runtime_provenance']['path']).read_text())
    before=old['source']['files'];after=freeze['source']['files'];header='groops/extension/sixStateTangent.h'
    require(len(before)==len(after)==384 and set(before)==set(after),'Frozen source membership differs')
    require({k for k in before if before[k]!=after[k]}=={header},'Source delta exceeds one header')
    native={k:v for k,v in after.items() if k.startswith('groops/') or k=='scripts/build_groops.py'}
    require(len(native)==70 and native==receipt['native_inputs'],'Native source inventory differs')
    require(build['status']=='built_precision_candidate','Native build did not complete')
    require(build['original_native']['sha256']==build['baseline_relinked_sha256']==previous['segmented_runtime']['native']['sha256'],'Baseline reproduction differs')
    changed={k for k in set(build['source_before'])|set(build['source_after']) if build['source_before'].get(k)!=build['source_after'].get(k)}
    require(changed=={'misc/orbitPoc/sixStateTangent.h'} and build['source_after']['misc/orbitPoc/sixStateTangent.h']==after[header],'Installed native delta differs')
    require(len(build['rebuilt_objects'])==27 and set(build['rebuilt_objects'])==set(build['compile_commands']),'Dependent translation units incomplete')
    require(runtime['actual_build_result']==receipt['actual_build_result'] and runtime['source_native']==build['native'],'Runtime build attribution differs')
    for k in ('native','build_manifest','library_manifest'):checked(runtime[k]);require(config['segmented_runtime'][k]==runtime[k],'Runtime artifact differs: '+k)
    require(runtime['native']['sha256']==build['native']['sha256'],'Relocated native differs')
    for role in ('dense_runtime','segmented_runtime'):
        for k,v in previous[role].items():
            if k not in ({'source_root','source_sha256','native','build_manifest','library_manifest'} if role=='segmented_runtime' else {'source_root','source_sha256'}):require(config[role][k]==v,'Unchanged runtime field differs: '+role+'/'+k)
    for k in ('groops/extension/segmentedQrMain.cpp','groops/extension/segmentedQr.h'):require(before[k]==after[k],'Independent QR solver source changed')
    require(receipt['fixed_stage_names']==list(STAGES),'Scientific stage sequence differs')
    return True

def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv)
    p=load_plan(a.plan,a.sha256);require(p['runner']['sha256']==sha(__file__),'Controller identity changed')
    spec=importlib.util.spec_from_file_location('audited_owned',p['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    e=d.load_execution(p['execution']['path']);paths={k:Path(v) for k,v in e['paths'].items()};freeze=json.loads(Path(p['source_freeze']['path']).read_text())
    config=json.loads(Path(p['config']['path']).read_text());equivalence=json.loads(Path(p['native_equivalence']['path']).read_text())
    require(e['fit_cpu']==24 and e['build_cpus']==[24,25,26,27],'CPU selection changed')
    require(config['output_dir']==str(paths['run']) and config['resources']['reserved_cpu_ids']==[24],'CLI output/CPU selection changed')
    require(all(config[k]['source_root']==str(paths['source']) for k in ('dense_runtime','segmented_runtime')),'Runtime source changed')
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
