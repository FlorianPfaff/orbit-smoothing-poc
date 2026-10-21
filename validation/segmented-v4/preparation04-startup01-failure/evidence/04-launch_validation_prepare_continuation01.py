#!/usr/bin/env python3
"""Detach one pinned validation-to-preparation continuation; no fit is authorized."""
import argparse,datetime,fcntl,hashlib,importlib.util,json,os,signal,subprocess,sys,time
from pathlib import Path
KEYS={'schema','launcher','controller','control_python','plan','control_root'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def exact(v):
    if not isinstance(v,dict) or set(v)!={'path','sha256'} or not Path(v['path']).is_absolute() or sha(v['path'])!=v['sha256']:raise RuntimeError('Launch artifact changed')
def inspect(path,digest):
    if sha(path)!=digest:raise RuntimeError('Sealed launch pins mismatch')
    pins=json.loads(Path(path).read_text())
    if set(pins)!=KEYS or pins['schema']!='orbit-poc-segmented-continuation-launch-pins-v1':raise RuntimeError('Unknown continuation launch pins')
    for k in ('launcher','controller','control_python','plan'):exact(pins[k])
    if pins['launcher']['sha256']!=sha(__file__):raise RuntimeError('Launcher bytes changed')
    plan=json.loads(Path(pins['plan']['path']).read_text());control=Path(pins['control_root'])
    if not control.is_absolute() or not control.is_dir() or control.is_symlink() or plan['control_root']!=str(control):raise RuntimeError('Continuation control root differs')
    if plan['helper']!=pins['controller'] or plan['control_python']!=pins['control_python']:raise RuntimeError('Host controller/interpreter identity differs')
    if pins['control_python']['sha256']!=sha(Path(sys.executable).resolve()):raise RuntimeError('Launcher interpreter differs')
    if set(os.sched_getaffinity(0))!={32}:raise RuntimeError('Continuation launch must use observer CPU32')
    for name in ('continuation-launch.json','continuation-driver.log','pipeline.json'):
        if (control/name).exists() or (control/name).is_symlink():raise RuntimeError('Preserve earlier continuation launch/output')
    spec=importlib.util.spec_from_file_location('pinned_one_shot_controller',pins['controller']['path']);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    if m.load_plan(pins['plan']['path'],pins['plan']['sha256'])!=plan:raise RuntimeError('Host plan validation differs')
    return pins,plan,control

def write_new(p,value):
    with p.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def main():
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    p=argparse.ArgumentParser();p.add_argument('--pins',type=Path,required=True);p.add_argument('--pins-sha256',required=True);a=p.parse_args();pins,plan,control=inspect(a.pins,a.pins_sha256)
    argv=[pins['control_python']['path'],'-B',pins['controller']['path'],'--plan',pins['plan']['path'],'--sha256',pins['plan']['sha256']]
    with (control/'continuation-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=control/'continuation-launch.json'
        if receipt.exists():raise RuntimeError('Launch receipt already exists; no implicit retry')
        with (control/'continuation-driver.log').open('x') as log:
            child=subprocess.Popen(argv,cwd=control,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True,env={'PATH':'/usr/bin:/bin','PYTHONDONTWRITEBYTECODE':'1','HOME':str(control)})
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
                r={'schema':'orbit-poc-segmented-continuation-detached-launch-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'driver_process':{'pid':child.pid,'start_ticks':int(fields[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'argv':argv,'observed_argv':observed,'command_sha256':hashlib.sha256(raw).hexdigest(),'launch_helper_sha256':sha(__file__),'plan':pins['plan'],'pins_sha256':a.pins_sha256,'stdin':'DEVNULL','stdout':str(control/'continuation-driver.log'),'start_new_session':True,'poll_returncode_at_receipt':child.poll(),'starting_checkpoint_policy':'The pinned one-shot controller waits for exact validation termination and requires the independent terminal audit plus actual startup before preparation only. No fits or scientific success are authorized by this launch.'}
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
                try:write_new(control/'continuation-launch-failure.json',{'error':repr(error),'driver_pid':child.pid,'returncode':child.poll(),'hard_kill':hard_kill,'descendant_cleanup_verified':False,'note':'Inspect driver final_cleanup independently; launcher never certifies descendant cleanup.'})
                except OSError:pass
                raise
            # Receipt is durable. A disconnected SSH stdout must not cancel launch.
            try:print(json.dumps(r),flush=True)
            except (BrokenPipeError,OSError):sys.stdout=open(os.devnull,'w')
if __name__=='__main__':main()
