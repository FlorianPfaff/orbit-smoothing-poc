"""Original-coordinate LM and covariance through exact segment conditionals."""
from dataclasses import replace
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from orbit_poc.numerics.optimizer import (
    Linearization, NumericalFailure, proposal, selected_covariance,
)
from orbit_poc.segmented.solver import (
    EliminationGroup, SegmentedGraph, SegmentedLinearSystem, SparseRow, Variable,
    linearization_digest,
)


@pytest.fixture(scope="module")
def segment_driver(tmp_path_factory):
    supplied = os.environ.get("ORBIT_POC_SEGMENTED_SOLVER")
    if supplied:
        return Path(supplied)
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.fail("Native C++ compiler is required for the segmented acceptance tests")
    source = Path(__file__).resolve().parents[1] / "groops/extension/segmentedQrMain.cpp"
    directory = tmp_path_factory.mktemp("segment-driver")
    output = directory / "segmented-qr"
    result = subprocess.run([compiler, "-std=c++17", "-O2", str(source),
                             "-Wl,-l:liblapack.so.3", "-Wl,-l:libblas.so.3", "-o", str(output)],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    return output


def problem(auxiliary_scale=1.):
    # q0 = initial state, q1 = force coordinate, q2 = shared GNSS bias.
    # x1=q0+q1, x2=x1+q1 are deterministic auxiliary states.
    a = np.array([[1., 1., 2.], [1., 2., -1.], [1/3, 0., 0.],
                  [0., 10., 0.], [0., 0., 2.], [1., 2., 1.]])
    b = np.array([1.1, 2.3, .2, -.4, .1, 2.])
    scales = 1 / np.linalg.norm(a, axis=0)
    q, r = np.linalg.qr(a * scales)
    point = Linearization(r, q.T @ b, scales, np.array([True, True, False]),
                          len(b), .5*float(b@b), float(np.linalg.norm(b-q@(q.T@b))**2),
                          "same-clock-bias-and-ambiguity-support", None)
    variables = tuple(Variable(i, 1, scales[i], 0 if i == 0 else 1, f"q{i}", "native")
                      for i in range(3)) + (
        Variable(3, 0, auxiliary_scale, 1, "x1", "m"),
        Variable(4, 0, auxiliary_scale, 1, "x2", "m"))
    equalities = (SparseRow(100, 0, 0., ((3, 1.), (0, -1.), (1, -1.)), "first interval"),
                  SparseRow(101, 1, 0., ((4, 1.), (3, -1.), (1, -1.)), "second interval"))
    rows = (SparseRow(0, 0, b[0], ((3, 1.), (2, 2.)), "observation1"),
            SparseRow(1, 1, b[1], ((4, 1.), (2, -1.)), "observation2"),
            SparseRow(2, 0, b[2], ((0, 1/3),), "initial prior"),
            SparseRow(3, 0, b[3], ((1, 10.),), "full force prior"),
            SparseRow(4, 1, b[4], ((2, 2.),), "global bias prior"),
            SparseRow(5, 1, b[5], ((4, 1.), (2, 1.)), "observation3"))
    groups = (EliminationGroup(0, (0,), ()), EliminationGroup(1, (3,), (1, 2, 4)))
    graph = SegmentedGraph(variables, equalities, rows, groups, (0, 1, 2),
                           linearization_digest(point), point.support_hash).validate()
    return point, graph


@pytest.mark.parametrize("damping", [0., 1e-3, 1., 1e6])
def test_segmented_step_preserves_original_coordinate_lm(segment_driver, tmp_path, damping):
    dense, graph = problem()
    system = SegmentedLinearSystem(graph, segment_driver, tmp_path)
    segmented = replace(dense, linear_system=system).validate()
    reference = proposal(dense, damping)
    actual = proposal(segmented, damping)
    std = np.sqrt(np.diag(selected_covariance(dense, np.eye(3))))
    assert np.max(np.abs(actual[0]-reference[0])/std) < 1e-7
    assert actual[1] == pytest.approx(reference[1], rel=1e-9, abs=1e-12)
    assert actual[2] == reference[2]
    assert system.rank_seconds > 0


@pytest.mark.parametrize("scale", [1., 1e-6, 1e6])
def test_zero_noise_conditional_covariance_and_native_unit_invariance(segment_driver, tmp_path, scale):
    dense, graph = problem(scale)
    system = SegmentedLinearSystem(graph, segment_driver, tmp_path)
    value = replace(dense, linear_system=system)
    design = np.array([[1., 1., 0.], [1., 2., 0.], [0., 1., 1.]])
    expected = selected_covariance(dense, design)
    result = selected_covariance(value, design)
    assert np.linalg.norm(result-expected)/np.linalg.norm(expected) < 1e-8
    proposal(value, 1e6)
    # A preceding damped solve must not contaminate posterior covariance.
    np.testing.assert_allclose(selected_covariance(value, design), result, rtol=1e-12, atol=1e-14)


def test_graph_identity_prevents_stale_factor_reuse(tmp_path):
    dense, graph = problem()
    system = SegmentedLinearSystem(graph, tmp_path/"absent-native", tmp_path)
    changed = replace(dense, rhs=dense.rhs+1., linear_system=system)
    with pytest.raises(NumericalFailure, match="exact native linearization") as error:
        changed.validate()
    assert error.value.reason == "stale_segment_graph"


def test_future_prior_dependency_cannot_be_eliminated():
    _, graph = problem()
    bad = replace(graph, groups=(EliminationGroup(0, (0,), (1,)),
                                  EliminationGroup(1, (3,), (2, 4))))
    with pytest.raises(NumericalFailure) as error:
        bad.validate()
    assert error.value.reason == "premature_elimination"


def test_no_fallback_when_native_solver_is_unavailable(tmp_path):
    dense, graph = problem()
    point = replace(dense, linear_system=SegmentedLinearSystem(graph, tmp_path/"absent", tmp_path))
    with pytest.raises(NumericalFailure) as error:
        proposal(point)
    assert error.value.reason == "missing_segment_solver"


def test_grouped_cartesian_and_cross_queries_match_full_covariance(segment_driver,tmp_path):
    dense,graph = problem()
    system = SegmentedLinearSystem(graph,segment_driver,tmp_path)
    point = replace(dense,linear_system=system)
    first = (((3,1.),),((4,1.),))
    second = (((1,1.),(2,1.)),)
    expected = selected_covariance(dense,np.array([[1.,1.,0.],[1.,2.,0.],[0.,1.,1.]]))
    blocks = system.covariance_blocks(point,[first,second,first+second])
    np.testing.assert_allclose(blocks[0],expected[:2,:2],rtol=1e-12,atol=1e-14)
    np.testing.assert_allclose(blocks[1],expected[2:,2:],rtol=1e-12,atol=1e-14)
    np.testing.assert_allclose(blocks[2],expected,rtol=1e-12,atol=1e-14)


def test_ledger_ids_cannot_overlap_and_damping_ids_are_new():
    dense,graph = problem()
    bad = replace(graph,stochastic=(replace(graph.stochastic[0],identifier=100),*graph.stochastic[1:]))
    with pytest.raises(NumericalFailure):bad.validate()
    damped = graph.with_damping(dense,.001).validate()
    identifiers = [r.identifier for r in (*damped.equalities,*damped.stochastic)]
    assert len(identifiers) == len(set(identifiers))


@pytest.mark.parametrize("error",[None,True,-1.,float("nan"),float("inf"),2e-12,3e-12])
def test_native_success_cannot_bypass_fixed_exact_equation_residual(tmp_path,monkeypatch,error):
    _,graph=problem()
    executable=tmp_path/"recorded-native";executable.touch()
    system=SegmentedLinearSystem(graph,executable,tmp_path/"solve")
    def claimed_success(argv,**kwargs):
        json.dump({"status":"complete","equality_max_backward_error":error},kwargs["stdout"])
        return SimpleNamespace(returncode=0,stderr="")
    monkeypatch.setattr(subprocess,"run",claimed_success)
    with pytest.raises(NumericalFailure) as failed:
        system._run(graph)
    assert failed.value.reason=="constraint_residual_inconsistent"
    assert system.calls[-1]["validation_failure"]==failed.value.reason
    assert Path(system.calls[-1]["output"]).is_file()
