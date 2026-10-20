"""Exact profile-pair equality fails on changed scientific evidence."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "check_nuisance_performance_pair.py"
spec = importlib.util.spec_from_file_location("check_nuisance_pair", SCRIPT)
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def make_run(root, *, cpu=1., floor=False):
    root.mkdir()
    xml = root / "profile.xml"
    xml.write_text("<groops/>")
    argv = ["/usr/bin/taskset", "-c", "0", "/native", str(xml)]
    supervisor = write(root / "supervisor.json", {"status": "complete", "returncode": 0,
        "owned_process_group_cleaned": True, "cleanup": {"verified": True}, "argv": argv})
    write(root / "profile.execution.json", {"returncode": 0, "timed_out": False, "status": "complete",
        "owned_process_group_cleaned": True, "supervisor_sha256": hashlib.sha256(supervisor.read_bytes()).hexdigest(),
        "command": argv, "config_sha256": hashlib.sha256(xml.read_bytes()).hexdigest(),
        "native_binary_sha256": "b" * 64, "blas_openmp_threads": 1, "input_identity_after": "verified"})
    profile = {"nuisance_converged": not floor, "nuisance_floor_limited": floor,
        "iterations": 2, "threshold_m": 1e-8, "required_consecutive_small_updates": 2,
        "fixed_weights": True, "dynamic_updates": False,
        "maximum_update_m": 1e-9,
        "history": [{"maximum_update_m": 1e-9}, {"maximum_update_m": 1e-9}]}
    if floor:
        profile.update(nuisance_objective_resolution=1e-10, nuisance_predicted_reduction=1e-12,
            nuisance_floor_policy="empirical_equivalent_arithmetic_and_symmetric_probes_v1",
            nuisance_floor_audit=[*[{"kind": "equivalent_arithmetic", "mode": mode, "success": True, "support_unchanged": True}
                                   for mode in (1, 2, 3)],
                {"kind": "two_amplitude_symmetric_nuisance_probe", "probes": [{}, {}, {}, {}],
                 "success": True, "support_unchanged": True, "empirical_quadratic_potential": 1e-12,
                 "half_empirical_quadratic_potential": 1e-12, "empirical_quadratic_potential_with_allowance": 1e-11,
                 "half_empirical_quadratic_potential_with_allowance": 1e-11}])
    write(root / "qr.profile.json", profile)
    for generation in range(1, 4):
        stem = root / f"qr.{generation}"
        for suffix in check.REQUIRED_FACTOR:
            path = Path(str(stem) + "." + suffix)
            if suffix == "factor.json":
                write(path, {"rows": 1, "columns": 1, "orthogonal_energy": 3., "scales": [1.]})
            elif suffix == "diagnostics.json":
                write(path, {"lambda": 0, "rank_status": "full", "rank": 1, "source_rows": 3})
            elif suffix == "profile.json":
                write(path, {"direct_cost": 2., "nuisance_predicted_reduction": 1e-14})
            elif suffix.endswith(".bin"):
                path.write_bytes(struct.pack("<QQd", 1, 1, 2.))
            else:
                path.write_text("index\tvalue\n0\t2\n")
        if generation <= 2:
            write(Path(str(stem) + ".nuisance_line_search.json"), {"accepted": True,
                "full_step_prediction": 5., "zero_update_replay": {"status": 0, "actual_reduction": 0},
                "trials": [{"status": 0, "cost": 2., "observation_signature": "a", "child_user_seconds": cpu,
                            "child_system_seconds": cpu / 10, "peak_child_rss_bytes": int(cpu * 100)}]})
            Path(str(stem) + ".receiver_times.tsv").write_text("epoch\ttime\n0\t0\n")
    return root


def pair(tmp_path, **kwargs):
    off, on = make_run(tmp_path / "off", **kwargs), make_run(tmp_path / "on", cpu=2., **kwargs)
    jobs = []
    for cache, root in enumerate((off, on)):
        jobs.append({"name": root.name, "method": "pulses", "cache": cache, "accumulate": 0,
            "profile": str(root / "profile.xml"), "profile_sha256": hashlib.sha256((root / "profile.xml").read_bytes()).hexdigest(),
            "source_profile": {"sha256": "a" * 64}, "input_files": [{"path": "/input", "sha256": "c" * 64}]})
    preparation = write(tmp_path / "preparation.json", {"schema": "orbit-poc-nuisance-pair-preparation-v1",
        "cpu": 0, "one_numerical_thread": True, "predeclared_order": ["off", "on"], "jobs": jobs})
    freeze = write(tmp_path / "freeze.json", {"schema": "orbit-poc-nuisance-pair-freeze-v1",
        "preparation_sha256": hashlib.sha256(preparation.read_bytes()).hexdigest(), "order": ["off", "on"],
        "native": {"path": "/native", "sha256": "b" * 64}})
    for cache, root in enumerate((off, on)):
        path = root / "profile.execution.json"; value = json.loads(path.read_text())
        value.update(cache=cache, accumulate_epoch_observations=0, freeze_sha256=hashlib.sha256(freeze.read_bytes()).hexdigest())
        write(path, value)
        for generation in (1, 2):
            search = json.loads((root / f"qr.{generation}.nuisance_line_search.json").read_text())
            row = {"available": True, "completed": True, "cost_only": False, "build_wall_seconds": 1.,
                "observation_design_wall_seconds": .5, "observation_design_calls": 2,
                "interpolation_cache": bool(cache), "interpolation_calls": 2,
                "interpolation_cache_hits": cache, "interpolation_evaluations": 2-cache, "interpolation_wall_seconds": .2}
            child = {"status": 0, "wall_seconds": 1., "row_build": row}
            trial = {**child, **{key: search["trials"][0][key] for key in check.STRIPPED_TRIAL_FIELDS}}
            write(root / f"qr.{generation}.nuisance_performance.json", {
                "schema": "orbit-poc-nuisance-performance-v1", "parent_row_build": row,
                "zero_update_replay": child, "ordinary_trials": [trial], "arithmetic_audits": [], "probe_rounds": []})
    return off, on


def test_matching_science_ignores_only_declared_trial_resource_fields(tmp_path):
    off, on = pair(tmp_path)
    result = check.compare(off, on)
    assert result["passed"] and result["scientific_comparison_count"] > 30
    assert result["artifact_equality"] and result["cache_pair_verified"]
    assert result["runs"][0]["final_generation"] == 3
    assert result["runs"][0]["profile_classification"] == "strict_nuisance_convergence"
    assert result["accepted_covariance"] is False
    assert result["whole_fit_convergence_established"] is False
    assert result["removed_fields"]["nuisance_line_search.trials[*]"] == list(check.STRIPPED_TRIAL_FIELDS)


def test_row_compression_does_not_change_payload_comparison(tmp_path):
    off, on = pair(tmp_path)
    rows = on / "qr.1.rows.tsv"
    rows.with_suffix(rows.suffix + ".gz").write_bytes(gzip.compress(rows.read_bytes()))
    rows.unlink()
    assert check.compare(off, on)["passed"]


@pytest.mark.parametrize("suffix,key,value", [
    ("profile.json", "nuisance_predicted_reduction", 1e-13),
    ("diagnostics.json", "source_rows", 4),
    ("factor.json", "orthogonal_energy", 4.),
    ("nuisance_line_search.json", "full_step_prediction", 6.),
    ("nuisance_line_search.json", "wall_seconds", 0.1),
])
def test_changed_scientific_fields_fail(tmp_path, suffix, key, value):
    off, on = pair(tmp_path)
    path = on / ("qr.1." + suffix)
    data = json.loads(path.read_text()); data[key] = value; write(path, data)
    result = check.compare(off, on)
    assert not result["passed"]
    assert any(issue.get("file") == path.name for issue in result["issues"])


@pytest.mark.parametrize("name", ["qr.3.R.bin", "qr.3.rhs.bin", "qr.2.parameters.tsv", "qr.1.receiver_times.tsv",
                                  "qr.1.rows.tsv", "qr.1.nuisance_coordinates.tsv", "qr.profile.json"])
def test_missing_required_scientific_evidence_fails_even_on_both_sides(tmp_path, name):
    off, on = pair(tmp_path)
    (off / name).unlink(); (on / name).unlink()
    assert not check.compare(off, on)["passed"]


def test_changed_binary_and_row_bytes_fail(tmp_path):
    off, on = pair(tmp_path)
    (on / "qr.3.R.bin").write_bytes(struct.pack("<QQd", 1, 1, 2.000000000000001))
    (on / "qr.1.rows.tsv").write_text("changed\n")
    assert not check.compare(off, on)["passed"]


def test_unmatched_scientific_artifact_fails(tmp_path):
    off, on = pair(tmp_path)
    write(on / "qr.4.profile.json", {"direct_cost": 2.})
    assert not check.compare(off, on)["passed"]


def test_fresh_factor_cannot_be_a_nuisance_update(tmp_path):
    off, on = pair(tmp_path)
    for root in (off, on):
        write(root / "qr.3.nuisance_line_search.json", {"accepted": True})
    result = check.compare(off, on)
    assert not result["passed"]
    assert any("separate fresh" in item["message"] for item in result["issues"])


def test_equal_relaxed_thresholds_are_not_accepted(tmp_path):
    off, on = pair(tmp_path)
    for root in (off, on):
        path = root / "qr.profile.json"; value = json.loads(path.read_text()); value["threshold_m"] = 1e-6; write(path, value)
    assert not check.compare(off, on)["passed"]


def test_floor_limited_equality_never_authorizes_covariance(tmp_path):
    off, on = pair(tmp_path, floor=True)
    result = check.compare(off, on)
    assert result["passed"]
    assert all(run["profile_classification"] == "floor_limited_progress_only" for run in result["runs"])
    assert result["accepted_covariance"] is False


def test_equal_invalid_floor_audits_do_not_pass(tmp_path):
    off, on = pair(tmp_path, floor=True)
    for root in (off, on):
        path = root / "qr.profile.json"; value = json.loads(path.read_text()); value["nuisance_floor_audit"] = []; write(path, value)
    assert not check.compare(off, on)["passed"]


def test_running_or_failed_execution_rejected(tmp_path):
    off, on = pair(tmp_path)
    path = on / "profile.execution.json"; value = json.loads(path.read_text()); value["returncode"] = None; write(path, value)
    assert not check.compare(off, on)["passed"]


def test_configuration_pin_and_native_identity_checked(tmp_path):
    off, on = pair(tmp_path)
    (on / "profile.xml").write_text("<modified/>")
    path = on / "profile.execution.json"; value = json.loads(path.read_text()); value["native_binary_sha256"] = "c" * 64; write(path, value)
    result = check.compare(off, on)
    assert not result["passed"]
    assert any("executable" in item["message"] for item in result["issues"])


def test_invalid_factor_payload_is_rejected_even_if_equal(tmp_path):
    off, on = pair(tmp_path)
    for root in (off, on):
        (root / "qr.3.R.bin").write_bytes(b"not a matrix")
    assert not check.compare(off, on)["passed"]


def test_duplicate_json_keys_not_silently_discarded(tmp_path):
    off, on = pair(tmp_path)
    (on / "qr.1.profile.json").write_text('{"direct_cost":3,"direct_cost":2}')
    assert not check.compare(off, on)["passed"]


@pytest.mark.parametrize("field,value", [("status", "running"), ("owned_process_group_cleaned", False),
    ("cache", 0), ("accumulate_epoch_observations", 1), ("freeze_sha256", "a" * 64),
    ("supervisor_sha256", "c" * 64)])
def test_actual_runner_metadata_negative_cases_fail(tmp_path, field, value):
    off, on = pair(tmp_path)
    path = on / "profile.execution.json"; data = json.loads(path.read_text()); data[field] = value; write(path, data)
    result = check.compare(off, on)
    assert result["artifact_equality"]
    assert not result["passed"] and not result["cache_pair_verified"]


def test_off_versus_off_is_not_a_cache_experiment(tmp_path):
    off, _ = pair(tmp_path)
    result = check.compare(off, off)
    assert result["artifact_equality"] and not result["cache_pair_verified"] and not result["passed"]


def test_missing_freeze_is_not_an_accepted_historical_cache_pair(tmp_path):
    off, on = pair(tmp_path)
    (tmp_path / "freeze.json").unlink()
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["cache_pair_verified"] and not result["passed"]


def test_missing_sidecar_cannot_prove_cache_was_exercised(tmp_path):
    off, on = pair(tmp_path)
    (on / "qr.2.nuisance_performance.json").unlink()
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["cache_pair_verified"] and not result["passed"]


def test_wrong_frozen_cpu_is_rejected(tmp_path):
    off, on = pair(tmp_path)
    path = on / "profile.execution.json"; data = json.loads(path.read_text()); data["command"][2] = "2"; write(path, data)
    assert not check.compare(off, on)["passed"]


def test_supervisor_cleanup_pin_cannot_hide_unclean_process_tree(tmp_path):
    off, on = pair(tmp_path)
    supervisor = on / "supervisor.json"; data = json.loads(supervisor.read_text()); data["cleanup"]["verified"] = False; write(supervisor, data)
    execution = on / "profile.execution.json"; data = json.loads(execution.read_text()); data["supervisor_sha256"] = hashlib.sha256(supervisor.read_bytes()).hexdigest(); write(execution, data)
    result = check.compare(off, on)
    assert not result["passed"] and not result["cache_pair_verified"]


def test_strict_profile_history_and_final_update_are_consistent(tmp_path):
    off, on = pair(tmp_path)
    for root in (off, on):
        path = root / "qr.profile.json"; data = json.loads(path.read_text()); data["maximum_update_m"] = 2e-9; write(path, data)
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["passed"]


def test_missing_run_reports_failure_instead_of_dropping_attempt(tmp_path):
    off, on = pair(tmp_path)
    result = check.compare(off, tmp_path / "missing")
    assert not result["passed"] and len(result["runs"]) == 2
    assert result["runs"][1]["issues"]
