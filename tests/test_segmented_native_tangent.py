"""Small actual-GROOPS gate for exported local tangent/design operators.

Run with ORBIT_POC_SEGMENTED_GROOPS pointing at a --numerics --segmented build.
It reuses the independently propagated v3.1 synthetic fixtures unchanged and
adds exports. No GNSS fit, flight data, or benchmark outcome is substituted.
"""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pytest
from scipy.sparse import lil_matrix
from scipy.sparse.linalg import spsolve

from orbit_poc.comparison.backend import read_native_table

ROOT = Path(__file__).resolve().parents[1]


def records(path):
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[-1] == {"kind": "complete"}
    return rows


def verify_variation_export(directory):
    exported = records(directory / "local-design.jsonl")
    meta = exported[0]
    n, p = meta["epochs"], meta["parameter_count"]
    assert meta["initial_parameter_offset"] == p-6
    assert meta["post_pulse"] is True
    phi = {row["index"]: np.array(row["phi"]).reshape(6, 6)
           for row in exported if row["kind"] == "epoch"}
    forcing = {row["index"]: row["integrand"] for row in exported if row["kind"] == "forcing"}
    e, f = lil_matrix((6*n, 6*n)), np.zeros((6*n, p))
    e[:6, :6] = np.eye(6)
    f[:6, -6:] = np.eye(6)
    for row in exported:
        if row["kind"] == "quadrature":
            k = row["interval"]
            e[6*(k+1):6*(k+2), 6*(k+1):6*(k+2)] = np.eye(6)
            e[6*(k+1):6*(k+2), 6*k:6*(k+1)] = -np.eye(6)
            for sample, weight, _ in row["terms"]:
                for component, column, value in forcing[sample]:
                    f[6*(k+1)+component, column] += weight*value
        if row["kind"] == "pulse":
            i, col = row["epoch"], row["parameter"]
            f[6*i:6*i+6, col:col+3] += np.array(row["map"]).reshape(6, 3)
    c = spsolve(e.tocsc(), f)
    reconstructed = np.concatenate([phi[i] @ c[6*i:6*i+6] for i in range(n)])
    native = read_native_table(directory / "native-design.txt", p)
    np.testing.assert_allclose(reconstructed, native, rtol=2e-11, atol=2e-11)
    np.testing.assert_allclose(reconstructed[:6, -6:], phi[0], rtol=0, atol=0)
    return meta


def verify_tangent_export(directory):
    exported = records(directory / "local-tangent.jsonl")
    meta = exported[0]
    assert meta["maximum_tangent_relative_residual"] <= 2e-12
    assert meta["nominal_force_history"] == "unchanged_whole_arc"
    assert meta["new_process_priors"] is False
    n, dt = meta["epochs"], meta["dt"]
    samples = {(row["channel"], row["index"]): row for row in exported if row["kind"] == "sample"}
    e = lil_matrix((6*n, 6*n))
    for i in range(n):
        e[6*i:6*i+6, 6*i:6*i+6] = np.eye(6)
        if i:
            e[6*i:6*i+6, 6*(i-1):6*i] = -np.eye(6)
            e[6*i:6*i+3, 6*(i-1)+3:6*i] = -dt*np.eye(3)
    for row in exported:
        if row["kind"] != "quadrature":
            continue
        k = row["interval"]
        for sample, integral, moment in row["terms"]:
            node = samples[row["channel"], sample]
            for offset, derivative, halo in [(0, "Ar", "position_halo"), (3, "Av", "velocity_halo")]:
                jac = np.array(node[derivative]).reshape(3, 3)
                for epoch, weight, high, low in node[halo]:
                    assert abs(weight-(float.fromhex(high)+float.fromhex(low))) <= abs(np.spacing(weight))
                    e[6*(k+1):6*(k+1)+3, 6*epoch+offset:6*epoch+offset+3] -= (dt*integral-moment)*weight*jac
                    e[6*(k+1)+3:6*(k+2), 6*epoch+offset:6*epoch+offset+3] -= integral*weight*jac
    b = np.zeros((6*n, 6))
    b[:3, :3] = np.eye(3)
    b[3:6, 3:6] = meta["initial_velocity_scale"]*np.eye(3)
    local = spsolve(e.tocsc(), b)
    # The independent native diagnostic exports physical initial SI columns.
    rows = read_native_table(directory / "transition.txt", 43)
    reference = rows[:, 7:].reshape(n, 6, 6)
    normalized = local.reshape(n, 6, 6) @ np.linalg.inv(local[:6])
    np.testing.assert_allclose(normalized, reference, rtol=2e-9, atol=2e-9)


def verify_cartesian_queries(directory):
    records_ = [json.loads(line) for line in (directory / "covariance-queries.jsonl").read_text().splitlines()]
    assert records_[0]["schema"] == "orbit-poc-segmented-covariance-queries-v1"
    assert records_[0]["post_pulse_velocity"] and not records_[0]["covariance_produced"]
    assert records_[-1] == {"kind": "complete", "trajectory_count": 121, "nominal_observation_count": 241}
    states = [r for r in records_ if r["kind"] == "state"]
    p = states[0]["native_count"]
    grid = read_native_table(directory / "native-design.txt", p).reshape(121, 6, p)
    reference = read_native_table(directory / "native-query-design.txt", p).reshape(241, 6, p)
    queried = []
    for row in states:
        assert row["native_first"] == row["receiver"] == row["arc"] == 0
        result = np.zeros((6, p))
        for offset, key in ((0, "position_halo"), (3, "velocity_halo")):
            for epoch, rounded, high, low in row[key]:
                result[offset:offset+3] += rounded * grid[epoch, offset:offset+3]
        if row["set"] == "trajectory":
            np.testing.assert_array_equal(result, grid[row["index"]])
        else:
            queried.append(result)
    queried = np.asarray(queried)
    np.testing.assert_allclose(queried, reference, rtol=2e-11, atol=2e-11)
    # A full SPD parameter covariance exposes all position/velocity and pulse
    # cross terms. No result from the dense native covariance exporter is used.
    z = np.random.default_rng(47291).normal(size=(p, p))
    covariance = z @ z.T + np.eye(p)
    actual = queried @ covariance @ queried.transpose(0, 2, 1)
    expected = reference @ covariance @ reference.transpose(0, 2, 1)
    scales = np.sqrt(np.diagonal(expected, axis1=1, axis2=2))
    assert np.max(np.linalg.norm((actual-expected)/scales[:, :, None]/scales[:, None, :], axis=(1, 2))) < 1e-8


@pytest.mark.parametrize("profile,density", [("synthetic_complete_v1", False),
                                             ("synthetic_complete_v1", True),
                                             ("flight_gravity_drag_v1", False)])
def test_actual_native_local_operator_export(tmp_path, monkeypatch, profile, density):
    executable = os.environ.get("ORBIT_POC_SEGMENTED_GROOPS")
    if not executable:
        pytest.skip("set ORBIT_POC_SEGMENTED_GROOPS to execute the actual native export gate")
    # Exercise the actual opt-in coefficient arithmetic and tiny-Time query
    # conventions, even though these small programs do not create GNSS rows.
    monkeypatch.setenv("ORBIT_POC_NUMERICS_QR_PREFIX", str(tmp_path / "native-prefix"))
    spec = importlib.util.spec_from_file_location("existing_native_tangent_fixture", ROOT / "tests/test_numerics_derivatives.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    original_run = fixture._run

    def export_run(binary, config, directory):
        propagation = config.find(".//PreprocessingVariationalEquation")
        if propagation is not None:
            fixture._add(propagation, "orbitPocSegmentedTangentExport", directory / "local-tangent.jsonl")
        evaluation = config.find(".//OrbitPocEvaluateVariational")
        if evaluation is not None:
            fixture._add(evaluation, "outputfileSegmentedDesign", directory / "local-design.jsonl")
            fixture._add(evaluation, "outputfileSegmentedReferenceDesign", directory / "native-design.txt")
            fixture._add(evaluation, "outputfileSegmentedCovarianceQueries", directory / "covariance-queries.jsonl")
            fixture._add(evaluation, "outputfileSegmentedQueryReferenceDesign", directory / "native-query-design.txt")
            grid = fixture._add(fixture._add(evaluation, "segmentedQueryTimeSeries"), "uniformSampling")
            for name, value in (("timeStart", 60000), ("timeEnd", "60000+600/86400"), ("sampling", "2.5/86400")):
                fixture._add(grid, name, value)
        return original_run(binary, config, directory)

    fixture._run = export_run
    fixture.test_actual_native_complete_synthetic_transition(executable, tmp_path, profile, density)
    verify_tangent_export(tmp_path)
    if profile == "synthetic_complete_v1":
        verify_variation_export(tmp_path)
        verify_cartesian_queries(tmp_path)
