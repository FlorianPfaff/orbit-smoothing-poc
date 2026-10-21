#!/usr/bin/env python3
"""Finite correctness recovery on a pinned idle host; no campaign resume semantics."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

BASE = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20')
ROOT = Path('/mnt/d/orbit-numerics-v3.1/correctness')
PRIOR = ROOT/'validation-02/pipeline.json'
OLD_CASES = Path('/mnt/d/orbit-numerics-v3.1-artifacts/engineering/objective-validation-near-03')
INITIAL = Path('/mnt/d/orbit-numerics-v3.1/engineering-archive/development-fits-07/pulses-staged/point-029-confirmation/physical_initial.txt')
NEW_REPLAY = ROOT/'validation-02/objective-log_drag_ou/point-012-direction-0.25--1-repeat/profile.xml'
FLIGHT_PREPARED = BASE/'work/v3/utc-receiver-epoch-check/normal/preparation_manifest.json'
FULL_DAY_REQUEST = BASE/'work/numerics-v3.1/resource-preflight-24h-request.json'
ORIGINAL_SOURCE_SHA256 = 'fb9560e7ea98e8f561034f856e9a977e324da7852325ff73b14bc0ae1125fbb9'
# Filled only after the separate numerical correction and regression inventory freeze.
SOURCE_FILE_COUNT = 764
SOURCE_SHA256 = '194b460ab90ed2eb3818af16324086f8cd0fe9aecd77308cd9ff45de23da660a'
ALLOWED_CORRECTION_PATHS = sorted([
    'groops/extension/native_derivatives.py','groops/extension/native_row_qr.py',
    'groops/extension/native_synthetic_force.py','groops/extension/scaledRowQr.h',
    'groops/extension/stagedVariationalBody.h','groops/extension/preciseEquinoctialReference.h',
    'groops/extension/queryPrecision.py','groops/extension/twofoldInterpolation.h',
    'tests/fixtures/twofold_interpolation_probe.cpp','tests/test_numerics_query_precision.py',
    'tests/test_numerics_reference_precision.py'])
REGRESSION_SUITE = {'files':['tests/test_numerics_query_precision.py','tests/test_numerics_reference_precision.py'],
                    'expected_count':18}
CANDIDATE03_PINS_SHA256 = '2b6a982e765a5fd963c807126fbcdb9a783b48b54ea505b8cd11866c516bc258'
ADDITIONAL_TESTS = ['tests/test_numerics_geometry_precision.py', 'tests/test_numerics_synthetic_force_arithmetic.py']
PATH_KEYS = {'root','source','native_source','build','binaries','run','temporary','control','python','cmake','prefix','upstream_repository','wrapper'}
MUTABLE_KEYS = ('native_source','build','binaries','run','temporary')
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


def artifact(path):
    path = Path(path)
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':')).encode()).hexdigest()


def require_digest(value, name):
    if not isinstance(value, str) or len(value)!=64 or any(x not in '0123456789abcdef' for x in value):
        raise RuntimeError('Invalid required digest: '+name)


def load_execution(path):
    value=json.loads(Path(path).read_text())
    required={'schema','host','paths','build_cpus','fit_cpu','read_only_bindings','runtime_artifacts','reserved_cpu_note'}
    if set(value)!=required or value['schema']!='orbit-poc-correctness-execution-v1':
        raise RuntimeError('Unknown or missing execution fields')
    if set(value['host'])!={'hostname','boot_id'} or not all(isinstance(v,str) and v for v in value['host'].values()):
        raise RuntimeError('Expected host identity is required')
    if set(value['paths'])!=PATH_KEYS:
        raise RuntimeError('Unknown or missing execution paths')
    for name, raw in value['paths'].items():
        if not isinstance(raw,str) or not Path(raw).is_absolute() or '..' in Path(raw).parts:
            raise RuntimeError('Execution path must be absolute: '+name)
    recovery_root=Path(value['paths']['root'])
    if len(recovery_root.parts)<3:raise RuntimeError('Recovery root must be a dedicated nested directory')
    for name in (*MUTABLE_KEYS,'source','control','wrapper'):
        if recovery_root not in Path(value['paths'][name]).parents:
            raise RuntimeError('Recovery-owned path must remain beneath its dedicated root: '+name)
    locations=[Path(value['paths'][name]) for name in MUTABLE_KEYS]
    source=Path(value['paths']['source'])
    for i,path in enumerate(locations):
        if any(path==other or path in other.parents or other in path.parents for other in locations[i+1:]):
            raise RuntimeError('Writable directories must be disjoint')
        if source==path or source in path.parents or path in source.parents:
            raise RuntimeError('Frozen source must be separate from writable directories')
    cpus=value['build_cpus']
    if not isinstance(cpus,list) or len(cpus)!=4 or len(set(cpus))!=4 or any(type(c)!=int or c<0 for c in cpus):
        raise RuntimeError('Exactly four distinct nonnegative build CPUs required')
    if type(value['fit_cpu'])!=int or value['fit_cpu']<0:
        raise RuntimeError('Exactly one nonnegative fit CPU required')
    if not isinstance(value['reserved_cpu_note'],str) or not value['reserved_cpu_note'].strip():
        raise RuntimeError('CPU reservation provenance is required')
    bindings=value['read_only_bindings']
    if not isinstance(bindings,list):raise RuntimeError('Read-only bindings must be a list')
    seen=set()
    for row in bindings:
        if not isinstance(row,dict) or set(row)!={'source','target'}:
            raise RuntimeError('Invalid read-only binding')
        for key in row:
            if not isinstance(row[key],str) or not Path(row[key]).is_absolute() or '..' in Path(row[key]).parts:
                raise RuntimeError('Binding paths must be absolute')
        target=Path(row['target'])
        if target in seen:raise RuntimeError('Duplicate namespace target')
        seen.add(target)
        if any(target==w or target in w.parents or w in target.parents for w in locations):
            raise RuntimeError('Read-only aliases must not overlap writable directories')
    artifacts=value['runtime_artifacts']
    if not isinstance(artifacts,dict) or not {'control_python','python','cmake','bubblewrap','taskset'}<=set(artifacts):
        raise RuntimeError('Required runtime pins are missing')
    for key,row in artifacts.items():
        if not isinstance(row,dict) or set(row)!={'path','sha256'} or not Path(row['path']).is_absolute():
            raise RuntimeError('Invalid runtime artifact: '+key)
        require_digest(row['sha256'],key)
    for key in ('python','cmake'):
        if artifacts[key]['path']!=value['paths'][key]:
            raise RuntimeError('Runtime executable path mismatch: '+key)
    if artifacts['bubblewrap']['path']!='/usr/bin/bwrap' or artifacts['taskset']['path']!='/usr/bin/taskset':
        raise RuntimeError('Namespace and affinity executable paths must be explicit system paths')
    return value


def host_path(path, execution):
    path=Path(path)
    matches=[]
    for row in execution['read_only_bindings']:
        target=Path(row['target'])
        if path==target or target in path.parents:
            matches.append((len(target.parts),Path(row['source'])/path.relative_to(target)))
    return max(matches,key=lambda x:x[0])[1] if matches else path



def resolved_host_path(path, execution):
    """Resolve canonical absolute symlinks through read-only aliases, never host fallbacks.

    Conda/venv links embed the original canonical prefix. Resolving the staged
    symlink with pathlib alone would accidentally read the unrelated host path.
    Each link is mapped again; cycles and more than 64 link traversals fail.
    """
    logical=Path(path)
    seen=set()
    for _ in range(65):
        physical=host_path(logical,execution)
        if physical in seen:raise RuntimeError('Canonical alias symlink cycle: '+str(path))
        seen.add(physical)
        parts=physical.parts
        for index in range(1,len(parts)+1):
            prefix=Path(*parts[:index])
            if prefix.is_symlink():
                target=Path(os.readlink(prefix))
                remaining=parts[index:]
                logical=Path(os.path.normpath(str((target if target.is_absolute() else prefix.parent/target).joinpath(*remaining))))
                break
        else:
            if not physical.exists():raise RuntimeError('Mapped canonical artifact is missing: '+str(path))
            return physical
    raise RuntimeError('Canonical alias symlink traversal limit: '+str(path))


def source_receipt(source):
    source=Path(source)
    if source.is_symlink() or not source.is_dir():raise RuntimeError('Source snapshot is not a real directory')
    names=[]
    for path in source.rglob('*'):
        relative=path.relative_to(source)
        if relative.parts[0]=='.git':continue
        if path.is_symlink():raise RuntimeError('Frozen source contains a symlink: '+str(relative))
        if path.is_file():names.append(path)
    files={str(path.relative_to(source)):sha(path) for path in sorted(names)}
    return {'files':files,'sha256':digest(files)}


def load_required_pins(path, execution_path):
    path=Path(path)
    if not path.is_file():raise RuntimeError('Required candidate06 pins are unset')
    pins=json.loads(path.read_text())
    expected={'schema','source_sha256','source_file_count','driver_sha256','wrapper_sha256','execution_sha256',
              'additional_native_tests','expected_native_test_count','input_artifacts',
              'candidate03_pins','source_freeze','interruption_record','new_source_freeze',
              'correction_lineage','allowed_correction_paths','regression_suite','recovery_verifier_sha256'}
    if set(pins)!=expected or pins['schema']!='orbit-poc-correctness-candidate06-pins-v1':
        raise RuntimeError('Unknown or missing candidate06 pin fields')
    require_digest(SOURCE_SHA256,'unfrozen corrected source')
    for key in ('source_sha256','driver_sha256','wrapper_sha256','execution_sha256','recovery_verifier_sha256'):require_digest(pins[key],key)
    if pins['source_sha256']!=SOURCE_SHA256 or pins['source_file_count']!=SOURCE_FILE_COUNT:
        raise RuntimeError('Correction must match its independently frozen source inventory')
    if pins['allowed_correction_paths']!=ALLOWED_CORRECTION_PATHS or pins['regression_suite']!=REGRESSION_SUITE:
        raise RuntimeError('Correction paths or separate regression inventory changed')
    if pins['expected_native_test_count']!=106 or pins['additional_native_tests']!=ADDITIONAL_TESTS:
        raise RuntimeError('Recovery must retain the exact 106-test inventory')
    if pins['execution_sha256']!=sha(execution_path):raise RuntimeError('Execution configuration changed')
    for key in ('candidate03_pins','source_freeze','interruption_record','new_source_freeze','correction_lineage'):
        item=pins[key]
        if not isinstance(item,dict) or set(item)!={'path','sha256'} or not Path(item['path']).is_absolute():
            raise RuntimeError('Invalid required historical artifact: '+key)
        require_digest(item['sha256'],key)
    if pins['candidate03_pins']['sha256']!=CANDIDATE03_PINS_SHA256:
        raise RuntimeError('Original candidate03 pins must be preserved')
    if not isinstance(pins['input_artifacts'],dict) or set(pins['input_artifacts'])!=set(PINNED_INPUTS):
        raise RuntimeError('Exact 14 input artifact pins required')
    for role,path in PINNED_INPUTS.items():
        item=pins['input_artifacts'][role]
        if not isinstance(item,dict) or set(item)!={'path','sha256'} or item['path']!=str(path):
            raise RuntimeError('Input canonical path differs: '+role)
        require_digest(item['sha256'],role)
    return pins


def verify_pins(pins, execution, execution_path):
    paths=execution['paths']
    for path,key in ((Path(__file__),'driver_sha256'),(Path(paths['wrapper']),'wrapper_sha256'),(execution_path,'execution_sha256')):
        if sha(path)!=pins[key]:raise RuntimeError('Control pin changed: '+str(path))
    for name,row in execution['runtime_artifacts'].items():
        if sha(resolved_host_path(row['path'],execution))!=row['sha256']:raise RuntimeError('Runtime pin changed: '+name)
    if resolved_host_path(execution['runtime_artifacts']['control_python']['path'],execution).resolve()!=Path(sys.executable).resolve():
        raise RuntimeError('Control interpreter path differs from execution pin')
    historic={}
    for name in ('candidate03_pins','source_freeze','interruption_record'):
        row=pins[name]; path=host_path(row['path'],execution)
        if sha(path)!=row['sha256']:raise RuntimeError('Historical artifact changed: '+name)
        historic[name]=json.loads(path.read_text())
    prior=historic['candidate03_pins']
    if (prior.get('input_artifacts')!=pins['input_artifacts'] or prior.get('source_sha256')!=ORIGINAL_SOURCE_SHA256
            or prior.get('expected_native_test_count')!=106 or prior.get('additional_native_tests')!=ADDITIONAL_TESTS):
        raise RuntimeError('Scientific inputs differ from interrupted candidate03')
    frozen=historic['source_freeze'].get('source')
    if not isinstance(frozen,dict) or len(frozen.get('files',{}))!=758 or frozen.get('sha256')!=ORIGINAL_SOURCE_SHA256:
        raise RuntimeError('Historical source inventory mismatch')
    current=source_receipt(paths['source'])
    import importlib.util
    helper_path=Path(__file__).with_name('recovery_evidence_06.py')
    if sha(helper_path)!=pins['recovery_verifier_sha256']:raise RuntimeError('Correction verifier changed')
    spec=importlib.util.spec_from_file_location('driver_correction_lineage06',helper_path)
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    def read_pin(item,role):
        path=Path(item['path'])
        if sha(path)!=item['sha256']:raise RuntimeError('Correction artifact changed: '+role)
        return json.loads(path.read_text())
    helper.validate_correction(pins,frozen,current,execution,read_pin)
    restart=historic['interruption_record']
    if (restart.get('status')!='interrupted_by_host_restart'
            or restart.get('previous_boot_id')==restart.get('observed_boot_id')
            or not restart.get('previous_boot_id') or not restart.get('observed_boot_id')
            or restart.get('native_tests_produced') is not False or restart.get('native_binary_produced') is not False):
        raise RuntimeError('Interrupted-run provenance is incomplete or not a restart')
    historical_pipeline=restart.get('prior_pipeline',{})
    if not {'path','sha256'}<=set(historical_pipeline):raise RuntimeError('Missing interrupted pipeline pin')
    old_pipeline_path=host_path(historical_pipeline['path'],execution)
    if sha(old_pipeline_path)!=historical_pipeline['sha256']:raise RuntimeError('Interrupted pipeline changed')
    old_pipeline=json.loads(old_pipeline_path.read_text())
    if old_pipeline.get('native') or any(s.get('name')=='native-tests' for s in old_pipeline.get('steps',[])):
        raise RuntimeError('Interruption claim disagrees with preserved pipeline')
    for role,path in PINNED_INPUTS.items():
        if sha(host_path(path,execution))!=pins['input_artifacts'][role]['sha256']:
            raise RuntimeError('Prescribed input changed: '+role)
    import xml.etree.ElementTree as ET
    for role,fields in REPLAY_DEPENDENCIES.items():
        root=ET.parse(host_path(PINNED_INPUTS[role],execution)).getroot()
        for tag,dependency_role in fields.items():
            if {node.text for node in root.iter(tag)}!={str(PINNED_INPUTS[dependency_role])}:
                raise RuntimeError('Replay fixed physical dependency differs: '+role+'/'+tag)
    prior_closed=json.loads(host_path(PRIOR,execution).read_text())
    if (prior_closed.get('status')!='failed' or (prior_closed.get('final_cleanup') or {}).get('verified') is not True
            or (prior_closed.get('resume') or {}).get('status')!='resumed'):
        raise RuntimeError('Previous failed validation02 must remain closed and resumed')
    return current


def boot():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def command_processes():
    result={}
    for pid,info in table().items():
        try:
            raw=(Path('/proc')/str(pid)/'cmdline').read_bytes()
            result[pid]={**info,'argv':[x.decode(errors='replace') for x in raw.split(b'\0') if x],
                         'command_sha256':hashlib.sha256(raw).hexdigest()}
        except (FileNotFoundError,ProcessLookupError):pass
    return result


def workload(item):
    args=item.get('argv',[])
    if not args or item.get('state')=='Z':return False
    first=Path(args[0]).name
    if first.startswith(('groops','cc1','f951','lto1')) or first in {'ninja','make','cmake','gcc','g++','cc','c++','gfortran'}:return True
    if any(Path(arg).name in {'worker-request.json','build_groops.py','orbit_poc'} for arg in args):return True
    if any(arg.startswith('orbit_poc.numerics.') or arg.startswith('orbit_poc.comparison.') for arg in args):return True
    if any(Path(arg).name.startswith(('validate_numerics_','run_comparison_','run_calibration_')) for arg in args):return True
    return False


def admission(execution, registry=()):
    expected=execution['host']
    if expected!={'hostname':socket.gethostname(),'boot_id':boot()}:
        raise RuntimeError('Pinned execution host or boot identity changed')
    allowed_cpus=set(os.sched_getaffinity(0))
    if not set(execution['build_cpus']+[execution['fit_cpu']])<=allowed_cpus:
        raise RuntimeError('Reserved CPUs are outside current affinity')
    known={os.getpid():proc(os.getpid())};namespaces=set()
    for owned in registry:
        owned.observe();known.update(owned.known);namespaces.update(owned.namespaces)
    values=command_processes();conflicts=[]
    for pid,item in values.items():
        owner=known.get(pid)
        if (owner and owner['start_ticks']==item['start_ticks']) or item['pid_namespace'] in namespaces:continue
        if workload(item):conflicts.append(item)
    if conflicts:
        raise RuntimeError('Competing native/orbit workload detected: '+json.dumps(conflicts,sort_keys=True))
    return {'status':'admitted','hostname':expected['hostname'],'boot_id':expected['boot_id'],'observed_at':stamp(),
            'driver_identity':values.get(os.getpid(),known[os.getpid()]),'conflicting_processes':[],
            'build_cpus':execution['build_cpus'],'fit_cpu':execution['fit_cpu'],
            'reserved_cpu_note':execution['reserved_cpu_note'],'policy':'serial_owned_pid_namespace_no_external_native_orbit_workload_v1'}


def prepare_writable_directories(paths):
    for key in MUTABLE_KEYS:
        path=Path(paths[key])
        if path.is_symlink() or path.exists():raise RuntimeError('Recovery path must be fresh and absent: '+str(path))
        if not path.parent.is_dir():raise RuntimeError('Recovery parent must be staged before launch: '+str(path.parent))
    for key in MUTABLE_KEYS:Path(paths[key]).mkdir()


def verify_native_junit(path, expected):
    import xml.etree.ElementTree as ET
    root=ET.parse(path).getroot();cases=list(root.iter('testcase'))
    failures=sum(any(child.tag in ('failure','error','skipped') for child in case) for case in cases)
    if len(cases)!=expected or failures:raise RuntimeError('Native test inventory differs or contains failures/errors/skips')
    return {'tests':len(cases),'passed':len(cases),'failures':0,'errors':0,'skipped':0}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution',type=Path,required=True)
    parser.add_argument('--pins',type=Path,required=True)
    parser.add_argument('--pins-sha256',required=True)
    args=parser.parse_args(argv)
    require_digest(args.pins_sha256,'sealed pin file')
    if sha(args.pins)!=args.pins_sha256:raise RuntimeError('Sealed pin file changed')
    execution=load_execution(args.execution)
    pins=load_required_pins(args.pins,args.execution)
    paths={key:Path(value) for key,value in execution['paths'].items()}
    source=verify_pins(pins,execution,args.execution)
    admitted=admission(execution)
    # The fixed host-local lock serializes all recovery launches in this control directory.
    with (paths['control']/'candidate06-validation.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        admitted=admission(execution)
        prepare_writable_directories(paths)
        SOURCE=paths['source'];RUN=paths['run'];PYTHON=paths['python'];WRAPPER=paths['wrapper']
        NATIVE_SOURCE=paths['native_source'];BUILD=paths['build'];BINARIES=paths['binaries'];TEMPORARY=paths['temporary']
        registry=[];caught=None
        journal={'schema':'orbit-poc-correctness-validation-run-v3','status':'starting','started_at':stamp(),
            'steps':[],'helper_sha256':sha(__file__),'source':source,'required_pins':artifact(args.pins),
            'execution':artifact(args.execution),'admission':admitted,'wrapper':artifact(WRAPPER),
            'control_python':artifact(Path(sys.executable).resolve()),
            'prior_failed_validation':artifact(host_path(PRIOR,execution)),
            'interruption_record':artifact(host_path(pins['interruption_record']['path'],execution)),
            'correction_lineage':artifact(host_path(pins['correction_lineage']['path'],execution)),
            'resume':{'status':'not_applicable','reason':'no_campaign_running'},
            'scope':'Separate correctness recovery; neither replaces nor certifies the frozen 150-attempt benchmark.'}
        try:
            save(RUN/'pipeline.json',journal)
            for number in (signal.SIGINT,signal.SIGTERM):signal.signal(number,interrupted)
            def guard_live():
                admission(execution,registry)
            def guard():
                guard_live()
                if sha(args.pins)!=args.pins_sha256:raise RuntimeError('Required candidate06 pins changed')
                if verify_pins(pins,execution,args.execution)!=source:raise RuntimeError('Source changed during validation')
            def run(name,command,limit,*,required=True):
                guard()
                actual=[execution['runtime_artifacts']['control_python']['path'],WRAPPER,
                        '--execution',args.execution,'--execution-sha256',pins['execution_sha256'],'--',*command]
                entry={'name':name,'argv':list(map(str,actual)),'started_at':stamp(),'timeout_seconds':limit}
                journal.update(status='running',phase=name);journal['steps'].append(entry);save(RUN/'pipeline.json',journal)
                env=dict(os.environ,PYTHONPATH=str(SOURCE/'src'),PYTHONDONTWRITEBYTECODE='1',
                    OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',TMPDIR=str(TEMPORARY))
                def on_started(pid):
                    entry['pid']=pid;save(RUN/'pipeline.json',journal)
                def on_finished(value):
                    entry.update(value,finished_at=stamp());save(RUN/'pipeline.json',journal)
                try:
                    with (RUN/(name+'.log')).open('w') as log:
                        entry['returncode']=supervise(actual,cwd=SOURCE,env=env,log=log,limit=limit,
                            guard_live=guard_live,on_started=on_started,on_finished=on_finished,registry=registry)
                except BaseException:
                    entry['status']='interrupted_timeout_or_supervision_failure';raise
                guard()
                entry['status']='passed' if entry['returncode']==0 else 'failed';save(RUN/'pipeline.json',journal)
                if required and entry['returncode']:raise RuntimeError(name+' failed; inspect the preserved log')
                return entry['returncode']==0
            guard()
            run('clone',['git','clone','--no-hardlinks','--no-checkout',paths['upstream_repository'],NATIVE_SOURCE],600)
            run('checkout',['git','-C',NATIVE_SOURCE,'checkout','--detach','7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'],600)
            run('build',['/usr/bin/taskset','-c',','.join(map(str,execution['build_cpus'])),PYTHON,SOURCE/'scripts/build_groops.py',
                '--source-dir',NATIVE_SOURCE,'--build-dir',BUILD,'--prefix',paths['prefix'],
                '--cmake-executable',paths['cmake'],'--numerics','--jobs','4'],7200)
            import shutil
            native_hash=sha(BUILD/'groops');native=BINARIES/('groops-'+native_hash[:16])
            if native.exists():raise RuntimeError('Refusing to overwrite a correctness candidate')
            shutil.copy2(BUILD/'groops',native)
            shutil.copy2(BUILD/'build-manifest.json',str(native)+'.build-manifest.json');native.chmod(0o555)
            if sha(native)!=native_hash or json.loads((BUILD/'build-manifest.json').read_text())['executable_sha256']!=native_hash:
                raise RuntimeError('Archived executable disagrees with its actual build')
            journal['native']={'path':str(native),'sha256':native_hash,'build_manifest_sha256':sha(str(native)+'.build-manifest.json')}
            save(RUN/'pipeline.json',journal)
            common=['/usr/bin/taskset','-c',str(execution['fit_cpu']),'env','ORBIT_POC_CORRECTNESS_NATIVE='+str(native),
                    'ORBIT_POC_V31_NATIVE='+str(native),'ORBIT_POC_GROOPS='+str(native)]
            run('native-tests',common+[PYTHON,'-m','pytest','-q','-s','-p','no:cacheprovider',
                '--basetemp='+str(RUN/'pytest-temp'),'--junitxml='+str(RUN/'native-tests.xml'),
                *ORIGINAL_TESTS,*pins['additional_native_tests']],3600)
            journal['native_test_inventory']=verify_native_junit(RUN/'native-tests.xml',106);save(RUN/'pipeline.json',journal)
            regression=pins['regression_suite']
            outcomes=[run('correction-regression-tests',common+[PYTHON,'-m','pytest','-q','-s','-p','no:cacheprovider',
                '--basetemp='+str(RUN/'regression-pytest-temp'),'--junitxml='+str(RUN/'correction-regression-tests.xml'),
                *regression['files']],3600,required=False)]
            try:
                journal['correction_regression_inventory']=verify_native_junit(RUN/'correction-regression-tests.xml',regression['expected_count'])
            except Exception as error:
                journal['correction_regression_inventory']={'status':'failed','error':type(error).__name__+': '+str(error)}
                outcomes.append(False)
            save(RUN/'pipeline.json',journal)
            for method in ('log_drag_ou','pulses'):
                name='synthetic-refinement-'+method
                outcomes.append(run(name,common+[PYTHON,SOURCE/'scripts/validate_numerics_synthetic_refinement.py',
                    '--request',OLD_CASES/(method+'-staged')/'request.json','--binary',native,'--output',RUN/name],7200,required=False))
            outcomes.append(run('flight-refinement',common+[PYTHON,SOURCE/'scripts/validate_numerics_flight_refinement.py',
                '--prepared',FLIGHT_PREPARED,'--binary',native,'--output',RUN/'flight-refinement'],7200,required=False))
            outcomes.append(run('eccentric-24h-refinement',common+[PYTHON,SOURCE/'scripts/validate_numerics_synthetic_refinement.py',
                '--request',FULL_DAY_REQUEST,'--binary',native,'--output',RUN/'eccentric-24h-refinement'],7200,required=False))
            for method in ('log_drag_ou','pulses'):
                name='objective-'+method
                outcomes.append(run(name,common+[PYTHON,SOURCE/'scripts/validate_numerics_objective.py',
                    '--request',OLD_CASES/(method+'-staged')/'request.json','--native-binary',native,
                    '--initial-state-from',INITIAL,'--output',RUN/name],7200,required=False))
            outcomes.append(run('nuisance-replay',common+[PYTHON,SOURCE/'scripts/validate_numerics_nuisance.py',
                '--source-profile',OLD_CASES/'log_drag_ou-staged/point-030-direction-0.015625-1-repeat/profile.xml',
                '--native',native,'--output',RUN/'nuisance-replay','--allow-floor-limited'],7500,required=False))
            outcomes.append(run('nuisance-replay-candidate1-point012',common+[PYTHON,SOURCE/'scripts/validate_numerics_nuisance.py',
                '--source-profile',NEW_REPLAY,'--native',native,'--output',RUN/'nuisance-replay-candidate1-point012',
                '--allow-floor-limited'],7500,required=False))
            if sha(native)!=native_hash:raise RuntimeError('Correctness executable changed during validation')
            guard();journal.update(status='passed' if all(outcomes) else 'failed',finished_at=stamp())
        except BaseException as error:
            caught=error;journal.update(status='failed',error=type(error).__name__+': '+str(error),finished_at=stamp())
        finally:
            with cleanup_signals():
                failures=[]
                for owned in registry:
                    try:owned.cleanup(force=owned.child.poll() is None)
                    except BaseException as error:failures.append(type(error).__name__+': '+str(error))
                journal['final_cleanup']={'verified':not failures,'errors':failures,'commands':[owned.last_cleanup for owned in registry]}
                if failures:caught=caught or RuntimeError('Owned recovery workload cleanup is unconfirmed')
                try:save(RUN/'pipeline.json',journal)
                except BaseException as error:
                    print('Final recovery journal write failed: '+repr(error),file=sys.stderr);caught=caught or error
        if caught:raise caught
        return 0 if journal['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(main())
