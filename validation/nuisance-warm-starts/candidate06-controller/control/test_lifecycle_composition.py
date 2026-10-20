"""Composed unit evidence. Native computation is mocked; no native fit is run.

Real production paths: minimize, NativeModel init/evaluate/trial/accept/execute/
finish, WarmStartLifecycle, file readers, rank checks and retention.
Mock boundaries: input/config provisioning, physical closure, run_native.
The mock emits a seven-coordinate identity factor and a one-dimensional
quadratic objective. Deliberate anomalies are declared per test.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.numerics import backend
from orbit_poc.numerics.config import Controls
from orbit_poc.numerics.nuisance_warm_start import PREFIX
from orbit_poc.numerics.optimizer import minimize


CANDIDATE = Path('/home/emper/orbit-nuisance-warmstarts/source-candidate06')
EPOCHS = np.array([60000., 60000.00001])
PROTECTED = {'initial', 'repeat', 'closure-refinement', 'repeat-floor',
             'refine-floor', 'confirmation', 'final-covariance'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def numpy_scalar(value):
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError('Unexpected trace value: ' + type(value).__name__)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, default=numpy_scalar) + '\n')


def write_factor(path, values):
    matrix = np.asarray(values, dtype='<f8')
    if matrix.ndim == 1:
        matrix = matrix[:, None]
    Path(path).write_bytes(struct.pack('<QQ', *matrix.shape) + matrix.tobytes())


def floor_receipt():
    return {'nuisance_converged': False, 'nuisance_floor_limited': True,
            'nuisance_objective_resolution': 1e-12,
            'nuisance_predicted_reduction': 1e-13,
            'nuisance_floor_policy': 'empirical_equivalent_arithmetic_and_symmetric_probes_v1',
            'nuisance_floor_audit': [
                *[{'kind': 'equivalent_arithmetic', 'mode': mode,
                   'success': True, 'support_unchanged': True} for mode in (1, 2, 3)],
                {'kind': 'two_amplitude_symmetric_nuisance_probe', 'probes': [{}, {}, {}, {}],
                 'empirical_quadratic_potential': 1e-13,
                 'half_empirical_quadratic_potential': 1e-13,
                 'empirical_quadratic_potential_with_allowance': 2e-13,
                 'half_empirical_quadratic_potential_with_allowance': 3e-13,
                 'success': True, 'support_unchanged': True}]}


class SyntheticNative:
    """Native I/O substitute; never implements donor selection or acceptance."""
    def __init__(self, monkeypatch, tmp_path, *, enabled=True, reject_first=False,
                 measure_floor=False, limited_first=False, corrupt=None):
        self.root = tmp_path / 'fit'
        self.root.mkdir()
        self.trace = {'evidence_kind': 'mock_composed_python_unit', 'native_execution': False,
                      'launches': [], 'acceptances': [], 'optimizer_emissions': [],
                      'scenario': {'enabled': enabled, 'reject_first': reject_first,
                                   'measure_floor': measure_floor, 'limited_first': limited_first,
                                   'corrupt': corrupt}}
        self.reject_first, self.measure_floor = reject_first, measure_floor
        self.limited_first, self.corrupt = limited_first, corrupt
        self.points = {}
        self.configs = {}
        self.model = None
        assert Path(backend.__file__).resolve() == CANDIDATE / 'src/orbit_poc/numerics/backend.py'

        def forbidden_process(*args, **kwargs):
            raise AssertionError('Subprocess/native execution is forbidden in this unit fixture')

        monkeypatch.setattr(subprocess, 'Popen', forbidden_process)
        monkeypatch.setattr(os, 'system', forbidden_process)
        for key in list(os.environ):
            if key.startswith(PREFIX):
                monkeypatch.delenv(key)
        if enabled:
            monkeypatch.setenv(PREFIX + '_STARTS', '1')
        self.inherited = {PREFIX + '_INPUT': '/forbidden/inherited-seed',
                          PREFIX + '_INPUT_SHA256': 'f' * 64,
                          PREFIX + '_OUTPUT': '/forbidden/inherited-output',
                          PREFIX + '_FUTURE': 'inherited-poison'}
        for key, value in self.inherited.items():
            monkeypatch.setenv(key, value)

        binary = tmp_path / 'not-an-executable'
        binary.write_bytes(b'fixture identity only; this file is never executed')
        data = tmp_path / 'observations'
        data.write_bytes(b'fixed synthetic observation support')
        item = {'path': str(data), 'sha256': sha(data), 'role': 'observations'}
        prepared = {'native_artifacts': [item], 'native_paths': {}}
        job = {'method': 'groops_pulses', 'stage': 'synthetic',
               'numerics_profile': 'qr_lm_staged_jacobian',
               'parameters': {'interval_seconds': 1200., 'sigma_velocity_m_s': 1e-4},
               'estimation_inputs': [item], 'expected_native_binary_sha256': sha(binary),
               **{key: 'a' * 64 for key in ('force_model_hash', 'measurement_model_hash',
                                          'preprocessing_hash', 'mask_hash')}}
        monkeypatch.setattr(backend.native, '_binary', lambda _: binary)
        monkeypatch.setattr(backend.native, '_preparation', lambda _: prepared)
        monkeypatch.setattr(backend.native, '_private_data',
                            lambda _, private: Path(private).mkdir(parents=True))
        monkeypatch.setattr(backend, 'build_fit_configs', self.build_config)
        monkeypatch.setattr(backend.native, 'run_native', self.run_native)

        # Physical closure is the only NativeModel method replaced. Even this
        # substitute invokes the real execute boundary, so inherited seed leaks
        # on propagation/proposal paths are observable.
        def close(model, state, config, folder, tighter):
            self.points[str(folder)] = {'state': state.initial.copy(), 'tighter': tighter}
            tree = ET.Element('groops')
            node = ET.SubElement(tree, 'SyntheticClosure')
            node.text = ' '.join(map(str, state.initial))
            model.execute(tree, folder, 'propagate')
            orbit, variable = folder / 'closed-orbit.dat', folder / 'variational.dat'
            reference, design = folder / 'reference.txt', folder / 'design.txt'
            orbit.write_bytes(b'synthetic closed orbit')
            variable.write_bytes(b'synthetic variational data')
            backend.write_matrix(reference, state.initial)
            backend.write_matrix(design, np.eye(6))
            config['native_paths']['variational'] = str(variable)
            states = np.tile(state.initial, (len(EPOCHS), 1))
            return orbit, variable, reference, design, EPOCHS.copy(), states

        monkeypatch.setattr(backend.NativeModel, '_close', close)
        self.model = backend.NativeModel(job, self.root)
        assert self.model.controls == Controls()  # Production limits unchanged.
        real_accept = self.model.accept

        def observed_accept(point):
            record = {'label': Path(point.metadata['folder']).name.split('-', 2)[2],
                      'folder': point.metadata['folder'], 'state': point.state.initial.tolist(),
                      'floor_limited': point.metadata['nuisance_floor_limited'],
                      'before': self.donor()}
            try:
                result = real_accept(point)
            except BaseException as error:
                record['error'] = type(error).__name__ + ': ' + str(error)
                raise
            else:
                record['completed'] = True
                return result
            finally:
                record['after'] = self.donor()
                self.trace['acceptances'].append(record)
                self.persist()

        # Observation-only wrapper delegates every installation to the real hook.
        self.model.accept = observed_accept

    def donor(self):
        donor = self.model.warm_start.donor if self.model is not None else None
        return donor.payload.path if donor is not None else None

    def persist(self):
        self.trace['retained_donor'] = self.donor()
        write_json(self.root.parent / 'composition-trace.json', self.trace)

    def build_config(self, prepared, private, method, parameters):
        folder = Path(private).parent
        result_keys = ('orbit', 'covariance', 'covariance_observations', 'orbit_native',
                       'parameter_covariance', 'parameters', 'preprocessing_audit',
                       'phase_recovery', 'apriori_solution', 'parameter_names')
        outputs = {key: str(Path(private) / (key + '.txt')) for key in result_keys}
        root = ET.Element('groops')
        glob = ET.SubElement(root, 'global')
        for label in ['timeStart', 'timeEnd']:
            ET.SubElement(glob, 'time', label=label).text = '60000'
        propagation = ET.SubElement(ET.SubElement(root, 'program'), 'PreprocessingVariationalEquation')
        ET.SubElement(propagation, 'ephemerides').text = 'synthetic'
        processing = ET.SubElement(ET.SubElement(root, 'program'), 'GnssProcessing')
        dynamic = ET.SubElement(ET.SubElement(processing, 'parametrization'), 'leoDynamicOrbits')
        for tag in ['outputfileCovariance', 'outputfileParameterCovariance', 'outputfileCovarianceObservationEpochs']:
            ET.SubElement(dynamic, tag).text = str(Path(private) / tag)
        source = Path(private) / 'source.xml'
        backend.native._save_xml(root, source)
        config = {'configs': {'estimate': str(source), 'variational': str(source)},
                  'result_paths': outputs, 'native_paths': {}, 'date': '2024-05-10'}
        self.configs[str(folder)] = config
        return config

    def run_native(self, binary, xml, folder, label, *, timeout, environment_overrides=None):
        folder = Path(folder)
        inherited = {key: value for key, value in os.environ.items() if key.startswith(PREFIX)}
        assert inherited == {}, 'The real execute boundary leaked inherited warm controls'
        environment = dict(os.environ, **(environment_overrides or {}))
        warm = {key: value for key, value in environment.items() if key.startswith(PREFIX)}
        point_folder = folder if folder.name.startswith('point-') else folder.parent
        point_label = point_folder.name.split('-', 2)[2]
        row = {'call': label, 'point_label': point_label, 'folder': str(folder),
               'acceptance_count': len(self.trace['acceptances']),
               'retained_donor_at_launch': self.donor(), 'inherited_warm_fields': inherited,
               'warm_environment': warm,
               'controlled_environment': dict(environment_overrides or {}), 'timeout_positive': timeout > 0}
        self.trace['launches'].append(row)
        self.persist()
        tree = ET.parse(xml)
        if label == 'linearized-proposal':
            node = tree.find('.//OrbitPocEvaluateVariational')
            state = backend.native.read_native_table(node.findtext('inputfileParameters')).ravel()
            orbit = Path(node.findtext('outputfileOrbit'))
            orbit.write_bytes(b'synthetic proposal orbit')
            np.savetxt(orbit.with_suffix('.txt'), np.column_stack((EPOCHS, np.tile(state, (2, 1)))))
        elif label == 'profile':
            self.emit_profile(folder, point_label, warm, environment, tree)
        else:
            assert label == 'propagate' and tree.find('SyntheticClosure') is not None
        return {'returncode': 0, 'timed_out': False, 'mock_native': True}

    def emit_profile(self, folder, label, warm, environment, tree):
        x = self.points[str(folder)]['state'][0]
        cost = 1. + .5 * (2. - x) ** 2
        if self.measure_floor and label == 'repeat':
            cost += 1e-6
        if self.reject_first and label == 'trial-001':
            cost += 10.
        limited = self.limited_first and label == 'trial-001'
        profile = floor_receipt() if limited else {'nuisance_converged': True, 'nuisance_floor_limited': False}
        base = folder / 'qr.1'
        factor = np.eye(7)
        if self.corrupt == 'actual_rank' and label == 'trial-001':
            factor[-1, -1] = 0.
        rhs = np.r_[2. - x, np.zeros(6)]
        write_factor(str(base) + '.R.bin', factor)
        write_factor(str(base) + '.rhs.bin', rhs)
        write_json(str(base) + '.factor.json', {'scales': [1.] * 7,
                   'dynamic': [True] * 6 + [False], 'orthogonal_energy': 2.})
        diagnostics = {'lambda': 0., 'rank_status': 'full', 'reduced_rows': 8}
        if self.corrupt == 'damped' and label == 'trial-001':
            diagnostics['lambda'] = 1.
        write_json(str(base) + '.diagnostics.json', diagnostics)
        write_json(str(base) + '.profile.json', {'direct_cost': cost})
        write_json(folder / 'qr.profile.json', profile)
        Path(str(base) + '.parameters.tsv').write_text('index\tname\tdynamic\tunit\tscale\n' +
            ''.join(f'{i}\tx{i}\t{int(i < 6)}\tm\t1\n' for i in range(7)))
        Path(str(base) + '.rows.tsv').write_text('kind\trow\nsynthetic\t0\n')
        outputs = self.configs[str(folder)]['result_paths']
        for name, path in outputs.items():
            Path(path).write_text('fixed synthetic ' + name + '\n')
        state = self.points[str(folder)]['state']
        np.savetxt(outputs['orbit'], np.column_stack((EPOCHS, np.tile(state, (2, 1)))))
        cov = np.column_stack((EPOCHS, np.tile(np.eye(6).ravel(), (2, 1))))
        np.savetxt(outputs['covariance'], cov)
        np.savetxt(outputs['covariance_observations'], cov)
        assert environment['ORBIT_POC_NUMERICS_QR_PREFIX'] == str(folder / 'qr')
        assert environment['ORBIT_POC_NUMERICS_SOLVER'] == 'scaled_qr_v1'
        assert (tree.find('.//computeCovarianceMatrix') is not None) == (label == 'final-covariance')
        if warm.get(PREFIX + '_STARTS') != '1':
            assert warm == {}
            return
        payload = Path(warm[PREFIX + '_OUTPUT'])
        if not limited:
            payload.write_bytes(('synthetic opaque seed: ' + str(folder)).encode())
        receipt = {'schema': 'orbit-poc-native-nuisance-warm-state-v1',
                   'mode': warm[PREFIX + '_MODE'], 'context_sha256': warm[PREFIX + '_CONTEXT_SHA256'],
                   'chart_sha256': '1' * 64, 'cold_origin_sha256': '2' * 64,
                   'source_prefix': str(folder / 'qr'), 'source_generation': str(base),
                   'eligibility': {'nuisance_converged': not limited, 'nuisance_floor_limited': limited,
                                   'fresh_undamped': True, 'rank_status': 'full'},
                   'imported': {'used': PREFIX + '_INPUT' in warm,
                                'path': warm.get(PREFIX + '_INPUT', ''),
                                'sha256': warm.get(PREFIX + '_INPUT_SHA256', '')},
                   'counts': {'coordinates': 1},
                   'invariants': {'target_cold_ionosphere_unchanged': True,
                                  'target_clock_prior_anchors_unchanged': True},
                   'export_status': 'ineligible' if limited else 'exported',
                   'payload_sha256': None if limited else sha(payload)}
        if self.corrupt == 'fresh' and label == 'trial-001':
            receipt['eligibility']['fresh_undamped'] = False
        if self.corrupt == 'strict' and label == 'trial-001':
            receipt['eligibility']['nuisance_converged'] = False
        write_json(str(payload) + '.json', receipt)

    def run(self):
        initial = backend.PhysicalState(np.zeros(6), np.zeros(0), self.root / 'original-orbit')
        def emit(value):
            self.trace['optimizer_emissions'].append(json.loads(json.dumps(value, default=numpy_scalar)))
            self.persist()
        try:
            result = minimize(self.model, initial, controls=self.model.controls, emit=emit)
            self.trace['optimizer_result'] = result
            return result
        except BaseException as error:
            self.trace['raised'] = type(error).__name__ + ': ' + str(error)
            raise
        finally:
            self.trace['inherited_restored'] = all(os.environ.get(k) == v for k, v in self.inherited.items())
            self.persist()

    def profiles(self):
        return [row for row in self.trace['launches'] if row['call'] == 'profile']

    def assert_environment_and_lineage(self, *, all_cold_labels=True):
        profiles = self.profiles()
        if all_cold_labels:
            assert PROTECTED <= {row['point_label'] for row in profiles}
        for row in self.trace['launches']:
            warm = row['warm_environment']
            assert row['inherited_warm_fields'] == {} and row['timeout_positive']
            assert PREFIX + '_FUTURE' not in warm
            assert '/forbidden/' not in json.dumps(warm)
            if row['call'] != 'profile':
                assert warm == {}
                continue
            prior = self.trace['acceptances'][:row['acceptance_count']]
            expected = prior[-1]['after'] if prior else None
            assert row['retained_donor_at_launch'] == expected
            if row['point_label'] in PROTECTED:
                assert PREFIX + '_INPUT' not in warm and PREFIX + '_INPUT_SHA256' not in warm
            elif self.model.warm_start.enabled:
                assert row['point_label'].startswith('trial-')
                assert warm.get(PREFIX + '_INPUT') == expected
                if expected:
                    assert warm[PREFIX + '_INPUT_SHA256'] == sha(expected)
        for event in self.trace['acceptances']:
            if self.model.warm_start.enabled:
                expected = None if event['floor_limited'] else str(Path(event['folder']) / 'nuisance-warm-state.bin')
                assert event['completed'] and event['after'] == expected
        assert self.trace['inherited_restored']


def test_optimizer_rejection_and_all_cold_checks_use_actual_backend_boundaries(monkeypatch, tmp_path):
    case = SyntheticNative(monkeypatch, tmp_path, reject_first=True, measure_floor=True)
    result = case.run()
    assert result['converged'] and result['result']['covariance_valid']
    assert result['history'][0]['reason'] == 'nonpositive_actual_reduction'
    assert not result['history'][0]['accepted']
    profiles = case.profiles()
    trials = [row for row in profiles if row['point_label'].startswith('trial-')]
    assert len(trials) >= 3
    assert trials[0]['warm_environment'][PREFIX + '_INPUT'] == trials[1]['warm_environment'][PREFIX + '_INPUT']
    rejected = trials[0]['folder']
    assert all(event['folder'] != rejected for event in case.trace['acceptances'])
    assert all(row['warm_environment'].get(PREFIX + '_INPUT') != rejected + '/nuisance-warm-state.bin' for row in profiles)
    assert any(event['label'].startswith('trial-') for event in case.trace['acceptances'])
    assert result['confirmation_checks'] and all(row['stationary'] for row in result['confirmation_checks'])
    assert any('floor_measurement' in row for row in result['history'])
    case.assert_environment_and_lineage()


def test_accepted_floor_limited_trial_revokes_donor_before_next_real_trial(monkeypatch, tmp_path):
    case = SyntheticNative(monkeypatch, tmp_path, limited_first=True)
    result = case.run()
    assert result['converged'] and result['result']['covariance_valid']
    assert result['history'][0]['accepted'] and result['history'][0]['nuisance_floor_limited_trial']
    floor_accept = next(event for event in case.trace['acceptances'] if event['label'] == 'trial-001')
    assert floor_accept['before'] and floor_accept['after'] is None
    assert not (Path(floor_accept['folder']) / 'nuisance-warm-state.bin').exists()
    next_trial = next(row for row in case.profiles() if row['point_label'] == 'trial-002')
    assert next_trial['retained_donor_at_launch'] is None
    assert PREFIX + '_INPUT' not in next_trial['warm_environment']
    assert any(event['label'] == 'trial-002' and event['after'] for event in case.trace['acceptances'])
    case.assert_environment_and_lineage()


def test_default_off_suppresses_poisoned_inherited_seeds_through_complete_optimizer(monkeypatch, tmp_path):
    case = SyntheticNative(monkeypatch, tmp_path, enabled=False, measure_floor=True)
    result = case.run()
    assert result['converged'] and result['result']['covariance_valid']
    assert not case.model.warm_start.enabled and case.donor() is None
    assert all(row['warm_environment'] == {} for row in case.trace['launches'])
    assert not list(case.root.glob('point-*/nuisance-warm-state.bin*'))
    case.assert_environment_and_lineage()


@pytest.mark.parametrize('corrupt', ['fresh', 'damped', 'strict'])
def test_bad_native_export_cannot_be_promoted_in_composed_optimizer(monkeypatch, tmp_path, corrupt):
    case = SyntheticNative(monkeypatch, tmp_path, corrupt=corrupt)
    with pytest.raises(ValueError, match='Nuisance warm start:'):
        case.run()
    assert [event['label'] for event in case.trace['acceptances']] == ['initial', 'closure-refinement']
    assert case.donor().endswith('point-003-closure-refinement/nuisance-warm-state.bin')
    assert 'final-covariance' not in {row['point_label'] for row in case.profiles()}
    case.assert_environment_and_lineage(all_cold_labels=False)


def test_actual_deficient_factor_rejects_trial_despite_full_rank_native_claim(monkeypatch, tmp_path):
    case = SyntheticNative(monkeypatch, tmp_path, corrupt='actual_rank', measure_floor=True)
    result = case.run()
    assert result['converged'] and result['result']['covariance_valid']
    assert result['history'][0]['reason'] == 'rank_deficient' and not result['history'][0]['accepted']
    assert 'trial-001' not in {event['label'] for event in case.trace['acceptances']}
    trials = [row for row in case.profiles() if row['point_label'].startswith('trial-')]
    assert trials[0]['warm_environment'][PREFIX + '_INPUT'] == trials[1]['warm_environment'][PREFIX + '_INPUT']
    case.assert_environment_and_lineage()
