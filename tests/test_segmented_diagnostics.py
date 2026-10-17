"""Native query identity and separate position/velocity conditional maps."""
from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest

from orbit_poc.numerics.optimizer import NumericalFailure
from orbit_poc.segmented.diagnostics import physical_queries


def fixture(tmp_path):
    phi = [np.eye(6),np.diag([2.,3.,4.,5.,6.,7.])]
    times = [[60000,0.],[60000,.5]]
    design = [{"kind":"metadata","schema":"orbit-poc-segmented-design-v1",
               "epochs":2,"parameter_count":6,"initial_parameter_offset":0,"post_pulse":True}]
    design += [{"kind":"epoch","index":i,"time":times[i],"phi":value.ravel().tolist()}
               for i,value in enumerate(phi)]
    design.append({"kind":"complete"})
    weight = lambda i,w:[i,w,float(w).hex(),float(0).hex()]
    state = lambda kind,i,t,p,v:{"kind":"state","set":kind,"receiver":2,"arc":0,
        "index":i,"native_first":5,"native_count":6,"time":t,
        "position_halo":p,"velocity_halo":v}
    rows = [{"kind":"metadata","schema":"orbit-poc-segmented-covariance-queries-v1",
        "factor_stem":"fresh/factor","coordinates":"Cartesian_SI",
        "row_order":"position_xyz_velocity_xyz","post_pulse_velocity":True,"covariance_produced":False}]
    rows += [state("trajectory",i,t,[weight(i,1.)],[weight(i,1.)]) for i,t in enumerate(times)]
    rows.append(state("nominal_observation",0,[60000,.25],
                      [weight(0,.25),weight(1,.75)],[weight(0,.75),weight(1,.25)]))
    rows.append({"kind":"complete","trajectory_count":2,"nominal_observation_count":1})
    point = SimpleNamespace(scales=np.ones(8),dynamic=np.array([False,False]+[True]*6),
        metadata={"factor_prefix":"fresh/factor","diagnostics":{"local_parameters":3}})
    paths = [tmp_path/"design.jsonl",tmp_path/"queries.jsonl"]
    return point,design,rows,paths


def evaluate(point,design,rows,paths):
    for path,values in zip(paths,(design,rows)):
        path.write_text("".join(json.dumps(row)+"\n" for row in values))
    return physical_queries(point,*paths)


def test_query_covariance_map_preserves_distinct_native_position_velocity_stencils(tmp_path):
    point,design,rows,paths = fixture(tmp_path)
    groups = evaluate(point,design,rows,paths)
    queries = groups["nominal_observation"][0][1]
    mapped = np.zeros((6,12))
    for i,row in enumerate(queries):
        for variable,value in row:
            mapped[i,variable-8] = value
    expected = np.zeros((6,12))
    expected[:3,:3] = .25*np.eye(3)
    expected[:3,6:9] = .75*np.diag([2.,3.,4.])
    expected[3:,3:6] = .75*np.eye(3)
    expected[3:,9:] = .25*np.diag([5.,6.,7.])
    np.testing.assert_array_equal(mapped,expected)
    # Full cross-position/velocity covariance is retained by the six-row query.
    rng = np.random.default_rng(7141)
    a = rng.normal(size=(12,12));covariance = a@a.T
    np.testing.assert_allclose(mapped@covariance@mapped.T,expected@covariance@expected.T)


@pytest.mark.parametrize("location,key,value",[
    (0,"schema","wrong"),(0,"factor_stem","old/factor"),(0,"coordinates","RTN"),
    (0,"row_order","velocity_first"),(0,"post_pulse_velocity",False),(0,"covariance_produced",True),
    (1,"native_first",4),(1,"native_count",7),(2,"receiver",3),(2,"arc",1),
    (2,"index",0),(2,"time",[60000,.4]),(3,"index",1),(3,"time",[60000,1.]),
    (-1,"trajectory_count",3),(-1,"nominal_observation_count",2),
])
def test_query_identity_or_support_changes_fail_closed(tmp_path,location,key,value):
    point,design,rows,paths = fixture(tmp_path)
    rows[location][key] = value
    with pytest.raises(NumericalFailure):
        evaluate(point,design,rows,paths)


@pytest.mark.parametrize("change",["missing_grid","empty_halo","repeated_node","wrong_grid_node",
    "grid_interpolation","changed_weight","wrong_parameter_order","missing_local_map","wrong_design_count"])
def test_query_missing_or_inconsistent_native_dependencies_are_rejected(tmp_path,change):
    point,design,rows,paths = fixture(tmp_path)
    if change == "missing_grid":
        del rows[2]
    elif change == "empty_halo":
        rows[3]["velocity_halo"] = []
    elif change == "repeated_node":
        rows[3]["position_halo"].append(deepcopy(rows[3]["position_halo"][0]))
    elif change == "wrong_grid_node":
        rows[1]["position_halo"][0][0] = 1
    elif change == "grid_interpolation":
        rows[1]["position_halo"] = deepcopy(rows[3]["position_halo"])
    elif change == "changed_weight":
        rows[3]["position_halo"][0][1] = .5
    elif change == "wrong_parameter_order":
        point.dynamic = np.array([True,False,True,True,True,True,True,False])
    elif change == "missing_local_map":
        del point.metadata["diagnostics"]["local_parameters"]
    elif change == "wrong_design_count":
        design[0]["parameter_count"] = 7
    with pytest.raises(NumericalFailure):
        evaluate(point,design,rows,paths)
