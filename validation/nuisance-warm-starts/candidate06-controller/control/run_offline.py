"""Run the isolated composed unit fixture; never invoke a native executable."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

D = Path(__file__).resolve().parent
C = Path('/home/emper/orbit-nuisance-warmstarts/source-candidate06')


def pin(path):
    path = Path(path)
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.parent != D or output.exists():
        raise ValueError('Use a new, direct child of the separate composition control directory')
    if os.sched_getaffinity(0) != {4}:
        raise ValueError('This Python-only replay requires CPU4 affinity')
    original = json.loads((D / 'author-tests01/plan.json').read_bytes())
    sources = [pin(path) for path in sorted((C / 'src').rglob('*.py'))]
    if sources != original['production_source_files']:
        raise ValueError('Candidate Python inventory drifted')
    if pin(Path(sys.executable).resolve()) != original['python']:
        raise ValueError('Use the pinned Python interpreter')
    output.mkdir()
    test = output / 'test_lifecycle_composition.py'
    shutil.copy2(D / test.name, test)
    env = dict(os.environ, PYTHONPATH=str(C / 'src'), PYTHONDONTWRITEBYTECODE='1',
               PYTHONPYCACHEPREFIX=str(output / 'empty-pycache'), PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
    thread_keys = ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS',
                   'NUMEXPR_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS', 'BLIS_NUM_THREADS']
    for key in thread_keys:
        env[key] = '1'
    command = [sys.executable, '-s', '-B', '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
               str(test), '--basetemp', str(output / 'tmp'), '--junitxml', str(output / 'tests.xml')]
    plan = {'schema': 'mock-composed-python-test-attempt-v1',
            'started_at': datetime.now(timezone.utc).isoformat(), 'command': command,
            'cpu_affinity': sorted(os.sched_getaffinity(0)), 'python': pin(Path(sys.executable).resolve()),
            'runner': pin(Path(__file__).resolve()), 'basis_plan': pin(D / 'author-tests01/plan.json'),
            'test_source': pin(test), 'production_source_files': sources,
            'environment': {key: env[key] for key in [*thread_keys, 'PYTHONPATH', 'PYTHONDONTWRITEBYTECODE',
                            'PYTHONPYCACHEPREFIX', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD']},
            'native_execution': False}
    (output / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    started = time.monotonic()
    with (output / 'tests.log').open('wb') as log:
        result = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
    unchanged = sources == [pin(path) for path in sorted((C / 'src').rglob('*.py'))]
    receipt = {'returncode': result.returncode, 'elapsed_seconds': time.monotonic() - started,
               'finished_at': datetime.now(timezone.utc).isoformat(), 'source_bytes_unchanged': unchanged,
               'test_source': pin(test), 'log': pin(output / 'tests.log')}
    if (output / 'tests.xml').exists():
        receipt['junit'] = pin(output / 'tests.xml')
    (output / 'execution.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt))
    print((output / 'tests.log').read_text()[-12000:])
    return result.returncode if unchanged else 2


if __name__ == '__main__':
    raise SystemExit(main())
