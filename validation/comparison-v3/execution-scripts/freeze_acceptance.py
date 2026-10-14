"""Review actual evidence, then bind gates 1–4 to the final production protocol.

--check-only is strictly read-only: it never creates protocol.json or gate files.
A passing engineering review is not a scientific comparison or coverage claim.
"""
from datetime import datetime, timezone
from copy import deepcopy
import argparse
import json
from pathlib import Path
import shutil

from orbit_poc.comparison import protocol
from orbit_poc.comparison.config import load_config
from orbit_poc.comparison.protocol import (freeze_protocol, read_json, write_json, file_hash,
                                           canonical_hash, source_snapshot, case_matrix)
from orbit_poc.comparison.gates import validate_gates

NATIVE_SHA = '74863d5a16dbcb1f762e9a4bbe7eebc064e1d11f641691a7d3f87e3669288453'
UPSTREAM = '7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'
METHODS = {'groops_pulses', 'groops_log_drag_ou'}


def check(condition, reason):
    if not condition:
        raise ValueError(reason)


def matching_hash(path, expected):
    check(isinstance(expected, str) and len(expected) == 64, 'Missing exact SHA256: '+str(path))
    check(Path(path).is_file() and file_hash(path) == expected, 'Missing/modified evidence artifact: '+str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--evidence-dir', type=Path, required=True)
    parser.add_argument('--tests-record', default='automated-tests-f2b41a4b.json')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args(argv)
    config = load_config(args.config)
    root, evidence = Path(config.output_dir), args.evidence_dir.resolve()
    snapshot = source_snapshot()
    issues, checked, extra_artifacts = [], {}, {}
    tests_key = args.tests_record.removesuffix('.json')

    def require(name, validator):
        try:
            row = read_json(evidence/(name+'.json'))
            validator(row)
            checked[name] = row
            return row
        except (OSError, ValueError, KeyError, TypeError, AssertionError, StopIteration) as error:
            issues.append({'evidence':name, 'error':f'{type(error).__name__}: {error}'})
            return None

    def current_pass(row):
        check(row.get('passed') is True and row.get('native_binary_sha256') == NATIVE_SHA,
              'Requires passed=true on the current native executable')

    def test_suite(row):
        check(row.get('status') == 'passed' and row.get('failures') == 0 and row.get('errors') == 0,
              'Full automated suite did not pass')
        check(row.get('source_stable_during_run') is True and row.get('test_source_stable_during_run') is True,
              'Runtime or test source changed during the suite')
        check(row.get('native_tests_enabled') is True and row.get('native_binary_sha256') == NATIVE_SHA,
              'Current native tests were not enabled')
        check(row['source_snapshot']['sha256'] == snapshot['sha256'], 'Tests do not cover the final runtime source')
        check(row.get('passed', 0) > 0 and row.get('skipped', 0) <= 1,
              'Empty suite or unexpected skipped tests')
        if row.get('skipped'):
            check(row.get('skip_reasons') == ['Optional archived real v1 pilot fixture is not present'],
                  'Unexpected skipped test')
        for item in row['artifacts'].values():
            matching_hash(evidence/item['file'], item['sha256'])
        for key in ('source_snapshot', 'test_source_snapshot_at_completion'):
            item = row[key]
            matching_hash(evidence/item['manifest'], item['manifest_sha256'])
            manifest = read_json(evidence/item['manifest'])
            check(canonical_hash(manifest['files']) == manifest['sha256'] == item['sha256'],
                  'Source manifest canonical hash differs')
        tests = read_json(evidence/row['test_source_snapshot_at_completion']['manifest'])['files']
        project = Path(protocol.__file__).resolve().parents[3]
        for path, digest in tests.items():
            matching_hash(project/path, digest)
        current_python_tests = {str(path.relative_to(project)) for path in (project/'tests').rglob('*.py')}
        check(current_python_tests <= set(tests), 'Untested Python test files were added after the suite')

    def baseline(row):
        check(row.get('passed') is True and row.get('unmodified_upstream') is True,
              'Official unmodified upstream example reproduction is required')
        check(row['groops_upstream_commit'] == UPSTREAM and row['example_sha256'] == config.backend.example_sha256,
              'Official example/upstream identity differs')
        check(len(row['agreement']) == 2 and all(item['passed'] is True for item in row['agreement']),
              'Both example days must pass their recorded thresholds')

    def native_build(row):
        check(row.get('native_binary_sha256') == NATIVE_SHA and row.get('upstream_commit') == UPSTREAM,
              'Native build identity differs')
        check(row.get('build_result') == 'success' and row['patched_source']['compiled_source_matches_fresh_patch'] is True,
              'Native build/installation verification failed')
        matching_hash(evidence/'fresh-extension-installation.json',
                      row['patched_source']['fresh_installation_evidence_sha256'])
        matching_hash(evidence/row['build_log'], row['build_log_sha256'])

    def four_synthetic_fits(row):
        current_pass(row)
        check(len(row['records']) == 4 and all(item.get('status') == 'complete' and
            item.get('converged') is True and item.get('covariance_valid') is True for item in row['records']),
            'Four completed independent-truth engineering fits are required')
        check(row.get('same_predictive_support_across_arms') is True and
              all(row.get('same_preprocessing_across_arms', {}).values()), 'Synthetic support/preprocessing mismatch')
        check(len(row.get('preparation', [])) == 2 and all(item['nominal_initialization']['converged'] is True
            for item in row['preparation']), 'Closed common nominal initialization is missing')

    def full_utc_fits(row):
        current_pass(row)
        check(row.get('final_source_sha256') == snapshot['sha256'], 'UTC engineering review does not target final source')
        records = row.get('records', [])
        check(len(records) == 4 and {(item['coverage'], item['method']) for item in records} ==
              {(coverage, method) for coverage in ('normal', 'blackout') for method in METHODS},
              'Requires normal/blackout engineering fits for both methods exactly once')
        check(row.get('same_audit_across_methods') == {'normal':True, 'blackout':True},
              'Primary methods must share preprocessing for each coverage')
        identities = row.get('shared_input_hashes_match', {})
        check(identities and all(value is True for value in identities.values()),
              'Engineering fits must use hash-matched common inputs')
        for item in records:
            check(item.get('status') == 'complete' and item.get('converged') is True and
                item.get('covariance_valid') is True and item.get('native_binary_sha256') == NATIVE_SHA,
                'An engineering fit is failed, unconverged, or uses another binary')
            check(item.get('audit_stable_across_outer_iterations') is True,
                  'Preprocessing changed during an engineering fit')
            result_path = Path(item['result_path'])
            matching_hash(result_path, item['result_sha256'])
            request_path = Path(item.get('request_path', result_path.with_name('request.json')))
            matching_hash(request_path, item['request_sha256'])
            request = read_json(request_path)
            check(request['source_hash'] == item['source_sha256'], 'Engineering request source differs')
            check(not {'evaluation_inputs','calibration_inputs','truth','reference_orbit'} & set(request),
                  'Evaluation-only inputs leaked into an engineering fit')
            normalized = {}
            for provenance in item.get('path_normalized_provenance', []):
                ledger_path = provenance['path']
                matching_hash(ledger_path, provenance['raw_sha256'])
                declared = [entry for entry in request['estimation_inputs'] if entry['path'] == ledger_path]
                check(len(declared) == 1 and declared[0]['sha256'] == provenance['raw_sha256'] and
                    declared[0].get('metadata', {}).get('kind') == 'known_gnss_osb_datum_normalization',
                    'Only the known OSB provenance ledger may undergo path normalization')
                ledger = read_json(ledger_path)
                check(ledger['bias_inputs'] == provenance['verified_bias_inputs'], 'OSB source provenance differs')
                semantic = deepcopy(ledger)
                for bias in semantic['bias_inputs']:
                    matching_hash(bias['path'], bias['sha256'])
                    del bias['path']  # Every numerical correction and source hash remains.
                check(canonical_hash(semantic) == provenance['normalized_sha256'],
                      'OSB ledger differs beyond the explicitly removed source paths')
                normalized[ledger_path] = provenance['normalized_sha256']
            raw_inputs = []
            preparation = None
            for entry in request['estimation_inputs']:
                matching_hash(entry['path'], entry['sha256'])
                if entry.get('metadata', {}).get('kind') == 'native_preparation':
                    check(preparation is None, 'Multiple native preparation manifests in one fit')
                    preparation = read_json(entry['path'])
                else:
                    raw_inputs.append([entry['role'], normalized.get(entry['path'], entry['sha256'])])
            check(sorted(raw_inputs) == item['shared_inputs']['raw_inputs'],
                  'Shared raw-input signature does not match the actual fit request')
            check(preparation is not None, 'Native preparation manifest missing from engineering request')
            for key, digest in item['shared_inputs']['native_inputs'].items():
                matching_hash(preparation['native_paths'][key], digest)
            check(item['shared_inputs']['identity'] == {key:request[key] for key in
                ('force_model_hash','measurement_model_hash','preprocessing_hash','mask_hash')},
                'Shared model/preprocessing identity differs from the fit request')
            actual = read_json(result_path)
            check(actual.get('status') == 'complete' and actual.get('converged') is True and
                  actual.get('covariance_valid') is True and actual.get('native_binary_sha256') == NATIVE_SHA,
                  'Underlying engineering result disagrees with its summary')
            check(actual.get('metadata', {}).get('final_covariance_confirmation') is True,
                  'Final undamped covariance confirmation is missing')
            check(actual.get('metadata', {}).get('orbit_epochs') == 17281 and
                  actual.get('arc', {}).get('duration_seconds') == 86400 and
                  actual.get('arc', {}).get('time_scale') == 'UTC', 'Engineering fit is not a complete UTC day')
            check(actual.get('preprocessing_audit_sha256') == item['audit_sha256'], 'Preprocessing audit hash differs')
            for artifact in actual['artifacts']:
                matching_hash(artifact['path'], artifact['sha256'])
            runtime_path = next(a['path'] for a in actual['artifacts'] if a['role'] == 'native_runtime')
            runtime = read_json(runtime_path)
            check(runtime['source_hash'] == item['source_sha256'], 'Runtime source identity differs')
            last = runtime['outer_iterations'][-1]
            check(last['final_confirmation'] is True and last['criteria_met'] is True and
                  last['covariance_computed'] is True and last['covariance_valid'] is True,
                  'Final native solve has no valid convergence/covariance confirmation')
            controls = runtime['controls']
            check(0 < controls['maximum_orbit_change_m'] <= 3e-5 and
                  0 < controls['maximum_log_density_update'] <= 1e-4 and
                  last['maximum_orbit_change_m'] < controls['maximum_orbit_change_m'] and
                  last['maximum_log_density_update'] < controls['maximum_log_density_update'],
                  'Final raw-update tolerances are not satisfied or were relaxed')
            if item['method'] == 'groops_log_drag_ou':
                check(last.get('density_step', {}).get('scale') == 1., 'Final density confirmation was damped')
            if item['source_sha256'] != snapshot['sha256']:
                reference = item['source_equivalence']
                path = evidence/reference['path']
                matching_hash(path, reference['sha256'])
                equivalent = read_json(path)
                check(equivalent.get('controlled_source_sha256') == item['source_sha256'] and
                      equivalent.get('final_source_sha256') == snapshot['sha256'] and equivalent.get('scope'),
                      'Scoped source-equivalence identities are missing')
                check(equivalent.get('fit_job_identical') is True or
                      item['method'] == 'groops_pulses' and equivalent.get('pulse_branch_equivalent') is True,
                      'No explicit equivalence review covers this fitting method')
                extra_artifacts[str(path)] = file_hash(path)
        for coverage in ('normal', 'blackout'):
            pair = [item['shared_inputs'] for item in records if item['coverage'] == coverage]
            check(pair[0] == pair[1], 'Primary methods did not receive matching shared inputs')
            check(len({item['audit_sha256'] for item in records if item['coverage'] == coverage}) == 1,
                  'Primary method audit hashes disagree')

    def refinement(row):
        current_pass(row)
        records = row.get('records', [])
        check(len(records) == 16 and {(item['orbit'], item['atmosphere'], item['method']) for item in records} ==
              {(orbit, atmosphere, method) for orbit in config.synthetic.orbits
               for atmosphere in config.synthetic.atmospheres for method in METHODS}, 'Incomplete synthetic refinement cells')
        check(all(item.get('passed') is True and item['duration_hours'] == 24 and
            item['max_offgrid_position_difference_m'] < .01*config.synthetic.phase_sigma_m for item in records),
            'A full-day synthetic interpolation refinement failed')

    def flight_refinement(row):
        current_pass(row)
        check({item['method'] for item in row['records']} == METHODS and len(row['records']) == 2,
              'Both full-flight numerical arms are required')
        check(all(len(item['comparisons']) == 2 and all(test['passed'] is True and test['duration_hours'] == 24
              for test in item['comparisons']) for item in row['records']), 'Flight numerical refinement failed')

    def thermal(row):
        check(row.get('passed') is True and len(row.get('records', [])) == 2, 'Thermal refinement incomplete')
        check({item['method'] for item in row['records']} == METHODS, 'Thermal methods incomplete')
        check(all(item['thermal_refinement']['native_binary_sha256'] == NATIVE_SHA and
            item['thermal_refinement']['steps_seconds'] == [.1, .05] and
            item['combined_refinement']['passed'] is True for item in row['records']),
            'Explicit 0.1-second thermal and combined refinement is required')

    require('external-baseline', baseline)
    require('auxiliary-downloads', lambda r:check(r.get('status') == 'complete' and len(r.get('sources', [])) == 56,
                                               'Official example auxiliary inventory incomplete'))
    require('fresh-extension-installation', lambda r:check(r.get('passed') is True and r.get('upstream_commit') == UPSTREAM and
        r.get('second_application_idempotent') is True, 'Fresh installation or idempotence failed'))
    require('native-build', native_build)
    require(tests_key, test_suite)
    require('native-linear-74863', lambda r:(current_pass(r),check(set(r.get('models', {})) == {'pulses','density'} and
        all(m['passed'] is True and m['all_required_checks_present'] is True for m in r['models'].values()),
        'Independent native QR/GTSAM model checks incomplete')))
    require('utc_small_fit_observation_covariance', lambda r:check(r.get('passed') is True and
        r.get('fit_and_probe_native_binary_sha256') == NATIVE_SHA, 'Observation-epoch covariance check failed'))
    require('synthetic-functional-closure-74863', four_synthetic_fits)
    require('nuisance_mapping_74863', lambda r:check(r.get('passed') is True and r.get('binary_sha256') == NATIVE_SHA,
                                                 'Clock/ambiguity/slip recovery check failed'))
    require('utc_engineering_fits_74863', full_utc_fits)
    require('deferred-covariance-74863', lambda r:(current_pass(r),check(len(r['records']) == 4 and
        all(item['passed'] is True for item in r['records']), 'Covariance scheduling equivalence failed')))
    for name in ('utc_observation_covariance', 'utc_prediction_geometry', 'flight_postfit_crd_sessions_74863'):
        require(name, current_pass)
    for name in ('utc_osb_native_regression', 'slr_frame_validation', 'slr_covariance_projection'):
        require(name, lambda r:check(r.get('passed') is True, 'Historical component check failed'))
    require('slr_correction_wiring', lambda r:check(r['range_bias_sign_check']['passed'] is True,
                                                'Fixed external SLR bias-sign check failed'))
    require('slr-correction-freeze-tests', lambda r:check(r.get('status') == 'passed' and
        r['junit_summary']['failures'] == '0' and r['junit_summary']['errors'] == '0', 'SLR correction-freeze tests failed'))
    require('physics-refinement-24h-74863', refinement)
    require('flight-refinement-final', flight_refinement)
    require('thermal-refinement-0p1', thermal)
    require('atmospheric-attitude-regression', lambda r:check(r.get('status') == 'passed', 'Attitude interpolation check failed'))
    require('density-trajectory-derivative-74863', lambda r:check(r.get('status') == 'complete' and
        r.get('native_binary_sha256') == NATIVE_SHA and r.get('evidence_class') == 'diagnostic_only' and
        all(item.get('closed') is True for item in r['records']), 'Scoped derivative diagnostic is incomplete'))

    case_counts = {stage:{split:len(case_matrix(config, stage, split)) for split in ('calibration','evaluation')}
                   for stage in ('synthetic','flight')}
    if case_counts != {'synthetic':{'calibration':48,'evaluation':800},'flight':{'calibration':12,'evaluation':12}}:
        issues.append({'evidence':'production-config', 'error':'Configuration does not have the prescribed full case counts'})
    if config.backend.groops_commit != UPSTREAM:
        issues.append({'evidence':'production-config', 'error':'GROOPS upstream pin differs'})
    executable = shutil.which(config.backend.groops_executable)
    if executable is None or file_hash(executable) != NATIVE_SHA:
        issues.append({'evidence':'production-executable', 'error':'Configured executable is unavailable or has another SHA256 on this host'})
    review = {'status':'ready' if not issues else 'not_ready', 'check_only':args.check_only,
        'source_hash':snapshot['sha256'], 'native_binary_sha256':NATIVE_SHA, 'case_counts':case_counts,
        'checked_evidence':sorted(checked), 'issues':issues,
        'scope':'Precalibration engineering acceptance review only; no scientific accuracy/coverage claim'}
    if args.check_only or issues:
        print(json.dumps(review, indent=2, sort_keys=True))
        return 0 if not issues else 1

    check(not (root/'acceptance-gates.json').exists(), 'Refusing to replace an existing acceptance review')
    frozen = freeze_protocol(config, root)
    check(frozen['native_binary']['sha256'] == NATIVE_SHA, 'Production executable differs')
    groups = {
        'external_baseline':['external-baseline','auxiliary-downloads'],
        'model_correctness':['fresh-extension-installation','native-build',tests_key,'native-linear-74863',
            'utc_small_fit_observation_covariance','density-trajectory-derivative-74863'],
        'pipeline_correctness':['synthetic-functional-closure-74863','nuisance_mapping_74863','utc_engineering_fits_74863',
            'deferred-covariance-74863','utc_observation_covariance','utc_prediction_geometry','utc_osb_native_regression',
            'slr_correction_wiring','slr_frame_validation','slr_covariance_projection',
            'flight_postfit_crd_sessions_74863','slr-correction-freeze-tests'],
        'numerical_accuracy':['physics-refinement-24h-74863','flight-refinement-final','thermal-refinement-0p1',
            'atmospheric-attitude-regression']}
    record = {'schema_version':3, 'protocol_hash':frozen['protocol_hash'], 'native_binary_sha256':NATIVE_SHA,
        'review_helper_sha256':file_hash(__file__), 'configuration_sha256':file_hash(args.config),
        'scope':'Ordered final acceptance review of gates 1–4 only; individual experiments retain their actual original times and source scope.',
        'scientific_comparison_complete':False, 'uncertainty_calibration_claim':False,
        'limitations':['Local covariance is conditional on selected hyperparameters and fixed products.',
            'The native transition omits full non-gravity state gradients. The one-knot propagated density derivative diagnostic is not a global Jacobian error bound.',
            'Historical component checks retain their recorded native identities; the current full suite and matched native experiments cover the final implementation.',
            'Calibration selection, evaluation-input freezes and production results remain separate later stages.'], 'gates':{}}
    for name, names in groups.items():
        artifacts = [{'path':str(evidence/(key+'.json')), 'sha256':file_hash(evidence/(key+'.json'))} for key in names]
        if name == 'pipeline_correctness':
            artifacts += [{'path':path, 'sha256':digest} for path,digest in sorted(extra_artifacts.items())]
        record['gates'][name] = {'passed':True, 'completed_at':datetime.now(timezone.utc).isoformat(),
            'completion_semantics':'Final ordered evidence review; not fabricated experiment chronology.', 'artifacts':artifacts}
    record['evidence_hash'] = canonical_hash(record)
    write_json(root/'acceptance-gates.json', record)
    validate_gates(root, frozen)
    print(json.dumps({'protocol_hash':frozen['protocol_hash'], 'source_hash':frozen['source']['sha256'],
                      'evidence_hash':record['evidence_hash']}, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
