#!/usr/bin/env python3
"""Durably supervise the unchanged frozen campaign, owning only our descendants."""
import argparse
import ctypes
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def save(path, value, *, new=False):
    target = path if new else path.with_suffix(path.suffix + '.writing')
    with target.open('x' if new else 'w') as stream:
        json.dump(value, stream, indent=2); stream.write('\n')
        stream.flush(); os.fsync(stream.fileno())
    if not new:
        target.replace(path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def proc(pid):
    fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
    return {'pid': pid, 'parent': int(fields[1]), 'start_ticks': int(fields[19]), 'state': fields[0]}


def descendants():
    rows = {}
    for p in Path('/proc').glob('[0-9]*'):
        try:
            row = proc(int(p.name)); rows[row['pid']] = row
        except (FileNotFoundError, ProcessLookupError):
            pass
    owned = {os.getpid()}
    while True:
        more = {pid for pid, row in rows.items() if row['parent'] in owned}
        if more <= owned:
            break
        owned |= more
    return [rows[pid] for pid in sorted(owned - {os.getpid()})]


def send_owned(row, number):
    try:
        fd = os.pidfd_open(row['pid'])
    except ProcessLookupError:
        return
    try:
        current = proc(row['pid'])
        if current['start_ticks'] != row['start_ticks']:
            raise RuntimeError('Owned PID identity changed')
        signal.pidfd_send_signal(fd, number)
    except (FileNotFoundError, ProcessLookupError):
        pass
    finally:
        os.close(fd)


def reap():
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                return
        except ChildProcessError:
            return


def cleanup(grace=30.0):
    initial = descendants()
    for row in initial:
        send_owned(row, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        reap()
        if not descendants():
            return {'verified': True, 'initial': initial, 'hard_kill': False, 'remaining': []}
        time.sleep(.05)
    for row in descendants():
        send_owned(row, signal.SIGKILL)
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        reap()
        if not descendants():
            return {'verified': True, 'initial': initial, 'hard_kill': True, 'remaining': []}
        time.sleep(.05)
    return {'verified': False, 'initial': initial, 'hard_kill': True, 'remaining': descendants()}


def checked_plan(path, digest):
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Control interpreter lacks required pidfd ownership APIs')
    if sha(path) != digest:
        raise RuntimeError('Plan hash changed')
    p = json.loads(path.read_text())
    if set(p) != {'schema','root','command','environment','cwd','artifacts','helper_sha256','boot_id'} or p['schema'] != 'original150-resume-plan-v1':
        raise RuntimeError('Unknown resume plan')
    if p['helper_sha256'] != sha(__file__) or p['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
        raise RuntimeError('Helper or host boot changed')
    for pin in p['artifacts']:
        if set(pin) != {'path','sha256'} or sha(pin['path']) != pin['sha256']:
            raise RuntimeError('Pinned recovery artifact changed')
    return p


def supervise(path, digest):
    plan = checked_plan(path, digest); root = Path(plan['root'])
    # Orphaned grandchildren remain owned even if their worker creates a session.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'PR_SET_CHILD_SUBREAPER failed')
    deadline = time.monotonic() + 15
    while not (root/'launch.json').is_file():
        if time.monotonic() > deadline:
            raise RuntimeError('Durable launch handoff never committed')
        time.sleep(.02)
    launch = json.loads((root/'launch.json').read_text())
    identity = proc(os.getpid())
    if launch['process']['pid'] != identity['pid'] or launch['process']['start_ticks'] != identity['start_ticks'] or not launch['launch_committed']:
        raise RuntimeError('Launch receipt does not identify this supervisor')
    checked_plan(path, digest)
    state = {'schema':'original150-resume-supervision-v1','status':'running','started_at':stamp(),
             'plan_sha256':digest,'process':identity,'command':plan['command'],'signals':[]}
    stop = []
    def interrupted(number, _frame):
        stop.append(number)
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, interrupted)
    save(root/'supervision.json', state, new=True)
    child = None
    try:
        with (root/'campaign.log').open('x') as log:
            child = subprocess.Popen(plan['command'], cwd=plan['cwd'], env=dict(os.environ, **plan['environment']),
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
            state['wrapper_process'] = proc(child.pid); save(root/'supervision.json', state)
            while child.poll() is None and not stop:
                time.sleep(.5)
            if stop:
                state['status'] = 'interrupted'
                state['signals'] = stop
            else:
                state['returncode'] = child.returncode
                state['status'] = 'completed' if child.returncode == 0 else 'failed'
    except BaseException as error:
        state.update(status='failed', error=repr(error))
    finally:
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, signal.SIG_IGN)
        state['cleanup'] = cleanup()
        if child is not None and state.get('returncode') is None:
            state['returncode'] = child.poll()
        if not state['cleanup']['verified']:
            state['status'] = 'failed'
        state['finished_at'] = stamp(); save(root/'supervision.json', state)
    return 0 if state['status'] == 'completed' else 1


def launch(path, digest):
    p = checked_plan(path, digest); root = Path(p['root'])
    with (root/'launch.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if any((root/n).exists() for n in ('launch.json','launch-failure.json','supervision.json')):
            raise RuntimeError('Existing launch; no automatic retry')
        argv = [sys.executable, str(Path(__file__).resolve()), '--plan', str(path.resolve()), '--sha256', digest, '--supervise']
        with (root/'supervisor.log').open('x') as log:
            child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True, env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
            try:
                identity = proc(child.pid); end = time.monotonic()+5
                while True:
                    if proc(child.pid)['start_ticks'] != identity['start_ticks']:
                        raise RuntimeError('Supervisor PID changed')
                    raw = (Path('/proc')/str(child.pid)/'cmdline').read_bytes()
                    observed = [s.decode() for s in raw.split(b'\0') if s]
                    if observed == argv:
                        break
                    if observed or child.poll() is not None or time.monotonic() > end:
                        raise RuntimeError('Supervisor command handoff mismatch: '+repr(observed))
                    time.sleep(.01)
                receipt = {'schema':'original150-resume-launch-v1','created_at':stamp(),'process':identity,
                    'boot_id':p['boot_id'],'argv':argv,'observed_argv':observed,'command_sha256':hashlib.sha256(raw).hexdigest(),
                    'plan_sha256':digest,'helper_sha256':sha(__file__),'launch_committed':True}
                save(root/'launch.json',receipt,new=True)
            except BaseException as error:
                if child.poll() is None:
                    child.terminate()
                    try:child.wait(timeout=5)
                    except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
                save(root/'launch-failure.json',{'error':repr(error),'returncode':child.poll(),'descendant_cleanup_verified':False},new=True)
                raise
        try:print(json.dumps(receipt),flush=True)
        except (BrokenPipeError,OSError):pass
    return 0


if __name__ == '__main__':
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True,type=Path);parser.add_argument('--sha256',required=True)
    parser.add_argument('--supervise',action='store_true');args=parser.parse_args()
    sys.exit(supervise(args.plan,args.sha256) if args.supervise else launch(args.plan,args.sha256))
