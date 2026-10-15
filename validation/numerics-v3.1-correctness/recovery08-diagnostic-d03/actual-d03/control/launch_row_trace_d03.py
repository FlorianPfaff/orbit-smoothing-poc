#!/usr/bin/env python3
"""Detach one pinned D03 diagnostic after its terminal-state namespace proof."""
import argparse,datetime,fcntl,hashlib,importlib.util,json,os,signal,subprocess,sys,time
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_new(p,value):
    with p.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def checked(pin):
    if set(pin)!={'path','sha256'} or not Path(pin['path']).is_absolute() or sha(pin['path'])!=pin['sha256']:
        raise RuntimeError('Pinned artifact changed: '+str(pin.get('path')))
def validated(a):
    if sha(a.plan)!=a.plan_sha256:raise RuntimeError('Sealed plan mismatch')
    if sha(a.execution)!=a.execution_sha256:raise RuntimeError('Sealed execution mismatch')
    if sha(a.smoke)!=a.smoke_sha256:raise RuntimeError('Sealed smoke mismatch')
    plan=json.loads(a.plan.read_text());smoke=json.loads(a.smoke.read_text())
    if set(plan)!={'schema','runner','execution','driver','source_freeze','helpers','inputs','input_links','prior_pipeline','prior_postprocess','last_generation'}:raise RuntimeError('Unknown plan fields')
    if plan.get('schema')!='orbit-poc-diagnostic-row-trace-plan-v2' or plan.get('last_generation')!=4:raise RuntimeError('Wrong diagnostic scope')
    execution_pin={'path':str(a.execution),'sha256':a.execution_sha256};plan_pin={'path':str(a.plan),'sha256':a.plan_sha256}
    if plan['execution']!=execution_pin or smoke.get('execution')!=execution_pin or smoke.get('plan')!=plan_pin:raise RuntimeError('Smoke/plan/execution attribution differs')
    for key in ('runner','driver','source_freeze','prior_pipeline','prior_postprocess'):checked(plan[key])
    for pin in (*plan['helpers'].values(),*plan['inputs'].values()):checked(pin)
    if (smoke.get('schema')!='orbit-poc-d03-namespace-smoke-v1' or smoke.get('passed') is not True or
        smoke.get('cleanup',{}).get('verified') is not True or smoke.get('production_mutable_directories_absent') is not True or
        smoke.get('scientific_validation_complete') is not False):raise RuntimeError('Namespace proof is not passed, clean and diagnostic-only')
    checked(smoke['helper']);checked(smoke['upstream_helper']);checked(smoke['upstream_reference'])
    prior=json.loads(Path(plan['prior_pipeline']['path']).read_text());post=json.loads(Path(plan['prior_postprocess']['path']).read_text())
    if not (prior.get('status')=='failed' and prior.get('finished_at') and prior.get('final_cleanup',{}).get('verified') is True):raise RuntimeError('Original validation is not terminal and clean')
    if not (post.get('status') in ('completed','failed') and post.get('finished_at') and post.get('steps') and all(s.get('cleanup_verified') is True for s in post['steps'])):raise RuntimeError('Original postprocessor is not terminal and clean')
    if post.get('validation_pipeline',{}).get('sha256')!=plan['prior_pipeline']['sha256']:raise RuntimeError('Postprocessor attribution differs')
    spec=importlib.util.spec_from_file_location('d03_launch_owned_driver',plan['driver']['path']);d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
    execution=d.load_execution(a.execution);paths=execution['paths']
    control_python=execution['runtime_artifacts']['control_python'];checked(control_python)
    if sha(sys.executable)!=control_python['sha256']:raise RuntimeError('Use the pinned control interpreter')
    if {'path':paths['wrapper'],'sha256':sha(paths['wrapper'])}!=plan['helpers']['wrapper']:raise RuntimeError('Wrapper identity differs')
    for key in ('native_source','build','binaries','run','temporary'):
        target=Path(paths[key])
        if target.exists() or target.is_symlink():raise RuntimeError('Fresh production output required: '+key)
    admission=d.admission(execution)
    if smoke.get('admission',{}).get('hostname')!=admission['hostname'] or smoke.get('admission',{}).get('boot_id')!=admission['boot_id']:raise RuntimeError('Namespace proof belongs to another host/boot')
    return execution,plan,admission

def main():
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('execution','plan','smoke'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('execution-sha256','plan-sha256','smoke-sha256'):p.add_argument('--'+name,required=True)
    a=p.parse_args();execution,plan,admission=validated(a);paths=execution['paths'];control=Path(paths['control'])
    runner=plan['runner']['path']
    argv=[execution['runtime_artifacts']['control_python']['path'],runner,'--plan',str(a.plan),'--sha256',a.plan_sha256]
    with (control/'diagnostic-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=control/'diagnostic-launch.json'
        if receipt.exists():raise RuntimeError('Launch receipt already exists; no implicit retry')
        with (control/'diagnostic-driver.log').open('x') as log:
            child=subprocess.Popen(argv,cwd=paths['source'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            # Popen confirms exec success; start_new_session isolates it from SSH.
            try:
                proc=Path('/proc')/str(child.pid)
                fields=(proc/'stat').read_text().rsplit(')',1)[1].split()
                start_ticks=int(fields[19]);handoff_deadline=time.monotonic()+5.0
                while True:
                    current=(proc/'stat').read_text().rsplit(')',1)[1].split()
                    if int(current[19])!=start_ticks:raise RuntimeError('Driver identity changed during launch handoff')
                    raw=(proc/'cmdline').read_bytes();observed=[x.decode() for x in raw.split(b'\0') if x]
                    if observed==argv:break
                    if observed:raise RuntimeError('Nonempty driver command identity differs during launch handoff: observed='+repr(observed)+' poll_returncode='+repr(child.poll()))
                    if child.poll() is not None:raise RuntimeError('Driver exited before launch handoff')
                    if time.monotonic()>=handoff_deadline:raise RuntimeError('Driver identity handoff timed out')
                    time.sleep(0.01)
                r={'schema':'orbit-poc-d03-detached-launch-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'driver_process':{'pid':child.pid,'start_ticks':int(fields[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'argv':argv,'observed_argv':observed,'command_sha256':hashlib.sha256(raw).hexdigest(),'launch_helper_sha256':sha(__file__),'execution_sha256':sha(a.execution),'plan_sha256':a.plan_sha256,'smoke':{'path':str(a.smoke),'sha256':a.smoke_sha256},'runner':plan['runner'],'admission':admission,'diagnostic_only':True,'scientific_validation_complete':False,'stdin':'DEVNULL','stdout':str(control/'diagnostic-driver.log'),'start_new_session':True,'poll_returncode_at_receipt':child.poll(),'campaign_resume':'not_applicable'}
                if observed!=argv:raise RuntimeError('Driver command identity differs before receipt handoff: observed='+repr(observed)+' poll_returncode='+repr(child.poll()))
                r['launch_committed']=True
                write_new(receipt,r)
            except BaseException as error:
                hard_kill=False
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        hard_kill=True;child.kill();child.wait(timeout=30)
                try:write_new(control/'diagnostic-launch-failure.json',{'error':repr(error),'driver_pid':child.pid,'returncode':child.poll(),'hard_kill':hard_kill,'descendant_cleanup_verified':False,'note':'Inspect driver final_cleanup independently; launcher never certifies descendant cleanup.'})
                except OSError:pass
                raise
            # Receipt is durable. A disconnected SSH stdout must not cancel launch.
            try:print(json.dumps(r),flush=True)
            except (BrokenPipeError,OSError):sys.stdout=open(os.devnull,'w')
if __name__=='__main__':main()
