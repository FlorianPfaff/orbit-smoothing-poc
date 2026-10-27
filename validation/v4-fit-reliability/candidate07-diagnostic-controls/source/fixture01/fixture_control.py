"""One reviewed, bounded pure proposal-binding fixture job; no GNSS inputs."""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import sys
import time

HERE = Path(__file__).resolve().parent
SOURCE = Path('/mnt/d/orbit-v41-recovery02/candidate07-density04-undamped-objective-probe01/preparation01')
SOURCE_SHA = '754967b72939e921f0eafcb98766c1daa514bf8ae1e512c49dbe9f77518a3cef'
OUT = Path('/mnt/d/orbit-v41-recovery02/candidate07-density04-undamped-probe-fixtures01')
SCRATCH = Path('/home/emper/orbit-density04-undamped-probe-fixtures01')
LOCK = Path('/mnt/d/orbit-v41-recovery02/validation-controls07/cooperative-admission.lock')
PYTHON = '/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python'
PYTHON_SHA = '58f0ee5f4cb0af42a69aed9f122d63cc535fcfa6bca71132a3d0e24be95c4ac8'
LIMITS = {'timeout_seconds': 300, 'max_process_tree_rss_bytes': 8*1024**3,
          'min_free_disk_bytes': 1024**3, 'cpu': 4}

def require(value, message):
    if not value: raise ValueError(message)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''): h.update(part)
    return h.hexdigest()

def read(path): return json.loads(Path(path).read_text())

def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())

def pin(path): return {'path': str(path), 'sha256': digest(path)}

def verify(item):
    require(digest(item['path']) == item['sha256'], 'Changed bytes: '+item['path'])

def ledger(root, name, sha=None):
    path = root/name
    if sha: require(digest(path) == sha, 'Ledger changed: '+str(path))
    result = []
    for line in path.read_text().splitlines():
        value, relative = line.split('  ', 1); target = root/relative
        require(target.resolve() == target and target.is_relative_to(root), 'Source alias/escape')
        row = {'path': str(target), 'sha256': value}; verify(row); result.append(row)
    expected = {str(path), *(x['path'] for x in result)}
    actual = {str(x) for x in root.rglob('*') if x.is_file() or x.is_symlink()}
    require(len(result) == len(expected)-1 and actual == expected, 'Source membership differs')
    return result

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); sys.modules[name] = module
    spec.loader.exec_module(module); return module

def simple_rows(name, root):
    return [{'path': str(root/relative), 'sha256': sha}
            for sha, relative in (line.split('  ', 1) for line in (HERE/name).read_text().splitlines())]

def runtime_snapshot():
    """Verify the saved finite runtime envelope; never import/probe its packages."""
    envelope = read(HERE/'python-envelope.json'); rows = list(envelope['files'])
    for tree in envelope['trees']:
        root = Path(tree['root'])
        expected = {r['relative'] for r in tree['entries'] if r['kind'] != 'directory'}
        actual = set()
        for parent, directories, files in os.walk(root, followlinks=False):
            directories[:] = [name for name in directories if name != '__pycache__'
                and str((Path(parent)/name).relative_to(root)) not in tree.get('excluded', [])]
            require(not any((Path(parent)/name).is_symlink() for name in directories), 'Unpinned runtime directory alias')
            actual.update(str((Path(parent)/name).relative_to(root)) for name in files)
        require(actual == expected, 'Python tree membership changed: '+str(root))
        rows.extend(r for r in tree['entries'] if r['kind'] != 'directory')
    for path in envelope['absent']: require(not os.path.lexists(path), 'Unexpected startup file: '+path)
    require(sorted(str(p) for p in Path(envelope['site_directory']).glob('*.pth'))
            == sorted(envelope['site_startup_members']), 'Site startup membership changed')
    rows += simple_rows('host-files.sha256', Path('/'))
    for row in rows:
        verify(row)
        if 'resolved' in row: require(str(Path(row['path']).resolve()) == row['resolved'], 'Runtime alias changed')
        if 'link_target' in row: require(os.readlink(row['path']) == row['link_target'], 'Runtime link text changed')
    return {'files_verified': len(rows), 'file_bytes': sum(Path(r['path']).stat().st_size for r in rows),
            'identities': rows, 'native_gnss_inputs': [], 'runtime_execution_probe': False}

def environment():
    return {'HOME': '/home/emper', 'PATH': '/usr/bin:/bin',
            'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONNOUSERSITE': '1', 'PYTHONPYCACHEPREFIX': str(SCRATCH/'pycache'),
            'OMP_NUM_THREADS': '1', 'OPENBLAS_NUM_THREADS': '1', 'MKL_NUM_THREADS': '1',
            'NUMEXPR_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1', 'BLIS_NUM_THREADS': '1',
            'TMPDIR': str(SCRATCH/'tmp')}

def namespace(plan_path, plan_sha):
    """Finite read-only code/runtime mounts; orbital archives are absent."""
    envelope = read(HERE/'python-envelope.json')
    args = ['/usr/bin/taskset', '-c', '4', '/usr/bin/bwrap', '--die-with-parent', '--unshare-all',
            '--new-session', '--cap-drop', 'ALL', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--symlink', 'usr/lib', '/lib']
    mounts = {str(SOURCE): str(SOURCE), str(HERE): str(HERE), str(plan_path): str(plan_path)}
    # -S disables site startup; hide the site directory even when the stdlib
    # parent is mounted. The supervisor uses the separately pinned host site.
    stdlib = next(t['root'] for t in envelope['trees'] if t['root'].endswith('/lib/python3.11'))
    mounts[stdlib] = stdlib; mounts[str(Path(stdlib).resolve())] = str(Path(stdlib).resolve())
    for row in envelope['files']:
        if '/site-packages/' in row['path']: continue
        mounts[row['path']] = row['resolved']; mounts[row['resolved']] = row['resolved']
        canonical_base = str(Path(envelope['base_prefix']).resolve())
        if row['resolved'].startswith(canonical_base+'/lib/'):
            mounts[envelope['base_prefix']+row['resolved'][len(canonical_base):]] = row['resolved']
    for target, source in sorted(mounts.items(), key=lambda item: (item[0].count('/'), item[0])):
        args += ['--ro-bind', source, target]
    for path in sorted({stdlib+'/site-packages', str(Path(stdlib).resolve())+'/site-packages'}):
        args += ['--tmpfs', path]
    args += ['--bind', str(SCRATCH), str(SCRATCH), '--chdir', str(SCRATCH), '--clearenv']
    for key, value in environment().items(): args += ['--setenv', key, value]
    args += ['--setenv', 'PWD', str(SCRATCH), PYTHON, '-I', '-S', '-B', '-X',
             'pycache_prefix='+str(SCRATCH/'pycache'), str(HERE/'fixture_worker.py'),
             '--plan', str(plan_path), '--plan-sha256', plan_sha]
    return args

def source_checks(review):
    require(review['schema'] == 'undamped-probe-fixture-execution-source-review-v1'
            and review['approved_actions'] == ['qualify'] and review['approved'] is True,
            'Actual independent fixture-only review required')
    require(review['probe_ledger'] == {'path': str(SOURCE/'inputs.sha256'), 'sha256': SOURCE_SHA}, 'Wrong probe')
    require(review['control_ledger']['path'] == str(HERE/'inputs.sha256'), 'Wrong controls')
    own = ledger(HERE, 'inputs.sha256', review['control_ledger']['sha256'])
    source = ledger(SOURCE, 'inputs.sha256', SOURCE_SHA)
    require(len(source) == 11, 'Probe source count changed')
    return own + source

def prepare(args):
    review = read(args.review); verify({'path': str(args.review), 'sha256': args.review_sha256})
    source_checks(review)
    require(args.plan.is_absolute() and args.plan.parent.resolve() == args.plan.parent, 'Canonical plan parent required')
    require(not any(args.plan.is_relative_to(root) for root in (HERE,SOURCE,OUT,SCRATCH)),
            'Plan must be outside frozen source and exclusive future output roots')
    plan = {'schema': 'undamped-probe-fixture-execution-plan-v1', 'review': pin(args.review),
            'probe_ledger': review['probe_ledger'], 'control_ledger': review['control_ledger'],
            'limits': LIMITS, 'output': str(OUT), 'scratch': str(SCRATCH), 'environment': environment(),
            'python': {'path': PYTHON, 'sha256': PYTHON_SHA},
            'expected_ids': (SOURCE/'expected-test-ids.txt').read_text().splitlines(),
            'native_gnss_runs': 0, 'covariance_authority': False, 'release_authority': False}
    require(len(plan['expected_ids']) == len(set(plan['expected_ids'])) == 5, 'Exactly five methods required')
    save(args.plan, plan); print(digest(args.plan))

def run(args):
    verify({'path': str(args.plan), 'sha256': args.plan_sha256}); plan = read(args.plan)
    require(plan['schema'] == 'undamped-probe-fixture-execution-plan-v1' and plan['limits'] == LIMITS
            and plan['output'] == str(OUT) and plan['scratch'] == str(SCRATCH)
            and plan['environment'] == environment(), 'Plan scope differs')
    OUT.mkdir(mode=0o700); result = {'status': 'failed', 'plan': pin(args.plan), 'signals': [],
        'native_gnss_runs': 0, 'covariance_authority': False, 'release_authority': False}
    lock = None; start = time.monotonic(); handlers = {}; before=None; runtime=None; review=None
    def interrupted(number, _):
        result['signals'].append(number); raise KeyboardInterrupt('Fixture controller interrupted')
    for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP): handlers[number] = signal.signal(number, interrupted)
    try:
        verify(plan['review']); review = read(plan['review']['path'])
        before = source_checks(review); save(OUT/'source-before.json', before)
        require(plan['probe_ledger'] == review['probe_ledger']
                and plan['control_ledger'] == review['control_ledger']
                and plan['expected_ids'] == (SOURCE/'expected-test-ids.txt').read_text().splitlines()
                and plan['python'] == {'path': PYTHON, 'sha256': PYTHON_SHA},
                'Plan source/runtime attribution differs')
        require(digest(sys.executable) == PYTHON_SHA, 'Wrong Python executable')
        fd = os.open(LOCK, os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW, 0o600); lock = os.fdopen(fd, 'r+')
        a = os.fstat(fd); b = LOCK.lstat()
        require(stat.S_ISREG(a.st_mode) and a.st_uid == os.getuid() and (a.st_dev,a.st_ino) == (b.st_dev,b.st_ino), 'Unsafe lock')
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        admission = load(HERE/'reused/admission.py', 'fixture_admission').admission(cpu=4)
        save(OUT/'admission.json', admission); os.sched_setaffinity(0, {4})
        SCRATCH.mkdir(mode=0o700); (SCRATCH/'tmp').mkdir(mode=0o700)
        runtime = runtime_snapshot(); save(OUT/'runtime-before.json', runtime)
        sys.path.insert(0, read(HERE/'python-envelope.json')['site_directory'])
        supervisor = load(HERE/'reused/supervisor.py', 'fixture_supervisor')
        command = namespace(args.plan, args.plan_sha256)
        save(OUT/'actual-command.json', {'argv': command, 'cwd': str(HERE), 'environment': environment()})
        outcome = supervisor.run_owned(command, python_executable=PYTHON, cwd=HERE, env=environment(),
            log_path=OUT/'worker.log', receipt_path=OUT/'supervisor.json', working_directory=SCRATCH,
            timeout_seconds=300, max_process_tree_rss_bytes=8*1024**3, min_free_disk_bytes=1024**3)
        result['supervisor'] = pin(OUT/'supervisor.json')
        result['cleanup_verified'] = outcome.get('cleanup',{}).get('verified') is True
        require(outcome['status'] == 'complete' and outcome['returncode'] == 0
                and outcome['cleanup']['empty_tree_certificate'] == 'kernel_ECHILD'
                and outcome['cleanup']['remaining'] == [] and not outcome['cleanup']['signals']
                and not outcome['cleanup']['hard_kill'], 'Unclean or failed worker')
        fixture = read(SCRATCH/'fixture-result.json'); result['fixture_result'] = pin(SCRATCH/'fixture-result.json')
        require(fixture['status'] == 'passed' and fixture['expected_ids'] == plan['expected_ids']
                and sorted(fixture['started_ids']) == sorted(plan['expected_ids'])
                and sorted(fixture['success_ids']) == sorted(plan['expected_ids'])
                and fixture['tests_run'] == 5 and fixture['failures'] == [] and fixture['errors'] == []
                and fixture['skips'] == [] and fixture['unexpected_successes'] == []
                and fixture['expected_failures'] == [] and fixture['forbidden_events'] == []
                and fixture['source_control_bytes_unchanged'] is True, 'Not all five exact fixtures passed')
        result['status'] = 'passed'
    except BaseException as error: result['error'] = repr(error)
    finally:
        # Also retain postchecks if supervision raises or the worker fails.
        if runtime is not None and before is not None:
            try:
                after=runtime_snapshot();save(OUT/'runtime-after.json',after)
                source_after=source_checks(review);save(OUT/'source-after.json',source_after)
                require(runtime==after and before==source_after,'Source/runtime changed')
                result['source_runtime_unchanged']=True
            except BaseException as error:
                result.update(status='failed',posthash_error=repr(error),source_runtime_unchanged=False)
        result['elapsed_seconds'] = time.monotonic()-start
        save(OUT/'result.json', result)
        if lock: lock.close()
        for number, handler in handlers.items(): signal.signal(number, handler)
    return 0 if result['status'] == 'passed' else 1

def main():
    require(sys.flags.isolated and sys.flags.no_site and sys.flags.dont_write_bytecode
            and sys.pycache_prefix == str(SCRATCH/'pycache'), 'Use the pinned isolated launch command')
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('action', choices=['prepare','run'])
    parser.add_argument('--plan', type=Path, required=True); parser.add_argument('--plan-sha256')
    parser.add_argument('--review', type=Path); parser.add_argument('--review-sha256'); args = parser.parse_args()
    return prepare(args) if args.action == 'prepare' else run(args)

if __name__ == '__main__': raise SystemExit(main())
