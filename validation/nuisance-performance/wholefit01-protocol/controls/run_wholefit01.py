#!/usr/bin/env python3
"""Two separately frozen whole-fit attempts; no retries or production writes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, allow_nan=False, sort_keys=True, indent=2)
        stream.write('\n')


def record(path):
    return {'path': str(path), 'sha256': sha(path)} if path.is_file() else None


def verify(freeze):
    for item in freeze['pinned_files']:
        if sha(item['path']) != item['sha256']:
            raise RuntimeError('Frozen file changed: '+item['path'])


def admission(freeze):
    import psutil
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if os.uname().nodename != freeze['host'] or boot != freeze['boot_id']:
        raise RuntimeError('Host or boot changed; preserve attempt and prepare a new protocol')
    if freeze['cpu'] not in os.sched_getaffinity(0):
        raise RuntimeError('Admitted CPU unavailable')
    conflicts = []
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():
            continue
        try:
            name = (path/'comm').read_text().strip()
            if name.startswith('groops') or name in ('cc1plus', 'ninja', 'f951', 'segmented_qr'):
                conflicts.append({'pid': int(path.name), 'name': name})
        except FileNotFoundError:
            pass
    if conflicts:
        raise RuntimeError('Competing native/build process: '+repr(conflicts))
    free_memory = psutil.virtual_memory().available
    free_disk = shutil.disk_usage(freeze['root']).free
    if free_memory < freeze['maximum_process_tree_rss_bytes'] + freeze['reserve_bytes']:
        raise RuntimeError('Insufficient free memory for frozen resource budget')
    if free_disk < freeze['minimum_free_output_bytes']:
        raise RuntimeError('Insufficient free output space')
    return {'host': freeze['host'], 'boot_id': boot, 'cpu': freeze['cpu'],
            'free_memory_bytes': free_memory, 'free_disk_bytes': free_disk,
            'conflicting_processes': conflicts, 'time': time.time(),
            'scope': 'cooperative local admission; no exclusive CPU reservation claim'}


def classify(measured, output, request):
    if measured.get('owned_process_group_cleaned') is not True:
        return {'status': 'failed', 'converged': False, 'covariance_valid': False,
                'error': 'Owned-process cleanup was not verified'}
    if measured['status'] in ('timeout', 'memory_limit', 'disk_limit', 'interrupted'):
        return {'status': measured['status'], 'converged': False, 'covariance_valid': False,
                'error': 'Frozen whole-fit limit or interruption'}
    if measured.get('returncode') != 0 or not output.exists():
        return {'status': 'failed', 'converged': False, 'covariance_valid': False,
                'error': 'Worker failed or produced no result'}
    result = json.loads(output.read_text())
    if result.get('status') not in ('complete', 'timeout', 'failed', 'unresolved_rank', 'invalid_covariance'):
        return {'status': 'failed', 'converged': False, 'covariance_valid': False,
                'error': 'Worker reported unsupported status', 'worker_result': result}
    if result['status'] == 'complete':
        try:
            from orbit_poc.segmented.report import strict_result
            strict_result(result, request)
        except Exception as error:
            return {'status': 'failed', 'converged': False, 'covariance_valid': False,
                    'error': 'Complete worker receipt failed the existing strict gate: '+str(error),
                    'reported_worker_status': 'complete'}
    # Process completion is not numerical convergence. Preserve backend outcome.
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', required=True, type=Path)
    parser.add_argument('--freeze-sha256', required=True)
    args = parser.parse_args()
    if sha(args.freeze) != args.freeze_sha256:
        raise RuntimeError('Freeze identity differs')
    freeze = json.loads(args.freeze.read_text())
    if freeze['schema'] != 'orbit-poc-nuisance-wholefit-freeze-v1':
        raise ValueError('Unknown freeze schema')
    root = Path(freeze['root'])
    if root != args.freeze.resolve().parent:
        raise ValueError('Freeze root differs')
    if sha(__file__) != freeze['runner']['sha256']:
        raise RuntimeError('Runner differs from frozen code')
    lock = (root/'controller.lock').open('a')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if (root/'launch.json').exists():
        raise RuntimeError('Existing launch: no automatic resume or replacement')
    verify(freeze)
    initial_admission = admission(freeze)
    sys.path.insert(0, str(Path(freeze['source_root'])/'src'))
    from orbit_poc.segmented.supervisor import run_owned
    save(root/'launch.json', {'runner_pid': os.getpid(), 'freeze_sha256': args.freeze_sha256,
                             'admission': initial_admission, 'order': [j['name'] for j in freeze['jobs']]})
    outcomes = []
    for job in freeze['jobs']:
        if sha(args.freeze) != args.freeze_sha256:
            raise RuntimeError('Freeze changed after launch')
        directory = root/job['name']
        if directory.exists():
            raise RuntimeError('Output directory already exists: '+str(directory))
        verify(freeze)
        admitted = admission(freeze)
        directory.mkdir()
        save(directory/'admission.json', admitted)
        request = directory/'request.json'
        request.write_bytes(Path(job['request']['path']).read_bytes())
        env = {k: v for k, v in os.environ.items()
               if k not in ('PYTHONPATH', 'PYTHONHOME') and not k.startswith(('ORBIT_POC_', 'LD_'))}
        env.update(freeze['environment'])
        env['ORBIT_POC_NUISANCE_INTERPOLATION_CACHE'] = str(job['cache'])
        output = directory/'worker-result.json'
        argv = [freeze['python']['path'], '-s', '-B', freeze['worker']['path'],
                freeze['source_root'], str(request), str(output), str(job['cache']),
                str(args.freeze.resolve()), args.freeze_sha256]
        measured = run_owned(argv, python_executable=freeze['python']['path'],
            cwd=freeze['source_root'], env=env, log_path=directory/'worker.log',
            receipt_path=directory/'supervisor.json', timeout_seconds=freeze['wall_time_seconds'],
            max_process_tree_rss_bytes=freeze['maximum_process_tree_rss_bytes'],
            min_free_disk_bytes=freeze['minimum_free_output_bytes'], working_directory=directory)
        result = classify(measured, output, json.loads(request.read_text()))
        result.update(freeze_sha256=args.freeze_sha256, cache=job['cache'],
                      request_sha256=sha(request), harness_execution=measured,
                      evidence={'request': record(request), 'worker_result': record(output),
                                'supervisor': record(directory/'supervisor.json'),
                                'effective_environment': record(directory/'effective-environment.json')})
        save(directory/'result.json', result)
        try:
            if sha(args.freeze) != args.freeze_sha256:
                raise RuntimeError('Freeze changed during execution')
            verify(freeze)
            post = {'verified': True, 'freeze_sha256': args.freeze_sha256,
                    'pinned_file_count': len(freeze['pinned_files'])}
        except Exception as error:
            post = {'verified': False, 'error': type(error).__name__+': '+str(error)}
        save(directory/'post-input-check.json', post)
        outcome = {'name': job['name'], 'status': result['status'],
                   'result_sha256': sha(directory/'result.json'),
                   'post_input_identity_verified': post['verified']}
        outcomes.append(outcome)
        print(json.dumps(outcome), flush=True)
        if not post['verified'] or not measured.get('owned_process_group_cleaned') or result['status'] == 'interrupted':
            save(root/'execution-stopped.json', {'outcomes': outcomes, 'all_attempts_executed': False})
            return
    save(root/'execution-complete.json', {'outcomes': outcomes, 'all_attempts_executed': True,
                                        'freeze_sha256': args.freeze_sha256})


if __name__ == '__main__':
    main()
