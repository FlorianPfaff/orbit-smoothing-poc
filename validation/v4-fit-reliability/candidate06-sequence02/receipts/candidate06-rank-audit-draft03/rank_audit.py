"""SOURCE ONLY, UNTESTED: independent saved-R rank audit, no release authority.

No project imports, propagation, fits, normal equations, ridge or truncation.
SciPy DGESVD is selected explicitly; native GROOPS uses DGESDD. A classification
disagreement is a discrepancy, never resolved by widening the rank thresholds.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import tempfile

ROOT = Path('/mnt/d/orbit-v41-recovery02')
SEQUENCE = ROOT/'density-trial-sequence02'
COLD = ROOT/'candidate06-cold02'
SEQUENCE_SHA = '0d886a5f236ba5a1b734b5395d142e663e13c3b7fa2693044072c0822ff05d67'
NATIVE_SHA = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
SOURCE_SHA = '3c9174b52e0b894ffee58f0f4a28bb5e633e5861b377da0a587eac9eb8f2b702'
COLD_FREEZE_SHA = '630a55edeb657d85e7cc1ce94630a09fc1128c5c4e6a45fd90c33242f550e83a'
STAGES = ('cold-pulses', 'cold-density')
FORMAT = 'uint64 rows, uint64 columns, row-major float64; little-endian'
MAX_BYTES = 256*1024*1024
MAX_COLUMNS = 4096
MAX_LOCAL = 1000000
EPS = sys.float_info.epsilon
STATUS = {'full': 'full_rank', 'deficient': 'rank_deficient', 'unresolved': 'unresolved_rank'}
ERRORS = (OSError, ValueError, TypeError, KeyError, OverflowError, struct.error, ImportError, RuntimeError)


class Missing(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0, maximum=2**53):
    require(type(value) is int and minimum <= value <= maximum, 'Invalid '+name)
    return value


def number(value, name, positive=False):
    require(type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0), 'Invalid '+name)
    return float(value)


def classify_singular_values(values, effective_rows, columns):
    """Exact frozen binary64 policy; this function does not compute an SVD."""
    integer(columns, 'columns', 1, MAX_COLUMNS)
    integer(effective_rows, 'effective_rows', 0)
    require(len(values) == columns, 'Singular value count differs')
    singular = [number(x, 'singular value') for x in values]
    require(all(a >= b for a, b in zip(singular, singular[1:])), 'Singular values not descending')
    threshold = EPS * max(effective_rows, columns) * singular[0]
    require(math.isfinite(threshold), 'Rank threshold is nonfinite')
    rank = sum(x > threshold for x in singular)
    status = 'deficient' if rank < columns else ('unresolved' if singular[-1] <= 10*threshold else 'full')
    condition = singular[0]/singular[-1] if singular[-1] else None
    if condition is not None and not math.isfinite(condition):
        condition = None
    return {'status': status, 'python_status': STATUS[status], 'rank': rank,
            'columns': columns, 'effective_rows': effective_rows,
            'threshold': threshold, 'sigma_max': singular[0], 'sigma_min': singular[-1],
            'condition_number': condition,
            'singular_values': singular}


def decode_factor(raw, expected_columns):
    """Decode exact native little-endian row-major bytes without trimming."""
    integer(expected_columns, 'expected columns', 1, MAX_COLUMNS)
    require(type(raw) is bytes and 16 <= len(raw) <= MAX_BYTES, 'Invalid factor payload size')
    rows, columns = struct.unpack('<QQ', raw[:16])
    require(rows == columns == expected_columns, 'Factor dimensions differ from reviewed full chart')
    require(len(raw) == 16+8*rows*columns, 'Truncated or trailing factor bytes')
    import numpy as np
    result = np.frombuffer(raw, dtype='<f8', offset=16).reshape((rows, columns))
    require(np.isfinite(result).all(), 'Nonfinite factor')
    require(not np.any(np.tril(result, -1) != 0), 'Nonzero lower factor entry; do not truncate')
    return result


def validate_metadata(info, diag, expected_rows, expected_columns, expected_dynamic):
    """Bind dimensions/scales; do not unscale or rescale the already scaled R."""
    n = integer(expected_columns, 'expected columns', 1, MAX_COLUMNS)
    m = integer(expected_rows, 'expected rows', 0)
    integer(expected_dynamic, 'expected dynamic count', 1, n)
    require(info['schema'] == 'orbit-poc-qr-factor-v1' and info['binary_format'] == FORMAT,
            'Conditional or unsupported factor metadata')
    require(integer(info['rows'], 'metadata rows', 1) == n
            and integer(info['columns'], 'metadata columns', 1) == n, 'Metadata dimensions differ')
    require(diag['schema'] == 'orbit-poc-native-qr-v1', 'Conditional or unsupported diagnostics')
    require(number(diag['lambda'], 'damping') == 0, 'Damped factor cannot certify rank')
    require(info.get('full_rank_certificate') is not False and info.get('covariance_authority') is not False,
            'Explicit incomplete/conditional factor certificate')
    require(integer(diag['retained_parameters'], 'retained count', 1) == n, 'Retained count differs')
    require(integer(diag['reduced_rows'], 'reduced row count', 0) == m,
            'Reviewed effective row count differs from native reduced_rows')
    local = info['local_global_indices']; retained = info['retained_global_indices']
    require(isinstance(local, list) and len(local) <= MAX_LOCAL, 'Invalid local chart')
    require(all(type(x) is int and x == i for i, x in enumerate(local)), 'Incomplete local chart')
    require(isinstance(retained, list) and len(retained) == n
            and all(type(x) is int and x == len(local)+i for i, x in enumerate(retained)),
            'Incomplete original retained chart')
    require(integer(diag['local_parameters'], 'local count', 0, MAX_LOCAL) == len(local), 'Local count differs')
    source_rows = integer(diag['source_rows'], 'source rows', m)
    require(source_rows-m == len(local), 'Epoch-local elimination row accounting differs')
    require(integer(info['original_objective_rows'], 'original objective rows', source_rows) >= source_rows,
            'Original objective row accounting differs')
    require(info['local_elimination'] == 'independent_epoch_clock_vtec_qr', 'Unsupported local elimination')
    for key, count in (('scales', n), ('local_scales', len(local))):
        require(isinstance(info[key], list) and len(info[key]) == count, 'Wrong '+key+' length')
        for value in info[key]:
            number(value, key, positive=True)
    require(isinstance(info['dynamic'], list) and len(info['dynamic']) == n
            and all(type(x) is bool for x in info['dynamic'])
            and sum(info['dynamic']) == expected_dynamic, 'Dynamic coordinate map differs')
    require(diag['rank_status'] in STATUS, 'Unknown native rank vocabulary')
    integer(diag['rank'], 'reported rank', 0, n)
    for key in ('rank_threshold', 'sigma_max', 'sigma_min'):
        number(diag[key], key)
    return {'effective_rows': m, 'columns': n, 'source_rows': source_rows,
            'original_objective_rows': info['original_objective_rows'], 'local_parameters': len(local),
            'row_count_basis': 'native reduced_rows after epoch-local QR; not source_rows or original_objective_rows',
            'factor_coordinate_basis': 'saved column-scaled retained original parameters; no second scaling'}


def verify_parameter_table(text, info):
    lines = text.splitlines()
    require(lines and lines[0] == 'index\tname\tdynamic\tunit\tscale\tcoordinate_convention',
            'Unsupported parameter inventory')
    k = len(info['local_global_indices']); n = info['columns']
    require(len(lines) == 1+k+n, 'Parameter inventory dimensions differ')
    for i, line in enumerate(lines[1:]):
        fields = line.split('\t')
        require(len(fields) == 6 and fields[0] == str(i), 'Parameter inventory index differs')
        require(fields[1] and fields[3] and fields[5], 'Missing native identity/unit/convention')
        require(fields[2] in ('0', '1'), 'Invalid parameter dynamic flag')
        scale = number(float(fields[4]), 'parameter inventory scale', positive=True)
        require(scale == info['local_scales'][i] if i < k else scale == info['scales'][i-k],
                'Scale metadata differs from native inventory')
        require(fields[2] == '0' if i < k else (fields[2] == '1') == info['dynamic'][i-k],
                'Dynamic map differs from native inventory')


def audit_arrays(factor, info, diag, recorded_singular, *, effective_rows, columns, dynamic_count):
    """Pure supplied-array audit. Never read project state or form R.T @ R."""
    import numpy as np
    from scipy.linalg import svd
    dimensions = validate_metadata(info, diag, effective_rows, columns, dynamic_count)
    require(isinstance(factor, np.ndarray) and factor.dtype == np.float64
            and factor.shape == (columns, columns), 'Factor array must be full float64 square chart')
    require(np.isfinite(factor).all(), 'Nonfinite factor')
    require(not np.any(np.tril(factor, -1) != 0), 'Nonzero lower factor entry; do not truncate')
    native = classify_singular_values(recorded_singular, effective_rows, columns)
    discrepancies = []
    for key, value in (('rank_status', native['status']), ('rank', native['rank']),
                       ('rank_threshold', native['threshold']), ('sigma_max', native['sigma_max']),
                       ('sigma_min', native['sigma_min'])):
        if diag[key] != value:
            discrepancies.append('Native diagnostics inconsistent with native singular table: '+key)
    # Explicit gesvd differs from producer DGESDD. No normal equations or fallback.
    singular = svd(factor, compute_uv=False, overwrite_a=False, check_finite=True, lapack_driver='gesvd')
    independent = classify_singular_values(singular.tolist(), effective_rows, columns)
    if (independent['status'], independent['rank']) != (native['status'], native['rank']):
        discrepancies.append('DGESVD/DGESDD rank classification or rank count differs')
    delta = [a-b for a, b in zip(independent['singular_values'], native['singular_values'])]
    largest = max(independent['sigma_max'], native['sigma_max'])
    return {'schema': 'candidate06-independent-saved-factor-rank-v1', 'approved': False,
            'covariance_authority': False, 'release_authority': False, 'dimensions': dimensions,
            'independent_driver': 'scipy.linalg.svd lapack_driver=gesvd compute_uv=False',
            'producer_driver_from_pinned_source': 'GROOPS LAPACK DGESDD computeSingularVectors=FALSE',
            'native_reported': native, 'independent': independent, 'discrepancies': discrepancies,
            'rank_classification_agrees': not discrepancies,
            'full_rank_classification_agrees': not discrepancies and independent['status'] == 'full',
            'singular_value_differences': delta,
            'maximum_absolute_singular_value_difference': max(abs(x) for x in delta),
            'maximum_difference_over_largest_singular_value': max(abs(x) for x in delta)/largest if largest else 0.,
            'singular_value_numeric_agreement_accepted': False,
            'comparison_policy': 'Report floating differences without a new numerical tolerance; exact rank classification must agree.'}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    """Reject nonfinite constants and overflow before evidence enters a report."""
    def reject_constant(value):
        raise ValueError('Nonfinite JSON constant: '+value)
    def finite_float(value):
        parsed = float(value)
        require(math.isfinite(parsed), 'Nonfinite/overflow JSON number: '+value)
        return parsed
    return json.loads(raw, parse_constant=reject_constant, parse_float=finite_float)


def write_new_json(path, value):
    """Serialize a finite report fully, then publish atomically without overwrite."""
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n').encode('utf-8')
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='wb', prefix='.rank-audit-', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hard-link creation is atomic and fails if target exists.
        # No overwrite or non-atomic fallback on unsupported filesystems.
        os.link(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class Reader:
    def __init__(self):
        self.used = {}

    def read(self, pin):
        require(isinstance(pin, dict) and set(pin) == {'path', 'bytes', 'sha256'}, 'Invalid exact artifact pin')
        path = Path(pin['path'])
        require(path.is_absolute() and str(path) == str(path.resolve()) and not path.is_symlink(),
                'Artifact requires canonical regular path; no inferred alias')
        integer(pin['bytes'], 'artifact size', 0, MAX_BYTES)
        require(type(pin['sha256']) is str and re.fullmatch('[0-9a-f]{64}', pin['sha256']), 'Invalid artifact digest')
        try:
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES+1)
        except FileNotFoundError as exc:
            raise Missing('Missing pinned artifact: '+str(path)) from exc
        require(len(raw) == pin['bytes'] and len(raw) <= MAX_BYTES, 'Artifact size differs or exceeds audit bound')
        require(digest(raw) == pin['sha256'], 'Artifact digest differs')
        previous = self.used.get(str(path))
        require(previous is None or previous == pin, 'Artifact attribution changed during audit')
        self.used[str(path)] = dict(pin)
        return raw

    def json(self, pin):
        return strict_json(self.read(pin))


def empty_report():
    return {'schema': 'candidate06-terminal-rank-audit-draft-v1', 'source_only_draft': True,
            'approved': False, 'covariance_authority': False, 'release_authority': False,
            'cases': [{'stage': stage, 'status': 'unavailable', 'recorded_status': None} for stage in STAGES],
            'errors': [], 'consumed_pins': [], 'all_two_full_rank_classifications_agree': False,
            'limits': ['No independent raw-row recount or column-norm reconstruction.',
                       'No comparison to prior confirmation Python certificate: it is a different factor.',
                       'No nuisance convergence, covariance, objective, full execution or release certificate.',
                       'Audit byte/dimension bounds are not a measured process-tree memory certificate.']}


def verify_terminal(manifest, reader):
    require(isinstance(manifest, dict), 'Manifest is not an object')
    require(manifest['schema'] == 'candidate06-terminal-rank-inputs-v1', 'Wrong manifest schema')
    require(manifest['planned_cases'] == list(STAGES), 'Wrong planned inventory')
    require(manifest['sequence_plan_sha256'] == SEQUENCE_SHA
            and manifest['candidate_source_hash'] == SOURCE_SHA
            and manifest['native_binary_sha256'] == NATIVE_SHA, 'Wrong frozen identity')
    pins = manifest['terminal']
    for name, filename in (('launch', 'launch.json'), ('result', 'result.json')):
        require(pins[name]['path'] == str(SEQUENCE/filename), 'Foreign terminal receipt')
    launch = reader.json(pins['launch']); result = reader.json(pins['result'])
    require(launch['plan_sha256'] == result['plan_sha256'] == SEQUENCE_SHA, 'Terminal plan attribution differs')
    require(launch['pid'] == 86724 and launch['start_ticks'] == 2037467
            and launch['boot_id'] == 'cb2d0b40-9b17-45f8-9e5c-716efb8e6aa5', 'Unexpected sequence identity')
    require(result['status'] in ('complete', 'failed', 'interrupted'), 'Sequence is not terminal')
    proc = Path('/proc')/str(launch['pid'])/'stat'
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if boot == launch['boot_id'] and proc.exists():
        fields = proc.read_text().rsplit(')', 1)[1].split()
        require(int(fields[19]) != launch['start_ticks'], 'Original sequence still exists; execution prohibited')
    return result['status']


def audit_manifest_object(manifest, reader):
    result = empty_report()
    try:
        result['sequence_recorded_status'] = verify_terminal(manifest, reader)
        aggregate_pin = manifest['terminal'].get('cold_aggregate')
        if aggregate_pin is None:
            raise Missing('No cold aggregate pin; planned cases remain unavailable')
        require(aggregate_pin['path'] == str(COLD/'result.json'), 'Foreign cold aggregate')
        aggregate = reader.json(aggregate_pin)
        require(aggregate['planned_stages'] == list(STAGES)
                and aggregate['freeze_sha256'] == COLD_FREEZE_SHA, 'Cold aggregate identity differs')
        outcomes = aggregate['stages']
        require(isinstance(outcomes, list) and all(isinstance(x, dict) for x in outcomes), 'Invalid cold outcomes')
        names = [x['stage'] for x in outcomes]
        require(len(names) == len(set(names)) and set(names).issubset(STAGES), 'Duplicate/foreign cold outcome')
        by_stage = {x['stage']: x for x in outcomes}
        require(set(manifest['cases']) == set(STAGES), 'Missing or unknown case records')
        for report in result['cases']:
            stage = report['stage']; case = manifest['cases'][stage]
            try:
                require(isinstance(case, dict), 'Case manifest entry is not an object')
                report['recorded_status'] = by_stage.get(stage, {}).get('status')
                require(case.get('recorded_status') == report['recorded_status'], 'Manifest/actual recorded outcome differs')
                if case.get('recorded_status') in ('failed', 'timeout', 'interrupted', 'memory_limit', 'resource_limit'):
                    report['status'] = 'recorded_unsuccessful'; continue
                if case.get('recorded_status') in (None, 'not_executed_or_interrupted_without_receipt'):
                    report['status'] = 'unavailable'; continue
                require(case['recorded_status'] == 'passed', 'Unknown recorded case status')
                require(case['backend_result']['path'] == str(COLD/stage/'backend-result.json'), 'Foreign backend result')
                backend = reader.json(case['backend_result'])
                require(backend['status'] == 'complete' and backend['converged'] is True
                        and backend['source_hash'] == SOURCE_SHA and backend['native_binary_sha256'] == NATIVE_SHA,
                        'Backend result is not complete or candidate identity differs')
                prefix = Path(case['factor_prefix'])
                require(prefix.is_absolute() and prefix.is_relative_to(COLD/stage/'fit')
                        and prefix.parent.name.endswith('-final-covariance')
                        and re.fullmatch(r'qr\.\d+', prefix.name), 'Not the owned final-covariance factor')
                files = case['files']
                suffixes = {'factor': '.R.bin', 'coordinates': '.factor.json', 'diagnostics': '.diagnostics.json',
                            'singular_values': '.singular_values.txt', 'parameters': '.parameters.tsv'}
                require(set(files) == set(suffixes), 'Wrong factor file inventory')
                for key, suffix in suffixes.items():
                    require(files[key]['path'] == str(prefix)+suffix, 'Mixed factor generation: '+key)
                for key, role in (('factor', 'native_qr_factor'), ('coordinates', 'native_qr_coordinates'),
                                  ('diagnostics', 'native_qr_diagnostics'), ('parameters', 'native_qr_parameters')):
                    matches = [x for x in backend['artifacts'] if x.get('role') == role]
                    require(len(matches) == 1 and all(matches[0].get(k) == files[key][k]
                            for k in ('path', 'sha256')), 'Selected factor differs from final backend artifact: '+key)
                expected = case['reviewed_dimensions']
                require(set(expected) == {'effective_rows', 'columns', 'dynamic_count'}, 'Wrong reviewed dimension fields')
                require(expected['dynamic_count'] == (12 if stage == 'cold-pulses' else 67), 'Wrong original dynamic count')
                info = reader.json(files['coordinates']); diag = reader.json(files['diagnostics'])
                validate_metadata(info, diag, expected['effective_rows'], expected['columns'], expected['dynamic_count'])
                verify_parameter_table(reader.read(files['parameters']).decode('utf-8'), info)
                raw = reader.read(files['factor'])
                factor = decode_factor(raw, expected['columns'])
                saved = [float(x) for x in reader.read(files['singular_values']).decode('ascii').splitlines()]
                details = audit_arrays(factor, info, diag, saved, **expected)
                report.update(status='rank_check_complete' if details['full_rank_classification_agrees'] else 'rank_discrepancy_or_not_full', details=details)
            except Missing as exc:
                report.update(status='unavailable', error=str(exc)[:3000])
            except Exception as exc:
                report.update(status='audit_discrepancy', error=str(exc)[:3000])
    except Exception as exc:
        result['errors'].append(str(exc)[:3000])
    result['consumed_pins'] = list(reader.used.values())
    result['all_two_full_rank_classifications_agree'] = not result['errors'] and all(x['status'] == 'rank_check_complete' for x in result['cases'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--inputs-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = empty_report()
    try:
        with args.inputs.open('rb') as source:
            raw = source.read(MAX_BYTES+1)
        require(len(raw) <= MAX_BYTES and digest(raw) == args.inputs_sha256, 'Manifest size/digest differs')
        manifest = strict_json(raw)
        auditor_sha = digest(Path(__file__).read_bytes())
        require(manifest['audit_source_sha256'] == auditor_sha, 'Manifest is bound to another audit source')
        result = audit_manifest_object(manifest, Reader())
        result['auditor_sha256'] = auditor_sha
        result['input_manifest_sha256'] = args.inputs_sha256
        result['interpreter'] = sys.executable
    except Exception as exc:
        result['errors'].append(str(exc)[:3000])
    write_new_json(args.output, result)
    return 0 if result['all_two_full_rank_classifications_agree'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
