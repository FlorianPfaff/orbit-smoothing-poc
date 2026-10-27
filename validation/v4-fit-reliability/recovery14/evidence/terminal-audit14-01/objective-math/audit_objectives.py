#!/usr/bin/env python3
"""Read-only recalculation of run14's two objective gates; no native execution.

Writes only to this audit directory. Saved profile results are evidence, not
instructions. No project implementation is imported by the independent math.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import io
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np

ROOT = Path('/mnt/d/orbit-v41-recovery02/reference-gates14-run01')
SOURCE = Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
OUT = Path(__file__).resolve().parent
BINARY_HASH = '28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
SOURCE_HASH = 'f7e8e79b7cd8061142504bc9cb94476ad41cb19d6d582a14e4f8bb7fb07ce680'
PYTHON_HASH = '58f0ee5f4cb0af42a69aed9f122d63cc535fcfa6bca71132a3d0e24be95c4ac8'
evidence = {}
checks = []

def pin(path):
    path = Path(path)
    if str(path) not in evidence:
        raw = path.read_bytes()
        evidence[str(path)] = {'path': str(path), 'bytes': len(raw),
                               'sha256': hashlib.sha256(raw).hexdigest()}
    return evidence[str(path)]

def read(path):
    pin(path)
    return json.loads(Path(path).read_text())

def check(name, passed, **detail):
    checks.append({'name': name, 'passed': bool(passed), **detail})

def close(a, b):
    # Audit arithmetic comparison only; never changes any scientific limit.
    return math.isclose(a, b, rel_tol=2e-13, abs_tol=2e-12)

def matrix(path):
    pin(path)
    return np.loadtxt(path, skiprows=2)

def table(path):
    pin(path)
    return list(csv.DictReader(Path(path).read_text().splitlines(), delimiter='\t'))

def method_audit(method):
    label = 'objective-' + method
    root = ROOT / label / 'result'
    validation = read(root / 'validation.json')
    request = read(root / 'request.json')
    source = read(root / 'source.json')
    params = request['parameters']
    check(label + ': immutable scientific identity',
          validation['source_hash'] == source['sha256'] == SOURCE_HASH and
          validation['native_binary_sha256'] == request['expected_native_binary_sha256'] == BINARY_HASH and
          request['stage'] == 'synthetic' and request['split'] == 'engineering' and
          request['numerics_profile'] == 'qr_lm_staged_jacobian' and request['method'] == method)
    for filename in ['scripts/validate_numerics_objective.py',
                     'src/orbit_poc/numerics/backend.py',
                     'groops/extension/gnssProcessingStepOrbitPocNumerics.h']:
        item = pin(SOURCE / filename)
        check(label + ': source ' + filename, item['sha256'] == source['files'][filename])
    check(label + ': unchanged derivative policy',
          validation['relative_derivative_tolerance'] == 1e-4 and
          validation['derivative_refinement_policy'] == {
              'maximum_scales': 9, 'physical_repeat_allowance_multiplier': 10,
              'ratio': .5, 'required_consecutive_passing_scales': 2})
    state_pin = pin(validation['state_input']['path'])
    check(label + ': preserved blind physical initialization',
          state_pin['sha256'] == validation['state_input']['sha256'])
    evaluations = {}
    initial_preprocessing = None
    initial_parameter_support = None
    for exported in validation['profile_evaluations']:
        folder = Path(exported['receipt']).parent
        check(label + ':' + exported['label'] + ': fresh run14 output',
              folder.parent == root and folder.name.startswith('point-'))
        receipt = read(folder / 'qr.profile.json')
        factor_paths = sorted(folder.glob('qr.*.factor.json'), key=lambda p: int(p.name.split('.')[1]))
        prefix = str(factor_paths[-1]).removesuffix('.factor.json')
        info = read(prefix + '.factor.json')
        diagnostics = read(prefix + '.diagnostics.json')
        costs = read(prefix + '.profile.json')
        confirmation = read(prefix + '.nuisance_confirmation.json')
        closure = read(folder / 'closure.json')
        execution = read(folder / 'profile.execution.json')
        check(label + ':' + exported['label'] + ': native successful fixed-thread execution',
              execution['returncode'] == 0 and execution['timed_out'] is False and
              execution['blas_openmp_threads'] == 1 and
              execution['native_binary_sha256'] == BINARY_HASH and
              execution['config_sha256'] == pin(folder / 'profile.xml')['sha256'] and
              execution['command'][1] == str(folder / 'profile.xml'))
        strict = (receipt['nuisance_converged'] is True and
                  receipt['nuisance_floor_limited'] is False and
                  receipt['conditional_nuisance_qr'] is True and
                  receipt['fresh_full_nuisance_confirmed'] is True and
                  receipt['threshold_m'] == 1e-8 and
                  receipt['required_consecutive_small_updates'] == 2 and
                  0 <= receipt['fresh_full_nuisance_update_m'] < 1e-8 and
                  len(receipt['history']) >= 2 and
                  all(0 <= row['maximum_update_m'] < 1e-8 for row in receipt['history'][-2:]) and
                  receipt['fixed_weights'] is True and receipt['dynamic_updates'] is False and
                  receipt['nuisance_objective_resolution'] == 0 and
                  receipt['nuisance_floor_audit'] == [] and
                  confirmation['nuisance_floor_limited'] is False and
                  confirmation['undamped_maximum_update_m'] == receipt['fresh_full_nuisance_update_m'])
        check(label + ':' + exported['label'] + ': strict nuisance convergence', strict,
              final_two_updates_m=[x['maximum_update_m'] for x in receipt['history'][-2:]],
              fresh_full_update_m=receipt['fresh_full_nuisance_update_m'])
        final_closure = closure['iterations'][-1]
        check(label + ':' + exported['label'] + ': tighter physical closure',
              closure['converged'] is True and closure['tighter'] is True and
              final_closure['position_change_m'] < 2e-7 and
              final_closure['velocity_change_m_s'] < 3e-10 and
              closure['force_state_reset'] == 'fresh native process at every iteration',
              final_position_change_m=final_closure['position_change_m'],
              final_velocity_change_m_s=final_closure['velocity_change_m_s'])
        compression = read(prefix + '.rows.tsv.compression.json')
        compressed_pin = pin(prefix + '.rows.tsv.gz')
        raw = gzip.decompress(Path(prefix + '.rows.tsv.gz').read_bytes())
        check(label + ':' + exported['label'] + ': lossless row evidence',
              compressed_pin['sha256'] == compression['compressed']['sha256'] and
              len(raw) == compression['source']['bytes'] and
              hashlib.sha256(raw).hexdigest() == compression['source']['sha256'])
        rows = list(csv.DictReader(io.StringIO(raw.decode()), delimiter='\t'))
        row_cost = .5 * math.fsum(float(row['rhs'])**2 for row in rows)
        check(label + ':' + exported['label'] + ': independently summed row objective',
              close(row_cost, costs['direct_cost']) and costs['direct_cost'] == exported['objective'] and
              close(.5 * costs['profile_residual2'], costs['direct_cost']) and
              info['objective_residual_basis'] == 'original_weighted_rows_v1' and
              len(rows) == diagnostics['source_rows'] and diagnostics['lambda'] == 0,
              row_objective=row_cost, native_direct_objective=costs['direct_cost'],
              absolute_difference=abs(row_cost-costs['direct_cost']))
        if method == 'log_drag_ou':
            pin(folder / 'native/log_density.txt')
            data = np.loadtxt(folder / 'native/log_density.txt')
            force = data[:, 1]
            dt = np.diff(data[:, 0]) * 86400
            sigma, tau = params['sigma_log_density'], params['tau_seconds']
            expected = -np.r_[force[0]/sigma, (force[1:]-np.exp(-dt/tau)*force[:-1]) /
                             (sigma*np.sqrt(-np.expm1(-2*dt/tau)))]
            prior_source, prior_tolerance = 'constraint.logDensityOu', 2e-8
            check(label + ':' + exported['label'] + ': no duplicated stationary prior',
                  len(expected) == len(force) == 61 and len(dt) == 60 and
                  params['initial_prior'] == 'stationary_ou' and
                  params['empirical_acceleration'] is False)
        else:
            pin(folder / 'full_pulses_um_s.txt')
            force = np.loadtxt(folder / 'full_pulses_um_s.txt')
            expected = -force / (params['sigma_velocity_m_s'] * 1e6)
            prior_source, prior_tolerance = 'constraint.pulses', 1e-12
            check(label + ':' + exported['label'] + ': full native pulse reference',
                  np.array_equal(matrix(folder / 'fixed_force.txt')[:-6], force))
        actual = np.array([float(row['rhs']) for row in rows if row['source'] == prior_source])
        discrepancy = float(np.max(np.abs(actual-expected))) if actual.shape == expected.shape else math.inf
        prior_cost = .5 * float(expected @ expected)
        check(label + ':' + exported['label'] + ': full nonzero prior penalty',
              actual.shape == expected.shape and discrepancy <= prior_tolerance and
              prior_cost > 0 and costs['direct_cost'] >= prior_cost,
              prior_source=prior_source, rows=len(actual), full_parameter_prior_cost=prior_cost,
              maximum_rhs_difference=discrepancy, unchanged_tolerance=prior_tolerance)
        audit_file = folder / 'native/output/2024-04-24/preprocessing_audit.txt'
        preprocessing_hash = pin(audit_file)['sha256']
        parameter_rows = table(prefix + '.parameters.tsv')
        parameter_support = [{k:v for k,v in row.items() if k != 'scale'} for row in parameter_rows]
        if initial_preprocessing is None:
            initial_preprocessing, initial_parameter_support = preprocessing_hash, parameter_support
        check(label + ':' + exported['label'] + ': fixed observations weights arcs parameter support',
              preprocessing_hash == initial_preprocessing and parameter_support == initial_parameter_support)
        singular_path = prefix + '.singular_values.txt'
        pin(singular_path)
        singular = np.loadtxt(singular_path)
        threshold = np.finfo(float).eps * max(diagnostics['reduced_rows'], info['columns']) * max(singular)
        check(label + ':' + exported['label'] + ': undamped full statistical rank',
              len(singular) == info['columns'] and min(singular) > 10*threshold and
              close(threshold, diagnostics['rank_threshold']) and diagnostics['rank_status'] == 'full' and
              diagnostics['rank'] == info['columns'],
              minimum_singular_value=float(min(singular)), rank_threshold=float(threshold))
        evaluations[exported['label']] = {
            'folder': str(folder), 'objective': costs['direct_cost'], 'prior_cost': prior_cost,
            'prior_rhs_max_difference': discrepancy, 'strict_nuisance': strict,
            'nuisance_floor_limited': receipt['nuisance_floor_limited'],
            'objective_resolution': receipt['nuisance_objective_resolution'],
            'fresh_full_update_m': receipt['fresh_full_nuisance_update_m'],
            'final_position_closure_m': final_closure['position_change_m'],
            'final_velocity_closure_m_s': final_closure['velocity_change_m_s'],
            'row_objective_difference': abs(row_cost-costs['direct_cost']),
            'force': force.tolist(), 'physical_initial': matrix(folder/'physical_initial.txt').tolist()}
    expected_count = 22 if method == 'log_drag_ou' else 10
    check(label + ': all evaluations accounted for', len(evaluations) == expected_count and
          len(list(root.glob('point-*'))) == expected_count)
    base, repeat = evaluations['nonzero-full-prior'], evaluations['repeat']
    repeat_difference = abs(base['objective']-repeat['objective'])
    resolution = 10*repeat_difference
    check(label + ': repeated identical physical state', base['force'] == repeat['force'] and
          base['physical_initial'] == repeat['physical_initial'])
    check(label + ': measured repeat allowance',
          repeat_difference == validation['objective_repeat_difference'] and
          resolution == validation['empirical_physical_objective_resolution'],
          repeat_difference=repeat_difference, empirical_physical_resolution=resolution)
    first_prior = validation['prior']
    check(label + ': base prior summary independently agrees',
          close(base['prior_cost'], first_prior['cost']) and
          close(base['prior_rhs_max_difference'], first_prior['max_rhs_difference']))
    derivatives = []
    streak = 0
    accepted = None
    for index, saved in enumerate(validation['directional_derivatives']):
        scale = .5 ** index
        endpoints, allowances = [], []
        for sign in (-1, 1):
            name = f'direction-{scale}-{sign}'
            point, repeated = evaluations[name], evaluations[name+'-repeat']
            check(label + ':' + name + ': repeat uses exact fixed physical parameters',
                  point['force'] == repeated['force'] and point['physical_initial'] == repeated['physical_initial'])
            difference = abs(point['objective']-repeated['objective'])
            allowance = max(resolution,10*difference)+max(point['objective_resolution'], repeated['objective_resolution'])
            endpoints.append(point['objective']); allowances.append(allowance)
            archived = saved['endpoint_resolution_checks'][0 if sign == -1 else 1]
            check(label + ':' + name + ': endpoint repeat allowance recomputed',
                  difference == archived['repeat_difference'] and allowance == archived['empirical_resolution'] and
                  repeated['objective'] == archived['repeat_cost'])
        finite_difference = (endpoints[1]-endpoints[0])/(2*scale)
        native = saved['native_derivative']
        denominator = max(abs(finite_difference),abs(native),1e-12)
        relative = abs(finite_difference-native)/denominator
        fraction = sum(allowances)/(2*scale*denominator)
        total = relative+fraction
        passed = total <= 1e-4
        streak = streak+1 if passed else 0
        if streak == 2 and accepted is None:
            accepted = [.5**(index-1),scale]
        check(label + f': scale {scale} independently recalculated acceptance',
              saved['scale'] == scale and saved['negative_cost'] == endpoints[0] and saved['positive_cost'] == endpoints[1] and
              close(finite_difference,saved['finite_difference']) and close(relative,saved['relative_difference']) and
              close(fraction,saved['empirical_resolution_fraction']) and
              close(total,saved['relative_difference_plus_resolution']) and
              saved['passes_unchanged_tolerance'] == passed,
              finite_difference=finite_difference, recorded_native_derivative=native,
              relative_difference=relative, empirical_resolution_fraction=fraction,
              total=total, unchanged_limit=1e-4, pass_at_scale=passed)
        derivatives.append({'scale':scale,'finite_difference':finite_difference,'recorded_native_derivative':native,
                            'relative_difference':relative,'empirical_resolution_fraction':fraction,
                            'total_error':total,'passes':passed,'margin_below_limit':1e-4-total})
    check(label + ': first two consecutive passing scales',
          accepted is not None and accepted == validation['accepted_derivative_scales'] and
          len(derivatives) <= 9 and accepted[-1] == derivatives[-1]['scale'])
    # Retention deliberately keeps the newest factor, so do not misrepresent
    # comparison against the archived native scalar as a fresh tangent solve.
    retention = read(root / 'factor-retention.json')
    missing_base = root/'point-001-nonzero-full-prior/qr.7.R.bin'
    removal = [item for event in retention['events'] for item in event.get('removed', [])
               if item.get('path') == str(missing_base)]
    check(label + ': base factor retention attribution', not missing_base.exists() and len(removal) == 1)
    return {'method':method,'parameters':params,'profile_count':len(evaluations),
            'strict_nuisance_count':sum(x['strict_nuisance'] for x in evaluations.values()),
            'floor_limited_count':sum(x['nuisance_floor_limited'] for x in evaluations.values()),
            'maximum_fresh_full_update_m':max(x['fresh_full_update_m'] for x in evaluations.values()),
            'maximum_position_closure_m':max(x['final_position_closure_m'] for x in evaluations.values()),
            'maximum_velocity_closure_m_s':max(x['final_velocity_closure_m_s'] for x in evaluations.values()),
            'maximum_row_objective_rounding_difference':max(x['row_objective_difference'] for x in evaluations.values()),
            'base_prior':{'cost':base['prior_cost'],'maximum_rhs_difference':base['prior_rhs_max_difference']},
            'base_objective':base['objective'],'repeat_difference':repeat_difference,'physical_resolution':resolution,
            'accepted_scales':accepted,'derivatives':derivatives,'evaluations':evaluations,
            'base_factor_removal':removal,
            'native_derivative_scope':'Recorded native directional derivative; base R was intentionally removed. Independently recomputed endpoint objectives, finite differences, repeat allowances, and acceptance. No second native tangent evaluation.'}

def main():
    check('pinned audit Python executable', pin(Path(sys.executable).resolve())['sha256'] == PYTHON_HASH)
    methods = [method_audit(method) for method in ('log_drag_ou','pulses')]
    # Check that every small evidence file used in this audit stayed fixed.
    initial_pins = list(evidence.values())
    changed = [item['path'] for item in initial_pins if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']]
    check('all accessed evidence unchanged during audit', not changed, changed_paths=changed)
    result = {'schema':'orbit-poc-independent-run14-objective-math-audit-v1',
              'created_utc':datetime.now(timezone.utc).isoformat(),
              'scope':'Read-only recalculation of two existing objective gates and all 32 saved profile evaluations; no native execution, nonlinear refit, or benchmark modification.',
              'passed':all(c['passed'] for c in checks), 'check_count':len(checks),
              'failed_checks':[c for c in checks if not c['passed']], 'methods':methods,
              'checks':checks,'evidence':initial_pins,'audit_script':pin(__file__),
              'limitations':[
                  'Recorded native directional derivatives cannot be independently rebuilt from removed base R factors; this audit recomputes the finite differences and unchanged gate arithmetic against their recorded values.',
                  'Weighted-row RHS dumps are binary64 diagnostics. Their summed cost agrees to recorded rounding; this is not a rerun of the native twofold/long-double measurement arithmetic.',
                  'Repeat differences under tighter closure are empirical physical objective resolution, not a rigorous error bound and not nuisance convergence.',
                  'Strict nuisance convergence at fixed physical points is not convergence of the complete orbit estimation problem and does not authorize covariance.',
                  'These bounded synthetic engineering checks do not establish full-fit regression success, v4 equivalence, scientific superiority, or release readiness.',
                  'Full dependency and bulk input provenance are audited by the parent terminal audit; this focused audit checks small source, request, profile, and row artifacts only.'
              ]}
    destination = OUT/'result.json'
    if destination.exists():
        raise FileExistsError('Preserve existing audit output: '+str(destination))
    destination.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'passed':result['passed'],'checks':len(checks),'failed_checks':result['failed_checks'],
                      'result':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()}))
    return 0 if result['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
