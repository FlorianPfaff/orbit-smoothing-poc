"""Native-export lifting against an independently assembled dense problem."""
from dataclasses import replace
import json
from pathlib import Path

import numpy as np
import pytest

from orbit_poc.numerics.optimizer import Linearization, NumericalFailure, proposal, selected_covariance
from orbit_poc.segmented.graph import build_graph, _hex_extended, recover_epoch_nuisance
from orbit_poc.segmented.solver import SegmentedLinearSystem
from test_segmented_solver import segment_driver


def exported_problem(root, *, local_forcing=False, wide_halo=False):
    """A coupled six-state operator with crossing interpolation and clocks.

    Assemble the reference directly in original coordinates and eliminate all
    clocks in one global QR, independently of the local export assembler.
    """
    rng = np.random.default_rng(61991)
    n, step, dynamic = 17, 600., 8
    retained, local = 9, n-1
    metadata = {"kind": "metadata", "schema": "orbit-poc-segmented-design-v1",
                "epochs": n, "parameter_count": dynamic, "initial_parameter_offset": 2,
                "post_pulse": True, "dt": step}
    design = [metadata]
    maps, phi = [], []
    transform = np.zeros((6, dynamic)); transform[:, 2:] = np.eye(6)
    forcing = rng.normal(size=(n, 6, 2))*1e-5
    if local_forcing:
        forcing[6:,:,0]=0.
        forcing[:6,:,1]=0.
    for k in range(n):
        p = np.eye(6); p[:3, 3:] = np.eye(3)*(k*step/9600.)
        phi.append(p)
        if k:
            transform[:, :2] += step*.5*(forcing[k-1]+forcing[k])
        maps.append(p@transform)
        design.extend([
            {"kind": "epoch", "index": k, "time": [60000, k*step/86400.], "phi": p.ravel().tolist()},
            {"kind": "forcing", "index": k, "integrand": [[i,j,float(forcing[k,i,j])] for i in range(6) for j in range(2)]}])
        if k:
            design.append({"kind": "quadrature", "interval": k-1,
                           "terms": [[k-1,step*.5,0.],[k,step*.5,0.]]})
    design.append({"kind": "complete"})
    records = [{"kind": "metadata", "schema": "orbit-poc-segmented-weighted-rows-v1",
                "total_columns": local+retained, "local_columns": local}]
    observations, full, target = [], [], []
    positions = np.array([[1.,0.,0.],[0.,1.,0.],[0.,0.,1.],[1.,1.,1.]])
    for epoch in range(n-1):
        records.append({"kind": "epoch", "index": epoch, "first": epoch, "count": 1})
        block = np.zeros((4, local+retained)); block[:,epoch] = 1.
        halo = [(epoch,.25),(epoch+1,.75)] if not wide_halo or epoch<2 else [(epoch-2,.25),(epoch,.25),(epoch+1,.5)]
        block[:,local:local+dynamic] = positions@sum(weight*maps[index][:3] for index,weight in halo)
        block[:,-1] = [1.,-1.,2.,-.5]
        row_start = len(full)
        observations.append({"kind": "observation", "factor_stem": str(root/"qr.0"),
            "native_first": local, "native_count": dynamic, "arc": 0,
            "rows": 4, "row_start": row_start, "position_design": positions.ravel().tolist(),
            "halo": [[index,weight,float(weight).hex(),float(0).hex()] for index,weight in halo]})
        for row in block:
            rhs = float(rng.normal())
            records.append({"kind": "row", "index": len(full), "epoch": epoch,
                "source": "weighted_observation", "rhs": rhs,
                "terms": [[i,float(v)] for i,v in enumerate(row) if v]})
            full.append(row); target.append(rhs)
    # Nonzero full-parameter priors, including one coupled OU-like transition.
    priors = np.eye(retained)
    priors[1,0] = -.8
    for i, prior in enumerate(priors):
        row = np.r_[np.zeros(local),prior]
        rhs = float(.1*(i+1))
        records.append({"kind": "row", "index": len(full), "epoch": None,
            "source": "global_constraint", "rhs": rhs,
            "terms": [[j,float(v)] for j,v in enumerate(row) if v]})
        full.append(row); target.append(rhs)
    full, target = np.array(full), np.array(target)
    q, _ = np.linalg.qr(full[:,:local], mode="complete")
    a, b = (q.T@full[:,local:])[local:], (q.T@target)[local:]
    scales = 1/np.linalg.norm(a, axis=0)
    q, r = np.linalg.qr(a*scales)
    point = Linearization(r,q.T@b,scales,np.r_[np.ones(dynamic,dtype=bool),False],len(b),
        .5*float(b@b),float(np.linalg.norm(b-q@(q.T@b))**2),"fixed_support",None,
        metadata={"factor_prefix": str(root/"qr.0")})
    records.append({"kind": "complete", "source_rows": len(full), "reduced_rows": len(b),
                    "group_removed_energy": .7})
    paths = [root/name for name in ("design.jsonl","rows.jsonl","observations.jsonl")]
    for path, rows in zip(paths, (design, records, observations)):
        path.write_text("".join(json.dumps(r)+"\n" for r in rows))
    return point, paths


@pytest.mark.parametrize("segment_seconds", [3600,14400])
@pytest.mark.parametrize("damping", [0.,1e-3,1e3])
def test_lifted_native_exports_preserve_clocks_priors_and_interpolation(segment_driver,tmp_path,segment_seconds,damping):
    dense, paths = exported_problem(tmp_path)
    graph, receipt = build_graph(dense,*paths,segment_seconds=segment_seconds)
    system = SegmentedLinearSystem(graph,segment_driver,tmp_path/"solves")
    segmented = replace(dense,linear_system=system).validate()
    a, b = proposal(dense,damping), proposal(segmented,damping)
    sigma = np.sqrt(np.diag(selected_covariance(dense,np.eye(9))))
    assert np.max(abs(a[0]-b[0])/sigma) < 1e-7
    selection = np.eye(9)[[0,1,2,6,8]]
    covariance = selected_covariance(dense,selection)
    actual = selected_covariance(segmented,selection)
    assert np.linalg.norm(actual-covariance)/np.linalg.norm(covariance) < 1e-8
    assert receipt["group_removed_energy"] == .7
    assert len(receipt["epoch_conditionals"]) == 16
    assert sum(r["local_columns"] for r in receipt["epoch_conditionals"]) == 16


def test_duplicate_or_stale_rows_cannot_enter_the_graph(tmp_path):
    dense, paths = exported_problem(tmp_path)
    with paths[2].open("a") as stream:
        stream.write(paths[2].read_text().splitlines()[0]+"\n")
    with pytest.raises(NumericalFailure,match="duplicated"):
        build_graph(dense,*paths,segment_seconds=3600)


def test_hex_interpolation_preserves_low_part():
    assert _hex_extended("0x1.000000000000001p+0") > np.longdouble(1)


def test_force_ownership_waits_for_deterministic_stencils_crossing_a_cut(segment_driver,tmp_path):
    dense,paths=exported_problem(tmp_path,local_forcing=True,wide_halo=True)
    layouts=[]
    expected=proposal(dense)[0]
    sigma=np.sqrt(np.diag(selected_covariance(dense,np.eye(9))))
    for seconds in (3600,14400):
        graph,_=build_graph(dense,*paths,segment_seconds=seconds)
        system=SegmentedLinearSystem(graph,segment_driver,tmp_path/str(seconds))
        value=proposal(replace(dense,linear_system=system))[0]
        assert np.max(abs(value-expected)/sigma)<1e-7
        layouts.append(graph.groups)
    assert layouts[0]!=layouts[1]


def test_local_stencil_transport_does_not_need_dense_physical_columns(tmp_path):
    dense,paths=exported_problem(tmp_path)
    reference,first=build_graph(dense,*paths,segment_seconds=3600)
    rows=[json.loads(line) for line in paths[1].read_text().splitlines()]
    local=rows[0]["local_columns"]
    rows[0]["dynamic_observation_terms"]="native_local_stencil"
    for row in rows:
        if row["kind"]!="row":continue
        physical=[term for term in row["terms"] if local<=term[0]<local+8] if row["source"]=="weighted_observation" else []
        row["omitted_dynamic_columns"]=len(physical)
        row["terms"]=[term for term in row["terms"] if term not in physical]
    paths[1].write_text("".join(json.dumps(row)+"\n" for row in rows))
    lifted,receipt=build_graph(dense,*paths,segment_seconds=3600)
    assert lifted==reference
    assert receipt["dynamic_observation_transport"]=="native_local_stencil"
    observations=paths[2].read_text().splitlines()
    paths[2].write_text("\n".join(observations[1:])+"\n")
    with pytest.raises(NumericalFailure,match="declared local physical columns"):
        build_graph(dense,*paths,segment_seconds=3600)


@pytest.mark.parametrize("offset", [300.,1800.])
@pytest.mark.parametrize("damping", [0.,1e-3,1e3])
def test_shifted_cuts_preserve_identical_physical_rows_and_posterior(segment_driver,tmp_path,offset,damping):
    dense,paths=exported_problem(tmp_path,local_forcing=True,wide_halo=True)
    nominal,_=build_graph(dense,*paths,segment_seconds=3600)
    shifted,receipt=build_graph(dense,*paths,segment_seconds=3600,segment_offset_seconds=offset)
    assert shifted.equalities==nominal.equalities
    assert shifted.stochastic==nominal.stochastic
    assert shifted.variables==nominal.variables
    assert shifted.groups!=nominal.groups
    assert receipt["segment_offset_seconds"]==offset
    system=SegmentedLinearSystem(shifted,segment_driver,tmp_path/"shifted")
    point=replace(dense,linear_system=system)
    expected=proposal(dense,damping)[0]
    actual=proposal(point,damping)[0]
    covariance=selected_covariance(dense,np.eye(9))
    assert np.max(abs(actual-expected)/np.sqrt(np.diag(covariance)))<1e-7
    assert np.linalg.norm(selected_covariance(point,np.eye(9))-covariance)/np.linalg.norm(covariance)<1e-8


@pytest.mark.parametrize("offset", [True,-1.,3600.,float("nan"),float("inf"),"300"])
def test_invalid_cut_offsets_are_rejected_before_reading_exports(offset,tmp_path):
    with pytest.raises(ValueError,match="Computational cut offset"):
        build_graph(None,tmp_path/"missing",None,None,segment_seconds=3600,
                    segment_offset_seconds=offset)


def test_clock_conditional_recovery_matches_joint_original_row_qr(segment_driver,tmp_path):
    dense,paths=exported_problem(tmp_path,local_forcing=True,wide_halo=True)
    graph,receipt=build_graph(dense,*paths,segment_seconds=3600,segment_offset_seconds=300.)
    system=SegmentedLinearSystem(graph,segment_driver,tmp_path/"recover")
    result=system._run(graph)
    values=dict(zip((v.identifier for v in graph.variables),result["step"]))
    recovered=recover_epoch_nuisance(receipt["epoch_conditionals"],values)
    records=[json.loads(line) for line in paths[1].read_text().splitlines()]
    rows=[r for r in records if r["kind"]=="row"]
    matrix=np.zeros((len(rows),records[0]["total_columns"]))
    for i,row in enumerate(rows):
        for j,v in row["terms"]:matrix[i,j]=v
    q,r=np.linalg.qr(matrix)
    expected=np.linalg.solve(r,q.T@np.array([row["rhs"] for row in rows]))
    covariance_root=np.linalg.solve(r,np.eye(len(r)))
    sigma=np.linalg.norm(covariance_root,axis=1)
    offset=receipt["temporary_nuisance_id_offset"]
    local=records[0]["local_columns"]
    actual=np.array([recovered[offset+i] for i in range(local)])
    assert np.max(abs(actual-expected[:local])/sigma[:local])<1e-7


def test_missing_or_reused_nuisance_conditionals_fail_explicitly(tmp_path):
    dense,paths=exported_problem(tmp_path)
    graph,receipt=build_graph(dense,*paths,segment_seconds=3600)
    conditionals=receipt["epoch_conditionals"]
    with pytest.raises(NumericalFailure,match="dependency is missing"):
        recover_epoch_nuisance(conditionals,{})
    zeros={v.identifier:0. for v in graph.variables}
    with pytest.raises(NumericalFailure,match="conditional identity"):
        recover_epoch_nuisance([conditionals[0],conditionals[0]],zeros)


def test_native_coordinate_identity_and_units_are_retained_and_checked(tmp_path):
    dense,paths=exported_problem(tmp_path)
    dense.metadata["diagnostics"]={}
    with pytest.raises(NumericalFailure,match="metadata is missing"):
        build_graph(dense,*paths,segment_seconds=3600)
    local=16
    rows=[f"{i}\tclock:{i}\t0\tm\t1\tdirect_native_coordinate" for i in range(local)]
    for i,scale in enumerate(dense.scales):
        rows.append(f"{local+i}\tparameter:{i}\t{int(dense.dynamic[i])}\t{'1' if i<2 else 'm'}\t{scale:.17g}\tnative_basis")
    path=Path(dense.metadata["factor_prefix"]+".parameters.tsv")
    path.write_text("index\tname\tdynamic\tunit\tscale\tcoordinate_convention\n"+"\n".join(rows)+"\n")
    graph,receipt=build_graph(dense,*paths,segment_seconds=3600)
    assert graph.variables[0].name=="parameter:0" and graph.variables[0].unit=="1"
    assert graph.variables[2].unit=="m" and graph.variables[9].unit=="m"
    assert receipt["original_coordinate_metadata"]==str(path)
    path.write_text(path.read_text().replace("parameter:0\t1", "parameter:0\t0"))
    with pytest.raises(NumericalFailure,match="dynamic identity changed"):
        build_graph(dense,*paths,segment_seconds=3600)

