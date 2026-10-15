"""Real isolated ownership, immediate orphan, limits and PID reuse fixtures."""
import json,os,signal,subprocess,sys,time
from pathlib import Path

import pytest

from orbit_poc.segmented import supervisor as s


def run(tmp_path,code,*,timeout=5.,memory=512*1024**2):
    return s.run_owned([sys.executable,"-c",code],python_executable=sys.executable,
        cwd=tmp_path,env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"),
        log_path=tmp_path/"worker.log",receipt_path=tmp_path/"supervision.json",
        timeout_seconds=timeout,max_process_tree_rss_bytes=memory,min_free_disk_bytes=0,
        working_directory=tmp_path)


@pytest.mark.parametrize("status",[0,7])
def test_exit_code_and_verified_cleanup_are_preserved(tmp_path,status):
    value=run(tmp_path,f"raise SystemExit({status})")
    assert value["returncode"]==status
    assert value["status"]==("complete" if status==0 else "failed")
    assert value["owned_process_group_cleaned"] is True and value["cleanup"]["remaining"]==[]
    assert Path(tmp_path/"supervision.plan.json").is_file()
    with pytest.raises(ValueError,match="Preserve"):
        run(tmp_path,"raise SystemExit(0)")


ORPHAN=r'''import os,json,time
from pathlib import Path
r,w=os.pipe()
first=os.fork()
if first:
    os.close(w);os.read(r,1);os._exit(0)
os.close(r);os.setsid()
second=os.fork()
if second:os._exit(0)
Path('orphan.json').write_text(json.dumps({'pid':os.getpid(),'start_ticks':int(Path('/proc/self/stat').read_text().rsplit(')',1)[1].split()[19])}))
os.write(w,b'1');os.close(w)
while True:time.sleep(1)
'''


def test_immediate_double_fork_setsid_orphan_is_adopted_and_unrelated_process_survives(tmp_path):
    unrelated=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],start_new_session=True)
    owned=s.Pidfd(unrelated.pid)
    try:
        result=run(tmp_path,ORPHAN)
        orphan=json.loads((tmp_path/"orphan.json").read_text())
        assert result["status"]=="complete" and result["owned_process_group_cleaned"]
        assert any(row["pid"]==orphan["pid"] and row["start_ticks"]==orphan["start_ticks"] for row in result["tracked_owned_processes"])
        try:assert s.process(orphan["pid"])["start_ticks"]!=orphan["start_ticks"]
        except FileNotFoundError:pass
        assert unrelated.poll() is None
        assert all(row["pid"]!=unrelated.pid for row in result["tracked_owned_processes"])
        assert all(row["pid"]!=unrelated.pid for row in result["cleanup"]["signals"])
    finally:
        owned.send(signal.SIGTERM);unrelated.wait(timeout=5);owned.close()


def test_timeout_cleans_the_owned_tree(tmp_path):
    result=run(tmp_path,"import time;time.sleep(30)",timeout=.2)
    assert result["status"]=="timeout" and result["owned_process_group_cleaned"]
    assert result["returncode"]==-signal.SIGTERM
    assert result["elapsed_seconds"]<5.


def test_memory_limit_is_on_the_whole_descendant_tree(tmp_path):
    code="""import os,time
for _ in range(2):
    if os.fork()==0:
        a=bytearray(48*1024**2)
        while True:time.sleep(1)
while True:time.sleep(1)
"""
    result=run(tmp_path,code,memory=80*1024**2)
    assert result["status"]=="memory_limit" and result["owned_process_group_cleaned"]
    assert result["peak_process_tree_rss_bytes"]>80*1024**2
    assert len(result["tracked_owned_processes"])>=3


def test_reused_pid_is_never_signalled(monkeypatch):
    calls=[]
    monkeypatch.setattr(s,"process",lambda pid:{"pid":pid,"start_ticks":22,"state":"S"})
    monkeypatch.setattr(s,"_syscall",lambda *args:calls.append(args))
    assert s.send_owned({"pid":123,"start_ticks":11},signal.SIGKILL) is False
    assert calls==[]


def test_stale_intermediate_parent_never_authorizes_an_unrelated_signal(monkeypatch):
    direct={"pid":123,"parent":os.getpid(),"start_ticks":11,"state":"S"}
    unrelated={"pid":124,"parent":123,"start_ticks":22,"state":"S"}
    snapshots=iter([[direct,unrelated],[]]);sent=[];registry={}
    monkeypatch.setattr(s,"descendants",lambda:next(snapshots))
    monkeypatch.setattr(s,"reap",lambda child:None)
    monkeypatch.setattr(s,"no_owned_children",lambda child:True)
    monkeypatch.setattr(s,"send_owned",lambda row,number:sent.append(row["pid"]) or True)
    monkeypatch.setattr(s.time,"sleep",lambda duration:None)
    result=s.cleanup(None,registry)
    assert result["verified"] and sent==[123]
    assert list(registry)==[(123,11)]


def test_reuse_during_pidfd_open_closes_descriptor_without_sending(monkeypatch):
    states=iter([{"pid":123,"start_ticks":11},{"pid":123,"start_ticks":22}]);calls=[];closed=[]
    monkeypatch.setattr(s,"process",lambda pid:next(states))
    monkeypatch.setattr(s,"_syscall",lambda *args:(calls.append(args),999)[1])
    monkeypatch.setattr(s.os,"close",lambda fd:closed.append(fd))
    assert s.send_owned({"pid":123,"start_ticks":11},signal.SIGKILL) is False
    assert calls==[(434,123,0)] and closed==[999]


def test_missing_pidfd_capability_blocks_launch_without_numeric_fallback(tmp_path,monkeypatch):
    monkeypatch.setattr(s,"capability_check",lambda:(_ for _ in ()).throw(OSError("pidfds unavailable")))
    monkeypatch.setattr(s.subprocess,"Popen",lambda *a,**kw:pytest.fail("A worker must not launch"))
    with pytest.raises(OSError,match="pidfds unavailable"):
        run(tmp_path,"pass")
    assert not list(tmp_path.iterdir())


def test_parent_sigterm_requests_owned_cleanup_before_return(tmp_path):
    source=Path(__file__).resolve().parents[1]/"src"
    code="""import json,os,sys
from pathlib import Path
from orbit_poc.segmented.supervisor import run_owned
p=Path(sys.argv[1])
v=run_owned([sys.executable,'-c','import time;time.sleep(30)'],python_executable=sys.executable,cwd=p,
 env=os.environ.copy(),log_path=p/'worker.log',receipt_path=p/'supervision.json',
 timeout_seconds=20.,max_process_tree_rss_bytes=536870912,min_free_disk_bytes=0,working_directory=p)
(p/'returned.json').write_text(json.dumps(v))
"""
    caller=subprocess.Popen([sys.executable,"-c",code,str(tmp_path)],env=dict(os.environ,PYTHONPATH=str(source)),start_new_session=True)
    handle=s.Pidfd(caller.pid)
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            path=tmp_path/"supervision.json"
            if path.exists() and "worker" in json.loads(path.read_text()):break
            if caller.poll() is not None:pytest.fail("Caller exited before interruption fixture")
            time.sleep(.02)
        else:pytest.fail("Owned worker did not launch")
        handle.send(signal.SIGTERM);caller.wait(timeout=15)
        result=json.loads((tmp_path/"returned.json").read_text())
        assert result["status"]=="interrupted" and result["owned_process_group_cleaned"]
        assert result["signals_received"]==[signal.SIGTERM]
    finally:
        if caller.poll() is None:handle.send(signal.SIGTERM);caller.wait(timeout=15)
        handle.close()


def test_empty_proc_snapshot_cannot_certify_a_live_adopted_child(tmp_path):
    # Isolate the subreaper from pytest and any unrelated caller children.
    source=Path(__file__).resolve().parents[1]/"src"
    code=r'''import json,os,subprocess,sys
from pathlib import Path
from orbit_poc.segmented import supervisor as s
s.subreaper()
child=subprocess.Popen([sys.executable,'-c',sys.argv[1]])
child.wait(timeout=5)
orphan=json.loads(Path('orphan.json').read_text())
real_descendants=s.descendants
snapshots=0
def missed_snapshot():
    global snapshots
    snapshots+=1
    return [] if snapshots==1 else real_descendants()
s.descendants=missed_snapshot
registry={}
result=s.cleanup(child,registry)
try:alive=s.process(orphan['pid'])['start_ticks']==orphan['start_ticks']
except FileNotFoundError:alive=False
print(json.dumps({'cleanup':result,'snapshots':snapshots,'orphan_alive':alive,
                  'tracked':list(registry.values())}))
'''
    result=subprocess.run([sys.executable,"-c",code,ORPHAN],cwd=tmp_path,
        env=dict(os.environ,PYTHONPATH=str(source)),capture_output=True,text=True,timeout=15,check=True)
    value=json.loads(result.stdout)
    assert value["snapshots"]>=2
    assert value["cleanup"]["verified"] and value["cleanup"]["empty_tree_certificate"]=="kernel_ECHILD"
    assert value["orphan_alive"] is False and len(value["tracked"])>=1
