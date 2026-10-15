"""Tiny fabricated receipts test the independent audit, without native work."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location("correctness_audit", Path(__file__).with_name("verify_correctness_results_07.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
NATIVE = "a"*64


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def profile(strict=True):
    history = [{"maximum_update_m": 1e-10 if strict else 1e-5,
                "gradient_scaled": 1e-12, "predicted_reduction": 1e-12} for _ in range(2 if strict else 1)]
    return {"nuisance_converged": strict, "nuisance_floor_limited": not strict,
            "nuisance_objective_resolution": 0., "nuisance_predicted_reduction": 1e-12,
            "nuisance_gradient_scaled": 1e-12, "fixed_weights": True, "dynamic_updates": False,
            "threshold_m": 1e-8, "required_consecutive_small_updates": 2,
            "iterations": len(history), "history": history, "maximum_update_m": history[-1]["maximum_update_m"]}


def validator(value):
    # Production invokes the real backend validator; these independent unit
    # checks isolate the arithmetic audit from package imports.
    if value["nuisance_converged"] and not value["nuisance_floor_limited"]:
        return 0., False
    if value["nuisance_floor_limited"] and not value["nuisance_converged"]:
        return value["nuisance_objective_resolution"], True
    raise ValueError("Invalid profile flags")


def factor(folder, cost):
    save(folder/"qr.99.factor.json", {"objective_residual_basis": "original_weighted_rows_v1",
         "objective_accumulation": "compensated_long_double", "original_objective_rows": 10})
    save(folder/"qr.99.profile.json", {"direct_cost": cost})


def objective(tmp_path):
    points = []
    def endpoint(label, cost):
        folder = tmp_path/label
        path = folder/"qr.profile.json"
        save(path, profile())
        factor(folder, cost)
        points.append({"label": label, "objective": cost, "nuisance_converged": True,
                       "nuisance_floor_limited": False, "empirical_objective_resolution": 0.,
                       "nuisance_predicted_reduction": 1e-12, "receipt": str(path)})
    endpoint("nonzero-full-prior", 100.); endpoint("repeat", 100.)
    values = []
    for scale in (1., .5):
        checks = []
        for sign in (-1, 1):
            cost = 100.+2*sign*scale
            label = f"direction-{scale}-{sign}"
            endpoint(label, cost); endpoint(label+"-repeat", cost)
            checks.append({"sign": sign, "repeat_cost": cost, "repeat_difference": 0., "empirical_resolution": 0.})
        values.append({"scale": scale, "negative_cost": 100.-2*scale, "positive_cost": 100.+2*scale,
                       "finite_difference": 2., "native_derivative": 2., "relative_difference": 0.,
                       "empirical_resolution_fraction": 0., "relative_difference_plus_resolution": 0.,
                       "endpoint_resolution_checks": checks, "passes_unchanged_tolerance": True})
    return {"passed": True, "native_binary_sha256": NATIVE, "relative_derivative_tolerance": 1e-4,
            "derivative_refinement_policy": dict(audit.POLICY),
            "rank": {"status": "full_rank", "rank": 2, "columns": 2, "effective_rows": 10,
                     "minimum_singular_value": .1, "maximum_singular_value": 1., "threshold": math.ulp(1.)*10},
            "prior": {"source": "constraint.pulses", "rows": 2, "absolute_tolerance": 1e-12,
                      "maximum_residual_difference": 0., "cost": .01, "objective": 100.},
            "profile_evaluations": points, "objective_repeat_difference": 0.,
            "empirical_physical_objective_resolution": 0., "directional_derivatives": values,
            "accepted_derivative_scales": [1., .5]}


def floor_profile():
    p, e = 1e-12, 1e-8
    a = math.sqrt(4096*e/p)
    probes = [{"alpha": alpha, "actual_reduction": 2*alpha*p-alpha*alpha*p,
               "cost": 100.-(2*alpha*p-alpha*alpha*p), "maximum_update_m": abs(alpha)*1e-5,
               "status": 0, "error": ""} for alpha in (a, -a, a/2, -a/2)]
    r = [x["actual_reduction"] for x in probes]
    c, h = -(r[0]+r[1]), -(r[2]+r[3])
    s, t = (r[1]-r[0])/(2*a), (r[3]-r[2])/a
    potentials = (s*s*a*a/(2*c), t*t*a*a/(8*h),
                  (abs(s)+4*e/a)**2*a*a/(2*(c-2*e)), (abs(t)+8*e/a)**2*a*a/(8*(h-2*e)))
    record = {"kind": "two_amplitude_symmetric_nuisance_probe", "success": True, "support_unchanged": True,
              "amplitude": a, "slope": s, "half_slope": t, "curvature": c, "half_curvature": h,
              **dict(zip(audit.POTENTIALS, potentials)), "probes": probes,
              "curvature_resolution_multiple": 16, "curvature_scaling_error_multiple": 12,
              "slope_error_multiple": 4, "amplitude_slope_error_multiple": 8,
              "maximum_probe_amplitude": 1e9, "maximum_probe_influence_m": 1, "maximum_probe_rounds": 5,
              "probe_amplitude_policy": "bounded_precision_refinement_v1"}
    record["probe_history"] = [{k: deepcopy(v) for k,v in record.items() if k in
        ("amplitude", "slope", "half_slope", "curvature", "half_curvature", "probes", *audit.POTENTIALS)}]
    record["probe_history"][0].update(success=True, rejection="")
    value = profile(False)
    value.update(nuisance_objective_resolution=e,
                 nuisance_floor_policy="empirical_equivalent_arithmetic_and_symmetric_probes_v1",
                 nuisance_floor_audit=[{"kind": "equivalent_arithmetic", "mode": mode, "success": True,
                    "support_unchanged": True, "actual_reduction": e/mode, "cost": 100.-e/mode,
                    "status": 0, "error": ""} for mode in (1,2,3)]+[record])
    return value


def test_complete_objective_recomputed(tmp_path):
    result = audit.verify_objective(objective(tmp_path), "pulses", audit.Evidence(tmp_path), validator, NATIVE)
    assert result["passed"] and result["profiling_status_counts"] == {"strict_converged": 10}


@pytest.mark.parametrize("change", ["finite_difference", "resolution", "tolerance", "rank", "missing_endpoint", "stale_cost", "wrong_basis"])
def test_objective_fails_closed(tmp_path, change):
    value = objective(tmp_path)
    if change == "finite_difference": value["directional_derivatives"][0]["finite_difference"] = 3.
    elif change == "resolution": value["directional_derivatives"][0]["empirical_resolution_fraction"] = .00001
    elif change == "tolerance": value["relative_derivative_tolerance"] = .01
    elif change == "rank": value["rank"]["minimum_singular_value"] = 0.
    elif change == "missing_endpoint": value["profile_evaluations"].pop()
    elif change == "stale_cost": save(tmp_path/"repeat/qr.99.profile.json", {"direct_cost": 101.})
    else: save(tmp_path/"repeat/qr.99.factor.json", {"objective_residual_basis": "rotated"})
    with pytest.raises((ValueError, KeyError)):
        audit.verify_objective(value, "pulses", audit.Evidence(tmp_path), validator, NATIVE)


def test_floor_is_progress_only():
    value = floor_profile()
    status, resolution = audit.profile_status(value, validator, floor_prediction=1e-12, raw_update=1e-5)
    assert status == "progress_only_floor_limited" and resolution == 1e-8


@pytest.mark.parametrize("change", ["fake_curvature", "false_resolution", "failed_support", "actual_influence", "predicted_influence", "missing_probe", "history", "nonfinite"])
def test_floor_recomputes_native_probe_inequalities(change):
    value = floor_profile(); probe = value["nuisance_floor_audit"][-1]
    raw = 1e-5
    if change == "fake_curvature": probe["curvature"] *= 2
    elif change == "false_resolution": value["nuisance_objective_resolution"] *= 2
    elif change == "failed_support": probe["support_unchanged"] = False
    elif change == "actual_influence": probe["probes"][0]["maximum_update_m"] = 1.1
    elif change == "predicted_influence": raw = 1.
    elif change == "missing_probe": probe["probes"].pop()
    elif change == "history": probe["probe_history"][0]["amplitude"] *= 2
    else: probe["probes"][0]["actual_reduction"] = float("nan")
    with pytest.raises(ValueError): audit.check_floor(value, 1e-12, raw)


def nuisance(tmp_path):
    searches = []
    for generation in (1,2):
        search = {"accepted": False, "stationary_without_update": True, "nuisance_floor_limited": False,
                  "objective_before": 100., "full_step_prediction": 1e-12, "undamped_maximum_update_m": 1e-10,
                  "zero_update_replay": {"status": 0, "cost": 100., "actual_reduction": 0., "maximum_update_m": 0.},
                  "trials": [{"status": 0, "actual_reduction": 1e-12, "cost": 100.,
                              "alpha": 1., "maximum_update_m": 1e-10,
                              "observation_signature": "fixed", "ambiguity_half_integer_crossings": 1}]}
        path = tmp_path/"nuisance-replay"/f"qr.{generation}.nuisance_line_search.json"
        save(path, search)
        searches.append({"generation": generation, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **search})
    state = profile()
    save(tmp_path/"nuisance-replay/qr.profile.json", state)
    factor(tmp_path/"nuisance-replay", 100.)
    return {"passed": True, "returncode": 0, "timed_out": False, "native_unchanged": True,
            "native_sha256": NATIVE, "searches": searches, "profile": state,
            "ambiguity_half_integer_crossings_tested": 2, "fixed_observations_and_weights_verified_every_trial": True,
            "zero_update_replay_exact": True, "strict_nuisance_converged": True, "progress_only_floor_validated": False}


def test_strict_replay_verified(tmp_path):
    result = audit.verify_nuisance(nuisance(tmp_path), audit.Evidence(tmp_path), validator, NATIVE)
    assert result["passed"] and result["status"] == "strict_converged"


def test_replay_rejects_changed_transaction_file(tmp_path):
    data = nuisance(tmp_path)
    path = tmp_path/"nuisance-replay/qr.1.nuisance_line_search.json"
    save(path, {"changed": True})
    with pytest.raises(ValueError, match="content mismatch"):
        audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE)


def test_missing_receipt_retains_missing_artifact_status(tmp_path):
    evidence = audit.Evidence(tmp_path)
    with pytest.raises(FileNotFoundError): evidence.read(tmp_path/"missing.json", "missing")
    assert evidence.artifacts[-1]["status"] == "missing"


def test_duplicate_json_keys_rejected(tmp_path):
    path = tmp_path/"bad.json"; path.write_text('{"passed":true,"passed":false}')
    with pytest.raises(ValueError, match="Duplicate"):
        audit.Evidence(tmp_path).read(path, "bad")


def test_overflowing_json_number_rejected_even_in_extra_metadata(tmp_path):
    path = tmp_path/"bad.json"; path.write_text('{"extra":1e999}')
    with pytest.raises(ValueError, match="Nonfinite"):
        audit.Evidence(tmp_path).read(path, "bad")


def floor_search():
    p = floor_profile()
    return {"accepted": False, "stationary_without_update": False, "nuisance_floor_limited": True,
            "objective_before": 100., "full_step_prediction": 1e-12, "undamped_maximum_update_m": 1e-5,
            "nuisance_objective_resolution": 1e-8, "nuisance_floor_audit": p["nuisance_floor_audit"],
            "zero_update_replay": {"status": 0, "cost": 100., "actual_reduction": 0., "maximum_update_m": 0.},
            "trials": [{"status": 0, "alpha": .5**i, "cost": 100.+1e-10, "actual_reduction": -1e-10,
                        "maximum_update_m": .5**i*1e-5, "observation_signature": "fixed",
                        "ambiguity_half_integer_crossings": 0} for i in range(17)]}


def test_floor_search_checks_all_prerequisites():
    assert audit.check_search(floor_search()) == ("fixed", 0)


@pytest.mark.parametrize("change", ["zero_replay", "failed_trial", "signature", "disposition", "alpha", "negative_crossings", "early_acceptance"])
def test_floor_search_rejects_missing_prerequisites(change):
    value = floor_search()
    if change == "zero_replay": value["zero_update_replay"]["actual_reduction"] = 1e-9
    elif change == "failed_trial": value["trials"][2]["status"] = 1
    elif change == "signature": value["trials"][3]["observation_signature"] = "changed"
    elif change == "disposition": value["stationary_without_update"] = True
    elif change == "alpha": value["trials"][3]["alpha"] = .1
    elif change == "negative_crossings": value["trials"][4]["ambiguity_half_integer_crossings"] = -1
    else: value["trials"][2]["actual_reduction"] = 1e-9
    with pytest.raises(ValueError): audit.check_search(value)


def test_replay_checks_history_links(tmp_path):
    data = nuisance(tmp_path)
    data["profile"]["history"][0]["predicted_reduction"] = 2e-12
    save(tmp_path/"nuisance-replay/qr.profile.json", data["profile"])
    with pytest.raises(ValueError, match="history prediction"):
        audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE)


def test_replay_checks_parent_state_cost_chain(tmp_path):
    data = nuisance(tmp_path)
    second = data["searches"][1]
    second["objective_before"] = 101.
    second["zero_update_replay"]["cost"] = 101.
    path = tmp_path/"nuisance-replay/qr.2.nuisance_line_search.json"
    save(path, {k:v for k,v in second.items() if k not in ("generation", "sha256")})
    second["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="Accepted-state objective"):
        audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE)


def test_stationary_record_may_have_finite_negative_diagnostic_prediction(tmp_path):
    data = nuisance(tmp_path)
    for i, search in enumerate(data["searches"]):
        search["full_step_prediction"] = -1e-20
        data["profile"]["history"][i]["predicted_reduction"] = -1e-20
        path = tmp_path/"nuisance-replay"/f"qr.{i+1}.nuisance_line_search.json"
        save(path, {k:v for k,v in search.items() if k not in ("generation", "sha256")})
        search["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    data["profile"]["nuisance_predicted_reduction"] = -1e-20
    save(tmp_path/"nuisance-replay/qr.profile.json", data["profile"])
    result = audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE)
    assert result["passed"] and result["stationary_negative_prediction_count"] == 2


def test_second_replay_uses_its_own_receipts(tmp_path):
    data = nuisance(tmp_path)
    original = tmp_path/'nuisance-replay'
    second = tmp_path/'nuisance-replay-candidate1-point012'
    original.rename(second)
    result = audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE, second.name)
    assert result['passed'] is True
    with pytest.raises(FileNotFoundError):
        audit.verify_nuisance(data, audit.Evidence(tmp_path), validator, NATIVE)

def test_unknown_replay_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError,match='Unknown exact replay'):
        audit.verify_nuisance({},audit.Evidence(tmp_path),validator,NATIVE,'../other')

def test_numerical_gate_functions_are_ast_identical():
    import ast
    old=ast.parse(Path(__file__).with_name('verify_correctness_results.py').read_text())
    new=ast.parse(Path(__file__).with_name('verify_correctness_results_07.py').read_text())
    for name in ('number','equal','check_objective_factor','probe_numbers','check_floor','profile_status','check_search','verify_objective'):
        first=next(v for v in old.body if getattr(v,'name',None)==name)
        second=next(v for v in new.body if getattr(v,'name',None)==name)
        assert ast.dump(first,include_attributes=False)==ast.dump(second,include_attributes=False),name


def test_audit_failure_in_first_replay_does_not_skip_second(tmp_path,monkeypatch):
    import sys,types
    source=tmp_path/'source';backend=source/'src/orbit_poc/numerics/backend.py';backend.parent.mkdir(parents=True);backend.write_text('# fake validator source')
    package=types.ModuleType('orbit_poc');numeric=types.ModuleType('orbit_poc.numerics');module=types.ModuleType('orbit_poc.numerics.backend')
    module.__file__=str(backend);module.nuisance_profile_resolution=validator;package.numerics=numeric;numeric.backend=module
    for name,value in [('orbit_poc',package),('orbit_poc.numerics',numeric),('orbit_poc.numerics.backend',module)]:monkeypatch.setitem(sys.modules,name,value)
    run=tmp_path/'run'
    inventory={'src/orbit_poc/numerics/backend.py':hashlib.sha256(backend.read_bytes()).hexdigest()}
    source_hash=hashlib.sha256(json.dumps(inventory,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    pinpath=tmp_path/'control/candidate07-pins.json';save(pinpath,{'source_sha256':source_hash,
        'recovery_verifier_sha256':hashlib.sha256(Path(audit.__file__).with_name('recovery_evidence_07.py').read_bytes()).hexdigest()})
    save(run/'pipeline.json',{'native':{'sha256':NATIVE},'source':{'files':inventory,'sha256':source_hash},
        'required_pins':{'path':str(pinpath),'sha256':hashlib.sha256(pinpath.read_bytes()).hexdigest()}})
    monkeypatch.setattr(audit,'validate_replay_provenance',lambda *args:{'fixture':'isolated-loop-test'})
    real_loader=audit.load_recovery_helper
    def recovery_loader():
        helper=real_loader()
        helper.validate_recovery=lambda *args: {'status':'verified'}
        return helper
    monkeypatch.setattr(audit,'load_recovery_helper',recovery_loader)
    original_evidence=audit.Evidence
    class FixtureEvidence(original_evidence):
        def __init__(self,path):
            super().__init__(path);self.execution={'paths':{'run':str(run),'source':str(source)}}
    monkeypatch.setattr(audit,'Evidence',FixtureEvidence)
    for method in ('log_drag_ou','pulses'):save(run/('objective-'+method)/'validation.json',{})
    for replay in audit.REPLAYS:save(run/replay/'receipt.json',{'passed':False,'returncode':1})
    monkeypatch.setattr(audit,'verify_objective',lambda *args:{'passed':True,'errors':[]})
    seen=[]
    def check(data,evidence,validator,native,replay):
        seen.append(replay)
        if replay=='nuisance-replay':raise ValueError('first exact replay failed')
        return {'passed':True,'status':'progress_only_floor_limited','errors':[]}
    monkeypatch.setattr(audit,'verify_nuisance',check)
    result=audit.audit(run,source)
    assert seen==list(audit.REPLAYS)
    assert result['passed'] is False
    assert result['nuisance_replays']['nuisance-replay']['passed'] is False
    assert result['nuisance_replays']['nuisance-replay-candidate1-point012']['passed'] is True
    assert result['nuisance_replays']['nuisance-replay-candidate1-point012']['status']=='progress_only_floor_limited'


def replay_provenance_fixture(tmp_path):
    run=tmp_path/'run';run.mkdir();steps=[];inputs={};receipts={}
    for name,role in audit.REPLAY_INPUT_ROLES.items():
        path=tmp_path/(role+'.xml')
        prefix='old' if role=='old_nuisance_replay' else 'new'
        tags=[]
        for tag,suffix in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):
            leaf=tmp_path/(prefix+'-'+suffix+'.dat');leaf.write_bytes((role+suffix).encode())
            inputs[prefix+'_replay_'+suffix]={'path':str(leaf),'sha256':hashlib.sha256(leaf.read_bytes()).hexdigest()}
            tags.append('<'+tag+'>'+str(leaf)+'</'+tag+'>')
        path.write_text('<config>'+''.join(tags)+'</config>')
        digest=hashlib.sha256(path.read_bytes()).hexdigest();inputs[role]={'path':str(path),'sha256':digest}
        receipts[name]={'passed':True,'source_profile':str(path),'source_profile_sha256':digest}
        steps.append({'name':name,'status':'passed','returncode':0,'argv':['python','--source-profile',str(path),'--output',str(run/name)]})
    return run,{'steps':steps},{'input_artifacts':inputs},receipts

def test_exact_replay_provenance_links_correct_pin_and_command(tmp_path):
    run,pipeline,pins,receipts=replay_provenance_fixture(tmp_path)
    for name in audit.REPLAYS:
        proof=audit.validate_replay_provenance(receipts[name],name,pipeline,pins,audit.Evidence(run))
        assert proof['input_role']==audit.REPLAY_INPUT_ROLES[name]

@pytest.mark.parametrize('change',['swapped_receipt','duplicated_source','wrong_argv','duplicate_step','failed_step','changed_source'])
def test_exact_replay_provenance_rejects_wrong_case(tmp_path,change):
    run,pipeline,pins,receipts=replay_provenance_fixture(tmp_path);name='nuisance-replay-candidate1-point012'
    if change=='swapped_receipt':receipts[name]=receipts['nuisance-replay']
    elif change=='duplicated_source':pins['input_artifacts']['candidate1_nuisance_replay']=pins['input_artifacts']['old_nuisance_replay']
    elif change=='wrong_argv':pipeline['steps'][1]['argv'][2]=pins['input_artifacts']['old_nuisance_replay']['path']
    elif change=='duplicate_step':pipeline['steps'].append(deepcopy(pipeline['steps'][1]))
    elif change=='failed_step':pipeline['steps'][1]['status']='failed'
    elif change=='changed_source':Path(receipts[name]['source_profile']).write_text('<changed/>')
    with pytest.raises(ValueError):audit.validate_replay_provenance(receipts[name],name,pipeline,pins,audit.Evidence(run))

@pytest.mark.parametrize('change',['backend','inventory'])
def test_source_validator_must_match_actual_executed_inventory(tmp_path,change):
    source=tmp_path/'source';path=source/'src/orbit_poc/numerics/backend.py';path.parent.mkdir(parents=True);path.write_text('old')
    files={'src/orbit_poc/numerics/backend.py':hashlib.sha256(path.read_bytes()).hexdigest()}
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    pipeline={'source':{'files':files,'sha256':digest}};pins={'source_sha256':digest}
    audit.validate_source_provenance(pipeline,pins,source,audit.Evidence(tmp_path))
    if change=='backend':path.write_text('new validator')
    else:pipeline['source']['files']['other.py']='0'*64
    with pytest.raises(ValueError):audit.validate_source_provenance(pipeline,pins,source,audit.Evidence(tmp_path))


@pytest.mark.parametrize('which',['old','new'])
@pytest.mark.parametrize('field',['variational','reference','density'])
def test_replay_physical_inputs_are_independently_pinned(tmp_path,which,field):
    run,pipeline,pins,receipts=replay_provenance_fixture(tmp_path)
    name='nuisance-replay' if which=='old' else 'nuisance-replay-candidate1-point012'
    Path(pins['input_artifacts'][which+'_replay_'+field]['path']).write_bytes(b'changed physical input')
    with pytest.raises(ValueError,match='physical input changed'):
        audit.validate_replay_provenance(receipts[name],name,pipeline,pins,audit.Evidence(run))
