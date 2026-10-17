"""Bounded native gate orchestration and identical-row arithmetic fixtures."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path

import numpy as np
import pytest

from orbit_poc.comparison.protocol import read_json,write_json
from test_segmented_graph import exported_problem
from test_segmented_solver import segment_driver


@pytest.fixture
def gate():
    path = Path(__file__).resolve().parents[1]/"scripts/validate_segmented_linearization.py"
    spec = importlib.util.spec_from_file_location("segmented_linearization_gate",path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def request():
    return {"kind":"fit","stage":"synthetic","split":"engineering",
        "numerics_profile":"qr_lm_staged_jacobian","method":"groops_pulses",
        "source_hash":"old_preparation","backend":{"groops_executable":"old_native"},
        "estimation_inputs":[{"role":"gnss_observations","path":"retained","sha256":"abc"}],
        "parameters":{"interval_seconds":1200.,"sigma_velocity_m_s":1e-4}}


def executables(tmp_path):
    binary,solver=tmp_path/"native",tmp_path/"solver"
    binary.write_bytes(b"native");solver.write_bytes(b"solver")
    return binary,solver


def test_derived_request_preserves_frozen_statistical_inputs(gate,tmp_path):
    binary,solver=executables(tmp_path)
    original=request();snapshot=deepcopy(original)
    updated=gate.blind_request(original,binary,solver,{"sha256":"current_source"})
    assert original==snapshot
    assert updated["preparation_source_hash"]=="old_preparation"
    assert updated["source_hash"]=="current_source" and updated["segmented_profile"]=="segmented_1h"
    assert updated["parameters"]==original["parameters"]
    assert updated["estimation_inputs"]==original["estimation_inputs"]
    assert updated["expected_native_binary_sha256"]==gate.file_hash(binary)
    assert updated["backend"]["segmented_solver"]["sha256"]==gate.file_hash(solver)


@pytest.mark.parametrize("key,value",[("stage","flight"),("split","evaluation"),
    ("kind","prediction"),("numerics_profile","legacy_v3"),("method","other"),
    ("truth","hidden"),("reference_orbit","GNV"),("evaluation_inputs",[])])
def test_gate_rejects_nonblind_or_wrong_profile_request(gate,tmp_path,key,value):
    binary,solver=executables(tmp_path);original=request();original[key]=value
    with pytest.raises(ValueError,match="blind"):
        gate.blind_request(original,binary,solver,{"sha256":"new"})


def test_identical_rows_all_chart_covariance_full_energy_and_dynamic_damping(gate,tmp_path,segment_driver):
    point,paths=exported_problem(tmp_path)
    result=gate.compare_linearization(point,paths,segment_driver,tmp_path/"comparison")
    assert result["original_columns"]==9 and result["dense_orthogonal_residual_energy"]>0
    assert result["independent_gtsam"]["version"]=="4.2"
    assert result["independent_gtsam"]["maximum_map_discrepancy_posterior_sd"]<1e-7
    assert result["independent_gtsam"]["covariance_relative_error"]<1e-8
    assert [x["segment_seconds"] for x in result["profiles"]]==[3600,14400]
    for profile in result["profiles"]:
        assert [x["damping"] for x in profile["trials"]]==[0.,.001,1000.]
        assert profile["covariance_relative_error"]<1e-8
        assert profile["covariance_optimization_damping"]==0.
        assert all(x["maximum_map_discrepancy_posterior_sd"]<1e-7 for x in profile["trials"])
        assert all(x["normalized_residual_energy_difference"]<2e-12 for x in profile["trials"])
        assert all(x["normalized_orthogonal_residual_energy_difference"]<2e-12 for x in profile["trials"])
        assert all(x["maximum_equality_backward_error"]<2e-12 for x in profile["trials"])
        assert len(profile["calls"])==4


def test_wrong_dense_certificate_is_detected_and_progress_preserved(gate,tmp_path,segment_driver):
    point,paths=exported_problem(tmp_path)
    changed=replace(point,rhs=point.rhs+0.1)
    with pytest.raises(AssertionError,match="MAP"):
        gate.compare_linearization(changed,paths,segment_driver,tmp_path/"comparison")
    progress=read_json(tmp_path/"comparison/comparison-progress.json")
    assert progress["profiles"][0]["trials"][0]["maximum_map_discrepancy_posterior_sd"]>=1e-7


def test_dense_gate_bound_precedes_any_solver_run(gate,tmp_path,monkeypatch):
    point,paths=exported_problem(tmp_path)
    monkeypatch.setattr(gate,"MAX_ORIGINAL_COLUMNS",8)
    with pytest.raises(AssertionError,match="200"):
        gate.compare_linearization(point,paths,tmp_path/"missing",tmp_path/"comparison")
    assert not list((tmp_path/"comparison").rglob("*.rows"))


def test_native_failure_retains_request_source_and_failed_validation(gate,tmp_path,monkeypatch):
    binary,solver=executables(tmp_path);inputfile=tmp_path/"original.json";write_json(inputfile,request())
    monkeypatch.setattr(gate,"source_snapshot",lambda:{"sha256":"source","files":{}})
    class FailedModel:
        def __init__(self,job,root):
            self.executions=[{"returncode":1,"status":"failed"}];self.propagations=0
        def initial_state(self):raise RuntimeError("preserved native failure")
    monkeypatch.setattr(gate,"V4Model",FailedModel)
    output=tmp_path/"failed"
    assert gate.main(["--request",str(inputfile),"--binary",str(binary),"--solver",str(solver),"--output",str(output)])==1
    result=read_json(output/"validation.json")
    assert result["passed"] is False and result["physical_evaluations"]==0
    assert "preserved native failure" in result["error"]
    assert result["native_executions"][0]["returncode"]==1
    assert read_json(inputfile)==request()
    before=(output/"validation.json").read_bytes()
    with pytest.raises(ValueError,match="fresh"):
        gate.main(["--request",str(inputfile),"--binary",str(binary),"--solver",str(solver),"--output",str(output)])
    assert (output/"validation.json").read_bytes()==before


def test_original_weighted_row_substitution_matches_dense_before_gtsam(gate,tmp_path):
    from orbit_poc.segmented.graph import build_graph
    point,paths=exported_problem(tmp_path)
    graph,_=build_graph(point,*paths,segment_seconds=3600)
    a,b,error=gate.original_weighted_rows(graph)
    assert a.shape==(point.effective_rows,len(point.scales)) and error<2e-12
    rng=np.random.default_rng(10614)
    # Compare the complete quadratic at independent nonzero original states,
    # including the saved native orthogonal energy and nonzero prior targets.
    for _ in range(5):
        x=rng.normal(size=len(point.scales))*point.scales
        expected=np.linalg.norm(point.rhs-point.factor@(x/point.scales))**2+point.residual_energy
        assert np.linalg.norm(b-a@x)**2==pytest.approx(expected,rel=2e-12,abs=2e-12)


def test_oracle_fails_closed_on_missing_causal_dependency(gate,tmp_path):
    from orbit_poc.segmented.graph import build_graph
    point,paths=exported_problem(tmp_path)
    graph,_=build_graph(point,*paths,segment_seconds=3600)
    reordered=replace(graph,equalities=tuple(reversed(graph.equalities)))
    with pytest.raises(AssertionError,match="causal"):
        gate.original_weighted_rows(reordered)


def test_gtsam_receipt_preserves_actual_row_failure(gate,tmp_path):
    from orbit_poc.segmented.graph import build_graph
    from orbit_poc.numerics.optimizer import selected_covariance
    point,paths=exported_problem(tmp_path)
    graph,_=build_graph(point,*paths,segment_seconds=3600)
    covariance=selected_covariance(point,np.eye(len(point.scales)))
    changed=replace(point,rhs=point.rhs+.1)
    with pytest.raises(AssertionError,match="GTSAM MAP"):
        gate.gtsam_original_row_oracle(changed,graph,covariance,tmp_path)
    receipt=read_json(tmp_path/"gtsam-original-row-validation.json")
    assert receipt["maximum_map_discrepancy_posterior_sd"]>=1e-7
    assert Path(receipt["original_rows_and_result"]["path"]).is_file()


def test_exact_constraint_error_is_a_separate_gate_from_energy(gate,tmp_path,segment_driver,monkeypatch):
    point,paths=exported_problem(tmp_path)
    original_read=gate.read_json
    def inconsistent(path):
        value=original_read(path)
        if "equality_max_backward_error" in value:
            value["equality_max_backward_error"]=2e-12
        return value
    monkeypatch.setattr(gate,"read_json",inconsistent)
    with pytest.raises(AssertionError,match="exact-equality residual"):
        gate.compare_linearization(point,paths,segment_driver,tmp_path/"comparison")
    trial=original_read(tmp_path/"comparison/comparison-progress.json")["profiles"][0]["trials"][0]
    assert trial["normalized_residual_energy_difference"]<2e-12
    assert trial["maximum_equality_backward_error"]==2e-12
