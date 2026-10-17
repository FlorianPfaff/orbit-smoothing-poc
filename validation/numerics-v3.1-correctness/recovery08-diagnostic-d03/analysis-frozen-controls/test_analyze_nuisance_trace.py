from copy import deepcopy
from decimal import Decimal as D, localcontext
import importlib.util
import json
from pathlib import Path
import struct
import sys
import pytest

P = Path(__file__).with_name('analyze_nuisance_trace.py')
spec = importlib.util.spec_from_file_location('d03_analysis', P)
a = importlib.util.module_from_spec(spec); sys.modules[spec.name] = a; spec.loader.exec_module(a)


@pytest.fixture(autouse=True)
def precision():
    with localcontext() as c:
        c.prec = 110
        yield


def identity(phase, alpha=0):
    return (phase+str(alpha), {'baseline': 1, 'joint': 2, 'trial': 3}[phase], phase, D(alpha), '0')


def equation(phase, alpha=0):
    e = a.Ledger(identity(phase, alpha), (0, 4, 5), 1)
    def scalar(name, value, row=0, col=0, comp=''):
        e.values[comp, name, row, col] = D(value)
    def pair(name, value, row=0):
        scalar(name+'.high', value, row); scalar(name+'.low', 0, row)
    change = D(alpha)*D('.01'); stec = D(2)+D(alpha)*D('.003')
    dstec = D('.1')+D(alpha)*D('.003'); clock = D(2)+change
    scalar('observed', 100); scalar('sigma', '.5'); scalar('transmitter_scale', 1)
    scalar('receiver_clock_seconds', clock/a.C); scalar('transmitter_clock_seconds', 0)
    scalar('rDotTrans', 0); scalar('rDotRecv', 0)
    for name, val in [('range_distance', D(97)), ('range_relativistic_dot', D(0)), ('range_clock', clock)]: pair(name, val)
    scalar('range_shapiro', 0)
    rr = D(100)-D(97)-clock; recv = rr-D('.3'); trans = recv-D('.15'); amb = trans-D('.1'); model = amb-D('.1')*stec
    for name, val in [('range_residual', rr), ('after_receiver_correction', recv), ('after_transmitter_correction', trans),
                      ('after_ambiguity', amb), ('after_models', model)]: pair(name, val)
    for comp, bias, pattern in [('receiver_correction', '.2', '.1'), ('transmitter_correction', '.1', '.05')]:
        scalar('signal_bias_operand', bias, comp=comp); scalar('antenna_pattern_operand', pattern, comp=comp)
    scalar('signal_composition', 1)
    scalar('STEC', stec); scalar('dSTEC', dstec); scalar('sigmaSTEC', 2)
    for name, val in [('f2', 1), ('f3', 1), ('f4', 1), ('Ap', '.1'), ('s', 0), ('r', 0), ('bending', 0)]: scalar('ionosphere_'+name, val)
    for flag in ('apply1stOrder', 'apply2ndOrder', 'apply3rdOrder', 'applyBending'): scalar(flag, flag == 'apply1stOrder')
    # Native coefficient is rounded binary64. Model expansion must use that
    # coefficient, exactly as the source does, not the decimal literal 0.1.
    coeff = a.rounded64(D('.1')); model = amb-coeff*stec
    pair('after_models', model)
    pair('retained_original_precise', model*2); pair('complete_original_precise', model*2)
    pair('retained_original_precise', -dstec/2, 1); pair('complete_original_precise', -dstec/2, 1)
    scalar('retained_original_native', a.rounded64(model*2)); scalar('retained_original_native', a.rounded64(-dstec/2), 1)
    scalar('complete_original_local_design', coeff*2); scalar('complete_original_local_design', '.5', 1)
    return e


def record(ident, stage, value, row=0, col=0, block=(a.SENTINEL,)*3, comp='', event=1):
    return a.Record(ident[0], 1, 'qr.4', ident[2], ident[3], block, row, comp, stage, 'double', col, D(value), ident[1], event, ident[4])


def fixture():
    b = equation('baseline'); j = deepcopy(b); j.identity = identity('joint')
    j.values = {k: v for k, v in j.values.items() if not k[1].startswith('retained_original')}
    for row, val in a.vector(b.pairs('complete_original_precise')).items():
        j.values['', 'joint_original_precise.high', row, 0] = val
        j.values['', 'joint_original_precise.low', row, 0] = D(0)
    coeff = a.rounded64(D('.1'))
    for name, row, col, val in [('joint_global_design', 0, 0, D(2)), ('joint_global_design', 1, 0, D(0)),
                                ('joint_global_requested_block', 0, 0, D('.01')),
                                ('joint_local_design', 0, 0, coeff*2), ('joint_local_design', 1, 0, D('.5')),
                                ('joint_local_requested', 0, 0, D('.003')),
                                ('joint_total_native_influence', 0, 0, a.rounded64(D('.02')+coeff*2*D('.003'))),
                                ('joint_total_native_influence', 1, 0, a.rounded64(D('.0015')))]:
        j.values['', name, row, col] = val
    t0, t1 = equation('trial', 0), equation('trial', 1)
    updates = {j.identity: [record(j.identity, 'parameter_requested', '.01')]}
    for t in (t0, t1):
        updates[t.identity] = [record(t.identity, 'parameter_before', 0), record(t.identity, 'parameter_after', D('.01')*t.identity[3])]
    constraints = {}
    for e in (b, t0, t1):
        alpha = e.identity[3]
        constraints[e.identity] = {(5, 7): {('constraint_context', 0): 'fixture_prior', ('constraint_original_rhs', 0): D('-.4')-D('.002')*alpha,
                                          ('constraint_original_coefficient', 0): D('.2')}}
    return [b, j, t0, t1], updates, constraints, {'original_objective_rows': 3}, {'full_step_prediction': 0.0094}


def test_complete_all_row_cost_and_component_conservation():
    r = a.analyze(*fixture())
    assert r['original_objective_rows'] == 3
    assert r['observation_rows'] == 2 and r['separate_constraint_rows'] == 1
    zero, full = r['trials']; assert D(zero['actual_reduction']) == 0
    assert abs(D(full['component_accounting_closure'])) < D('1e-80')
    assert abs(D(full['actual_minus_requested_prediction'])) < D('1e-80')
    assert full['stored_state_attribution']['STEC_coefficient_geometry_change']['normalized_residual']['count'] == 1
    assert full['stored_native_observation_model_complete'] is True
    assert abs(D(full['actual_minus_stored_native_prediction'])) < D('1e-80')
    assert abs(D(full['prediction_error_contribution_closure'])) < D('1e-80')


@pytest.mark.parametrize('mutation', ['missing_trial', 'missing_row', 'changed_weights', 'changed_observation', 'changed_constraint', 'duplicate_baseline', 'wrong_count', 'wrong_block_mapping', 'changed_joint'])
def test_missing_or_changed_support_fails_closed(mutation):
    eq, up, co, fa, se = fixture()
    if mutation == 'missing_trial': eq.pop()
    elif mutation == 'missing_row': eq[-1].values.pop(('', 'retained_original_precise.low', 1, 0))
    elif mutation == 'changed_weights': eq[-1].values['', 'sigma', 0, 0] = D(3)
    elif mutation == 'changed_observation': eq[-1].values['', 'observed', 0, 0] = D(99)
    elif mutation == 'changed_constraint': co[eq[-1].identity][5, 7]['constraint_original_coefficient', 0] = D('.3')
    elif mutation == 'duplicate_baseline': eq.append(deepcopy(eq[0]))
    elif mutation == 'wrong_count': fa['original_objective_rows'] = 4
    elif mutation == 'wrong_block_mapping': eq[1].values['', 'joint_global_requested_block', 0, 0] = D(2)
    elif mutation == 'changed_joint': eq[1].values['', 'joint_original_precise.low', 0, 0] = D('1e-20')
    with pytest.raises(ValueError): a.analyze(eq, up, co, fa, se)


def test_global_block_offset_is_added_to_vector_row():
    assert a.dot_rows({(0, 7): D(2), (1, 8): D(3)}, {7: D(4), 8: D(5)}) == {0: D(8), 1: D(15)}
    with pytest.raises(ValueError): a.dot_rows({(0, 7): D(1)}, {0: D(1)})


def test_exact_hex_preserves_extended_low_bits():
    assert a.exact_hex('0x8.000000000000001p-3') == D(1)+D(2)**-63
    assert a.exact_hex('-0x0p+0').is_signed()
    for v in ('nan', 'inf', '0.5', '0x1p999999'):
        with pytest.raises(ValueError): a.exact_hex(v)


def line(stage='observed', val=1., row=0, event=1, kind='double', component='', phase='baseline', alpha='0x0p+0'):
    bits = struct.pack('>d', val).hex() if kind == 'double' else '-'
    value = val.hex() if kind == 'double' else str(val)
    return '\t'.join(['qr.4', phase, alpha, '0', '4', '5', str(row), component, stage, kind, '0', value, bits, '1', str(event), '0'])+'\n'


def test_parser_text_bits_and_monotone_events(tmp_path):
    p = tmp_path/'trace.tsv'; p.write_text(line()+line('parameter_name', 'receiver.clock', event=2, kind='text'))
    rs = list(a.records(p)); assert rs[1].value == 'receiver.clock'
    p.write_text(line()+line(event=1))
    with pytest.raises(ValueError): list(a.records(p))
    p.write_text(line().replace('3ff0000000000000', '4000000000000000'))
    with pytest.raises(ValueError): list(a.records(p))


def test_streaming_retained_capture_and_recovery_only_separate(tmp_path):
    p = tmp_path/'trace.tsv'
    p.write_text(line()+line('retained_original_precise.high', 1., event=2, kind='double')+
                 line('observed', 2., event=3)+line('receiver_center_high', 7., event=4))
    eq, up, co, counts = a.load_trace([p])
    assert len(eq) == 2 and len(eq[0].matrix('retained_original_precise.high')) == 1
    assert not eq[1].matrix('retained_original_precise.high')
    assert counts['geometry_records'] == 1


def test_native_raw_clock_and_stec_update_losses():
    i = identity('trial', 1); b = (0, a.SENTINEL, 4)
    rs = [record(i, n, v, block=b, event=k) for k, (n, v) in enumerate([
        ('clock_seconds_before', 1), ('clock_requested_metres', '1e-9'), ('clock_requested_seconds', D('1e-9')/a.C), ('clock_seconds_after', 1),
        ('local_STEC_before', 2), ('local_dSTEC_before', 1), ('local_STEC_requested', '1e-30'), ('local_STEC_after', 2), ('local_dSTEC_after', 1)], 1)]
    r = a.summarize_raw_updates(rs)
    assert D(r['clock_store_loss_metres']['sum']) == D('-1e-9')
    assert D(r['local_STEC_store_loss']['sum']) == D('-1e-30')


def test_bias_mapping_targets_native_array_slot():
    i = identity('trial', 1)
    rs = [record(i, 'bias_global_start', 10), record(i, 'bias_update_before', 1, row=0), record(i, 'bias_update_before', 2, row=1),
          record(i, 'bias_requested', '.01'), record(i, 'bias_type_mapping', 1),
          record(i, 'bias_update_after', 1, row=0), record(i, 'bias_update_after', '2.009', row=1)]
    r = a.summarize_raw_updates(rs)
    assert D(r['bias_store_loss_metres']['sum']) == D('-.001')


def test_constraint_cost_cannot_disappear():
    eq, up, co, fa, se = fixture(); co.clear()
    with pytest.raises(ValueError, match='support incomplete'): a.analyze(eq, up, co, fa, se)


def test_unknown_stec_branch_is_unavailable_not_invented():
    e = equation('baseline'); e.values['', 'after_models.high', 0, 0] += D('.01')
    assert a.stec_coefficients(e, 0) is None


def test_coefficient_geometry_and_state_effect_are_distinct():
    b, t = equation('baseline'), equation('trial', 1)
    t.values['', 'ionosphere_Ap', 0, 0] = D('.11')
    coeff = a.rounded64(D('.11')); stec = t.scalar('STEC')
    model = t.pairs('after_ambiguity')[0, 0]-coeff*stec
    t.values['', 'after_models.high', 0, 0] = model
    for n in ('retained_original_precise', 'complete_original_precise'): t.values['', n+'.high', 0, 0] = 2*model
    q = a.stored_state_attribution(b, t, 0)
    assert q['STEC_coefficient_geometry_change'] != 0
    assert abs(q['STEC_decomposition_closure']) < D('1e-80')


def test_geometry_missing_is_explicit():
    assert a.geometry_diagnostics(equation('baseline'))['available'] is False


def test_geometry_velocity_narrowing_and_time_sum_separate():
    e = equation('baseline'); g = e.geometry
    for name, vv in [('receiver_position_high', [0, 0, 0]), ('receiver_position_low', [0, 0, 0]),
                     ('transmitter_position_high', [97, 0, 0]), ('transmitter_position_low', [0, 0, 0]),
                     ('transmitter_velocity', [1, 0, 0])]:
        for i, v in enumerate(vv): g['light_time', name, i, 0] = D(v)
    for i, v in enumerate([D(1)+D('1e-20'), D(0), D(0)]):
        g['transmitter_velocity_interpolation', 'polynomial_precise_result.high', 0, i] = v
        g['transmitter_velocity_interpolation', 'polynomial_precise_result.low', 0, i] = D(0)
    for n, v in [('travel_seconds', '.1'), ('receiver_clock_seconds', '.2'), ('duration_seconds', '.30000000000000000001')]:
        g['light_time', n, 0, 0] = D(v)
    r = a.geometry_diagnostics(e)
    assert D(r['range_sqrt_representation_error_m']) == 0
    assert D(r['velocity_narrowing_relativistic_range_m']) == -2*D(97)*D('1e-20')/a.C
    assert D(r['duration_addition_error_s']) == D('1e-20')


def test_clock_derivative_omission_is_not_called_rounding():
    b, t = equation('baseline'), equation('trial', 1)
    t.values['', 'range_shapiro', 0, 0] = D('1e-15')
    t.values['', 'range_residual.high', 0, 0] -= D('1e-15')
    q = a.stored_state_attribution(b, t, 0)
    assert q['relativistic_plus_shapiro_change'] == D('2e-15')
    assert q['actual_range_minus_native_clock_design_at_stored_state'] != 0


def test_changed_composition_withholds_stored_state_complete_claim():
    b, t = equation('baseline'), equation('trial', 1)
    t.values['', 'signal_composition', 0, 0] += D('1e-9')
    assert 'stored_state_linear_model_change' not in a.stored_state_attribution(b, t, 0)


def test_vtec_requested_versus_actual_update_arithmetic():
    i = identity('trial', 1)
    seq = [('VTEC_STEC_before', 1), ('VTEC_requested', '.001'), ('VTEC_gradient_x_requested', '.002'), ('VTEC_gradient_y_requested', '.003'),
           ('VTEC_STEC_after', '1.001'), ('VTEC_mapping', 2), ('VTEC_cos', '.5'), ('VTEC_sin', '.25')]
    rr = [record(i, n, v, event=k) for k, (n, v) in enumerate(seq, 1)]
    assert D(a.summarize_raw_updates(rr)['VTEC_arithmetic_and_store_loss']['sum']) == D('-.0045')


def test_raw_ambiguity_update_representation_loss():
    i = identity('trial', 1)
    rr = [record(i, n, v, event=k) for k, (n, v) in enumerate([
        ('ambiguity_global_start', 20), ('ambiguity_update_before', 1), ('ambiguity_update_requested', '1e-20'), ('ambiguity_update_after', 1)], 1)]
    assert D(a.summarize_raw_updates(rr)['ambiguity_store_loss_cycles']['sum']) == D('-1e-20')


def test_analysis_paths_cannot_swap_uncompared_factor(tmp_path):
    eq = {'directories': ['old', 'off', str(tmp_path)]}
    assert a.verify_analysis_paths(eq, tmp_path/'qr.4.factor.json', tmp_path/'qr.4.nuisance_line_search.json') == str(tmp_path/'qr.4')
    with pytest.raises(ValueError): a.verify_analysis_paths(eq, tmp_path/'qr.3.factor.json', tmp_path/'qr.4.nuisance_line_search.json')


def test_equivalence_requirement_fails_closed(tmp_path):
    p = tmp_path/'eq.json'; p.write_text(json.dumps({'passed': True, 'checks': [{}]*52}))
    with pytest.raises(ValueError): a.verify_equivalence(p)


def test_equivalence_pins_checked(tmp_path):
    p = equivalence_fixture(tmp_path)
    assert a.verify_equivalence(p)['passed']
    (tmp_path/'on/qr.4.factor.json').write_text('changed')
    with pytest.raises(ValueError): a.verify_equivalence(p)


def equivalence_fixture(tmp_path):
    dirs = [tmp_path/x for x in ('reference', 'off', 'on')]
    for d in dirs: d.mkdir()
    suffixes = ['R.bin', 'z.bin', 'rhs.bin', 'parameters.tsv', 'delta.tsv', 'singular_values.txt', 'profile.json',
                'bias_coordinates.tsv', 'nuisance_coordinates.tsv', 'receiver_times.tsv']
    checks = []
    for gen in range(1, 5):
        for suffix in suffixes:
            paths = [d/f'qr.{gen}.{suffix}' for d in dirs]
            for p in paths: p.write_bytes(('frozen numerical data '+str(gen)+suffix).encode())
            checks.append({'kind': 'exact_bytes_or_original_retired_factor_identity', 'files': [a.artifact(p) for p in paths]})
        paths = [d/f'qr.{gen}.rows.tsv' for d in dirs]
        for p in paths: p.write_text('original rows')
        checks.append({'kind': 'exact_decompressed_row_bytes', 'sha256': a.artifact(paths[0])['sha256'], 'files': [a.artifact(p) for p in paths]})
        for suffix in ('factor.json', 'nuisance_line_search.json'):
            paths = [d/f'qr.{gen}.{suffix}' for d in dirs]
            for p in paths:
                v = {'keep_intermediate_factors': False, 'spool_directory': str(p.parent)} if suffix == 'factor.json' else {'full_step_prediction': 1}
                p.write_text(json.dumps(v))
            exclusions = ['spool_directory'] if suffix == 'factor.json' else sorted(['peak_child_rss_bytes', 'child_user_seconds', 'child_system_seconds'])
            checks.append({'kind': 'exact_json_except_explicit_operational_fields', 'excluded_keys': exclusions, 'files': [a.artifact(p) for p in paths]})
    (dirs[0]/'qr.5.factor.json').write_text('{}')
    stops = []
    for d in dirs[1:]:
        p = d/'qr.diagnostic-incomplete.json'; p.write_text(json.dumps({'schema': 'orbit-poc-d03-generation-stop-v1', 'diagnostic_only': True,
            'scientific_complete': False, 'completed_generations': 4, 'reason': 'bounded diagnostic stopped before generation5'}))
        stops.append(a.artifact(p))
    p = tmp_path/'eq.json'; p.write_text(json.dumps({'schema': 'orbit-poc-d03-equivalence-v1', 'passed': True, 'diagnostic_only': True,
        'scientific_validation_complete': False, 'last_generation': 4, 'directories': [str(d) for d in dirs], 'stop_receipts': stops, 'checks': checks}))
    return p


@pytest.mark.parametrize('change', ['empty_check', 'wrong_kind', 'swapped_file', 'missing_stop', 'bad_exclusion', 'changed_numeric', 'missing_generation'])
def test_complete_equivalence_structure_is_required(tmp_path, change):
    p = equivalence_fixture(tmp_path); v = json.loads(p.read_text())
    if change == 'empty_check': v['checks'][3] = {}
    elif change == 'wrong_kind': v['checks'][3]['kind'] = 'different'
    elif change == 'swapped_file': v['checks'][3]['files'][0] = v['checks'][3]['files'][1]
    elif change == 'missing_stop': v['stop_receipts'].pop()
    elif change == 'bad_exclusion': v['checks'][12]['excluded_keys'].append('full_step_prediction')
    elif change == 'changed_numeric':
        obj = v['checks'][12]['files'][2]; Path(obj['path']).write_text('{"full_step_prediction":2}'); v['checks'][12]['files'][2] = a.artifact(Path(obj['path']))
    elif change == 'missing_generation': (tmp_path/'reference/qr.5.factor.json').unlink()
    p.write_text(json.dumps(v))
    with pytest.raises(ValueError): a.verify_equivalence(p)


def test_reference_retired_factor_requires_bound_identity(tmp_path):
    p = equivalence_fixture(tmp_path); v = json.loads(p.read_text()); obj = v['checks'][0]['files'][0]
    Path(obj['path']).unlink(); rp = tmp_path/'reference/qr.1.retention.json'
    rp.write_text(json.dumps({'schema': 'orbit-poc-native-factor-retention-v1', 'status': 'completed',
                             'artifacts': [{**obj, 'role': 'superseded_triangular_factor'}]}))
    obj['retention_receipt'] = a.artifact(rp); p.write_text(json.dumps(v))
    assert a.verify_equivalence(p)['passed']
    rr = json.loads(rp.read_text()); rr['artifacts'][0]['sha256'] = '0'*64; rp.write_text(json.dumps(rr)); obj['retention_receipt'] = a.artifact(rp); p.write_text(json.dumps(v))
    with pytest.raises(ValueError): a.verify_equivalence(p)


def test_existing_binary_cannot_hide_behind_retirement_receipt(tmp_path):
    p = equivalence_fixture(tmp_path); v = json.loads(p.read_text()); obj = v['checks'][0]['files'][0]
    rp = tmp_path/'reference/qr.1.retention.json'
    rp.write_text(json.dumps({'schema': 'orbit-poc-native-factor-retention-v1', 'status': 'completed',
                             'artifacts': [{**obj, 'role': 'superseded_triangular_factor'}]}))
    obj['retention_receipt'] = a.artifact(rp); p.write_text(json.dumps(v))
    Path(obj['path']).write_text('changed binary restored at old path')
    with pytest.raises(ValueError, match='existing binary'): a.verify_equivalence(p)


def test_target_and_matvec_effects_telescope_to_native_qr_difference():
    r = a.analyze(*fixture()); p = r['prediction_arithmetic_comparison']
    total = sum(D(p[n]) for n in ('precise_minus_rounded_target_effect',
        'decimal_minus_native_joint_effect_at_rounded_targets', 'rounded_native_joint_minus_qr_factor_prediction'))
    assert abs(total-D(r['requested_prediction_minus_native'])) < D('1e-80')


def test_binary64_significand_rounding_ties_even():
    one = D(1); half = D(2)**-64
    assert a.rounded_binary(one+half) == one
    assert a.rounded_binary(one+3*half) == one+D(2)**-62
    assert a.rounded_binary(-one-half) == -one
    assert a.rounded_binary(D('1e-20'), 53) == a.rounded64(D('1e-20'))


def test_distance_to_query_sequence_excludes_later_convergence_distance():
    dist = D(20200000)+D('1e-12'); rd = a.rounded_binary(dist); travel = a.rounded_binary(rd/a.C)
    clk = D('1e-8'); duration = a.rounded_binary(travel+clk)
    seq = [('travel_seconds', D('.067')), ('receiver_clock_seconds', clk), ('duration_seconds', D('.067')+clk),
           ('distance_before_narrowing.high', D(20200000)), ('distance_before_narrowing.low', D('1e-12')),
           ('travel_seconds', travel), ('receiver_clock_seconds', clk), ('duration_seconds', duration),
           ('distance_before_narrowing.high', D('1e-11')), ('distance_before_narrowing.low', D('1e-30'))]
    qs = a.light_time_queries([(i, 'light_time', n, val) for i, (n, val) in enumerate(seq, 1)])
    assert len(qs) == 2 and qs[0]['seed_query']
    assert qs[1]['distance_cast_error_m'] == rd-dist
    assert qs[1]['native_division_replay_error_s'] == 0
    assert qs[1]['native_duration_replay_error_s'] == 0
    assert qs[1]['total_query_arithmetic_error_s'] == duration-clk-dist/a.C
