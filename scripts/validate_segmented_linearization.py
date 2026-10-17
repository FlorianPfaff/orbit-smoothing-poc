#!/usr/bin/env python3
"""Compare dense and constrained segment QR on one actual blind native point.

This is a bounded engineering gate, not a fitted trajectory or benchmark result.
The native chronological trajectory and GNSS rows are evaluated exactly once;
both cut schedules, all damping trials and covariance use that same export.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import importlib.util
from pathlib import Path
import traceback

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.protocol import artifact_record,file_hash,read_json,source_snapshot,write_json
from orbit_poc.numerics.optimizer import certify_rank,proposal,selected_covariance
from orbit_poc.segmented.backend import V4Model
from orbit_poc.segmented.graph import build_graph
from orbit_poc.segmented.solver import SegmentedLinearSystem,linearization_digest

MAX_ORIGINAL_COLUMNS = 200
DAMPING = (0.,1e-3,1e3)
MAP_TOLERANCE = 1e-7
COVARIANCE_TOLERANCE = 1e-8
RESIDUAL_TOLERANCE = 2e-12
MAX_ORACLE_VARIABLES = 10000
MAX_ORACLE_ROWS = 100000


def require(ok,message):
    if not ok:
        raise AssertionError(message)


def blind_request(request,binary,solver,snapshot):
    """Preserve the old blind statistical request; change only execution identity."""
    from copy import deepcopy
    value = deepcopy(request)
    if (value.get("kind") != "fit" or value.get("split") != "engineering"
            or value.get("stage") != "synthetic" or value.get("numerics_profile") != "qr_lm_staged_jacobian"
            or value.get("method") not in ("groops_pulses","groops_log_drag_ou")
            or any(k in value for k in ("evaluation_inputs","calibration_inputs","truth","reference_orbit"))):
        raise ValueError("A preserved blind synthetic staged-derivative engineering fit request is required")
    value["preparation_source_hash"] = value["source_hash"]
    value["source_hash"] = snapshot["sha256"]
    value["backend"]["groops_executable"] = str(Path(binary).resolve())
    value["backend"]["segmented_solver"] = {"path":str(Path(solver).resolve()),"sha256":file_hash(solver)}
    value["expected_native_binary_sha256"] = file_hash(binary)
    value["segmented_profile"] = "segmented_1h"
    return value


def original_weighted_rows(graph):
    """Substitute the bounded native equality chain before any segment QR.

    This small-oracle path does not use the native QR factor or any segment
    conditionals. It reconstructs original-coordinate weighted rows from the
    exact equality and observation/prior ledgers. Epoch clocks have already
    been projected out by the same explicitly recorded local QR as the gate.
    """
    graph.validate()
    n = len(graph.retained_ids);count = len(graph.variables)
    require(n <= MAX_ORIGINAL_COLUMNS and count <= MAX_ORACLE_VARIABLES
            and len(graph.stochastic) <= MAX_ORACLE_ROWS,"Actual-row oracle exceeds its bounded small problem")
    transform = np.zeros((count,n),dtype=np.longdouble)
    known = np.zeros(count,dtype=bool)
    for j,identifier in enumerate(graph.retained_ids):
        transform[identifier,j] = 1.;known[identifier] = True
    maximum_residual = 0.
    for row in graph.equalities:
        require(row.rhs == 0.,"Closed native tangent equalities must be homogeneous")
        unresolved = [(i,v) for i,v in row.terms if v != 0 and not known[i]]
        require(len(unresolved) == 1,"Oracle requires the actual causal six-state variation recurrence")
        identifier,pivot = unresolved[0]
        total = sum((np.longdouble(v)*transform[i] for i,v in row.terms if i != identifier),np.zeros(n,dtype=np.longdouble))
        transform[identifier] = -total/np.longdouble(pivot);known[identifier] = True
        residual = sum((np.longdouble(v)*transform[i] for i,v in row.terms),np.zeros(n,dtype=np.longdouble))
        scale = sum((abs(np.longdouble(v))*abs(transform[i]) for i,v in row.terms),np.zeros(n,dtype=np.longdouble))
        maximum_residual = max(maximum_residual,float(np.max(abs(residual)/np.maximum(1.,scale))))
    require(known.all(),"Original-row oracle has unresolved native auxiliary coordinates")
    require(maximum_residual < RESIDUAL_TOLERANCE,"Original-row substitution failed its true equality residual")
    a = np.empty((len(graph.stochastic),n));b = np.empty(len(graph.stochastic))
    for i,row in enumerate(graph.stochastic):
        a[i] = sum((np.longdouble(v)*transform[j] for j,v in row.terms),np.zeros(n,dtype=np.longdouble))
        b[i] = row.rhs
    require(np.isfinite(a).all() and np.isfinite(b).all(),"Nonfinite original-row oracle inputs")
    return a,b,maximum_residual


def gtsam_original_row_oracle(point,graph,covariance,output):
    """Independent GTSAM4.2 QR on the actual retained weighted linearization."""
    import importlib.metadata
    import gtsam
    from scipy.linalg import solve_triangular
    require(importlib.metadata.version("gtsam") == "4.2","The independent oracle is pinned to GTSAM4.2")
    a,b,equality_residual = original_weighted_rows(graph)
    scaled = a*point.scales
    factor = gtsam.JacobianFactor(0,scaled,b,gtsam.noiseModel.Unit.Create(len(b)))
    ordering = gtsam.Ordering();ordering.push_back(0)
    # In pinned GTSAM4.2 this exact API calls EliminateQR directly. The graph's
    # default eliminateSequential API may choose Cholesky for unconstrained rows.
    # https://github.com/borglab/gtsam/blob/4.2/gtsam/linear/JacobianFactor.cpp#L706-L712
    conditional,_remainder = factor.eliminate(ordering)
    r,d = np.asarray(conditional.R()),np.asarray(conditional.d())
    n = len(point.scales)
    noise = conditional.get_model()
    # GTSAM represents an already whitened unit-noise conditional by nullptr.
    sigmas = np.ones(n) if noise is None else np.asarray(noise.sigmas())
    require(r.shape == (n,n) and d.shape == (n,) and sigmas.shape == (n,)
            and np.isfinite(r).all() and np.isfinite(d).all() and np.all(sigmas > 0),"Invalid independent GTSAM conditional")
    step = point.scales*solve_triangular(r,d)
    square_root = point.scales[:,None]*solve_triangular(r,np.diag(sigmas))
    actual_covariance = square_root@square_root.T
    reference = proposal(replace(point,linear_system=None),0.)[0]
    posterior_sd = np.sqrt(np.diag(covariance))
    map_error = float(np.max(abs(step-reference)/posterior_sd))
    covariance_error = float(np.linalg.norm(actual_covariance-covariance)/np.linalg.norm(covariance))
    expected_energy = float(np.linalg.norm(point.rhs-point.factor@(reference/point.scales))**2+point.residual_energy)
    energy = float(np.linalg.norm(b-a@step)**2)
    energy_error = abs(energy-expected_energy)/max(1.,abs(expected_energy))
    path = Path(output)/"gtsam-original-rows.npz"
    np.savez_compressed(path,weighted_design=a,weighted_target=b,column_scales=point.scales,
                        step=step,covariance=actual_covariance)
    receipt = {"version":"4.2","elimination_api":"JacobianFactor.eliminate(Ordering) -> EliminateQR","scope":"Actual original weighted observation/prior rows after native-compatible epoch nuisance projection and causal deterministic substitution; no input from native R or segment conditionals",
        "rows":len(b),"columns":n,"maximum_equality_substitution_residual":equality_residual,
        "maximum_map_discrepancy_posterior_sd":map_error,"covariance_relative_error":covariance_error,
        "full_residual_energy":energy,"normalized_residual_energy_difference":energy_error,
        "original_rows_and_result":artifact_record("gtsam_original_weighted_rows",path)}
    write_json(Path(output)/"gtsam-original-row-validation.json",receipt)
    require(map_error < MAP_TOLERANCE,"Actual-row GTSAM MAP differs by at least1e-7 posterior standard deviations")
    require(covariance_error < COVARIANCE_TOLERANCE,"Actual-row GTSAM covariance differs by at least1e-8 relative error")
    require(energy_error < RESIDUAL_TOLERANCE,"Actual-row GTSAM full residual energy differs")
    return receipt


def compare_linearization(point,paths,solver,output,*,deadline=None):
    """Gate the captured rows without another physical or nuisance evaluation."""
    output = Path(output);output.mkdir(parents=True,exist_ok=True)
    dense = replace(point,linear_system=None).validate()
    n = len(dense.scales)
    require(n <= MAX_ORIGINAL_COLUMNS,"Bounded gate refuses more than 200 original retained columns")
    rank = certify_rank(dense)
    covariance = selected_covariance(dense,np.eye(n))
    posterior_sd = np.sqrt(np.diag(covariance))
    require(np.isfinite(posterior_sd).all() and np.all(posterior_sd > 0),"Invalid original-chart posterior scales")
    np.savez_compressed(output/"dense-reference.npz",covariance=covariance,posterior_sd=posterior_sd,
                        factor=dense.factor,rhs=dense.rhs,scales=dense.scales,dynamic=dense.dynamic)
    result = {"original_columns":n,"rank":rank,"linearization_sha256":linearization_digest(dense),
        "support_hash":dense.support_hash,"effective_rows":dense.effective_rows,
        "dense_orthogonal_residual_energy":dense.residual_energy,"profiles":[],
        "dense_reference":artifact_record("identical_dense_reference",output/"dense-reference.npz"),
        "residual_energy_scope":"Full linear least-squares residual including orthogonal constant; eliminated nuisance conditional targets are fitted, not extra penalties."}
    for seconds in (3600,14400):
        folder = output/f"segments-{seconds}";folder.mkdir()
        graph,receipt = build_graph(dense,*paths,segment_seconds=seconds)
        write_json(folder/"graph.json",receipt)
        system = SegmentedLinearSystem(graph,solver,folder/"solves",deadline=deadline)
        segmented = replace(dense,linear_system=system).validate()
        profile = {"segment_seconds":seconds,"graph":artifact_record("segmented_graph",folder/"graph.json"),
                   "trials":[],"calls":system.calls}
        result["profiles"].append(profile)
        for damping in DAMPING:
            expected,expected_prediction,expected_gradient = proposal(dense,damping)
            actual,prediction,gradient = proposal(segmented,damping)
            error = float(np.max(np.abs(actual-expected)/posterior_sd))
            z = expected/dense.scales
            dense_energy = float(np.linalg.norm(dense.rhs-dense.factor@z)**2+dense.residual_energy
                                 + damping*np.linalg.norm(z[dense.dynamic])**2)
            payload = read_json(system.calls[-1]["output"])
            equality_error = payload["equality_max_backward_error"]
            residual_difference = abs(payload["residual_energy"]-dense_energy)/max(1.,abs(dense_energy))
            orthogonal_difference = abs(payload["orthogonal_residual_energy"]-dense_energy)/max(1.,abs(dense_energy))
            trial = {"damping":damping,"maximum_map_discrepancy_posterior_sd":error,
                "dense_residual_energy":dense_energy,"segmented_residual_energy":payload["residual_energy"],
                "segmented_orthogonal_residual_energy":payload["orthogonal_residual_energy"],
                "normalized_residual_energy_difference":residual_difference,
                "normalized_orthogonal_residual_energy_difference":orthogonal_difference,
                "maximum_equality_backward_error":equality_error,
                "equality_residual_normalization":"max_i |d_i-E_i*x| / (|d_i|+sum_j |E_ij*x_j|); zero denominator gives zero",
                "dense_predicted_reduction":expected_prediction,"segmented_predicted_reduction":prediction,
                "dense_scaled_gradient":expected_gradient,"segmented_scaled_gradient":gradient,
                "native_result":artifact_record("constrained_qr_result",system.calls[-1]["output"])}
            profile["trials"].append(trial)
            write_json(output/"comparison-progress.json",result)
            require(error < MAP_TOLERANCE,"Segmented MAP differs by at least 1e-7 posterior standard deviations")
            require(max(residual_difference,orthogonal_difference) < RESIDUAL_TOLERANCE,
                    "Full residual energy differs from the identical dense linearization")
            require(np.isfinite(equality_error) and 0 <= equality_error < RESIDUAL_TOLERANCE,
                    "Recovered native solution violates the fixed2e-12 exact-equality residual gate")
            require(gradient == expected_gradient,"Original scaled-gradient definition changed")
        actual_covariance = selected_covariance(segmented,np.eye(n))
        relative = float(np.linalg.norm(actual_covariance-covariance)/np.linalg.norm(covariance))
        normalized = float(np.linalg.norm((actual_covariance-covariance)/posterior_sd[:,None]/posterior_sd[None,:]))
        profile.update(covariance_relative_error=relative,covariance_posterior_normalized_error=normalized,
                       covariance_optimization_damping=0.,covariance_all_original_coordinates=True)
        np.savez_compressed(folder/"covariance.npz",covariance=actual_covariance)
        profile["covariance"] = artifact_record("segmented_original_covariance",folder/"covariance.npz")
        write_json(output/"comparison-progress.json",result)
        require(relative < COVARIANCE_TOLERANCE,"Segmented covariance differs by at least 1e-8 relative Frobenius error")
    result["independent_gtsam"] = gtsam_original_row_oracle(dense,graph,covariance,output)
    write_json(output/"comparison-progress.json",result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request",type=Path,required=True)
    parser.add_argument("--binary",type=Path,required=True)
    parser.add_argument("--solver",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--initial-state-from",type=Path)
    args = parser.parse_args(argv)
    if args.output.is_symlink() or args.output.exists() and any(args.output.iterdir()):
        raise ValueError("Choose a fresh output directory; all prior gate evidence is preserved")
    args.output.mkdir(parents=True,exist_ok=True)
    receipt = {"schema":"orbit-poc-segmented-linearization-gate-v1","passed":False,
        "scope":"One blind native engineering linearization; no accepted fit covariance or release approval",
        "accepted_fit_covariance":False,"physical_evaluations":0,"maximum_original_columns":MAX_ORIGINAL_COLUMNS,
        "map_tolerance_posterior_sd":MAP_TOLERANCE,"relative_covariance_tolerance":COVARIANCE_TOLERANCE,
        "normalized_residual_energy_tolerance":RESIDUAL_TOLERANCE,
        "preserved_failures":True,"damping_values":list(DAMPING)}
    model = None
    try:
        snapshot = source_snapshot()
        request = blind_request(read_json(args.request),args.binary,args.solver,snapshot)
        write_json(args.output/"request.json",request);write_json(args.output/"source.json",snapshot)
        receipt.update(original_request=artifact_record("original_blind_engineering_request",args.request),
                       request=artifact_record("derived_engineering_request",args.output/"request.json"),
                       source=artifact_record("source_snapshot",args.output/"source.json"),
                       source_sha256=snapshot["sha256"],native=artifact_record("native_binary",args.binary),
                       solver=artifact_record("segmented_qr_binary",args.solver))
        model = V4Model(request,args.output)
        initial = model.initial_state()
        if args.initial_state_from is not None:
            values = native.read_native_table(args.initial_state_from).ravel()
            require(values.shape == (6,) and np.isfinite(values).all(),"Finite six-component preserved blind initial state required")
            initial = replace(initial,initial=values)
            receipt["initial_state_input"] = artifact_record("preserved_blind_initial_state",args.initial_state_from)
        amplitude = .2*(request["parameters"]["sigma_log_density"] if model.density
                        else 1e6*request["parameters"]["sigma_velocity_m_s"])
        force = amplitude*np.cos(.37*np.arange(len(initial.force)))
        point = model.evaluate(replace(initial,force=force),"identical-linearization",tighter=True)
        receipt["physical_evaluations"] = 1
        require(point.metadata["nuisance_floor_limited"] is False,"This small gate requires strict native nuisance stationarity")
        helper = Path(__file__).with_name("validate_numerics_objective.py")
        spec = importlib.util.spec_from_file_location("unchanged_full_prior_check",helper)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        receipt["prior_check_source"] = artifact_record("unchanged_native_prior_check",helper)
        receipt["prior"] = module.prior_check(point,model)
        base = point.metadata["factor_prefix"]
        paths = [Path(point.metadata["segmented_design"]),Path(base+".segmented_rows.jsonl"),Path(base+".segmented_observations.jsonl")]
        receipt["captured_exports"] = [artifact_record(role,path) for role,path in zip(
            ("native_variation_design","native_weighted_rows","native_local_observation_design"),paths)]
        receipt["native_evidence"] = [artifact_record(role,path) for role,path in (
            ("nuisance_profile",Path(point.metadata["folder"])/"qr.profile.json"),
            ("closure",Path(point.metadata["folder"])/"closure.json"),
            ("native_factor",base+".factor.json"),("native_rank",base+".diagnostics.json"))]
        receipt["comparison"] = compare_linearization(point,paths,args.solver,args.output/"comparison",
            deadline=model.start+model.controls.wall_time_seconds)
        receipt["cut_scope"] = "One-hour preserved fixtures may have no interior computational cut; differing-cut long arcs remain required benchmark evidence."
        receipt["passed"] = True
    except Exception as error:
        receipt.update(error=f"{type(error).__name__}: {error}",traceback=traceback.format_exc())
    if model is not None:
        receipt.update(native_executions=model.executions,propagation_count=model.propagations)
    write_json(args.output/"validation.json",receipt)
    print({k:receipt[k] for k in ("passed","error") if k in receipt},flush=True)
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
