#!/usr/bin/env python3
"""Freeze/run the unchanged eight corrected-reference gates in a private mount namespace.

Preparation hashes files and runs no native work. Run is a separate explicit
operation. Original scientific files and global canonical aliases are untouched.
"""
from __future__ import annotations
import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import time
from types import SimpleNamespace

B = Path('/mnt/d/orbit-v41-recovery01')
RECOVERY_ROOT = Path('/mnt/d/orbit-v41-recovery02')
PREVIOUS_OUTPUT = B / 'reference-gates10-run01'
PROTECTED = Path('/home/emper/orbit-v4.1')
SOURCE = B / 'candidate04/source'
PYTHON = Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python')
INVENTORY = PROTECTED / 'control/reference-input-inventory01.json'
CAPTURE = PROTECTED / 'control/reference-captured-mapping01.json'
BUILD = B / 'candidate04/build-result04.json'
SPOOL_PROBE = RECOVERY_ROOT / 'validation-controls07/stdio-probe/result.json'
# Resource admission guard, not a certified worst-case scratch bound.
SCRATCH_REQUIRED_BYTES = 4 * 1024**3
REFERENCE = Path('/mnt/d/orbit-segmented-v4/validation-02-packet/control/corrected-terminal10-independent-audit.json')
PREFIXES = (Path('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013'),
            Path('/mnt/seagate10tb/orbit-comparison-v3-20261013-florianpfaff'))
STAGES = ('synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses', 'flight-refinement',
          'eccentric-24h-refinement', 'objective-log_drag_ou', 'objective-pulses',
          'nuisance-replay', 'nuisance-replay-candidate1-point012')
NATIVE_ENV = {'ORBIT_POC_NUISANCE_CONDITIONAL_QR': '1', 'ORBIT_POC_NUISANCE_FIXED_DYNAMICS': '1', 'ORBIT_POC_GNSS_DESIGN_STORAGE': 'disk',
              'ORBIT_POC_GNSS_DESIGN_BLOCK_EPOCHS': '64', 'ORBIT_POC_NUISANCE_PERFORMANCE': '1',
              'ORBIT_POC_NUISANCE_INTERPOLATION_CACHE': '1', 'ORBIT_POC_NUISANCE_COST_ONLY_DESIGN': '1',
              'ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY': '1', 'ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS': '64'}
THREADS = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS',
           'BLIS_NUM_THREADS', 'GOTO_NUM_THREADS')


def read(path):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('Duplicate JSON key: ' + key)
            out[key] = value
        return out
    return json.loads(Path(path).read_text(), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + x)))


def sha(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def pin(path):
    path = Path(path).absolute()
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def verify(item):
    if sha(item['path']) != item['sha256']:
        raise ValueError('Frozen bytes changed: ' + item['path'])


def save(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def api():
    sys.path.insert(0, str(SOURCE / 'src'))
    from orbit_poc.segmented import validation, multiday
    return validation, multiday


def target_path(raw):
    path = Path(raw)
    if (not path.is_absolute() or '..' in path.parts or str(path) != raw
            or not any(path.is_relative_to(prefix) and path != prefix for prefix in PREFIXES)):
        raise ValueError('Unauthorized private alias: ' + raw)
    return path


def aliases(inventory, historical, capture):
    """Content-address lookup is restricted to independently inventoried bytes."""
    by_hash = {}
    for item in inventory['dependencies']:
        local = item.get('local_content') or {}
        if local.get('available') and local.get('sha256') == item['expected_sha256']:
            by_hash.setdefault(local['sha256'], local['path'])
    for item in capture['files']:
        by_hash.setdefault(item['sha256'], item['local_path'])
    wanted = dict((item['path'], item['sha256']) for item in historical['dependencies'])
    if len(wanted) != len(historical['dependencies']):
        raise ValueError('Duplicate dependency path')
    directories = set()
    for tree in historical['data_directories']:
        root = Path(tree['root'])
        if root.exists():
            continue
        target_path(str(root)); directories.add(str(root))
        for entry in tree['entries']:
            path = root / entry['relative']
            target_path(str(path))
            if entry['kind'] == 'directory':
                directories.add(str(path))
            elif entry['kind'] == 'file':
                old = wanted.setdefault(str(path), entry['sha256'])
                if old != entry['sha256']:
                    raise ValueError('Conflicting scientific data hash: ' + str(path))
            else:
                raise ValueError('Unsupported historical private alias kind')
    result = []
    checked = {}
    for raw, digest in sorted(wanted.items()):
        path = Path(raw)
        if path.exists() or path.is_symlink():
            if sha(path) != digest:
                raise ValueError('Existing canonical input differs: ' + raw)
            continue
        target_path(raw)
        if digest not in by_hash:
            raise ValueError('No exact verified local bytes: ' + raw)
        local = Path(by_hash[digest]).resolve(strict=True)
        if not local.is_file():
            raise ValueError('Alias source is not regular')
        if local not in checked:
            checked[local] = pin(local)
        if checked[local]['sha256'] != digest:
            raise ValueError('Captured or local input changed: ' + str(local))
        result.append({'target': raw, 'source': checked[local]})
        directories.add(str(path.parent))
    return result, sorted(directories, key=lambda x: (len(Path(x).parts), x))


def overlay_mount_identity(raw):
    """Freeze destination resolution without changing historical input paths.

    Bubblewrap cannot mount through a symlink destination ancestor on this
    host. Mount the mirror on the existing resolved directory instead; the
    historical spelling continues to access that exact read-only mirror.
    Do not create or repair links in the host filesystem.
    """
    path = Path(raw)
    if not path.is_absolute() or '..' in path.parts or str(path) != raw:
        raise ValueError('Unsafe historical overlay target')
    links = []
    for item in reversed((path, *path.parents)):
        if item.is_symlink():
            links.append({'path': str(item), 'target': str(item.readlink())})
    if path.exists():
        if not path.is_dir():
            raise ValueError('Existing historical overlay target is not a directory')
        destination = path.resolve(strict=True)
    else:
        if links or path.resolve() != path:
            raise ValueError('Unresolved historical overlay path or symlink')
        destination = path
    return {'path': str(destination), 'symlink_ancestors': links}


def verified_overlay_mount(row):
    identity = overlay_mount_identity(row['target'])
    if row.get('mount_identity') != identity:
        raise ValueError('Historical overlay destination resolution changed')
    return identity['path']


def reconstruct_data(output, historical, inventory, capture):
    """Restore exact historical directory/file semantics without editing hosts."""
    _, multiday = api()
    by_hash = {}
    for row in inventory['dependencies']:
        local = row.get('local_content') or {}
        if local.get('available') and local.get('sha256') == row['expected_sha256']:
            by_hash.setdefault(local['sha256'], local['path'])
    for row in capture['files']:
        by_hash.setdefault(row['sha256'], row['local_path'])
    overlays = []
    for index, historical_tree in enumerate(historical['data_directories']):
        source = Path(output) / 'mirrors' / ('tree' + str(index))
        source.mkdir(parents=True)
        observed = set()
        for entry in historical_tree['entries']:
            relative = Path(entry['relative'])
            if (relative.is_absolute() or '..' in relative.parts or not relative.parts
                    or str(relative) != entry['relative'] or str(relative) in observed):
                raise ValueError('Unsafe or duplicate historical native member')
            observed.add(str(relative))
            # The prescribed three inventories contain no links. Refuse any
            # future linked inventory instead of silently changing its semantics.
            if entry.get('link_target') is not None:
                raise ValueError('Historical linked data semantics need explicit support')
            target = source / relative
            if entry['kind'] == 'directory':
                target.mkdir(parents=True, exist_ok=True)
            elif entry['kind'] == 'file':
                canonical = Path(historical_tree['root']) / relative
                local = canonical if canonical.is_file() else Path(by_hash[entry['sha256']])
                if sha(local) != entry['sha256']:
                    raise ValueError('Historical native member bytes differ: ' + str(canonical))
                target.parent.mkdir(parents=True, exist_ok=True)
                with local.open('rb') as origin, target.open('xb') as destination:
                    shutil.copyfileobj(origin, destination, 1024 * 1024)
                if sha(target) != entry['sha256']:
                    raise ValueError('Copied native member bytes differ')
            else:
                raise ValueError('Unsupported historical native member kind')
        actual = multiday.native_data_inventory(source)
        def semantic(tree):
            return [{key: row.get(key) for key in ('relative', 'kind', 'link_target', 'bytes', 'sha256')}
                    for row in tree['entries']]
        if semantic(actual) != semantic(historical_tree):
            raise ValueError('Reconstructed native membership or file semantics differ')
        inventory_path = Path(output) / 'mirrors' / ('tree' + str(index) + '.inventory.json')
        save(inventory_path, actual)
        overlays.append({'target': historical_tree['root'], 'source': str(source), 'inventory': pin(inventory_path),
                         'exact_historical_semantics': True, 'historical_symlink_members': 0,
                         'mount_identity': overlay_mount_identity(historical_tree['root'])})
    return overlays


def namespace(plan, writable, argv):
    """Mount inputs read-only; only a designated new child output is writable."""
    writable = Path(writable).absolute()
    output = Path(plan['output'])
    if not writable.is_relative_to(output) or writable.resolve() != writable or not writable.is_dir():
        raise ValueError('Namespace writable directory escapes fresh output')
    tmp = writable / 'tmp'
    if tmp.resolve() != tmp or not tmp.is_dir():
        raise ValueError('Namespace scratch directory is missing or indirect')
    args = ['/usr/bin/bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid',
            '--ro-bind', '/', '/', '--tmpfs', '/mnt', '--ro-bind', '/mnt/c', '/mnt/c',
            '--ro-bind', '/mnt/d', '/mnt/d', '--tmpfs', '/home',
            '--ro-bind', '/home/emper', '/home/emper', '--proc', '/proc', '--dev', '/dev',
            ] + storage_api().binds(plan['storage'], writable)
    # All added alias destinations live below the two empty private roots.
    parents = set()
    for raw in plan['alias_directories']:
        p = target_path(raw)
        while str(p) not in ('/mnt', '/home'):
            parents.add(str(p)); p = p.parent
    for raw in sorted(parents, key=lambda x: (len(Path(x).parts), x)):
        args += ['--dir', raw]
    seen = set()
    for row in plan['aliases']:
        target_path(row['target'])
        if row['target'] in seen:
            raise ValueError('Duplicate namespace alias')
        seen.add(row['target'])
        args += ['--ro-bind', row['source']['path'], row['target']]
    expected_roots = [row['root'] for row in plan.get('historical_inputs', {}).get('data_directories', [])]
    overlays = plan.get('directory_overlays', [])
    if overlays and [row['target'] for row in overlays] != expected_roots:
        raise ValueError('Native directory overlay differs from exact historical roots')
    if 'objective_outputs' in plan:
        args += objective_output_api().binds(plan, writable, overlay_mount_identity)
    for row in overlays:
        args += ['--ro-bind', row['source'], verified_overlay_mount(row)]
    return args + ['--remount-ro', '/mnt', '--remount-ro', '/home',
                   '--chdir', str(SOURCE), '--'] + list(argv)


def base_env():
    return {'PATH': '/usr/bin:/bin', 'HOME': '/home/emper', 'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONPATH': str(SOURCE / 'src'),
            'LD_LIBRARY_PATH': '/home/emper/orbit-nuisance-warmstarts/toolchain-01/lib',
            **{key: '1' for key in THREADS}, **NATIVE_ENV}


def containing_mount(mounts, path):
    path = Path(path)
    by_id = {row['id']: row for row in mounts}
    def depth(row):
        visited = set()
        while row is not None:
            if row['id'] in visited:
                raise ValueError('Cyclic mount ancestry')
            visited.add(row['id'])
            row = by_id.get(row['parent'])
        return len(visited)
    eligible = [row for row in mounts if path.is_relative_to(Path(row['path']))]
    if not eligible:
        raise ValueError('Missing kernel mount for ' + str(path))
    # A mounted-on mount remains listed; the overmount has the same path and
    # its covered mount as ancestor. Select the deepest actual mount in a tie.
    return max(eligible, key=lambda row: (len(Path(row['path']).parts), depth(row)))


def readonly_mounts(plan):
    """Verify actual kernel mount flags; no attempted writes to input files."""
    def unescape(raw):
        for source, target in (('\\040', ' '), ('\\011', '\t'), ('\\012', '\n'), ('\\134', '\\')):
            raw = raw.replace(source, target)
        return raw
    mounts = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        mounts.append({'id': int(fields[0]), 'parent': int(fields[1]),
                       'path': unescape(fields[4]), 'options': fields[5].split(','),
                       'filesystem_type': fields[fields.index('-') + 1]})
    def containing(raw):
        return containing_mount(mounts, Path(raw).resolve(strict=True))
    originals = [row['path'] for row in plan['historical_inputs']['dependencies']]
    originals += [row['path'] for row in plan['historical_inputs']['input_artifacts'].values()]
    originals += [row['root'] for row in plan['historical_inputs']['data_directories']]
    originals += [row['target'] for row in plan['aliases']]
    originals += [str(SOURCE), plan['runtime']['native']['path'], plan['runner']['path'], '/home', '/mnt']
    selected = {}
    for raw in originals:
        mount = containing(raw)
        if 'ro' not in mount['options']:
            raise ValueError('Original input mount writable: ' + raw)
        selected[mount['path']] = mount
    writable = []
    for key in ('TMPDIR', 'ORBIT_POC_GNSS_DESIGN_SCRATCH', 'ORBIT_POC_NUMERICS_SPOOL_DIRECTORY'):
        if not os.environ.get(key):
            raise ValueError('Explicit temporary directory missing: ' + key)
        path = Path(os.environ[key]).resolve(strict=True)
        if not path.is_relative_to(Path(plan['output'])):
            raise ValueError('Temporary directory escapes new output: ' + key)
        mount = containing(path)
        if 'rw' not in mount['options']:
            raise ValueError('Fresh output temporary directory is not writable: ' + key)
        if key == 'ORBIT_POC_NUMERICS_SPOOL_DIRECTORY':
            if mount['filesystem_type'] in ('tmpfs', 'ramfs'):
                raise ValueError('QR spool must remain on the pinned D filesystem')
        else:
            if mount['filesystem_type'] != 'tmpfs':
                raise ValueError('Design/TMPDIR scratch must use owned tmpfs')
            storage_api().child_identity(plan['storage'], path)
        writable.append({'environment_key': key, 'directory': str(path), 'mount': mount})
    return {'checked_original_paths': len(originals), 'readonly_mounts': list(selected.values()),
            'writable_scratch_mount': writable,
            'private_objective_output': objective_output_api().proof(plan, Path(os.environ['TMPDIR']).parent.name, containing) if 'objective_outputs' in plan else {'active': False},
            'proof': 'Longest containing resolved-path kernel mount, deepest mount ancestry for overmounts; no write probes'}


def validate_data_membership(actual, historical):
    """Allow current aliases only for the exact original data role and bytes."""
    expected = {tree['root']: {entry['relative']: entry['sha256'] for entry in tree['entries'] if 'sha256' in entry}
                for tree in historical['data_directories']}
    dependencies = {}
    for row in historical['dependencies']:
        if '/data/' in row['path']:
            relative = row['path'].split('/data/', 1)[1]
            dependencies.setdefault(relative, set()).add(row['sha256'])
    for tree in actual:
        if tree['root'] not in expected:
            raise ValueError('Unexpected native data root')
        observed = set()
        for entry in tree['entries']:
            if 'sha256' not in entry:
                continue
            relative = entry['relative']; observed.add(relative)
            wanted = expected[tree['root']].get(relative)
            allowed = {wanted} if wanted is not None else dependencies.get(relative, set())
            if entry['sha256'] not in allowed:
                raise ValueError('Unapproved glob-visible input role or bytes: ' + tree['root'] + '/' + relative)
        if set(expected[tree['root']]) - observed:
            raise ValueError('Original native data membership missing')


def planned_stage_env(root):
    return {**base_env(), 'TMPDIR': str(Path(root) / 'tmp'),
            'ORBIT_POC_GNSS_DESIGN_SCRATCH': str(Path(root) / 'scratch'),
            'ORBIT_POC_NUMERICS_SPOOL_DIRECTORY': str(Path(root) / 'row-spool')}


def storage_api():
    import importlib.util
    path = Path(__file__).with_name('reference_storage09.py')
    spec = importlib.util.spec_from_file_location('reference_storage09', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def runtime_api():
    import importlib.util
    path = Path(__file__).with_name('reference_runtime09.py')
    spec = importlib.util.spec_from_file_location('reference_runtime09', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def recovery_api():
    import importlib.util
    path = Path(__file__).with_name('reference_recovery.py')
    spec = importlib.util.spec_from_file_location('reference_recovery', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def objective_output_api():
    import importlib.util
    path = Path(__file__).with_name('reference_objective_output.py')
    spec = importlib.util.spec_from_file_location('reference_objective_output', path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    return module


def checked_plan(path, expected):
    path = Path(path)
    if not isinstance(expected, str) or len(expected) != 64 or sha(path) != expected:
        raise ValueError('Plan hash differs')
    plan = read(path)
    if (plan['schema'] != 'orbit-poc-v41-reference-gates-plan-v7-composition07' or plan['stages'] != list(STAGES)
            or plan['environment'] != base_env() or plan['cpu'] != 4
            or plan['controller_limits'] != {'readonly_inventory_preflight_seconds': 1800}
            or plan['limits'] != {'process_tree_rss_bytes': 8 * 1024**3, 'min_free_disk_bytes': 16 * 1024**3}
            or plan['runner']['path'] != str(Path(__file__).absolute())):
        raise ValueError('Frozen reference-gate protocol differs')
    for item in plan['pins']:
        verify(item)
    verify(plan['storage_manifest'])
    if plan['storage'] != read(plan['storage_manifest']['path']) or plan['scratch_required_bytes'] != SCRATCH_REQUIRED_BYTES:
        raise ValueError('Frozen scratch ownership or capacity policy changed')
    if plan['storage']['output'] != plan['output'] or list(plan['storage']['stages']) != sorted(('prepared', *STAGES)):
        raise ValueError('Scratch stage inventory differs')
    verify(plan['runner'])
    verify(plan['python_runtime'])
    runtime_api().verify(read(plan['python_runtime']['path']), base_env())
    for item in plan['aliases']:
        target_path(item['target']); verify(item['source'])
    if [job['stage'] for job in plan['jobs']] != list(STAGES):
        raise ValueError('Stage inventory differs')
    validation, _ = api()
    _, multiday = api()
    if [row['target'] for row in plan['directory_overlays']] != [row['root'] for row in plan['historical_inputs']['data_directories']]:
        raise ValueError('Reconstructed data root inventory differs')
    for row in plan['directory_overlays']:
        verified_overlay_mount(row)
        verify(row['inventory'])
        if multiday.native_data_inventory(row['source']) != read(row['inventory']['path']):
            raise ValueError('Reconstructed native data membership or bytes changed')
    objective_output_api().verify(plan, overlay_mount_identity)
    for job in plan['jobs']:
        duration = 7500 if job['stage'].startswith('nuisance-replay') else 7200
        if (job['timeout_seconds'] != duration or job['environment'] != planned_stage_env(job['directory'])
                or job['argv'] != validation.command(job['stage'], plan['historical_inputs'], plan['runtime'], job['directory'])):
            raise ValueError('Original gate command, deadline, or environment changed')
    if sha(path) != expected:
        raise ValueError('Plan hash changed during verification')
    return plan


def verified_inputs(plan, *, new=False):
    validation, multiday = api()
    historical = plan['historical_inputs']
    destination = Path(plan['output']) / 'prepared' / 'validation-inputs.json'
    if new:
        actual = [multiday.native_data_inventory(item['root']) for item in historical['data_directories']]
        validate_data_membership(actual, historical)
        value = {**historical, 'source_reference': plan['corrected_source_freeze'], 'data_directories': actual}
        save(destination, value)
    config = SimpleNamespace(validation_inputs=pin(destination), corrected_reference=plan['corrected_reference'])
    value = validation.verify_inputs(config, {'runtimes': {'segmented': plan['runtime']}}, SOURCE)
    return value, pin(destination)


def validate_build(build):
    execution = build.get('execution') or {}
    required = ('inputs_and_originals_unchanged', 'boot_unchanged', 'dependencies_unchanged',
                'source_snapshot_unchanged', 'tools_unchanged')
    if (execution.get('status') != 'complete' or execution.get('returncode') != 0
            or any(build.get(key) is not True for key in required)
            or not cleanup_verified(execution)):
        raise ValueError('No verified candidate04 build with complete identity and kernel_ECHILD cleanup')


def prepare(output):
    output = Path(output).absolute()
    if output.exists() or output.is_symlink() or output.parent.resolve() != output.parent or output.parent != RECOVERY_ROOT:
        raise ValueError('Choose a new output directory directly below recovery02')
    current_admission = admission()
    inventory, capture, build = read(INVENTORY), read(CAPTURE), read(BUILD)
    historical = read(inventory['source_authority']['historical_validation_inputs']['path'])
    validate_build(build)
    runtime = {'source_root': str(SOURCE), 'native': build['native'], 'python': pin(PYTHON)}
    sidecar = pin(str(Path(runtime['native']['path'])) + '.build-manifest.json')
    if sidecar['sha256'] != build['build_manifest']['sha256']:
        raise ValueError('Adjacent native build manifest differs')
    mounts, directories = aliases(inventory, historical, capture)
    authority = inventory['source_authority']
    pins = [pin(x) for x in (INVENTORY, CAPTURE, BUILD, REFERENCE, Path(__file__), Path(__file__).with_name('reference_runtime09.py'), '/usr/bin/bwrap', '/usr/bin/taskset', '/usr/bin/sha256sum', SPOOL_PROBE, Path(__file__).with_name('reference_storage09.py'), Path(__file__).with_name('reference_recovery.py'), Path(__file__).with_name('reference_objective_output.py'), B / 'candidate04/source-snapshot.json', B / 'build-review04/build-audit04.json', PREVIOUS_OUTPUT / 'freeze.json', PREVIOUS_OUTPUT / 'plan.json', RECOVERY_ROOT / 'interruption-audit/interruption.json')]
    pins += [runtime['native'], runtime['python'], sidecar, build['build_manifest'], build['build_plan'], *build['libraries']]
    pins += [authority['historical_validation_inputs'], authority['corrected_source_freeze']]
    pins += list(inventory['protected_sources'].values()) + list(inventory['python_source_inputs'].values()) + list(inventory['runtime_helpers'].values())
    probe = read(SPOOL_PROBE)
    if (probe.get('passed') is not True or probe.get('source_unchanged') is not True
            or probe.get('scratch_empty_after_close') is not True
            or probe['boot_id'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip()
            or probe['source']['sha256'] != sha(SOURCE / 'groops/extension/scaledRowQr.h')):
        raise ValueError('Exact stdio row-spool filesystem probe has not passed')
    pins += [probe['probe'], probe['source']]
    for item in pins:
        verify(item)
    validation, _ = api()
    if tuple(validation.GATE1[2:]) != STAGES:
        raise ValueError('Original gate order differs')
    jobs = [{'stage': stage, 'directory': str(output / stage),
             'timeout_seconds': 7500 if stage.startswith('nuisance-replay') else 7200,
             'argv': validation.command(stage, historical, runtime, output / stage),
             'environment': planned_stage_env(output / stage)} for stage in STAGES]
    plan = {'schema': 'orbit-poc-v41-reference-gates-plan-v7-composition07', 'output': str(output), 'runtime': runtime,
            'runner': pin(Path(__file__)), 'pins': pins, 'aliases': mounts, 'alias_directories': directories,
            'historical_inputs': historical, 'corrected_source_freeze': authority['corrected_source_freeze'],
            'corrected_reference': pin(REFERENCE), 'stages': list(STAGES), 'jobs': jobs, 'cpu': 4,
            'environment': base_env(), 'controller_limits': {'readonly_inventory_preflight_seconds': 1800}, 'limits': {'process_tree_rss_bytes': 8 * 1024**3, 'min_free_disk_bytes': 16 * 1024**3},
            'scope': 'Original eight downstream gates only; native test audit and full fits remain separate; no release/covariance authority.',
            'recovery': {'previous_output': str(PREVIOUS_OUTPUT), 'previous_results_reused': False,
                         'fresh_complete_stage_inventory': True, 'preparation_admission': current_admission},
            'created_at': datetime.datetime.now(datetime.timezone.utc).isoformat()}
    output.mkdir()
    storage = storage_api().create(output, STAGES)
    save(output / 'storage.json', storage)
    plan['storage'] = storage
    plan['storage_manifest'] = pin(output / 'storage.json')
    plan['scratch_required_bytes'] = SCRATCH_REQUIRED_BYTES
    storage_api().capacity(storage, 'prepared', SCRATCH_REQUIRED_BYTES)
    runtime_inventory = runtime_api().collect(SOURCE, base_env())
    save(output / 'python-runtime.json', runtime_inventory)
    plan['python_runtime'] = pin(output / 'python-runtime.json')
    plan['directory_overlays'] = reconstruct_data(output, historical, inventory, capture)
    for name in ('prepared', *STAGES):
        for leaf in ('tmp', 'scratch', 'row-spool'):
            (output / name / leaf).mkdir(parents=True, mode=0o700)
    plan['objective_outputs'] = objective_output_api().create(output, overlay_mount_identity(str(objective_output_api().TARGET)))
    save(output / 'plan.json', plan)
    checked_plan(output / 'plan.json', sha(output / 'plan.json'))
    return output / 'plan.json'


def preflight(path):
    started = time.monotonic()
    admission()
    original_plan = pin(path)
    plan = checked_plan(path, original_plan['sha256'])
    output = Path(plan['output']) / 'prepared'
    # Read-only Python inside the namespace hashes and applies unchanged parsers.
    args = namespace(plan, output, [plan['runtime']['python']['path'], '-s', '-B', str(Path(__file__).absolute()),
                                   '_freeze_inputs', '--plan', str(path), '--sha256', original_plan['sha256']])
    command = ['/usr/bin/taskset', '-c', '4', *args]
    env = planned_stage_env(output)
    save(output / 'preflight-command.json', {'argv': command, 'environment': env, 'plan': original_plan})
    with (output / 'preflight.log').open('x') as stream:
        result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=plan['controller_limits']['readonly_inventory_preflight_seconds'])
    save(output / 'preflight-execution.json', {'returncode': result.returncode, 'native_launched': False,
         'controller_inventory_elapsed_seconds': time.monotonic()-started,
         'readonly_namespace_timeout_seconds': plan['controller_limits']['readonly_inventory_preflight_seconds'],
         'scientific_deadlines_changed': False})
    if result.returncode:
        raise ValueError('Read-only private namespace preflight failed')
    checked_plan(path, original_plan['sha256'])
    for row in plan['aliases']:
        if Path(row['target']).exists() or Path(row['target']).is_symlink():
            raise ValueError('Unexpected host-global alias created: ' + row['target'])
    save(output / 'host-alias-check.json', {'all_private_aliases_absent_on_host': True, 'paths': [r['target'] for r in plan['aliases']]})
    save(Path(plan['output']) / 'freeze.json', {'plan': original_plan, 'validation_inputs': pin(output / 'validation-inputs.json'),
         'preflight': pin(output / 'preflight-result.json'), 'native_launched': False, 'launch_authority': False})


def admission():
    rows = []
    for path in Path('/proc').glob('[0-9]*'):
        try:
            name = (path / 'comm').read_text().strip()
            if name.startswith(('groops', 'segmented-qr', 'segmented_qr')) or name in ('cc1plus', 'cc1', 'f951', 'ninja', 'c++', 'g++', 'gcc'):
                rows.append({'pid': int(path.name), 'name': name})
        except (FileNotFoundError, ProcessLookupError):
            pass
    if rows:
        raise RuntimeError('Competing native workload; preserve it: ' + str(rows))
    return recovery_api().admission(cpu=4)


def stage_worker(path, expected, stage):
    started = time.monotonic()
    plan = checked_plan(path, expected)
    mount_proof = readonly_mounts(plan)
    inputs, input_pin = verified_inputs(plan)
    freeze = read(Path(plan['output']) / 'freeze.json')
    if input_pin != freeze['validation_inputs'] or freeze['plan'] != pin(path):
        raise ValueError('Fresh frozen dependency closure changed')
    job = next(j for j in plan['jobs'] if j['stage'] == stage)
    if any(os.environ.get(k) != v for k, v in job['environment'].items()):
        raise ValueError('Stage environment differs')
    before_native = time.monotonic()
    result = subprocess.run(job['argv'], cwd=SOURCE, env=job['environment'], check=False)
    after_native = time.monotonic()
    validation, _ = api()
    record = {'stage': stage, 'argv': job['argv'], 'returncode': result.returncode, 'status': 'failed',
              'covariance_authority': False, 'full_fit_verified': False, 'release_authority': False,
              'mount_proof': mount_proof, 'controller_before_scientific_seconds': before_native-started,
              'scientific_command_seconds': after_native-before_native}
    try:
        checked_plan(path, expected)
        verified_inputs(plan)
        verify(freeze['validation_inputs'])
        if result.returncode != 0:
            raise ValueError('Original validation command failed')
        record['evidence'] = validation.check_result(stage, job['directory'], inputs,
                                 {'runtimes': {'segmented': plan['runtime']}}, read(plan['corrected_reference']['path']))
        checked_plan(path, expected)
        verify(freeze['validation_inputs'])
        record['status'] = 'passed'
    except Exception as exc:
        record['error'] = repr(exc)
    record['controller_after_scientific_seconds'] = time.monotonic()-after_native
    record['worker_total_seconds'] = time.monotonic()-started
    record['controller_inventory_included_in_stage_limit'] = True
    save(Path(job['directory']) / 'strict-result.json', record)
    return 0 if record['status'] == 'passed' else 1


def checked_freeze(path, expected):
    """Return only the original frozen plan, after complete byte verification."""
    if not isinstance(expected, str) or len(expected) != 64 or sha(path) != expected:
        raise ValueError('Explicit freeze hash differs')
    freeze = read(path)
    for name in ('plan', 'validation_inputs', 'preflight'):
        verify(freeze[name])
    plan = checked_plan(freeze['plan']['path'], freeze['plan']['sha256'])
    # Detect modification while checking the nested dependency closure.
    for name in ('plan', 'validation_inputs', 'preflight'):
        verify(freeze[name])
    if sha(path) != expected:
        raise ValueError('Explicit freeze changed during validation')
    return freeze, plan


def cleanup_verified(result):
    cleanup = result.get('cleanup') or {}
    return (result.get('owned_process_group_cleaned') is True
            and cleanup.get('verified') is True
            and cleanup.get('empty_tree_certificate') == 'kernel_ECHILD'
            and cleanup.get('remaining') == [])


def run(path, expected):
    run_started = time.monotonic()
    frozen_artifact = pin(path)
    freeze, plan = checked_freeze(path, expected)
    if frozen_artifact['sha256'] != expected:
        raise ValueError('Initial freeze differs')
    plan_path = Path(freeze['plan']['path'])
    plan_hash = freeze['plan']['sha256']
    output = Path(plan['output'])
    if sha(sys.executable) != plan['runtime']['python']['sha256']:
        raise ValueError('Executing Python differs')
    for job in plan['jobs']:
        directory = Path(job['directory'])
        expected_leaves = {'tmp', 'scratch', 'row-spool'}
        if job['stage'] in objective_output_api().STAGES:
            expected_leaves.add(objective_output_api().LEAF)
        if set(p.name for p in directory.iterdir()) != expected_leaves:
            raise ValueError('Preserve prior stage evidence: ' + str(directory))
        if any(any((directory / leaf).iterdir()) for leaf in expected_leaves):
            raise ValueError('Stage scratch was already used')
    lock = (output / 'run.lock').open('x')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    sys.path.insert(0, str(SOURCE / 'src'))
    from orbit_poc.segmented.supervisor import run_owned
    results = []
    error = None
    try:
        save(output / 'run-started.json', {'freeze': frozen_artifact, 'plan': freeze['plan'], 'admission': admission()})
        for job in plan['jobs']:
            stage_started = time.monotonic()
            checked_freeze(path, expected)
            root = Path(job['directory'])
            save(root / 'admission.json', {**admission(), 'scratch': storage_api().capacity(plan['storage'], job['stage'], plan['scratch_required_bytes'])})
            args = namespace(plan, root, [plan['runtime']['python']['path'], '-s', '-B', str(Path(__file__).absolute()),
                                         '_stage', '--plan', str(plan_path), '--sha256', plan_hash, '--stage', job['stage']])
            launched_at = time.monotonic()
            result = run_owned(['/usr/bin/taskset', '-c', '4', *args], python_executable=plan['runtime']['python']['path'],
                       cwd=SOURCE, env=job['environment'], log_path=root / 'stage.log', receipt_path=root / 'supervisor.json',
                       timeout_seconds=job['timeout_seconds'], max_process_tree_rss_bytes=plan['limits']['process_tree_rss_bytes'],
                       min_free_disk_bytes=plan['limits']['min_free_disk_bytes'], working_directory=root)
            completed_at = time.monotonic()
            cleanup = cleanup_verified(result)
            record = {'stage': job['stage'], 'status': 'failed', 'execution': pin(root / 'supervisor.json'),
                      'cleanup_verified': cleanup, 'freeze': frozen_artifact, 'plan': freeze['plan'],
                      'input_identity_after': 'not_verified',
                      'controller_before_launch_seconds': launched_at-stage_started,
                      'supervised_stage_wall_seconds': completed_at-launched_at}
            results.append(record)
            try:
                checked_freeze(path, expected)
                record['input_identity_after'] = 'verified'
            except Exception as exc:
                record['input_identity_after'] = 'changed'
                record['identity_error'] = repr(exc)
                raise
            passed = result['status'] == 'complete' and result['returncode'] == 0 and cleanup
            record['status'] = 'passed' if passed else 'failed' if result['status'] == 'complete' else result['status']
            strict = root / 'strict-result.json'
            if strict.is_file():
                record['strict_result'] = pin(strict)
                evidence = read(strict)
                if (evidence.get('status') != 'passed' or evidence.get('stage') != job['stage']
                        or evidence.get('argv') != job['argv'] or evidence.get('returncode') != 0):
                    record['status'] = 'failed'
            elif passed:
                record['status'] = 'failed'
                record['error'] = 'Missing strict output parser evidence'
            record['controller_after_stage_seconds'] = time.monotonic()-completed_at
            record['end_to_end_stage_seconds'] = time.monotonic()-stage_started
            if not cleanup:
                record['status'] = 'failed'
                raise RuntimeError('Missing verified kernel_ECHILD cleanup proof; subsequent launch prohibited')
            if result['status'] == 'interrupted':
                raise RuntimeError('Interrupted stage; subsequent launch prohibited')
        checked_freeze(path, expected)
    except BaseException as exc:
        error = repr(exc)
    finally:
        done = {row['stage']: row for row in results}
        passed = error is None and len(results) == len(STAGES) and all(r['status'] == 'passed' for r in results)
        save(output / 'result.json', {'planned_stages': list(STAGES), 'error': error,
             'freeze': frozen_artifact, 'plan': freeze['plan'], 'all_eight_strict_passed': passed,
             'end_to_end_run_seconds': time.monotonic()-run_started,
             'runtime_inventory_costs_included': True,
             'stages': [done.get(stage, {'stage': stage, 'status': 'not_executed_or_interrupted_without_receipt'}) for stage in STAGES],
             'release_authority': False, 'accepted_covariance': False, 'whole_fit_verified': False})
        lock.close()
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=('prepare', 'preflight', 'run', '_freeze_inputs', '_stage'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument('--freeze', type=Path)
    parser.add_argument('--sha256')
    parser.add_argument('--stage', choices=STAGES)
    args = parser.parse_args()
    if args.operation == 'prepare':
        if args.output is None: parser.error('--output required')
        print(prepare(args.output))
    elif args.operation == 'preflight':
        if args.plan is None: parser.error('--plan required')
        preflight(args.plan)
    elif args.operation == 'run':
        if args.freeze is None or args.sha256 is None: parser.error('--freeze and --sha256 required')
        return run(args.freeze, args.sha256)
    elif args.operation == '_freeze_inputs':
        if args.plan is None or args.sha256 is None: parser.error('--plan and --sha256 required')
        plan = checked_plan(args.plan, args.sha256)
        mount_proof = readonly_mounts(plan)
        value, artifact = verified_inputs(plan, new=True)
        checked_plan(args.plan, args.sha256)
        save(Path(plan['output']) / 'prepared/preflight-result.json', {'status': 'verified', 'validation_inputs': artifact,
             'original_inputs': len(value['input_artifacts']), 'protected_scripts': 15,
             'dependencies': len(value['dependencies']), 'native_data_roots': len(value['data_directories']),
             'all_inputs_read_only_by_mount': True, 'native_launched': False, 'mount_proof': mount_proof})
    else:
        if args.plan is None or args.sha256 is None or args.stage is None: parser.error('stage arguments missing')
        return stage_worker(args.plan, args.sha256, args.stage)
    return 0


if __name__ == '__main__':
    sys.exit(main())
