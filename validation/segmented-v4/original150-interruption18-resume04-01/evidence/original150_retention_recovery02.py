"""Explicit original150 post-fit recovery; no numerical runtime substitution.

The parent-only hook preserves legacy output bytes instead of running the newer
terminal compactor on an unrelated legacy receipt. Numerical child interpreters,
their source, requests, binaries, resource limits and result validation are unchanged.
"""
from pathlib import Path
import argparse, hashlib, json, os, sys

SCHEMA = 'orbit-poc-original150-retention-recovery-plan-v2'
ERROR = 'ValueError: Terminal retention receipt belongs to another policy or profile'


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def pin(path):
    return {'path': str(Path(path).absolute()), 'sha256': sha(path)}


def checked(item):
    need(set(item) == {'path', 'sha256'}, 'Unexpected artifact fields')
    path = Path(item['path'])
    need(path.is_absolute() and path.is_file() and sha(path) == item['sha256'], 'Artifact changed: ' + str(path))
    return path


def read(item):
    return json.loads(checked(item).read_text())


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def append_exact(path, value):
    """Finish only this identical explicit recovery transaction after interruption."""
    path = Path(path)
    raw = encoded(value)
    need(not path.is_symlink(), 'Recovery destination is a symlink')
    if path.exists():
        need(path.is_file() and path.read_bytes() == raw, 'Existing recovery output differs')
        return
    # A unique temporary is not used: incomplete writes are preserved and reject.
    with path.open('xb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def artifact(role, path, **metadata):
    return {'role': role, **pin(path), 'metadata': metadata}


def process_identity(pid):
    try:
        values = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return int(values[19]), values[0]
    except FileNotFoundError:
        return None


def check_plan(plan_path, digest):
    need(sha(plan_path) == digest, 'Recovery plan changed')
    plan = json.loads(Path(plan_path).read_text())
    need(set(plan) == {'schema', 'helper_sha256', 'source_root', 'source_sha256', 'config', 'manifest',
                     'retention_module', 'boot_id', 'stopped_processes', 'existing_checkpoints', 'failure',
                     'prepared_at', 'campaign_adapter_receipt'}, 'Unknown recovery plan field')
    need(plan['schema'] == SCHEMA and plan['helper_sha256'] == sha(__file__), 'Recovery helper/schema differs')
    need(plan['boot_id'] == Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'Recovery host boot changed')
    for row in plan['stopped_processes']:
        need(set(row) == {'pid', 'start_ticks'}, 'Invalid stopped identity')
        actual = process_identity(row['pid'])
        need(actual is None or actual[0] != row['start_ticks'], 'Previously owned process still exists')
    need(len(plan['stopped_processes']) >= 3, 'Controller/supervisor/worker absence required')
    for name in ('config', 'manifest', 'retention_module'):
        checked(plan[name])
    return plan


def inspect_failure(plan, protocol, config, project, *, allow_later_checkpoints=False):
    """Read-only proof and proposed terminal record; public frozen validators run."""
    need(protocol.source_snapshot(project)['sha256'] == plan['source_sha256'], 'Frozen source differs')
    root = protocol._root(config, None, project)
    need(pin(root / 'manifest.json') == plan['manifest'], 'Manifest artifact differs')
    manifest = protocol.verify_manifest(config, root, project)
    f = plan['failure']
    need(set(f) == {'attempt_id', 'controller', 'supervision', 'worker_result', 'retention', 'request',
                   'worker_request', 'resource_guard', 'worker_log', 'native_runtime'}, 'Unknown failure evidence')
    rows = plan['existing_checkpoints']
    need(len(rows) == 5 and len(manifest['attempts']) == 150, 'Exact five-checkpoint recovery boundary required')
    cases = {c['case_id']: c for c in manifest['cases']}
    for row, attempt in zip(rows, manifest['attempts']):
        need(set(row) == {'attempt_id', 'record', 'result'} and row['attempt_id'] == attempt['attempt_id'], 'Prior checkpoint order differs')
        directory = root / 'attempts' / attempt['attempt_id']
        need(pin(directory / 'result-record.json') == row['record'] and pin(directory / 'result.json') == row['result'], 'Prior checkpoint changed')
        protocol.verify_checkpoint(directory, protocol.attempt_job(config, manifest, cases[attempt['case_id']], attempt))
    attempt = manifest['attempts'][5]
    need(attempt['attempt_id'] == f['attempt_id'] and attempt['profile'] == 'legacy_v3', 'Exact sixth legacy attempt required')
    directory = root / 'attempts' / attempt['attempt_id']
    need(directory.is_dir() and not directory.is_symlink(), 'Attempt directory differs')
    for later in manifest['attempts'][6:]:
        d = root / 'attempts' / later['attempt_id']
        if allow_later_checkpoints and (d / 'result-record.json').exists():
            need(d.is_dir() and not d.is_symlink(), 'Later checkpoint directory differs')
            protocol.verify_checkpoint(d, protocol.attempt_job(config, manifest, cases[later['case_id']], later))
        else:
            need(not d.exists() or (d.is_dir() and not d.is_symlink() and not any(d.iterdir())), 'Later attempt already has uncheckpointed evidence')
    case = cases[attempt['case_id']]
    job = protocol.attempt_job(config, manifest, case, attempt)
    for name, filename in (('request', 'request.json'), ('worker_request', 'worker-request.json'),
                           ('worker_result', 'worker-result.json'), ('retention', 'retention.json'),
                           ('resource_guard', 'resource-guard.json'), ('worker_log', 'worker.log'),
                           ('native_runtime', 'native_runtime.json')):
        need(pin(directory / filename) == f[name], 'Failure evidence location/bytes differ: ' + name)
    need(read(f['request']) == job and read(f['worker_request']) == job, 'Original request identity differs')
    controller, supervision = read(f['controller']), read(f['supervision'])
    need(controller.get('status') == 'failed' and controller.get('error') == ERROR and controller.get('run') is None,
         'Not the observed post-fit retention failure')
    need(controller.get('configuration') == plan['config'] and controller.get('exit_code') == 1 and controller.get('phase') == 'finished', 'Controller attribution differs')
    need('compact_attempt(directory, result, attempt["profile"])' in controller.get('traceback', '') and
         'Terminal retention receipt belongs to another policy or profile' in controller['traceback'], 'Failure stack differs')
    cleanup = supervision.get('cleanup', {})
    need(supervision.get('status') == 'failed' and supervision.get('returncode') == 1 and supervision.get('signals') == [] and
         cleanup.get('verified') is True and cleanup.get('remaining') == [] and cleanup.get('hard_kill') is False,
         'Original supervisor cleanup not established')
    raw = read(f['worker_result']); runtime = manifest['legacy_runtime']
    need(raw.get('status') == 'complete' and raw.get('native_binary_sha256') == runtime['native']['sha256'], 'Raw worker attribution differs')
    need(set(read(f['retention'])) == {'cartesian_marginals', 'deleted_outputs', 'retain_native_diagnostics', 'superseded_iterations'}, 'Not the observed legacy receipt shape')
    for item in raw.get('artifacts', []):
        protocol.verify_artifact(item)
    need(any(item.get('role') == 'retention_audit' and item['path'] == f['retention']['path'] and item['sha256'] == f['retention']['sha256'] for item in raw['artifacts']), 'Worker retention attribution differs')
    native = read(f['native_runtime'])
    need(native.get('execution') and all(x.get('native_binary_sha256') == runtime['native']['sha256'] for x in native['execution']), 'Native execution ledger differs')
    recovery = {'schema': 'orbit-poc-original150-postfit-failure-recovery-v1', 'prepared_at': plan['prepared_at'],
                'attempt_id': attempt['attempt_id'], 'request_hash': protocol.canonical_hash(job),
                'manifest_hash': manifest['manifest_hash'], 'helper': pin(__file__), 'failure_evidence': f,
                'configuration': plan['config'], 'source_sha256': plan['source_sha256'],
                'outcome': 'failed', 'failure_scope': 'parent_controller_terminal_retention',
                'raw_worker_status': raw['status'], 'numerical_rerun': False, 'covariance_authorized': False,
                'measurements': 'Parent harness wall time, peak process-tree RSS, returncode and minima were lost before checkpoint. They remain null; raw worker timings are diagnostic only.',
                'preservation': 'All existing checkpoints, request, worker output, legacy retention and native outputs remain unchanged.'}
    receipt = directory / 'controller-retention-recovery.json'
    recovery_pin = {'path': str(receipt), 'sha256': hashlib.sha256(encoded(recovery)).hexdigest()}
    result = {'status': 'failed', 'converged': False, 'covariance_valid': False,
              'error': 'Controller terminal retention failed after a raw complete legacy worker result; parent harness measurements unavailable. No retry.',
              'failure_scope': 'parent_controller_terminal_retention', 'raw_worker_status': raw['status'],
              'request_hash': protocol.canonical_hash(job), 'numerics_profile': attempt['profile'],
              'numerics_manifest_hash': manifest['manifest_hash'], 'input_manifest_hash': case['input_manifest_hash'],
              'harness_execution': {'runtime': runtime, 'elapsed_seconds': None, 'peak_process_tree_rss_bytes': None,
                                    'returncode': None, 'minimum_free_output_bytes': None, 'minimum_free_physical_backing_bytes': None,
                                    'measurement': recovery['measurements'], 'log': f['worker_log'],
                                    'outer_supervisor_cleanup': f['supervision'], 'recovery': recovery_pin},
              'artifacts': [dict(role='controller_failure_recovery', **recovery_pin, metadata={'accepted_covariance': False})] +
                           [dict(role='raw_' + name, **value, metadata={'diagnostic_only': True, 'accepted_covariance': False})
                            for name, value in f.items() if name != 'attempt_id']}
    result_path = directory / 'result.json'
    index = {'attempt_id': attempt['attempt_id'], 'case_id': case['case_id'], 'profile': attempt['profile'],
             'status': 'failed', 'request_hash': protocol.canonical_hash(job),
             'result': {'path': str(result_path), 'sha256': hashlib.sha256(encoded(result)).hexdigest()}}
    return directory, recovery, result, index


def record_failure(plan, protocol, config, project):
    root = protocol._root(config, None, project)
    with protocol.exclusive(root):
        directory, recovery, result, index = inspect_failure(plan, protocol, config, project)
        # Preflight all destinations before adding any part of this transaction.
        for name, value in (('controller-retention-recovery.json', recovery), ('result.json', result), ('result-record.json', index)):
            path = directory / name
            need(not path.is_symlink() and (not path.exists() or (path.is_file() and path.read_bytes() == encoded(value))), 'Existing recovery destination differs')
        for name, value in (('controller-retention-recovery.json', recovery), ('result.json', result), ('result-record.json', index)):
            append_exact(directory / name, value)
        return {'status': 'recorded_controller_failure', 'attempt_id': index['attempt_id'], 'result': pin(directory / 'result.json'), 'numerical_rerun': False}


def verify_campaign_recovery(plan, protocol, config, project):
    """Bind continuation to the reviewed recovery, not just rehashed result flags."""
    directory, recovery, result, index = inspect_failure(plan, protocol, config, project, allow_later_checkpoints=True)
    for name, value in (('controller-retention-recovery.json', recovery), ('result.json', result), ('result-record.json', index)):
        path = directory / name
        need(path.is_file() and not path.is_symlink() and path.read_bytes() == encoded(value), 'Reviewed recovery checkpoint differs: ' + name)
    manifest = protocol.read_json(checked(plan['manifest']))
    attempt = manifest['attempts'][5]; cases = {c['case_id']: c for c in manifest['cases']}
    protocol.verify_checkpoint(directory, protocol.attempt_job(config, manifest, cases[attempt['case_id']], attempt))
    return {'status': 'verified_reviewed_recovery', 'first_five_unchanged': True,
            'sixth_recovery': pin(directory / 'controller-retention-recovery.json'), 'sixth_result': pin(directory / 'result.json')}


def install_retention_adapter(module, protocol, config, manifest, project, plan_identity):
    original = module.compact_attempt
    root = protocol._root(config, None, project)
    attempts = {x['attempt_id']: x for x in manifest['attempts']}
    cases = {x['case_id']: x for x in manifest['cases']}

    def adapted(directory, result, profile):
        if profile != 'legacy_v3':
            return original(directory, result, profile)
        directory = Path(directory)
        need(directory.parent == root / 'attempts' and not directory.is_symlink(), 'Legacy terminal directory differs')
        attempt = attempts[directory.name]
        need(attempt['profile'] == profile, 'Legacy terminal profile differs')
        job = protocol.attempt_job(config, manifest, cases[attempt['case_id']], attempt)
        need(protocol.read_json(directory / 'request.json') == job and result.get('request_hash') == protocol.canonical_hash(job), 'Legacy terminal job differs')
        need(result.get('numerics_manifest_hash') == manifest['manifest_hash'] and result.get('numerics_profile') == profile and result.get('harness_execution', {}).get('runtime') == manifest['legacy_runtime'], 'Legacy terminal runtime/manifest differs')
        for item in result.get('artifacts', []):
            protocol.verify_artifact(item)
        old = directory / 'retention.json'
        need(not old.is_symlink(), 'Legacy retention symlink rejected')
        preserved = pin(old) if old.exists() else None
        receipt = directory / 'legacy-terminal-preservation.json'
        need(not receipt.exists() and not receipt.is_symlink(), 'Preserve prior terminal adapter receipt')
        value = {'schema': 'orbit-poc-original150-legacy-terminal-preservation-v1', 'policy': 'preserve_all_legacy_outputs',
                 'attempt_id': attempt['attempt_id'], 'request_hash': protocol.canonical_hash(job),
                 'manifest_hash': manifest['manifest_hash'], 'terminal_status': result['status'],
                 'legacy_retention': preserved, 'control_plan': plan_identity, 'helper': pin(__file__),
                 'removed': [], 'removed_bytes': 0, 'archived_runtime_modified': False,
                 'scope': 'Parent-only post-fit compaction bypass. Archived worker retention and all its outputs preserved. Numerical children and new-profile compaction unchanged.'}
        append_exact(receipt, value)
        need(preserved is None or pin(old) == preserved, 'Legacy receipt changed')
        result.setdefault('artifacts', []).append(artifact('legacy_terminal_preservation', receipt, numerical_changes=False))
        return result

    module.compact_attempt = adapted
    return original


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument('--plan', type=Path, required=True); ap.add_argument('--sha256', required=True)
    ap.add_argument('--mode', choices=('inspect', 'record-failure', 'campaign'), required=True); ap.add_argument('--startup-receipt', type=Path)
    args = ap.parse_args(argv); plan = check_plan(args.plan, args.sha256)
    sys.path.insert(0, str(Path(plan['source_root']) / 'src'))
    from orbit_poc.numerics import protocol, retention, campaign
    from orbit_poc.numerics.config import load_config
    config = load_config(checked(plan['config'])); project = Path(plan['source_root'])
    need(pin(retention.__file__) == plan['retention_module'], 'Loaded compactor differs')
    need(protocol.source_snapshot(project)['sha256'] == plan['source_sha256'], 'Loaded frozen source differs')
    if args.mode == 'inspect':
        _, recovery, result, index = inspect_failure(plan, protocol, config, project)
        print(json.dumps({'status': 'reviewable', 'recovery': recovery, 'proposed_result': result, 'proposed_index': index}, indent=2)); return 0
    if args.mode == 'record-failure':
        print(json.dumps(record_failure(plan, protocol, config, project), indent=2)); return 0
    need(args.startup_receipt is not None, 'Pinned runtime startup receipt required')
    root = protocol._root(config, None, project); manifest = protocol.verify_manifest(config, root, project)
    prerequisite = verify_campaign_recovery(plan, protocol, config, project)
    receipt = Path(plan['campaign_adapter_receipt'])
    need(receipt.is_absolute() and not receipt.exists() and not receipt.is_symlink(), 'Fresh adapter campaign receipt required')
    append_exact(receipt, {'schema': 'orbit-poc-original150-parent-retention-adapter-v1', 'plan': pin(args.plan), 'helper': pin(__file__),
                          'retention_module': plan['retention_module'], 'source_sha256': plan['source_sha256'],
                          'reviewed_recovery': prerequisite,
                          'scope': 'Only parent terminal compaction for legacy_v3 changes; every numerical worker, frozen job, source and executable remains unchanged.',
                          'startup_receipt': pin(args.startup_receipt)})
    install_retention_adapter(retention, protocol, config, manifest, project, pin(args.plan))
    result = campaign.run_to_report(checked(plan['config']), args.startup_receipt, project=project)
    print(json.dumps(result, indent=2)); return result['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
