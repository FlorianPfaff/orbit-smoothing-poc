#!/usr/bin/env python3
"""Freeze the separate original-case cache experiment before either fit."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

B = Path('/home/emper/orbit-nuisance-performance')
ROOT = B/'wholefit01'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for data in iter(lambda: stream.read(1024*1024), b''):
            h.update(data)
    return h.hexdigest()


def record(path):
    return {'path': str(path), 'sha256': sha(path)}


def main():
    preparation = ROOT/'preparation.json'
    if sha(preparation) != 'ca7b5cf489d01f7a78a96fddf8eaf08aa13fec4294d122bd21d011b6dc3cfd35':
        raise RuntimeError('Preparation differs')
    prep = json.loads(preparation.read_text())
    source = json.loads((ROOT/'source-inventory.json').read_text())
    runtime = json.loads((ROOT/'python-runtime-actual01.json').read_text())
    native = json.loads((ROOT/'runtime-closures01.json').read_text())
    original = json.loads((ROOT/'original/request.json').read_text())
    pins = {}

    def pin(path, expected=None):
        item = record(Path(path))
        if expected is not None and item['sha256'] != expected:
            raise RuntimeError('Prepared identity differs: '+str(path))
        if item['path'] in pins and pins[item['path']] != item:
            raise RuntimeError('Conflicting pin')
        pins[item['path']] = item
        return item

    for path in (ROOT/'inputs').rglob('*'):
        if path.is_symlink():
            raise RuntimeError('Unreviewed input symlink')
        if path.is_file():
            pin(path)
    for name, expected in source['files'].items():
        pin(ROOT/'source'/name, expected)
    for item in runtime['files']:
        pin(item['path'], item['sha256'])
    for closure in native['closures'].values():
        pin(closure['executable']['path'], closure['executable']['sha256'])
        if not os.access(closure['executable']['path'], os.X_OK):
            raise RuntimeError('Pinned native executable is not executable')
        for item in closure['dependencies']:
            pin(item['path'], item['sha256'])
    runner = pin(B/'control/run_wholefit01.py')
    worker = pin(B/'control/wholefit_worker01.py')
    pin(__file__)
    for path in [preparation, ROOT/'source-inventory.json', ROOT/'runtime-closures01.json',
                 ROOT/'python-runtime-actual01.json', ROOT/'input-preflight01.json', ROOT/'input-layout01.json',
                 ROOT/'original/request.json', ROOT/'original/native_preparation.json',
                 ROOT/'capture-inputs02.receipt.json', B/'control/candidate-build-complete01.json',
                 B/'build-01/build-manifest.json', B/'control/wholefit-controller-independent-review01.json',
                 B/'control/wholefit-preparation-independent-review01.json']:
        pin(path)
    jobs = []
    for cache in (1, 0):
        rec = next(item for item in prep['requests'] if item['cache'] == cache)
        request = json.loads(Path(rec['path']).read_text())
        for key in ('case', 'method', 'parameters', 'numerical_controls', 'numerics_profile', 'segmented_profile',
                    'stage', 'force_model_hash', 'measurement_model_hash', 'mask_hash', 'preprocessing_hash'):
            if request[key] != original[key]:
                raise RuntimeError('Original numerical/scientific setting changed: '+key)
        if type(request.get('nuisance_performance_cache')) is not int or request['nuisance_performance_cache'] != cache:
            raise RuntimeError('Wrong request cache treatment')
        if request['expected_native_binary_sha256'] != '8b6986943d7836c4f4cb03278069893d3b797a5bcbd2a3f4ba763a1b27a6fcb2':
            raise RuntimeError('Wrong candidate executable')
        if request['backend']['diagnostic_native']['sha256'] != original['backend']['diagnostic_native']['sha256']:
            raise RuntimeError('Diagnostic exporter byte identity changed')
        jobs.append({'name': 'cache'+str(cache), 'cache': cache,
                     'request': pin(rec['path'], rec['sha256']), 'job_sha256': rec['job_sha256']})
    python = pin(sys.executable)
    environment = {key: '1' for key in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
        'NUMEXPR_NUM_THREADS', 'BLIS_NUM_THREADS', 'GOTO_NUM_THREADS', 'PYTHONDONTWRITEBYTECODE',
        'PYTHONNOUSERSITE', 'ORBIT_POC_NUISANCE_PERFORMANCE')}
    environment['LD_LIBRARY_PATH'] = native['library_directory']
    freeze = {'schema': 'orbit-poc-nuisance-wholefit-freeze-v1', 'created_at_unix': time.time(),
        'root': str(ROOT), 'source_root': str(ROOT/'source'), 'source_hash': source['sha256'],
        'source_commit': source['source_commit'], 'host': os.uname().nodename,
        'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'cpu': 0,
        'python': python, 'runner': runner, 'worker': worker, 'environment': environment,
        'wall_time_seconds': 7200., 'maximum_process_tree_rss_bytes': 8*1024**3,
        'minimum_free_output_bytes': 32*1024**3, 'reserve_bytes': 8*1024**3,
        'numerical_controls': original['numerical_controls'], 'jobs': jobs,
        'original_request': record(ROOT/'original/request.json'), 'input_preparation': record(preparation),
        'candidate': native['closures']['candidate']['executable'],
        'diagnostic_exporter': native['closures']['exporter']['executable'],
        'supervisor': record(ROOT/'source/src/orbit_poc/segmented/supervisor.py'),
        'pinned_files': [pins[key] for key in sorted(pins)],
        'purpose': 'Original 24h timeout case; same candidate executable cache enabled then disabled; separate from all frozen campaigns',
        'order_policy': 'Cache enabled first, declared before either outcome; one run per arm, no speedup confidence interval',
        'storage_policy': 'Unchanged NativeModel retention/compression/spool settings',
        'historical_runtime_equivalence_claim': False,
        'success_policy': 'Complete existing strict whole-fit/covariance gates; nuisance convergence alone is insufficient; preserve every timeout/failure',
        'production_mutations': False}
    with (ROOT/'freeze.json').open('x') as stream:
        json.dump(freeze, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'freeze': str(ROOT/'freeze.json'), 'sha256': sha(ROOT/'freeze.json'),
                      'pinned_files': len(pins), 'jobs': [job['name'] for job in jobs]}))


if __name__ == '__main__':
    main()
