"""Pure candidate03 algebra and control tests; no compiler/native execution.

The matrix tests establish the proposed algebra on identical original rows.
They are deliberately not a substitute for compiled native/GTSAM comparisons.
"""
import copy
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from orbit_poc.numerics.backend import nuisance_profile_resolution, require_full_native_factor
from orbit_poc.numerics.optimizer import NumericalFailure

ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / 'groops/extension'
spec = importlib.util.spec_from_file_location('conditional_installer', EXTENSION / 'native_conditional_nuisance_v41.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
FIXTURE = Path(__file__).parent / 'fixtures/conditional_nuisance_v41/gnssProcessingStep.cpp'


def certificate(matrix, rows):
    if not matrix.shape[1]:
        return 'full'
    singular = np.linalg.svd(matrix, compute_uv=False)
    threshold = np.finfo(float).eps * max(rows, *matrix.shape) * singular[0]
    if len(singular) < matrix.shape[1] or singular[-1] <= threshold:
        return 'deficient'
    return 'unresolved' if singular[-1] <= 10 * threshold else 'full'


def qr_solve(a, b):
    if not a.shape[1]:
        return np.empty(0)
    scale = 1 / np.linalg.norm(a, axis=0)
    q, r = np.linalg.qr(a * scale, mode='reduced')
    if certificate(r, len(a)) != 'full':
        raise ValueError('rank')
    return np.linalg.solve(r, q.T @ b) * scale


def eliminate(local, remaining, b):
    k = local.shape[1]
    if not k:
        return remaining, b, (np.empty((0, 0)), np.empty((0, remaining.shape[1])), np.empty(0), np.empty(0))
    scale = 1 / np.linalg.norm(local, axis=0)
    if certificate(local * scale, len(local)) != 'full':
        raise ValueError('local rank')
    q, r = np.linalg.qr(local * scale, mode='complete')
    transformed, target = q.T @ remaining, q.T @ b
    return transformed[k:], target[k:], (r[:k], transformed[:k], target[:k], scale)


def recover(conditional, retained):
    r, a, b, scale = conditional
    return np.linalg.solve(r, b - a @ retained) * scale if len(b) else np.empty(0)


def profile(a, b, *, groups, local, dynamic, compact):
    """Independent two-stage local elimination plus compact/full retained QR."""
    retained_original = np.arange(groups + local, a.shape[1])
    selected = np.array([i for i in retained_original if i not in dynamic], dtype=int)
    after_group, group_target, group_conditional = eliminate(a[:, :groups], a[:, groups:], b)
    indices = selected - groups if compact else retained_original - groups
    reduced, target, epoch_conditional = eliminate(after_group[:, :local], after_group[:, indices], group_target)
    scale = 1 / np.where(np.linalg.norm(reduced, axis=0) > 0, np.linalg.norm(reduced, axis=0), 1)
    q, r = np.linalg.qr(reduced * scale, mode='complete')
    n = reduced.shape[1]
    triangular, z = r[:n], (q.T @ target)[:n]
    remainder = (q.T @ target)[n:]
    if certificate(triangular, len(reduced)) != 'full':
        raise ValueError('retained rank')
    keep = np.arange(n) if compact else np.array([i for i, global_id in enumerate(retained_original) if global_id not in dynamic], dtype=int)
    scaled = np.zeros(n)
    scaled[keep] = qr_solve(triangular[:, keep], z)
    retained = scaled * scale
    x = np.zeros(a.shape[1])
    x[selected if compact else retained_original] = retained
    x[groups:groups + local] = recover(epoch_conditional, retained)
    x[:groups] = recover(group_conditional, x[groups:])
    prediction = triangular @ scaled
    removed_energy = group_conditional[2] @ group_conditional[2] + epoch_conditional[2] @ epoch_conditional[2]
    reduction = prediction @ (z - .5 * prediction) + .5 * removed_energy
    objective = .5 * (remainder @ remainder + (z - prediction) @ (z - prediction))
    return x, objective, reduction, removed_energy


def problem():
    rng = np.random.default_rng(51243)
    # 4 independent STEC groups, 2 epoch clocks, interleaved physical and
    # global nuisance coordinates. Last rows include nonzero physical priors.
    a = np.zeros((26, 10))
    for group in range(4):
        rows = slice(4 * group, 4 * group + 4)
        a[rows, group] = rng.uniform(.4, 2, 4)
        a[rows, 4 + group // 2] = rng.uniform(.5, 1.5, 4)
    a[:16, 6:] = rng.normal(size=(16, 4))
    a[16, 4] = 1.3; a[17, 5] = .8
    a[18:, 6:] = np.array([[2, 0, 0, 0], [-1, 0, 3, 0], [0, 0, 4, 0],
                          [0, 1, 0, -.6], [1, 0, -2, 0], [0, .5, 0, 2],
                          [0, 0, 0, 0], [0, 0, 0, 0]])
    b = rng.normal(size=26)
    b[18:] = [4., -7., 3., 1., 6., -.2, 8., -9.]
    return a, b


@pytest.mark.parametrize('unit_scale', [np.ones(10), np.array([1e2, .1, 2, 4, .2, 3, 1e6, 1e-2, 1e-5, 1e3])])
@pytest.mark.parametrize('permutation', [False, True])
def test_identical_original_rows_preserve_joint_nuisances_cost_and_prediction(unit_scale, permutation):
    a, b = problem(); a = a * unit_scale
    if permutation:
        order = np.random.default_rng(177).permutation(len(a)); a, b = a[order], b[order]
    dynamic = {6, 8}; nuisance = [i for i in range(10) if i not in dynamic]
    original = qr_solve(a[:, nuisance], b)
    q, r = np.linalg.qr(a[:, nuisance], mode='reduced')
    inverse = np.linalg.solve(r, np.eye(len(nuisance)))
    standard_deviation = np.sqrt(np.diag(inverse @ inverse.T))
    full = profile(a, b, groups=4, local=2, dynamic=dynamic, compact=False)
    compact = profile(a, b, groups=4, local=2, dynamic=dynamic, compact=True)
    for result in (full, compact):
        np.testing.assert_allclose((result[0][nuisance] - original) / standard_deviation, 0, atol=1e-7)
        assert np.array_equal(result[0][sorted(dynamic)], np.zeros(2))
        residual = b - a @ result[0]
        assert result[1] == pytest.approx(.5 * residual @ residual, rel=1e-12, abs=1e-12)
        assert result[2] == pytest.approx(.5 * (b @ b - residual @ residual), rel=1e-12, abs=1e-12)
    np.testing.assert_allclose(full[0], compact[0], rtol=1e-10, atol=1e-8)
    assert full[3] == pytest.approx(compact[3], rel=1e-12)
    # Pure physical priors and zero-design rows retain irreducible energy.
    assert compact[1] >= .5 * (8**2 + 9**2)


def test_group_and_epoch_recovery_remain_coupled_to_shared_nuisances():
    a, b = problem()
    x, *_ = profile(a, b, groups=4, local=2, dynamic={6, 8}, compact=True)
    disconnected = qr_solve(a[:, :6], b)
    assert np.max(np.abs(disconnected - x[:6])) > 1e-3


def test_empty_retained_nuisance_set_preserves_fixed_physical_costs():
    a, b = problem()
    x, cost, reduction, _ = profile(a, b, groups=4, local=2, dynamic={6, 7, 8, 9}, compact=True)
    expected = qr_solve(a[:, :6], b)
    np.testing.assert_allclose(x[:6], expected, atol=1e-12)
    assert np.array_equal(x[6:], np.zeros(4))
    residual = b - a @ x
    assert cost == pytest.approx(.5 * residual @ residual, rel=1e-12)
    assert reduction == pytest.approx(.5 * (b @ b - residual @ residual), rel=1e-12)


def test_dynamic_only_deficiency_is_not_certified_by_compact_rank():
    a, b = problem(); a[:, 6] = 2 * a[:, 8]
    profile(a, b, groups=4, local=2, dynamic={6, 8}, compact=True)
    with pytest.raises(ValueError, match='rank'):
        profile(a, b, groups=4, local=2, dynamic={6, 8}, compact=False)


@pytest.mark.parametrize('which', ['nuisance', 'local'])
def test_compact_does_not_drop_deficient_directions(which):
    a, b = problem()
    a[:, 9 if which == 'nuisance' else 1] = 0
    with np.errstate(divide='ignore', invalid='ignore'), pytest.raises((ValueError, np.linalg.LinAlgError)):
        profile(a, b, groups=4, local=2, dynamic={6, 8}, compact=True)


@pytest.mark.parametrize('small,status', [(1e-16, 'deficient'), (1e-14, 'unresolved'), (1e-12, 'full')])
def test_rank_classification_keeps_original_row_threshold(small, status):
    assert certificate(np.diag([1., small]), 10) == status


def strict_receipt():
    return {'nuisance_converged': True, 'nuisance_floor_limited': False,
            'conditional_nuisance_qr': True, 'fresh_full_nuisance_confirmed': True,
            'fresh_full_nuisance_update_m': 2e-9, 'threshold_m': 1e-8,
            'required_consecutive_small_updates': 2,
            'history': [{'maximum_update_m': 1e-9}, {'maximum_update_m': 2e-9}]}


@pytest.mark.parametrize('change', [1e-8, 1e-7, -1., float('nan'), None, True])
def test_two_compact_small_updates_cannot_bypass_fresh_full_confirmation(change):
    receipt = strict_receipt(); receipt['fresh_full_nuisance_update_m'] = change
    with pytest.raises(NumericalFailure, match='confirmation'):
        nuisance_profile_resolution(receipt, covariance=True)


def test_strict_full_confirmation_and_floor_separation():
    assert nuisance_profile_resolution(strict_receipt(), covariance=True) == (0., False)
    receipt = strict_receipt(); receipt['nuisance_floor_limited'] = True
    with pytest.raises(NumericalFailure):
        nuisance_profile_resolution(receipt, covariance=True)


def full_factor():
    return ({'schema': 'orbit-poc-qr-factor-v1', 'rows': 4, 'columns': 4,
             'local_global_indices': [0, 1], 'retained_global_indices': [2, 3, 4, 5]},
            {'schema': 'orbit-poc-native-qr-v1', 'rank_status': 'full', 'rank': 4,
             'retained_parameters': 4, 'lambda': 0})


@pytest.mark.parametrize('defect', ['conditional', 'missing_physical', 'unresolved', 'damped'])
def test_conditional_factor_cannot_authorize_physical_evaluation(defect):
    info, diagnostics = full_factor()
    require_full_native_factor(info, diagnostics)
    if defect == 'conditional': info['schema'] = 'orbit-poc-conditional-nuisance-qr-factor-v1'
    if defect == 'missing_physical': info['retained_global_indices'] = [2, 4, 7, 8]
    if defect == 'unresolved': diagnostics['rank_status'] = 'unresolved'
    if defect == 'damped': diagnostics['lambda'] = 1e-5
    with pytest.raises(NumericalFailure): require_full_native_factor(info, diagnostics)


def source_fixture(tmp_path):
    for name in ('nuisance-performance', 'nuisance-v41', 'design-storage-v41'):
        (tmp_path / ('orbit-poc-' + name + '-extension.json')).write_text('{}')
    processing = tmp_path / installer.PROCESSING
    processing.parent.mkdir(parents=True); processing.write_bytes(FIXTURE.read_bytes())
    for name, destination in installer.HEADERS.items():
        path = tmp_path / destination; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((EXTENSION / name).read_bytes())
    return tmp_path


def test_installer_actual_candidate02_hooks_and_repeat_identity(tmp_path):
    root = source_fixture(tmp_path)
    receipt = installer.apply(root)
    assert installer.apply(root) == receipt
    code = (root / installer.PROCESSING).read_text()
    assert code.index('const std::string mode=') < code.index('const Bool conditional=')
    assert 'conditional?Vector():orbitPocRowQr().solve()' in code
    assert 'if(!confirm)return 0.;' in code
    assert 'if(!exactZero||!confirmation.stationary)' in code
    assert code.index('if(confirm)\n      {\n        // The parent') < code.index('auto audit=[&](UInt mode)')
    assert 'confirmation.undampedChange;' in code
    confirmation = code.split('      if(confirm)\n      {\n        // The parent', 1)[1].split('      auto audit=', 1)[0]
    assert confirmation.count('isolatedNuisanceTrial(') == 2
    assert 'apply(' not in confirmation and 'buildNormals(' not in confirmation
    assert not receipt['native_execution']
    (root / installer.PROCESSING).write_text(code + '\n')
    with pytest.raises(ValueError, match='changed'): installer.apply(root)


def test_installer_preflights_all_hooks_before_writing(tmp_path):
    root = source_fixture(tmp_path); path = root / installer.PROCESSING
    path.write_text(path.read_text().replace('      if(mode!="profile_step")return apply(1.);', '      changed_anchor();'))
    before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match='anchor mismatch'): installer.apply(root)
    assert before == {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_installer_refuses_previously_sealed_native_source(tmp_path):
    root = source_fixture(tmp_path)
    (root / 'orbit-poc-reliability-v41-build-profile.json').write_text('{}')
    with pytest.raises(ValueError, match='separate new'): installer.apply(root)


@pytest.mark.parametrize('defect', ['dropped', 'extra', 'schema', 'symlink', 'dangling'])
def test_installer_reentry_requires_exact_regular_receipt(tmp_path, defect):
    root = source_fixture(tmp_path); receipt = installer.apply(root)
    path = root / installer.MANIFEST
    if defect == 'dropped': receipt['outputs'].pop(installer.PROCESSING)
    if defect == 'extra': receipt['outputs']['../external'] = '0' * 64
    if defect == 'schema': receipt['schema'] = 'unknown'
    if defect in ('symlink', 'dangling'):
        saved = root / 'saved-receipt.json'; path.rename(saved)
        path.symlink_to(saved if defect == 'symlink' else root / 'missing')
    else:
        path.write_text(json.dumps(receipt))
    with pytest.raises(ValueError): installer.apply(root)


def test_distinct_inner_artifacts_and_guarded_full_modes():
    header = (EXTENSION / 'scaledRowQr.h').read_text()
    assert '.conditional_factor.json' in header and '.conditional_diagnostics.json' in header
    assert 'conditionalNuisance&&(!nuisanceOnly||lambda!=0)' in header
    assert header.count('Conditional nuisance factor cannot authorize covariance') == 2
    assert 'segmentedCapture=(segmented=="1")&&!conditionalNuisance' in header
    assert 'norms[retainedGlobalIndices[j]]' in header
    assert 'if(ids[j]>=total||!std::isfinite(values[j]))' in header


def test_conditional_metadata_cannot_match_full_factor_discovery(tmp_path):
    (tmp_path / 'qr.1.conditional_factor.json').write_text('{}')
    assert list(tmp_path.glob('qr.*.factor.json')) == []
    (tmp_path / 'qr.2.factor.json').write_text('{}')
    assert [p.name for p in tmp_path.glob('qr.*.factor.json')] == ['qr.2.factor.json']
