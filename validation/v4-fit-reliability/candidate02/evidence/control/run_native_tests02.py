#!/usr/bin/env python3
"""Rerun the unchanged 106 native and 51 correction tests on the candidate."""
from pathlib import Path
import hashlib
import json
import os
import sys
import xml.etree.ElementTree as ET

B = Path('/home/emper/orbit-v4-failure-investigation')
R = B/'source'
sys.path.insert(0, str(R/'src'))
from orbit_poc.segmented.supervisor import run_owned


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    with Path(path).open('x') as f:
        json.dump(data, f, sort_keys=True, indent=2);f.write('\n')


def main():
    build = json.loads((B/'control/build-result02.json').read_text())
    native = build['native']['path']
    if sha(native) != build['native']['sha256']: raise RuntimeError('Candidate changed')
    assert build['execution']['status']=='complete' and build['inputs_and_originals_unchanged']
    out = B/'native-tests02';out.mkdir()
    suites = [('native', 106, [
        'tests/test_numerics_native_qr.py', 'tests/test_numerics_original_objective.py',
        'tests/test_numerics_mean_residual.py', 'tests/test_numerics_derivatives.py',
        'tests/test_numerics_geometry_precision.py', 'tests/test_numerics_synthetic_force_arithmetic.py']),
        ('correction', 51, [
        'tests/test_numerics_query_precision.py', 'tests/test_numerics_reference_precision.py',
        'tests/test_numerics_precise_residual.py', 'tests/test_numerics_precise_objective.py',
        'tests/test_numerics_light_time_precision.py']),
        ('fail_fast', 37, ['tests/test_native_nuisance_fail_fast.py']),
        ('cost_query', 15, ['tests/test_native_cost_only_query.py'])]
    pins = {name: sha(R/name) for _, _, names in suites for name in names}
    protected = {item['path']: item['sha256'] for item in [build['native'], build['build_manifest'], *build['libraries']]}
    protected.update({str(R/'src/orbit_poc/segmented/supervisor.py'):sha(R/'src/orbit_poc/segmented/supervisor.py'), str(Path(__file__).resolve()):sha(__file__)})
    freeze = {'suites': suites, 'test_hashes': pins, 'candidate_build': build,
              'protected_files':protected, 'runner_sha256': sha(__file__), 'supervisor_sha256': sha(R/'src/orbit_poc/segmented/supervisor.py'),
              'threads': 1, 'cpu': 0, 'cache': 1, 'performance': 1,
              'scope': 'unchanged native/regression test sets; not the complete propagation/objective release suite'}
    save(out/'freeze.json', freeze)
    env = {k: v for k, v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH', 'PYTHONHOME')}
    env.update(PYTHONPATH=str(R/'src'), PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1',
               ORBIT_POC_V31_NATIVE=native, ORBIT_POC_CORRECTNESS_NATIVE=native, ORBIT_POC_GROOPS=native,
               ORBIT_POC_NUISANCE_PERFORMANCE='1', ORBIT_POC_NUISANCE_INTERPOLATION_CACHE='1', ORBIT_POC_COST_QUERY_NATIVE_SOURCE=build['source_root'], ORBIT_POC_COST_QUERY_NATIVE_BUILD=str(B/'build-02'), ORBIT_POC_COST_QUERY_NATIVE_CXX='/home/emper/orbit-nuisance-warmstarts/toolchain-01/bin/x86_64-conda-linux-gnu-c++', ORBIT_POC_NUISANCE_COST_ONLY_DESIGN='1', LD_LIBRARY_PATH='/home/emper/orbit-nuisance-warmstarts/toolchain-01/lib')
    results = []
    for name, expected, files in suites:
        if any(sha(p)!=h for p,h in protected.items()):raise RuntimeError('Protected runtime/source changed before suite')
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
        unchanged = all(sha(R/p)==h for p,h in pins.items()) and all(sha(p)==h for p,h in protected.items())
        clean = execution.get('owned_process_group_cleaned') is True and execution.get('cleanup',{}).get('verified') is True
        passed = execution['status']=='complete' and clean and unchanged and counts=={'tests':expected,'failure':0,'error':0,'skipped':0}
        result = {'suite': name, 'passed': passed, 'counts': counts, 'execution': execution, 'inputs_and_runtime_unchanged':unchanged}
        save(d/'result.json', result);results.append(result)
        print(json.dumps({'suite': name, 'passed': passed, 'counts': counts}), flush=True)
        if not clean or not unchanged:break
    save(out/'result.json', {'passed': (len(results)==len(suites) and all(r['passed'] for r in results)), 'results': results})
    if not (len(results)==len(suites) and all(r['passed'] for r in results)): raise SystemExit(1)


if __name__=='__main__': main()
