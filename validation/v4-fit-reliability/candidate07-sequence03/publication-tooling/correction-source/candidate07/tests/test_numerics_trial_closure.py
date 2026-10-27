"""Measured native residual exhaustion; rejected trial, never relaxed closure.

Source-only until independently admitted execution. Archived files are actual
failed outputs, while monkeypatched models below are explicitly unit harnesses.
"""
from dataclasses import replace
from pathlib import Path
import gzip
import hashlib
import json
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.numerics import backend
from orbit_poc.numerics.config import Controls
from orbit_poc.numerics.optimizer import NumericalFailure, NumericalTrialClosureFailure, minimize
from test_numerics_optimizer import ProfiledModel


FIXTURE = Path(__file__).parent / 'fixtures/density_tangent_closure'


@pytest.fixture
def archived():
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    for item in manifest['files']:
        data = (FIXTURE / item['fixture']).read_bytes()
        assert len(data) == item['bytes']
        assert hashlib.sha256(data).hexdigest() == item['sha256']
    execution = json.loads((FIXTURE / 'propagate.execution.json').read_text())
    assert execution['config_sha256'] == hashlib.sha256((FIXTURE / 'propagate.xml').read_bytes()).hexdigest()
    assert execution['native_binary_sha256'] == manifest['native_binary_sha256']
    tree = ET.parse(FIXTURE / 'propagate.xml')
    assert tree.findtext('.//orbitPocDerivativeProfile') == 'synthetic_complete_v1'
    assert tree.findtext('.//inputfileOrbit').endswith('point-005-trial-002/closure-02/orbit.dat')
    rows = []
    with gzip.open(FIXTURE / 'previous-orbit.txt.gz', 'rt') as stream:
        for line in stream:
            try:
                row = [float(value) for value in line.split()]
            except ValueError:
                continue
            if len(row) == 10:
                rows.append(row)
    values = np.asarray(rows)
    assert values.shape == (720, 10)
    return {'log': (FIXTURE / 'propagate.log').read_text(), 'execution': execution,
            'previous_states': values[:, 1:7], 'derivative_profile': 'synthetic_complete_v1'}


def test_exact_archived_residual_exhaustion_is_distinct_and_does_not_reclassify_legacy_errors(archived):
    result = backend.wide_tangent_closure_failure_evidence(**archived)
    assert result['failure_kind'] == 'wide_returned_binary64_residual_exhaustion'
    assert result['relative_residual'] == 1.0644281392730035e-05
    assert result['tolerance'] == 2e-12 and result['iterations'] == 120
    assert result['solve_role'] == 'physical_correction' and result['column'] == 0
    assert result['duration_seconds'] == 3595 and result['samples'] == 720
    assert result['recoverable_only_during_trial'] is True
    assert result['failed_state_accepted'] is False and result['native_thresholds_unchanged'] is True
    assert backend.native_failure_reason(archived['log'], archived['execution']) == 'native_failure'
    assert backend.reference_domain_failure_evidence(**archived, gm=398600441500000.) is None
    previous = json.loads((FIXTURE / 'previous-derivatives.json').read_text())
    assert previous['maximum_tangent_relative_residual'] == 9.8285642212607614e-13
    assert previous['maximum_tangent_iterations'] == 3


@pytest.mark.parametrize('change', [
    {'returncode': -9}, {'returncode': -11}, {'returncode': 137}, {'returncode': 2},
    {'returncode': 0}, {'returncode': True}, {'timed_out': True}, {'timed_out': None},
    {'native_binary_sha256': '0' * 64}, {'native_binary_sha256': None},
])
def test_unknown_binary_resource_crash_and_other_exits_are_fatal(archived, change):
    archived['execution'] = {**archived['execution'], **change}
    assert backend.wide_tangent_closure_failure_evidence(**archived) is None


@pytest.mark.parametrize('change', [
    {'execution': None}, {'previous_states': None},
    {'previous_states': np.empty((0, 6))}, {'previous_states': np.ones((1, 6))},
    {'previous_states': np.ones((2, 7))}, {'previous_states': np.ones(6)},
    {'previous_states': np.full((2, 6), float('nan'))},
    {'previous_states': np.full((2, 6), float('inf'))}, {'previous_states': [['bad']]},
    {'derivative_profile': 'flight_gravity_drag_v1'}, {'derivative_profile': 'legacy_v3'},
    {'log': None}, {'log': 'x' * 65537},
])
def test_missing_generated_state_and_unqualified_context_are_fatal(archived, change):
    assert backend.wide_tangent_closure_failure_evidence(**{**archived, **change}) is None


@pytest.mark.parametrize('old,new', [
    ('relative_residual=1.0644281392730035e-05', 'relative_residual=nan'),
    ('relative_residual=1.0644281392730035e-05', 'relative_residual=inf'),
    ('relative_residual=1.0644281392730035e-05', 'relative_residual=1e999'),
    ('relative_residual=1.0644281392730035e-05', 'relative_residual=2e-12'),
    ('relative_residual=1.0644281392730035e-05', 'relative_residual=1e-12'),
    ('tolerance=2e-12', 'tolerance=2e-11'), ('iterations=120', 'iterations=119'),
    ('iterations=120', 'iterations=121'), ('solve_role=physical_correction', 'solve_role=state_transition'),
    ('column=0', 'column=1'), ('duration_seconds=3595', 'duration_seconds=0'),
    ('duration_seconds=3595', 'duration_seconds=nan'),
    ('PreprocessingVariationalEquation', 'GnssProcessing'), ('(computeArc)', '(otherOperation)'),
    ('****** Error ******', 'another error'),
    ('wide tangent returned double state did not meet true residual tolerance', 'invalid wide tangent input'),
])
def test_exact_native_failure_contract_is_required(archived, old, new):
    assert old in archived['log']
    archived['log'] = archived['log'].replace(old, new)
    assert backend.wide_tangent_closure_failure_evidence(**archived) is None


@pytest.mark.parametrize('extra', ['Segmentation fault', 'Cannot open input file', '****** Error ******'])
def test_extra_terminal_or_nested_error_is_not_hidden(archived, extra):
    for text in (archived['log'] + extra + '\n',
                 archived['log'].replace('wide tangent returned', extra + '\nwide tangent returned')):
        assert backend.wide_tangent_closure_failure_evidence(**{**archived, 'log': text}) is None


@pytest.mark.parametrize('first_closure_fails', [False, True])
def test_native_close_preserves_evidence_state_and_factor_and_requires_preceding_closure(
        tmp_path, monkeypatch, archived, first_closure_fails):
    # Controlled API unit harness, not a replayed propagation or native result.
    source = ET.parse(FIXTURE / 'propagate.xml')
    path = tmp_path / 'variational.xml'
    source.write(path)
    folder = tmp_path / 'controlled-trial'
    folder.mkdir()
    initial_reference = tmp_path / 'accepted-orbit.dat'
    initial_reference.write_bytes(b'accepted reference sentinel, unchanged')
    state = backend.PhysicalState(np.arange(6.), np.zeros(61), initial_reference)
    initial_copy, force_copy = state.initial.copy(), state.force.copy()
    model = backend.NativeModel.__new__(backend.NativeModel)
    model.density, model.derivatives, model.propagations = True, 'synthetic_complete_v1', 0
    model.protected_factor = tmp_path / 'accepted.R.bin'
    model.protected_factor.write_bytes(b'accepted factor sentinel, unchanged')
    monkeypatch.setattr(model, '_evaluation', lambda *a, **kw: [])
    monkeypatch.setattr(backend, 'compact_closed_closures', lambda *a: None)
    monkeypatch.setattr(backend.native, '_orbit', lambda *a: (np.arange(720.), archived['previous_states']))
    calls = []

    def execute(tree, iteration, label):
        assert label == 'propagate'
        calls.append(tree.find('.//PreprocessingVariationalEquation/inputfileOrbit').text)
        if len(calls) == 1 and not first_closure_fails:
            (iteration / 'orbit.dat').write_bytes(b'controlled preceding closure reference sentinel')
            return
        (iteration / 'propagate.log').write_text(archived['log'])
        try:
            raise backend.native.NativeExecutionError('archived returned-state residual exhaustion', execution=archived['execution'])
        except backend.native.NativeExecutionError as error:
            raise NumericalFailure('native_failure', str(error)) from error

    monkeypatch.setattr(model, 'execute', execute)
    with pytest.raises(NumericalFailure) as caught:
        model._close(state, {'configs': {'variational': str(path)}, 'date': '2024-04-24'}, folder, False)
    assert model.protected_factor.read_bytes() == b'accepted factor sentinel, unchanged'
    assert initial_reference.read_bytes() == b'accepted reference sentinel, unchanged'
    np.testing.assert_array_equal(state.initial, initial_copy)
    np.testing.assert_array_equal(state.force, force_copy)
    assert not (folder / 'trial-domain-failure.json').exists()
    receipt = folder / 'trial-closure-failure.json'
    if first_closure_fails:
        assert not isinstance(caught.value, NumericalTrialClosureFailure)
        assert caught.value.reason == 'native_failure' and not receipt.exists()
        assert calls == [str(initial_reference)]
    else:
        assert isinstance(caught.value, NumericalTrialClosureFailure)
        record = json.loads(receipt.read_text())
        assert record == caught.value.evidence and record['closure_iteration'] == 2
        assert calls == [str(initial_reference), str(folder / 'closure-01/orbit.dat')]
        assert record['reference_orbit'] == calls[1]
        assert record['reference_orbit_sha256'] == hashlib.sha256(Path(calls[1]).read_bytes()).hexdigest()
        assert record['native_binary_sha256'] == archived['execution']['native_binary_sha256']
        assert record['propagation_config_sha256'] == archived['execution']['config_sha256']
        assert record['propagation_log']['role'] == 'failed_numerical_closure_log'
        assert (folder / 'closure-02/propagate.log').read_text() == archived['log']


def test_typed_trial_rejection_preserves_accepted_linearization_and_existing_damping(archived):
    evidence = backend.wide_tangent_closure_failure_evidence(**archived)

    class FailedTrials(ProfiledModel):
        def __init__(self):
            super().__init__()
            self.accepted, self.before_retry = [], []

        def accept(self, point):
            self.accepted.append(point)

        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-') and int(label[6:]) <= 4:
                point = self.accepted[-1]
                self.before_retry.append((point.state, point.factor.copy(), point.rhs.copy(),
                                          point.scales.copy(), point.support_hash))
                raise NumericalTrialClosureFailure('archived residual exhaustion', evidence)
            return super().evaluate(state, label, tighter)

    model = FailedTrials()
    result = minimize(model, 0.)
    assert result['converged'], result
    rejected = result['history'][:4]
    assert [row['damping'] for row in rejected] == pytest.approx([.001, .002, .008, .064])
    assert all(not row['accepted'] and row['trial_closure_evidence'] == evidence for row in rejected)
    assert all(row['reason'] == 'numerical_trial_closure' and 'trial_domain_evidence' not in row for row in rejected)
    assert all(row['actual_reduction'] is None and row['gain_ratio'] is None for row in rejected)
    assert len({row['objective_before'] for row in rejected}) == 1
    assert result['history'][4]['damping'] == pytest.approx(1.024)
    for state, factor, rhs, scale, support in model.before_retry:
        assert state == 0. and support == 'fixed-observations'
        np.testing.assert_array_equal(factor, model.before_retry[0][1])
        np.testing.assert_array_equal(rhs, model.before_retry[0][2])
        np.testing.assert_array_equal(scale, model.before_retry[0][3])


@pytest.mark.parametrize('phase', ['initial', 'repeat', 'closure-refinement', 'confirmation', 'finish'])
def test_same_typed_failure_outside_trial_is_fatal_without_covariance(archived, phase):
    evidence = backend.wide_tangent_closure_failure_evidence(**archived)

    class FailedPhase(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label == phase:
                raise NumericalTrialClosureFailure('controlled nontrial exhaustion', evidence)
            return super().evaluate(state, label, tighter)

        def finish(self, point):
            if phase == 'finish':
                raise NumericalTrialClosureFailure('controlled final exhaustion', evidence)
            return super().finish(point)

    model = FailedPhase()
    result = minimize(model, 0.)
    assert result['status'] == 'numerical_trial_closure'
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized
    assert all(row.get('reason') != 'numerical_trial_closure' for row in result['history'])


def test_same_reason_without_typed_evidence_is_fatal():
    class Untyped(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-'):
                raise NumericalFailure('numerical_trial_closure', 'no typed evidence')
            return super().evaluate(state, label, tighter)

    model = Untyped()
    result = minimize(model, 0.)
    assert result['status'] == 'numerical_trial_closure' and not result['history']
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized


@pytest.mark.parametrize('wall_expires', [False, True])
def test_repeated_numerical_failure_cannot_escape_existing_budgets(archived, wall_expires):
    evidence = backend.wide_tangent_closure_failure_evidence(**archived)
    elapsed = [0.]

    class AlwaysInvalid(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-'):
                if wall_expires:
                    elapsed[0] = Controls().wall_time_seconds + 1.
                raise NumericalTrialClosureFailure('controlled trial exhaustion', evidence)
            return super().evaluate(state, label, tighter)

    model = AlwaysInvalid()
    result = minimize(model, 0., controls=replace(Controls(), maximum_trial_evaluations=3), clock=lambda: elapsed[0])
    assert result['status'] == ('timeout' if wall_expires else 'iteration_limit')
    assert result['trial_evaluations'] == (1 if wall_expires else 3) and result['accepted_iterations'] == 0
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized
