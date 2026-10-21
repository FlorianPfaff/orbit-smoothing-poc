#!/usr/bin/env python3
"""Finite candidate validation inside a verified paused-campaign boundary."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

BASE = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20')
ROOT = Path('/mnt/d/orbit-numerics-v3.1/correctness')
SOURCE = ROOT/'source-02'
CONTROL = ROOT/'control'
RUN = ROOT/'validation-03'
PYTHON = BASE/'work/numerics-v3.1/python/bin/python'
WRAPPER = CONTROL/'with_correctness_namespace_03.py'
SPEC = CONTROL/'live-campaign-spec.json'
PAUSE = CONTROL/'pause-03.json'
RESUME = CONTROL/'resume-03.json'
NATIVE_SOURCE = ROOT/'groops-source-02'
BUILD = ROOT/'build-02'
OLD_CASES = Path('/mnt/d/orbit-numerics-v3.1-artifacts/engineering/objective-validation-near-03')
INITIAL = Path('/mnt/d/orbit-numerics-v3.1/engineering-archive/development-fits-07/pulses-staged/point-029-confirmation/physical_initial.txt')

BINARIES = ROOT/'binaries-02'
TEMPORARY = ROOT/'temporary-03'
PINS = CONTROL/'candidate03-pins.json'  # Intentionally absent until root seals source02.
PRIOR = ROOT/'validation-02/pipeline.json'
NEW_REPLAY = ROOT/'validation-02/objective-log_drag_ou/point-012-direction-0.25--1-repeat/profile.xml'
FLIGHT_PREPARED = BASE/'work/v3/utc-receiver-epoch-check/normal/preparation_manifest.json'
FULL_DAY_REQUEST = BASE/'work/numerics-v3.1/resource-preflight-24h-request.json'
ORIGINAL_TESTS = ['tests/test_numerics_native_qr.py', 'tests/test_numerics_original_objective.py',
                  'tests/test_numerics_mean_residual.py', 'tests/test_numerics_derivatives.py']
PINNED_INPUTS = {
    'prior_validation': PRIOR,
    'initial_state': INITIAL,
    'density_request': OLD_CASES/'log_drag_ou-staged/request.json',
    'pulse_request': OLD_CASES/'pulses-staged/request.json',
    'old_nuisance_replay': OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/profile.xml',
    'candidate1_nuisance_replay': NEW_REPLAY,
    'flight_prepared': FLIGHT_PREPARED,
    'full_day_request': FULL_DAY_REQUEST,
    'old_replay_variational': OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/closure-02/variational.dat',
    'old_replay_reference': OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/closure-02/reference.txt',
    'old_replay_density': OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/native/log_density.txt',
    'new_replay_variational': NEW_REPLAY.parent/'closure-02/variational.dat',
    'new_replay_reference': NEW_REPLAY.parent/'closure-02/reference.txt',
    'new_replay_density': NEW_REPLAY.parent/'native/log_density.txt',
}
REPLAY_DEPENDENCIES = {
    'old_nuisance_replay': {'inputfileVariational':'old_replay_variational',
        'inputfileNumericsReferenceParameters':'old_replay_reference','inputfileLogDensity':'old_replay_density'},
    'candidate1_nuisance_replay': {'inputfileVariational':'new_replay_variational',
        'inputfileNumericsReferenceParameters':'new_replay_reference','inputfileLogDensity':'new_replay_density'},
}
# Shared GNSS observations/products stay in the pre-existing frozen read-only
# preparation inventory; these extra pins bind each selected fixed physical orbit.



def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = Path(str(path)+'.writing')
    with temporary.open('w') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def source_receipt():
    names = subprocess.check_output(['git', '-C', str(SOURCE), 'ls-files', '-z', '--cached', '--others', '--exclude-standard']).split(b'\0')
    files = {name.decode(): sha(SOURCE/name.decode()) for name in names if name and (SOURCE/name.decode()).is_file()}
    return {'files': files, 'sha256': hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def interrupted(number, _frame):
    raise KeyboardInterrupt('Validation interrupted by signal '+str(number))


@contextmanager
def cleanup_signals():
    # A second ordinary interrupt must not abandon cleanup or its receipt.
    previous = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    for number in previous:
        signal.signal(number, signal.SIG_IGN)
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def proc(pid):
    root = Path('/proc')/str(pid)
    fields = (root/'stat').read_text().rsplit(')', 1)[1].split()
    try:
        namespace = os.readlink(root/'ns/pid')
    except PermissionError:
        namespace = None  # Other users' namespace links may be unreadable.
    return {'pid': pid, 'start_ticks': int(fields[19]), 'parent': int(fields[1]),
            'state': fields[0], 'pid_namespace': namespace}


def table():
    result = {}
    for path in Path('/proc').iterdir():
        if path.name.isdigit():
            try:
                value = proc(int(path.name)); result[value['pid']] = value
            except (FileNotFoundError, ProcessLookupError):
                pass
    return result


class OwnedCommand:
    """One separate session, whose actual workload has a private PID namespace.

    The wrapper's PID-namespace init owns nested setsid processes. Killing the
    wrapper/session kills that init and the kernel kills its complete namespace.
    Known process identities and namespace membership are independently checked
    before any campaign resume. No psutil or process-name signalling is used.
    """
    def __init__(self, command, *, cwd, env, log):
        self.child = None
        self.known = {}
        self.namespaces = set()
        self.host_namespace = os.readlink('/proc/self/ns/pid')
        self.cleanup_verified = False
        self.last_cleanup = None
        self.child = subprocess.Popen(list(map(str, command)), cwd=cwd, env=env,
                                      stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        # No operation after Popen may escape the caller's cleanup ownership.

    def observe(self):
        values = table()
        root = values.get(self.child.pid)
        original = self.known.get(self.child.pid)
        descendants = ({self.child.pid} if root and (original is None or root['start_ticks'] == original['start_ticks']) else set())
        descendants.update(pid for pid, old in self.known.items() if pid in values and values[pid]['start_ticks'] == old['start_ticks'])
        changed = True
        while changed:
            changed = False
            for pid, value in values.items():
                if value['parent'] in descendants and pid not in descendants:
                    descendants.add(pid); changed = True
        for pid in descendants:
            value = values.get(pid)
            if value:
                old = self.known.get(pid)
                if old and old['start_ticks'] != value['start_ticks']:
                    continue
                self.known[pid] = value
                if value['pid_namespace'] and value['pid_namespace'] != self.host_namespace:
                    self.namespaces.add(value['pid_namespace'])
        return values

    def live(self):
        values = self.observe()
        live = []
        for pid, value in values.items():
            known = self.known.get(pid)
            if value['state'] == 'Z':
                continue  # Zombies cannot run or retain native working memory.
            if ((known and known['start_ticks'] == value['start_ticks'])
                    or value['pid_namespace'] in self.namespaces):
                live.append(value)
        return live

    def cleanup(self, *, force, timeout=15.):
        with cleanup_signals():
            self.observe()
            was_running = self.child.poll() is None
            if (force or self.live()) and self.child.returncode is None:
                # A live/unreaped Popen child still owns its fresh session ID.
                # Never signal its numeric process group after it has been reaped.
                try:
                    os.killpg(self.child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic()+timeout
            while True:
                self.child.poll()
                remaining = self.live()
                if self.child.returncode is not None and not remaining:
                    self.cleanup_verified = True
                    self.last_cleanup = {'verified': True, 'observed_at': stamp(),
                        'forced': force, 'was_running': was_running,
                        'returncode': self.child.returncode,
                        'identities': list(self.known.values()), 'pid_namespaces': sorted(self.namespaces),
                        'live_owned_processes': [], 'zombie_policy': 'Non-executing zombies are excluded from live workload checks.'}
                    return self.last_cleanup
                if time.monotonic() >= deadline:
                    self.last_cleanup = {'verified': False, 'observed_at': stamp(), 'live_owned_processes': remaining}
                    raise RuntimeError('Candidate workload cleanup is unconfirmed; campaign must stay paused')
                time.sleep(.05)


def supervise(command, *, cwd, env, log, limit, guard_live, on_started, on_finished,
              registry, poll_seconds=.5):
    owned = OwnedCommand(command, cwd=cwd, env=env, log=log)
    registry.append(owned)
    started = time.monotonic()
    failure = None
    try:
        owned.observe()
        on_started(owned.child.pid)
        while True:
            owned.observe()
            guard_live()
            code = owned.child.poll()
            if code is not None:
                return code
            if time.monotonic()-started >= limit:
                raise subprocess.TimeoutExpired(command, limit)
            time.sleep(min(poll_seconds, max(.001, limit-(time.monotonic()-started))))
    except BaseException as error:
        failure = error
        raise
    finally:
        # Includes on_started receipt errors and guard failures after Popen.
        try:
            cleanup = owned.cleanup(force=failure is not None)
        finally:
            on_finished({'elapsed_seconds': time.monotonic()-started,
                         'cleanup': owned.last_cleanup,
                         'interrupted_or_timeout': failure is not None})


def load_boundary():
    spec = importlib.util.spec_from_file_location('boundary_pause', CONTROL/'boundary_pause.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_required_pins():
    """No default pins: this guard runs before lock or paused-campaign ownership."""
    if not PINS.is_file():
        raise RuntimeError('Required candidate03 pins are unset; root must freeze source and controls first')
    pins = json.loads(PINS.read_text())
    required = {'schema', 'source_sha256', 'wrapper_sha256', 'boundary_sha256', 'spec_sha256',
                'driver_sha256', 'additional_native_tests', 'expected_native_test_count', 'input_artifacts'}
    if set(pins) != required or pins['schema'] != 'orbit-poc-correctness-candidate03-pins-v1':
        raise RuntimeError('Unknown or missing candidate03 pin fields')
    for key in ('source_sha256','wrapper_sha256','boundary_sha256','spec_sha256','driver_sha256'):
        value = pins[key]
        if not isinstance(value,str) or len(value) != 64 or any(x not in '0123456789abcdef' for x in value):
            raise RuntimeError('Unset or invalid required pin: '+key)
    tests = pins['additional_native_tests']
    if (not isinstance(tests,list) or len(tests)<2 or len(set(tests)) != len(tests)
            or 'tests/test_numerics_geometry_precision.py' not in tests
            or any(not isinstance(x,str) or not x.startswith('tests/test_') or not x.endswith('.py')
                   or len(Path(x).parts)!=2 or x in ORIGINAL_TESTS for x in tests)):
        raise RuntimeError('Required geometry and synthetic-force test pins are unset or invalid')
    count = pins['expected_native_test_count']
    if type(count) is not int or count <= 88:
        raise RuntimeError('Expanded expected native test count is unset')
    if not isinstance(pins['input_artifacts'],dict) or set(pins['input_artifacts']) != set(PINNED_INPUTS):
        raise RuntimeError('Exact input artifact pins are required')
    for role,path in PINNED_INPUTS.items():
        item = pins['input_artifacts'][role]
        if not isinstance(item,dict) or set(item) != {'path','sha256'} or item['path'] != str(path):
            raise RuntimeError('Input path pin differs: '+role)
        value=item['sha256']
        if not isinstance(value,str) or len(value)!=64 or any(x not in '0123456789abcdef' for x in value):
            raise RuntimeError('Input digest pin is unset: '+role)
    return pins


def verify_control_pins(pins):
    for path,key in ((Path(__file__),'driver_sha256'),(WRAPPER,'wrapper_sha256'),
                     (CONTROL/'boundary_pause.py','boundary_sha256'),(SPEC,'spec_sha256')):
        if sha(path) != pins[key]:
            raise RuntimeError('Control pin changed: '+str(path))


def verify_pins(pins):
    verify_control_pins(pins)
    current = source_receipt()
    if current['sha256'] != pins['source_sha256']:
        raise RuntimeError('Source02 inventory differs from the required frozen pin')
    for role,path in PINNED_INPUTS.items():
        if sha(path) != pins['input_artifacts'][role]['sha256']:
            raise RuntimeError('Prescribed input changed: '+role)
    import xml.etree.ElementTree as ET
    for role,fields in REPLAY_DEPENDENCIES.items():
        root = ET.parse(PINNED_INPUTS[role]).getroot()
        for tag,dependency_role in fields.items():
            values = {item.text for item in root.iter(tag)}
            if values != {str(PINNED_INPUTS[dependency_role])}:
                raise RuntimeError('Replay fixed physical dependency differs: '+role+'/'+tag)
    for test in ORIGINAL_TESTS + pins['additional_native_tests']:
        if test not in current['files'] or not (SOURCE/test).is_file():
            raise RuntimeError('Required native test missing from frozen source: '+test)
    prior = json.loads(PRIOR.read_text())
    if (prior.get('status') != 'failed' or (prior.get('final_cleanup') or {}).get('verified') is not True
            or (prior.get('resume') or {}).get('status') != 'resumed'):
        raise RuntimeError('Prior validation02 must remain closed, failed, and resumed')
    return current


def prepare_writable_directories():
    for path in (NATIVE_SOURCE, BUILD, BINARIES, TEMPORARY):
        if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
            raise RuntimeError('Fresh native/build/binary/temp path must be absent or empty: '+str(path))
    for path in (NATIVE_SOURCE, BUILD, BINARIES, TEMPORARY):
        path.mkdir(exist_ok=True)


def verify_native_junit(path, expected):
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    cases = list(root.iter('testcase'))
    failures = sum(any(child.tag in ('failure','error','skipped') for child in case) for case in cases)
    if len(cases) != expected or failures:
        raise RuntimeError('Native test inventory differs or contains failures/errors/skips')
    return {'tests':len(cases),'passed':len(cases),'failures':0,'errors':0,'skipped':0}


def main():
    pins = load_required_pins()
    verify_control_pins(pins)
    pin_file_sha = sha(PINS)
    boundary = load_boundary()
    # Lock the reviewed pause control while any candidate workload may exist.
    # Duplicate driver launches fail before acquiring resume ownership.
    with (CONTROL/'candidate-validation.lock').open('a') as driver_lock:
        fcntl.flock(driver_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if RUN.exists():
            raise RuntimeError('Choose a new validation directory; no evidence may be overwritten')
        pause_lock = Path(str(SPEC)+'.control.lock').open('a')
        fcntl.flock(pause_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        registry = []
        journal = {'schema': 'orbit-poc-correctness-validation-run-v2', 'status': 'starting',
            'started_at': stamp(), 'steps': [], 'helper_sha256': sha(__file__),
            'scope': 'Separate correctness candidate; does not replace or certify the frozen 150-attempt benchmark.'}
        journal_ready = False
        caught = None
        try:
            frozen = boundary.read(SPEC)
            paused = boundary.read(PAUSE)
            if paused.get('status') != 'paused' or not paused.get('heavy_work_permitted'):
                raise RuntimeError('No verified inactive-fit pause receipt')
            if paused.get('specification') != boundary.artifact(SPEC):
                raise RuntimeError('Pause specification changed')
            if boundary.check_spec(frozen)['state'] != 'T':
                raise RuntimeError('Frozen campaign is not stopped at its boundary')
            RUN.mkdir()
            journal_ready = True
            journal.update(source=verify_pins(pins), required_pins=boundary.artifact(PINS),
                           prior_failed_validation=boundary.artifact(PRIOR), wrapper=boundary.artifact(WRAPPER),
                           control_python=boundary.artifact(Path(sys.executable).resolve()),
                           pause_receipt=boundary.artifact(PAUSE), specification=boundary.artifact(SPEC))
            if '--unshare-pid' not in WRAPPER.read_text():
                raise RuntimeError('Reviewed wrapper must create a private PID namespace')
            prepare_writable_directories()
            save(RUN/'pipeline.json', journal)
            for number in (signal.SIGINT, signal.SIGTERM):
                signal.signal(number, interrupted)

            def unchanged():
                if sha(PINS) != pin_file_sha:
                    raise RuntimeError('Required candidate03 pins changed')
                if verify_pins(pins) != journal['source']:
                    raise RuntimeError('Correctness source changed during validation')
                if boundary.artifact(WRAPPER) != journal['wrapper']:
                    raise RuntimeError('Correctness PID namespace wrapper changed')
                if sha(__file__) != journal['helper_sha256']:
                    raise RuntimeError('Validation control helper changed')

            def guard_live():
                # Cheap poll: no source/data hashing while a workload is active.
                if boundary.require_process(frozen['campaign_process'])['state'] != 'T':
                    raise RuntimeError('Frozen campaign resumed unexpectedly; stop candidate workload')
                boundary.require_process(frozen['outer_process'])

            def guard():
                guard_live()
                boundary.check_spec(frozen)
                observed = boundary.verify_boundary(frozen)
                if not observed['safe'] or observed['checkpoint_signature'] != paused['after']['checkpoint_signature']:
                    raise RuntimeError('Frozen campaign boundary changed')
                boundary.deadline(frozen)
                unchanged()

            def run(name, command, limit, *, required=True):
                guard()
                actual = [PYTHON, WRAPPER, *command]
                entry = {'name': name, 'argv': list(map(str, actual)), 'started_at': stamp(), 'timeout_seconds': limit}
                journal.update(status='running', phase=name)
                journal['steps'].append(entry)
                save(RUN/'pipeline.json', journal)
                env = dict(os.environ, PYTHONPATH=str(SOURCE/'src'), PYTHONDONTWRITEBYTECODE='1',
                    OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                    NUMEXPR_NUM_THREADS='1', TMPDIR=str(TEMPORARY))
                def on_started(pid):
                    entry['pid'] = pid
                    save(RUN/'pipeline.json', journal)
                def on_finished(value):
                    entry.update(value, finished_at=stamp())
                    save(RUN/'pipeline.json', journal)
                try:
                    with (RUN/(name+'.log')).open('w') as log:
                        entry['returncode'] = supervise(actual, cwd=SOURCE, env=env, log=log, limit=limit,
                            guard_live=guard_live, on_started=on_started, on_finished=on_finished, registry=registry)
                except BaseException:
                    entry['status'] = 'interrupted_timeout_or_supervision_failure'
                    raise
                guard()
                entry['status'] = 'passed' if entry['returncode'] == 0 else 'failed'
                save(RUN/'pipeline.json', journal)
                if required and entry['returncode']:
                    raise RuntimeError(name+' failed; inspect the preserved log')
                return entry['returncode'] == 0

            guard()
            if any(NATIVE_SOURCE.iterdir()) or any(BUILD.iterdir()):
                raise RuntimeError('Correctness native source/build must initially be empty')
            run('clone', ['git', 'clone', '--no-hardlinks', '--no-checkout', BASE/'work/numerics-v3.1/groops-source', NATIVE_SOURCE], 600)
            run('checkout', ['git', '-C', NATIVE_SOURCE, 'checkout', '--detach', '7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'], 600)
            run('build', ['taskset', '-c', '24-27', PYTHON, SOURCE/'scripts/build_groops.py',
                '--source-dir', NATIVE_SOURCE, '--build-dir', BUILD, '--prefix', BASE/'work/v3/native-env',
                '--cmake-executable', BASE/'work/numerics-v3.1/python/bin/cmake', '--numerics', '--jobs', '4'], 7200)
            import shutil
            native_hash = sha(BUILD/'groops')
            binary_dir = BINARIES
            binary_dir.mkdir(exist_ok=True)
            native = binary_dir/('groops-'+native_hash[:16])
            if native.exists():
                raise RuntimeError('Refusing to overwrite a correctness candidate')
            shutil.copy2(BUILD/'groops', native)
            shutil.copy2(BUILD/'build-manifest.json', str(native)+'.build-manifest.json')
            native.chmod(0o555)
            if sha(native) != native_hash or json.loads((BUILD/'build-manifest.json').read_text())['executable_sha256'] != native_hash:
                raise RuntimeError('Archived executable disagrees with its actual build')
            journal['native'] = {'path': str(native), 'sha256': native_hash, 'build_manifest_sha256': sha(str(native)+'.build-manifest.json')}
            save(RUN/'pipeline.json', journal)
            common = ['taskset', '-c', '28', 'env', 'ORBIT_POC_CORRECTNESS_NATIVE='+str(native),
                      'ORBIT_POC_V31_NATIVE='+str(native), 'ORBIT_POC_GROOPS='+str(native)]
            run('native-tests', common+[PYTHON, '-m', 'pytest', '-q', '-s', '-p', 'no:cacheprovider',
                '--basetemp='+str(RUN/'pytest-temp'), '--junitxml='+str(RUN/'native-tests.xml'),
                *ORIGINAL_TESTS, *pins['additional_native_tests']], 3600)
            journal['native_test_inventory'] = verify_native_junit(RUN/'native-tests.xml', pins['expected_native_test_count'])
            save(RUN/'pipeline.json', journal)
            outcomes = []
            for method in ('log_drag_ou', 'pulses'):
                name = 'synthetic-refinement-'+method
                outcomes.append(run(name, common+[PYTHON, SOURCE/'scripts/validate_numerics_synthetic_refinement.py',
                    '--request', OLD_CASES/(method+'-staged')/'request.json', '--binary', native,
                    '--output', RUN/name], 7200, required=False))
            outcomes.append(run('flight-refinement', common+[PYTHON, SOURCE/'scripts/validate_numerics_flight_refinement.py',
                '--prepared', FLIGHT_PREPARED, '--binary', native, '--output', RUN/'flight-refinement'], 7200, required=False))
            outcomes.append(run('eccentric-24h-refinement', common+[PYTHON, SOURCE/'scripts/validate_numerics_synthetic_refinement.py',
                '--request', FULL_DAY_REQUEST, '--binary', native, '--output', RUN/'eccentric-24h-refinement'], 7200, required=False))
            for method in ('log_drag_ou', 'pulses'):
                name = 'objective-'+method
                outcomes.append(run(name, common+[PYTHON, SOURCE/'scripts/validate_numerics_objective.py',
                    '--request', OLD_CASES/(method+'-staged')/'request.json', '--native-binary', native,
                    '--initial-state-from', INITIAL, '--output', RUN/name], 7200, required=False))
            outcomes.append(run('nuisance-replay', common+[PYTHON, SOURCE/'scripts/validate_numerics_nuisance.py',
                '--source-profile', OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/profile.xml',
                '--native', native, '--output', RUN/'nuisance-replay', '--allow-floor-limited'], 7500, required=False))
            outcomes.append(run('nuisance-replay-candidate1-point012', common+[PYTHON, SOURCE/'scripts/validate_numerics_nuisance.py',
                '--source-profile', NEW_REPLAY, '--native', native, '--output', RUN/'nuisance-replay-candidate1-point012',
                '--allow-floor-limited'], 7500, required=False))
            if sha(native) != native_hash:
                raise RuntimeError('Correctness executable changed during validation')
            guard()
            journal.update(status='passed' if all(outcomes) else 'failed', finished_at=stamp())
        except BaseException as error:
            caught = error
            journal.update(status='failed', error=type(error).__name__+': '+str(error), finished_at=stamp())
        finally:
            # Journal failures cannot bypass cleanup/resume. A failed cleanup
            # deliberately keeps the campaign paused instead of overlapping fits.
            with cleanup_signals():
                cleanup_failures = []
                for owned in registry:
                    try:
                        owned.cleanup(force=owned.child.poll() is None)
                    except BaseException as error:
                        cleanup_failures.append(type(error).__name__+': '+str(error))
                journal['final_cleanup'] = {'verified': not cleanup_failures, 'errors': cleanup_failures,
                    'commands': [owned.last_cleanup for owned in registry]}
                pause_lock.close()
                if not cleanup_failures:
                    try:
                        journal['resume'] = boundary.resume(SPEC, PAUSE, RESUME)
                    except BaseException as error:
                        journal['resume_error'] = type(error).__name__+': '+str(error)
                        caught = caught or error
                else:
                    journal['resume_withheld'] = 'Owned correctness workload cleanup could not be verified'
                    caught = caught or RuntimeError(journal['resume_withheld'])
                if journal_ready:
                    try:
                        save(RUN/'pipeline.json', journal)
                    except BaseException as error:
                        print('Final control journal write failed: '+repr(error), file=sys.stderr)
                        caught = caught or error
        if caught:
            raise caught
        return 0 if journal['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
