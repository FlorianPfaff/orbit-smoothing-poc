#!/usr/bin/env python3
"""Finite, read-only validation09 handoff; only NEW postprocessing outputs are written.

No source edits, native fits, campaign signals, retries, Git action or gate upgrades.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
ROOT=Path('/unconfigured-recovery09')
CONTROL=ROOT/'control';SOURCE=ROOT/'source';RUN=ROOT/'validation'
PREVIOUS=ROOT/'previous';PYTHON=ROOT/'python'
HELPERS=('verify_correctness_results_09.py','render_correctness_report_09.py',
         'collect_correctness_publication_09.py','recovery_evidence_09.py')
EXECUTION={}


def checked_artifact(item,label):
    require(isinstance(item,dict) and isinstance(item.get('path'),str) and Path(item['path']).is_absolute()
            and isinstance(item.get('sha256'),str) and len(item['sha256'])==64,'Missing artifact: '+label)
    require(sha(item['path'])==item['sha256'],'Pinned artifact changed: '+label)
    return read(item['path'])


def configure(plan):
    global ROOT,CONTROL,SOURCE,RUN,PREVIOUS,PYTHON,EXECUTION
    EXECUTION=checked_artifact(plan['execution'],'execution')
    require(EXECUTION.get('schema')=='orbit-poc-correctness-execution-v1','Unexpected execution schema')
    paths=EXECUTION['paths']
    ROOT=Path(paths['root']);CONTROL=Path(paths['control']);SOURCE=Path(paths['source']);RUN=Path(paths['run'])
    # The same pinned alias resolver is used by independent evidence helpers.
    module_spec=importlib.util.spec_from_file_location('post04_recovery',CONTROL/'recovery_evidence_09.py')
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    PREVIOUS=module.host_path(plan['previous'],EXECUTION)
    PYTHON=Path(plan['reporting_python']['path'])



def now():return datetime.now(timezone.utc).isoformat()
def require(value,message):
    if not value:raise RuntimeError(message)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()
def pairs(items):
    result={}
    for key,value in items:
        require(key not in result,'Duplicate JSON key');result[key]=value
    return result
def read(path):
    require(Path(path).stat().st_size<=64*1024*1024,'Oversized control or metadata receipt')
    data=json.loads(Path(path).read_text(),object_pairs_hook=pairs,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    require(isinstance(data,dict),'Expected JSON object');return data
def save(path,value):
    temporary=Path(str(path)+'.writing')
    with temporary.open('w') as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
    temporary.replace(path)
def artifact(path):
    p=Path(path);return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}


def load_plan(path,expected):
    require(isinstance(expected,str) and len(expected)==64 and sha(path)==expected,'Reviewed postprocess plan changed')
    plan=read(path)
    required={'schema','execution','candidate_pins','source_sha256','source_commit','driver_process','helpers',
              'reporting_python','postprocessor_sha256','output_root','previous','wait_seconds'}
    require(set(plan)==required,'Unexpected or missing postprocess plan fields')
    require(plan['schema']=='orbit-poc-correctness-postprocess09-plan-v1','Wrong postprocess plan schema')
    for key in ('source_sha256','postprocessor_sha256'):
        require(isinstance(plan[key],str) and len(plan[key])==64 and all(x in '0123456789abcdef' for x in plan[key]),'Unset digest '+key)
    require(set(plan['helpers'])==set(HELPERS) and all(isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v) for v in plan['helpers'].values()),'All four exact helper pins required')
    require(type(plan['wait_seconds']) is int and 1<=plan['wait_seconds']<=86400,'Finite wait must be within one day')
    interpreter=plan['reporting_python']
    require(isinstance(interpreter,dict) and set(interpreter)=={'path','sha256','versions'}
            and isinstance(interpreter['path'],str) and Path(interpreter['path']).is_absolute()
            and isinstance(interpreter['sha256'],str) and len(interpreter['sha256'])==64
            and isinstance(interpreter['versions'],dict) and {'python','numpy','scipy','gtsam','pytest','psutil'}<=set(interpreter['versions']),
            'Separate reporting interpreter path, hash and observed versions required')
    process=plan['driver_process']
    require(set(process)=={'pid','start_ticks','boot_id'} and type(process['pid']) is int and process['pid']>0
            and type(process['start_ticks']) is int and process['start_ticks']>=0 and isinstance(process['boot_id'],str) and process['boot_id'],
            'Exact driver process identity required')
    # Pin helper bytes before importing the path resolver, even during setup.
    execution=checked_artifact(plan['execution'],'execution')
    control=Path(execution['paths']['control'])
    require(sha(control/'recovery_evidence_09.py')==plan['helpers']['recovery_evidence_09.py'],'Recovery verifier source changed')
    configure(plan)
    output=Path(plan['output_root'])
    require(output.is_absolute() and output.parent==ROOT and output.name.startswith('postprocess-09-'),'Output must be a NEW direct execution-root/postprocess-09-* directory')
    require(not output.exists() and not output.is_symlink(),'Postprocessing output already exists; no retries or overwrite')
    require(Path(plan['previous']).is_absolute(),'Previous objective root must be absolute')
    return plan


def verify_small_identities(plan):
    require(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==plan['driver_process']['boot_id'],'Host boot identity changed')
    require(sha(__file__)==plan['postprocessor_sha256'],'Postprocessor source changed')
    require(sha(PYTHON)==plan['reporting_python']['sha256'],'Pinned reporting Python changed')
    checked_artifact(plan['execution'],'execution')
    pins=checked_artifact(plan['candidate_pins'],'candidate pins')
    require(pins['source_sha256']==plan['source_sha256'],'Candidate source identity differs')
    require(pins.get('execution_sha256')==plan['execution']['sha256'],'Candidate execution identity differs')
    require(pins.get('recovery_verifier_sha256')==plan['helpers']['recovery_evidence_09.py'],'Correction verifier pin differs')
    for name,key in (('validate_candidate_09.py','driver_sha256'),('with_correctness_namespace_09.py','wrapper_sha256')):
        require(sha(CONTROL/name)==pins[key],'Frozen candidate control changed: '+name)
    for name in HELPERS:require(sha(CONTROL/name)==plan['helpers'][name],'Evidence helper changed: '+name)
    return pins


def process_alive(identity):
    try:
        fields=(Path('/proc')/str(identity['pid'])/'stat').read_text().rsplit(')',1)[1].split()
    except FileNotFoundError:return False
    return int(fields[19])==identity['start_ticks'] and fields[0]!='Z'


def terminal_receipt(plan):
    path=RUN/'pipeline.json'
    if not path.is_file():return None
    value=read(path)
    if value.get('status') not in ('passed','failed') or not value.get('finished_at'):return None
    if value.get('final_cleanup',{}).get('verified') is not True:return None
    require(value.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'}
            and not any(value.get(k) for k in ('pause_receipt','resume_error','resume_withheld')),
            'Recovery terminal record must not claim campaign resume')
    pins=checked_artifact(plan['candidate_pins'],'terminal candidate pins')
    require(value.get('helper_sha256')==pins['driver_sha256'],'Executed driver identity differs')
    required=[('required_pins',plan['candidate_pins']),('execution',plan['execution']),
              ('wrapper',{'path':str(CONTROL/'with_correctness_namespace_09.py'),'sha256':pins['wrapper_sha256']})]
    for key,pin in required:
        item=value.get(key)
        require(isinstance(item,dict) and item.get('sha256')==pin['sha256'] and isinstance(item.get('path'),str)
                and Path(item['path']).resolve()==Path(pin['path']).resolve(),'Executed '+key+' differs from terminal control identity')
    admitted=value.get('admission') or {};identity=admitted.get('driver_identity') or {}
    require(admitted.get('status')=='admitted' and admitted.get('boot_id')==plan['driver_process']['boot_id']
            and all(identity.get(k)==plan['driver_process'][k] for k in ('pid','start_ticks')),
            'Terminal admission is not the exact watched validation driver')
    return value


def wait_for_terminal(plan,deadline,poll=5.):
    delay=poll
    while time.monotonic()<deadline:
        value=terminal_receipt(plan);alive=process_alive(plan['driver_process'])
        if value is not None and not alive:return value
        if not alive and value is None:raise RuntimeError('Driver exited without terminal verified owned cleanup; postprocessing not launched')
        time.sleep(min(delay,max(0.,deadline-time.monotonic())))
        delay=min(30.,delay*1.5)
    raise TimeoutError('Finite wait expired without terminal owned cleanup')


def source_identity(plan,deadline):
    files={}
    for path in sorted(SOURCE.rglob('*')):
        require(time.monotonic()<deadline,'Postprocess overall deadline exceeded during source verification')
        relative=path.relative_to(SOURCE)
        if relative.parts[0]=='.git':continue
        require(not path.is_symlink(),'Source snapshot contains a symlink')
        if path.is_file():files[str(relative)]=sha(path)
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    pins=read(plan['candidate_pins']['path'])
    require(digest==plan['source_sha256'] and len(files)==pins['source_file_count'],'Actual recovery source inventory changed')
    module_spec=importlib.util.spec_from_file_location('source_identity_recovery',CONTROL/'recovery_evidence_09.py')
    module=importlib.util.module_from_spec(module_spec);module_spec.loader.exec_module(module)
    frozen_path=module.host_path(pins['new_source_freeze']['path'],EXECUTION)
    require(sha(frozen_path)==pins['new_source_freeze']['sha256'],'Corrected source freeze changed')
    frozen=read(frozen_path)
    require(frozen.get('schema')=='orbit-poc-candidate09-source-freeze-v1'
            and frozen.get('commit')==plan['source_commit'],'Corrected source schema or commit differs')
    require(frozen.get('source')=={'files':files,'sha256':digest},'Actual snapshot differs from corrected candidate source')
    return {'commit':plan['source_commit'],'sha256':digest,'file_count':len(files)}


@contextmanager
def cleanup_signals():
    previous={number:signal.getsignal(number) for number in (signal.SIGINT,signal.SIGTERM)}
    for number in previous:signal.signal(number,signal.SIG_IGN)
    try:yield
    finally:
        for number,handler in previous.items():signal.signal(number,handler)


def run_stage(name,argv,output,deadline,journal,plan):
    verify_small_identities(plan)
    limit=min(600.,deadline-time.monotonic());require(limit>0,'Postprocess deadline expired')
    entry={'name':name,'argv':list(map(str,argv)),'started_at':now(),'timeout_seconds':limit,'status':'starting'}
    journal['steps'].append(entry);save(output/'pipeline.json',journal)
    child=None;started=time.monotonic()
    try:
        with (output/(name+'.log')).open('w') as log:
            child=subprocess.Popen(list(map(str,argv)),stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
                env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1'))
            entry['pid']=child.pid;save(output/'pipeline.json',journal)
            entry['returncode']=child.wait(timeout=limit)
            entry['status']='exited'
    except BaseException as error:
        entry.update(status='launch_timeout_or_execution_failure',error=type(error).__name__+': '+str(error))
        if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
    finally:
        # These allowlisted Python helpers execute no estimators or child jobs.
        # Signal only our still-owned new helper session, never campaign/driver.
        with cleanup_signals():
            if child is not None and child.poll() is None:
                try:os.killpg(child.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                child.wait(timeout=15)
            entry['cleanup_verified']=child is None or child.poll() is not None
            entry['elapsed_seconds']=time.monotonic()-started;entry['finished_at']=now()
            save(output/'pipeline.json',journal)
    verify_small_identities(plan)
    return entry


def interrupt(number,_frame):raise KeyboardInterrupt('Postprocess interrupted by signal '+str(number))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--plan-sha256',required=True)
    args=parser.parse_args(argv);plan=load_plan(args.plan,args.plan_sha256);output=Path(plan['output_root'])
    output.mkdir();journal={'schema':'orbit-poc-correctness-postprocess09-run-v1','status':'waiting','started_at':now(),
        'plan':artifact(args.plan),'reporting_interpreter':plan['reporting_python'],'reporting_version_provenance':'Observed versions supplied in reviewed plan; interpreter bytes checked before every helper. Scientific validation runtime is recorded independently in the execution configuration.','steps':[],'scientific_status':'not_assessed','scope':'Finite evidence processing only; no gate status upgrades, native fits, source changes, campaign signals or Git publication.'}
    deadline=time.monotonic()+plan['wait_seconds']
    try:
        for number in (signal.SIGINT,signal.SIGTERM):signal.signal(number,interrupt)
        save(output/'pipeline.json',journal);verify_small_identities(plan)
        terminal=wait_for_terminal(plan,deadline)
        journal.update(status='verifying_closed_evidence',validation_pipeline=artifact(RUN/'pipeline.json'),validation_status=terminal['status'])
        save(output/'pipeline.json',journal)
        journal['source']=source_identity(plan,deadline)
        require((terminal.get('source') or {}).get('sha256') in (None,plan['source_sha256']),'Executed source identity differs')
        audit_path=output/'independent-audit.json';report=output/'report';publication=output/'publication'
        prefix=['/usr/bin/taskset','-c',str(EXECUTION['fit_cpu']),PYTHON]
        commands=[('audit',prefix+[CONTROL/HELPERS[0],'--run',RUN,'--source',SOURCE,'--pins',plan['candidate_pins']['path'],'--output',audit_path],audit_path),
            ('report',prefix+[CONTROL/HELPERS[1],'--run',RUN,'--previous',PREVIOUS,'--control',CONTROL,'--audit',audit_path,'--output',report],report/'summary.json'),
            ('collect',prefix+[CONTROL/HELPERS[2],'--root',ROOT,'--run',RUN,'--control',CONTROL,'--source',SOURCE,'--binaries',EXECUTION['paths']['binaries'],'--previous',PREVIOUS,'--audit',audit_path,'--report',report,'--output',publication],publication/'manifest.json')]
        for name,command,result_path in commands:
            journal.update(status='running',phase=name)
            entry=run_stage(name,command,output,deadline,journal,plan)
            if result_path.is_file():
                try:
                    entry['result']=artifact(result_path);data=read(result_path)
                    entry['reported_outcome']=data.get('passed') if name=='audit' else data.get('candidate_evidence_status' if name=='report' else 'reported_evidence_status')
                    if name=='audit':
                        require(data.get('schema')=='orbit-poc-correctness-independent-audit09-v1' and type(data.get('passed')) is bool,'Audit result schema/pass flag invalid')
                        require(entry.get('returncode')==(0 if data['passed'] else 1),'Audit exit code contradicts its scientific outcome')
                    elif name=='report':
                        require(data.get('schema')=='orbit-correction-evidence-report09-v1','Report result schema invalid')
                    else:require(data.get('schema')=='orbit-poc-correctness-publication-bundle09-v1','Publication manifest schema invalid')
                except Exception as error:entry['result_error']=type(error).__name__+': '+str(error)
            else:entry['result_error']='Expected new result is missing'
            # Audit return1 with an actual failed audit is scientific evidence,
            # not grounds to hide later report and publication attempts.
            save(output/'pipeline.json',journal)
        if (report/'summary.json').is_file():journal['scientific_status']=read(report/'summary.json').get('candidate_evidence_status','invalid')
        completed=all('result' in step and not step.get('result_error') and step.get('cleanup_verified')
            and step.get('returncode') in ((0,1) if step['name']=='audit' else (0,)) for step in journal['steps'])
        if not completed and journal['scientific_status']=='passed_scoped_checks':journal['scientific_status']='not_verified'
        journal['status']='completed' if completed else 'failed'
    except BaseException as error:
        journal.update(status='failed',error=type(error).__name__+': '+str(error))
    finally:
        journal['finished_at']=now();save(output/'pipeline.json',journal)
    print(json.dumps({'status':journal['status'],'scientific_status':journal['scientific_status'],'output':str(output)}))
    return 0 if journal['status']=='completed' else 1

if __name__=='__main__':raise SystemExit(main())
