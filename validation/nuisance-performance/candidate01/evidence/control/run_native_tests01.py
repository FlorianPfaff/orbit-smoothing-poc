#!/usr/bin/env python3
"""Rerun the unchanged 106 native and 51 correction tests on the candidate."""
from pathlib import Path
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

B = Path('/home/emper/orbit-nuisance-performance')
R = B/'source'
sys.path.insert(0, str(R/'src'))
from orbit_poc.segmented.supervisor import run_owned


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, sort_keys=True, indent=2);f.write('\n')


def main():
    build = json.loads((B/'control/candidate-build-complete01.json').read_text())
    native = build['native']['path']
    if sha(native) != build['native']['sha256']: raise RuntimeError('Candidate changed')
    out = B/'native-tests01';out.mkdir()
    suites = [('native', 106, [
        'tests/test_numerics_native_qr.py', 'tests/test_numerics_original_objective.py',
        'tests/test_numerics_mean_residual.py', 'tests/test_numerics_derivatives.py',
        'tests/test_numerics_geometry_precision.py', 'tests/test_numerics_synthetic_force_arithmetic.py']),
        ('correction', 51, [
        'tests/test_numerics_query_precision.py', 'tests/test_numerics_reference_precision.py',
        'tests/test_numerics_precise_residual.py', 'tests/test_numerics_precise_objective.py',
        'tests/test_numerics_light_time_precision.py'])]
    pins = {name: sha(R/name) for _, _, names in suites for name in names}
    freeze = {'suites': suites, 'test_hashes': pins, 'candidate_build': build,
              'runner_sha256': sha(__file__), 'supervisor_sha256': sha(R/'src/orbit_poc/segmented/supervisor.py'),
              'threads': 1, 'cpu': 0, 'cache': 1, 'performance': 1,
              'scope': 'unchanged native/regression test sets; not the complete propagation/objective release suite'}
    save(out/'freeze.json', freeze)
    env = {k: v for k, v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PYTHONPATH=str(R/'src'), PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1',
               ORBIT_POC_V31_NATIVE=native, ORBIT_POC_CORRECTNESS_NATIVE=native, ORBIT_POC_GROOPS=native,
               ORBIT_POC_NUISANCE_PERFORMANCE='1', ORBIT_POC_NUISANCE_INTERPOLATION_CACHE='1')
    results = []
    for name, expected, files in suites:
        for p in Path('/proc').glob('[0-9]*'):
            try:
                comm = (p/'comm').read_text().strip()
                if comm.startswith('groops') or comm in ('ninja', 'cc1plus', 'f951'):
                    raise RuntimeError('Competing local native/compiler workload: '+comm)
            except FileNotFoundError: pass
        d = out/name;d.mkdir()
        argv = ['/usr/bin/taskset', '-c', '0', sys.executable, '-s', '-m', 'pytest', '-q', '-s',
                '-p', 'no:cacheprovider', '--basetemp='+str(d/'temp'), '--junitxml='+str(d/'tests.xml'), *files]
        execution = run_owned(argv, python_executable=sys.executable, cwd=R, env=env,
                              log_path=d/'pytest.log', receipt_path=d/'supervisor.json',
                              timeout_seconds=3600, max_process_tree_rss_bytes=8*1024**3,
                              min_free_disk_bytes=16*1024**3, working_directory=d)
        cases = list(ET.parse(d/'tests.xml').getroot().iter('testcase')) if (d/'tests.xml').exists() else []
        counts = {'tests': len(cases), **{tag: sum(c.find(tag) is not None for c in cases) for tag in ('failure','error','skipped')}}
        passed = execution['status']=='complete' and counts=={'tests':expected,'failure':0,'error':0,'skipped':0}
        if any(sha(R/p)!=h for p, h in pins.items()): raise RuntimeError('Test source changed')
        result = {'suite': name, 'passed': passed, 'counts': counts, 'execution': execution}
        save(d/'result.json', result);results.append(result)
        print(json.dumps({'suite': name, 'passed': passed, 'counts': counts}), flush=True)
    save(out/'result.json', {'passed': all(r['passed'] for r in results), 'results': results})
    if not all(r['passed'] for r in results): raise SystemExit(1)


if __name__=='__main__': main()
