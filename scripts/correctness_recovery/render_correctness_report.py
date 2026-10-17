#!/usr/bin/env python3
"""Render compact correction evidence without running or certifying estimators."""
import argparse
from datetime import datetime, timezone
import hashlib
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
STEPS = ('clone', 'checkout', 'build', 'native-tests', 'synthetic-refinement-log_drag_ou',
         'synthetic-refinement-pulses', 'objective-log_drag_ou', 'objective-pulses', 'nuisance-replay')
LIMITATION = ('This is a bounded numerical engineering correctness check, including selected synthetic and flight refinement fixtures. It does not replace, '
              'reclassify or certify the frozen 150-attempt campaign, establish flight accuracy, '
              'or accept a v3.1 release. Audited numerical-floor status is not nuisance convergence '
              'and cannot authorize accepted covariance. Repeated-evaluation spread is empirical, '
              'not a rigorous error bound.')


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


def collect(run, old, control, audit=None):
    run, old, control = map(Path, (run, old, control))
    source, pipeline = evidence(run/'pipeline.json')
    pipeline = pipeline or {}
    steps = pipeline.get('steps') or []
    if not isinstance(steps, list) or not all(isinstance(s, dict) for s in steps): steps = []
    reuse = pipeline.get('reused_build')
    invalid_reuse = reuse is not None and not isinstance(reuse, dict)
    if invalid_reuse: reuse = None
    prior_meta, prior_data = ({'status':'not_supplied'}, None)
    if isinstance(reuse, dict) and isinstance(reuse.get('prior_pipeline'), dict):
        previous_path = reuse['prior_pipeline'].get('path')
        if isinstance(previous_path, str): prior_meta, prior_data = evidence(previous_path)
    prior_steps = (prior_data or {}).get('steps') or []
    if not isinstance(prior_steps, list): prior_steps = []
    planned = (*STEPS[:-3], 'flight-refinement', 'eccentric-24h-refinement', *STEPS[-3:]) if reuse else STEPS
    expanded_steps = []
    for name in planned:
        actual = [s for s in steps if s.get('name') == name]
        if not actual and reuse and name in ('clone','checkout','build'):
            old_step = next((s for s in prior_steps if isinstance(s, dict) and s.get('name') == name), None)
            actual = [{'name':name, 'status':'reused_not_rerun', 'previous_attempt_status':(old_step or {}).get('status'), 'previous_attempt_receipt':prior_meta.get('path')}]
        expanded_steps.extend(actual or [{'name': name, 'status': 'not_run'}])
    expanded_steps.extend({**s, 'unplanned_step': True} for s in steps if s.get('name') not in planned)
    result = {'schema': 'orbit-correction-evidence-report-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'scope': LIMITATION, 'release_acceptance': 'not_assessed', 'frozen_campaign_reclassified': False,
        'pause_timing_scope':'Verified between-attempt pauses exclude an active recorded fit timer, but intermissions may change cache and environmental context. No absence of timing effect is claimed. Any raced stop remains explicit and is not guaranteed timing-neutral.',
        'renderer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'rules': {'relative_derivative_tolerance': TOLERANCE, 'derivative_refinement_policy': POLICY,
            'refinement_grid_seconds': [5., 2.5], 'position_difference_limit_m_exclusive': 3e-5,
            'signal_difference_fraction_of_noise_exclusive': .01},
        'pipeline': {'evidence': source, 'status': pipeline.get('status', source['status']),
            'phase': pipeline.get('phase'), 'error': pipeline.get('error'), 'source': pipeline.get('source'),
            'native': pipeline.get('native'), 'helper_sha256': pipeline.get('helper_sha256'),
            'wrapper': pipeline.get('wrapper'), 'resume': pipeline.get('resume'),
            'resume_error': pipeline.get('resume_error'), 'resume_withheld': pipeline.get('resume_withheld'),
            'final_cleanup': pipeline.get('final_cleanup'), 'reused_build':reuse,
            'prior_failed_validation':pipeline.get('prior_failed_validation'), 'runner_change':pipeline.get('runner_change')},
        'steps': expanded_steps,
        'native_tests': junit(run/'native-tests.xml'),
        'objectives': {m: objective(run/('objective-'+m)/'validation.json') for m in METHODS},
        'previous_objectives': {m: objective(old/(m+'-staged')/'validation.json') for m in METHODS},
        'synthetic_refinement': {m: refinement(run/('synthetic-refinement-'+m)/'result.json') for m in METHODS},
        'nuisance_replay': nuisance(run/'nuisance-replay/receipt.json'), 'provenance': {},
        'prior_validation_attempt':{'evidence':prior_meta,'record':prior_data},
        'additional_refinement': ({'density_24h':refinement(run/'eccentric-24h-refinement/result.json'),
            'flight_april24':refinement(run/'flight-refinement/result.json',flight=True)} if reuse else {})}
    pause_pin = pipeline.get('pause_receipt') or {}
    pause_name = Path(pause_pin.get('path', 'pause-01.json')).name if isinstance(pause_pin, dict) else 'pause-01.json'
    resume_name = pause_name.replace('pause-', 'resume-', 1) if pause_name.startswith('pause-') else 'resume.json'
    for name in ('live-campaign-spec.json', pause_name, resume_name):
        meta, data = evidence(control/name)
        result['provenance'][name] = {'evidence': meta, 'record': data}
    errors = []
    if source['status'] == 'invalid': errors.append('Pipeline JSON is invalid')
    if invalid_reuse: errors.append('Reused build evidence must be an object')
    if reuse:
        if prior_meta.get('status') != 'available' or prior_meta.get('sha256') != reuse.get('prior_pipeline', {}).get('sha256'):
            errors.append('Reused build prior pipeline is missing or differs from its pin')
        if prior_data is not None and prior_data.get('native') != pipeline.get('native'):
            errors.append('Reused candidate binary differs from preserved prior attempt')
    native = pipeline.get('native') or {}
    if not isinstance(native, dict):
        errors.append('Pipeline native identity must be an object'); native = {}
    expected = native.get('sha256')
    if expected:
        checks = [(v, 'native_binary_sha256') for v in result['objectives'].values()]
        checks += [(v, 'binary_sha256') for v in result['synthetic_refinement'].values()]
        checks += [(v, 'binary_sha256') for v in result['additional_refinement'].values()]
        checks += [(result['nuisance_replay'], 'native_sha256')]
        for item, key in checks:
            actual = item.get(key)
            if actual is not None and actual != expected:
                errors.append('Candidate binary identity differs: '+item['evidence']['path'])
                item['status'] = 'invalid'
    pause = result['provenance'][pause_name]
    if pipeline.get('pause_receipt') and pause['evidence']['status'] == 'available':
        if not isinstance(pipeline['pause_receipt'], dict) or pipeline['pause_receipt'].get('sha256') != pause['evidence']['sha256']:
            errors.append('Pause receipt differs from the pipeline pin')
    result['independent_audit'] = {'status': 'not_supplied', 'record': None}
    if audit is not None:
        meta, audit_data = evidence(audit)
        checked = {'evidence': meta, 'status': meta['status'], 'record': audit_data}
        result['independent_audit'] = checked
        if audit_data is not None:
            audit_errors = []
            if audit_data.get('schema') != 'orbit-poc-correctness-independent-audit-v1' or not boolean(audit_data.get('passed')):
                audit_errors.append('Independent audit schema/pass flag is invalid')
            artifacts = audit_data.get('input_artifacts')
            if isinstance(artifacts, dict): artifacts = list(artifacts.values())
            if not isinstance(artifacts, list) or not all(isinstance(a, dict) and isinstance(a.get('path'), str) and a.get('status') in ('available', 'missing', 'invalid') and (a['status'] != 'available' or isinstance(a.get('sha256'), str)) for a in artifacts):
                audit_errors.append('Independent audit input artifacts are invalid'); artifacts = []
            by_path = {str(Path(a['path']).absolute()): a for a in artifacts}
            expected_inputs = [v['evidence'] for v in result['objectives'].values()] + [result['nuisance_replay']['evidence']]
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
    required = [result['native_tests'], *result['objectives'].values(), *result['synthetic_refinement'].values(), result['nuisance_replay']]
    required.extend(result['additional_refinement'].values())
    states = [item['status'] for item in required]
    if audit is not None: states.append(result['independent_audit']['status'])
    result['candidate_evidence_status'] = ('invalid' if errors or 'invalid' in states else
        'failed' if pipeline.get('status') == 'failed' or pipeline.get('resume_error') or pipeline.get('resume_withheld') or 'failed' in states else
        'passed_scoped_checks' if pipeline.get('status') == 'passed' and isinstance(pipeline.get('resume'), dict) and pipeline['resume'].get('status') == 'resumed' and all(s == 'passed' for s in states) else 'incomplete')
    return result


def esc(value):
    if value is None: return '—'
    if isinstance(value, (dict, list)): value = json.dumps(value, sort_keys=True, ensure_ascii=False)
    return html.escape(str(value), quote=True)


def tab(headers, rows):
    return '<table><thead><tr>'+''.join('<th>'+esc(h)+'</th>' for h in headers)+'</tr></thead><tbody>'+''.join(
        '<tr>'+''.join('<td>'+esc(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table>'


def detail(label, value):
    return '<details><summary>'+esc(label)+'</summary><pre>'+esc(json.dumps(value, indent=2, sort_keys=True))+'</pre></details>'


def document(report):
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">',
        '<title>Orbit v3.1 correction evidence</title><style>body{font:16px system-ui;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#19212a}table{border-collapse:collapse;width:100%;font-size:13px;margin:1rem 0}th,td{border:1px solid #ccd2d8;padding:.4rem;text-align:left;overflow-wrap:anywhere}th{background:#eef2f6}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}details{margin:1rem 0}h2{margin-top:2rem}.scope{border-left:4px solid #b36d00;padding:1rem;background:#fff7e8}</style>',
        '<h1>Orbit v3.1 correction evidence</h1><p><strong>'+esc(report['candidate_evidence_status'])+'</strong> · '+esc(report['created_at'])+'</p>',
        '<p class="scope">'+esc(LIMITATION)+'</p>',
        '<p>Unchanged objective rule: relative derivative discrepancy plus empirical resolution ≤ 10⁻⁴ at two consecutive step halvings; at most nine scales, ratio ½, repeated physical-cost allowance ×10. Refinement uses 5 s and 2.5 s grids: position differences &lt;30 µm and code/carrier differences &lt;1% of the smaller assumed/native noise, with fixed nuisance values and common weights.</p>',
        '<h2>Candidate sequence</h2>',tab(['Step','Status','Return code','Seconds'],[(s['name'],s.get('status','running'),s.get('returncode'),s.get('elapsed_seconds')) for s in report['steps']]),
        detail('Pipeline identities, source inventory, cleanup and resume',report['pipeline'])]
    previous=report['prior_validation_attempt']
    if previous['evidence'].get('status') != 'not_supplied':
        parts += ['<h2>Preserved previous validation attempt</h2><p>The candidate build is reused byte for byte. Clone, checkout and build were not rerun. The previous native-test invocation failed and remains part of the record; a retry does not erase that failure.</p>',
            tab(['Prior step','Status','Return code','Seconds'],[(s.get('name'),s.get('status'),s.get('returncode'),s.get('elapsed_seconds')) for s in ((previous.get('record') or {}).get('steps') or []) if isinstance(s,dict)]),detail('Complete prior attempt and pinned build reuse evidence',previous)]
    tests = report['native_tests']
    parts += ['<h2>Native tests</h2><p>Status: '+esc(tests['status'])+'. Skipped checks remain incomplete evidence.</p>',
        tab(['Passed','Failed','Errors','Skipped','Total'], [[(tests.get('counts') or {}).get(k) for k in ('passed','failed','errors','skipped','total')]]),
        detail('All JUnit cases and evidence identity',tests)]
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
            parts.append(detail('Prior, endpoint repeat spreads, profile qualifications and complete evidence',obj))
    parts.append('<h2>Synthetic propagation and measurement refinement</h2>')
    for method, item in report['synthetic_refinement'].items():
        parts.append('<h3>'+esc(method)+' — '+esc(item['status'])+'</h3>')
        rows=(item.get('native_signals') or {}).get('signals',[]) if isinstance(item.get('native_signals'),dict) else []
        parts.append(tab(['Observable','Frequency Hz','Maximum difference m','Fraction of noise','Passed'],
            [[r.get(k) for k in ('observable','frequency_hz','maximum_difference_m','maximum_fraction_of_sigma','passed')] for r in rows if isinstance(r,dict)]))
        parts.append(detail('Refinement metrics, fixed settings and evidence identity',item))
    if report['additional_refinement']:
        parts.append('<h2>Full-day synthetic and selected flight refinement</h2><p>These are fixed-parameter numerical checks. They do not establish flight orbit accuracy.</p>')
        for name,item in report['additional_refinement'].items():
            parts.append('<h3>'+esc(name)+' — '+esc(item['status'])+'</h3>')
            parts.append(detail('Unchanged refinement criteria, measured differences and full evidence',item))
    item=report['nuisance_replay']
    parts += ['<h2>Nuisance replay</h2><p>Validation: '+esc(item['status'])+'; resolution: <strong>'+esc(item['resolution_status'])+'</strong>.</p>',
        '<p>Audited floor-only evidence does not establish stationarity or convergence and cannot authorize accepted covariance.</p>',detail('Nuisance transaction checks and profile audit',item),
        '<h2>Independent evidence audit</h2><p>Status: '+esc(report['independent_audit']['status'])+'.</p>',detail('Independent calculations and matched input identities',report['independent_audit']),
        '<h2>Pause/resume provenance</h2><p>'+esc(report['pause_timing_scope'])+'</p>',detail('Exact external control records',report['provenance']),
        detail('Report integrity errors',report['integrity_errors']),'<p>Machine-readable companion: summary.json. Missing and failed evidence has not been replaced or removed.</p></html>']
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
