"""Current-host admission and detached launch for the preserved reference gates.

The numerical runner and its pidfd/subreaper cleanup remain authoritative.  This
module adds no numerical fallback, new pass result, or campaign-resume receipt.
An old boot identifier never authorizes a current process or scratch directory.
"""
from __future__ import annotations

import argparse
import datetime
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import time


ROOT = Path(__file__).absolute().parent
OUTPUT_ROOT = ROOT.parent
MEMORY_REQUIRED_BYTES = 8 * 1024**3
NATIVE_NAMES = {'cc1', 'cc1plus', 'f951', 'ninja', 'cmake', 'make', 'c++', 'g++',
                'gcc', 'clang', 'clang++', 'gfortran'}


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def runner_api():
    path = ROOT / 'reference_gates09.py'
    spec = importlib.util.spec_from_file_location('reference_recovery_runner', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def process_snapshot(proc=Path('/proc')):
    rows = []
    for directory in proc.glob('[0-9]*'):
        try:
            fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            rows.append({'pid': int(directory.name), 'parent': int(fields[1]),
                         'state': fields[0], 'start_ticks': int(fields[19]),
                         'name': (directory / 'comm').read_text().strip(),
                         'argv': (directory / 'cmdline').read_bytes().decode(errors='replace').rstrip('\0').split('\0')})
        except (FileNotFoundError, ProcessLookupError):
            pass
        except PermissionError as error:
            raise RuntimeError('Current-host process admission cannot inspect ' + str(directory)) from error
    return rows


def competing_workloads(rows, self_pid):
    """Exclude only this caller and its current ancestry, never unrelated PIDs."""
    by_pid = {row['pid']: row for row in rows}
    ancestors = set()
    cursor = self_pid
    while cursor in by_pid and cursor not in ancestors:
        ancestors.add(cursor)
        cursor = by_pid[cursor]['parent']
    result = []
    for row in rows:
        if row['pid'] in ancestors or row.get('state') == 'Z':
            continue
        name = row['name']
        native = name.startswith(('groops', 'segmented-qr', 'segmented_qr')) or name in NATIVE_NAMES
        argv = row.get('argv') or []
        python = name.startswith(('python', 'pytest'))
        # Script/module arguments identify numerical controllers even when no
        # native child is alive yet.  Do not interpret arbitrary source strings.
        arguments = argv[1:]
        if '-c' in arguments:
            arguments = arguments[:arguments.index('-c')]
        numerical_python = python and any(
            ('orbit' in value.lower() or 'validate_numerics' in value.lower())
            and (value.endswith('.py') or 'pytest' in value or 'orbit_poc' in value)
            for value in arguments)
        if native or numerical_python:
            result.append({**row, 'reason': 'native workload' if native else 'numerical Python controller'})
    return result


def admission_from_snapshot(rows, *, self_pid, affinity, available_memory, boot_id, host, cpu=4):
    if cpu not in affinity:
        raise RuntimeError(f'Prescribed CPU {cpu} is outside current allowed affinity')
    foreign = competing_workloads(rows, self_pid)
    if foreign:
        raise RuntimeError('Competing native/numerical workload; preserve it: ' + json.dumps(foreign))
    if available_memory < MEMORY_REQUIRED_BYTES:
        raise RuntimeError('Insufficient current memory for the unchanged 8 GiB process-tree limit')
    return {'host': host, 'boot_id': boot_id, 'cpu': cpu, 'allowed_cpus': sorted(affinity),
            'available_memory_bytes': available_memory, 'required_memory_bytes': MEMORY_REQUIRED_BYTES,
            'competing_workloads': [], 'pid': self_pid,
            'scope': 'Cooperative current-host admission; no exclusive CPU reservation or old-boot process attribution.'}


def admission(cpu=4):
    memory = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        pieces = line.split()
        if len(pieces) == 3 and pieces[2] == 'kB':
            memory[pieces[0].rstrip(':')] = int(pieces[1]) * 1024
    return admission_from_snapshot(process_snapshot(), self_pid=os.getpid(),
        affinity=os.sched_getaffinity(0), available_memory=memory['MemAvailable'],
        boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
        host=os.uname().nodename, cpu=cpu)


def inherited_environment(required, inherited=None):
    """Keep the verified HOME value, exposing only the frozen whitelist."""
    result = dict(os.environ if inherited is None else inherited)
    if result.get('HOME') != required.get('HOME'):
        raise ValueError('Current inherited HOME differs from the pinned runtime environment')
    return dict(required)


def verify_review(review, *, freeze_hash, runner_hash, launcher_hash):
    if (review.get('schema') != 'orbit-v41-recovery02-launch-review-v1'
            or review.get('approved') is not True
            or review.get('freeze_sha256') != freeze_hash
            or review.get('runner_sha256') != runner_hash
            or review.get('launcher_sha256') != launcher_hash
            or review.get('old_attempt_unchanged') is not True
            or review.get('scientific_settings_unchanged') is not True
            or review.get('all_eight_fresh') is not True):
        raise ValueError('Independent recovery launch review does not authorize these frozen controls')


def verified_launch(freeze, freeze_hash, audit, audit_hash):
    g = runner_api()
    freeze = Path(freeze).absolute()
    if freeze.parent.parent != OUTPUT_ROOT or freeze.parent == ROOT or freeze.name != 'freeze.json':
        raise ValueError('Launch requires a fresh recovery02 output directory')
    if digest(audit) != audit_hash:
        raise ValueError('Recovery review hash differs')
    review = g.read(audit)
    verify_review(review, freeze_hash=freeze_hash, runner_hash=digest(g.__file__),
                  launcher_hash=digest(__file__))
    frozen, plan = g.checked_freeze(freeze, freeze_hash)
    if plan['output'] != str(freeze.parent) or plan['recovery']['previous_results_reused'] is not False:
        raise ValueError('Recovery output or fresh-results policy differs')
    if g.read(frozen['preflight']['path']).get('status') != 'verified':
        raise ValueError('Fresh readonly preflight is not verified')
    if digest(sys.executable) != plan['runtime']['python']['sha256']:
        raise ValueError('Launcher must use the pinned Python executable')
    return g, plan


def launch(freeze, freeze_hash, audit, audit_hash):
    g, plan = verified_launch(freeze, freeze_hash, audit, audit_hash)
    current_admission = admission(cpu=plan['cpu'])
    output = Path(plan['output'])
    for name in ('detached-launch.json', 'detached-started.json', 'detached-result.json', 'detached.log', 'run.lock'):
        if (output / name).exists():
            raise ValueError('Preserve existing launch evidence; choose a fresh attempt: ' + name)
    command = [plan['runtime']['python']['path'], '-s', '-B', str(Path(__file__).absolute()),
               '_run', '--freeze', str(Path(freeze).absolute()), '--sha256', freeze_hash,
               '--audit', str(Path(audit).absolute()), '--audit-sha256', audit_hash]
    # A regular file remains open independently of the chat/SSH transport.
    with (output / 'detached.log').open('x') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Detached output must be a regular file')
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
            stderr=subprocess.STDOUT, start_new_session=True, close_fds=True,
            cwd=g.SOURCE, env=inherited_environment(g.base_env()))
        identity = next((row for row in process_snapshot() if row['pid'] == child.pid), None)
        record = {'schema': 'orbit-v41-recovery02-detached-launch-v1', 'argv': command,
                  'child_pid': child.pid, 'observed_child_identity': identity,
                  'admission': current_admission, 'freeze_sha256': freeze_hash,
                  'review_sha256': audit_hash, 'stdout': str(output / 'detached.log'),
                  'stdin': '/dev/null', 'start_new_session': True,
                  'status': 'launched; inspect detached-started/result and stage receipts',
                  'old_results_reused': False, 'release_authority': False}
        save(output / 'detached-launch.json', record)
    return record


class RecoveryInterrupted(BaseException):
    pass


def execute(freeze, freeze_hash, audit, audit_hash):
    # Even a failure of the child's repeated identity check gets a terminal
    # record.  Only a new, canonical recovery output may receive that record.
    freeze = Path(freeze).absolute()
    output = freeze.parent
    if (output.parent != OUTPUT_ROOT or output == ROOT or freeze.name != 'freeze.json'
            or output.resolve() != output or not output.is_dir()):
        raise ValueError('Child execution requires a canonical recovery output directory')
    if (output / 'detached-result.json').exists():
        raise ValueError('Preserve existing detached result; choose a fresh attempt')
    lock = None
    started = time.monotonic()
    signals = []
    handlers = {}
    def interrupted(number, _):
        signals.append(number)
        raise RecoveryInterrupted(number)
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        handlers[number] = signal.signal(number, interrupted)
    status = 'failed'
    code = 1
    error = None
    try:
        g, plan = verified_launch(freeze, freeze_hash, audit, audit_hash)
        lock_path = Path('/mnt/d/orbit-v41-recovery02/validation-controls07/cooperative-admission.lock')
        lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(lock_fd, 'r+')
        info, entry = os.fstat(lock_fd), lock_path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or (info.st_dev, info.st_ino) != (entry.st_dev, entry.st_ino):
            lock.close()
            raise ValueError('Shared admission lock ownership differs')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        current_admission = admission(cpu=plan['cpu'])
        save(output / 'detached-started.json', {'admission': current_admission,
            'freeze_sha256': freeze_hash, 'review_sha256': audit_hash,
            'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'launcher_sha256': digest(__file__), 'pid': os.getpid()})
        # The preserved runner delegates every child to the original pidfd
        # subreaper; that helper must produce its kernel_ECHILD cleanup proof.
        code = g.run(freeze, freeze_hash)
        native_interrupted = False
        numerical_result = output / 'result.json'
        if numerical_result.is_file():
            ledger = json.loads(numerical_result.read_text())
            native_interrupted = any(row.get('status') == 'interrupted' for row in ledger.get('stages', []))
        status = 'interrupted' if signals or native_interrupted else ('complete' if code == 0 else 'failed')
    except RecoveryInterrupted as exc:
        status, error = 'interrupted', repr(exc)
    except BaseException as exc:
        error = repr(exc)
    finally:
        for number, handler in handlers.items():
            signal.signal(number, handler)
        save(output / 'detached-result.json', {'status': status, 'returncode': code,
            'error': error, 'signals_received': signals, 'elapsed_seconds': time.monotonic() - started,
            'freeze_sha256': freeze_hash, 'review_sha256': audit_hash,
            'numerical_result': str(output / 'result.json'),
            'cleanup_authority': 'Original stage pidfd/subreaper receipts; no inferred cleanup certificate',
            'release_authority': False, 'old_results_reused': False})
        if lock is not None:
            lock.close()
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('admission', 'launch', '_run'))
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--audit-sha256')
    args = parser.parse_args()
    if args.operation == 'admission':
        print(json.dumps(admission(), sort_keys=True))
        return 0
    if any(value is None for value in (args.freeze, args.sha256, args.audit, args.audit_sha256)):
        parser.error('--freeze, --sha256, --audit and --audit-sha256 are required')
    if args.operation == 'launch':
        print(json.dumps(launch(args.freeze, args.sha256, args.audit, args.audit_sha256), sort_keys=True))
        return 0
    return execute(args.freeze, args.sha256, args.audit, args.audit_sha256)


if __name__ == '__main__':
    raise SystemExit(main())
