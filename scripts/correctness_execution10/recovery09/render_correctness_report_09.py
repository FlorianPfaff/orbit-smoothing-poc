#!/usr/bin/env python3
"""Render compact correction evidence without running or certifying estimators."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import html
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

POLICY = {'maximum_scales': 9, 'ratio': .5, 'required_consecutive_passing_scales': 2,
          'physical_repeat_allowance_multiplier': 10}
TOLERANCE = 1e-4
METHODS = ('log_drag_ou', 'pulses')
REPLAYS = {
    "nuisance-replay": "original near03 density point-030-direction-0.015625-1-repeat",
    "nuisance-replay-candidate1-point012": "validation02 density point-012-direction-0.25--1-repeat",
}
STEPS = ('clone', 'checkout', 'build', 'native-tests', 'correction-regression-tests', 'synthetic-refinement-log_drag_ou',
         'synthetic-refinement-pulses', 'flight-refinement', 'eccentric-24h-refinement',
         'objective-log_drag_ou', 'objective-pulses', *REPLAYS)
LIMITATION = ('This is a bounded numerical engineering correctness check, including selected synthetic and flight refinement fixtures. It does not replace, '
              'reclassify or certify the frozen 150-attempt campaign, establish flight accuracy, '
              'or accept a v3.1 release. Audited numerical-floor status is not nuisance convergence '
              'and cannot authorize accepted covariance. Repeated-evaluation spread is empirical, '
              'not a rigorous error bound.')


def load_recovery_helper():
    path=Path(__file__).with_name('recovery_evidence_09.py')
    spec=importlib.util.spec_from_file_location('recovery_evidence04_report',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: '+key)
        result[key] = value
    return result


def strict_float(value):
    number = float(value)
    if not math.isfinite(number): raise ValueError('Non-finite JSON number: '+value)
    return number


def reject_constant(value):
    raise ValueError('Non-finite JSON number: '+value)


def evidence(path, *, xml=False):
    path = Path(path).absolute()
    result = {'path': str(path), 'status': 'missing'}
    if not path.is_file():
        return result, None
    try:
        if path.stat().st_size > 64*1024*1024:
            raise ValueError('Compact evidence exceeds 64 MiB')
        raw = path.read_bytes()
        result.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
        if xml:
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
                raise ValueError('XML declarations/entities are not permitted')
            value = ET.fromstring(raw)
        else:
            value = json.loads(raw, object_pairs_hook=strict_pairs, parse_constant=reject_constant, parse_float=strict_float)
            if not isinstance(value, dict):
                raise ValueError('Expected a JSON object')
        result['status'] = 'available'
        return result, value
    except (OSError, ValueError, ET.ParseError) as error:
        result.update(status='invalid', error=str(error))
        return result, None


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def boolean(value):
    return type(value) is bool


def objective(path):
    source, data = evidence(path)
    result = {'evidence': source, 'status': source['status'], 'directional_scales': []}
    if data is None:
        return result
    result.update(reported_passed=data.get('passed'), error=data.get('error'),
        native_binary_sha256=data.get('native_binary_sha256'), source_hash=data.get('source_hash'),
        initialization_policy=data.get('initialization_policy'), state_input=data.get('state_input'),
        prior=data.get('prior'), rank=data.get('rank'),
        objective_repeat_difference=data.get('objective_repeat_difference'),
        empirical_physical_objective_resolution=data.get('empirical_physical_objective_resolution'),
        relative_derivative_tolerance=data.get('relative_derivative_tolerance'),
        derivative_refinement_policy=data.get('derivative_refinement_policy'),
        profile_evaluations=data.get('profile_evaluations', []),
        accepted_derivative_scales=data.get('accepted_derivative_scales', []))
    problems = []
    if data.get('relative_derivative_tolerance') != TOLERANCE or data.get('derivative_refinement_policy') != POLICY:
        problems.append('Objective rules differ from the unchanged 1e-4 / nine-scale / two-consecutive / 10x policy')
    if not boolean(data.get('passed')):
        problems.append('Objective passed flag is absent or is not Boolean')
    rows = data.get('directional_derivatives', [])
    profiles = data.get('profile_evaluations', [])
    if not isinstance(rows, list) or not all(isinstance(v, dict) for v in rows):
        problems.append('Directional derivative records must be a list of objects'); rows = []
    if not isinstance(profiles, list) or not all(isinstance(v, dict) for v in profiles):
        problems.append('Profile evaluation records must be a list of objects'); profiles = []
        result['profile_evaluations'] = []
    completed = {}
    for row in rows:
        h = row.get('scale')
        if not number(h) or h not in [.5**k for k in range(9)] or h in completed:
            problems.append('Unknown or duplicate directional scale'); continue
        completed[h] = row
    labels = {}
    for profile in profiles:
        label = profile.get('label', '')
        match = re.fullmatch(r'direction-([0-9.]+)-(-?1)(-repeat)?', str(label))
        if match:
            labels.setdefault(float(match[1]), []).append(label)
    failed_label = re.search(r'direction-([0-9.]+)-(-?1)(-repeat)?', str(data.get('error', '')))
    failed_scale = float(failed_label[1]) if failed_label else None
    result['profile_resolution_counts'] = {'strict': sum(p.get('nuisance_converged') is True and p.get('nuisance_floor_limited') is not True for p in profiles), 'audited_floor_only': sum(p.get('nuisance_floor_limited') is True and p.get('nuisance_converged') is False for p in profiles), 'unresolved': sum(p.get('nuisance_converged') is not True and p.get('nuisance_floor_limited') is not True for p in profiles)}
    passing = []
    for exponent in range(9):
        h = .5**exponent
        row = completed.get(h)
        item = {'scale': h, 'status': 'not_attempted', 'completed_profile_labels': labels.get(h, [])}
        if row is not None:
            item.update(row)
            rel, floor, combined = (row.get(k) for k in ('relative_difference', 'empirical_resolution_fraction', 'relative_difference_plus_resolution'))
            valid = all(number(v) and v >= 0 for v in (rel, floor, combined))
            if valid:
                valid = math.isclose(rel+floor, combined, rel_tol=1e-12, abs_tol=1e-16)
            derived = valid and combined <= TOLERANCE
            if not valid or not boolean(row.get('passes_unchanged_tolerance')) or row.get('passes_unchanged_tolerance') != derived:
                item['status'] = 'invalid'; problems.append('Directional criterion or passed flag is inconsistent at scale '+str(h))
            else:
                item['status'] = 'passed' if derived else 'failed'
                passing.append((h, derived))
        elif h in labels or h == failed_scale:
            item.update(status='incomplete', error=data.get('error'), failure_label_from_error=failed_label[0] if h == failed_scale else None)
        result['directional_scales'].append(item)
    prior = data.get('prior')
    prior_ok = (isinstance(prior, dict) and number(prior.get('maximum_residual_difference'))
        and prior.get('absolute_tolerance') == {'constraint.logDensityOu': 2e-8, 'constraint.pulses': 1e-12}.get(prior.get('source'))
        and 0 <= prior['maximum_residual_difference'] <= prior['absolute_tolerance']
        and number(prior.get('cost')) and prior['cost'] > 0)
    result['prior_status'] = 'passed' if prior_ok else ('missing' if prior is None else 'invalid')
    consecutive = any(a[1] and b[1] and b[0] == a[0]*.5 for a, b in zip(passing, passing[1:]))
    if data.get('passed') is True and (not consecutive or not prior_ok or data.get('error')):
        problems.append('Claimed objective pass lacks consecutive passing scales and valid nonzero prior evidence, or records an error')
    result['status'] = 'invalid' if problems else ('passed' if data.get('passed') is True else 'failed')
    result['integrity_errors'] = problems
    return result


def junit(path):
    source, tree = evidence(path, xml=True)
    result = {'evidence': source, 'status': source['status'], 'counts': None, 'cases': []}
    if tree is None:
        return result
    if tree.tag not in ('testsuites', 'testsuite'):
        result.update(status='invalid', error='Expected JUnit testsuite(s) root'); return result
    counts = dict(passed=0, failed=0, errors=0, skipped=0, total=0)
    problems = []
    for case in tree.iter('testcase'):
        tags = [key for key in ('failure', 'error', 'skipped') if case.find(key) is not None]
        if len(tags) > 1:
            problems.append('Testcase has contradictory outcome tags')
        status = {'failure': 'failed', 'error': 'errors', 'skipped': 'skipped'}.get(tags[0] if tags else '', 'passed')
        counts[status] += 1; counts['total'] += 1
        result['cases'].append({'name': case.get('name'), 'class': case.get('classname'), 'status': status,
            'details': [{'kind': child.tag, 'message': child.get('message'), 'text': child.text}
                        for child in case if child.tag in ('failure', 'error', 'skipped')]})
    for suite in tree.iter('testsuite'):
        cases = list(suite.iter('testcase'))
        for key, tag in (('tests', None), ('failures', 'failure'), ('errors', 'error'), ('skipped', 'skipped')):
            if key in suite.attrib:
                actual = len(cases) if tag is None else sum(case.find(tag) is not None for case in cases)
                try:
                    if int(suite.attrib[key]) != actual: problems.append('JUnit declared '+key+' disagrees with testcase records')
                except ValueError:
                    problems.append('Invalid JUnit count')
    result.update(counts=counts, integrity_errors=problems)
    result['status'] = ('invalid' if problems else 'failed' if counts['failed'] or counts['errors'] else
                        'incomplete' if counts['skipped'] or counts['total'] == 0 else 'passed')
    return result


def refinement(path, *, flight=False):
    source, data = evidence(path)
    result = {'evidence': source, 'status': source['status']}
    if data is None: return result
    for key in ('passed', 'status', 'error', 'binary_sha256', 'request_sha256', 'diagnostic_source_sha256',
                'signal_diagnostic_source_sha256', 'method', 'case', 'state_grid_seconds', 'controls', 'scope', 'metrics', 'native_signals', 'elapsed_seconds'):
        result['reported_status' if key == 'status' else key] = data.get(key)
    problems = []
    signals = data.get('native_signals') or {}
    rows = signals.get('signals', []) if isinstance(signals, dict) else []
    metrics = data.get('metrics') or {}
    grid_valid = data.get('state_grid_seconds') == [5., 2.5]
    if flight:
        controls = data.get('controls') or {}
        if not isinstance(controls, dict): controls = {}
        coarse, fine = controls.get('coarse', {}), controls.get('fine', {})
        grid_valid = isinstance(coarse, dict) and isinstance(fine, dict) and coarse.get('state_seconds') == 5. and fine.get('state_seconds') == 2.5
        if grid_valid:
            a, b = coarse.get('thermal_seconds'), fine.get('thermal_seconds')
            grid_valid = isinstance(a, list) and isinstance(b, list) and bool(a) and len(a) == len(b) and all(number(x) and number(y) and x > 0 and y == x/2 for x,y in zip(a,b))
            x, y = coarse.get('atmosphere_seconds'), fine.get('atmosphere_seconds')
            grid_valid = grid_valid and number(x) and number(y) and x > 0 and y == x/2
    valid = (grid_valid and isinstance(metrics, dict)
        and set(metrics) == {'aligned_position_maximum_m', 'offgrid_position_maximum_m'}
        and all(number(x) and 0 <= x < 3e-5 for x in metrics.values())
        and isinstance(signals, dict) and signals.get('comparison_weights_frozen') is True
        and signals.get('fixed_nuisance_values_identical') is True and isinstance(rows, list) and len(rows) == 4)
    if valid:
        identities = {(r.get('observable'), r.get('frequency_hz')) for r in rows if isinstance(r, dict)}
        valid = identities == {(o, f) for o in ('code', 'carrier') for f in (1575420000., 1227600000.)}
        valid = valid and all(number(r.get('maximum_fraction_of_sigma')) and 0 <= r['maximum_fraction_of_sigma'] < .01
                            and r.get('passed') is True for r in rows)
    if not boolean(data.get('passed')): problems.append('Refinement passed flag is missing or is not Boolean')
    if data.get('passed') is True and (not valid or data.get('error') or data.get('status') != 'complete'):
        problems.append('Claimed refinement pass does not satisfy the fixed grid, 30 micrometre, and 1%-noise rules')
    result.update(status='invalid' if problems else ('passed' if data.get('passed') else 'failed'), integrity_errors=problems)
    return result


def nuisance(path):
    source, data = evidence(path)
    result = {'evidence': source, 'status': source['status'], 'resolution_status': 'unavailable'}
    if data is None: return result
    keys = ('passed', 'returncode', 'timed_out', 'elapsed_seconds', 'native_sha256', 'native_unchanged',
            'build_manifest_sha256', 'strict_nuisance_converged', 'progress_only_floor_validated',
            'allow_floor_limited_requested', 'fixed_observations_and_weights_verified_every_trial',
            'ambiguity_half_integer_crossings_tested', 'zero_update_replay_exact', 'profile')
    result.update({key: data.get(key) for key in keys})
    strict, floor = data.get('strict_nuisance_converged'), data.get('progress_only_floor_validated')
    result['resolution_status'] = ('strict_convergence' if strict is True and floor is False else
        'audited_floor_only_not_converged' if floor is True and strict is False else 'unresolved_or_invalid')
    profile = data.get('profile') or {}
    if not isinstance(profile, dict): profile = {}
    audits = profile.get('nuisance_floor_audit') or [] if isinstance(profile, dict) else []
    floor_valid = (floor is True and strict is False and data.get('allow_floor_limited_requested') is True
        and profile.get('nuisance_converged') is False and profile.get('nuisance_floor_limited') is True
        and number(profile.get('nuisance_predicted_reduction')) and number(profile.get('nuisance_objective_resolution'))
        and 0 < profile['nuisance_predicted_reduction'] <= profile['nuisance_objective_resolution']
        and isinstance(audits, list) and bool(audits) and all(isinstance(a, dict) and a.get('success') is True and a.get('support_unchanged') is True for a in audits))
    strict_valid = strict is True and floor is False and profile.get('nuisance_converged') is True and profile.get('nuisance_floor_limited') is not True
    valid = (data.get('returncode') == 0 and data.get('timed_out') is False and data.get('native_unchanged') is True
        and data.get('fixed_observations_and_weights_verified_every_trial') is True and data.get('zero_update_replay_exact') is True
        and number(data.get('ambiguity_half_integer_crossings_tested')) and data['ambiguity_half_integer_crossings_tested'] > 0
        and (strict_valid or floor_valid))
    problems = []
    if not boolean(data.get('passed')): problems.append('Nuisance passed flag is missing or is not Boolean')
    if data.get('passed') is True and not valid: problems.append('Claimed nuisance validation pass lacks consistent strict/floor audit and transaction evidence')
    result.update(status='invalid' if problems else ('passed' if data.get('passed') else 'failed'), integrity_errors=problems)
    return result


def exact_replay(path, source_failure):
    result = nuisance(path)
    second, data = evidence(path)
    if second != result['evidence']:
        result.update(status='invalid',integrity_errors=[*result.get('integrity_errors',[]),'Replay receipt changed between status and diagnostic reads'])
        return {**result,'source_failure':source_failure}
    data = data or {}
    searches = data.get('searches')
    result.update(source_failure=source_failure, error=data.get('error'),
        source_profile_sha256=data.get('source_profile_sha256'), replay_profile_sha256=data.get('replay_profile_sha256'),
        final_search=searches[-1] if isinstance(searches,list) and searches else None)
    return result


def collect(run, old, control, audit=None):
    run, old, control = map(Path, (run, old, control))
    source, pipeline = evidence(run/'pipeline.json')
    pipeline = pipeline or {}
    execution_pin=pipeline.get('execution') or {}
    execution_data=evidence(execution_pin['path'])[1] if isinstance(execution_pin,dict) and isinstance(execution_pin.get('path'),str) else {}
    execution_data=execution_data or {}
    def physical(path):return load_recovery_helper().host_path(path,execution_data)
    steps = pipeline.get('steps') or []
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps): steps = []
    reuse = pipeline.get('reused_build')
    invalid_reuse = reuse is not None and not isinstance(reuse, dict)
    if invalid_reuse: reuse = None
    prior_meta, prior_data = ({'status':'not_supplied'}, None)
    if isinstance(reuse, dict) and isinstance(reuse.get('prior_pipeline'), dict):
        previous_path = reuse['prior_pipeline'].get('path')
        if isinstance(previous_path, str): prior_meta, prior_data = evidence(physical(previous_path))
    if prior_data is None and isinstance(pipeline.get('prior_failed_validation'),dict):
        previous_path = pipeline['prior_failed_validation'].get('path')
        if isinstance(previous_path,str): prior_meta, prior_data = evidence(physical(previous_path))
    prior_steps = (prior_data or {}).get('steps') or []
    if not isinstance(prior_steps, list): prior_steps = []
    planned = STEPS
    expanded_steps = []
    for name in planned:
        actual = [s for s in steps if s.get('name') == name]
        if not actual and reuse and name in ('clone','checkout','build'):
            old_step = next((s for s in prior_steps if isinstance(s, dict) and s.get('name') == name), None)
            actual = [{'name':name, 'status':'reused_not_rerun', 'previous_attempt_status':(old_step or {}).get('status'), 'previous_attempt_receipt':prior_meta.get('path')}]
        expanded_steps.extend(actual or [{'name': name, 'status': 'not_run'}])
    expanded_steps.extend({**s, 'unplanned_step': True} for s in steps if s.get('name') not in planned)
    result = {'schema': 'orbit-correction-evidence-report09-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': LIMITATION, 'release_acceptance': 'not_assessed', 'frozen_campaign_reclassified': False,
        'execution_scope':'Fresh serial validation of an explicitly versioned numerical correction. The original 106-test suite, physical inputs and numerical criteria remain unchanged. Interrupted03 and failed04/05/06/07/08 remain distinct. No campaign pause or resume is claimed.',
        'renderer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'recovery_verifier_sha256':hashlib.sha256(Path(__file__).with_name('recovery_evidence_09.py').read_bytes()).hexdigest(),
        'rules': {'relative_derivative_tolerance': TOLERANCE, 'derivative_refinement_policy': POLICY,
            'refinement_grid_seconds': [5., 2.5], 'position_difference_limit_m_exclusive': 3e-5,
            'signal_difference_fraction_of_noise_exclusive': .01},
        'pipeline': {'evidence': source, 'status': pipeline.get('status', source['status']),
            'phase': pipeline.get('phase'), 'error': pipeline.get('error'), 'source': pipeline.get('source'),
            'native': pipeline.get('native'), 'helper_sha256': pipeline.get('helper_sha256'),
            'wrapper': pipeline.get('wrapper'), 'resume': pipeline.get('resume'),
            'execution':pipeline.get('execution'), 'admission':pipeline.get('admission'), 'interruption_record':pipeline.get('interruption_record'),
            'resume_error': pipeline.get('resume_error'), 'resume_withheld': pipeline.get('resume_withheld'),
            'final_cleanup': pipeline.get('final_cleanup'), 'reused_build':reuse,
            'prior_failed_validation':pipeline.get('prior_failed_validation'), 'runner_change':pipeline.get('runner_change'),
            'required_pins':pipeline.get('required_pins'), 'native_test_inventory':pipeline.get('native_test_inventory')},
        'steps': expanded_steps,
        'native_tests': junit(run/'native-tests.xml'),
        'correction_regression_tests': junit(run/'correction-regression-tests.xml'),
        'objectives': {m: objective(run/('objective-'+m)/'validation.json') for m in METHODS},
        'previous_objectives': {m: objective(old/(m+'-staged')/'validation.json') for m in METHODS},
        'synthetic_refinement': {m: refinement(run/('synthetic-refinement-'+m)/'result.json') for m in METHODS},
        'nuisance_replays': {name:exact_replay(run/name/'receipt.json',label) for name,label in REPLAYS.items()}, 'provenance': {},
        'prior_validation_attempt':{'evidence':prior_meta,'record':prior_data},
        'additional_refinement': ({'density_24h':refinement(run/'eccentric-24h-refinement/result.json'),
            'flight_april24':refinement(run/'flight-refinement/result.json',flight=True)})}
    errors = []
    required_pin=pipeline.get('required_pins') or {}
    pins_path=Path(required_pin.get('path',control/'candidate09-pins.json')) if isinstance(required_pin,dict) else control/'candidate09-pins.json'
    pins_meta,pins_data=evidence(pins_path)
    result['provenance']['candidate09-pins.json']={'evidence':pins_meta,'record':pins_data}
    if pins_data and pins_data.get('recovery_verifier_sha256')!=result['recovery_verifier_sha256']:
        errors.append('Correction provenance verifier differs from frozen pins')
    if required_pin:
        if not isinstance(required_pin,dict) or pins_meta.get('status')!='available' or required_pin.get('sha256')!=pins_meta.get('sha256'):
            errors.append('Required source/control pins are missing or changed')
    result['recovery']={'status':'not_assessed'}
    if pipeline.get('execution') or pipeline.get('status')=='passed':
        try:
            helper=load_recovery_helper()
            def read_pin(pin,role):
                meta,data=evidence(pin.get('path',''))
                result['provenance'][role]={'evidence':meta,'record':data}
                if meta.get('status')!='available' or meta.get('sha256')!=pin.get('sha256'):
                    raise ValueError('Recovery provenance missing or changed: '+role)
                return data
            result['recovery']=helper.validate_recovery(pipeline,pins_data or {},read_pin)
        except (ValueError,TypeError,KeyError,OSError) as error:
            result['recovery']={'status':'invalid','error':str(error)}
            errors.append('Recovery provenance invalid: '+str(error))
    tests=result['native_tests'];inventory=pipeline.get('native_test_inventory')
    if tests.get('status')=='passed':
        counts=tests.get('counts') or {}
        expected_inventory={'tests':counts.get('total'),'passed':counts.get('passed'),'failures':counts.get('failed'),'errors':counts.get('errors'),'skipped':counts.get('skipped')}
        if inventory!=expected_inventory:
            tests['status']='invalid';errors.append('Passed JUnit does not match the recorded native test inventory')
        if counts.get('total')!=106 or pins_data is None or pins_data.get('expected_native_test_count')!=106:
            tests['status']='invalid';errors.append('Passed JUnit does not match the pinned expected native test count')
        identities=[(item.get('class'),item.get('name')) for item in tests.get('cases',[])]
        expected_tests=['tests/test_numerics_native_qr.py','tests/test_numerics_original_objective.py',
            'tests/test_numerics_mean_residual.py','tests/test_numerics_derivatives.py',
            'tests/test_numerics_geometry_precision.py','tests/test_numerics_synthetic_force_arithmetic.py']
        native_steps=[item for item in steps if item.get('name')=='native-tests']
        if len(identities)!=len(set(identities)) or any(not all(item) for item in identities):
            tests['status']='invalid';errors.append('Passed JUnit contains duplicate or unnamed testcase identities')
        if (len(native_steps)!=1 or native_steps[0].get('status')!='passed' or native_steps[0].get('returncode')!=0
                or [arg for arg in native_steps[0].get('argv',[]) if isinstance(arg,str) and arg.startswith('tests/')]!=expected_tests):
            tests['status']='invalid';errors.append('Passed JUnit lacks the exact executed six-module test command')

    regression=result['correction_regression_tests']
    if regression.get('status')=='passed':
        counts=regression.get('counts') or {};spec=(pins_data or {}).get('regression_suite') or {}
        identities=[(item.get('class'),item.get('name')) for item in regression.get('cases',[])]
        recorded=pipeline.get('correction_regression_inventory')
        expected={'tests':counts.get('total'),'passed':counts.get('passed'),'failures':counts.get('failed'),'errors':counts.get('errors'),'skipped':counts.get('skipped')}
        actual=[s for s in steps if s.get('name')=='correction-regression-tests']
        if (counts.get('total')!=spec.get('expected_count') or recorded!=expected
                or len(identities)!=len(set(identities)) or any(not all(item) for item in identities)
                or len(actual)!=1 or actual[0].get('status')!='passed' or actual[0].get('returncode')!=0
                or [arg for arg in actual[0].get('argv',[]) if isinstance(arg,str) and arg.startswith('tests/')]!=spec.get('files')):
            regression['status']='invalid';errors.append('Separate correction regression JUnit, command or count differs from freeze')

    if source['status'] == 'invalid': errors.append('Pipeline JSON is invalid')
    if invalid_reuse: errors.append('Reused build evidence must be an object')
    if reuse:
        if prior_meta.get('status') != 'available' or prior_meta.get('sha256') != reuse.get('prior_pipeline', {}).get('sha256'):
            errors.append('Reused build prior pipeline is missing or differs from its pin')
        if prior_data is not None and prior_data.get('native') != pipeline.get('native'):
            errors.append('Reused candidate binary differs from preserved prior attempt')
    if pipeline.get('prior_failed_validation') and not reuse:
        prior_pin = pipeline['prior_failed_validation']
        if prior_meta.get('status')!='available' or prior_meta.get('sha256')!=prior_pin.get('sha256'):
            errors.append('Preserved previous validation differs from its pin')
    native = pipeline.get('native') or {}
    if not isinstance(native, dict):
        errors.append('Pipeline native identity must be an object'); native = {}
    expected = native.get('sha256')
    if expected:
        checks = [(v, 'native_binary_sha256') for v in result['objectives'].values()]
        checks += [(v, 'binary_sha256') for v in result['synthetic_refinement'].values()]
        checks += [(v, 'binary_sha256') for v in result['additional_refinement'].values()]
        checks += [(item, 'native_sha256') for item in result['nuisance_replays'].values()]
        for item, key in checks:
            actual = item.get(key)
            if actual is not None and actual != expected:
                errors.append('Candidate binary identity differs: '+item['evidence']['path'])
                item['status'] = 'invalid'
    result['independent_audit'] = {'status': 'not_supplied', 'record': None}
    if audit is not None:
        meta, audit_data = evidence(audit)
        checked = {'evidence': meta, 'status': meta['status'], 'record': audit_data}
        result['independent_audit'] = checked
        if audit_data is not None:
            audit_errors = []
            if audit_data.get('schema') != 'orbit-poc-correctness-independent-audit09-v1' or not boolean(audit_data.get('passed')):
                audit_errors.append('Independent audit schema/pass flag is invalid')
            replay_audits = audit_data.get('nuisance_replays')
            methods_audits = audit_data.get('objective_methods')
            if not isinstance(replay_audits,dict) or set(replay_audits)!=set(REPLAYS) or not all(isinstance(v,dict) and boolean(v.get('passed')) for v in replay_audits.values()):
                audit_errors.append('Independent audit must report both exact nuisance replays')
            if not isinstance(methods_audits,dict) or set(methods_audits)!=set(METHODS) or not all(isinstance(v,dict) and boolean(v.get('passed')) for v in methods_audits.values()):
                audit_errors.append('Independent audit must report both objective methods')
            if not audit_errors:
                aggregate = all(v['passed'] for v in [*replay_audits.values(),*methods_audits.values()]) and not audit_data.get('errors')
                if audit_data['passed'] != aggregate:
                    audit_errors.append('Independent audit aggregate contradicts component outcomes')
            artifacts = audit_data.get('input_artifacts')
            if isinstance(artifacts, dict): artifacts = list(artifacts.values())
            if not isinstance(artifacts, list) or not all(isinstance(a, dict) and isinstance(a.get('path'), str) and a.get('status') in ('available', 'missing', 'invalid') and (a['status'] != 'available' or isinstance(a.get('sha256'), str)) for a in artifacts):
                audit_errors.append('Independent audit input artifacts are invalid'); artifacts = []
            by_path = {str(Path(a['path']).absolute()): a for a in artifacts}
            expected_inputs = [v['evidence'] for v in result['objectives'].values()] + [v['evidence'] for v in result['nuisance_replays'].values()]
            for item in expected_inputs:
                pinned = by_path.get(item['path'], {})
                if (item.get('sha256') and pinned.get('sha256') != item['sha256']) or pinned.get('status') != item['status']:
                    audit_errors.append('Independent audit does not match current input '+item['path'])
                elif item['status'] != 'available' and audit_data.get('passed') is True:
                    audit_errors.append('Independent audit claims pass with unavailable current input '+item['path'])
            if audit_data.get('passed') is True and audit_data.get('errors'):
                audit_errors.append('Independent audit claims pass while recording errors')
            checked['status'] = 'invalid' if audit_errors else ('passed' if audit_data.get('passed') is True else 'failed')
            checked['integrity_errors'] = audit_errors
            errors.extend(audit_errors)
    result['integrity_errors'] = errors
    required = [result['native_tests'], result['correction_regression_tests'], *result['objectives'].values(), *result['synthetic_refinement'].values(), *result['nuisance_replays'].values()]
    required.extend(result['additional_refinement'].values())
    states = [item['status'] for item in required]
    if audit is not None: states.append(result['independent_audit']['status'])
    result['candidate_evidence_status'] = ('invalid' if errors or 'invalid' in states else
        'failed' if pipeline.get('status') == 'failed' or 'failed' in states else
        'passed_scoped_checks' if pipeline.get('status') == 'passed' and isinstance(pipeline.get('final_cleanup'),dict) and pipeline['final_cleanup'].get('verified') is True and result['recovery'].get('status')=='verified' and result['independent_audit'].get('status')=='passed' and all(s == 'passed' for s in states) else 'incomplete')
    return result


def esc(value):
    if value is None: return '—'
    if isinstance(value, (dict, list)): value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def tab(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def detail(label, value, summary_link='summary.json'):
    encoded=json.dumps(value,indent=2,sort_keys=True)
    if len(encoded.encode())>32768:
        return ('<details><summary>'+esc(label)+'</summary><p>Complete structured evidence ('
            +str(len(encoded.encode()))+' bytes) is retained in <a href="'+esc(summary_link)
            +'">the full machine-readable summary</a>. This presentation omits the repeated payload only.</p></details>')
    return '<details><summary>'+esc(label)+'</summary><pre>'+esc(encoded)+'</pre></details>'


def document(report, summary_link='summary.json'):
    render_detail=lambda label,value:detail(label,value,summary_link)
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
        '<title>Orbit v3.1 correction evidence</title><style>body{font:16px system-ui;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#19212a}table{border-collapse:collapse;width:100%;font-size:13px;margin:1rem 0}th,td{border:1px solid #ccd2d8;padding:.4rem;text-align:left;overflow-wrap:anywhere}th{background:#eef2f6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}details{margin:1rem 0}h2{margin-top:2rem}.scope{border-left:4px solid #b36d00;padding:1rem;background:#fff7e8}</style>',
        '<h1>Orbit v3.1 correction evidence</h1><p><strong>'+esc(report['candidate_evidence_status'])+'</strong> · '+esc(report['created_at'])+'</p>',
        '<p class="scope">'+esc(LIMITATION)+'</p>',
        '<p>Unchanged objective rule: relative derivative discrepancy plus empirical resolution ≤ 10⁻⁴ at two consecutive step halvings; at most nine scales, ratio ½, repeated physical-cost allowance ×10. Refinement uses 5 s and 2.5 s grids: position differences &lt;30 µm and code/carrier differences &lt;1% of the smaller assumed/native noise, with fixed nuisance values and common weights.</p>',
        '<h2>Candidate sequence</h2>',tab(['Step','Status','Return code','Seconds'],[(s['name'],s.get('status','running'),s.get('returncode'),s.get('elapsed_seconds')) for s in report['steps']]),
        render_detail('Pipeline identities, source inventory, admitted execution and cleanup',report['pipeline'])]
    previous=report['prior_validation_attempt']
    if previous['evidence'].get('status') != 'not_supplied':
        explanation = ('The candidate build is reused byte for byte; clone, checkout and build were not rerun.' if report['pipeline'].get('reused_build') else 'This candidate uses a new build. The previous candidate and every failed check remain preserved; a new run does not erase them.')
        parts += ['<h2>Preserved previous validation attempt</h2><p>'+esc(explanation)+'</p>',
            tab(['Prior step','Status','Return code','Seconds'],[(s.get('name'),s.get('status'),s.get('returncode'),s.get('elapsed_seconds')) for s in ((previous.get('record') or {}).get('steps') or []) if isinstance(s,dict)]),render_detail('Complete prior attempt and pinned build reuse evidence',previous)]
    recovery=report.get('recovery',{})
    if recovery.get('interrupted_previous'):
        parts += ['<h2>Preserved interrupted validation03</h2><p>The earlier host restart interrupted the build before a native executable or native test results were produced. This is incomplete infrastructure evidence, distinct from validation02 scientific failures.</p>',render_detail('Interrupted attempt and restart evidence',recovery['interrupted_previous'])]
    if recovery.get('correction'):
        parts += ['<h2>Explicit correction lineage</h2><p>The original758-file, historical06 and immediate previous07 source freezes and failed attempts04/05/06/07/08 are retained. Only the reviewed, hash-pinned source paths changed; the original106 tests and prescribed numerical gate scripts remain unchanged.</p>',render_detail('Correction source inventories, path differences and prior failures',recovery['correction'])]
    parts += ['<h2>Separate correction regression tests</h2><p>These new tests are additional to the unchanged106-test inventory.</p>',render_detail('Separate regression JUnit evidence',report['correction_regression_tests'])]
    tests = report['native_tests']
    parts += ['<h2>Native tests</h2><p>Status: '+esc(tests['status'])+'. Skipped checks remain incomplete evidence.</p>',
        tab(['Passed','Failed','Errors','Skipped','Total'], [[(tests.get('counts') or {}).get(k) for k in ('passed','failed','errors','skipped','total')]]),
        render_detail('All JUnit cases and evidence identity',tests)]
    for group, title in (('objectives','Candidate objective checks'),('previous_objectives','Preserved earlier objective checks')):
        parts.append('<h2>'+title+'</h2>')
        for method in METHODS:
            obj=report[group][method]
            parts.append('<h3>'+esc(method)+' — '+esc(obj['status'])+'</h3>')
            if obj.get('error'): parts.append('<p>'+esc(obj['error'])+'</p>')
            parts.append(tab(['Scale','Status','Finite difference','Native derivative','Relative error','Resolution fraction','Combined','Completed profiles'],
                [[r.get(k) for k in ('scale','status','finite_difference','native_derivative','relative_difference','empirical_resolution_fraction','relative_difference_plus_resolution','completed_profile_labels')] for r in obj['directional_scales']]))
            parts.append('<p>Base repeat spread: '+esc(obj.get('objective_repeat_difference'))+'; empirical physical allowance: '+esc(obj.get('empirical_physical_objective_resolution'))+'. Prior check: '+esc(obj.get('prior_status'))+'.</p>')
            parts.append('<p>Profile resolution counts: '+esc(obj.get('profile_resolution_counts'))+'. Audited floor-only counts are not converged profiles.</p>')
            parts.append(render_detail('Prior, endpoint repeat spreads, profile qualifications and complete evidence',obj))
    parts.append('<h2>Synthetic propagation and measurement refinement</h2>')
    for method, item in report['synthetic_refinement'].items():
        parts.append('<h3>'+esc(method)+' — '+esc(item['status'])+'</h3>')
        rows=(item.get('native_signals') or {}).get('signals',[]) if isinstance(item.get('native_signals'),dict) else []
        parts.append(tab(['Observable','Frequency Hz','Maximum difference m','Fraction of noise','Passed'],
            [[r.get(k) for k in ('observable','frequency_hz','maximum_difference_m','maximum_fraction_of_sigma','passed')] for r in rows if isinstance(r,dict)]))
        parts.append(render_detail('Refinement metrics, fixed settings and evidence identity',item))
    if report['additional_refinement']:
        parts.append('<h2>Full-day synthetic and selected flight refinement</h2><p>These are fixed-parameter numerical checks. They do not establish flight orbit accuracy.</p>')
        for name,item in report['additional_refinement'].items():
            parts.append('<h3>'+esc(name)+' — '+esc(item['status'])+'</h3>')
            parts.append(render_detail('Unchanged refinement criteria, measured differences and full evidence',item))
    for name,item in report['nuisance_replays'].items():
        parts += ['<h2>'+esc(name)+'</h2><p>Exact failed location: '+esc(item['source_failure'])+'.</p><p>Validation: '+esc(item['status'])+'; resolution: <strong>'+esc(item['resolution_status'])+'</strong>.</p>',
            '<p>Audited floor-only evidence does not establish stationarity or convergence and cannot authorize accepted covariance.</p>',render_detail('Nuisance transaction checks and profile audit',item)]
    parts += [
        '<h2>Independent evidence audit</h2><p>Status: '+esc(report['independent_audit']['status'])+'.</p>',render_detail('Independent calculations and matched input identities',report['independent_audit']),
        '<h2>Execution and restart provenance</h2><p>'+esc(report['execution_scope'])+'</p>',render_detail('Recovery classification',report['recovery']),render_detail('Exact external control records',report['provenance']),
        render_detail('Report integrity errors',report['integrity_errors']),'<p>Machine-readable companion: <a href="'+esc(summary_link)+'">'+esc(summary_link)+'</a>. Missing and failed evidence has not been replaced or removed.</p></html>']
    return '\n'.join(parts)


def render(run, old, control, output, audit=None):
    output=Path(output)
    if output.exists(): raise ValueError('Choose a new report directory; existing reports are immutable')
    report=collect(run,old,control,audit)
    page=document(report)
    encoded=json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n'
    output.mkdir(parents=True,exist_ok=False)
    (output/'summary.json').write_text(encoded)
    (output/'index.html').write_text(page)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('run','previous','control','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--audit',type=Path)
    args=parser.parse_args();result=render(args.run,args.previous,args.control,args.output,args.audit)
    print(json.dumps({'status':result['candidate_evidence_status'],'report':str(args.output/'index.html')}))
    return 0


if __name__=='__main__':raise SystemExit(main())
