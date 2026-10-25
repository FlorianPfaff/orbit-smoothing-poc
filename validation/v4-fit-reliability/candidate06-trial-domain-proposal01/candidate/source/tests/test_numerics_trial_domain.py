"""Archived domain failure, narrowly typed recovery and unchanged rollback."""
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
from orbit_poc.numerics.optimizer import NumericalFailure, PhysicalTrialDomainFailure, minimize
from test_numerics_optimizer import ProfiledModel


FIXTURE = Path(__file__).parent / 'fixtures/density_reference_domain'


@pytest.fixture
def archived():
    manifest = json.loads((FIXTURE / 'manifest.json').read_text())
    for item in manifest['files']:
        assert hashlib.sha256((FIXTURE / item['fixture']).read_bytes()).hexdigest() == item['sha256']
    rows = []
    for line in gzip.open(FIXTURE / 'orbit.txt.gz', 'rt'):
        try:
            row = [float(value) for value in line.split()]
        except ValueError:
            continue
        if len(row) == 10:
            rows.append(row)
    values = np.asarray(rows)
    return {'log': (FIXTURE / 'propagate.log').read_text(),
            'execution': json.loads((FIXTURE / 'propagate.execution.json').read_text()),
            'previous_states': values[:, 1:7], 'derivative_profile': 'synthetic_complete_v1',
            'gm': manifest['gm']}


def test_exact_archived_failure_is_typed_without_broad_native_reclassification(archived):
    result = backend.reference_domain_failure_evidence(**archived)
    assert result['samples'] == 720
    assert result['nonelliptic_osculating_samples'] == 447
    assert result['minimum_radius_m'] == pytest.approx(560881.2680583355)
    assert result['maximum_speed_m_s'] == pytest.approx(79502.14893695017)
    assert result['recoverable_only_during_trial'] is True
    assert backend.native_failure_reason(archived['log'], archived['execution']) == 'native_failure'


@pytest.mark.parametrize('change', [
    {'returncode': -9}, {'returncode': -11}, {'returncode': 137}, {'returncode': 2},
    {'returncode': 0}, {'returncode': True}, {'timed_out': True}, {'timed_out': None},
])
def test_resource_crash_and_unknown_exits_remain_fatal(archived, change):
    archived['execution'] = {**archived['execution'], **change}
    assert backend.reference_domain_failure_evidence(**archived) is None


@pytest.mark.parametrize('change', [
    {'previous_states': None}, {'gm': None}, {'gm': -1.}, {'gm': float('nan')},
    {'derivative_profile': 'flight_gravity_drag_v1'}, {'derivative_profile': 'legacy_v3'},
    {'previous_states': np.zeros((2, 6))}, {'previous_states': np.ones((2, 7))},
    {'previous_states': np.full((2, 6), float('nan'))},
    {'previous_states': np.full((2, 6), 1e300)},
    {'previous_states': np.array([[7e6, 0., 0., 0., 7500., 0.]] * 2)},
])
def test_only_measured_generated_synthetic_domain_is_recoverable(archived, change):
    assert backend.reference_domain_failure_evidence(**{**archived, **change}) is None


@pytest.mark.parametrize('change', [
    lambda text: text.replace('Nonfinite equinoctial reference input', 'Cannot open input file'),
    lambda text: text + 'Segmentation fault\n',
    lambda text: text.replace('PreprocessingVariationalEquation', 'GnssProcessing'),
    lambda text: text.replace('(computeArc)', '(otherOperation)'),
    lambda text: text.replace('****** Error ******', ''),
    lambda text: text + '****** Error ******\n',
    lambda text: 'Nonfinite equinoctial reference input\n',
])
def test_exact_terminal_error_and_propagation_context_are_required(archived, change):
    archived['log'] = change(archived['log'])
    assert backend.reference_domain_failure_evidence(**archived) is None


def test_native_close_preserves_failed_files_and_binds_generated_reference(tmp_path, monkeypatch, archived):
    source = ET.Element('root')
    globals_node = ET.SubElement(source, 'global')
    ET.SubElement(globals_node, 'time', label='timeStart').text = '60424'
    ET.SubElement(globals_node, 'time', label='timeEnd').text = '60424+1/24'
    propagation = ET.SubElement(source, 'PreprocessingVariationalEquation')
    ET.SubElement(ET.SubElement(propagation, 'useEnke'), 'GM').text = str(archived['gm'])
    path = tmp_path / 'variational.xml'
    ET.ElementTree(source).write(path)
    folder = tmp_path / 'point-004-trial-001'
    folder.mkdir()
    initial_reference = tmp_path / 'accepted-orbit.dat'
    initial_reference.write_bytes(b'accepted orbit, unchanged')
    state = backend.PhysicalState(np.arange(6.), np.zeros(61), initial_reference)
    initial_copy, force_copy = state.initial.copy(), state.force.copy()
    model = backend.NativeModel.__new__(backend.NativeModel)
    model.density, model.derivatives, model.propagations = True, 'synthetic_complete_v1', 0
    model.protected_factor = tmp_path / 'accepted.R.bin'
    model.protected_factor.write_bytes(b'accepted factor, unchanged')
    monkeypatch.setattr(model, '_evaluation', lambda *a, **kw: [])
    monkeypatch.setattr(backend, 'compact_closed_closures', lambda *a: None)
    monkeypatch.setattr(backend.native, '_orbit', lambda *a: (np.arange(720.), archived['previous_states']))
    calls = []

    def execute(tree, iteration, label):
        assert label == 'propagate'
        calls.append(tree.find('.//PreprocessingVariationalEquation/inputfileOrbit').text)
        if len(calls) == 1:
            (iteration / 'orbit.dat').write_bytes(b'finite generated closure-01 orbit')
            return
        (iteration / 'propagate.log').write_text(archived['log'])
        try:
            raise backend.native.NativeExecutionError('exact archived domain failure', execution=archived['execution'])
        except backend.native.NativeExecutionError as native_error:
            raise NumericalFailure('native_failure', str(native_error)) from native_error

    monkeypatch.setattr(model, 'execute', execute)
    with pytest.raises(PhysicalTrialDomainFailure) as caught:
        model._close(state, {'configs': {'variational': str(path)}, 'date': '2024-04-24'}, folder, False)
    record = json.loads((folder / 'trial-domain-failure.json').read_text())
    assert record == caught.value.evidence
    assert calls == [str(initial_reference), str(folder / 'closure-01/orbit.dat')]
    assert record['reference_orbit'] == calls[1]
    assert record['reference_orbit_sha256'] == hashlib.sha256(Path(calls[1]).read_bytes()).hexdigest()
    assert (folder / 'closure-02/propagate.log').read_text() == archived['log']
    assert model.protected_factor.read_bytes() == b'accepted factor, unchanged'
    np.testing.assert_array_equal(state.initial, initial_copy)
    np.testing.assert_array_equal(state.force, force_copy)


def test_typed_trial_rollback_keeps_state_and_factor_and_uses_original_damping(archived):
    evidence = backend.reference_domain_failure_evidence(**archived)

    class FailedTrials(ProfiledModel):
        def __init__(self):
            super().__init__()
            self.accepted, self.before_retry = [], []

        def accept(self, point):
            self.accepted.append(point)

        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-') and int(label[6:]) <= 4:
                point = self.accepted[-1]
                self.before_retry.append((point.state, point.factor.copy(), point.rhs.copy()))
                raise PhysicalTrialDomainFailure('archived propagation domain', evidence)
            return super().evaluate(state, label, tighter)

    model = FailedTrials()
    result = minimize(model, 0.)
    assert result['converged'], result
    rejected = result['history'][:4]
    assert [entry['damping'] for entry in rejected] == pytest.approx([.001, .002, .008, .064])
    assert all(not entry['accepted'] and entry['trial_domain_evidence'] == evidence for entry in rejected)
    assert all(entry['actual_reduction'] is None and entry['gain_ratio'] is None for entry in rejected)
    assert result['history'][4]['damping'] == pytest.approx(1.024)
    assert len({entry['objective_before'] for entry in rejected}) == 1
    for state, factor, rhs in model.before_retry:
        assert state == 0.
        np.testing.assert_array_equal(factor, model.before_retry[0][1])
        np.testing.assert_array_equal(rhs, model.before_retry[0][2])


@pytest.mark.parametrize('phase', ['initial', 'repeat', 'closure-refinement', 'confirmation', 'finish'])
def test_domain_failures_outside_trial_are_fatal_without_covariance(archived, phase):
    evidence = backend.reference_domain_failure_evidence(**archived)

    class FailedPhase(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label == phase:
                raise PhysicalTrialDomainFailure('controlled nontrial failure', evidence)
            return super().evaluate(state, label, tighter)

        def finish(self, point):
            if phase == 'finish':
                raise PhysicalTrialDomainFailure('controlled final failure', evidence)
            return super().finish(point)

    model = FailedPhase()
    result = minimize(model, 0.)
    assert result['status'] == 'physical_trial_domain'
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized
    assert all(row.get('reason') != 'physical_trial_domain' for row in result['history'])


def test_untyped_domain_reason_is_not_a_recoverable_native_error():
    class Untyped(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-'):
                raise NumericalFailure('physical_trial_domain', 'no typed evidence')
            return super().evaluate(state, label, tighter)

    model = Untyped()
    result = minimize(model, 0.)
    assert result['status'] == 'physical_trial_domain'
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized
    assert not result['history']


def test_repeated_domain_failure_exhausts_existing_budget_without_false_convergence(archived):
    evidence = backend.reference_domain_failure_evidence(**archived)

    class AlwaysInvalid(ProfiledModel):
        def evaluate(self, state, label, tighter=False):
            if label.startswith('trial-'):
                raise PhysicalTrialDomainFailure('controlled trial failure', evidence)
            return super().evaluate(state, label, tighter)

    model = AlwaysInvalid()
    result = minimize(model, 0., controls=replace(Controls(), maximum_trial_evaluations=3))
    assert result['status'] == 'iteration_limit'
    assert result['trial_evaluations'] == 3 and result['accepted_iterations'] == 0
    assert not result['converged'] and not result['covariance_valid'] and not model.finalized
