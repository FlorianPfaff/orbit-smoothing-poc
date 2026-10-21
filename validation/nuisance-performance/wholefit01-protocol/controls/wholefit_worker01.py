#!/usr/bin/env python3
"""Direct, attributed backend worker; no numerical or campaign modifications."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    source, request, output, cache, freeze_path, expected_freeze = sys.argv[1:]
    data = Path(freeze_path).read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_freeze:
        raise RuntimeError('Worker freeze identity changed')
    freeze = json.loads(data)
    if cache not in ('0', '1'):
        raise ValueError('Explicit cache treatment required')
    selected = [job for job in freeze['jobs'] if job['cache'] == int(cache)]
    if len(selected) != 1 or hashlib.sha256(Path(request).read_bytes()).hexdigest() != selected[0]['request']['sha256']:
        raise RuntimeError('Worker request or treatment differs from freeze')
    if source != freeze['source_root'] or Path(output).parent != Path(freeze['root'])/selected[0]['name']:
        raise RuntimeError('Worker source or output root differs')
    os.sched_setaffinity(0, {freeze['cpu']})
    if os.sched_getaffinity(0) != {freeze['cpu']}:
        raise RuntimeError('Worker affinity differs')
    for key, value in freeze['environment'].items():
        if os.environ.get(key) != value:
            raise RuntimeError('Worker environment differs: ' + key)
    if os.environ.get('ORBIT_POC_NUISANCE_INTERPOLATION_CACHE') != cache:
        raise RuntimeError('Worker cache treatment differs')
    if {key for key in os.environ if key.startswith('ORBIT_POC_')} != {
            'ORBIT_POC_NUISANCE_INTERPOLATION_CACHE', 'ORBIT_POC_NUISANCE_PERFORMANCE'}:
        raise RuntimeError('Unfrozen numerical environment override')
    root = Path(output).parent
    with (root/'effective-environment.json').open('x') as stream:
        json.dump({'schema': 'orbit-poc-nuisance-wholefit-environment-v1',
                   'cache': int(cache), 'environment': {**freeze['environment'],
                   'ORBIT_POC_NUISANCE_INTERPOLATION_CACHE': cache},
                   'cpu_affinity': sorted(os.sched_getaffinity(0)),
                   'freeze_sha256': expected_freeze, 'pid': os.getpid(),
                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'source': source, 'request_sha256': hashlib.sha256(Path(request).read_bytes()).hexdigest(),
                   'storage_policy': 'unchanged NativeModel overrides: intermediate factors=0, compressed row provenance=1'},
                  stream, indent=2, sort_keys=True)
        stream.write('\n')
    sys.path.insert(0, str(Path(source)/'src'))
    from orbit_poc.segmented.backend import fit_job
    job = json.loads(Path(request).read_text())
    if job.get('nuisance_performance_cache') != int(cache):
        raise RuntimeError('Declared request cache treatment differs')
    result = fit_job(job, root)
    with Path(output).open('x') as stream:
        json.dump(result, stream, allow_nan=False, indent=2, sort_keys=True)
        stream.write('\n')


if __name__ == '__main__':
    main()
