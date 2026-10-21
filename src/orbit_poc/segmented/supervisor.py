"""Dedicated Linux subreaper for exactly one bounded v4 worker tree.

Only descendants of this dedicated process can become owned. Signals use
kernel pidfds after a start-tick identity check; numeric PID/PGID signals are
never used. A reparented child remains owned even after an immediate setsid().
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import time

import psutil


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value,*,new=False):
    path=Path(path);target=path if new else path.with_name(path.name+".writing")
    with target.open("x" if new else "w") as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write("\n")
        stream.flush();os.fsync(stream.fileno())
    if not new:target.replace(path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def process(pid):
    fields=(Path("/proc")/str(pid)/"stat").read_text().rsplit(")",1)[1].split()
    return {"pid":int(pid),"parent":int(fields[1]),"start_ticks":int(fields[19]),"state":fields[0]}


def _syscall(number,*args):
    # The selected hosts use these Linux generic syscall numbers. Refuse any
    # other ABI rather than guessing or falling back to numeric signals.
    if sys.platform!="linux" or platform.machine() not in ("x86_64","aarch64") or ctypes.sizeof(ctypes.c_void_p)!=8:
        raise RuntimeError("Linux64 x86_64/aarch64 pidfd ABI is required")
    libc=ctypes.CDLL(None,use_errno=True);libc.syscall.restype=ctypes.c_long
    value=libc.syscall(ctypes.c_long(number),*[ctypes.c_long(a) for a in args])
    if value<0:
        code=ctypes.get_errno();raise OSError(code,os.strerror(code))
    return int(value)


class Pidfd:
    def __init__(self,pid,expected_start=None):
        self.fd=None
        before=process(pid)
        if expected_start is not None and before["start_ticks"]!=expected_start:
            raise ProcessLookupError("Owned PID identity changed")
        fd=_syscall(434,pid,0)  # pidfd_open(pid, flags)
        try:
            after=process(pid)
            if before["start_ticks"]!=after["start_ticks"]:
                raise ProcessLookupError("PID changed while opening its pidfd")
        except BaseException:
            os.close(fd);raise
        self.fd=fd;self.identity=after

    def send(self,number):
        if self.fd is None:raise RuntimeError("Closed pidfd")
        try:_syscall(424,self.fd,number,0,0)  # pidfd_send_signal(fd, sig, NULL, flags)
        except ProcessLookupError:pass

    def close(self):
        if self.fd is not None:os.close(self.fd);self.fd=None


def capability_check():
    handle=Pidfd(os.getpid())
    try:handle.send(0)
    finally:handle.close()


def subreaper():
    capability_check()
    libc=ctypes.CDLL(None,use_errno=True)
    if libc.prctl(36,1,0,0,0)!=0:raise OSError(ctypes.get_errno(),"PR_SET_CHILD_SUBREAPER failed")
    value=ctypes.c_int()
    if libc.prctl(37,ctypes.byref(value),0,0,0)!=0 or value.value!=1:
        raise RuntimeError("Cannot verify dedicated subreaper")


def descendants():
    rows={}
    for path in Path("/proc").glob("[0-9]*"):
        try:rows[int(path.name)]=process(int(path.name))
        except (FileNotFoundError,ProcessLookupError):pass
    owned={os.getpid()}
    while True:
        more={pid for pid,row in rows.items() if row["parent"] in owned}
        if more<=owned:break
        owned|=more
    return [rows[pid] for pid in sorted(owned-{os.getpid()})]


def reap(child):
    while True:
        try:
            pid,status=os.waitpid(-1,os.WNOHANG)
            if not pid:return
            if child is not None and pid==child.pid:child.returncode=os.waitstatus_to_exitcode(status)
        except ChildProcessError:return


def send_owned(row,number):
    try:handle=Pidfd(row["pid"],row["start_ticks"])
    except (FileNotFoundError,ProcessLookupError):return False
    try:handle.send(number)
    finally:handle.close()
    return True


def no_owned_children(child):
    """Only kernel ECHILD certifies an empty dedicated subreaper tree.

    A /proc enumeration may miss a child forked during that enumeration. If a
    direct child remains, or a zombie was just reaped, take another snapshot.
    Every live descendant has a direct-child ancestor or is adopted here.
    """
    try:
        pid,status=os.waitpid(-1,os.WNOHANG)
        if child is not None and pid==child.pid:
            child.returncode=os.waitstatus_to_exitcode(status)
        return False
    except ChildProcessError:
        return True


def cleanup(child,registry,*,grace_seconds=3.):
    started=time.monotonic();hard=False;signals=[]
    while True:
        reap(child);rows=descendants()
        direct=[row for row in rows if row["parent"]==os.getpid()]
        for row in direct:registry[(row["pid"],row["start_ticks"])]=row
        if not rows and no_owned_children(child):
            return {"verified":True,"hard_kill":hard,"remaining":[],"signals":signals,
                    "empty_tree_certificate":"kernel_ECHILD"}
        elapsed=time.monotonic()-started
        if elapsed>=grace_seconds+5.:
            return {"verified":False,"hard_kill":hard,"remaining":rows,"signals":signals}
        number=signal.SIGTERM if elapsed<grace_seconds else signal.SIGKILL
        hard|=number==signal.SIGKILL
        # Recursive /proc ancestry is non-atomic. A reused intermediate PID
        # must never authorize signalling an unrelated descendant. Only this
        # dedicated subreaper's direct children are attributable; after their
        # parents exit, remaining descendants are adopted and handled here.
        for row in direct:
            if row["state"]!="Z" and send_owned(row,number):
                signals.append({"pid":row["pid"],"start_ticks":row["start_ticks"],"signal":int(number)})
        time.sleep(.02)


PLAN_KEYS={"schema","argv","cwd","log_path","receipt_path","working_directory","timeout_seconds",
           "max_process_tree_rss_bytes","min_free_disk_bytes","helper_sha256","boot_id"}


def checked_plan(path,sha):
    if digest(path)!=sha:raise ValueError("Worker supervision plan changed")
    value=json.loads(Path(path).read_text())
    if set(value)!=PLAN_KEYS or value["schema"]!="orbit-poc-segmented-supervision-plan-v1":
        raise ValueError("Unknown supervision plan")
    if (not isinstance(value["argv"],list) or not value["argv"]
            or any(not isinstance(x,str) or "\0" in x for x in value["argv"])
            or any(not Path(value[x]).is_absolute() for x in ("cwd","log_path","receipt_path","working_directory"))):
        raise ValueError("Invalid worker argv or absolute paths")
    if (type(value["timeout_seconds"]) not in (int,float) or not math.isfinite(value["timeout_seconds"])
            or value["timeout_seconds"]<=0
            or any(type(value[k]) is not int or value[k]<0 for k in ("max_process_tree_rss_bytes","min_free_disk_bytes"))
            or value["max_process_tree_rss_bytes"]==0):
        raise ValueError("Invalid supervision resource limits")
    if value["helper_sha256"]!=digest(__file__) or value["boot_id"]!=Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise ValueError("Supervisor source or current boot changed")
    return value


def supervise(path,sha):
    plan=checked_plan(path,sha);subreaper()
    state={"schema":"orbit-poc-segmented-supervision-v1","status":"running","plan_sha256":sha,
           "supervisor":process(os.getpid()),"boot_id":plan["boot_id"],"helper_sha256":plan["helper_sha256"],
           "argv":plan["argv"],"returncode":None,"peak_process_tree_rss_bytes":0,
           "owned_process_group_cleaned":False,"signals_received":[]}
    save(plan["receipt_path"],state,new=True)
    def interrupted(number,_):state["signals_received"].append(number)
    for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(number,interrupted)
    child=None;registry={};started=time.monotonic();next_save=started
    try:
        with Path(plan["log_path"]).open("x") as stream:
            child=subprocess.Popen(plan["argv"],cwd=plan["cwd"],env=os.environ.copy(),stdin=subprocess.DEVNULL,
                                   stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
            state["worker"]=process(child.pid);save(plan["receipt_path"],state)
            while True:
                rows=descendants();rss=0
                for row in rows:
                    if row["parent"]==os.getpid():
                        registry[(row["pid"],row["start_ticks"])]=row
                    try:
                        handle=psutil.Process(row["pid"])
                        if process(row["pid"])["start_ticks"]==row["start_ticks"]:rss+=handle.memory_info().rss
                    except (FileNotFoundError,ProcessLookupError,psutil.NoSuchProcess):pass
                state["peak_process_tree_rss_bytes"]=max(state["peak_process_tree_rss_bytes"],rss)
                elapsed=time.monotonic()-started
                if state["signals_received"]:state["status"]="interrupted";break
                if elapsed>=plan["timeout_seconds"]:state["status"]="timeout";break
                if rss>plan["max_process_tree_rss_bytes"]:state["status"]="memory_limit";break
                if psutil.disk_usage(plan["working_directory"]).free<plan["min_free_disk_bytes"]:state["status"]="disk_limit";break
                if child.poll() is not None:
                    state["status"]="complete" if child.returncode==0 else "failed";break
                reap(child)
                if time.monotonic()>=next_save:
                    state["elapsed_seconds"]=elapsed;state["tracked_owned_processes"]=list(registry.values())
                    save(plan["receipt_path"],state);next_save=time.monotonic()+1.
                time.sleep(.02)
    except BaseException as error:
        state.update(status="failed",error=type(error).__name__+": "+str(error))
    finally:
        for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):signal.signal(number,signal.SIG_IGN)
        try:
            cleaned=cleanup(child,registry)
        except BaseException as error:
            cleaned={"verified":False,"remaining":descendants(),"error":repr(error)}
        state.update(cleanup=cleaned,owned_process_group_cleaned=cleaned["verified"],
                     tracked_owned_processes=list(registry.values()),elapsed_seconds=time.monotonic()-started,
                     returncode=None if child is None else child.poll())
        if not cleaned["verified"]:state.update(status="failed",error="Owned descendant cleanup was not verified")
        save(plan["receipt_path"],state)
    return 0 if state["status"]=="complete" else 1


def run_owned(argv,*,python_executable,cwd,env,log_path,receipt_path,timeout_seconds,
              max_process_tree_rss_bytes,min_free_disk_bytes,working_directory):
    """Launch the dedicated helper, wait, and verify its terminal attribution.

    The helper receives only the existing worker environment, not serialized
    credentials. Its own descendants are the only processes it ever signals.
    """
    capability_check()
    receipt_path=Path(receipt_path).absolute();plan_path=receipt_path.with_name(receipt_path.stem+".plan.json")
    control_log=receipt_path.with_name(receipt_path.stem+".log")
    for path in (receipt_path,plan_path,control_log,Path(log_path)):
        if path.exists():raise ValueError("Preserve existing worker supervision evidence")
    plan={"schema":"orbit-poc-segmented-supervision-plan-v1","argv":list(map(str,argv)),"cwd":str(Path(cwd).absolute()),
          "log_path":str(Path(log_path).absolute()),"receipt_path":str(receipt_path),"working_directory":str(Path(working_directory).absolute()),
          "timeout_seconds":timeout_seconds,"max_process_tree_rss_bytes":max_process_tree_rss_bytes,"min_free_disk_bytes":min_free_disk_bytes,
          "helper_sha256":digest(__file__),"boot_id":Path("/proc/sys/kernel/random/boot_id").read_text().strip()}
    save(plan_path,plan,new=True);sha=digest(plan_path);checked_plan(plan_path,sha)
    command=[str(python_executable),"-s",str(Path(__file__).resolve()),"--plan",str(plan_path),"--sha256",sha]
    with control_log.open("x") as stream:
        child=subprocess.Popen(command,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=stream,
                               stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
        handle=Pidfd(child.pid);identity=handle.identity
        interrupted=False;handlers={}
        class ControlInterrupted(BaseException):pass
        def control_interrupted(number,_):raise ControlInterrupted(number)
        try:
            for number in (signal.SIGINT,signal.SIGTERM,signal.SIGHUP):
                handlers[number]=signal.getsignal(number);signal.signal(number,control_interrupted)
            try:child.wait(timeout=float(timeout_seconds)+30.)
            except (KeyboardInterrupt,SystemExit,ControlInterrupted,subprocess.TimeoutExpired):
                interrupted=True;handle.send(signal.SIGTERM)
                for number in handlers:signal.signal(number,signal.SIG_IGN)
                try:child.wait(timeout=12.)
                except subprocess.TimeoutExpired:
                    handle.send(signal.SIGKILL);child.wait(timeout=5.)
        finally:
            for number,handler in handlers.items():signal.signal(number,handler)
            handle.close()
    if not receipt_path.is_file():
        raise RuntimeError("Supervisor produced no ownership receipt; cleanup is unverified")
    value=json.loads(receipt_path.read_text())
    if (value.get("schema")!="orbit-poc-segmented-supervision-v1" or value.get("plan_sha256")!=sha
            or value.get("helper_sha256")!=plan["helper_sha256"] or value.get("boot_id")!=plan["boot_id"]
            or value.get("supervisor",{}).get("pid")!=identity["pid"]
            or value["supervisor"].get("start_ticks")!=identity["start_ticks"]
            or value.get("argv")!=plan["argv"] or value.get("status")=="running"
            or value.get("cleanup",{}).get("verified") is not True
            or value.get("owned_process_group_cleaned") is not True):
        raise RuntimeError("Supervisor identity or terminal descendant cleanup was not verified")
    if child.returncode!= (0 if value["status"]=="complete" else 1):
        raise RuntimeError("Supervisor exit and terminal receipt disagree")
    if interrupted and value["status"]=="complete":
        value={**value,"status":"interrupted","caller_interrupted":True}
    return value


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--plan",type=Path,required=True);parser.add_argument("--sha256",required=True)
    args=parser.parse_args();sys.exit(supervise(args.plan,args.sha256))
