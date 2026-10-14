#!/usr/bin/env python3
"""Run the two reviewed publication steps once, in dependency order."""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(worker, repo, control, expected_worker, expected_verifier, runner=subprocess.run):
    control = Path(control)
    control.mkdir(parents=True, exist_ok=True)
    status_path = control / 'pipeline-status.json'
    with (control / 'pipeline.lock').open('a') as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        if status_path.exists():
            raise ValueError('Existing pipeline status requires reconciliation; never relaunch automatically')
        record = {'pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
                  'worker_sha256': expected_worker, 'verifier_sha256': expected_verifier,
                  'worker': str(worker), 'repo': str(repo), 'steps': [],
                  'scientific_superiority_claim': False, 'estimators_launched': False}

        def save():
            temporary = status_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(record, indent=2, sort_keys=True) + '\n')
            temporary.replace(status_path)

        try:
            for action in ('--wait-for-bundle', '--publish'):
                if digest(worker) != expected_worker or digest(worker.with_name('completion_handoff_03.py')) != expected_verifier:
                    raise ValueError('Reviewed publication worker/verifier changed')
                argv = [sys.executable, str(worker), action, '--repo', str(repo),
                        '--control', str(control / 'worker'), '--max-wait-hours', '336']
                step = {'action': action, 'argv': argv, 'started_at': datetime.now(timezone.utc).isoformat()}
                record['steps'].append(step)
                record.update(status='running', phase=action)
                save()
                with (control / (action[2:] + '.log')).open('xb') as log:
                    result = runner(argv, stdout=log, stderr=subprocess.STDOUT, pass_fds=(lock.fileno(),))
                step.update(returncode=result.returncode, finished_at=datetime.now(timezone.utc).isoformat())
                if result.returncode:
                    record.update(status='stopped', reason='Dependency step failed; no retry or later action')
                    save()
                    return record
            record.update(status='complete', phase='published_and_verified')
        except BaseException as error:
            record.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'stopped',
                          reason=f'{type(error).__name__}: {error}',
                          instruction='Inspect worker receipts before reconciliation; a push may have completed')
        save()
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('worker', 'repo', 'control'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('expected-worker', 'expected-verifier'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    result = execute(args.worker.resolve(), args.repo.resolve(), args.control.resolve(),
                     args.expected_worker, args.expected_verifier)
    print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'complete' else 2


if __name__ == '__main__':
    raise SystemExit(main())
