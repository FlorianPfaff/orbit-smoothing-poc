"""Closed-fit diagnostics preserve missing evidence and failed trials."""
import importlib.util
import json
import hashlib
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_nuisance_profile.py"
spec = importlib.util.spec_from_file_location("nuisance_profile_analysis", SCRIPT)
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def fixture(tmp_path):
    root = tmp_path / "capture"
    terminal = write(tmp_path / "result-record.json", {"status": "timeout", "attempt_id": "example", "job_sha256": "a" * 64})
    supervisor = write(tmp_path / "supervisor.json", {"status": "timeout", "elapsed_seconds": 120., "cleanup": {"verified": True}})
    point = root / "point-001-initial"
    write(point / "profile.execution.json", {"elapsed_seconds": 90., "returncode": 0, "timed_out": False,
          "native_binary_sha256": "b" * 64, "config_sha256": "c" * 64})
    write(point / "qr.profile.json", {"nuisance_converged": True, "nuisance_floor_limited": False,
          "iterations": 1, "maximum_update_m": 1e-9, "threshold_m": 1e-8, "history": [{"maximum_update_m": 1e-9}]})
    write(point / "qr.1.nuisance_line_search.json", {"accepted": False, "stationary_without_update": True,
          "zero_update_replay": {"status": 0}, "trials": [{"status": 0, "child_user_seconds": 2., "child_system_seconds": .5}]})
    return root, terminal, supervisor, point


def test_timing_scopes_and_no_implied_whole_fit_convergence(tmp_path):
    root, terminal, supervisor, _ = fixture(tmp_path)
    value = analysis.analyze([root], terminal=terminal, supervisor=supervisor)
    assert value["profile_wall_seconds"]["recorded_sum"] == 90
    assert value["recorded_profile_wall_fraction_of_supervised_fit"] == .75
    assert value["trial_child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 2.5
    assert value["zero_replay_child_cpu"]["total_cpu_seconds"]["recorded_sum"] is None
    assert value["zero_replay_child_cpu"]["total_cpu_seconds"]["unknown_count"] == 1
    assert value["points"][0]["strict_nuisance_converged_reported"] is True
    assert value["whole_fit"]["converged_reported"] is None
    assert value["whole_fit"]["covariance_valid_reported"] is None
    assert value["phase_evidence"]["lm_trial_evidenced"] is False
    assert "does not prove" in value["phase_evidence"]["scope"]
    assert value["analyzer"]["sha256"] == hashlib.sha256(SCRIPT.read_bytes()).hexdigest()
    assert len(value["provenance"]) == 5


def test_incomplete_profile_and_missing_timing_remain_unknown(tmp_path):
    root, terminal, supervisor, _ = fixture(tmp_path)
    write(root / "point-002-repeat" / "closure.json", {"converged": True, "tighter": False})
    value = analysis.analyze([root], terminal=terminal, supervisor=supervisor)
    assert value["profile_wall_seconds"]["coverage"] == "partial"
    assert value["profile_wall_seconds"]["unknown_count"] == 1
    second = value["points"][1]
    assert second["closure_converged_reported"] is True
    assert second["profile_wall_seconds"] is None
    assert second["strict_nuisance_converged_reported"] is None
    assert second["trial_child_cpu"]["total_cpu_seconds"]["recorded_sum"] is None


def test_failed_children_and_replay_cpu_are_kept_separate(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    write(point / "qr.2.nuisance_line_search.json", {"accepted": False, "floor_rejection": "bad_probe",
        "zero_update_replay": {"status": 7, "child_user_seconds": 3., "child_system_seconds": .2},
        "trials": [{"status": 9, "alpha": .5, "error": "probe failed", "child_user_seconds": 1.},
                   {"status": 0, "child_user_seconds": 4., "child_system_seconds": .1}]})
    value = analysis.analyze([root], terminal=terminal)
    assert value["trial_child_cpu"]["user_seconds"]["recorded_sum"] == 7.
    assert value["trial_child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 6.6
    assert value["trial_child_cpu"]["total_cpu_seconds"]["coverage"] == "partial"
    assert value["zero_replay_child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 3.2
    outcome = value["points"][0]["line_search_outcomes"][1]
    assert outcome["failed_trials"][0]["error"] == "probe failed"
    assert outcome["zero_replay_status"] == 7
    assert outcome["floor_rejection"] == "bad_probe"
    assert value["points"][0]["search_receipts_match_reported_iterations"] is False


def test_identical_capture_copies_do_not_double_count(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    copied = tmp_path / "copy" / point.name
    write(copied / "profile.execution.json", json.loads((point / "profile.execution.json").read_text()))
    value = analysis.analyze([root, copied.parent], terminal=terminal)
    assert value["profile_wall_seconds"]["recorded_sum"] == 90.
    assert len(value["provenance"]) == 5  # Four unique payloads plus copied execution.
    write(copied / "profile.execution.json", {"elapsed_seconds": 91.})
    with pytest.raises(ValueError, match="Conflicting"):
        analysis.analyze([root, copied.parent], terminal=terminal)


@pytest.mark.parametrize("status", ["running", "pending", "starting", None, "invented"])
def test_live_or_unknown_terminal_status_rejected(tmp_path, status):
    root, terminal, _, _ = fixture(tmp_path)
    write(terminal, {"status": status})
    with pytest.raises(ValueError, match="terminal"):
        analysis.analyze([root], terminal=terminal)


def test_supervisor_mismatch_rejected(tmp_path):
    root, terminal, supervisor, _ = fixture(tmp_path)
    write(supervisor, {"status": "complete"})
    with pytest.raises(ValueError, match="statuses disagree"):
        analysis.analyze([root], terminal=terminal, supervisor=supervisor)


def test_invalid_receipt_is_retained_with_hash_and_error(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    (point / "qr.profile.json").write_text("{unfinished")
    value = analysis.analyze([root], terminal=terminal)
    assert value["points"][0]["strict_nuisance_converged_reported"] is None
    assert len(value["input_issues"]) == 1
    assert value["input_issues"][0]["sha256"]


def test_manifest_hashes_are_verified(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    path = point / "qr.profile.json"
    row = {"relative": str(path.relative_to(root)), "bytes": path.stat().st_size,
           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    manifest = write(root / "manifest.json", {"files": [row]})
    value = analysis.analyze([root], terminal=terminal, manifests=[manifest])
    assert value["verified_capture_manifests"][0]["verified_files"] == 1
    path.write_text("{}")
    with pytest.raises(ValueError, match="identity mismatch"):
        analysis.analyze([root], terminal=terminal, manifests=[manifest])


def test_manifest_escape_rejected(tmp_path):
    root, terminal, _, _ = fixture(tmp_path)
    manifest = write(root / "manifest.json", {"files": [{"relative": "../outside"}]})
    with pytest.raises(ValueError, match="escapes"):
        analysis.analyze([root], terminal=terminal, manifests=[manifest])


@pytest.mark.parametrize("number", [True, -1., float("inf"), float("nan"), "3", None])
def test_invalid_timing_is_unknown(number):
    result = analysis.metric([{"elapsed_seconds": number}], "elapsed_seconds")
    assert result["recorded_sum"] is None and result["unknown_count"] == 1


def test_lm_attempt_evidence_is_reported_without_claiming_success(tmp_path):
    root, terminal, _, _ = fixture(tmp_path)
    write(root / "iterations.json", {"trial_evaluations": 1})
    write(root / "point-004-trial-001" / "closure.json", {"converged": False})
    value = analysis.analyze([root], terminal=terminal)
    assert value["phase_evidence"]["lm_trial_evidenced"] is True
    assert value["whole_fit"]["status"] == "timeout"


def test_execution_identity_is_checked_against_terminal(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    execution_path = point / "profile.execution.json"
    execution = json.loads(execution_path.read_text())
    execution["command"] = ["/native", "/run/other/" + point.name + "/profile.xml"]
    write(execution_path, execution)
    with pytest.raises(ValueError, match="attempt identities"):
        analysis.analyze([root], terminal=terminal)
    execution["command"][1] = "/run/example/" + point.name + "/profile.xml"
    write(execution_path, execution)
    value = analysis.analyze([root], terminal=terminal)
    assert value["terminal_to_execution_identity"] == "matches"
    execution["command"][1] = "/run/example/point-999-else/profile.xml"
    write(execution_path, execution)
    with pytest.raises(ValueError, match="captured point"):
        analysis.analyze([root], terminal=terminal)


def test_nonfinite_json_is_reported_as_invalid_evidence(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    (point / "qr.profile.json").write_text('{"maximum_update_m":NaN}')
    value = analysis.analyze([root], terminal=terminal)
    assert value["points"][0]["strict_nuisance_converged_reported"] is None
    assert "Nonfinite" in value["input_issues"][0]["error"]
    json.dumps(value, allow_nan=False)


def test_output_never_replaces_existing_report(tmp_path, monkeypatch):
    root, terminal, _, _ = fixture(tmp_path)
    output = tmp_path / "analysis.json"
    output.write_text("preserved")
    monkeypatch.setattr("sys.argv", [str(SCRIPT), str(root), "--terminal", str(terminal), "--output", str(output)])
    with pytest.raises(FileExistsError):
        analysis.main()
    assert output.read_text() == "preserved"


def test_noninteger_trial_status_is_not_a_success(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    write(point / "qr.2.nuisance_line_search.json", {"trials": [{"status": False}]})
    value = analysis.analyze([root], terminal=terminal)
    assert value["points"][0]["line_search_outcomes"][1]["failed_trials"][0]["status"] is False


def performance_child(*, user=2., system=.5, status=0):
    return {"status": status, "wall_seconds": 3., "child_user_seconds": user,
            "child_system_seconds": system, "peak_child_rss_bytes": 100,
            "row_build": {"available": True, "completed": status == 0, "cost_only": True,
                          "build_wall_seconds": 2., "observation_design_wall_seconds": .75,
                          "observation_design_calls": 4}}


def sidecar():
    return {"schema": "orbit-poc-nuisance-performance-v1",
            "parent_row_build": {"available": True, "completed": True, "cost_only": False,
                                 "build_wall_seconds": 5., "observation_design_wall_seconds": 1., "observation_design_calls": 4},
            "zero_update_replay": performance_child(user=3., system=.2),
            "ordinary_trials": [performance_child()],
            "arithmetic_audits": [performance_child(user=4., system=.1, status=9)],
            "probe_rounds": [[performance_child(user=5., system=.3)],
                             [performance_child(user=6., system=.4)]]}


def test_sidecars_supplement_missing_cpu_without_double_counting(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    search_path = point / "qr.1.nuisance_line_search.json"
    search = json.loads(search_path.read_text())
    search.update(completed_probe_rounds=2, nuisance_floor_audit=[
        {"kind": "equivalent_arithmetic", "status": 9},
        {"kind": "two_amplitude_symmetric_nuisance_probe", "probe_history": [
            {"probes": [{"status": 0}]}, {"probes": [{"status": 0}]}]}])
    write(search_path, search)
    write(point / "qr.1.nuisance_performance.json", sidecar())
    value = analysis.analyze([root], terminal=terminal)
    assert value["trial_child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 2.5
    assert value["zero_replay_child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 3.2
    performance = value["performance"]
    assert performance["sidecar_count"] == performance["search_record_count"] == 1
    assert performance["parent_row_build"]["build_wall_seconds"]["recorded_sum"] == 5.
    assert performance["parent_row_build"]["observation_design_wall_seconds"]["recorded_sum"] == 1.
    groups = performance["child_categories"]
    assert groups["ordinary_trials"]["child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 2.5
    assert groups["probe_rounds"]["child_cpu"]["total_cpu_seconds"]["recorded_sum"] == 11.7
    assert groups["arithmetic_audits"]["failed_or_unknown_status_count"] == 1
    assert groups["arithmetic_audits"]["row_build"]["incomplete_count"] == 1
    assert "included" in performance["parent_row_build"]["scope"]


def test_historical_sidecar_metrics_stay_unknown(tmp_path):
    root, terminal, _, _ = fixture(tmp_path)
    value = analysis.analyze([root], terminal=terminal)
    assert value["performance"]["sidecar_count"] == 0
    assert value["performance"]["parent_row_build"]["build_wall_seconds"]["recorded_sum"] is None
    assert value["performance"]["child_categories"]["zero_update_replay"]["wall_seconds"]["unknown_count"] == 1


@pytest.mark.parametrize("change", ["schema", "count", "status", "timing", "row_build"])
def test_mismatched_sidecar_cannot_relabel_existing_measurements(tmp_path, change):
    root, terminal, _, point = fixture(tmp_path)
    value = sidecar()
    if change == "schema":
        value["schema"] = "unknown-v0"
    elif change == "count":
        value["ordinary_trials"] = []
    elif change == "status":
        value["ordinary_trials"][0]["status"] = 1
    elif change == "timing":
        value["ordinary_trials"][0]["child_user_seconds"] = 999.
    else:
        value["zero_update_replay"].pop("row_build")
    write(point / "qr.1.nuisance_performance.json", value)
    with pytest.raises(ValueError):
        analysis.analyze([root], terminal=terminal)


def test_orphan_sidecar_is_retained_as_an_issue_not_counted(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    write(point / "qr.9.nuisance_performance.json", sidecar())
    value = analysis.analyze([root], terminal=terminal)
    assert value["performance"]["sidecar_count"] == 0
    assert "Orphan" in value["input_issues"][0]["error"]


@pytest.mark.parametrize("group", ["arithmetic", "probe", "probe_status"])
def test_extra_or_misattributed_audit_child_timings_rejected(tmp_path, group):
    root, terminal, _, point = fixture(tmp_path)
    value = sidecar()
    value["arithmetic_audits"] = []
    value["probe_rounds"] = []
    if group == "arithmetic":
        value["arithmetic_audits"] = [performance_child()]
    else:
        value["probe_rounds"] = [[performance_child(status=7)]]
        if group == "probe_status":
            search_path = point / "qr.1.nuisance_line_search.json"
            search = json.loads(search_path.read_text())
            search.update(completed_probe_rounds=1, nuisance_floor_audit=[
                {"kind": "two_amplitude_symmetric_nuisance_probe", "probe_history": [{"probes": [{"status": 0}]}]}])
            write(search_path, search)
    write(point / "qr.1.nuisance_performance.json", value)
    with pytest.raises(ValueError, match="canonical"):
        analysis.analyze([root], terminal=terminal)


def test_explicit_running_capture_rejected_even_with_old_terminal(tmp_path):
    root, terminal, _, _ = fixture(tmp_path)
    write(root / "supervisor.json", {"status": "running"})
    with pytest.raises(ValueError, match="live"):
        analysis.analyze([root], terminal=terminal)


def test_terminal_pinned_full_result_is_checked(tmp_path):
    root, terminal, _, _ = fixture(tmp_path)
    result = write(root / "result.json", {"status": "timeout"})
    data = json.loads(terminal.read_text())
    data["result"] = {"sha256": hashlib.sha256(result.read_bytes()).hexdigest()}
    write(terminal, data)
    analysis.analyze([root], terminal=terminal)
    write(result, {"status": "timeout", "error": "different attempt result"})
    with pytest.raises(ValueError, match="result pin"):
        analysis.analyze([root], terminal=terminal)


def test_receipts_changed_during_analysis_are_rejected(tmp_path, monkeypatch):
    root, terminal, _, point = fixture(tmp_path)
    original = analysis.artifact
    calls = 0

    def changing(path):
        nonlocal calls
        pin, data = original(path)
        if Path(path).name == "qr.profile.json":
            calls += 1
            if calls == 2:
                (point / "qr.profile.json").write_text("{}")
        return pin, data

    monkeypatch.setattr(analysis, "artifact", changing)
    with pytest.raises(ValueError, match="changed during"):
        analysis.analyze([root], terminal=terminal)


def test_overflow_json_number_is_invalid_evidence(tmp_path):
    root, terminal, _, point = fixture(tmp_path)
    (point / "qr.profile.json").write_text('{"maximum_update_m":1e999}')
    value = analysis.analyze([root], terminal=terminal)
    assert "Nonfinite" in value["input_issues"][0]["error"]
    json.dumps(value, allow_nan=False)


def test_successful_worker_can_report_numerical_failure(tmp_path):
    root, terminal, supervisor, _ = fixture(tmp_path)
    write(terminal, {"status": "nuisance_failure"})
    write(supervisor, {"status": "complete", "returncode": 0})
    value = analysis.analyze([root], terminal=terminal, supervisor=supervisor)
    assert value["whole_fit"]["status"] == "nuisance_failure"
    assert value["whole_fit"]["supervisor_process_status"] == "complete"
