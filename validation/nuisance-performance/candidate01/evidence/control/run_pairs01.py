#!/usr/bin/env python3
"""Frozen local nuisance-cache comparison; never touches campaign outputs."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

BASE = Path('/home/emper/orbit-nuisance-performance')
REPO = BASE / 'source'
sys.path.insert(0, str(REPO / 'src'))
from orbit_poc.segmented.supervisor import run_owned


def sha(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda: f.read(1024 * 1024), b''): h.update(b)
    return h.hexdigest()


def save(p, value):
    with Path(p).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True, allow_nan=False)
        f.write('\n')


def verify_inputs(job):
    for rec in [job['source_profile'], *job['input_files']]:
        if sha(rec['path']) != rec['sha256']:
            raise RuntimeError('Input changed: ' + rec['path'])
    if sha(job['profile']) != job['profile_sha256']:
        raise RuntimeError('Prepared configuration changed')


def admission():
    rows = []
    for p in Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            comm = (p / 'comm').read_text().strip()
            if comm.startswith('groops') or comm in ('cc1plus', 'f951', 'ninja'):
                rows.append({'pid': int(p.name), 'comm': comm})
        except FileNotFoundError: pass
    if rows: raise RuntimeError('Other native/build workload blocks admission: ' + repr(rows))
    return {'host': os.uname().nodename,
            'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'cpu': 0, 'unrelated_native_or_build_processes': rows,
            'scope': 'local cooperative admission; no exclusive CPU claim'}


def main():
    out = BASE / 'paired01'
    prep = out / 'preparation.json'
    if sha(prep) != '388a1253c8d999da8623d4f63f3727dd10c06f1727d7c9238eaa6cea8cc212ed':
        raise RuntimeError('Prepared pair protocol changed')
    plan = json.loads(prep.read_text())
    native = BASE / 'build-01/groops'
    build = BASE / 'build-01/build-manifest.json'
    bm = json.loads(build.read_text())
    if sha(native) != bm['executable_sha256'] or not bm.get('nuisance_performance_extension'):
        raise RuntimeError('Unverified candidate build')
    freeze = {'schema': 'orbit-poc-nuisance-pair-freeze-v1',
              'preparation_sha256': sha(prep), 'runner_sha256': sha(__file__),
              'build_manifest': {'path': str(build), 'sha256': sha(build)},
              'native': {'path': str(native), 'sha256': sha(native)},
              'python': {'path': sys.executable, 'sha256': sha(sys.executable)},
              'supervisor_sha256': sha(REPO / 'src/orbit_poc/segmented/supervisor.py'),
              'admission': admission(), 'order': plan['predeclared_order'],
              'purpose': plan['purpose'], 'time': time.time()}
    for job in plan['jobs']: verify_inputs(job)
    save(out / 'freeze.json', freeze)
    for job in plan['jobs']:
        directory = Path(job['profile']).parent
        if sha(build) != freeze['build_manifest']['sha256'] or sha(native) != freeze['native']['sha256']:
            raise RuntimeError('Build identity changed')
        verify_inputs(job)
        save(directory / 'admission.json', admission())
        env = {k: v for k, v in os.environ.items()
               if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
        env.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                   NUMEXPR_NUM_THREADS='1', BLIS_NUM_THREADS='1', GOTO_NUM_THREADS='1',
                   PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                   ORBIT_POC_NUISANCE_PERFORMANCE='1',
                   ORBIT_POC_NUISANCE_INTERPOLATION_CACHE=str(job['cache']),
                   ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS='1',
                   ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE='0')
        argv = ['/usr/bin/taskset', '-c', str(plan['cpu']), str(native), job['profile']]
        started = time.monotonic()
        result = run_owned(argv, python_executable=sys.executable, cwd=directory, env=env,
                           log_path=directory / 'profile.log', receipt_path=directory / 'supervisor.json',
                           timeout_seconds=plan['timeout_seconds'],
                           max_process_tree_rss_bytes=plan['max_process_tree_rss_bytes'],
                           min_free_disk_bytes=16 * 1024**3, working_directory=directory)
        controller_elapsed = time.monotonic() - started
        verify_inputs(job)
        execution = {'command': argv, 'config_sha256': job['profile_sha256'],
                     'native_binary_sha256': freeze['native']['sha256'],
                     'elapsed_seconds': result['elapsed_seconds'],
                     'controller_elapsed_seconds': controller_elapsed,
                     'native_supervised_elapsed_seconds': result['elapsed_seconds'],
                     'returncode': result['returncode'], 'timed_out': result['status'] == 'timeout',
                     'status': result['status'], 'peak_rss_bytes': result['peak_process_tree_rss_bytes'],
                     'blas_openmp_threads': 1, 'cache': job['cache'],
                     'accumulate_epoch_observations': job['accumulate'],
                     'owned_process_group_cleaned': result['owned_process_group_cleaned'],
                     'supervisor_sha256': sha(directory / 'supervisor.json'),
                     'input_identity_after': 'verified', 'freeze_sha256': sha(out / 'freeze.json')}
        save(directory / 'profile.execution.json', execution)
        print(json.dumps({'job': job['name'], **execution}), flush=True)
        if not result['owned_process_group_cleaned']:
            raise RuntimeError('Unverified cleanup; stop before next run')
    save(out / 'execution-complete.json', {'all_planned_attempts_executed': True,
                                         'count': len(plan['jobs']), 'freeze_sha256': sha(out / 'freeze.json')})


if __name__ == '__main__': main()
