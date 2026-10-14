"""Targeted native acceptance gaps beyond the general weighted-row QR suite.

These are small weighted-row systems, not simulated GNSS fits. Actual native
pulse/OU constraint generation and nonlinear nuisance profiling are checked by
scripts/validate_numerics_objective.py. Here the same native QR kernel is checked
against independent GTSAM and closed-form OU results using nonzero references.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.density import independent_linear_gate


@pytest.fixture
def native():
    value = os.environ.get("ORBIT_POC_V31_NATIVE")
    if not value:
        pytest.skip("ORBIT_POC_V31_NATIVE is required for native acceptance gates")
    return value


def _native_rows(native, directory, design, target, *, local=0, dynamic=0, failure=None):
    directory.mkdir(parents=True)
    rows = np.column_stack((design, target))
    np.savetxt(directory / "rows.txt", rows, fmt="%.17g", comments="",
               header=f"groops matrix version=20200123\nMatrix( {len(rows)} x {rows.shape[1]} )")
    tree = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(tree, "program"), "OrbitPocQrSolve")
    for name, value in {"inputfileRows": directory / "rows.txt",
                        "outputfileSolution": directory / "solution.txt",
                        "outputfileCovariance": directory / "covariance.txt",
                        "outputPrefix": directory / "qr", "localColumns": local,
                        "dynamicColumns": dynamic}.items():
        ET.SubElement(program, name).text = str(value)
    ET.ElementTree(tree).write(directory / "run.xml", encoding="utf-8", xml_declaration=True)
    result = subprocess.run([native, str(directory / "run.xml")], capture_output=True, text=True,
        timeout=120, env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1"))
    log = result.stdout + result.stderr
    (directory / "native.log").write_text(log)
    if failure is not None:
        assert result.returncode != 0, log
        assert not (directory / "covariance.txt").exists()
        diagnosis = json.loads((directory / "qr.1.diagnostics.json").read_text())
        assert diagnosis["rank_status"] == failure, diagnosis
        return diagnosis
    assert result.returncode == 0, log
    return (np.loadtxt(directory / "solution.txt", skiprows=2).reshape(-1),
            np.atleast_2d(np.loadtxt(directory / "covariance.txt", skiprows=2)),
            json.loads((directory / "qr.1.profile.json").read_text()))


def _ou_rows(knots, tau, sigma):
    """Construct innovations directly from the published discrete model."""
    times = np.asarray(knots, dtype=float)
    factor = np.zeros((len(times), len(times)))
    factor[0, 0] = 1 / sigma
    for index, dt in enumerate(np.diff(times), start=1):
        phi = np.exp(-dt / tau)
        deviation = sigma * np.sqrt(-np.expm1(-2 * dt / tau))
        factor[index, index - 1] = -phi / deviation
        factor[index, index] = 1 / deviation
    return factor


def _full_reference_problem(method):
    rng = np.random.default_rng(70231)
    local, initial, forces, global_nuisance = 3, 2, 6, 3
    dynamic = initial + forces
    count = local + dynamic + global_nuisance
    measurement = rng.normal(size=(72, count))
    measurement[:, :local] = 0
    for epoch in range(local):
        measurement[24 * epoch:24 * (epoch + 1), epoch] = rng.uniform(.5, 1.5, 24)
    force_indices = np.arange(local + initial, local + dynamic)
    if method == "pulses":
        # Two inertial three-component pulses, in native micrometres/second.
        force_rows = np.eye(forces) / 100.
        force_reference = np.array([40., -20., 10., -30., 50., 15.])
        measurement[:, force_indices] *= .003
    else:
        force_rows = _ou_rows(np.arange(forces) * 60., tau=1800., sigma=.1)
        force_reference = np.array([.09, -.04, .06, .02, -.03, .08])
        measurement[:, force_indices] *= 4.
    current = np.r_[20., -10., 7., .4, -.25, force_reference, .2, -.3, .1]
    truth = rng.normal(size=count)
    truth[force_indices] = force_reference * .35
    observed = measurement @ truth + rng.normal(size=len(measurement)) * .2
    prior = np.zeros((forces, count))
    prior[:, force_indices] = force_rows
    design = np.vstack((measurement, prior))
    target = np.r_[observed, np.zeros(forces)]
    return design, target, current, local, dynamic, force_indices


@pytest.mark.parametrize("method", ["pulses", "density"])
def test_native_full_reference_map_and_cross_covariance_match_gtsam(native, tmp_path, record_property, method):
    pytest.importorskip("gtsam")
    a, absolute_target, current, local, dynamic, force_indices = _full_reference_problem(method)
    residual = absolute_target - a @ current
    delta, covariance, profile = _native_rows(native, tmp_path / method, a, residual,
                                             local=local, dynamic=dynamic)
    retained = np.arange(local, a.shape[1])
    reference = independent_linear_gate(a, absolute_target, retained)
    assert reference["passed"], reference
    gtsam_mean = np.asarray(reference["gtsam_map"])
    standard_deviation = np.asarray(reference["qr_marginal_standard_deviations"])
    gtsam_covariance = np.asarray(reference["gtsam_state_covariance"])
    map_error = float(np.max(np.abs(current + delta - gtsam_mean) / standard_deviation))
    covariance_error = float(np.linalg.norm(covariance - gtsam_covariance) / np.linalg.norm(gtsam_covariance))
    # Explicit dynamic/global-nuisance cross-block, rather than diagonal-only
    # uncertainty, checks that nuisance uncertainty has been marginalized.
    cross = np.ix_(np.arange(dynamic), np.arange(dynamic, len(retained)))
    expected_cross = gtsam_covariance[cross]
    assert np.linalg.norm(expected_cross) > 1e-6
    cross_error = float(np.linalg.norm(covariance[cross] - expected_cross) / np.linalg.norm(expected_cross))
    record_property("native_gtsam_map_error_posterior_standard_deviations", map_error)
    record_property("native_gtsam_relative_covariance_error", covariance_error)
    record_property("native_gtsam_relative_dynamic_nuisance_cross_covariance_error", cross_error)
    assert map_error < 1e-7
    assert covariance_error < 1e-8
    assert cross_error < 1e-8
    assert profile["direct_cost"] == pytest.approx(.5 * residual @ residual, rel=2e-13)
    prior_residual = residual[-len(force_indices):]
    assert .5 * prior_residual @ prior_residual > .1
    # This test must distinguish full-parameter penalties from an incorrect
    # penalty applied only to the latest update.
    wrong_residual = residual.copy()
    wrong_residual[-len(force_indices):] = 0
    wrong_delta = np.linalg.lstsq(a, wrong_residual, rcond=None)[0]
    wrong_error = float(np.max(np.abs(current + wrong_delta - gtsam_mean) / standard_deviation))
    record_property("update_only_prior_counterexample_error_posterior_standard_deviations", wrong_error)
    assert wrong_error > .01


def test_native_coupled_ou_covariance_and_missing_stationary_constraint(native, tmp_path, record_property):
    # Irregular final interval is legal in the versioned knot discretization.
    knots = np.array([0., 60., 120., 180., 240., 275.])
    tau, sigma = 1800., .1
    factor = _ou_rows(knots, tau, sigma)
    reference = np.array([.12, -.03, .08, -.11, .04, .09])
    delta, covariance, profile = _native_rows(native, tmp_path / "proper", factor,
                                             -factor @ reference, dynamic=len(knots))
    expected = sigma**2 * np.exp(-np.abs(knots[:, None] - knots[None, :]) / tau)
    error = float(np.linalg.norm(covariance - expected) / np.linalg.norm(expected))
    record_property("native_ou_closed_form_relative_covariance_error", error)
    assert error < 1e-8
    np.testing.assert_allclose(reference + delta, 0, atol=1e-13)
    assert profile["direct_cost"] == pytest.approx(.5 * np.linalg.norm(factor @ reference)**2, rel=1e-13)
    # Transition rows alone leave one exponentially decaying mode unanchored.
    # Every column is used, so this is not the generic unused-column fixture.
    missing = factor.copy()
    missing[0] = 0
    assert np.all(np.linalg.norm(missing, axis=0) > 0)
    null_direction = np.exp(-(knots - knots[0]) / tau)
    np.testing.assert_allclose(missing @ null_direction, 0, atol=1e-13)
    result = _native_rows(native, tmp_path / "missing-stationary-prior", missing,
                         -missing @ reference, dynamic=len(knots), failure="deficient")
    assert result["rank"] == len(knots) - 1


def test_phase_report_preserves_original_observation_scale_after_integer_recentering(tmp_path):
    from orbit_poc.numerics.protocol import artifact
    from orbit_poc.numerics.report import _phase_difference

    columns = ["GPSMJD", "PRN", "type", "input_m", "processed_m", "removed_windup_m",
        "fitted_ambiguity_m", "receiver_bias_m", "transmitter_bias_m", "STEC", "TEC_factor_m",
        "residual_m", "sigma_m", "clock_m", "track_start_GPSMJD", "track_end_GPSMJD"]
    # A coupled frequency basis is essential: rounding occurs in native
    # ambiguity coordinates, while observations and the exporter use metres.
    transform = np.array([[.25, -.5], [.125, .25]])
    full_cycles = np.array([.52, -.47])
    integer = np.array([1., 0.])
    full_ambiguity = transform @ full_cycles
    recentered_ambiguity = transform @ (full_cycles - integer)
    removed_metres = transform @ integer
    original = np.array([101., 103.])
    windup = np.array([.125, -.25])
    initial_removal = np.array([2., -4.])
    processed = original - windup - initial_removal
    residual = np.array([.0015, -.003])

    def export(name, recentered, observed=original):
        path = tmp_path / f"{name}.txt"
        with path.open("w") as stream:
            stream.write("# " + " ".join(columns) + "\n")
            for i in range(2):
                values = [60424., 1, ("L1CG**", "L2WG**")[i], observed[i],
                    processed[i] - (removed_metres[i] if recentered else 0.), windup[i],
                    recentered_ambiguity[i] if recentered else full_ambiguity[i],
                    .1, -.2, 3., -.4, residual[i], .003, 4., 60424., 60424.1]
                stream.write(" ".join(str(value) for value in values) + "\n")
        return {"artifacts": [{"role": "phase_recovery", **artifact(path)}]}

    # Both representations have the same processed-observation minus ambiguity,
    # hence the same physical residual and canonical original-scale prediction.
    np.testing.assert_array_equal(processed - removed_metres - recentered_ambiguity,
                                  processed - full_ambiguity)
    legacy, full = export("legacy", True), export("full-float", False)
    compared = _phase_difference(legacy, full)
    assert compared["matched_observations"] == 2
    assert compared["prediction_difference_m"]["maximum_absolute"] == 0
    assert compared["prediction_difference_in_assumed_sigmas"]["rms"] == 0
    # Integer recentering is legitimate only within the representation. A real
    # change to original measured y must not silently pass this comparison.
    changed = export("changed-input", False, original - removed_metres)
    with pytest.raises(ValueError, match="input_m"):
        _phase_difference(legacy, changed)
