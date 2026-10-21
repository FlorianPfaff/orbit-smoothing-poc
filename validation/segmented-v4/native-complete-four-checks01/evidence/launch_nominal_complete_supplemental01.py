#!/usr/bin/env python3
"""Detach exactly one pinned validation driver; record its real host identity."""
import argparse,datetime,fcntl,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write_new(p,value):
    with p.open('x') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    fd=os.open(p.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def main():
    signal.signal(signal.SIGHUP,signal.SIG_IGN)
    p=argparse.ArgumentParser();p.add_argument('--execution',type=Path,required=True);p.add_argument('--pins',type=Path,required=True);p.add_argument('--pins-sha256',required=True);a=p.parse_args()
    if sha(a.pins)!=a.pins_sha256:raise RuntimeError('Sealed pins mismatch')
    pins=json.loads(a.pins.read_text());execution=json.loads(a.execution.read_text());paths=execution['paths'];control=Path(paths['control'])
    driver=control/'run_nominal_complete_supplemental01.py'
    if sha(driver)!=pins['driver_sha256'] or sha(a.execution)!=pins['execution_sha256'] or sha(pins['plan']['path'])!=pins['plan']['sha256']:raise RuntimeError('Launch controls changed')
    argv=[execution['runtime_artifacts']['control_python']['path'],str(driver),'--plan',pins['plan']['path'],'--sha256',pins['plan']['sha256']]
    with (control/'native-supplemental-launch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        receipt=control/'native-supplemental-launch.json'
        if receipt.exists():raise RuntimeError('Launch receipt already exists; no implicit retry')
        with (control/'native-supplemental-driver.log').open('x') as log:
            child=subprocess.Popen(argv,cwd=paths['source'],stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True,env=dict(os.environ,HOME='/home/florianpfaff',PYTHONDONTWRITEBYTECODE='1'))
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
                r={'schema':'orbit-poc-native-supplemental-detached-launch-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'driver_process':{'pid':child.pid,'start_ticks':int(fields[19]),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()},'argv':argv,'observed_argv':observed,'command_sha256':hashlib.sha256(raw).hexdigest(),'launch_helper_sha256':sha(__file__),'execution_sha256':sha(a.execution),'pins_sha256':a.pins_sha256,'stdin':'DEVNULL','stdout':str(control/'native-supplemental-driver.log'),'start_new_session':True,'poll_returncode_at_receipt':child.poll(),'campaign_resume':'not_applicable'}
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
                try:write_new(control/'native-supplemental-launch-failure.json',{'error':repr(error),'driver_pid':child.pid,'returncode':child.poll(),'hard_kill':hard_kill,'descendant_cleanup_verified':False,'note':'Inspect driver final_cleanup independently; launcher never certifies descendant cleanup.'})
                except OSError:pass
                raise
            # Receipt is durable. A disconnected SSH stdout must not cancel launch.
            try:print(json.dumps(r),flush=True)
            except (BrokenPipeError,OSError):sys.stdout=open(os.devnull,'w')
if __name__=='__main__':main()
