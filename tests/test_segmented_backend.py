"""The v4 integration keeps the corrected objective/compatibility contract."""
from pathlib import Path
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.numerics.backend import NativeModel
from orbit_poc.segmented.backend import V4Model,fit_job,TimedDenseSystem
from orbit_poc.segmented.diagnostics import covariance_pairs,selected_original_design
from test_segmented_graph import exported_problem


@pytest.mark.parametrize("profile",[None,"unknown","legacy_v3","segmented_2h"])
def test_backend_requires_an_explicit_supported_profile(tmp_path,profile):
    with pytest.raises(ValueError,match="registered"):
        fit_job({"segmented_profile":profile},tmp_path)
    assert not list(tmp_path.iterdir())


def test_segmented_profile_uses_native_queries_without_dense_covariance(monkeypatch,tmp_path):
    model = object.__new__(V4Model);model.segmented=True
    captured=[]
    monkeypatch.setattr(NativeModel,"execute",lambda self,*args:captured.append(args))
    tree = ET.fromstring("""<groops><program><GnssProcessing><parametrization><leoDynamicOrbits>
        <outputfileCovariance>a</outputfileCovariance><outputfileParameterCovariance>b</outputfileParameterCovariance>
        <outputfileCovarianceObservationEpochs>c</outputfileCovarianceObservationEpochs>
        <outputfileOrbit>orbit</outputfileOrbit></leoDynamicOrbits></parametrization>
        <processingStep><computeCovarianceMatrix/></processingStep>
        <processingStep><writeResults/></processingStep></GnssProcessing></program></groops>""")
    model.execute(tree,tmp_path,"profile",{"ORBIT_POC_NUMERICS_MODE":"profile_step"})
    tree,_,_,env=captured[0]
    assert tree.find(".//computeCovarianceMatrix") is None
    assert tree.find(".//outputfileCovariance") is None
    assert tree.find(".//outputfileOrbit").text=="orbit"
    assert tree.find(".//writeResults") is not None
    assert env=={"ORBIT_POC_NUMERICS_MODE":"profile_step","ORBIT_POC_SEGMENTED_ROWS":"1",
                "ORBIT_POC_SEGMENTED_COVARIANCE_QUERIES":"1"}


def test_dense_execution_tree_and_environment_are_unchanged(monkeypatch,tmp_path):
    model=object.__new__(V4Model);model.segmented=False
    tree=ET.fromstring("<groops><computeCovarianceMatrix/></groops>");environment={"test":"value"}
    monkeypatch.setattr(NativeModel,"execute",lambda self,*args:args)
    actual=model.execute(tree,tmp_path,"profile",environment)
    assert actual==(tree,tmp_path,"profile",environment)
    assert actual[0] is tree and actual[3] is environment


def test_postfit_dense_map_uses_same_export_without_whole_arc_dense_storage(tmp_path):
    dense,paths=exported_problem(tmp_path)
    maps=selected_original_design(paths[0],[0,5,16])
    assert set(maps)=={0,5,16}
    np.testing.assert_array_equal(maps[0][:,2:],np.eye(6))
    np.testing.assert_array_equal(maps[0][:,:2],np.zeros((6,2)))
    # Independent direct forcing prefix sum and physical STM.
    import json
    records=[json.loads(line) for line in paths[0].read_text().splitlines()]
    forcing={r["index"]:r["integrand"] for r in records if r["kind"]=="forcing"}
    expected=np.zeros((6,8));expected[:,2:]=np.eye(6)
    for i in range(16):
        for k in (i,i+1):
            for component,column,value in forcing[k]:expected[component,column]+=300.*value
    phi=np.eye(6);phi[:3,3:]=np.eye(3)
    np.testing.assert_allclose(maps[16],phi@expected,rtol=2e-15,atol=1e-16)


def test_cross_covariance_pairs_do_not_depend_on_segment_layout():
    mjd=60000+np.arange(0,24*3600+1,30)/86400
    pairs=covariance_pairs(mjd)
    assert pairs==[(0,2880),(120,240),(480,960)]


def test_dense_adapter_preserves_exact_arithmetic_and_counts_cost():
    from test_segmented_solver import problem
    from orbit_poc.numerics.optimizer import proposal,certify_rank
    point,_=problem();system=TimedDenseSystem()
    for damping in (0.,.001,1e5):
        actual=system.proposal(point,damping);expected=proposal(point,damping)
        np.testing.assert_array_equal(actual[0],expected[0]);assert actual[1:]==expected[1:]
    assert system.certify_rank(point)==certify_rank(point)
    assert system.metrics["rank_calls"]==1 and system.metrics["proposal_calls"]==3
