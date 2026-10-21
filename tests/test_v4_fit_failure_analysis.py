"""Evidence classification must not turn execution failure into scientific acceptance."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("v4_failure_analysis", ROOT / "scripts/analyze_v4_fit_failures.py")
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)
MANIFEST = "a" * 64
OPTIMIZER = ROOT / "src/orbit_poc/numerics/optimizer.py"


def pin(aid, name, content, point=None):
    path = Path("/frozen/attempts") / aid
    if point:
        path /= point
    raw = json.dumps(content).encode()
    return {"path": str(path / name), "bytes": len(raw), "sha256": analysis.digest(raw), "content": content}


def point(aid, name="point-001-initial", completed=False, entered=True):
    docs = {}
    files = [{"name": "fixed_force.txt", "bytes": 5}]
    logs = {}
    if entered:
        files.append({"name": "profile.log", "bytes": 100})
        logs["profile.log"] = {"path": f"/frozen/attempts/{aid}/{name}/profile.log", "bytes": 100,
                               "head": "", "tail": "accumulate normals"}
        docs["closure.json"] = pin(aid, "closure.json", {"converged": True}, name)
    if completed:
        docs["profile.execution.json"] = pin(aid, "profile.execution.json", {
            "returncode": 0, "timed_out": False, "elapsed_seconds": 3100}, name)
        docs["qr.profile.json"] = pin(aid, "qr.profile.json", {
            "nuisance_converged": True, "nuisance_floor_limited": False, "iterations": 11}, name)
    return {"point": name, "files": files, "json": docs, "logs": logs}


def case(aid="case--dense_corrected", status="timeout", points=None):
    points = [point(aid)] if points is None else points
    supervisor = {"status": "complete" if status in ("complete", "failed") else status,
                  "returncode": 0 if status in ("complete", "failed") else -15,
                  "elapsed_seconds": 7200, "peak_process_tree_rss_bytes": 900000000,
                  "owned_process_group_cleaned": True, "cleanup": {"verified": True, "remaining": []}}
    result = {"status": status, "segmented_manifest_hash": MANIFEST,
              "segmented_profile": "dense_corrected", "job_sha256": "b" * 64,
              "converged": False, "covariance_valid": False, "harness_execution": supervisor}
    rp = pin(aid, "result.json", result)
    record = {"attempt_id": aid, "status": status, "job_sha256": result["job_sha256"],
              "result": {k: rp[k] for k in ("path", "sha256")}}
    term = {"attempt": {"attempt_id": aid, "case_id": "case", "profile": "dense_corrected", "order": 0},
            "result": rp, "record": pin(aid, "result-record.json", record),
            "supervisor.json": pin(aid, "supervisor.json", supervisor),
            "top_entries": [p["point"] for p in points]}
    return term, {"attempt_id": aid, "points": points}


def search_record(aid="case--dense_corrected", **overrides):
    content = {"schema": "orbit-poc-native-nuisance-line-search-v1",
               "zero_update_replay": {"status": 1, "cost": 0},
               "trials": [{"status": 1, "error": analysis.CHILD_TIMEOUT, "cost": 0}]}
    content.update(overrides)
    name = "qr.1.nuisance_line_search.json"
    return {"attempt_id": aid, "point": "point-001-initial", "name": name,
            **pin(aid, name, content, "point-001-initial")}


def write_inputs(tmp_path, term=None, pts=None, records=None, memory=None):
    if term is None:
        term, pts = case()
    docs = [{"schema": analysis.SCHEMAS["terminal"], "captured_at": "2026-10-21T01:00:00Z",
             "manifest_hash": MANIFEST, "attempts": [term]},
            {"schema": analysis.SCHEMAS["points"], "captured_at": "2026-10-21T01:01:00Z",
             "manifest_hash": MANIFEST, "attempts": [pts] if pts else []},
            {"schema": analysis.SCHEMAS["search"], "captured_at": "2026-10-21T01:02:00Z",
             "records": records or []},
            {"schema": analysis.SCHEMAS["memory"], "captured_at": "2026-10-21T01:03:00Z",
             "attempts": memory or []}]
    paths = []
    for name, doc in zip(("terminal", "points", "search", "memory"), docs):
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(doc))
        paths.append(path)
    return paths


def run(paths):
    return analysis.analyze(*paths, OPTIMIZER)


def modify(path, fn):
    doc = json.loads(path.read_text())
    fn(doc)
    path.write_text(json.dumps(doc))


def test_initial_timeout_is_not_nuisance_nonconvergence(tmp_path):
    report = run(write_inputs(tmp_path))
    row = report["attempts"][0]
    assert row["status"] == "timeout"
    assert row["last_observed_stage"] == "native_profile_entered_without_success_record"
    assert row["before_first_optimizer_trial"] is True
    assert row["strict_completed_native_profiles"] == 0
    assert report["fit_covariance_authorized"] is False
    assert report["release_ready"] is False


def test_completed_baselines_are_not_completed_fit(tmp_path):
    aid = "case--dense_corrected"
    points = [point(aid, "point-001-initial", True), point(aid, "point-002-repeat", True),
              point(aid, "point-003-closure-refinement")]
    row = run(write_inputs(tmp_path, *case(aid, points=points)))["attempts"][0]
    assert row["strict_completed_native_profiles"] == 2
    assert row["completed_native_profile_seconds"] == 6200
    assert row["last_point"] == "point-003-closure-refinement"
    assert row["status"] == "timeout"
    assert row["before_first_optimizer_trial"] is True


def test_failed_replay_placeholder_is_not_measured_objective_change(tmp_path):
    term, pts = case(status="failed")
    pts["points"][0]["logs"]["profile.log"]["tail"] = analysis.REPLAY_GUARD
    row = run(write_inputs(tmp_path, term, pts, [search_record()]))["attempts"][0]
    assert row["supervisor_status"] == "complete" and row["status"] == "failed"
    assert row["points"][0]["zero_replay_guard_in_captured_tail"] is True
    s = row["nuisance_search"]
    assert s["failed_zero_update_replays"] == 1
    assert s["explicit_300s_trial_timeouts"] == 1
    assert s["zero_update_replay_timeout_explicit"] == 0
    assert "objective_change" not in s


@pytest.mark.parametrize("entered,expected", [(True, "native_profile_entered_without_success_record"),
    (False, "point_created_closure_progress_unknown")])
def test_memory_stage_is_separate_from_timeout(tmp_path, entered, expected):
    aid = "case--dense_corrected"
    row = run(write_inputs(tmp_path, *case(aid, "memory_limit", [point(aid, entered=entered)])))["attempts"][0]
    assert row["status"] == "memory_limit" and row["last_observed_stage"] == expected
    assert row["before_first_optimizer_trial"] is True


def test_nested_closure_progress_overrides_missing_top_level_receipt(tmp_path):
    aid = "case--dense_corrected"
    term, pts = case(aid, "memory_limit", [point(aid, entered=False)])
    log = f"Config file: /frozen/attempts/{aid}/point-001-initial/closure-01/propagate.xml\n" \
          "--- PreprocessingVariationalEquation ---\nwrite variational equation to file\n" \
          "--- OrbitPocEvaluateVariational ---\n"
    memory = [{"attempt_id": aid, "directories": [{"name": "closure-01", "files": [],
               "logs": {"propagate.log": {"head": log, "tail": log, "bytes": len(log)}}}]}]
    row = run(write_inputs(tmp_path, term, pts, memory=memory))["attempts"][0]
    assert row["last_observed_stage"] == "closure_orbit_evaluation_entered_without_completion"
    assert row["nested_closure_evidence"][0]["variational_archive_write_observed"] is True
    assert row["nested_closure_evidence"][0]["native_execution_completed"] is False


def test_harness_metadata_additions_preserve_exact_supervisor_fields(tmp_path):
    term, pts = case()
    harness = copy.deepcopy(term["supervisor.json"]["content"])
    harness.update(runtime={"native": "pinned"}, scope="one attempt",
                   supervisor_receipt={k: term["supervisor.json"][k] for k in ("path", "sha256")})
    term["result"]["content"]["harness_execution"] = harness
    assert run(write_inputs(tmp_path, term, pts))["attempts"][0]["cleanup_verified_in_capture"]
    harness["elapsed_seconds"] += 1
    with pytest.raises(ValueError, match="Harness execution"):
        run(write_inputs(tmp_path, term, pts))


def test_missing_point_detail_remains_unknown(tmp_path):
    term, _ = case()
    row = run(write_inputs(tmp_path, term, None))["attempts"][0]
    assert row["before_first_optimizer_trial"] is None
    assert row["last_observed_stage"] == "unknown_incomplete_point_capture"
    assert row["missing_evidence"]


def test_later_trial_not_described_as_pretrial(tmp_path):
    aid = "case--dense_corrected"
    row = run(write_inputs(tmp_path, *case(aid, points=[point(aid, "point-004-trial")])))["attempts"][0]
    assert row["before_first_optimizer_trial"] is False


def test_floor_limited_success_is_not_strict(tmp_path):
    aid = "case--dense_corrected"
    p = point(aid, completed=True)
    p["json"]["qr.profile.json"]["content"]["nuisance_floor_limited"] = True
    row = run(write_inputs(tmp_path, *case(aid, points=[p])))["attempts"][0]
    assert row["completed_native_profiles"] == 1
    assert row["strict_completed_native_profiles"] == 0


def test_cleanup_requires_positive_certificate(tmp_path):
    term, pts = case()
    term["supervisor.json"]["content"]["cleanup"]["remaining"] = [123]
    row = run(write_inputs(tmp_path, term, pts))["attempts"][0]
    assert row["cleanup_verified_in_capture"] is False


def test_manifest_mismatch_rejected(tmp_path):
    paths = write_inputs(tmp_path)
    modify(paths[1], lambda j: j.update(manifest_hash="c" * 64))
    with pytest.raises(ValueError, match="manifest mismatch"):
        run(paths)


@pytest.mark.parametrize("which", [0, 1, 2])
def test_duplicate_identities_rejected(tmp_path, which):
    paths = write_inputs(tmp_path, records=[search_record()])
    key = "records" if which == 2 else "attempts"
    modify(paths[which], lambda j: j[key].append(copy.deepcopy(j[key][0])))
    with pytest.raises(ValueError, match="Duplicate"):
        run(paths)


def test_cross_attempt_pin_substitution_rejected(tmp_path):
    term, pts = case()
    term["supervisor.json"]["path"] = "/frozen/attempts/other/supervisor.json"
    with pytest.raises(ValueError, match="Cross-attempt"):
        run(write_inputs(tmp_path, term, pts))


def test_cross_point_search_substitution_rejected(tmp_path):
    rec = search_record()
    rec["path"] = rec["path"].replace("point-001-initial", "point-002-repeat")
    with pytest.raises(ValueError, match="Cross-point"):
        run(write_inputs(tmp_path, records=[rec]))


def test_supervisor_status_cannot_override_fit_failure(tmp_path):
    term, pts = case(status="failed")
    term["supervisor.json"]["content"]["status"] = "timeout"
    with pytest.raises(ValueError, match="Supervisor/result"):
        run(write_inputs(tmp_path, term, pts))


def test_result_pin_binding_checked(tmp_path):
    term, pts = case()
    term["record"]["content"]["result"]["sha256"] = "d" * 64
    with pytest.raises(ValueError, match="result pin mismatch"):
        run(write_inputs(tmp_path, term, pts))


@pytest.mark.parametrize("token", ["NaN", "Infinity", "1e999"])
def test_nonfinite_capture_rejected(tmp_path, token):
    paths = write_inputs(tmp_path)
    paths[0].write_text(paths[0].read_text().replace('"order": 0', '"order": ' + token))
    with pytest.raises(ValueError):
        run(paths)


def test_duplicate_json_key_rejected(tmp_path):
    paths = write_inputs(tmp_path)
    paths[0].write_text(paths[0].read_text().replace('"order": 0', '"order": 0, "order": 1'))
    with pytest.raises(ValueError, match="Duplicate JSON key"):
        run(paths)


def test_optimizer_order_is_checked(tmp_path):
    paths = write_inputs(tmp_path)
    source = tmp_path / "optimizer.py"
    source.write_text(OPTIMIZER.read_text().replace('model.evaluate(initial, "initial")',
                                                   'model.evaluate(initial, "other")'))
    with pytest.raises(ValueError, match="ordering"):
        analysis.analyze(*paths, source)


def test_capture_bytes_are_hashed_and_original_pins_preserved(tmp_path):
    paths = write_inputs(tmp_path)
    report = run(paths)
    assert report["provenance"]["captures"]["terminal"]["sha256"] == analysis.digest(paths[0].read_bytes())
    row = report["attempts"][0]
    original = json.loads(paths[0].read_text())["attempts"][0]["result"]
    assert row["record_pins"]["result"]["sha256"] == original["sha256"]
    assert "captured_content_sha256" in row["record_pins"]["result"]
    assert "collector claims" in report["provenance"]["pin_scope"]


def test_html_escapes_captured_text(tmp_path):
    aid = '<img src=x onerror=alert(1)>'
    report = run(write_inputs(tmp_path, *case(aid)))
    html = analysis.render_html(report)
    assert aid not in html and "&lt;img" in html
    assert 'href="report.json"' in html


def test_cli_fresh_output_only_and_does_not_mutate_inputs(tmp_path, capsys):
    paths = write_inputs(tmp_path)
    before = [p.read_bytes() for p in paths]
    output = tmp_path / "report"
    args = ["--terminal", str(paths[0]), "--points", str(paths[1]), "--search", str(paths[2]),
            "--memory", str(paths[3]),
            "--optimizer-source", str(OPTIMIZER), "--output", str(output)]
    assert analysis.main(args) == 0
    saved = (output / "report.json").read_bytes()
    assert (output / "index.html").is_file()
    with pytest.raises(FileExistsError):
        analysis.main(args)
    assert (output / "report.json").read_bytes() == saved
    assert before == [p.read_bytes() for p in paths]
