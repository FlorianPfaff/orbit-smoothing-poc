"""Independent checks of the actual native original-row QR implementation."""
from __future__ import annotations
import json
import gzip
import hashlib
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest
from scipy.linalg import solve_triangular


@pytest.fixture
def native():
    value = os.environ.get("ORBIT_POC_V31_NATIVE")
    if not value:
        pytest.skip("ORBIT_POC_V31_NATIVE is required for actual native QR gates")
    return value


def _run(native, directory, a, b, *, local=0, dynamic=2, damping=0.0,
         nuisance_only=False, block_rows=256, success=True, ionosphere=False,
         generations=1, keep_intermediate=True, spool_directory=None, fail_before_factor_generation=0, cost_only=False, joint_epoch=False, compress_rows=False):
    directory.mkdir(parents=True)
    rows = np.column_stack((a, b))
    np.savetxt(directory / "rows.txt", rows, fmt="%.17g", comments="",
               header=f"groops matrix version=20200123\nMatrix( {len(a)} x {rows.shape[1]} )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": directory / "rows.txt",
                        "outputfileSolution": directory / "solution.txt",
                        "outputfileCovariance": directory / "covariance.txt",
                        "outputPrefix": directory / "qr", "localColumns": local,
                        "dynamicColumns": dynamic, "lambda": damping,
                        "nuisanceOnly": int(nuisance_only), "ionosphereColumn": int(ionosphere),
                        "generations": generations, "failBeforeFactorGeneration": fail_before_factor_generation, "costOnlyCheck": int(cost_only), "jointEpochLocals": int(joint_epoch)}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(directory / "run.xml", encoding="utf-8", xml_declaration=True)
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               ORBIT_POC_NUMERICS_QR_BLOCK_ROWS=str(block_rows),
               ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS=str(int(keep_intermediate)),
               ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE=str(int(compress_rows)))
    if spool_directory is not None:
        env["ORBIT_POC_NUMERICS_SPOOL_DIRECTORY"] = str(spool_directory)
    result = subprocess.run([native, str(directory / "run.xml")], text=True,
                            capture_output=True, env=env, timeout=120)
    (directory / "native.log").write_text(result.stdout + result.stderr)
    if not success:
        assert result.returncode != 0, result.stdout
        assert not (directory / "covariance.txt").exists()
        diagnostics = directory / "qr.1.diagnostics.json"
        return json.loads(diagnostics.read_text()) if diagnostics.exists() else {"failure": result.stdout + result.stderr}
    assert result.returncode == 0, result.stdout + result.stderr
    return (np.loadtxt(directory / "solution.txt", skiprows=2).reshape(-1),
            np.atleast_2d(np.loadtxt(directory / "covariance.txt", skiprows=2)),
            json.loads((directory / f"qr.{generations}.factor.json").read_text()),
            json.loads((directory / f"qr.{generations}.profile.json").read_text()))


def _problem():
    rng = np.random.default_rng(718)
    a = rng.normal(size=(48, 6))
    a[:, :2] = 0
    a[:18, 0] = rng.uniform(.5, 2, 18)
    a[18:36, 1] = rng.uniform(.5, 2, 18)
    # Last rows play the role of full-parameter Gaussian constraints.
    b = a @ np.array([1., -2., .3, -.1, 2., -.7]) + rng.normal(size=48) * .03
    return a, b


def _reference(a, b):
    q, r = np.linalg.qr(a, mode="reduced")
    x = solve_triangular(r, q.T @ b)
    inverse = solve_triangular(r, np.eye(r.shape[0]))
    return x, inverse @ inverse.T


def test_native_original_row_qr_map_covariance_and_profile(native, tmp_path, record_property):
    a, b = _problem()
    expected, covariance = _reference(a, b)
    x, c, meta, profile = _run(native, tmp_path / "local", a, b, local=2)
    record_property("map_error_posterior_standard_deviations", float(np.max(np.abs(x - expected) / np.sqrt(np.diag(covariance)))))
    record_property("relative_covariance_error", float(np.linalg.norm(c - covariance[2:, 2:]) / np.linalg.norm(covariance[2:, 2:])))
    np.testing.assert_allclose((x - expected) / np.sqrt(np.diag(covariance)), 0, atol=1e-7)
    assert np.linalg.norm(c - covariance[2:, 2:]) / np.linalg.norm(covariance[2:, 2:]) < 1e-8
    nuisance = [0, 1, 4, 5]
    residual = b - a[:, nuisance] @ np.linalg.lstsq(a[:, nuisance], b, rcond=None)[0]
    assert profile["profile_cost"] == pytest.approx(.5 * residual @ residual, rel=1e-12)
    assert profile["direct_cost"] == pytest.approx(.5 * b @ b, rel=1e-12)
    assert profile["nuisance_predicted_reduction"] == pytest.approx(.5 * (b @ b - residual @ residual), rel=1e-12)
    assert profile["nuisance_gradient_scaled"] == max(profile[name] for name in (
        "retained_nuisance_gradient_scaled", "clock_conditional_gradient_scaled", "group_conditional_gradient_scaled"))
    assert meta["retained_global_indices"] == [2, 3, 4, 5]
    assert meta["dynamic"] == [True, True, False, False]


@pytest.mark.parametrize("block_rows", [1, 7, 1000])
def test_native_row_order_and_block_size(native, tmp_path, block_rows):
    a, b = _problem()
    order = np.random.default_rng(919).permutation(len(a))
    x, c, *_ = _run(native, tmp_path / "run", a[order], b[order], local=2, block_rows=block_rows)
    expected, covariance = _reference(a, b)
    np.testing.assert_allclose(x, expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(c, covariance[2:, 2:], rtol=1e-11, atol=1e-13)


@pytest.mark.parametrize("block_rows", [1, 17, 128, 1000])
def test_native_triangular_merge_across_lapack_reflector_blocks(native, tmp_path, block_rows):
    rng = np.random.default_rng(818)
    a = rng.normal(size=(347, 82))
    a[:, :2] = 0
    a[:150, 0] = rng.uniform(.5, 2, 150)
    a[150:300, 1] = rng.uniform(.5, 2, 150)
    b = a @ rng.normal(size=a.shape[1]) + rng.normal(size=len(a)) * .03
    x, c, meta, profile = _run(native, tmp_path / "merge", a, b, local=2, dynamic=6, block_rows=block_rows)
    expected, covariance = _reference(a, b)
    assert meta["merge_kernel"] == "LAPACK_DTPQRT_DTPMQRT"
    assert np.max(np.abs(x - expected) / np.sqrt(np.diag(covariance))) < 1e-7
    assert np.linalg.norm(c - covariance[2:, 2:]) / np.linalg.norm(covariance[2:, 2:]) < 1e-8
    nuisance = np.r_[0, 1, np.arange(8, a.shape[1])]
    residual = b - a[:, nuisance] @ np.linalg.lstsq(a[:, nuisance], b, rcond=None)[0]
    assert profile["linearized_profile_cost"] == pytest.approx(.5 * residual @ residual, rel=1e-11)


def test_native_local_global_and_unit_invariance(native, tmp_path):
    a, b = _problem()
    expected, covariance = _reference(a, b)
    unit = np.array([1., 1., 1e6, 1e-5, 1., 1e3])
    x, c, *_ = _run(native, tmp_path / "units", a * unit, b, local=2)
    np.testing.assert_allclose(x * unit, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(c * unit[2:, None] * unit[None, 2:], covariance[2:, 2:], rtol=1e-10, atol=1e-13)
    # Move the two clock columns into the retained system; selected covariance
    # must still agree with joint elimination rather than conditioning on clocks.
    x, c, *_ = _run(native, tmp_path / "global", a, b, local=0, dynamic=0)
    np.testing.assert_allclose(x, expected, atol=1e-12)
    np.testing.assert_allclose(c, covariance, rtol=1e-11, atol=1e-13)


def test_native_profile_holds_dynamics_fixed(native, tmp_path):
    a, b = _problem()
    x, *_ = _run(native, tmp_path / "profile", a, b, local=2, nuisance_only=True)
    assert np.array_equal(x[2:4], np.zeros(2))
    nuisance = [0, 1, 4, 5]
    expected = np.linalg.lstsq(a[:, nuisance], b, rcond=None)[0]
    np.testing.assert_allclose(x[nuisance], expected, rtol=1e-12, atol=1e-12)


def test_native_nuisance_potential_resolves_objective_subtraction_floor(native, tmp_path):
    a = np.zeros((12, 4))
    a[:4] = np.eye(4)
    b = np.r_[0., 0., 1e-4, -1e-4, np.full(8, 1e8)]
    _, _, _, profile = _run(native, tmp_path / "floor", a, b, local=0, dynamic=2)
    assert profile["direct_cost"] - profile["linearized_profile_cost"] == 0
    assert profile["nuisance_predicted_reduction"] == pytest.approx(1e-8, rel=1e-12)
    assert profile["retained_nuisance_gradient_scaled"] == pytest.approx(1e-4 / np.linalg.norm(b), rel=1e-12)


def test_native_full_bias_coordinates_survive_overlapping_phase_updates(native, tmp_path):
    # Code/TEC bases may be orthogonal while the TEC and phase bases overlap.
    # The shared physical signal-bias array cannot then serve as a coefficient read.
    basis = np.array([[1., -1., 0.], [-1., -1., 0.], [0., 1., 1.], [0., 1., 0.]])
    physical = np.array([.2, -.4, .1, .6])
    updates = np.diag([.1, .4, 1.2])
    initial = basis.T @ physical / np.sum(basis * basis, axis=0)
    expected = np.column_stack((initial, initial[:, None] + np.cumsum(updates, axis=1)))
    for name, values in (("basis", np.column_stack((basis, physical))), ("updates", updates)):
        np.savetxt(tmp_path / f"{name}.txt", values, fmt="%.17g", comments="",
                   header=f"groops matrix version=20200123\nMatrix( {len(values)} x {values.shape[1]} )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "basis.txt", "inputfileCoordinateUpdates": tmp_path / "updates.txt",
                        "outputfileSolution": tmp_path / "coordinates.txt", "outputPrefix": tmp_path / "coordinates"}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml", encoding="utf-8", xml_declaration=True)
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=120)
    (tmp_path / "native.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    coordinates = np.loadtxt(tmp_path / "coordinates.txt", skiprows=2)
    np.testing.assert_allclose(coordinates, expected, rtol=1e-14, atol=1e-15)
    assert coordinates[1, 3] == coordinates[1, 2]  # phase update has no TEC-prior derivative
    contaminated = basis[:, 1] @ (physical + basis @ updates.sum(axis=1)) / (basis[:, 1] @ basis[:, 1])
    assert abs(contaminated - coordinates[1, -1]) > .1
    # Full nonzero prior rows together with the shared measurement basis have
    # the independent joint MAP; penalizing only the latest update would differ.
    current = coordinates[:, -1]
    prior = np.diag([2., 3., .7])
    target = np.array([.4, -.2, .3, -.5])
    design = np.vstack((basis, prior))
    rhs = np.r_[target - basis @ current, -prior @ current]
    delta, covariance, _, _ = _run(native, tmp_path / "map", design, rhs, dynamic=0)
    optimum, expected_covariance = _reference(design, np.r_[target, np.zeros(3)])
    np.testing.assert_allclose(current + delta, optimum, atol=1e-14)
    np.testing.assert_allclose(covariance, expected_covariance, rtol=1e-13, atol=1e-15)


def test_native_lm_excluded_from_covariance(native, tmp_path):
    a, b = _problem()
    _, cov = _reference(a, b)
    x, c, meta, _ = _run(native, tmp_path / "lm", a, b, local=2, damping=1e4)
    scales = np.asarray(meta["scales"])
    damping_rows = np.zeros((2, a.shape[1]))
    damping_rows[0, 2] = 100 / scales[0]
    damping_rows[1, 3] = 100 / scales[1]
    expected = np.linalg.lstsq(np.vstack((a, damping_rows)), np.r_[b, 0., 0.], rcond=None)[0]
    np.testing.assert_allclose(x, expected, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(c, cov[2:, 2:], rtol=1e-11, atol=1e-13)


@pytest.mark.parametrize("kind", ["unused", "duplicate", "unresolved"])
def test_native_rank_failure_has_no_covariance(native, tmp_path, kind):
    if kind == "unresolved":
        # Unit-normalized columns with one singular value at ~5x the explicit
        # epsilon*max(m,n)*smax threshold. No artificial variance is permitted.
        a = np.eye(4)
        a[:, 1] = a[:, 0]
        a[1, 1] = 10 * np.finfo(float).eps * 4
    else:
        a = np.eye(4)
        a[:, 1] = 0 if kind == "unused" else a[:, 0]
    diagnostics = _run(native, tmp_path / kind, a, np.ones(4), success=False)
    assert diagnostics["rank_status"] == ("unresolved" if kind == "unresolved" else "deficient")


def test_native_matches_independent_gtsam_nuisance_elimination(native, tmp_path, record_property):
    pytest.importorskip("gtsam")
    from orbit_poc.comparison.density import independent_linear_gate
    a, b = _problem()
    gate = independent_linear_gate(a, b, [2, 3])
    record_property("gtsam_vs_qr_map_error_posterior_standard_deviations", gate["normalized_map_discrepancy"])
    record_property("gtsam_vs_qr_relative_covariance_error", gate["relative_covariance_error"])
    assert gate["passed"]
    x, c, *_ = _run(native, tmp_path / "gtsam", a, b, local=2)
    expected, covariance = _reference(a, b)
    assert np.max(np.abs(x - expected) / np.sqrt(np.diag(covariance))) < 1e-7
    assert np.linalg.norm(c[:2, :2] - covariance[2:4, 2:4]) / np.linalg.norm(covariance[2:4, 2:4]) < 1e-8


def test_native_restores_eliminated_group_energy_to_direct_objective(native, tmp_path):
    rng = np.random.default_rng(881)
    a = rng.normal(size=(40, 5))
    b = a @ np.array([4., .3, -.5, .1, 2.]) + rng.normal(size=40) * .03
    x, c, _, profile = _run(native, tmp_path / "group", a, b, dynamic=2, ionosphere=True)
    expected, covariance = _reference(a, b)
    np.testing.assert_allclose(x, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(c, covariance[1:, 1:], rtol=1e-11, atol=1e-13)
    assert profile["direct_cost"] == pytest.approx(.5 * b @ b, rel=1e-13)
    assert profile["group_eliminated_target_energy"] > 1.
    nuisance = [0, 3, 4]
    residual = b - a[:, nuisance] @ np.linalg.lstsq(a[:, nuisance], b, rcond=None)[0]
    assert profile["linearized_profile_cost"] == pytest.approx(.5 * residual @ residual, rel=1e-12)


@pytest.mark.parametrize("unresolved", [False, True])
def test_native_ambiguity_datum_distinguishes_gauges_from_unresolved_rank(native, tmp_path, unresolved):
    # Two disconnected bias/ambiguity components have independent exact gauges.
    # A weak additional row must not be silently classified as another gauge.
    a = np.array([[1., 0., 1., 0.], [0., 1., 0., 1.], [0., 0., 0., 0.], [0., 0., 0., 0.]])
    if unresolved:
        a[2, 2] = 10 * np.finfo(float).eps * 4
    rows = np.column_stack((a, np.zeros(len(a))))
    np.savetxt(tmp_path / "rows.txt", rows, fmt="%.17g", comments="",
               header=f"groops matrix version=20200123\nMatrix( {len(a)} x {rows.shape[1]} )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "selection.txt",
                        "outputPrefix": tmp_path / "datum", "datumSelection": 1,
                        "datumReceiverColumns": 1, "datumTransmitterColumns": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml", encoding="utf-8", xml_declaration=True)
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=120)
    (tmp_path / "native.log").write_text(result.stdout + result.stderr)
    if unresolved:
        assert result.returncode != 0
        assert "Unresolved ambiguity datum rank" in result.stdout + result.stderr
        assert not (tmp_path / "selection.txt").exists()
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        np.testing.assert_array_equal(np.loadtxt(tmp_path / "selection.txt", skiprows=2).reshape(-1), [1, 1, 0, 0])


@pytest.mark.parametrize("keep_intermediate", [False, True])
def test_native_factor_retention_and_secure_spool_do_not_change_arithmetic(native, tmp_path, keep_intermediate):
    a, b = _problem()
    spool = tmp_path / "spool"
    spool.mkdir()
    directory = tmp_path / "fit"
    x, c, meta, _ = _run(native, directory, a, b, local=2, generations=3,
                         keep_intermediate=keep_intermediate, spool_directory=spool)
    baseline_x, baseline_covariance, *_ = _run(native, tmp_path / "baseline", a, b, local=2)
    np.testing.assert_array_equal(x, baseline_x)
    np.testing.assert_array_equal(c, baseline_covariance)
    expected, covariance = _reference(a, b)
    np.testing.assert_allclose(x, expected, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(c, covariance[2:, 2:], rtol=1e-11, atol=1e-13)
    assert meta["keep_intermediate_factors"] is keep_intermediate
    assert meta["spool_policy"] == "unlinked_mkstemp"
    assert meta["spool_directory"] == str(spool)
    assert meta["row_spool_bytes"] == (len(a)-2) * (a.shape[1]-2+1) * 8
    assert list(spool.iterdir()) == []
    for generation in range(1, 4):
        for suffix in (".factor.json", ".diagnostics.json", ".profile.json", ".parameters.tsv", ".singular_values.txt", ".delta.tsv"):
            assert (directory / f"qr.{generation}{suffix}").is_file()
        for suffix in (".R.bin", ".z.bin", ".rhs.bin", ".rows.tsv"):
            assert (directory / f"qr.{generation}{suffix}").exists() is (keep_intermediate or generation == 3)
        if not keep_intermediate and generation < 3:
            receipt = json.loads((directory / f"qr.{generation}.retention.json").read_text())
            assert receipt["status"] == "completed"
            assert len(receipt["artifacts"]) == 4
            for item in receipt["artifacts"]:
                suffix = str(item["path"]).split(f"qr.{generation}", 1)[1]
                original = (tmp_path / "baseline" / f"qr.1{suffix}").read_bytes()
                assert item["bytes"] == len(original)
                assert item["sha256"] == hashlib.sha256(original).hexdigest()
                assert item["role"].startswith("superseded_")


def test_native_failed_successor_preserves_previous_factor_and_cleans_spool(native, tmp_path):
    a, b = _problem()
    spool = tmp_path / "spool"
    spool.mkdir()
    directory = tmp_path / "fit"
    _run(native, directory, a, b, local=2, generations=2, keep_intermediate=False,
         spool_directory=spool, fail_before_factor_generation=2, success=False)
    assert list(spool.iterdir()) == []
    assert (directory / "qr.1.R.bin").is_file()
    assert (directory / "qr.1.rhs.bin").is_file()
    assert (directory / "qr.1.rows.tsv").is_file()
    assert not (directory / "qr.2.R.bin").exists()
    assert "Injected fixture failure" in (directory / "native.log").read_text()


@pytest.mark.parametrize("mode", ["accept", "reject", "stationary", "support", "exception"])
def test_native_nuisance_search_is_transactional(native, tmp_path, mode):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "search.json",
                        "outputPrefix": tmp_path / "qr", "nuisanceFixture": mode}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "qr.parent.txt").read_text() == "parent\npreserved\n"
    report = json.loads((tmp_path / "search.json").read_text())
    if mode in ("accept", "stationary"):
        assert report["zero_update_replay"]["actual_reduction"] == 0
        assert report["zero_update_replay"]["maximum_update_m"] == 0
    if mode == "accept":
        assert report["accepted"] and report["alpha"] == .25
        assert len(report["trials"]) == 3
        assert report["undamped_maximum_update_m"] == 4.95
        assert report["trials"][-1]["actual_reduction"] > 0
    elif mode == "stationary":
        assert report["stationary_without_update"] and not report["accepted"]
        assert len(report["trials"]) == 1
    else:
        assert not report["stationary_without_update"] and not report["accepted"]
        assert len(report["trials"]) == 17
    if mode in ("support", "exception"):
        assert all(trial["status"] == 1 for trial in report["trials"])


@pytest.mark.parametrize("ionosphere", [False, True])
def test_native_cost_only_objective_has_no_factor_exports(native, tmp_path, ionosphere):
    a, b = _problem()
    if ionosphere:
        a = np.random.default_rng(519).normal(size=(48, 6))
    directory = tmp_path / "cost"
    _run(native, directory, a, b, local=0 if ionosphere else 2, ionosphere=ionosphere, cost_only=True)
    receipt = json.loads((directory / "qr.cost_only.json").read_text())
    assert receipt["after"] == receipt["before"]
    assert receipt["actual_reduction"] == 0
    assert receipt["same_support"]
    assert not list(directory.glob("qr.2.*"))


def _joint_epoch_problem():
    rng = np.random.default_rng(1834)
    observation = rng.normal(size=(28, 7))
    # Columns are STEC, clock, VTEC, two dynamics and two global biases.
    prior = np.diag([.8, 0., .25, .1, .2, .5, .6])
    full_reference = np.array([.4, 2., -.7, .2, -.6, .8, -.9])
    design = np.vstack((observation, prior))
    residual = np.r_[rng.normal(size=28) - observation @ full_reference, -prior @ full_reference]
    return design, residual


def test_native_joint_epoch_vtec_clock_stec_map_covariance_and_profile(native, tmp_path):
    a, b = _joint_epoch_problem()
    expected, covariance = _reference(a, b)
    x, c, meta, profile = _run(native, tmp_path / "local", a, b, local=2, dynamic=2,
                              ionosphere=True, joint_epoch=True, cost_only=True)
    assert meta["local_elimination"] == "independent_epoch_clock_vtec_qr"
    assert meta["local_global_indices"] == [0, 1]
    assert len(meta["local_scales"]) == 2
    np.testing.assert_allclose((x - expected) / np.sqrt(np.diag(covariance)), 0, atol=1e-7)
    assert np.linalg.norm(c - covariance[3:, 3:]) / np.linalg.norm(covariance[3:, 3:]) < 1e-8
    globally, global_covariance, *_ = _run(native, tmp_path / "global", a, b, dynamic=0)
    np.testing.assert_allclose(x, globally, rtol=1e-12, atol=1e-12)
    np.testing.assert_allclose(c, global_covariance[3:, 3:], rtol=1e-12, atol=1e-12)
    nuisance = [0, 1, 2, 5, 6]
    reference_profile = np.linalg.lstsq(a[:, nuisance], b, rcond=None)[0]
    residual = b - a[:, nuisance] @ reference_profile
    assert profile["direct_cost"] == pytest.approx(.5 * b @ b, rel=1e-13)
    assert profile["profile_cost"] == pytest.approx(.5 * residual @ residual, rel=1e-12)
    profiled, *_ = _run(native, tmp_path / "profile", a, b, local=2, dynamic=2,
                        ionosphere=True, joint_epoch=True, nuisance_only=True)
    np.testing.assert_allclose(profiled[nuisance], reference_profile, rtol=1e-12, atol=1e-12)
    assert np.array_equal(profiled[3:5], np.zeros(2))


def test_native_joint_epoch_vtec_clock_units_rows_damping_invariance(native, tmp_path):
    a, b = _joint_epoch_problem()
    expected, covariance = _reference(a, b)
    units = np.array([1e-5, 1e9, 1e-7, 1e4, 1e-3, 1., 1e2])
    order = np.random.default_rng(778).permutation(len(b))
    x, c, *_ = _run(native, tmp_path / "units", (a * units)[order], b[order], local=2, dynamic=2,
                    ionosphere=True, joint_epoch=True, block_rows=7)
    np.testing.assert_allclose(x * units, expected, rtol=1e-11, atol=1e-12)
    np.testing.assert_allclose(c * units[3:, None] * units[None, 3:], covariance[3:, 3:], rtol=1e-11, atol=1e-12)
    _, damped_covariance, *_ = _run(native, tmp_path / "damping", a, b, local=2, dynamic=2,
                                    ionosphere=True, joint_epoch=True, damping=1000)
    np.testing.assert_allclose(damped_covariance, covariance[3:, 3:], rtol=1e-12, atol=1e-12)


@pytest.mark.parametrize("defect", ["missing", "dependent", "near"])
def test_native_joint_epoch_local_rank_failures_reject_covariance(native, tmp_path, defect):
    rng = np.random.default_rng(73)
    a = rng.normal(size=(32, 5))
    if defect == "missing":
        a[:, 1] = 0
    elif defect == "dependent":
        a[:, 1] = a[:, 0]
    else:
        a[:, 1] = a[:, 0] + 5e-14 * rng.normal(size=len(a))
    result = _run(native, tmp_path / defect, a, rng.normal(size=len(a)), local=2, dynamic=2,
                  joint_epoch=True, success=False)
    assert "epoch clock/VTEC nuisance rank" in result["failure"]
    assert "unresolved" in result["failure"] if defect == "near" else "deficient" in result["failure"]


def test_native_continuous_interpolation_preserves_exact_grid_and_clock_derivative(native, tmp_path):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "interpolation.txt",
                        "outputPrefix": tmp_path / "qr", "interpolationFixture": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    values = np.loadtxt(tmp_path / "interpolation.txt", skiprows=2)
    np.testing.assert_allclose(values[:, 3], values[:, 5], rtol=0, atol=2e-8)
    np.testing.assert_allclose(values[:, 4], 7000., rtol=1e-11, atol=0)
    assert np.max(values[:, 6]) < 2e-8
    assert np.array_equal(values[:, 7], np.zeros(14))
    for margin in (1e-7, 1e-5):
        selected = values[values[:, 0] == margin]
        # The historical shortcut has an orbit-sized discontinuity near the
        # negative clock-offset boundary; the QR path evaluates the polynomial.
        assert np.max(np.abs(selected[:, 2] - selected[:, 5])) > .9 * margin * 7000
        numerical = (selected[1, 3] - selected[0, 3]) / (selected[1, 1] - selected[0, 1])
        assert numerical == pytest.approx(7000., rel=.002)


def test_native_lossless_rows_survive_intermediate_factor_cleanup(native, tmp_path):
    a, b = _problem()
    raw = tmp_path / "raw"
    expected, covariance, *_ = _run(native, raw, a, b, local=2)
    compact = tmp_path / "compressed"
    x, c, metadata, _ = _run(native, compact, a, b, local=2, generations=3,
                             keep_intermediate=False, compress_rows=True)
    np.testing.assert_array_equal(x, expected)
    np.testing.assert_array_equal(c, covariance)
    assert metadata["row_provenance_policy"] == "verified_row_compression_v1"
    original = (raw / "qr.1.rows.tsv").read_bytes()
    for generation in range(1, 4):
        source = compact / f"qr.{generation}.rows.tsv"
        packed = Path(str(source) + ".gz")
        receipt = json.loads(Path(str(source) + ".compression.json").read_text())
        assert not source.exists()
        assert gzip.decompress(packed.read_bytes()) == original
        assert receipt["policy"] == "verified_row_compression_v1"
        assert receipt["role"] == "closed_native_row_provenance"
        assert receipt["compression_level"] == 6
        assert receipt["round_trip_verified"] and receipt["crc_verified"]
        assert receipt["source"] == {"path": str(source), "sha256": hashlib.sha256(original).hexdigest(), "bytes": len(original)}
        assert receipt["compressed"] == {"path": str(packed), "sha256": hashlib.sha256(packed.read_bytes()).hexdigest(), "bytes": packed.stat().st_size}
        assert (compact / f"qr.{generation}.R.bin").exists() == (generation == 3)
    for generation in (1, 2):
        removed = json.loads((compact / f"qr.{generation}.retention.json").read_text())["artifacts"]
        assert all("row_provenance" not in item["role"] for item in removed)


def test_native_lossless_rows_preserve_previous_generation_on_successor_failure(native, tmp_path):
    a, b = _problem()
    directory = tmp_path / "failed"
    _run(native, directory, a, b, local=2, generations=2, keep_intermediate=False,
         compress_rows=True, fail_before_factor_generation=2, success=False)
    assert (directory / "qr.1.R.bin").exists()
    assert (directory / "qr.1.rows.tsv.gz").exists()
    assert (directory / "qr.1.rows.tsv.compression.json").exists()
    assert not (directory / "qr.1.retention.json").exists()


def test_native_corrected_range_preserves_subnanometre_clock_updates(native, tmp_path):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "range.txt",
                        "outputPrefix": tmp_path / "qr", "rangeResidualFixture": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    values = np.loadtxt(tmp_path / "range.txt", skiprows=2)
    np.testing.assert_allclose(values[:, 1], values[:, 0], rtol=0, atol=2e-14)
    assert np.max(np.abs(values[:, 2] - values[:, 0])) > 1e-9
    assert values[0, 2] == 0 and values[0, 1] != 0


def test_native_receiver_clock_shift_avoids_negative_duration_loss_and_records_intrinsic_floor(native, tmp_path, record_property):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "time.txt",
                        "outputPrefix": tmp_path / "qr", "clockTimeFixture": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    values = np.loadtxt(tmp_path / "time.txt", skiprows=2)
    early = values[values[:, 0] == 3600.][0]
    assert early[1] > 4e-12 and early[2] < 4e-13
    assert np.max(values[:, 2]) < 5.6e-12
    assert np.max(values[:, 2]) > 4e-12  # native fractional-day storage remains finite
    assert np.max(values[:, 3]) > 3e-8
    assert np.max(values[:, 4]) < 8e-10
    assert np.max(values[:, 5]) < 1e-8
    record_property("maximum_relative_query_position_error_m", float(np.max(values[:, 4])))
    record_property("maximum_direct_shift_time_error_seconds", float(np.max(values[:, 2])))
    record_property("early_day_legacy_time_error_seconds", float(early[1]))
    record_property("early_day_direct_shift_time_error_seconds", float(early[2]))


def test_native_relative_clock_queries_preserve_exact_pulse_side(native, tmp_path):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "pulse.txt",
                        "outputPrefix": tmp_path / "qr", "relativePulseFixture": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    values = np.loadtxt(tmp_path / "pulse.txt", skiprows=2)
    np.testing.assert_allclose(values[:, 2], values[:, 1], rtol=0, atol=1e-14)
    assert np.max(np.abs(values[:, 3] - values[:, 1])) == 1


def test_native_subdouble_coordinate_remainders_preserve_range_changes(native, tmp_path):
    from decimal import Decimal, localcontext
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "range.txt",
                        "outputPrefix": tmp_path / "qr", "precisePositionFixture": 1}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    values = np.loadtxt(tmp_path / "range.txt", skiprows=2)
    with localcontext() as context:
        context.prec = 60
        receiver, transmitter = Decimal(6900000), Decimal(26000000)
        gm, c = Decimal("3.986004418e14"), Decimal(299792458)
        expected = []
        for row in values:
            shifted = Decimal.from_float(float(row[3])) + Decimal.from_float(float(row[4]))
            change = shifted - receiver - 2 * gm / (c*c) * ((transmitter/shifted).ln() - (transmitter/receiver).ln())
            expected.append(float(change))
    np.testing.assert_allclose(values[:, 1], expected, rtol=0, atol=4e-12)
    assert np.max(np.abs(values[:, 2] - expected)) > 1e-10
    assert values[5, 2] == 0 and values[5, 1] != 0


@pytest.mark.parametrize("mode,expected", [
    ("floor_accept", ""),
    ("floor_refine", ""),
    ("floor_small_direction", ""),
    ("floor_influence_cap", "required_probe_influence_exceeds_limit"),
    ("floor_actual_influence", "actual_probe_influence_exceeds_limit"),
    ("floor_derived_nonfinite", "nonfinite_symmetric_probe_diagnostics"),
    ("floor_numeric_cap", "required_probe_amplitude_exceeds_numeric_limit"),
    ("floor_audit_exception", "fixed_parameter_arithmetic_audit_failed"),
    ("floor_audit_nonfinite", "fixed_parameter_arithmetic_audit_failed"),
    ("floor_probe_nonfinite", "symmetric_probe_failed"),
    ("floor_allowance", "empirical_quadratic_potential_with_allowance_exceeds_resolution"),
    ("floor_audit_support", "fixed_parameter_arithmetic_audit_failed"),
    ("floor_zero_resolution", "potential_not_within_positive_measured_resolution"),
    ("floor_small_resolution", "potential_not_within_positive_measured_resolution"),
    ("floor_zero_replay", "zero_update_replay_failed"),
    ("floor_probe_support", "symmetric_probe_failed"),
    ("floor_probe_exception", "symmetric_probe_failed"),
    ("floor_wrong_slope", "symmetric_slope_disagrees_with_undamped_gradient"),
    ("floor_negative_curvature", "negative_or_unresolved_symmetric_curvature"),
    ("floor_unresolved_curvature", "negative_or_unresolved_symmetric_curvature"),
    ("floor_amplitude", "amplitude_dependent_symmetric_curvature"),
    ("floor_weak_curvature", "empirical_quadratic_potential_exceeds_resolution"),
])
def test_native_empirical_nuisance_floor_requires_independent_audits(native, tmp_path, mode, expected):
    np.savetxt(tmp_path / "rows.txt", [[1., 0.]], comments="", header="groops matrix version=20200123\nMatrix( 1 x 2 )")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": tmp_path / "rows.txt", "outputfileSolution": tmp_path / "search.json",
                        "outputPrefix": tmp_path / "qr", "nuisanceFixture": mode}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(root).write(tmp_path / "run.xml")
    result = subprocess.run([native, str(tmp_path / "run.xml")], text=True, capture_output=True,
                            env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"), timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "qr.parent.txt").read_text() == "parent\npreserved\n"
    report = json.loads((tmp_path / "search.json").read_text())
    assert not report["accepted"] and not report["stationary_without_update"]
    assert report["floor_rejection"] == expected
    assert report["nuisance_floor_limited"] == (not expected)
    assert len(report["trials"]) == 17
    assert report["maximum_probe_influence_m"] == 1
    assert report["maximum_probe_amplitude"] == 1e9
    if mode == "floor_influence_cap":
        assert report["requested_probe_influence_m"] > 1 and report["completed_probe_rounds"] == 0
    if mode == "floor_numeric_cap":
        assert report["requested_probe_amplitude"] > 1e9 and report["completed_probe_rounds"] == 0
    if not expected:
        assert report["nuisance_objective_resolution"] == ({"floor_refine": 1.01e-8, "floor_small_direction": 1e-8}.get(mode, 4e-8))
        assert report["full_step_prediction"] <= report["nuisance_objective_resolution"]
        audits = report["nuisance_floor_audit"]
        assert len(audits) == 4
        assert all(a["success"] and a["support_unchanged"] for a in audits)
        assert [a["mode"] for a in audits[:3]] == [1, 2, 3]
        probes = audits[-1]
        a = probes["amplitude"]
        assert [p["alpha"] for p in probes["probes"]] == [a, -a, a / 2, -a / 2]
        assert probes["slope"] == pytest.approx(-2 * report["full_step_prediction"], rel=1e-5, abs=1e-20)
        assert probes["curvature"] == pytest.approx(4 * probes["half_curvature"])
        assert all(p["maximum_update_m"] <= 1 for p in probes["probes"])
        assert 0 < probes["empirical_quadratic_potential_with_allowance"] <= report["nuisance_objective_resolution"]
        assert 0 < probes["half_empirical_quadratic_potential_with_allowance"] <= report["nuisance_objective_resolution"]
        history = probes["probe_history"]
        assert history[-1]["success"] and history[-1]["amplitude"] == a
        assert len(history) <= 5 and a <= 1e9
        assert a * report["undamped_maximum_update_m"] <= 1
        if mode == "floor_small_direction":
            assert a > 1024
        if mode == "floor_refine":
            assert len(history) > 1
            assert all(item["rejection"] == "empirical_quadratic_potential_with_allowance_exceeds_resolution" for item in history[:-1])
            assert all(after["amplitude"] == 2 * before["amplitude"] for before, after in zip(history, history[1:]))
    elif mode == "floor_allowance":
        history = report["nuisance_floor_audit"][-1]["probe_history"]
        assert len(history) > 1 and not any(item["success"] for item in history)
        assert history[-1]["amplitude"] * report["undamped_maximum_update_m"] <= 1 < 2 * history[-1]["amplitude"] * report["undamped_maximum_update_m"]


def test_native_floor_limited_profile_cannot_export_covariance(native, tmp_path, monkeypatch):
    monkeypatch.setenv("ORBIT_POC_NUMERICS_NUISANCE_FLOOR_LIMITED", "1")
    a, b = _problem()
    directory = tmp_path / "covariance"
    _run(native, directory, a, b, local=2, success=False)
    assert "No covariance for empirically floor-limited nuisance profile" in (directory / "native.log").read_text()
    assert not (directory / "covariance.txt").exists()
