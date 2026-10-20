"""Injected completion-helper controls; no real checker or native fit is run."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/complete_nuisance_wholefit.py"
SPEC = importlib.util.spec_from_file_location("completion", SCRIPT)
completion = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(completion)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def pin(path):
    return {"path": str(path), "sha256": completion.digest(path)}


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root, source, tools = (tmp_path / name for name in ("experiment", "source", "tools"))
    for directory in (root, source, tools):
        directory.mkdir()
    python = tools / "python"
    python.write_text("pinned interpreter fixture")
    checker = tools / "analyze_nuisance_wholefit.py"
    checker.write_text("pinned checker fixture")
    deps = [tools / name for name in ("analyze_nuisance_profile.py", "check_nuisance_performance_pair.py")]
    for dep in deps:
        dep.write_text("pinned dependency fixture")
    freeze = {"schema": "orbit-poc-nuisance-wholefit-freeze-v1", "root": str(root), "boot_id": "boot",
              "source_root": str(source), "python": pin(python), "worker": {"path": str(source / "worker.py")},
              "pinned_files": [], "environment": {"LD_LIBRARY_PATH": "/pinned/libraries"},
              "jobs": [{"name": "cache1", "cache": 1, "request": {"sha256": "1" * 64}},
                       {"name": "cache0", "cache": 0, "request": {"sha256": "0" * 64}}]}
    write(root / "freeze.json", freeze)
    launch = {"schema": "orbit-poc-wholefit-controller-launch-v1", "pid": 1234, "start_ticks": 123,
              "argv": ["python", "controller"], "boot_id": "boot",
              "freeze_sha256": completion.digest(root / "freeze.json")}
    write(root / "controller-launch.json", launch)
    plan = {"schema": completion.SCHEMA, "freeze": pin(root / "freeze.json"),
            "controller_launch": pin(root / "controller-launch.json"), "helper": pin(SCRIPT),
            "checker": pin(checker), "python": pin(python), "dependencies": [pin(p) for p in deps],
            "annotations": [],
            "report_directory": str(tmp_path / "report"), "cpu": 4, "poll_seconds": .1, "wait_seconds": 1}
    path = tmp_path / "plan.json"
    write(path, plan)
    now = [0.]
    monkeypatch.setattr(completion, "boot_id", lambda: "boot")
    monkeypatch.setattr(completion, "process", lambda pid: None)
    monkeypatch.setattr(completion.os, "sched_setaffinity", lambda pid, cpus: None)
    monkeypatch.setattr(completion.os, "sched_getaffinity", lambda pid: {4})
    monkeypatch.setattr(completion.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(completion.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    calls = []
    def forbidden(*args, **kwargs):
        raise AssertionError("No real subprocess may run in injected tests")
    monkeypatch.setattr(completion.subprocess, "run", forbidden)
    return SimpleNamespace(root=root, source=source, tools=tools, plan=plan, path=path, freeze=freeze,
                           launch=launch, deps=deps, now=now, calls=calls, monkeypatch=monkeypatch)


def run(f):
    return completion.run(f.path, completion.digest(f.path))


def alive(f, **updates):
    value = {"pid": 1234, "start_ticks": 123, "state": "S", "argv": f.launch["argv"]}
    value.update(updates)
    f.monkeypatch.setattr(completion, "process", lambda pid: value)


def close(f, name="cache1", **changes):
    directory = f.root / name
    directory.mkdir(exist_ok=True)
    job = next(j for j in f.freeze["jobs"] if j["name"] == name)
    sha = f.plan["freeze"]["sha256"]
    argv = [f.freeze["python"]["path"], "-s", "-B", f.freeze["worker"]["path"], str(f.source),
            str(directory / "request.json"), str(directory / "worker-result.json"), str(job["cache"]),
            str(f.root / "freeze.json"), sha]
    write(directory / "supervisor.plan.json", {"boot_id": "boot", "argv": argv, "working_directory": str(directory)})
    supervisor = {"status": "timeout", "boot_id": "boot", "argv": argv,
                  "owned_process_group_cleaned": True, "cleanup": {"verified": True},
                  "plan_sha256": completion.digest(directory / "supervisor.plan.json")}
    supervisor.update(changes)
    write(directory / "supervisor.json", supervisor)
    write(directory / "post-input-check.json", {"verified": True, "freeze_sha256": sha, "pinned_file_count": 0})
    write(directory / "result.json", {"harness_execution": supervisor, "freeze_sha256": sha,
                                      "request_sha256": job["request"]["sha256"]})


def terminal(f, stopped=False):
    names = ["cache1"] if stopped else ["cache1", "cache0"]
    value = {"outcomes": [{"name": n, "result_sha256": "a" * 64} for n in names],
             "all_attempts_executed": not stopped}
    if not stopped:
        value["freeze_sha256"] = f.plan["freeze"]["sha256"]
    write(f.root / ("execution-stopped.json" if stopped else "execution-complete.json"), value)


def checker(f, status="valid", outcomes=("timeout", "timeout"), callback=None, pair=False):
    result = {"schema": "orbit-poc-nuisance-wholefit-analysis-v1", "analysis_status": status,
              "whole_fit_complete_pair": pair, "scientific_equivalence": {"status": "passed" if pair else "not_evaluable"},
              "issues": [] if status == "valid" else ["injected issue"],
              "runs": [{"name": n, "cache": c, "outcome": outcome, "analysis_status": status,
                        "scientific_complete": pair, "accepted_covariance": pair, "wall_seconds": 7200.}
                       for (n, c), outcome in zip((("cache1", 1), ("cache0", 0)), outcomes)]}
    def fake(argv, **kwargs):
        f.calls.append((argv, kwargs))
        assert argv[:4] == [f.plan["python"]["path"], "-s", "-B", f.plan["checker"]["path"]]
        assert argv[4] == str(f.root) and argv[5] == "--output"
        assert all(kwargs["env"][key] == "1" for key in completion.THREADS)
        assert kwargs["env"]["LD_LIBRARY_PATH"] == "/pinned/libraries"
        assert not any(k.startswith("ORBIT_POC_") for k in kwargs["env"])
        assert "PYTHONPATH" not in kwargs["env"] and "PYTHONHOME" not in kwargs["env"]
        write(Path(argv[-1]), result)
        if callback:
            callback()
        return SimpleNamespace(returncode=0 if status == "valid" else 2)
    f.monkeypatch.setattr(completion.subprocess, "run", fake)
    return result


def clock_annotation(f, **changes):
    snapshot = f.root.parent / "supervisor-snapshot.json"
    write(snapshot, {"schema": "orbit-poc-segmented-supervision-v1", "boot_id": "boot",
                     "elapsed_seconds": 1390., "supervisor": {"parent": f.launch["pid"]}})
    observation = f.root.parent / "clock-observation.json"
    value = {"schema": "orbit-poc-clock-discrepancy-observation-v1", "boot_id": "boot",
             "controller_pid": f.launch["pid"], "controller_start_ticks": f.launch["start_ticks"],
             "controller_launch_sha256": f.plan["controller_launch"]["sha256"],
             "supervisor_capture_sha256": completion.digest(snapshot), "supervisor_elapsed_seconds": 1390.,
             "utc_since_controller_launch_seconds": 2620., "difference_seconds": 1230.}
    value.update(changes)
    write(observation, value)
    f.plan["annotations"] = [{"kind": "clock_discrepancy", "observation": pin(observation),
                              "supervisor_snapshot": pin(snapshot)}]
    write(f.path, f.plan)
    return observation, snapshot


def test_two_timeout_receipts_are_not_a_successful_fix(fixture):
    f = fixture
    alive(f)
    close(f); close(f, "cache0"); terminal(f)
    expected = checker(f)
    result = run(f)
    assert len(f.calls) == 1 and result["analysis_status"] == "valid"
    assert result["scientific_equivalence"] == expected["scientific_equivalence"]
    assert not result["whole_fit_complete_pair"]
    assert all(not r["accepted_covariance"] and r["outcome"] == "timeout" for r in result["attempts"])
    text = (Path(f.plan["report_directory"]) / "index.html").read_text()
    assert "Two valid timeouts remain two failed fits" in text
    assert "not an exclusive machine reservation" in text


def test_true_checker_decisions_are_carried_without_reclassification(fixture):
    f = fixture
    close(f); close(f, "cache0"); terminal(f)
    expected = checker(f, pair=True, outcomes=("complete", "complete"))
    result = run(f)
    assert result["scientific_equivalence"] == expected["scientific_equivalence"]
    assert result["whole_fit_complete_pair"] is True


def test_clock_discrepancy_retained_separately_from_scientific_result(fixture):
    f = fixture
    observation, snapshot = clock_annotation(f)
    close(f); close(f, "cache0"); terminal(f)
    expected = checker(f, pair=True, outcomes=("complete", "complete"))
    result = run(f)
    assert result["scientific_equivalence"] == expected["scientific_equivalence"]
    assert result["whole_fit_complete_pair"] is True and result["timing_comparison"] == "compromised"
    assert result["utc_two_hour_budget_compliance"] == "not_established"
    assert result["release_authority"] is False and result["speedup_claim"] is None
    report = Path(f.plan["report_directory"])
    assert (report / "annotation-0-observation.json").read_bytes() == observation.read_bytes()
    assert (report / "annotation-0-supervisor_snapshot.json").read_bytes() == snapshot.read_bytes()
    page = (report / "index.html").read_text()
    assert "Timing comparison is compromised" in page and "monotonic 7200-second limit" in page
    assert "two-hour elapsed-UTC budget is not established" in page and "no speedup conclusion" in page


@pytest.mark.parametrize("changes", [{"boot_id": "other"}, {"controller_pid": 999},
    {"controller_start_ticks": 999}, {"controller_launch_sha256": "f" * 64},
    {"supervisor_capture_sha256": "f" * 64}, {"supervisor_elapsed_seconds": 1.}])
def test_clock_annotation_requires_exact_original_attribution(fixture, changes):
    f = fixture
    clock_annotation(f, **changes)
    with pytest.raises(ValueError):
        run(f)
    assert not Path(f.plan["report_directory"]).exists()


def test_changed_clock_receipt_refuses_before_analysis(fixture):
    f = fixture
    observation, _ = clock_annotation(f)
    observation.write_text("changed")
    with pytest.raises(ValueError):
        run(f)
    assert not Path(f.plan["report_directory"]).exists()


def test_malformed_terminal_or_cleanup_receipt_never_authorizes_bulk_analysis(fixture):
    f = fixture
    close(f, cleanup=[])
    write(f.root / "execution-complete.json", {"outcomes": [None]})
    result = run(f)
    assert result["observation"]["kind"] == "controller_dead"
    assert "terminal_receipt_issue" in result["observation"]
    assert not result["checker_invoked"] and result["attempts"][0]["outcome"] == "unclosed_or_unknown"


def test_dead_controller_with_unclosed_worker_never_calls_checker(fixture):
    f = fixture
    (f.root / "cache1").mkdir()
    result = run(f)
    assert result["observation"]["kind"] == "controller_dead"
    assert not result["checker_invoked"] and result["analysis_status"] == "not_run"
    assert [r["outcome"] for r in result["attempts"]] == ["unclosed_or_unknown", "not_started"]
    assert not (f.root / "cache1/result.json").exists()


@pytest.mark.parametrize("changes", [{"owned_process_group_cleaned": False}, {"cleanup": {"verified": False}},
                                     {"status": "running"}, {"boot_id": "other"}, {"argv": ["other"]}])
def test_invalid_cleanup_stays_unknown_even_with_terminal_marker(fixture, changes):
    f = fixture
    close(f, **changes); terminal(f, stopped=True)
    result = run(f)
    assert not result["checker_invoked"] and not result["whole_fit_complete_pair"]
    assert result["attempts"][0]["outcome"] == "unclosed_or_unknown"


def test_dead_controller_closed_first_arm_keeps_second_pending(fixture):
    f = fixture
    close(f)
    checker(f, status="pending", outcomes=("timeout", "not_started"))
    result = run(f)
    assert len(f.calls) == 1 and result["analysis_status"] == "pending"
    assert result["attempts"][1]["outcome"] == "not_started"
    assert not result["whole_fit_complete_pair"]


def test_bounded_wait_expiration_is_not_fit_timeout(fixture):
    f = fixture
    alive(f)
    result = run(f)
    assert f.now[0] == pytest.approx(1.)
    assert result["observation"]["kind"] == "wait_expired"
    assert not result["checker_invoked"]
    assert all(r["outcome"] == "not_established" for r in result["attempts"])


@pytest.mark.parametrize("kind", ["boot", "pid", "argv"])
def test_changed_controller_identity_refuses_before_report(fixture, kind):
    f = fixture
    if kind == "boot":
        f.monkeypatch.setattr(completion, "boot_id", lambda: "new-boot")
    else:
        alive(f, **({"start_ticks": 999} if kind == "pid" else {"argv": ["other"]}))
    with pytest.raises(ValueError):
        run(f)
    assert not Path(f.plan["report_directory"]).exists()


@pytest.mark.parametrize("target", ["checker", "dependency", "python", "helper"])
def test_tool_identity_mismatch_refuses(fixture, target):
    f = fixture
    if target == "dependency":
        f.deps[0].write_text("changed")
    elif target == "helper":
        f.plan["helper"]["sha256"] = "0" * 64
        write(f.path, f.plan)
    else:
        Path(f.plan[target]["path"]).write_text("changed")
    with pytest.raises(ValueError):
        run(f)
    assert not Path(f.plan["report_directory"]).exists()


def test_dependency_change_after_checker_invalidates_trust_and_never_retries(fixture):
    f = fixture
    close(f); close(f, "cache0"); terminal(f)
    checker(f, callback=lambda: f.deps[0].write_text("changed"))
    result = run(f)
    assert len(f.calls) == 1 and result["issue"] and result["analysis_status"] == "not_run"
    assert (Path(f.plan["report_directory"]) / "checker.json").exists()
    assert not result["whole_fit_complete_pair"]


def test_existing_report_and_frozen_directory_overlaps_refuse(fixture):
    f = fixture
    for target in (f.root / "report", f.source / "report", f.tools / "report", f.root.parent):
        f.plan["report_directory"] = str(target); write(f.path, f.plan)
        with pytest.raises(ValueError): run(f)
    target = f.root.parent / "existing"; target.mkdir()
    f.plan["report_directory"] = str(target); write(f.path, f.plan)
    with pytest.raises(ValueError): run(f)


def test_exception_and_invalid_checker_evidence_still_show_all_attempts(fixture):
    f = fixture
    close(f); close(f, "cache0"); terminal(f)
    checker(f, status="invalid")
    result = run(f)
    assert result["analysis_status"] == "invalid" and len(result["attempts"]) == 2
    assert not result["whole_fit_complete_pair"]


def test_checker_crash_retains_invocation_and_no_success(fixture):
    f = fixture
    close(f); close(f, "cache0"); terminal(f)
    def crash(*args, **kwargs):
        f.calls.append(1)
        raise OSError("injected checker launch failure")
    f.monkeypatch.setattr(completion.subprocess, "run", crash)
    result = run(f)
    assert len(f.calls) == 1 and result["issue"]
    assert result["checker_invoked"] and not result["whole_fit_complete_pair"]


def test_json_html_escape_and_no_frozen_tree_writes(fixture):
    f = fixture
    close(f); close(f, "cache0"); terminal(f)
    expected = checker(f, status="invalid")
    expected["issues"] = ["<script>alert(1)</script>"]
    before = {str(p): p.read_bytes() for p in f.root.rglob("*") if p.is_file()}
    run(f)
    after = {str(p): p.read_bytes() for p in f.root.rglob("*") if p.is_file()}
    assert before == after
    page = (Path(f.plan["report_directory"]) / "index.html").read_text()
    assert "<script>alert" not in page and "&lt;script&gt;" in page


def test_no_signal_or_native_execution_api_exists_in_helper():
    source = SCRIPT.read_text()
    assert "os.kill(" not in source and ".terminate(" not in source and ".kill(" not in source
    assert "subprocess.run(argv" in source and "--output" in source
