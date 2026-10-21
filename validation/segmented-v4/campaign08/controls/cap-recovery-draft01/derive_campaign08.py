#!/usr/bin/env python3
"""Derive fresh outer controls after an audited zero-fit setup failure.

The original sealed mount/allowlist/inner inputs remain byte-identical. Only
the pinned outer namespace wrapper and its separately built bubblewrap change.
This writes metadata; the existing controller still performs all live checks.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import socket

B = Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff')
OLD = B / 'fit-campaign-control-07'
NEW = B / 'fit-campaign-control-08'
BIN = B / 'bwrap-cap-01/binaries/bwrap-0.6.1-ubuntu0.3-maxargs16384'
WRAPPER = B / 'bwrap-cap-01/controls/with_segmented_fit_namespace02.py'
KEYS = {'schema', 'helper', 'original_assembly', 'original_capture',
        'failure_review', 'build_review', 'wrapper_review', 'wrapper',
        'bubblewrap', 'control'}
ORIGINAL_ASSEMBLY = 'ad6a3a51dc556bad83ca460bb5354ae6a3bed26b7bbed359d8388598650e180b'
ORIGINAL_CAPTURE = '20c14ed104f0a7e1dd3f270f29fd43ceb0e59922d9ccb3535d5a19abcf15dbc0'
FAILURE_REVIEW = 'ec5c3054379336adf322c775fe1a5db6324daeaf6ba10eeb172bbf621f6732e9'
OUTPUTS = ('invocation.json', 'host-plan.json', 'launch-pins.json',
           'host-view-plan.json', 'recovery.json', 'failure.json')


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            digest.update(block)
    return digest.hexdigest()


def pin(path):
    return {'path': str(path), 'sha256': sha(path)}


def checked(value):
    need(isinstance(value, dict) and set(value) == {'path', 'sha256'}, 'Exact pin required')
    path = Path(value['path'])
    need(path.is_absolute() and path.is_file() and sha(path) == value['sha256'], 'Pinned control changed: ' + str(path))
    return path


def read(value):
    return json.loads(checked(value).read_text())


def module(name, value):
    spec = importlib.util.spec_from_file_location(name, checked(value))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def write_new(path, value):
    with Path(path).open('x') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return pin(path)


def process_gone(identity):
    try:
        fields = (Path('/proc') / str(identity['pid']) / 'stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return True
    return int(fields[19]) != identity['start_ticks'] or fields[0] == 'Z'


def empty_writables(mount):
    rows = mount['writable_mounts']
    need(len(rows) == 3 and {row['kind'] for row in rows} == {'attempts', 'temporary', 'lock'}, 'Original writable set differs')
    for row in rows:
        path = Path(row['source'])
        stat = path.stat()
        need(not path.is_symlink() and (stat.st_dev, stat.st_ino) == (row['identity']['device'], row['identity']['inode']), 'Writable identity changed')
        if row['kind'] == 'lock':
            need(path.is_file() and stat.st_size == 0, 'Original statistical lock changed')
        else:
            need(path.is_dir() and not any(path.iterdir()), 'A fit or private output already exists')


def fresh_control(control):
    need(set(control) == {'path', 'device', 'inode'} and control['path'] == str(NEW), 'Fresh canonical control required')
    stat = NEW.stat()
    need(NEW.is_dir() and not NEW.is_symlink() and str(NEW.resolve()) == str(NEW) and (stat.st_dev, stat.st_ino) == (control['device'], control['inode']), 'Fresh control identity changed')
    need(all(not (NEW / name).exists() and not (NEW / name).is_symlink() for name in (*OUTPUTS, 'pipeline.json', 'campaign-launch.json', 'campaign-driver.log')), 'Preserve earlier recovery output')


def accepted_correction(request, build_review, wrapper_review):
    need(build_review['status'] == 'accepted_cap_only_control_build' and build_review['binary'] == request['bubblewrap'], 'Control build lacks exact independent acceptance')
    need(wrapper_review['status'] == 'accepted_exact_bubblewrap_pin_change' and wrapper_review['wrapper'] == request['wrapper'] and wrapper_review['bubblewrap'] == request['bubblewrap'], 'Wrapper lacks exact independent acceptance')


def derive(old_invocation, old_host, old_launch, old_view, wrapper, bubblewrap, control):
    """Return only the permitted coordinate-preserving outer metadata deltas."""
    need(old_host['control_root'] == old_launch['control_root'] == str(OLD), 'Wrong failed campaign')
    need(old_host['wrapper'] == old_invocation['wrapper'], 'Old invocation/wrapper differ')
    need(old_view['mount_plan'] == old_invocation['mount_plan'], 'Old mount attribution differs')
    need(old_invocation['resume_planner'] is None, 'No fit may be resumed or replaced')
    need(wrapper['path'] == str(WRAPPER) and bubblewrap['path'] == str(BIN), 'Unexpected corrected controls')
    need(control == str(NEW), 'Explicit fresh campaign08 required')
    invocation = copy.deepcopy(old_invocation)
    invocation.update(wrapper=wrapper, bubblewrap=bubblewrap)
    host = copy.deepcopy(old_host)
    host.update(control_root=control, wrapper=wrapper)
    launch = copy.deepcopy(old_launch)
    launch['control_root'] = control
    view = copy.deepcopy(old_view)
    return invocation, host, launch, view


def context(request):
    need(set(request) == KEYS and request['schema'] == 'orbit-poc-campaign08-cap-recovery-request-v1', 'Unknown recovery options')
    need(request['helper'] == pin(Path(__file__).resolve()), 'Recovery helper changed')
    need(request['original_assembly'] == {'path': str(OLD / 'assembly.json'), 'sha256': ORIGINAL_ASSEMBLY}, 'Original assembly differs')
    need(request['original_capture']['sha256'] == ORIGINAL_CAPTURE and request['failure_review']['sha256'] == FAILURE_REVIEW, 'Original terminal audit differs')
    assembly = read(request['original_assembly'])
    capture = read(request['original_capture'])
    audit = read(request['failure_review'])
    need(audit['status'] == 'verified_setup_failure_no_fits' and audit['cleanup_verified'] is True and audit['fit_attempts'] == 0 and audit['actual_inner_proof_passed'] is False, 'No audited zero-fit boundary')
    need(capture['status'] == 'controller_failed' and capture['fit_attempts'] == 0 and capture['attempts_empty'] and capture['temporary_empty'] and not capture['prelaunch_probe_present'], 'Wrong terminal capture')
    for row in capture['files']:
        checked({key: row[key] for key in ('path', 'sha256')})
    need(all(process_gone(row) for row in capture['owned_identities']), 'An original owned process remains live')
    old_host = read(assembly['artifacts']['host-plan.json'])
    old_launch = read(assembly['artifacts']['launch-pins.json'])
    old_view = read(assembly['artifacts']['host-view-plan.json'])
    old_invocation = read(old_host['invocation'])
    need(old_host['host'] == {'hostname': socket.gethostname(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}, 'Original host/boot changed')
    mount = read(old_invocation['mount_plan'])
    empty_writables(mount)
    fresh_control(request['control'])
    binary = checked(request['bubblewrap'])
    wrapper = checked(request['wrapper'])
    need(str(binary) == str(BIN) and str(wrapper) == str(WRAPPER), 'Unreviewed control paths')
    build_review = read(request['build_review'])
    wrapper_review = read(request['wrapper_review'])
    accepted_correction(request, build_review, wrapper_review)
    need(module('corrected_fit_wrapper', request['wrapper']).EXPECTED_BUBBLEWRAP == request['bubblewrap'], 'Wrapper fixed binary identity differs')
    host_module = module('unchanged_host_controller', old_host['helper'])
    need(host_module.load_plan(assembly['artifacts']['host-plan.json']['path'], assembly['artifacts']['host-plan.json']['sha256']) == old_host, 'Original host context differs')
    return assembly, capture, old_invocation, old_host, old_launch, old_view, host_module


def assemble(request):
    assembly, capture, old_invocation, old_host, old_launch, old_view, host_module = context(request)
    invocation, host, launch, view = derive(old_invocation, old_host, old_launch, old_view, request['wrapper'], request['bubblewrap'], str(NEW))
    artifacts = {}
    def save(name, value):
        result = write_new(NEW / name, value)
        artifacts[name] = result
        return result
    try:
        host['invocation'] = save('invocation.json', invocation)
        launch['plan'] = save('host-plan.json', host)
        need(host_module.load_plan(launch['plan']['path'], launch['plan']['sha256']) == host, 'Unchanged host rejected recovery')
        view['launch_pins'] = save('launch-pins.json', launch)
        view_pin = save('host-view-plan.json', view)
        module('unchanged_host_view', view['helper']).build(view)
        for row in capture['files']:
            checked({key: row[key] for key in ('path', 'sha256')})
        result = {'schema': 'orbit-poc-campaign08-cap-recovery-result-v1', 'status': 'assembled_metadata',
                  'request': request, 'artifacts': artifacts, 'manifest_hash': assembly['manifest_hash'],
                  'unchanged_mount_plan': old_invocation['mount_plan'], 'unchanged_original_invocation': old_host['invocation'],
                  'fit_attempts': 0, 'native_executions': 0, 'fit_execution_authorized': False,
                  'launch_command': ['/usr/bin/taskset', '-c', '32', host['control_python']['path'], '-B', view['helper']['path'], '--plan', view_pin['path'], '--sha256', view_pin['sha256']],
                  'scope': 'Outer control recovery only. All original scientific, mount, allowlist, inner controller, probe and fit-order inputs are unchanged. Original failed campaign07 is retained. Actual inner proof remains mandatory.'}
        save('recovery.json', result)
        return result
    except BaseException as error:
        write_new(NEW / 'failure.json', {'status': 'failed', 'error': repr(error), 'artifacts': artifacts, 'fit_attempts': 0, 'native_executions': 0})
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--request', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = assemble(read({'path': args.request, 'sha256': args.sha256}))
    print(json.dumps({key: result[key] for key in ('status', 'manifest_hash', 'fit_attempts', 'launch_command')}))


if __name__ == '__main__':
    main()
