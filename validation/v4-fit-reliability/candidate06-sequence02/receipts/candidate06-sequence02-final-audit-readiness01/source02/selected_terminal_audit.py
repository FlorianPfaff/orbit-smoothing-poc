"""DRAFT, UNTESTED, NOT EXECUTED: selected-artifact audit, never release authority.

Run only after the entire sequence is terminal and the parent grants a serial
audit slot. This module imports only stdlib and never imports project controls,
executes a command, propagates an orbit, changes a result, or resumes a job.
It deliberately does not implement an independent SVD or a complete review of
the scientific gate computations. Its output always has approved=False.
"""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import math
import re
import struct
import sys
import xml.etree.ElementTree as ET

BASE = Path('/mnt/d/orbit-v41-recovery02')
SEQ = BASE / 'density-trial-sequence02'
GATES = BASE / 'candidate06-correctness02'
COLD = BASE / 'candidate06-cold02'
SEQ_SHA = '0d886a5f236ba5a1b734b5395d142e663e13c3b7fa2693044072c0822ff05d67'
GATE_PLAN_SHA = 'eb9f2a088b30cf631ab1437666e5f69cf23935f8e9fabbd355ef3254169c63f3'
COLD_PLAN_SHA = '39b2e76b51a3c9fdb296f39bd2aedcdd8fd1860fa658d52fc632bd7088c0094a'
NATIVE_SHA = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
SOURCE_SHA = '3c9174b52e0b894ffee58f0f4a28bb5e633e5861b377da0a587eac9eb8f2b702'
NOMINAL_SHA = '16bb3d709b50d6918c0ee2dbb6d419f17f17e934c04f39d607c77abcf73f3db1'
FIXED = {
    str(SEQ/'plan.json'): SEQ_SHA,
    str(SEQ/'sequence.py'): '1c323f5385ddaad5dbecbcce1fabc21c789068524c3af4072d886bd084f2b96f',
    str(GATES/'plan.json'): GATE_PLAN_SHA,
    str(GATES/'freeze.json'): '4868b8e5458c3e310bae43ae03d033f3fff4b4b7462bc92ef82dd454b92b92a2',
    str(COLD/'plan.json'): COLD_PLAN_SHA,
    str(COLD/'freeze.json'): '630a55edeb657d85e7cc1ce94630a09fc1128c5c4e6a45fd90c33242f550e83a',
    str(BASE/'candidate06-correctness02-review01/launch-review01.json'): 'bee25c37232d1dc11e59feae8fe0793ed1bd706edd165e4b82104c1572dbd2b7',
    str(BASE/'candidate06-cold02-review01/cold-launch-review01.json'): 'c110d869825abd386e3f782083c81eabfc27a08ae0bd45146f82ffe4167e8199',
    '/mnt/d/orbit-v41-density-trial-candidate06/source-snapshot.json': '24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739',
}
STAGES = (
    'native-tests', 'native-fail-fast-tests', 'correction-tests',
    'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
    'flight-refinement', 'eccentric-24h-refinement',
    'objective-log_drag_ou', 'objective-pulses',
    'nuisance-replay', 'nuisance-replay-candidate1-point012',
)
COUNTS = {'native-tests': 106, 'native-fail-fast-tests': 37, 'correction-tests': 51}
COLD_STAGES = ('cold-pulses', 'cold-density')
ORIGINAL_REQUESTS = {
    'cold-pulses': '9de707ae51e5031a5b13f1d02ab5ec5a67e996195840de6c5c7e81457a74c9f5',
    'cold-density': '2189944cfb519b5ca0730e6e02ee9cb809145a0845f66846931a8fb199694dfd',
}
OUTSTANDING = [
    'Independent SVD of the exact undamped original-coordinate R, with the unchanged deficient/unresolved thresholds; this draft checks recorded rank only.',
    'Exact frozen test-name inventories and all semantic fixture assertions, beyond JUnit counts/status and the strict receipt identities.',
    'Recompute all four refinement metrics and both objective/prior derivatives from raw scientific artifacts; verify two consecutive density scales and empirical resolution.',
    'Independently verify both nuisance-replay physical case identities and full strict nuisance histories, including the distinct original inputs.',
    'Full-grid Cartesian and prediction-epoch covariance reconstruction requires all exact tangent designs; this draft reconstructs dynamic covariance and the available initial design only.',
    'Independent NPZ arrays, prediction_mjd, prediction_covariance, symmetry and positive-definiteness checks; this draft hashes the NPZ but does not parse it.',
    'Review all nonlinear trial rollback/support/weights and recovered failed-native invocation receipts; selected saved final artifacts cannot prove the whole execution path.',
    'Review complete initialization/provenance chain, namespaces, owned-process limits and all preserved prior attempts; terminal receipts alone are not a fresh admission audit.',
    'Review interpretation of covariance discrepancy and direct/QR objective differences using existing policies; the draft reports them without inventing new tolerances.',
]


class Pending(Exception):
    pass


UNLAUNCHED_STATUS = 'not_executed_or_interrupted_without_receipt'


def require_attempt_receipt(row):
    """Classify the recorded outcome before dereferencing optional receipt pins."""
    if row is None:
        raise Pending('Planned attempt has no recorded outcome')
    status = row.get('status')
    if status == UNLAUNCHED_STATUS:
        raise Pending('Recorded not executed or interrupted without receipt; execution is unverified')
    if status in ('failed', 'timeout', 'interrupted', 'memory_limit', 'resource_limit'):
        raise ValueError('Recorded unsuccessful attempt: '+status)
    require(status == 'passed', 'Unknown or malformed claimed attempt status: '+repr(status))


def native_full_factor(diag, n):
    # Native schema vocabulary is "full". The separate Python certificate uses
    # "full_rank" and cannot substitute for this exact native diagnostic schema.
    require(diag['schema'] == 'orbit-poc-native-qr-v1' and diag['lambda'] == 0 and diag['rank_status'] == 'full' and diag['rank'] == diag['retained_parameters'] == n, 'Final native factor is damped or not recorded full rank')


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def pin_shape(pin):
    require(isinstance(pin, dict), 'Artifact pin is not an object')
    require(isinstance(pin.get('path'), str) and Path(pin['path']).is_absolute(), 'Artifact pin must have an absolute path')
    require(isinstance(pin.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', pin['sha256']), 'Artifact pin has no exact SHA256')
    return pin


def same_pin(left, right):
    return all(left.get(k) == right.get(k) for k in ('path', 'sha256'))


def finite(values):
    require(all(math.isfinite(x) for x in values), 'Nonfinite numerical artifact')
    return values


class Reader:
    def __init__(self, manifest):
        require(manifest.get('schema') == 'candidate06-terminal-selected-inputs-v1', 'Wrong terminal input manifest')
        require(manifest.get('sequence_plan_sha256') == SEQ_SHA, 'Wrong sequence input identity')
        self.manifest = manifest
        self.pins = {}
        self.consumed = {}
        for item in manifest['files']:
            pin_shape(item)
            require(item['path'] not in self.pins, 'Duplicate manifest path')
            self.pins[item['path']] = item
        for path, digest in FIXED.items():
            old = self.pins.get(path)
            require(old is None or old['sha256'] == digest, 'Manifest changes a fixed input')
            self.pins[path] = {'path': path, 'sha256': digest}

    def verify(self, pin):
        pin_shape(pin)
        path = Path(pin['path'])
        if not path.is_file():
            raise Pending('Missing pinned artifact: ' + str(path))
        digest = sha(path)
        require(digest == pin['sha256'], 'Artifact hash differs: ' + str(path))
        if 'bytes' in pin:
            require(type(pin['bytes']) is int and path.stat().st_size == pin['bytes'], 'Artifact size differs: ' + str(path))
        prior = self.consumed.get(str(path))
        require(prior is None or prior['sha256'] == digest, 'Artifact changed during audit')
        self.consumed[str(path)] = {'path': str(path), 'sha256': digest, 'bytes': path.stat().st_size}
        return path

    def explicit(self, path):
        path = str(path)
        if path not in self.pins:
            raise Pending('No explicit terminal hash for: ' + path)
        return self.verify(self.pins[path])

    def read(self, pin_or_path):
        path = self.verify(pin_or_path) if isinstance(pin_or_path, dict) else self.explicit(pin_or_path)
        return json.loads(path.read_text())

    def nested_pins(self, value):
        """Hash pin-shaped evidence only; never invent a hash from file presence."""
        found = []
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value:
                found.append(str(self.verify(value)))
            else:
                for item in value.values():
                    found.extend(self.nested_pins(item))
        elif isinstance(value, list):
            for item in value:
                found.extend(self.nested_pins(item))
        return found


def matrix(path):
    text = Path(path).read_text().splitlines()
    require(len(text) >= 2 and text[0].startswith('groops matrix version='), 'Unsupported matrix text')
    shape = re.fullmatch(r'Matrix\(\s*(\d+)\s+x\s+(\d+)\s*\)', text[1].strip())
    require(shape is not None, 'Missing exact matrix dimensions')
    n, m = map(int, shape.groups())
    rows = [finite([float(x) for x in line.split()]) for line in text[2:] if line.strip()]
    require(len(rows) == n and all(len(row) == m for row in rows), 'Matrix shape differs')
    return rows


def binary_matrix(path):
    data = Path(path).read_bytes()
    require(len(data) >= 16, 'Truncated QR binary')
    n, m = struct.unpack('<QQ', data[:16])
    require(n > 0 and m > 0 and len(data) == 16 + 8*n*m, 'QR binary size differs')
    values = finite(struct.unpack('<' + 'd'*(n*m), data[16:]))
    return [list(values[i*m:(i+1)*m]) for i in range(n)]


def orbit_text(path):
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt') as stream:
        lines = [line.strip() for line in stream if line.strip() and not line.lstrip().startswith('#')]
    require(len(lines) >= 4 and lines[0].startswith('groops instrument version='), 'Unsupported orbit text')
    require(lines[1].split() == ['-6', '1'], 'Expected exactly one orbit arc')
    count = int(lines[2])
    rows = [finite([float(x) for x in row.split()]) for row in lines[3:]]
    require(len(rows) == count and all(len(row) == 10 for row in rows), 'Orbit dimension differs')
    require(all(rows[i][0] < rows[i+1][0] for i in range(len(rows)-1)), 'Non-increasing orbit epochs')
    return rows


def triangular(R, b, transpose=False):
    n = len(R)
    require(len(b) == n and all(len(row) == n for row in R), 'Triangular solve dimensions differ')
    x = [0.0] * n
    for i in (range(n) if transpose else range(n-1, -1, -1)):
        require(R[i][i] != 0.0, 'Zero triangular pivot; no ridge or fallback permitted')
        terms = (R[j][i]*x[j] for j in range(i)) if transpose else (R[i][j]*x[j] for j in range(i+1, n))
        x[i] = (b[i] - math.fsum(terms))/R[i][i]
    return finite(x)


def dot(a, b):
    require(len(a) == len(b), 'Dot-product dimensions differ')
    return math.fsum(x*y for x, y in zip(a, b))


def supervisor_ok(supervisor):
    require(supervisor.get('status') == 'complete' and supervisor.get('returncode') == 0, 'Supervisor did not complete successfully')
    require(supervisor.get('owned_process_group_cleaned') is True, 'No owned cleanup confirmation')
    clean = supervisor.get('cleanup', {})
    require(clean.get('verified') is True and clean.get('empty_tree_certificate') == 'kernel_ECHILD' and clean.get('remaining') == [], 'No exact empty-tree certificate')
    require(not supervisor.get('signals_received'), 'Supervisor received a signal')


def terminal_identity(reader):
    plan = reader.read(SEQ/'plan.json')
    require(plan['gate_stages'] == list(STAGES) and plan['cold_stages'] == list(COLD_STAGES), 'Sequence inventory differs')
    for key in ('driver', 'gate_controller', 'gate_runner', 'cold_controller', 'cold_contracts', 'candidate_snapshot', 'gate_freeze', 'cold_freeze', 'source_review', 'gate_review', 'cold_review', 'python'):
        reader.verify(plan[key])
    for item in plan['helper_pins']:
        reader.verify(item)
    launch = reader.read(SEQ/'launch.json')
    result = reader.read(SEQ/'result.json')
    require(launch['plan_sha256'] == SEQ_SHA and result['plan_sha256'] == SEQ_SHA, 'Terminal sequence attribution differs')
    require(launch['pid'] == 86724 and launch['start_ticks'] == 2037467 and launch['boot_id'] == plan['boot_id'], 'Unexpected sequence launch identity')
    require(result.get('status') in ('complete', 'failed', 'interrupted'), 'No terminal sequence status')
    current_boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    proc = Path('/proc')/str(launch['pid'])/'stat'
    if current_boot == launch['boot_id'] and proc.exists():
        fields = proc.read_text().rsplit(')', 1)[1].split()
        if int(fields[19]) == launch['start_ticks']:
            raise Pending('Original sequence identity still exists; no concurrent audit allowed')
    require(result['release_authority'] is False and result['old_results_reused'] is False, 'Terminal authority/reuse declaration differs')
    return {'plan': plan, 'terminal': result}


def gate_stage(reader, job, aggregate_row, plan_pin, freeze_pin):
    stage = job['stage']
    require_attempt_receipt(aggregate_row)
    require(aggregate_row['stage'] == stage, 'Gate outcome order differs')
    require(all(key in aggregate_row for key in ('plan', 'freeze', 'execution', 'strict_result')), 'Claimed passed gate lacks required receipt fields')
    require(same_pin(aggregate_row['plan'], plan_pin) and same_pin(aggregate_row['freeze'], freeze_pin), 'Gate stage attribution differs')
    supervisor = reader.read(aggregate_row['execution'])
    strict = reader.read(aggregate_row['strict_result'])
    record = {'stage': stage, 'recorded_status': aggregate_row.get('status'), 'strict_status': strict.get('status')}
    reader.nested_pins(strict.get('evidence', {}))
    require(job['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY'] == ('0' if stage == 'native-tests' else '1'), 'Fail-fast stage mode differs')
    require(strict['stage'] == stage and strict['argv'] == job['argv'], 'Scientific stage argv differs')
    require(aggregate_row['status'] == 'passed' and aggregate_row['cleanup_verified'] is True and aggregate_row['input_identity_after'] == 'verified', 'Gate did not pass')
    supervisor_ok(supervisor)
    require(strict['status'] == 'passed' and strict['returncode'] == 0, 'Strict gate did not pass')
    if stage in COUNTS:
        evidence = strict['evidence']
        require(evidence['tests'] == COUNTS[stage], 'Wrong recorded test count')
        xml = ET.parse(reader.verify(evidence['junit'])).getroot()
        cases = list(xml.iter('testcase'))
        require(len(cases) == COUNTS[stage], 'Wrong actual JUnit test count')
        require(not any(list(case.iter(tag)) for case in cases for tag in ('failure', 'error', 'skipped')), 'JUnit failure/error/skip retained')
        require(len({(x.get('classname'), x.get('name')) for x in cases}) == len(cases), 'Duplicate JUnit case identity')
        record['junit_count'] = len(cases)
    else:
        evidence = strict['evidence']
        if isinstance(evidence.get('result'), dict):
            nested = reader.read(evidence['result'])
            record['nested_result_keys'] = sorted(nested)
            record['nested_pin_paths'] = reader.nested_pins(nested)
            # Scientific semantics and raw recomputation remain explicit full-review items.
    return record


def cold_selected(reader, stage, job, aggregate_row):
    root = COLD/stage
    fit = root/'fit'
    require(job['stage'] == stage and job['directory'] == str(root), 'Cold job identity differs')
    require(job['original_request']['sha256'] == ORIGINAL_REQUESTS[stage], 'Original cold request differs')
    reader.verify(job['original_request'])
    request = reader.read(job['request'])
    strict = reader.read(aggregate_row['strict_result'])
    supervisor = reader.read(aggregate_row['supervisor'])
    require(aggregate_row['stage'] == stage and aggregate_row['status'] == 'passed', 'Cold fit did not pass')
    supervisor_ok(supervisor)
    require(strict.get('status') == 'passed' and strict.get('stage') == stage and strict.get('whole_fit_verified') is True and strict.get('accepted_covariance') is True, 'Strict cold fit has no accepted covariance')
    require(strict['cold_start'] is True and strict['initial_state_override'] is False and strict['nuisance_donor'] is False, 'Cold initialization flags differ')
    reader.nested_pins(strict['evidence'])
    raw = reader.read(root/'backend-result.json')
    require(raw.get('status') == 'complete' and raw.get('numerical_status') == 'complete' and raw.get('converged') is True and raw.get('covariance_valid') is True, 'Backend has no strict complete covariance')
    for key in ('method', 'force_model_hash', 'measurement_model_hash', 'source_hash', 'preprocessing_hash', 'mask_hash'):
        require(raw.get(key) == request[key], 'Result/request differs: '+key)
    require(raw['source_hash'] == SOURCE_SHA and raw['native_binary_sha256'] == NATIVE_SHA and request['expected_native_binary_sha256'] == NATIVE_SHA, 'Wrong source or native executable')
    require(raw['runtime']['source_hash'] == SOURCE_SHA and raw['covariance_scope'] == 'marginalized', 'Runtime/covariance scope differs')
    require(raw['confirmation_checks'] and raw['confirmation_checks'][-1]['stationary'] is True, 'Missing strict optimizer confirmation')
    artifacts = raw['artifacts']
    for item in artifacts:
        require(Path(item['path']).is_relative_to(fit), 'Foreign cold artifact path')
        reader.verify(item)
    def artifact(role):
        matches = [a for a in artifacts if a['role'] == role]
        require(len(matches) == 1, 'Missing/nonunique artifact role: '+role)
        return matches[0]
    profile_pin = artifact('native_nuisance_profile')
    folder = Path(profile_pin['path']).parent
    require(folder.name.endswith('-final-covariance'), 'Final profile is not a fresh final-covariance point')
    require(same_pin(profile_pin, strict['evidence']['final_profile']) and same_pin(artifact('native_qr_factor'), strict['evidence']['final_factor']), 'Strict result selects different final native artifacts')
    profile = reader.read(profile_pin)
    require(profile.get('nuisance_converged') is True and profile.get('nuisance_floor_limited') is False and profile.get('fresh_full_nuisance_confirmed') is True, 'No strict nuisance convergence')
    require(profile['threshold_m'] == 1e-8 and profile['required_consecutive_small_updates'] == 2 and profile['fixed_weights'] is True and profile['dynamic_updates'] is False, 'Nuisance policy differs')
    require(len(profile['history']) >= 2 and all(x['maximum_update_m'] < 1e-8 for x in profile['history'][-2:]) and profile['fresh_full_nuisance_update_m'] < 1e-8, 'Final nuisance corrections exceed unchanged threshold')
    R = binary_matrix(reader.verify(artifact('native_qr_factor')))
    rhs_matrix = binary_matrix(reader.verify(artifact('native_qr_rhs')))
    coords = reader.read(artifact('native_qr_coordinates'))
    diag = reader.read(artifact('native_qr_diagnostics'))
    cost = reader.read(artifact('native_objective'))
    n = len(R)
    require(all(len(row) == n for row in R) and len(rhs_matrix) == n and all(len(row) == 1 for row in rhs_matrix), 'Final factor/rhs shape differs')
    require(all(R[i][j] == 0.0 for i in range(n) for j in range(i)), 'Nonzero lower-R entry: independent representation review required; do not silently discard')
    require(coords['schema'] == 'orbit-poc-qr-factor-v1' and coords['rows'] == coords['columns'] == n, 'Coordinate schema/dimensions differ')
    native_full_factor(diag, n)
    local = coords['local_global_indices']; retained = coords['retained_global_indices']
    require(all(type(x) is int for x in local+retained) and local == list(range(len(local))) and retained == list(range(len(local), len(local)+n)), 'Not the complete original retained chart')
    dynamic = coords['dynamic']; scales = finite(coords['scales'])
    require(len(dynamic) == len(scales) == n and all(type(x) is bool for x in dynamic) and all(x > 0 for x in scales), 'Invalid dynamic/scaling metadata')
    indices = [i for i, flag in enumerate(dynamic) if flag]
    force_count = 61 if stage == 'cold-density' else 6
    require(len(indices) == force_count+6, 'Wrong original dynamic dimension')
    b = [row[0] for row in rhs_matrix]
    z = triangular(R, b)
    correction = [scales[i]*z[i] for i in range(n)]
    dyn = [correction[i] for i in indices]
    objective = float(cost['direct_cost'])
    require(math.isfinite(objective) and objective >= 0, 'Invalid direct objective')
    gradient = max(abs(math.fsum(R[i][j]*b[i] for i in range(n))) for j in range(n))/max(1.0, math.sqrt(2*objective))
    controls = request['numerical_controls']
    require(controls['normalized_gradient_tolerance'] == 1e-8 and controls['maximum_position_change_m'] == 3e-5 and controls['maximum_density_update'] == 1e-4 and controls['maximum_pulse_update_m_s'] == 1e-8, 'Original convergence thresholds differ')
    require(gradient < controls['normalized_gradient_tolerance'], 'Reconstructed undamped gradient fails original threshold')
    force_update = max(abs(x) for x in dyn[:-6])*(1.0 if stage == 'cold-density' else 1e-6)
    require(force_update < controls['maximum_density_update' if stage == 'cold-density' else 'maximum_pulse_update_m_s'], 'Reconstructed force correction fails original threshold')
    # Every retained nuisance coordinate participates in each triangular solve.
    inverse_rows = []
    for index in indices:
        right = [0.0]*n; right[index] = scales[index]
        inverse_rows.append(triangular(R, right, transpose=True))
    covariance = [[dot(a, b_) for b_ in inverse_rows] for a in inverse_rows]
    native_cov = matrix(reader.verify(artifact('native_parameter_covariance')))
    d = len(indices)
    require(len(native_cov) == d and all(len(row) == d for row in native_cov), 'Native dynamic covariance dimensions differ')
    difference = math.sqrt(math.fsum((covariance[i][j]-native_cov[i][j])**2 for i in range(d) for j in range(d)))
    denominator = math.sqrt(math.fsum(x*x for row in native_cov for x in row))
    require(denominator > 0, 'Zero dynamic covariance norm')
    design = matrix(reader.verify(artifact('native_initial_state_design')))
    require(len(design) == 6 and all(len(row) == d for row in design), 'Initial-state design dimensions differ')
    initial_rows = [[math.fsum(design[i][j]*inverse_rows[j][k] for j in range(d)) for k in range(n)] for i in range(6)]
    initial_covariance = [[dot(a, b_) for b_ in initial_rows] for a in initial_rows]
    proposal_path = folder/'proposal-000/proposal-retention.json'
    proposal = reader.read(proposal_path)
    require(proposal['status'] == 'complete', 'No completed fresh undamped trajectory proposal')
    proposed = orbit_text(reader.verify(proposal['trajectory']))
    closure = Path(artifact('native_initial_state_design')['path']).parent
    closed = orbit_text(reader.explicit(closure/'orbit.txt.gz'))
    require(len(proposed) == len(closed) and all(a[0] == b_[0] for a, b_ in zip(proposed, closed)), 'Final proposal trajectory epoch support differs')
    position_change = max(math.sqrt(math.fsum((a[k]-b_[k])**2 for k in (1, 2, 3))) for a, b_ in zip(proposed, closed))
    require(position_change < controls['maximum_position_change_m'], 'Reconstructed fresh position change fails original threshold')
    cold = strict['evidence']['cold_start']
    require(cold['nominal_orbit_sha256'] == NOMINAL_SHA and cold['no_physical_override'] is True and cold['no_nuisance_donor'] is True, 'Cold input provenance differs')
    converted = orbit_text(reader.verify(cold['converted']))
    initial = [x for row in matrix(reader.verify(cold['physical_initial'])) for x in row]
    require(initial == converted[0][1:7], 'First physical state differs from retained original initialization conversion')
    force = [float(line.split()[-1]) for line in reader.verify(cold['force']).read_text().splitlines() if line.strip()]
    fixed = [x for row in matrix(reader.verify(cold['fixed_force'])) for x in row]
    require(len(force) == force_count and force == [0.0]*force_count and fixed == [0.0]*(force_count+6), 'Cold initial force is not exactly zero')
    return {
        'stage': stage, 'selected_checks_completed': True, 'lower_triangle_exact_zero': True,
        'retained_dimension': n, 'dynamic_indices': indices, 'undamped_native_correction': correction,
        'recomputed_normalized_gradient': gradient, 'recorded_normalized_gradient': strict['evidence']['fresh_final_correction']['normalized_gradient'],
        'recomputed_position_change_m': position_change, 'recorded_metrics': proposal['metrics'],
        'recomputed_force_update': force_update, 'force_update_units': 'log_density' if stage == 'cold-density' else 'm/s',
        'recomputed_dynamic_covariance_native_units': covariance,
        'dynamic_covariance_relative_frobenius_difference': difference/denominator,
        'recomputed_initial_cartesian_covariance_si': initial_covariance,
        'initial_cartesian_correction_si': [dot(row, dyn) for row in design],
        'direct_objective': objective,
        'undamped_qr_optimum_objective': 0.5*coords['orthogonal_energy'],
        'rank_certificate_scope': 'Recorded original factor only; independent SVD outstanding',
        'covariance_difference_accepted': False,
        'cold_state_matches_saved_original_conversion': True,
    }


def audit(reader):
    context = terminal_identity(reader)
    summary = {'sequence_terminal': context['terminal'], 'gates': [], 'cold': [], 'errors': [], 'phase_evidence': {}}
    terminal = context['terminal']
    if not (terminal.get('status') == 'complete' and terminal.get('returncode') == 0 and terminal.get('phase') == 'finished' and terminal.get('error') is None and not terminal.get('signals_received') and not terminal.get('phase_receipt_errors')):
        summary['errors'].append({'phase': 'sequence', 'audit_status': 'failed', 'recorded_status': terminal.get('status'), 'error': 'Sequence did not finish successfully; its original outcome is retained'})
    # Missing/failed gates do not erase the other planned attempts from the report.
    gate_plan = reader.read(GATES/'plan.json')
    gate_freeze = reader.read(GATES/'freeze.json')
    cold_plan = reader.read(COLD/'plan.json')
    require(gate_plan['schema'] == 'orbit-poc-candidate06-correctness-plan-v2' and gate_plan['stages'] == list(STAGES) and [x['stage'] for x in gate_plan['jobs']] == list(STAGES), 'Wrong complete gate plan inventory')
    require([x['stage'] for x in cold_plan['jobs']] == list(COLD_STAGES), 'Cold planned inventory differs')

    def phase_document(phase, path, validate):
        # Read aggregate/detached evidence independently: the absence of one
        # cannot erase available rows from the other or the pinned inventory.
        key = phase+'/'+Path(path).name
        try:
            value = reader.read(path)
            validate(value)
            summary['phase_evidence'][key] = {'audit_status': 'identity_verified', 'recorded_status': value.get('status')}
            return value
        except Exception as exc:
            record = {'phase': phase, 'path': str(path), 'audit_status': 'pending' if isinstance(exc, Pending) else 'failed', 'error': repr(exc)}
            summary['phase_evidence'][key] = record
            summary['errors'].append(record)
            return None

    def gate_aggregate_identity(value):
        require(value['planned_stages'] == list(STAGES), 'Gate aggregate planned inventory differs')
        require(same_pin(value['plan'], gate_freeze['plan']) and same_pin(value['freeze'], context['plan']['gate_freeze']), 'Gate aggregate attribution differs')
        names = [row['stage'] for row in value['stages']]
        require(len(set(names)) == len(names) and set(names).issubset(STAGES), 'Duplicate/foreign gate outcome')

    def gate_detached_identity(value):
        require(value['freeze_sha256'] == context['plan']['gate_freeze']['sha256'] and value['review_sha256'] == context['plan']['gate_review']['sha256'], 'Detached correctness attribution differs')

    aggregate = phase_document('correctness', GATES/'result.json', gate_aggregate_identity)
    detached = phase_document('correctness', GATES/'detached-result.json', gate_detached_identity)
    rows = {row['stage']: row for row in aggregate['stages']} if aggregate is not None else {}
    for job in gate_plan['jobs']:
        stage = job['stage']
        recorded_status = rows.get(stage, {}).get('status')
        try:
            if stage not in rows:
                raise Pending('Planned gate has no outcome')
            summary['gates'].append(gate_stage(reader, job, rows[stage], gate_freeze['plan'], context['plan']['gate_freeze']))
        except Exception as exc:
            record = {'stage': stage, 'recorded_status': recorded_status, 'audit_status': 'pending' if isinstance(exc, Pending) else 'failed', 'error': repr(exc)}
            summary['gates'].append(record); summary['errors'].append(record)
    gate_errors = any(row.get('stage') in STAGES for row in summary['errors'])
    all_gate_pass = not gate_errors and aggregate is not None and detached is not None and aggregate.get('all_eleven_strict_passed') is True and detached.get('status') == 'complete' and detached.get('returncode') == 0 and detached.get('error') is None and not detached.get('signals_received')
    summary['all_eleven_recorded_strict_passes_and_selected_hash_checks'] = all_gate_pass
    if detached is not None and not (detached.get('status') == 'complete' and detached.get('returncode') == 0 and detached.get('error') is None and not detached.get('signals_received')):
        summary['errors'].append({'phase': 'correctness', 'audit_status': 'failed', 'recorded_status': detached.get('status'), 'error': 'Correctness controller did not complete successfully'})

    def cold_aggregate_identity(value):
        require(value['planned_stages'] == list(COLD_STAGES), 'Cold outcome planned inventory differs')
        require(value['freeze_sha256'] == context['plan']['cold_freeze']['sha256'], 'Cold aggregate freeze differs')
        names = [row['stage'] for row in value['stages']]
        require(len(set(names)) == len(names) and set(names).issubset(COLD_STAGES), 'Duplicate/foreign cold outcome')

    def cold_detached_identity(value):
        require(value['freeze_sha256'] == context['plan']['cold_freeze']['sha256'] and value['audit_sha256'] == context['plan']['cold_review']['sha256'], 'Detached cold attribution differs')

    cold_result = phase_document('cold', COLD/'result.json', cold_aggregate_identity)
    cold_detached = phase_document('cold', COLD/'detached-result.json', cold_detached_identity)
    summary['cold_phase_terminal'] = cold_detached
    cold_rows = {row['stage']: row for row in cold_result['stages']} if cold_result is not None else {}
    cold_phase_complete = cold_result is not None and cold_detached is not None and cold_detached.get('status') == 'complete' and cold_detached.get('returncode') == 0 and cold_detached.get('error') is None and not cold_detached.get('signals_received') and cold_result.get('status') == 'passed'
    if cold_result is not None and cold_detached is not None and not cold_phase_complete:
        summary['errors'].append({'phase': 'cold', 'audit_status': 'failed', 'recorded_status': cold_result.get('status'), 'error': 'Cold phase did not complete successfully'})
    for job in cold_plan['jobs']:
        stage = job['stage']
        recorded = {'aggregate': cold_rows.get(stage, {}).get('status'), 'artifacts': []}
        # Collect bounded unsuccessful evidence too; never turn a failure into a
        # pass merely because the selected strict-final audit is inapplicable.
        for label, value in (('strict', cold_rows.get(stage, {}).get('strict_result')), ('supervisor', cold_rows.get(stage, {}).get('supervisor')), ('backend', COLD/stage/'backend-result.json')):
            try:
                if value is None:
                    raise Pending('No '+label+' receipt pin')
                document = reader.read(value)
                recorded[label] = {key: document[key] for key in ('status', 'numerical_status', 'returncode', 'error', 'converged', 'covariance_valid', 'accepted_covariance') if key in document}
                if label == 'backend':
                    for item in document.get('artifacts', []):
                        try:
                            reader.verify(item)
                            recorded['artifacts'].append({'path': item['path'], 'sha256': item['sha256'], 'hash_verified': True})
                        except Exception as exc:
                            recorded['artifacts'].append({'path': item.get('path'), 'hash_verified': False, 'error': repr(exc)})
            except Exception as exc:
                recorded[label] = {'audit_status': 'pending' if isinstance(exc, Pending) else 'failed', 'error': repr(exc)}
        try:
            require_attempt_receipt(cold_rows.get(stage))
            if not all_gate_pass:
                raise Pending('Recorded cold outcome remains unverified without all eleven strict gate receipts')
            if cold_result is None or cold_detached is None:
                raise Pending('Recorded cold outcome remains unverified without identity-verified cold phase receipts')
            selected = cold_selected(reader, stage, job, cold_rows[stage])
            selected['recorded_receipts'] = recorded
            summary['cold'].append(selected)
        except Exception as exc:
            record = {'stage': stage, 'audit_status': 'pending' if isinstance(exc, Pending) else 'failed', 'recorded_status': cold_rows.get(stage, {}).get('status'), 'recorded_receipts': recorded, 'error': repr(exc)}
            summary['cold'].append(record); summary['errors'].append(record)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--inputs-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Opening output exclusively preserves every audit failure and prior draft run.
    with args.output.open('x') as stream:
        result = {'schema': 'candidate06-selected-terminal-audit-draft-v1', 'draft_untested': True,
                  'source_revision': 'source02',
                  'approved': False, 'release_authority': False, 'covariance_authority': False,
                  'gates': [{'stage': stage, 'audit_status': 'pending', 'recorded_status': None} for stage in STAGES],
                  'cold': [{'stage': stage, 'audit_status': 'pending', 'recorded_status': None} for stage in COLD_STAGES],
                  'generated_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'input_manifest': {'path': str(args.inputs.absolute()), 'sha256': args.inputs_sha256},
                  'source': {'path': str(Path(__file__).absolute()), 'sha256': sha(__file__)},
                  'full_review_outstanding': OUTSTANDING}
        reader = None
        try:
            require(sha(args.inputs) == args.inputs_sha256, 'Terminal input manifest hash differs')
            manifest = json.loads(args.inputs.read_text())
            require(manifest.get('audit_source_sha256') == result['source']['sha256'], 'Input manifest is not bound to this exact draft source')
            reader = Reader(manifest)
            result.update(audit(reader))
            for item in list(reader.consumed.values()):
                reader.verify(item)
            # Even a clean selected review cannot authorize release or covariance.
            result['status'] = 'selected_review_incomplete' if result['errors'] else 'selected_checks_complete_full_review_required'
        except Exception as exc:
            result.update(status='pending' if isinstance(exc, Pending) else 'failed', error=repr(exc))
        finally:
            result['consumed_pins'] = list(reader.consumed.values()) if reader else []
            json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
    return 0 if result['status'] == 'selected_checks_complete_full_review_required' else 1


if __name__ == '__main__':
    sys.exit(main())
