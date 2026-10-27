"""SOURCE-ONLY, UNEXECUTED saved-output audit of eight scientific stages.

Only stdlib; no project imports, commands, refits, propagation, writes to inputs,
or approval authority. Run only after the complete sequence is terminal and an
exclusive serial audit slot is granted. A separately reviewed input manifest
pins every file read, including explicit namespace-to-host path mappings.
"""
from pathlib import Path
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import re
import stat
import xml.etree.ElementTree as ET
import zlib

BASE = Path('/mnt/d/orbit-v41-recovery02')
RUN = BASE / 'candidate06-correctness02'
SOURCE = Path('/mnt/d/orbit-v41-density-trial-candidate06/source')
PLAN_SHA = 'eb9f2a088b30cf631ab1437666e5f69cf23935f8e9fabbd355ef3254169c63f3'
FREEZE_SHA = '4868b8e5458c3e310bae43ae03d033f3fff4b4b7462bc92ef82dd454b92b92a2'
SEQ_SHA = '0d886a5f236ba5a1b734b5395d142e663e13c3b7fa2693044072c0822ff05d67'
NATIVE_SHA = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
NATIVE_PATH = '/mnt/d/orbit-v41-recovery01/candidate04/binaries/groops-v41-28c725765201e470'
SNAPSHOT_SHA = '24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739'
STAGES = ('native-tests', 'native-fail-fast-tests', 'correction-tests',
          'synthetic-refinement-log_drag_ou', 'synthetic-refinement-pulses',
          'flight-refinement', 'eccentric-24h-refinement', 'objective-log_drag_ou',
          'objective-pulses', 'nuisance-replay', 'nuisance-replay-candidate1-point012')
SCIENTIFIC = STAGES[3:]
INPUT_SHA = {
    'density_request': '2189944cfb519b5ca0730e6e02ee9cb809145a0845f66846931a8fb199694dfd',
    'pulse_request': '9de707ae51e5031a5b13f1d02ab5ec5a67e996195840de6c5c7e81457a74c9f5',
    'flight_prepared': '07ca66ce4c82179f98bbba18a28d47ad49f84b7eaa351f24beecc0c691daa554',
    'full_day_request': '8c1af6352f555f3b25d619d81899c28459321cea8204ae97a418e614f072c666',
    'initial_state': '61b08f300902d38357b3ea6889711818a3ae590af74de05375121ac05dc403ea',
    'old_nuisance_replay': '902923d3d84ce30cee1f0cb8484784aae62aafb69097f2d431c373913ac8aca0',
    'candidate1_nuisance_replay': '3440617770eae3177d6a87b8b743e79603ac9b0e9245da0d84f3016177eb1ed8',
    'old_replay_density': '04423d3a829d790f38f5d5c3befc6c28cc3d95b590ec89530653b47169806129',
    'old_replay_reference': '2d9e49252da986843035ed0e78df9fb217069a04426cfab1621ec571ba5744a8',
    'old_replay_variational': 'a2f39bb67f756f013a2b47bb9e5c8e8863a2dc100243a0682eda65a71020cf5d',
    'new_replay_density': '1c554b9450d5d7d3204886cdea63aead22b9965c986524ddfac44db75f665772',
    'new_replay_reference': 'bfcbabb09dc288aa939b68191150250e887e1ca535dcdbca1f8640350b7b94b7',
    'new_replay_variational': '10a8304c8f999fa61d84939eeadb16db4ab109bf8982f85b7ab2f9de24aa07f6',
    'prior_validation': '7b22601bafb88789c3e33d417178129e6ee0a7ee84fc6cebeef7aa371622e0cb',
}
SCRIPT_SHA = {
    'validate_numerics_synthetic_refinement.py': '1d53c011b87929874b3663f3743a46f66d63dd45e449b85c5e37ed0012ac08d0',
    'validate_numerics_flight_refinement.py': '77ca65a0359ceead4c24082493501e7f6e4c61a4b8de926906531d4023e843d9',
    'numerics_refinement_helpers.py': 'a03b06a4966cc0de7dd2538af669b2699027a0239c253c1a0e5b91e3ddb1c4f9',
    'validate_numerics_objective.py': '8000fedb69d874e7680a62dd3b24c65982c3230ef57aa022174b3df2b28bcf10',
    'validate_numerics_nuisance.py': '5887b02f9219ef3826aae8b11411056b33a39ddaad9173abf0b3f18a5737c713',
}
UNAVAILABLE = [
    'No independent propagation/refit, complete source/dependency tree or process-lifecycle audit; use the separately reviewed terminal supervisor audit.',
    'Three test suites and two cold fits are inventory-only here; source02 covers selected cold corrections/covariance and test receipt checks.',
    'No independent full SVD or recomputation of the analytic native directional derivative from pruned original factors/directions. Finite differences and prior residuals are independently recomputed.',
    'No direct recomputation of the full precise original measurement objective from every raw residual expansion; saved direct native costs are rebound to each endpoint.',
    'No complete independent floor-audit proof for any floor-limited objective endpoint. Such endpoints are reported distinctly and cannot authorize covariance.',
    'No complete flight Jacobian, calibrated uncertainty, accuracy superiority, benchmark substitution or release claim.',
]


class Missing(Exception):
    pass


EVIDENCE_ERRORS = (Missing, ValueError, KeyError, TypeError, IndexError,
                   OSError, ET.ParseError, EOFError, zlib.error, ArithmeticError)
MAX_BYTES = 256*1024**2


def required_fields(value, names, label):
    require(isinstance(value, dict), label+' is not an object')
    missing = [name for name in names if name not in value]
    if missing:
        raise Missing(label+' lacks saved metadata: '+', '.join(missing))


def error_text(error):
    # Keep failure reports bounded even when a malformed field is very large.
    return (type(error).__name__+': '+str(error))[:4096]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def close(a, b):
    # Existing validation.report arithmetic-consistency tolerance, not a new
    # scientific acceptance threshold. Predicates below use original limits.
    return number(a) and number(b) and math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-15)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


class Reader:
    def __init__(self, manifest):
        require(manifest['schema'] == 'candidate06-scientific-terminal-inputs-v1', 'Unknown input manifest')
        require(manifest['planned_stages'] == list(STAGES), 'Frozen eleven-stage inventory differs')
        require(manifest['scientific_stages'] == list(SCIENTIFIC), 'Eight-stage inventory differs')
        self.manifest = manifest
        self.files = manifest['files']
        self.used = {}

    def raw(self, logical, expected=None):
        logical = str(logical)
        if logical not in self.files:
            raise Missing('File absent from reviewed terminal manifest: ' + logical)
        item = self.files[logical]
        require(re.fullmatch('[0-9a-f]{64}', item['sha256']) is not None, 'Invalid file hash')
        path = Path(item['path'])
        require(path.is_absolute() and path == path.resolve(), 'Host backing path is not canonical')
        if not path.exists():
            raise Missing('Saved file unavailable: ' + str(path))
        require(stat.S_ISREG(path.lstat().st_mode), 'Saved artifact must be a regular file')
        require(type(item['bytes']) is int and 0 <= item['bytes'] <= 256*1024**2, 'Bounded audit file limit exceeded')
        require(path.stat().st_size == item['bytes'], 'File size changed: ' + logical)
        raw = path.read_bytes()
        require(digest(raw) == item['sha256'], 'Saved bytes changed: ' + logical)
        require(expected is None or item['sha256'] == expected, 'Frozen identity differs: ' + logical)
        self.used[logical] = dict(item)
        return raw

    def json(self, logical, expected=None):
        return decode(self.raw(logical, expected))

    def pin(self, item):
        return self.raw(item['path'], item['sha256'])

    def table(self, logical, columns):
        return table(self.raw(logical).decode(), columns)


def table(text, columns):
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != columns:
            continue
        try:
            row = [float(value) for value in fields]
        except ValueError:
            continue
        require(all(math.isfinite(value) for value in row), 'Nonfinite saved table')
        rows.append(row)
    require(rows and len(rows) <= 1000000, 'Missing or oversized numeric table')
    shape = re.search(r'Matrix\(\s*(\d+)\s*x\s*(\d+)\s*\)', text)
    if shape:
        require(int(shape[1]) == len(rows) and int(shape[2]) == columns, 'Native matrix declared shape differs')
    if text.startswith('groops instrument'):
        counts = [int(line.strip()) for line in text.splitlines() if line.strip().isdigit()]
        require(len(counts) == 1 and counts[0] == len(rows), 'Native instrument epoch count differs')
    return rows


def position_maximum(coarse, fine, offgrid=False):
    require(len({r[0] for r in coarse}) == len(coarse), 'Duplicate coarse epoch')
    require(len({r[0] for r in fine}) == len(fine), 'Duplicate fine epoch')
    if offgrid:
        require([r[0] for r in coarse] == [r[0] for r in fine], 'Off-grid support differs')
    fine_index = {r[0]: r for r in fine}
    require(all(r[0] in fine_index for r in coarse), 'Fine grid omits coarse epochs')
    return max(math.sqrt(sum((r[j]-fine_index[r[0]][j])**2 for j in (1, 2, 3))) for r in coarse)


def signal_metrics(a, b, support_a, support_b):
    require(len(a) == len(b) and support_a == support_b, 'Signal support differs')
    require(all(x[:4] == y[:4] and x[6:] == y[6:] for x, y in zip(a, b)), 'Signal identity or fixed nuisance changed')
    require(sorted({r[6] for r in a}) == sorted([5e-8, -5e-8, 5e-6, -5e-6, 2e-5, -2e-5]), 'Clock-offset inventory differs')
    require(all(r[5] > 0 for r in a+b), 'Invalid native sigma')
    result = []
    for phase, label, sigma in ((0, 'code', .3), (1, 'carrier', .003)):
        for frequency in (1575420000., 1227600000.):
            pairs = [(x, y) for x, y in zip(a, b) if x[3] == phase and x[2] == frequency]
            require(pairs, 'Missing dual-frequency code/phase component')
            differences = [abs(x[4]-y[4]) for x, y in pairs]
            fractions = [d/min(x[5], sigma) for d, (x, _) in zip(differences, pairs)]
            result.append(dict(observable=label, frequency_hz=frequency, rows=len(pairs),
                               assumed_sigma_m=sigma, maximum_difference_m=max(differences),
                               maximum_fraction_of_sigma=max(fractions), passed=all(x < .01 for x in fractions)))
    return result


def refinement(reader, stage, root, value, original):
    flight = stage == 'flight-refinement'
    script = 'validate_numerics_flight_refinement.py' if flight else 'validate_numerics_synthetic_refinement.py'
    require(value['status'] == 'complete' and value['passed'] is True, 'Refinement result failed')
    require(value['schema'] == ('flight-staged-refinement-3.1' if flight else 'synthetic-staged-refinement-3.1'), 'Refinement schema differs')
    require(value['binary_sha256'] == NATIVE_SHA and value['diagnostic_source_sha256'] == SCRIPT_SHA[script], 'Refinement runtime/source differs')
    require(value['signal_diagnostic_source_sha256'] == SCRIPT_SHA['numerics_refinement_helpers.py'], 'Signal source differs')
    if not flight:
        require(value['case'] == original['case'] and value['method'] == original['method'], 'Synthetic case substituted')
        require(value['state_grid_seconds'] == [5., 2.5], 'Synthetic refinement grids changed')
    else:
        require(value['duration_seconds'] == 1800. and value['start_utc_seconds'] == 42300.
                and value['source_preparation_sha256'] == INPUT_SHA['flight_prepared'], 'Flight window/input substituted')
        controls = value['controls']
        require(controls['coarse']['state_seconds'] == 5. and controls['fine']['state_seconds'] == 2.5, 'Flight state grids changed')
        require(controls['fine']['atmosphere_seconds'] == controls['coarse']['atmosphere_seconds']/2, 'Atmosphere refinement differs')
        require(controls['fine']['thermal_seconds'] == [x/2 for x in controls['coarse']['thermal_seconds']], 'Thermal refinement differs')
    metrics = {}
    for filename, metric, offgrid in (('fixed_orbit.txt', 'aligned_position_maximum_m', False),
                                       ('offgrid_orbit.txt', 'offgrid_position_maximum_m', True)):
        a, b = [reader.table(root/side/filename, 10) for side in ('coarse', 'fine')]
        if not offgrid:
            duration = 1800. if flight else original['case']['duration_hours']*3600.
            # Synthetic coarse preparation excludes its terminal epoch; the
            # diagnostic resampler and flight crop include theirs. This is the
            # actual native archived convention, not a shortened replacement.
            require(len(a) == int(duration/5.)+int(flight) and len(b) == int(duration/2.5)+1, 'Refinement duration/grid inventory differs')
        metrics[metric] = position_maximum(a, b, offgrid)
        require(metrics[metric] < 3e-5 and close(metrics[metric], value['metrics'][metric]), 'Position refinement predicate/arithmetic differs')
    a, b = [reader.table(root/side/'predictions/signals.txt', 8) for side in ('coarse', 'fine')]
    supports = [reader.raw(root/side/'predictions/signal_support.txt') for side in ('coarse', 'fine')]
    signals = signal_metrics(a, b, *supports)
    recorded = value['native_signals']['signals']
    require(len(recorded) == 4, 'Signal summary inventory differs')
    for actual, saved in zip(signals, recorded):
        for key in ('observable', 'frequency_hz', 'rows', 'assumed_sigma_m', 'passed'):
            require(actual[key] == saved[key], 'Signal summary differs: ' + key)
        for key in ('maximum_difference_m', 'maximum_fraction_of_sigma'):
            require(close(actual[key], saved[key]), 'Signal arithmetic differs: ' + key)
        require(actual['passed'], 'Signal noise-fraction gate failed')
    # Bind the actual XML used for every saved off-grid and signal computation.
    for side in ('coarse', 'fine'):
        for relative, label in ((Path(side), 'offgrid'), (Path(side)/'predictions', 'predict_signals')):
            execution = reader.json(root/relative/(label+'.execution.json'))
            require(execution['returncode'] == 0 and execution['timed_out'] is False and execution['native_binary_sha256'] == NATIVE_SHA, 'Saved native prediction invocation failed')
            require(execution['command'][-1] == str(root/relative/(label+'.xml')), 'Prediction XML path differs')
            reader.raw(root/relative/(label+'.xml'), execution['config_sha256'])
    return {'recomputed_metrics': metrics, 'recomputed_signals': signals,
            'limits': 'position <30 micrometres; every signal <1% of min(coarse native sigma, prescribed noise)',
            'unavailable': ['Independent physical force reconstruction and full closure history are outside this saved prediction audit.']}


def derivative_arithmetic(value):
    require(value['relative_derivative_tolerance'] == 1e-4, 'Derivative tolerance changed')
    require(value['derivative_refinement_policy'] == {'maximum_scales': 9, 'ratio': .5,
            'required_consecutive_passing_scales': 2, 'physical_repeat_allowance_multiplier': 10}, 'Derivative policy changed')
    rows = value['directional_derivatives']
    require(2 <= len(rows) <= 9, 'Wrong perturbation count')
    physical = value['empirical_physical_objective_resolution']
    require(number(physical) and number(value['objective_repeat_difference']) and value['objective_repeat_difference'] >= 0
            and physical == 10*value['objective_repeat_difference'], 'Physical repeat allowance differs from producer arithmetic')
    base_derivative = rows[0]['native_derivative']
    streak, calculations = [], []
    for i, row in enumerate(rows):
        scale = row['scale']
        require(scale == .5**i, 'Scales missing/reordered')
        neg, pos, native = [row[k] for k in ('negative_cost', 'positive_cost', 'native_derivative')]
        require(all(number(x) for x in (neg, pos, native)), 'Nonfinite derivative endpoint')
        require(native == base_derivative, 'Directional scales do not share the same base derivative')
        checks = row['endpoint_resolution_checks']
        require(len(checks) == 2 and {x['sign'] for x in checks} == {-1, 1}, 'Wrong endpoint inventory')
        for endpoint in checks:
            cost = neg if endpoint['sign'] == -1 else pos
            difference = abs(cost-endpoint['repeat_cost'])
            require(close(difference, endpoint['repeat_difference']) and number(endpoint['empirical_resolution'])
                    and endpoint['empirical_resolution'] >= max(physical, 10*difference), 'Endpoint repeat allowance differs')
        finite = (pos-neg)/(2*scale)
        denominator = max(abs(finite), abs(native), 1e-12)
        error = abs(finite-native)/denominator + sum(x['empirical_resolution'] for x in checks)/(2*scale*denominator)
        passed = error <= 1e-4
        require(row['passes_unchanged_tolerance'] is passed and close(error, row['relative_difference_plus_resolution'])
                and close(finite, row['finite_difference']), 'Derivative arithmetic differs')
        streak = streak+[scale] if passed else []
        calculations.append({'scale': scale, 'finite_difference': finite, 'error_plus_resolution': error, 'passed': passed})
    require(len(streak) >= 2 and value['accepted_derivative_scales'] == streak[-2:], 'No two consecutive passing scales')
    return calculations


def prior_residuals(density, parameters, force, epochs=None):
    if not density:
        return [-x/(parameters['sigma_velocity_m_s']*1e6) for x in force]
    sigma, tau = parameters['sigma_log_density'], parameters['tau_seconds']
    require(len(epochs) == len(force), 'Density knot inventory differs')
    expected = [-force[0]/sigma]
    for i in range(1, len(force)):
        dt = (epochs[i]-epochs[i-1])*86400.
        require(dt > 0, 'Non-increasing knot times')
        expected.append(-(force[i]-math.exp(-dt/tau)*force[i-1])/(sigma*math.sqrt(-math.expm1(-2*dt/tau))))
    return expected


def full_factor_metadata(info, diagnostic):
    """Mirror require_full_native_factor's saved metadata, not a new SVD."""
    required_fields(info, ('schema', 'rows', 'columns', 'local_global_indices',
                          'retained_global_indices'), 'Full factor')
    required_fields(diagnostic, ('schema', 'rank_status', 'lambda', 'rank',
                                'retained_parameters'), 'Full-factor diagnostic')
    columns = info['columns']
    local, retained = info['local_global_indices'], info['retained_global_indices']
    require(info['schema'] == 'orbit-poc-qr-factor-v1'
            and diagnostic['schema'] == 'orbit-poc-native-qr-v1'
            and diagnostic['rank_status'] == 'full'
            and type(diagnostic['lambda']) in (int, float) and diagnostic['lambda'] == 0
            and type(columns) is int and columns > 0
            and type(info['rows']) is int and info['rows'] == columns
            and type(diagnostic['rank']) is int and diagnostic['rank'] == columns
            and type(diagnostic['retained_parameters']) is int and diagnostic['retained_parameters'] == columns
            and isinstance(local, list) and all(type(x) is int for x in local)
            and all(value == index for index, value in enumerate(local))
            and isinstance(retained, list) and all(type(x) is int for x in retained)
            and len(retained) == columns
            and all(value == len(local)+index for index, value in enumerate(retained))
            and info.get('full_rank_certificate') is not False
            and info.get('covariance_authority') is not False,
            'Full original-coordinate undamped factor metadata differs')


def endpoint_qualification(profile, evaluation):
    """Check saved strict/floor predicates; do not turn a floor into convergence."""
    flags = ('nuisance_converged', 'nuisance_floor_limited')
    required_fields(profile, flags, 'Endpoint profile')
    required_fields(evaluation, (*flags, 'empirical_objective_resolution'), 'Endpoint summary')
    require(all(type(profile[k]) is bool and type(evaluation[k]) is bool for k in flags)
            and all(profile[k] is evaluation[k] for k in flags), 'Endpoint convergence qualification differs')
    strict, limited = [profile[k] for k in flags]
    require(strict != limited, 'Endpoint requires exactly one strict or floor-limited qualification')
    if strict:
        # An absent flag is unknown evidence, not a proof that a conditional
        # solve did not occur. Present false preserves the producer's full path.
        required_fields(profile, ('conditional_nuisance_qr',), 'Strict endpoint')
        require(type(profile['conditional_nuisance_qr']) is bool, 'Invalid conditional nuisance qualification')
        if profile['conditional_nuisance_qr']:
            required_fields(profile, ('threshold_m', 'fresh_full_nuisance_confirmed',
                'fresh_full_nuisance_update_m', 'required_consecutive_small_updates', 'history'), 'Strict conditional endpoint')
            history, change = profile['history'], profile['fresh_full_nuisance_update_m']
            require(number(profile['threshold_m']) and profile['threshold_m'] == 1e-8
                    and profile['fresh_full_nuisance_confirmed'] is True
                    and number(change) and 0 <= change < 1e-8
                    and profile['required_consecutive_small_updates'] == 2
                    and isinstance(history, list) and len(history) >= 2,
                    'Strict endpoint lacks fresh full-system confirmation')
            for row in history[-2:]:
                required_fields(row, ('maximum_update_m',), 'Strict final update')
                require(number(row['maximum_update_m']) and 0 <= row['maximum_update_m'] < 1e-8,
                        'Strict endpoint final updates differ')
        resolution, qualification = 0., 'strict'
    else:
        required_fields(profile, ('nuisance_objective_resolution', 'nuisance_predicted_reduction',
            'nuisance_floor_audit', 'nuisance_floor_policy'), 'Floor-limited endpoint')
        resolution, potential = profile['nuisance_objective_resolution'], profile['nuisance_predicted_reduction']
        audits = profile['nuisance_floor_audit']
        require(number(resolution) and number(potential) and 0 < potential <= resolution
                and profile['nuisance_floor_policy'] == 'empirical_equivalent_arithmetic_and_symmetric_probes_v1'
                and isinstance(audits, list) and len(audits) == 4
                and all(isinstance(row, dict) for row in audits), 'Floor-limited policy or resolution differs')
        for row in audits:
            required_fields(row, ('kind', 'success', 'support_unchanged'), 'Saved floor audit')
            require(row['success'] is True and row['support_unchanged'] is True, 'Saved floor audit failed')
            if row['kind'] == 'equivalent_arithmetic':
                required_fields(row, ('mode',), 'Saved arithmetic floor audit')
        for mode in (1, 2, 3):
            require(sum(row['kind'] == 'equivalent_arithmetic' and type(row.get('mode')) is int
                        and row['mode'] == mode for row in audits) == 1, 'Floor arithmetic mode inventory differs')
        probes = [row for row in audits if row['kind'] == 'two_amplitude_symmetric_nuisance_probe']
        require(len(probes) == 1, 'Floor symmetric-probe inventory differs')
        probe = probes[0]
        fields = ('probes', 'empirical_quadratic_potential', 'half_empirical_quadratic_potential',
                  'empirical_quadratic_potential_with_allowance', 'half_empirical_quadratic_potential_with_allowance')
        required_fields(probe, fields, 'Saved floor symmetric probe')
        require(isinstance(probe['probes'], list) and len(probe['probes']) == 4, 'Floor probe count differs')
        require(all(number(probe[k]) and 0 < probe[k] <= resolution for k in fields[1:]), 'Floor probe potential differs')
        qualification = 'floor_limited_saved_policy_predicates_only'
    require(number(evaluation['empirical_objective_resolution'])
            and evaluation['empirical_objective_resolution'] == resolution, 'Endpoint native resolution differs')
    return {'qualification': qualification, 'empirical_objective_resolution': resolution,
            'independent_floor_proof': False, 'covariance_authority': False}


def prior_row_archive(compressed, source):
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        row_bytes = stream.read(MAX_BYTES+1)
    require(len(row_bytes) <= MAX_BYTES and digest(row_bytes) == source['sha256']
            and len(row_bytes) == source['bytes'], 'Prior row archive round trip differs')
    return row_bytes


def objective(reader, stage, root, value, original):
    density = stage.endswith('log_drag_ou')
    require(value['passed'] is True and value['native_binary_sha256'] == NATIVE_SHA, 'Objective check failed')
    source = reader.json(root/'source.json')
    source_hash = digest(json.dumps(source['files'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    require(source['sha256'] == source_hash == value['source_hash'], 'Actual source-snapshot identity differs')
    candidate = reader.json(SOURCE.parent/'source-snapshot.json', SNAPSHOT_SHA)
    candidate_files = {x['relative_path']: x['sha256'] for x in candidate['files']}
    suffixes = {'.py', '.cpp', '.h', '.hpp', '.sh', '.xml', '.json', '.yaml', '.yml', '.txt'}
    roots = ('src/', 'scripts/', 'groops/extension/', 'groops/templates/', 'configs/')
    standalone = {'pyproject.toml', 'tudat-linux-64.lock.txt', 'groops/linux-64.lock.txt', 'groops/python-requirements.lock.txt'}
    expected_files = {k: v for k, v in candidate_files.items()
                      if (k.startswith(roots) and Path(k).suffix in suffixes) or k in standalone}
    require(source['files'] == expected_files, 'Objective source snapshot membership/bytes differ')
    actual_request = reader.json(root/'request.json')
    expected_request = dict(original)
    expected_request.update(preparation_source_hash=original['source_hash'], source_hash=source_hash,
                            expected_native_binary_sha256=NATIVE_SHA,
                            backend={**original['backend'], 'groops_executable': NATIVE_PATH})
    require(actual_request == expected_request, 'Objective request changed beyond prescribed runtime/source rebinding')
    require(value['initialization_policy'] == 'preserved_blind_engineering_initial_state'
            and value['state_input']['sha256'] == INPUT_SHA['initial_state'], 'Objective initialization substituted')
    reader.pin(value['state_input'])
    calculations = derivative_arithmetic(value)
    points = reader.manifest['objective_points'][stage]
    evaluations = value['profile_evaluations']
    require(len(points) == len(evaluations) == 2+4*len(calculations), 'Missing endpoint attribution')
    actual, qualifications = {}, []
    for spec, evaluation in zip(points, evaluations):
        require(spec['label'] == evaluation['label'] and spec['profile'] == evaluation['receipt'], 'Endpoint order/path differs')
        folder = Path(spec['profile']).parent
        require(folder.parent == root and folder.name.startswith('point-'), 'Foreign objective point')
        stem = Path(spec['factor_prefix'])
        require(stem.parent == folder and re.fullmatch(r'qr\.[1-9][0-9]*', stem.name), 'Foreign factor prefix')
        profile = reader.json(spec['profile'])
        info = reader.json(str(stem)+'.factor.json')
        diagnostic = reader.json(str(stem)+'.diagnostics.json')
        cost = reader.json(str(stem)+'.profile.json')
        full_factor_metadata(info, diagnostic)
        require(cost['direct_cost'] == evaluation['objective'], 'Endpoint objective differs from saved direct cost')
        qualifications.append({'label': evaluation['label'], **endpoint_qualification(profile, evaluation)})
        actual[evaluation['label']] = evaluation
    require(close(abs(actual['nonzero-full-prior']['objective']-actual['repeat']['objective']), value['objective_repeat_difference']), 'Fixed-point repeat differs')
    for row in value['directional_derivatives']:
        for sign, key in ((-1, 'negative_cost'), (1, 'positive_cost')):
            label = f"direction-{float(row['scale'])}-{sign}"
            require(actual[label]['objective'] == row[key], 'Directional objective point differs')
            endpoint = next(x for x in row['endpoint_resolution_checks'] if x['sign'] == sign)
            require(actual[label+'-repeat']['objective'] == endpoint['repeat_cost'], 'Repeat objective point differs')
            resolution = max(value['empirical_physical_objective_resolution'], 10*endpoint['repeat_difference']) + max(actual[label]['empirical_objective_resolution'], actual[label+'-repeat']['empirical_objective_resolution'])
            require(close(resolution, endpoint['empirical_resolution']), 'Empirical endpoint resolution not reconstructed')
    first = points[0]
    folder, stem = Path(first['profile']).parent, first['factor_prefix']
    if density:
        knots = reader.table(folder/'native/log_density.txt', 2)
        epochs, force = [r[0] for r in knots], [r[1] for r in knots]
    else:
        vector = [r[0] for r in reader.table(folder/'fixed_force.txt', 1)]
        require(len(vector) == 12 and vector[-6:] == [0.]*6, 'Pulse vector native ordering differs')
        epochs, force = None, vector[:6]
    expected = prior_residuals(density, original['parameters'], force, epochs)
    compression = reader.json(stem+'.rows.tsv.compression.json')
    compressed = reader.pin(compression['compressed'])
    row_bytes = prior_row_archive(compressed, compression['source'])
    label = 'constraint.logDensityOu' if density else 'constraint.pulses'
    observed = [float(row['rhs']) for row in csv.DictReader(io.StringIO(row_bytes.decode()), delimiter='\t') if row['source'] == label]
    require(len(observed) == len(expected) == (61 if density else 6), 'Full prior row count differs')
    discrepancy = max(abs(a-b) for a, b in zip(observed, expected))
    tolerance = 2e-8 if density else 1e-12
    cost = .5*sum(x*x for x in expected)
    prior = value['prior']
    require(discrepancy <= tolerance and 0 < cost <= actual['nonzero-full-prior']['objective'], 'Nonzero full prior fails')
    require(prior['absolute_tolerance'] == tolerance and prior['source'] == label and prior['rows'] == len(expected)
            and close(cost, prior['cost']), 'Prior cost/identity differs')
    return {'derivatives': calculations, 'recomputed_prior_cost': cost, 'recomputed_prior_residual_difference': discrepancy,
            'endpoint_count': len(points), 'floor_limited_endpoints': [x['label'] for x in evaluations if x['nuisance_floor_limited']],
            'endpoint_qualifications': qualifications,
            'unavailable': UNAVAILABLE[2:5]}


def xml(raw):
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'XML entities forbidden')
    return ET.fromstring(raw)


def replay_predicates(value):
    p = value['profile']
    require(value['passed'] is True and value['returncode'] == 0 and value['timed_out'] is False
            and value['strict_nuisance_converged'] is True and value['progress_only_floor_validated'] is False, 'Replay did not strictly converge')
    require(p['threshold_m'] == 1e-8 and p['required_consecutive_small_updates'] == 2
            and p['nuisance_converged'] is True and p['nuisance_floor_limited'] is False
            and p['fixed_weights'] is True and p['dynamic_updates'] is False, 'Replay policy differs')
    history, searches = p['history'], value['searches']
    require(len(searches) == len(history) >= 2, 'Replay search inventory incomplete')
    require(all(number(x['maximum_update_m']) and 0 <= x['maximum_update_m'] < 1e-8 for x in history[-2:])
            and p['maximum_update_m'] == history[-1]['maximum_update_m'], 'Missing consecutive strict updates')
    signatures, crossings = set(), 0
    for i, search in enumerate(searches):
        zero = search['zero_update_replay']
        require(search['generation'] == i+1 and zero['status'] == 0 and zero['actual_reduction'] == 0
                and zero['maximum_update_m'] == 0 and zero['cost'] == search['objective_before'], 'Non-exact zero replay')
        for trial in search['trials']:
            if trial['status'] == 0:
                signatures.add(trial.get('observation_signature'))
                crossings += trial.get('ambiguity_half_integer_crossings', 0)
    require(len(signatures) == 1 and None not in signatures and '0' not in signatures and crossings > 0, 'Replay support/crossing evidence fails')
    for search in searches[-2:]:
        require(search['stationary_without_update'] is True and search['nuisance_floor_limited'] is False
                and number(search['undamped_maximum_update_m']) and 0 <= search['undamped_maximum_update_m'] < 1e-8, 'Final replay search not strict')
    require(value['zero_update_replay_exact'] is True and value['fixed_observations_and_weights_verified_every_trial'] is True
            and value['ambiguity_half_integer_crossings_tested'] == crossings, 'Replay summary contradicts transactions')
    return {'raw_update_m': p['maximum_update_m'], 'successful_observation_signatures': sorted(signatures),
            'ambiguity_half_integer_crossings': crossings, 'generations': len(searches)}


def replay(reader, stage, root, value, inputs):
    prefix = 'old' if stage == 'nuisance-replay' else 'new'
    role = 'old_nuisance_replay' if prefix == 'old' else 'candidate1_nuisance_replay'
    require(value['schema'] == 'orbit-poc-native-nuisance-validation-v1' and value['native_sha256'] == NATIVE_SHA
            and value['native_unchanged'] is True and value['source_profile_sha256'] == INPUT_SHA[role], 'Replay native/original identity differs')
    source = xml(reader.pin(inputs[role]))
    executed = xml(reader.raw(root/'profile.xml', value['replay_profile_sha256']))
    for tag, name in (('inputfileVariational', 'variational'), ('inputfileNumericsReferenceParameters', 'reference'), ('inputfileLogDensity', 'density')):
        item = inputs[prefix+'_replay_'+name]
        reader.pin(item)
        before = [(n.text or '').strip() for n in source.iter(tag)]
        after = [(n.text or '').strip() for n in executed.iter(tag)]
        require(before and before == after, 'Replay physical execution paths changed')
        require(item['sha256'] == INPUT_SHA[prefix+'_replay_'+name], 'Replay physical bytes substituted')
    require(reader.json(root/'qr.profile.json') == value['profile'], 'Replay final profile summary differs')
    for search in value['searches']:
        raw = reader.json(root/f"qr.{search['generation']}.nuisance_line_search.json", search['sha256'])
        require(raw == {k: v for k, v in search.items() if k not in ('generation', 'sha256')}, 'Replay search summary differs')
    result = replay_predicates(value)
    result['physical_input_sha256'] = {name: INPUT_SHA[prefix+'_replay_'+name] for name in ('density', 'reference', 'variational')}
    result['original_profile_sha256'] = INPUT_SHA[role]
    return result


def classify(row):
    if row is None:
        return 'missing'
    if row.get('status') == 'not_executed_or_interrupted_without_receipt':
        return 'not_executed_or_unverified'
    if row.get('status') != 'passed':
        return 'recorded_'+str(row.get('status', 'unknown'))
    return 'candidate_for_saved_output_audit'


def empty_report():
    return {'schema': 'candidate06-scientific-terminal-audit-v1', 'audit_revision': 2,
              'approval': False, 'approved': False,
              'release_authority': False, 'covariance_authority': False, 'comprehensive_audit': False,
              'planned_stages': list(STAGES), 'scientific_stages': list(SCIENTIFIC),
              'stages': [{'stage': s, 'status': 'not_audited'} for s in SCIENTIFIC],
              'errors': [], 'unavailable': list(UNAVAILABLE), 'read_file_pins': {},
              'all_eight_saved_predicates_passed': False}


def audit(reader):
    result = empty_report()
    try:
        plan = reader.json(RUN/'plan.json', PLAN_SHA)
        freeze = reader.json(RUN/'freeze.json', FREEZE_SHA)
        require(plan['stages'] == list(STAGES) and [j['stage'] for j in plan['jobs']] == list(STAGES), 'Plan order differs')
        require(freeze['plan']['sha256'] == PLAN_SHA and plan['candidate_source']['sha256'] == SNAPSHOT_SHA
                and plan['runtime']['native']['sha256'] == NATIVE_SHA, 'Reference identity differs')
        reader.pin(plan['candidate_source'])
        reader.pin(plan['runtime']['native'])
        inputs = decode(reader.pin(freeze['validation_inputs']))['input_artifacts']
        require(set(inputs) == set(INPUT_SHA), 'Original fourteen-input inventory differs')
        for role, item in inputs.items():
            require(item['sha256'] == INPUT_SHA[role], 'Original input substituted: '+role)
            reader.pin(item)
        for filename, sha in SCRIPT_SHA.items():
            reader.raw(SOURCE/'scripts'/filename, sha)
        sequence = reader.json(BASE/'density-trial-sequence02/result.json')
        require(sequence['plan_sha256'] == SEQ_SHA and sequence['status'] in ('complete', 'failed', 'interrupted'), 'Sequence is not terminal or is foreign')
        aggregate = reader.json(RUN/'result.json')
        require(aggregate['plan']['sha256'] == PLAN_SHA and aggregate['freeze']['sha256'] == FREEZE_SHA, 'Aggregate identity differs')
        require([x['stage'] for x in aggregate['stages']] == list(STAGES), 'Terminal aggregate inventory differs')
        result['recorded_all_eleven_strict_passed'] = aggregate.get('all_eleven_strict_passed')
        by_stage = {x['stage']: x for x in aggregate['stages']}
        for record, job in zip(result['stages'], plan['jobs'][3:]):
            stage, row = job['stage'], by_stage[job['stage']]
            record.update(recorded_status=row.get('status'), status=classify(row))
            if record['status'] != 'candidate_for_saved_output_audit':
                continue
            try:
                require(row['plan']['sha256'] == PLAN_SHA and row['freeze']['sha256'] == FREEZE_SHA, 'Stage plan/freeze identity differs')
                strict = decode(reader.pin(row['strict_result']))
                require(strict['stage'] == stage and strict['argv'] == job['argv'] and strict['status'] == 'passed'
                        and strict['returncode'] == 0, 'Strict stage status/argv differs')
                root = RUN/stage/'result'
                evidence = strict['evidence']['result']
                name = 'result.json' if 'refinement' in stage else 'validation.json' if stage.startswith('objective-') else 'receipt.json'
                require(evidence['path'] == str(root/name), 'Foreign scientific result')
                value = decode(reader.pin(evidence))
                if stage.startswith('nuisance-replay'):
                    details = replay(reader, stage, root, value, inputs)
                else:
                    role = 'flight_prepared' if stage == 'flight-refinement' else 'full_day_request' if stage == 'eccentric-24h-refinement' else 'density_request' if stage.endswith('log_drag_ou') else 'pulse_request'
                    original = decode(reader.pin(inputs[role]))
                    if 'refinement' in stage:
                        if stage != 'flight-refinement':
                            require(value['request_sha256'] == INPUT_SHA[role], 'Refinement request identity differs')
                        details = refinement(reader, stage, root, value, original)
                    else:
                        details = objective(reader, stage, root, value, original)
                record.update(status='saved_predicates_passed', details=details)
            except Missing as error:
                record.update(status='incomplete_saved_evidence', error=error_text(error))
            except EVIDENCE_ERRORS as error:
                record.update(status='audit_discrepancy', error=error_text(error))
    except EVIDENCE_ERRORS as error:
        result['errors'].append(error_text(error))
    result['all_eight_saved_predicates_passed'] = not result['errors'] and all(x['status'] == 'saved_predicates_passed' for x in result['stages'])
    result['read_file_pins'] = reader.used
    return result


def audit_manifest(path, expected_hash):
    result = empty_report()
    result['requested_terminal_manifest_sha256'] = expected_hash
    try:
        # Unlike Path.read_bytes(), this bounds input allocation even if a
        # manifest grows between checking its metadata and reading its bytes.
        with path.open('rb') as stream:
            raw = stream.read(MAX_BYTES+1)
        require(len(raw) <= MAX_BYTES, 'Terminal manifest exceeds audit file bound')
        actual_hash = digest(raw)
        result['terminal_manifest_sha256'] = actual_hash
        require(actual_hash == expected_hash, 'Terminal manifest hash differs')
        result = audit(Reader(decode(raw)))
        result['requested_terminal_manifest_sha256'] = expected_hash
        result['terminal_manifest_sha256'] = actual_hash
    except EVIDENCE_ERRORS as error:
        result['errors'].append(error_text(error))
        result['all_eight_saved_predicates_passed'] = False
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--terminal-manifest', type=Path, required=True)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit_manifest(args.terminal_manifest, args.manifest_sha256)
    try:
        result['auditor_sha256'] = digest(Path(__file__).read_bytes())
    except EVIDENCE_ERRORS as error:
        result['errors'].append(error_text(error))
        result['all_eight_saved_predicates_passed'] = False
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
    return 0 if result['all_eight_saved_predicates_passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
