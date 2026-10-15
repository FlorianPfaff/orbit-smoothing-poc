#!/usr/bin/env python3
"""Independently audit completed correction receipts; never run an estimator.

This helper lives outside the candidate repository and writes only a new audit
file. Numerical-floor qualification remains progress-only, never convergence.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
REPLAY_INPUT_ROLES = {"nuisance-replay":"old_nuisance_replay",
                      "nuisance-replay-candidate1-point012":"candidate1_nuisance_replay"}
REPLAYS = {
    "nuisance-replay": "original near03 density point-030-direction-0.015625-1-repeat",
    "nuisance-replay-candidate1-point012": "validation02 density point-012-direction-0.25--1-repeat",
}

POLICY = {"maximum_scales": 9, "ratio": .5,
          "required_consecutive_passing_scales": 2,
          "physical_repeat_allowance_multiplier": 10}
POTENTIALS = ("empirical_quadratic_potential", "half_empirical_quadratic_potential",
              "empirical_quadratic_potential_with_allowance",
              "half_empirical_quadratic_potential_with_allowance")


def load_recovery_helper():
    path=Path(__file__).with_name('recovery_evidence_04.py')
    spec=importlib.util.spec_from_file_location('recovery_evidence04_audit',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def require(condition, message):
    if not condition:
        raise ValueError(message)


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "Missing or nonfinite numeric evidence")
    return float(value)


def equal(actual, expected, label):
    actual, expected = number(actual), number(expected)
    # Serialization/re-evaluation allowance, never a gate-tolerance expansion.
    allowance = 32*max(math.ulp(actual), math.ulp(expected))
    require(abs(actual-expected) <= allowance, label+" is inconsistent with recomputation")


def strict_pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate JSON key: "+key)
        result[key] = value
    return result


def strict_float(value):
    result = float(value)
    require(math.isfinite(result), "Nonfinite JSON number: "+value)
    return result


class Evidence:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.artifacts = []
        self.execution = {}

    def read(self, path, role, *, confined=True):
        path = Path(path).resolve()
        record = {"role": role, "path": str(path), "status": "missing" if not path.is_file() else "invalid"}
        self.artifacts.append(record)
        if confined:
            require(path.is_relative_to(self.root), "Receipt escapes the selected run: "+str(path))
        if not path.is_file():
            raise FileNotFoundError(path)
        require(path.stat().st_size <= 64*1024*1024, "Receipt exceeds compact audit limit")
        raw = path.read_bytes()
        record.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))
        value = json.loads(raw, object_pairs_hook=strict_pairs, parse_float=strict_float,
                           parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON: "+x)))
        require(isinstance(value, dict), "Receipt must be an object")
        record["status"] = "available"
        return value


def check_objective_factor(folder, evidence, role, expected_cost):
    factors = sorted(Path(folder).glob("qr.*.factor.json"), key=lambda p: int(p.name.split(".")[1]))
    require(factors, "Missing final native objective factor metadata")
    path = factors[-1]
    factor = evidence.read(path, role+"_factor")
    require(factor.get("objective_residual_basis") == "original_weighted_rows_v1"
            and factor.get("objective_accumulation") == "compensated_long_double"
            and type(factor.get("original_objective_rows")) is int and factor["original_objective_rows"] > 0,
            "Final factor does not certify original-row objective arithmetic")
    cost = evidence.read(Path(str(path).removesuffix(".factor.json")+".profile.json"), role+"_cost")
    equal(cost["direct_cost"], expected_cost, "Direct original-row objective")


def probe_numbers(record, e, prediction, *, allow_failed_allowance=False):
    a = number(record["amplitude"])
    require(0 < a <= 1e9, "Probe amplitude violates fixed numeric cap")
    probes = record["probes"]
    require(isinstance(probes, list) and len(probes) == 4, "Four symmetric probes are required")
    reductions = []
    for item, alpha in zip(probes, (a, -a, .5*a, -.5*a)):
        equal(item["alpha"], alpha, "Probe alpha")
        require(item["status"] == 0 and not item.get("error"), "A symmetric probe failed")
        require(0 <= number(item["maximum_update_m"]) <= 1., "Actual probe influence exceeds fixed metre cap")
        number(item["cost"])
        reductions.append(number(item["actual_reduction"]))
    plus, minus, halfplus, halfminus = reductions
    curvature, halfcurvature = -(plus+minus), -(halfplus+halfminus)
    slope, halfslope = (minus-plus)/(2*a), (halfminus-halfplus)/a
    for key, value in (("curvature", curvature), ("half_curvature", halfcurvature),
                       ("slope", slope), ("half_slope", halfslope)):
        equal(record[key], value, key)
    require(curvature > 16*e and halfcurvature > 16*e, "Unresolved or nonpositive symmetric curvature")
    require(abs(curvature-4*halfcurvature) <= 12*e, "Amplitude-dependent symmetric curvature")
    require(abs(slope-halfslope) <= 8*e/a, "Amplitude-dependent symmetric slope")
    require(abs(slope+2*prediction) <= 4*e/a and abs(halfslope+2*prediction) <= 8*e/a,
            "Symmetric slope disagrees with fresh undamped gradient")
    potentials = (slope*slope*a*a/(2*curvature), halfslope*halfslope*a*a/(8*halfcurvature),
                  (abs(slope)+4*e/a)**2*a*a/(2*(curvature-2*e)),
                  (abs(halfslope)+8*e/a)**2*a*a/(8*(halfcurvature-2*e)))
    for key, value in zip(POTENTIALS, potentials):
        equal(record[key], value, key)
        require(value > 0, "Nonpositive empirical potential")
    require(max(potentials[:2]) <= e, "Nominal empirical potential exceeds measured resolution")
    if not allow_failed_allowance:
        require(max(potentials[2:]) <= e, "Empirical potential with allowance exceeds resolution")
    return potentials


def check_floor(profile, prediction=None, raw_update=None):
    e = number(profile["nuisance_objective_resolution"])
    fresh = number(profile["nuisance_predicted_reduction"])
    prediction = fresh if prediction is None else number(prediction)
    require(e > 0 and 0 < prediction <= e and 0 < fresh <= e, "Potential is outside measured positive resolution")
    audits = profile["nuisance_floor_audit"]
    require(isinstance(audits, list) and len(audits) == 4, "Exactly four floor audit records required")
    arithmetic = [r for r in audits if r.get("kind") == "equivalent_arithmetic"]
    require(sorted(r.get("mode") for r in arithmetic) == [1, 2, 3], "Arithmetic modes must be exactly 1,2,3")
    require(all(r.get("success") is True and r.get("support_unchanged") is True for r in audits),
            "Floor audit failed or changed support")
    for item in arithmetic:
        require(item["status"] == 0 and not item.get("error"), "Equivalent arithmetic evaluation failed")
        number(item["cost"])
    equal(e, max(abs(number(r["actual_reduction"])) for r in arithmetic), "Measured arithmetic resolution")
    records = [r for r in audits if r.get("kind") == "two_amplitude_symmetric_nuisance_probe"]
    require(len(records) == 1, "One symmetric audit required")
    probe = records[0]
    for key, fixed in (("curvature_resolution_multiple", 16), ("curvature_scaling_error_multiple", 12),
                       ("slope_error_multiple", 4), ("amplitude_slope_error_multiple", 8),
                       ("maximum_probe_amplitude", 1e9), ("maximum_probe_influence_m", 1),
                       ("maximum_probe_rounds", 5)):
        equal(probe[key], fixed, key)
    require(probe["probe_amplitude_policy"] == "bounded_precision_refinement_v1", "Unknown probe policy")
    probe_numbers(probe, e, prediction)
    history = probe["probe_history"]
    require(1 <= len(history) <= 5, "Invalid bounded probe history")
    initial = max(64., math.sqrt(4096.*e/prediction))
    for i, item in enumerate(history):
        equal(item["amplitude"], initial*2**i, "Refined probe amplitude")
        if raw_update is not None:
            require(number(item["amplitude"])*number(raw_update) <= 1., "Predicted probe influence exceeds fixed cap")
        final = i == len(history)-1
        potentials = probe_numbers(item, e, prediction, allow_failed_allowance=not final)
        if final:
            require(item["success"] is True and item["rejection"] == "", "Final probe history is not successful")
            for key in ("amplitude", "slope", "half_slope", "curvature", "half_curvature", *POTENTIALS):
                equal(item[key], probe[key], "Final probe history "+key)
            require(item["probes"] == probe["probes"], "Final probe samples differ from history")
        else:
            require(item["success"] is False and item["rejection"] == "empirical_quadratic_potential_with_allowance_exceeds_resolution"
                    and max(potentials[2:]) > e, "Unsupported probe-refinement reason")
    return {"resolution": e, "fresh_potential": fresh, "probe_amplitude": probe["amplitude"],
            "probe_rounds": len(history)}


def profile_status(profile, validator, *, floor_prediction=None, raw_update=None):
    resolution, limited = validator(profile)
    require(profile.get("fixed_weights") is True and profile.get("dynamic_updates") is False,
            "Profile changed weights or physical parameters")
    equal(profile["threshold_m"], 1e-8, "Nuisance threshold")
    require(profile["required_consecutive_small_updates"] == 2, "Changed inner convergence count")
    history = profile["history"]
    require(len(history) == profile["iterations"] and history, "Incomplete nuisance history")
    for item in history:
        require(number(item["maximum_update_m"]) >= 0, "Negative nuisance influence")
        number(item["gradient_scaled"]); number(item["predicted_reduction"])
    equal(profile["maximum_update_m"], history[-1]["maximum_update_m"], "Final raw nuisance influence")
    number(profile["nuisance_gradient_scaled"]); number(profile["nuisance_predicted_reduction"])
    if limited:
        check_floor(profile, floor_prediction, raw_update)
        return "progress_only_floor_limited", resolution
    require(len(history) >= 2 and all(number(h["maximum_update_m"]) < 1e-8 for h in history[-2:]),
            "Strict nuisance convergence lacks two small fresh undamped corrections")
    return "strict_converged", 0.


def check_search(search):
    """Validate the native controller's complete recorded disposition."""
    flags = [search.get(k) for k in ("accepted", "stationary_without_update", "nuisance_floor_limited")]
    require(all(type(flag) is bool for flag in flags) and sum(flags) == 1, "Search disposition is not exclusive")
    before = number(search["objective_before"])
    prediction = number(search["full_step_prediction"])
    raw = number(search["undamped_maximum_update_m"])
    # Native stationarity uses the fresh undamped influence before the gain
    # test. Its finite diagnostic prediction may be slightly negative from
    # cancellation; positivity is required for accepted or floor-limited steps.
    require(before >= 0 and raw >= 0, "Negative search objective/influence")
    replay = search["zero_update_replay"]
    require(replay["status"] == 0 and replay["actual_reduction"] == 0 and replay["maximum_update_m"] == 0,
            "Zero-update replay is not exact")
    equal(replay["cost"], before, "Zero-update replay cost")
    trials = search["trials"]
    require(isinstance(trials, list) and 1 <= len(trials) <= 17, "Invalid bounded trial count")
    signatures, first_raw, crossings = set(), None, 0
    successful = []
    for i, trial in enumerate(trials):
        alpha = .5**i
        equal(trial["alpha"], alpha, "Ordinary trial alpha schedule")
        require(type(trial["status"]) is int and trial["status"] >= 0, "Invalid trial status")
        if trial["status"]:
            continue
        require(not trial.get("error"), "Successful trial has an error")
        require(number(trial["cost"]) >= 0 and number(trial["maximum_update_m"]) >= 0, "Invalid trial cost/influence")
        reduction = number(trial["actual_reduction"])
        signature = trial["observation_signature"]
        require(isinstance(signature, str) and signature not in ("", "0"), "Invalid observation signature")
        signatures.add(signature)
        count = trial["ambiguity_half_integer_crossings"]
        require(type(count) is int and count >= 0, "Invalid ambiguity crossing count")
        crossings += count
        if first_raw is None:
            first_raw = trial["maximum_update_m"]/alpha
        pred = (2*alpha-alpha*alpha)*prediction
        acceptable = reduction > 0 and pred > 0 and reduction/pred > 1e-4
        successful.append((i, acceptable))
        if i < len(trials)-1:
            require(first_raw >= 1e-8 and not acceptable, "Search continued after a terminal valid trial")
    require(first_raw is not None and len(signatures) == 1, "No consistent successful trial support")
    equal(raw, first_raw, "Fresh full undamped influence")
    if search["accepted"]:
        require(successful[-1][0] == len(trials)-1 and successful[-1][1] and raw >= 1e-8,
                "Accepted trial violates the unchanged gain rule")
        equal(search["alpha"], trials[-1]["alpha"], "Accepted nuisance alpha")
    elif search["stationary_without_update"]:
        require(raw < 1e-8 and successful[-1][0] == len(trials)-1, "Stationarity is not a fresh undamped correction")
    else:
        require(len(trials) == 17 and len(successful) == 17 and not any(item[1] for item in successful)
                and raw >= 1e-8 and prediction > 0, "Floor audit lacks seventeen valid rejected ordinary trials")
    return signatures.pop(), crossings


def verify_objective(data, method, evidence, validator, expected_native):
    require(data.get("passed") is True and not data.get("error"), "Objective harness did not pass")
    require(data["native_binary_sha256"] == expected_native, "Objective candidate binary differs")
    equal(data["relative_derivative_tolerance"], 1e-4, "Objective derivative tolerance")
    require(data["derivative_refinement_policy"] == POLICY, "Objective refinement policy changed")
    rank = data["rank"]
    require(all(type(rank[key]) is int and rank[key] > 0 for key in ("rank", "columns", "effective_rows"))
            and rank["effective_rows"] >= rank["columns"], "Invalid native rank dimensions")
    require(rank["status"] == "full_rank" and rank["rank"] == rank["columns"], "Objective factor is not fully resolved")
    require(0 < number(rank["minimum_singular_value"]) <= number(rank["maximum_singular_value"]), "Invalid singular values")
    threshold = sys.float_info.epsilon*max(rank["effective_rows"], rank["columns"])*number(rank["maximum_singular_value"])
    equal(rank["threshold"], threshold, "Rank threshold")
    require(number(rank["minimum_singular_value"]) > 10*threshold, "Objective rank unresolved")
    prior = data["prior"]
    expected_label = "constraint.logDensityOu" if method == "log_drag_ou" else "constraint.pulses"
    require(prior["source"] == expected_label and type(prior["rows"]) is int and prior["rows"] > 0, "Missing active full prior")
    tolerance = 2e-8 if method == "log_drag_ou" else 1e-12
    equal(prior["absolute_tolerance"], tolerance, "Full prior tolerance")
    require(0 <= number(prior["maximum_residual_difference"]) <= tolerance, "Full prior residual mismatch")
    require(0 < number(prior["cost"]) <= number(prior["objective"]), "Nonzero prior cost missing")
    points, statuses = {}, Counter()
    for point in data["profile_evaluations"]:
        label = point["label"]
        require(label not in points, "Duplicate objective endpoint label")
        profile = evidence.read(point["receipt"], "objective_profile_"+method+"_"+label)
        # Every floor audit's historical probe model uses its own pre-confirmation
        # prediction, retained in the preceding line-search receipt.
        prediction = raw_update = None
        if profile.get("nuisance_floor_limited"):
            folder = Path(point["receipt"]).parent
            searches = sorted(folder.glob("qr.*.nuisance_line_search.json"), key=lambda p: int(p.name.split(".")[1]))
            require(searches, "Missing floor-limited line-search evidence")
            search = evidence.read(searches[-1], "objective_floor_search_"+method+"_"+label)
            check_search(search)
            require(search["nuisance_floor_limited"] is True and search["nuisance_floor_audit"] == profile["nuisance_floor_audit"],
                    "Final profile does not preserve its successful floor audit")
            equal(search["nuisance_objective_resolution"], profile["nuisance_objective_resolution"], "Confirmed floor resolution")
            prediction, raw_update = search["full_step_prediction"], search["undamped_maximum_update_m"]
        status, resolution = profile_status(profile, validator, floor_prediction=prediction, raw_update=raw_update)
        statuses[status] += 1
        require(point["nuisance_converged"] == profile["nuisance_converged"]
                and point["nuisance_floor_limited"] == profile["nuisance_floor_limited"], "Endpoint profiling status differs")
        equal(point["empirical_objective_resolution"], resolution, "Endpoint objective resolution")
        equal(point["nuisance_predicted_reduction"], profile["nuisance_predicted_reduction"], "Endpoint fresh potential")
        number(point["objective"])
        check_objective_factor(Path(point["receipt"]).parent, evidence, "objective_"+method+"_"+label, point["objective"])
        points[label] = point
    base, repeat = points["nonzero-full-prior"], points["repeat"]
    equal(prior["objective"], base["objective"], "Prior endpoint objective")
    difference = abs(number(base["objective"])-number(repeat["objective"]))
    equal(data["objective_repeat_difference"], difference, "Base repeat difference")
    physical = 10*difference
    equal(data["empirical_physical_objective_resolution"], physical, "Physical repeat allowance")
    values = data["directional_derivatives"]
    require(2 <= len(values) <= 9, "Incomplete objective directional refinement")
    streak = 0
    for i, item in enumerate(values):
        scale = .5**i
        equal(item["scale"], scale, "Directional scale")
        checks = item["endpoint_resolution_checks"]
        require(len(checks) == 2, "Both endpoint repeats required")
        costs, resolutions = [], []
        for check, sign, cost_key in zip(checks, (-1, 1), ("negative_cost", "positive_cost")):
            require(check["sign"] == sign, "Endpoint sign mismatch")
            label = f"direction-{scale}-{sign}"
            value, replay = points[label], points[label+"-repeat"]
            cost, repeated_cost = number(value["objective"]), number(replay["objective"])
            delta = abs(cost-repeated_cost)
            resolution = max(physical, 10*delta)+max(value["empirical_objective_resolution"], replay["empirical_objective_resolution"])
            equal(item[cost_key], cost, "Directional endpoint cost")
            equal(check["repeat_cost"], repeated_cost, "Repeated endpoint cost")
            equal(check["repeat_difference"], delta, "Endpoint repeat difference")
            equal(check["empirical_resolution"], resolution, "Endpoint resolution allowance")
            costs.append(cost); resolutions.append(resolution)
        numerical = (costs[1]-costs[0])/(2*scale)
        derivative = number(item["native_derivative"])
        equal(derivative, values[0]["native_derivative"], "Fixed native directional derivative")
        denominator = max(abs(numerical), abs(derivative), 1e-12)
        relative = abs(numerical-derivative)/denominator
        fraction = sum(resolutions)/(2*scale*denominator)
        equal(item["finite_difference"], numerical, "Finite difference")
        equal(item["relative_difference"], relative, "Derivative discrepancy")
        equal(item["empirical_resolution_fraction"], fraction, "Relative resolution allowance")
        equal(item["relative_difference_plus_resolution"], relative+fraction, "Total derivative gate error")
        passed = relative+fraction <= 1e-4
        require(item["passes_unchanged_tolerance"] is passed, "Directional pass label differs from recomputation")
        streak = streak+1 if passed else 0
        require(streak < 2 or i == len(values)-1, "Harness continued after its first passing pair")
    require(streak == 2 and data["accepted_derivative_scales"] == [v["scale"] for v in values[-2:]],
            "Two consecutive accepted refinements missing")
    require(len(points) == 2+4*len(values), "Unmatched or missing objective endpoint evidence")
    return {"passed": True, "accepted_scales": data["accepted_derivative_scales"],
            "profiling_status_counts": dict(statuses), "errors": []}


def verify_nuisance(data, evidence, validator, expected_native, replay="nuisance-replay"):
    require(replay in REPLAYS, "Unknown exact replay identity")
    folder = evidence.root/replay
    require(data.get("passed") is True and data["returncode"] == 0 and data["timed_out"] is False,
            "Nuisance replay did not complete successfully")
    require(data["native_unchanged"] is True and data["native_sha256"] == expected_native, "Nuisance binary differs")
    searches = data["searches"]
    require(searches and [s["generation"] for s in searches] == list(range(1, len(searches)+1)), "Missing nuisance generations")
    signatures, crossings = set(), 0
    for index, search in enumerate(searches):
        generation = search["generation"]
        path = folder/f"qr.{generation}.nuisance_line_search.json"
        original = evidence.read(path, replay+"_search_"+str(generation))
        require(evidence.artifacts[-1]["sha256"] == search["sha256"] and original == {k:v for k,v in search.items() if k not in ("generation", "sha256")},
                "Nuisance receipt/search content mismatch")
        signature, count = check_search(search)
        signatures.add(signature); crossings += count
        if index+1 < len(searches):
            expected_cost = search["trials"][-1]["cost"] if search["accepted"] else search["objective_before"]
            equal(searches[index+1]["objective_before"], expected_cost, "Accepted-state objective replay")
    require(len(signatures) == 1 and None not in signatures and "0" not in signatures, "Observation support/weights changed")
    require(crossings > 0 and crossings == data["ambiguity_half_integer_crossings_tested"], "Missing ambiguity crossing witness")
    require(data["fixed_observations_and_weights_verified_every_trial"] is True and data["zero_update_replay_exact"] is True,
            "Replay summary conflicts with transaction checks")
    profile = evidence.read(folder/"qr.profile.json", replay+"_profile")
    require(profile == data["profile"], "Nuisance aggregate profile differs from native receipt")
    last = searches[-1]
    check_objective_factor(folder, evidence, replay+"_final", last["objective_before"])
    status, resolution = profile_status(profile, validator, floor_prediction=last["full_step_prediction"],
                                        raw_update=last["undamped_maximum_update_m"])
    require(profile["iterations"] == len(searches), "Nuisance history/search count differs")
    for item, search in zip(profile["history"], searches):
        equal(item["maximum_update_m"], search["undamped_maximum_update_m"], "Nuisance history raw influence")
        equal(item["predicted_reduction"], search["full_step_prediction"], "Nuisance history prediction")
    if status == "strict_converged":
        require(data["strict_nuisance_converged"] is True and data["progress_only_floor_validated"] is False,
                "Strict/progress-only summary differs")
        require(all(s["stationary_without_update"] is True and number(s["undamped_maximum_update_m"]) < 1e-8
                    for s in searches[-2:]), "Strict profile lacks two stationary undamped searches")
    else:
        require(data["allow_floor_limited_requested"] is True and data["strict_nuisance_converged"] is False
                and data["progress_only_floor_validated"] is True, "Floor status improperly relabelled")
        require(last["nuisance_floor_limited"] is True and last["nuisance_floor_audit"] == profile["nuisance_floor_audit"],
                "Final floor search/profile mismatch")
    return {"passed": True, "status": status, "resolution": resolution,
            "stationary_negative_prediction_count": sum(s["stationary_without_update"] and s["full_step_prediction"] < 0 for s in searches),
            "errors": []}


def record_bytes(evidence, path, role):
    path=load_recovery_helper().host_path(path,evidence.execution).resolve()
    item={"role":role,"path":str(path),"status":"missing" if not path.is_file() else "invalid"}
    evidence.artifacts.append(item)
    require(path.is_file() and path.stat().st_size <= 64*1024*1024,"Missing or oversized pinned dependency")
    raw=path.read_bytes();item.update(status="available",sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
    return item


def validate_source_provenance(pipeline, pins, source, evidence):
    inventory=pipeline.get("source") or {};files=inventory.get("files")
    require(isinstance(files,dict) and files,"Missing actual executed source inventory")
    digest=hashlib.sha256(json.dumps(files,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    require(digest==inventory.get("sha256")==pins.get("source_sha256"),"Executed source inventory digest differs from pinned source")
    path=Path(source)/"src/orbit_poc/numerics/backend.py"
    item=record_bytes(evidence,path,"backend_validator_source")
    require(item["sha256"]==files.get("src/orbit_poc/numerics/backend.py"),"Imported backend validator differs from executed source inventory")


def validate_replay_provenance(data, replay, pipeline, pins, evidence):
    role=REPLAY_INPUT_ROLES[replay]
    inputs=pins.get("input_artifacts") or {};pin=inputs.get(role) or {}
    other=inputs.get(REPLAY_INPUT_ROLES[next(name for name in REPLAYS if name!=replay)]) or {}
    require(isinstance(pin.get("path"),str) and isinstance(other.get("path"),str),"Missing exact replay source pins")
    expected=Path(pin["path"]).resolve()
    require(expected!=Path(other["path"]).resolve(),"Two prescribed replay sources are duplicated")
    item=record_bytes(evidence,expected,"prescribed_replay_profile_"+replay)
    require(item["sha256"]==pin.get("sha256"),"Prescribed replay source XML changed")
    # Bind the three exact physical inputs referenced by each immutable XML.
    # These cannot be silently substituted while retaining the same case label.
    prefix="old" if role=="old_nuisance_replay" else "new"
    raw=load_recovery_helper().host_path(expected,evidence.execution).read_bytes()
    require(b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(),"Replay XML entities forbidden")
    tree=ET.fromstring(raw)
    leaves={}
    for tag,suffix in (("inputfileVariational","variational"),
                       ("inputfileNumericsReferenceParameters","reference"),
                       ("inputfileLogDensity","density")):
        leafrole=prefix+"_replay_"+suffix
        leaf=inputs.get(leafrole) or {}
        require(isinstance(leaf.get("path"),str),"Missing prescribed replay physical-input pin")
        path=Path(leaf["path"]).resolve()
        matches=[(v.text or "").strip() for v in tree.iter(tag)]
        require(matches and all(Path(v).resolve()==path for v in matches),"Replay XML physical input differs from prescribed pin: "+tag)
        receipt=record_bytes(evidence,path,"prescribed_replay_input_"+leafrole)
        require(receipt["sha256"]==leaf.get("sha256"),"Prescribed replay physical input changed: "+leafrole)
        leaves[leafrole]={"path":str(path),"sha256":leaf["sha256"]}
    require(isinstance(data.get("source_profile"),str) and Path(data["source_profile"]).resolve()==expected
            and data.get("source_profile_sha256")==pin["sha256"],"Replay receipt source differs from its exact prescribed case")
    steps=[step for step in pipeline.get("steps",[]) if isinstance(step,dict) and step.get("name")==replay]
    require(len(steps)==1,"Replay step is not uniquely recorded")
    argv=steps[0].get("argv")
    require(isinstance(argv,list) and argv.count("--source-profile")==1 and argv.count("--output")==1,"Replay command source/output flags are ambiguous")
    index=argv.index("--source-profile");out=argv.index("--output")
    require(index+1<len(argv) and Path(argv[index+1]).resolve()==expected,"Replay command source differs from prescribed source")
    require(out+1<len(argv) and Path(argv[out+1]).resolve()==evidence.root/replay,"Replay command output differs from its independent directory")
    if data.get("passed") is True:
        require(steps[0].get("status")=="passed" and steps[0].get("returncode")==0,"Passed replay lacks a unique successful recorded command")
    return {"source_profile":str(expected),"source_profile_sha256":pin["sha256"],"input_role":role,"physical_inputs":leaves}


def audit(run, source, pins_path=None):
    evidence = Evidence(run)
    helper = Path(__file__).resolve()
    helper_bytes = helper.read_bytes()
    evidence.artifacts.append({"role": "independent_verifier_source", "path": str(helper), "status": "available",
                               "sha256": hashlib.sha256(helper_bytes).hexdigest(), "bytes": len(helper_bytes)})
    result = {"schema": "orbit-poc-correctness-independent-audit-v4", "passed": False,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "objective_methods": {method:{"passed":False,"errors":["Not assessed"]} for method in ("log_drag_ou","pulses")},
              "nuisance_replays": {name:{"passed":False,"status":"not_assessed","errors":[],"source_failure":label}
                                    for name,label in REPLAYS.items()},
              "input_artifacts": evidence.artifacts, "errors": [],
              "scope": "Independent receipt arithmetic/consistency audit. No estimator execution, covariance approval, scientific superiority or release certification. Floor status remains progress-only."}
    try:
        source = Path(source).resolve(strict=True)
        pipeline = evidence.read(Path(run)/"pipeline.json", "pipeline")
        pin_path=Path(pins_path).resolve() if pins_path is not None else Path(run).resolve().parent/"control/candidate04-pins.json"
        pins=evidence.read(pin_path,"candidate04_pins",confined=False)
        required=pipeline.get("required_pins") or {}
        require(isinstance(required.get("path"),str) and Path(required["path"]).resolve()==pin_path
                and required.get("sha256")==evidence.artifacts[-1]["sha256"],"Executed candidate04 input/control pins changed")
        helper_recovery=load_recovery_helper()
        record_bytes(evidence,Path(__file__).with_name('recovery_evidence_04.py'),'recovery_verifier_source')
        def read_pin(pin,role):
            value=evidence.read(pin['path'],role,confined=False)
            require(evidence.artifacts[-1].get('sha256')==pin['sha256'],'Recovery provenance changed: '+role)
            if role=='execution':evidence.execution=value
            return value
        result['recovery']=helper_recovery.validate_recovery(pipeline,pins,read_pin)
        require(Path(evidence.execution['paths']['run']).resolve()==evidence.root,'Audit run differs from executed run')
        require(Path(evidence.execution['paths']['source']).resolve()==source,'Audit source differs from executed source')
        validate_source_provenance(pipeline,pins,source,evidence)
        sys.path.insert(0, str(source/"src"))
        from orbit_poc.numerics.backend import nuisance_profile_resolution
        import orbit_poc.numerics.backend as backend
        require(Path(backend.__file__).resolve() == source/"src/orbit_poc/numerics/backend.py", "Wrong backend validator import")
        expected_native = pipeline["native"]["sha256"]
        require(len(expected_native) == 64, "Missing candidate binary identity")
    except Exception as error:
        result["errors"].append(type(error).__name__+": "+str(error))
        # An infrastructure failure must retain the planned absent or produced
        # receipts as pinned evidence; it cannot inherit numerical success.
        for role,path in [("objective_"+m,Path(run)/("objective-"+m)/"validation.json") for m in ("log_drag_ou","pulses")]+[(name+"_receipt",Path(run)/name/"receipt.json") for name in REPLAYS]:
            try:evidence.read(path,role)
            except (ValueError,FileNotFoundError,OSError):pass
        return result
    for method in ("log_drag_ou", "pulses"):
        try:
            data = evidence.read(Path(run)/("objective-"+method)/"validation.json", "objective_"+method)
            result["objective_methods"][method] = verify_objective(data, method, evidence, nuisance_profile_resolution, expected_native)
        except Exception as error:
            result["objective_methods"][method] = {"passed": False, "errors": [type(error).__name__+": "+str(error)]}
    for replay,label in REPLAYS.items():
        item = {"passed":False,"status":"failed","errors":[],"source_failure":label,
                "receipt":str(Path(run)/replay/"receipt.json")}
        result["nuisance_replays"][replay] = item
        try:
            data = evidence.read(Path(run)/replay/"receipt.json", replay+"_receipt")
            item.update(reported_passed=data.get("passed"), returncode=data.get("returncode"))
            item["source_provenance"]=validate_replay_provenance(data,replay,pipeline,pins,evidence)
            item.update(verify_nuisance(data, evidence, nuisance_profile_resolution, expected_native, replay))
        except Exception as error:
            item["errors"].append(type(error).__name__+": "+str(error))
    result["passed"] = (all(v["passed"] for v in result["objective_methods"].values())
                        and all(v["passed"] for v in result["nuisance_replays"].values()))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pins", type=Path)
    args = parser.parse_args()
    require(not args.output.exists(), "Choose a new audit output; prior audits are immutable")
    output = audit(args.run, args.source, args.pins)
    with args.output.open("x") as stream:
        json.dump(output, stream, indent=2, sort_keys=True, allow_nan=False); stream.write("\n")
    print(json.dumps({"passed": output["passed"], "audit": str(args.output)}))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
