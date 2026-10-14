from dataclasses import asdict, replace
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

import pytest

from orbit_poc.numerics.config import (Artifact, NumericsConfig, PROFILES,
                                      Resources, Runtime, config_from_dict)
from orbit_poc.numerics import protocol as p
from orbit_poc.numerics.report import create_report, numerical_comparisons, objective_resolution, nuisance_resolution


def test_exact_fixed_case_matrix_and_balanced_profile_rotation():
    cases = p.planned_cases()
    assert len(cases) == 50
    assert sum(c["origin"] == "fresh" for c in cases) == 32
    assert sum(c["origin"] == "retained_pulse_failure" for c in cases) == 6
    assert sum(c["origin"] == "retained_pulse_neighbor" for c in cases) == 6
    assert sum(c["origin"] == "retained_slow_density" for c in cases) == 2
    assert sum(c["origin"] == "retained_flight_control" for c in cases) == 4
    assert {c["case"]["seed"] for c in cases if c["origin"] == "fresh"} == {510000, 510001}
    attempts = p.attempts(cases)
    assert len(attempts) == len({a["attempt_id"] for a in attempts}) == 150
    for case in cases:
        assert {a["profile"] for a in attempts if a["case_id"] == case["case_id"]} == set(PROFILES)
    assert [a["profile"] for a in attempts[:3]] == list(PROFILES)
    assert [a["profile"] for a in attempts[3:6]] == [*PROFILES[1:], PROFILES[0]]


def test_published_case_selection_matches_the_execution_recipe():
    record = p.read_json(p.project_root() / "validation/numerics-v3.1/case-selection.json")
    assert record["cases"] == p.planned_cases()
    assert record["attempts"] == p.attempts(record["cases"])
    assert record["controls"] == asdict(NumericsConfig().controls)
    assert record["case_selection_hash"] == p.canonical_hash({
        key: value for key, value in record.items() if key != "case_selection_hash"})


@pytest.mark.parametrize("path,value", [
    (("unknown",), 1), (("controls", "jitter"), 1e-12),
    (("controls", "maximum_accepted_iterations"), 33),
    (("controls", "wall_time_seconds"), True),
    (("resources", "threads"), 2), (("profiles",), list(reversed(PROFILES))),
    (("legacy_runtime", "native", "sha256"), "bad"),
    (("resources", "reserved_cpu_ids"), [2, 2]),
])
def test_unknown_and_changed_scientific_or_numerical_options_rejected(path, value):
    config = json.loads(json.dumps(asdict(NumericsConfig())))
    target = config
    for name in path[:-1]: target = target[name]
    target[path[-1]] = value
    with pytest.raises(ValueError): config_from_dict(config)


@pytest.fixture
def prepared_campaign(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)
    (project / "src/frozen.py").write_text("value = 1\n")
    evidence = project / "validation/comparison-v3"; evidence.mkdir(parents=True)
    for name, _ in p.EVIDENCE.values():
        shutil.copy2(p.project_root() / "validation/comparison-v3" / name, evidence / name)
    inputs = tmp_path / "inputs"; inputs.mkdir()
    data = inputs / "observations.dat"; data.write_text("blind measurement fixture\n")
    identities = {key: p.canonical_hash(key) for key in p.IDENTITIES}
    roles = ["gnss_observations", "gnss_orbits", "gnss_clocks", "bootstrap_orbit", "attitude", "spacecraft_metadata", "earth_orientation"]
    estimation = [{"role": role, **p.artifact(data), **({"provenance": "gnss_only"} if role == "bootstrap_orbit" else {})} for role in roles]
    def prepared_for(case):
        identity = {**identities, "mask_hash": p.canonical_hash(case.get("mask", {}))}
        native = inputs / f"native-{identity['mask_hash']}.json"
        p.write_json(native, {"output_dir": str(inputs), "native_artifacts": [{"role": "receiver", **p.artifact(data)}], **identity})
        prepared = {"status": "prepared", "estimation_inputs": [*estimation,
            {"role": "force_auxiliary", **p.artifact(native), "metadata": {"kind": "native_preparation"}}], **identity}
        reference = tmp_path / f"prepared-{identity['mask_hash']}.json"; p.write_json(reference, prepared)
        return prepared, p.artifact(reference)
    count = {"preparations": 0, "executions": []}
    def retained(case):
        actual_case = case.get("case", {"date": "2024-04-24", "coverage": case.get("expected_coverage")})
        prepared, reference = prepared_for(actual_case)
        request = {"stage": case["stage"], "case": actual_case,
            "method": case["method"], "parameters": case.get("parameters", {"fixture": 1}), **prepared}
        request.pop("status")
        return request, {"request": reference}
    def fresh(*args):
        count["preparations"] += 1
        return prepared_for(args[0])
    runtime = {"source_root": str(project), "source_sha256": "1"*64,
               "python": {"path": sys.executable, "sha256": "2"*64},
               "native": {"path": "/bin/false", "sha256": "3"*64}, "libraries": None}
    monkeypatch.setattr(p, "verify_runtime", lambda *args: runtime)
    monkeypatch.setattr(p, "resource_guard", lambda *args: {"safe": True})
    monkeypatch.setattr(p, "_seed_inventory", lambda *args: {"fresh_seeds": p.FRESH_SEEDS, "overlap": []})
    monkeypatch.setattr(p, "_retained_request", retained)
    monkeypatch.setattr(p, "_fresh_preparation", fresh)
    root = tmp_path / "campaign"
    config = replace(NumericsConfig(), output_dir=str(root))
    assert p.prepare(config, project=project)["status"] == "prepared"
    assert count["preparations"] == 16
    return config, root, project, count, data


def test_prepare_reuses_exact_freeze_and_rejects_source_changes(prepared_campaign):
    config, root, project, count, _ = prepared_campaign
    before = p.file_hash(root / "manifest.json")
    assert p.prepare(config, project=project)["status"] == "prepared"
    assert count["preparations"] == 16
    assert p.file_hash(root / "manifest.json") == before
    (project / "src/frozen.py").write_text("value = 2\n")
    with pytest.raises(ValueError, match="source|Source"):
        p.run(config, project=project, max_attempts=1)


def test_shared_inputs_and_all_150_attempts_preserve_failures(prepared_campaign, monkeypatch):
    config, root, project, count, _ = prepared_campaign
    manifest = p.read_json(root / "manifest.json")
    groups = {}
    for case in manifest["cases"]:
        if case["origin"] == "fresh":
            groups.setdefault(p.canonical_hash(case["case"]), set()).add(case["input_manifest_hash"])
    assert len(groups) == 16 and all(len(values) == 1 for values in groups.values())
    def execute(job, directory, runtime, resources):
        count["executions"].append(job)
        valid = job["numerics_profile"] != "legacy_v3"
        import numpy as np
        state = directory / "state.npz"
        np.savez(state, mjd=np.array([60424., 60424.+30/86400]), states=np.zeros((2, 6)),
            covariance=np.tile(np.eye(6), (2, 1, 1)))
        audit = directory / "audit.txt"; audit.write_text("fixed observation audit\n")
        return {"status": "complete" if valid else "unresolved_rank", "converged": valid,
            "covariance_valid": valid, "covariance_scope": "marginalized", "parameter_blocks": ["initial_state", "nuisance"],
            "artifacts": [{"role": "state_estimate", **p.artifact(state)},
                {"role": "native_preprocessing_audit", **p.artifact(audit)}],
            "method": job["method"], "force_model_hash": job["force_model_hash"],
            "measurement_model_hash": job["measurement_model_hash"],
            "native_binary_sha256": job["expected_native_binary_sha256"],
            "preprocessing_audit_sha256": p.file_hash(audit),
            "metadata": {"reference_inputs_used": False}, "numerical_diagnostics": ({"history": [
                {"trial": 1, "accepted": True, "actual_reduction": 1e-10,
                 "objective_reduction_numerically_resolved": False,
                 "nuisance_floor_limited_before": True,
                 "nuisance_floor_limited_trial": False}]} if valid else None),
            "harness_execution": {"elapsed_seconds": 2., "peak_process_tree_rss_bytes": 1024}}
    monkeypatch.setattr(p, "_execute_job", execute)
    assert p.run(config, project=project)["terminal_attempts"] == 150
    assert len(count["executions"]) == 150
    for job in count["executions"]:
        assert not p.FORBIDDEN.intersection(job)
        if job["numerics_profile"] == "legacy_v3": assert "numerical_controls" not in job
        else: assert job["numerical_controls"] == asdict(config.controls)
    assert p.run(config, project=project)["jobs_started"] == 0
    assert len(count["executions"]) == 150  # Failed baselines never rerun.
    create_report(config, project=project)
    report = p.read_json(root / "report/report.json")
    assert report["execution_complete"] and not report["all_attempts_valid"]
    assert len(report["attempts"]) == 150
    assert report["profiles"][0]["status_counts"] == {"unresolved_rank": 50}
    assert report["profiles"][1]["valid_attempts"] == 50
    assert report["profiles"][0]["accepted_unresolved_objective_trials"] is None
    assert report["profiles"][1]["accepted_unresolved_objective_trials"] == 50
    assert report["profiles"][1]["objective_resolution_available_attempts"] == 50
    assert report["profiles"][0]["accepted_floor_limited_nuisance_trials"] is None
    assert report["profiles"][1]["accepted_floor_limited_nuisance_trials"] == 50
    assert report["profiles"][1]["nuisance_resolution_available_attempts"] == 50
    assert "Accepted unresolved gains" in (root / "report/index.html").read_text()
    assert "Accepted inexact-profile steps" in (root / "report/index.html").read_text()
    assert any("not a rigorous error bound" in item for item in report["limitations"])
    assert "coverage variants and methods are dependent" in (root / "report/index.html").read_text()
    assert "Solver/controller, forward arithmetic and bookkeeping" in (root / "report/index.html").read_text()
    assert any("not a pure linear-algebra replacement" in item for item in report["limitations"])
    assert any("not a Jacobian-only contrast" in item for item in report["limitations"])
    assert any("GNSS interpolation/time/range arithmetic stabilization" in item for item in report["limitations"])
    assert any("not 32 independent statistical trials" in item for item in report["limitations"])
    assert report["paired"][0]["jointly_valid_timed_pairs"] == 0


def test_partial_and_corrupt_attempts_stay_in_report(prepared_campaign, monkeypatch):
    config, root, project, _, _ = prepared_campaign
    monkeypatch.setattr(p, "_execute_job", lambda *args: {"status": "failed", "converged": False,
        "covariance_valid": False, "error": "<script>bad</script>", "artifacts": []})
    assert p.run(config, project=project, max_attempts=2)["terminal_attempts"] == 2
    create_report(config, project=project)
    report = p.read_json(root / "report/report.json")
    assert len(report["attempts"]) == 150
    assert sum(r["status"] == "not_run" for r in report["attempts"]) == 148
    html = (root / "report/index.html").read_text()
    assert "<script>bad</script>" not in html and "&lt;script&gt;bad&lt;/script&gt;" in html
    first = p.read_json(root / "plan.json")["attempts"][0]["attempt_id"]
    (root / "attempts" / first / "result.json").write_text("{}")
    create_report(config, project=project)
    assert p.read_json(root / "report/report.json")["attempts"][0]["status"] == "integrity_error"
    with pytest.raises(p.NotReady): p.run(config, project=project)


def test_changed_input_prevents_all_execution(prepared_campaign, monkeypatch):
    config, root, project, _, data = prepared_campaign
    data.write_text("mutated input")
    monkeypatch.setattr(p, "_execute_job", lambda *args: pytest.fail("changed inputs must never fit"))
    with pytest.raises((ValueError, p.NotReady)): p.run(config, project=project)
    assert not (root / "attempts").exists()


def test_interrupted_attempt_is_not_implicitly_retried(prepared_campaign, monkeypatch):
    config, root, project, _, _ = prepared_campaign
    first = p.read_json(root / "plan.json")["attempts"][0]["attempt_id"]
    directory = root / "attempts" / first; directory.mkdir(parents=True)
    (directory / "worker.log").write_text("interrupted native output")
    monkeypatch.setattr(p, "_execute_job", lambda *args: pytest.fail("no implicit retry"))
    result = p.run(config, project=project)
    assert result["status"] == "blocked" and result["jobs_started"] == 0


def test_resource_guard_checks_pid_start_scope_affinity_and_memory(tmp_path, monkeypatch):
    proc = tmp_path / "proc"; (proc / "sys/kernel/random").mkdir(parents=True)
    (proc / "sys/kernel/random/boot_id").write_text("boot-a\n")
    (proc / "meminfo").write_text(f"MemAvailable: {32*1024**2} kB\n")
    process = proc / "123"; process.mkdir()
    command = b"python\0/protected/campaign/driver.py\0"
    (process / "cmdline").write_bytes(command)
    fields = ["S"]+["0"]*18+["42"]+["0"]*4
    (process / "stat").write_text("123 (python) "+" ".join(fields))
    receipt = tmp_path / "guard.json"
    p.write_json(receipt, {"schema_version": 1, "pid": 123, "start_ticks": 42,
        "boot_id": "boot-a", "command_sha256": hashlib.sha256(command).hexdigest(),
        "scope_tokens": ["/protected/campaign"]})
    resources = replace(Resources(), protected_process_receipt=Artifact(**p.artifact(receipt)))
    with pytest.raises(p.NotReady, match="active"): p.resource_guard(resources, proc_root=proc)
    monkeypatch.setattr(os, "sched_getaffinity", lambda pid: {0, 1, 2, 3} if pid == 0 else {0, 1})
    safe = replace(resources, reserved_cpu_ids=(2, 3))
    assert p.resource_guard(safe, proc_root=proc)["protected_active_pids"] == [123]
    with pytest.raises(p.NotReady, match="overlaps"):
        p.resource_guard(replace(resources, reserved_cpu_ids=(1, 2)), proc_root=proc)
    # A reused PID is still protected if its command belongs to the campaign scope.
    (process / "stat").write_text("123 (python) "+" ".join(["S"]+["0"]*18+["43"]+["0"]*4))
    with pytest.raises(p.NotReady, match="active"): p.resource_guard(resources, proc_root=proc)
    (process / "cmdline").write_bytes(b"unrelated\0")
    assert p.resource_guard(resources, proc_root=proc)["protected_active_pids"] == []
    (proc / "meminfo").write_text("MemAvailable: 1024 kB\n")
    with pytest.raises(p.NotReady, match="memory"): p.resource_guard(resources, proc_root=proc)


def test_seed_reuse_is_rejected(tmp_path):
    path = tmp_path / "old-protocol.json"
    p.write_json(path, {"config": {"synthetic": {"evaluation_seeds": [510000]}}})
    config = replace(NumericsConfig(), prior_seed_protocols=(Artifact(**p.artifact(path)),))
    with pytest.raises(ValueError, match="already appeared"): p._seed_inventory(config, tmp_path)


def test_runtime_keeps_virtual_environment_invocation_path(tmp_path):
    source = tmp_path / "source"; (source / "src").mkdir(parents=True)
    (source / "src/pinned.py").write_text("value = 1\n")
    runtime = Runtime(source_root=str(source), source_sha256=p.source_snapshot(source)["sha256"],
        python=Artifact(path=sys.executable, sha256=p.file_hash(sys.executable)),
        native=Artifact(**p.artifact(sys.executable)))
    observed = p.verify_runtime(runtime, tmp_path)
    assert observed["python"]["path"] == str(Path(sys.executable).parent.resolve() / Path(sys.executable).name)
    assert observed["python"]["resolved_path"] == str(Path(sys.executable).resolve())


def test_backend_success_without_a_posterior_is_not_accepted(prepared_campaign, monkeypatch):
    config, root, project, _, _ = prepared_campaign
    monkeypatch.setattr(p, "_execute_job", lambda *args: {"status": "complete", "converged": True,
        "covariance_valid": True, "artifacts": [], "covariance_scope": "marginalized", "parameter_blocks": ["state"]})
    p.run(config, project=project, max_attempts=1)
    first = p.read_json(root / "plan.json")["attempts"][0]["attempt_id"]
    result = p.read_json(root / "attempts" / first / "result.json")
    assert result["status"] == "failed" and not result["covariance_valid"]
    assert result["error"].startswith("Invalid complete result:")


def test_mask_mismatch_is_rejected(prepared_campaign):
    _, root, _, _, _ = prepared_campaign
    fit = p.read_json(root / "manifest.json")["cases"][0]["fit_request"]
    fit["case"]["mask"]["intervals_seconds"] = []
    with pytest.raises(ValueError, match="mask"): p._verify_blind_request(fit)


def test_actual_archived_subprocess_uses_pinned_import_tree(tmp_path, monkeypatch):
    pytest.importorskip("psutil")
    source = tmp_path / "archived"
    package = source / "src/orbit_poc/comparison"; package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("")
    (package / "backend.py").write_text("import os\ndef fit_job(job, root):\n return {'status':'failed','origin':__file__,'profile':job['numerics_profile'],'override':os.environ.get('ORBIT_POC_NUMERICS_SOLVER')}\n")
    runtime = {"python": p.artifact(sys.executable), "source_root": str(source), "source_sha256": p.source_snapshot(source)["sha256"], "native": p.artifact(sys.executable), "libraries": None}
    monkeypatch.setenv("PYTHONPATH", "/definitely/the/wrong/source")
    monkeypatch.setenv("ORBIT_POC_NUMERICS_SOLVER", "unfrozen override")
    result = p._execute_job({"numerics_profile": "legacy_v3"}, tmp_path / "attempt", runtime, replace(Resources(), reserved_output_bytes=1024))
    assert result["origin"] == str(package / "backend.py")
    assert result["profile"] == "legacy_v3"
    assert result["override"] is None
    assert result["harness_execution"]["process_group_isolated"]


def test_timeout_kills_worker_process_group_and_descendant(tmp_path, monkeypatch):
    psutil = pytest.importorskip("psutil")
    source = tmp_path / "archived"; package = source / "src/orbit_poc/comparison"; package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text(""); (package / "__init__.py").write_text("")
    (package / "backend.py").write_text("import subprocess,sys,time\ndef fit_job(job, root):\n child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])\n (root/'child.pid').write_text(str(child.pid))\n time.sleep(30)\n")
    runtime = {"python": p.artifact(sys.executable), "source_root": str(source), "source_sha256": p.source_snapshot(source)["sha256"], "native": p.artifact(sys.executable), "libraries": None}
    # Separate interpreter startup from the resource-limit assertion. A busy
    # native compiler can delay Python startup beyond half a second.
    monkeypatch.setattr(p, "ATTEMPT_WALL_SECONDS", 30.)
    directory = tmp_path / "attempt"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(p._execute_job, {"numerics_profile": "legacy_v3"}, directory, runtime, replace(Resources(), reserved_output_bytes=1024))
        deadline = time.monotonic()+25
        while not (directory / "child.pid").exists() and not future.done() and time.monotonic() < deadline:
            time.sleep(.05)
        assert (directory / "child.pid").exists(), "Fixture worker did not signal descendant readiness"
        monkeypatch.setattr(p, "ATTEMPT_WALL_SECONDS", 0.)
        result = future.result(timeout=10)
    assert result["status"] == "timeout" and not result["covariance_valid"]
    child = int((directory / "child.pid").read_text())
    deadline = time.monotonic()+2
    while psutil.pid_exists(child) and psutil.Process(child).status() != psutil.STATUS_ZOMBIE and time.monotonic() < deadline:
        time.sleep(.05)
    assert not psutil.pid_exists(child) or psutil.Process(child).status() == psutil.STATUS_ZOMBIE


def test_legacy_phase_sidecar_indexes_only_this_attempt_output(tmp_path):
    directory = tmp_path / "attempt"; directory.mkdir()
    phase = directory / "output/2024-04-24/phase.txt"; phase.parent.mkdir(parents=True)
    phase.write_text("native diagnostic\n")
    config = directory / "estimate.xml"
    config.write_text(f"<groops><outputfilePhaseRecovery>{directory}/output/{{loopTime:%D}}/phase.txt</outputfilePhaseRecovery></groops>")
    before = p.file_hash(config)
    result = {"status": "complete", "artifacts": [{"role": "native_fit_configuration", **p.artifact(config)}]}
    job = {"numerics_profile": "legacy_v3", "case": {"epoch": "2024-04-24T00:00:00"}}
    p.attach_legacy_phase_diagnostic(result, job, directory)
    assert result["artifacts"][-1]["role"] == "phase_recovery"
    assert result["artifacts"][-1]["sha256"] == p.file_hash(phase)
    assert p.file_hash(config) == before
    result = {"status": "complete", "artifacts": [{"role": "native_fit_configuration", **p.artifact(config)}]}
    p.attach_legacy_phase_diagnostic(result, job, directory / "other-attempt")
    assert result["diagnostic_availability"]["carrier_phase_predictions"]["status"] == "unavailable"


def test_matched_numerical_differences_and_support_mismatch_are_explicit(tmp_path):
    import numpy as np
    header = "# GPSMJD PRN type input_m processed_m removed_windup_m fitted_ambiguity_m receiver_bias_m transmitter_bias_m STEC TEC_factor_m residual_m sigma_m clock_m track_start_GPSMJD track_end_GPSMJD\n"
    rows = []
    for index, profile in enumerate(PROFILES):
        estimate = tmp_path / (profile + ".npz")
        states = np.zeros((2, 6)); states[:, 0] = index * .01
        np.savez(estimate, mjd=np.array([60424., 60424.+30/86400]), states=states,
            covariance=np.tile(np.eye(6)*(1+index*.1), (2, 1, 1)))
        phase = tmp_path / (profile + ".txt")
        phase.write_text(header + f"60424 1 L1CG** 100 99 1 0 0 0 0 1 {index*.003:.9f} .003 0 60424 60424.1\n")
        rows.append({"case_id": "same-case", "profile": profile, "origin": "fresh", "method": "groops_pulses",
            "status": "complete", "valid": True, "artifacts": [{"role": "state_estimate", **p.artifact(estimate)},
                {"role": "phase_recovery", **p.artifact(phase)}]})
    pairs = numerical_comparisons(rows)
    assert [r["comparison"] for r in pairs] == ["solver_only", "derivative_change"]
    assert pairs[0]["state_and_covariance"]["position_difference_m"]["maximum"] == pytest.approx(.01)
    assert pairs[0]["state_and_covariance"]["position_covariance_difference_m2"]["maximum"] == pytest.approx(np.sqrt(3)*.1)
    assert pairs[0]["carrier_phase_predictions"]["prediction_difference_in_assumed_sigmas"]["rms"] == pytest.approx(1.)
    assert pairs[0]["code_predictions"]["status"] == "unavailable"
    phase = Path(rows[2]["artifacts"][1]["path"])
    phase.write_text(phase.read_text().replace("60424 1 L1CG**", "60424 2 L1CG**"))
    rows[2]["artifacts"][1] = {"role": "phase_recovery", **p.artifact(phase)}
    comparison = numerical_comparisons(rows)[1]
    assert comparison["state_and_covariance"]["status"] == "compared"
    assert comparison["carrier_phase_predictions"]["status"] == "unavailable"
    assert "support differs" in comparison["carrier_phase_predictions"]["reason"]


@pytest.mark.parametrize("mutation,message", [
    ("empty", "nonempty"), ("duplicate_epoch", "ordered"),
    ("nonfinite", "nonfinite"), ("indefinite", "positive definite"),
    ("asymmetric", "asymmetric"), ("empty_file", "Unreadable"), ("nonnumeric", "real numeric"), ("npy", "Unreadable"),
])
def test_cartesian_posterior_receipt_requires_valid_numeric_contents(tmp_path, mutation, message):
    import numpy as np
    path = tmp_path / "state.npz"
    mjd = np.array([60424., 60424.+30/86400]); states = np.zeros((2, 6))
    covariance = np.tile(np.eye(6), (2, 1, 1))
    if mutation == "empty": mjd, states, covariance = mjd[:0], states[:0], covariance[:0]
    if mutation == "duplicate_epoch": mjd[1] = mjd[0]
    if mutation == "nonfinite": states[0, 0] = np.nan
    if mutation == "nonnumeric": states = states.astype(str)
    if mutation == "indefinite": covariance[:, 0, 1] = covariance[:, 1, 0] = 2.
    if mutation == "asymmetric": covariance[:, 0, 1] = .1
    np.savez(path, mjd=mjd, states=states, covariance=covariance)
    if mutation == "empty_file": path.write_bytes(b"")
    if mutation == "npy":
        with path.open("wb") as stream: np.save(stream, states)
    with pytest.raises(ValueError, match=message): p.read_cartesian_estimate(p.artifact(path))


def test_generated_retention_preserves_final_outputs_and_all_diagnostics(tmp_path):
    from orbit_poc.numerics.retention import compact_attempt
    root = tmp_path / "attempt"; root.mkdir()
    keep = root / "point-002-final/qr.2.R.bin"
    old = root / "point-001-initial/qr.1.R.bin"
    variable = root / "point-001-initial/closure-01/variational.dat"
    for path in (keep, old, variable):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"generated numerical matrix\n")
    log = old.with_suffix(".json"); log.write_text('{"rank_status":"full"}\n')
    outside = tmp_path / "original.dat"; outside.write_bytes(b"immutable preparation\n")
    alias = root / "point-001-initial/closure-02/variational.dat"
    alias.parent.mkdir(); alias.symlink_to(outside)
    final = {"status":"complete", "artifacts":[{"role":"native_qr_factor", **p.artifact(keep)}]}
    compact_attempt(root, final, "qr_lm_staged_jacobian")
    assert keep.is_file() and log.is_file() and alias.is_symlink() and outside.is_file()
    assert not old.exists() and not variable.exists()
    receipt = p.read_json(root / "retention.json")
    assert {r["path"] for r in receipt["removed"]} == {str(old), str(variable)}
    assert all(p.is_digest(r["sha256"]) and r["bytes"] > 0 for r in receipt["removed"])
    assert not receipt["errors"]
    assert final["artifacts"][-1]["role"] == "numerical_retention_audit"



def test_terminal_release_persists_proof_before_unlink_and_recovers(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import compact_attempt
    old = tmp_path / "point-001-initial/qr.1.R.bin"
    old.parent.mkdir(); old.write_bytes(b"audited generated factor")
    result = {"status": "complete", "artifacts": []}
    unlink = Path.unlink
    def interrupted_release(path, *args, **kwargs):
        if path == old:
            record = p.read_json(tmp_path / "retention.json")["removed"][0]
            assert record["path"] == str(path) and record["sha256"] == p.file_hash(path)
            assert record["bytes"] == path.stat().st_size and record["status"] == "verified_before_release"
            unlink(path, *args, **kwargs)
            raise KeyboardInterrupt("simulated interruption after release")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", interrupted_release)
    with pytest.raises(KeyboardInterrupt): compact_attempt(tmp_path, result, "qr_lm_staged_jacobian")
    assert not old.exists()
    proof = p.read_json(tmp_path / "retention.json")
    assert proof["removed"][0]["sha256"] == hashlib.sha256(b"audited generated factor").hexdigest()
    assert proof["status"] == "running"
    monkeypatch.setattr(Path, "unlink", unlink)
    compact_attempt(tmp_path, result, "qr_lm_staged_jacobian")
    recovered = p.read_json(tmp_path / "retention.json")
    assert recovered["status"] == "complete"
    assert recovered["removed"][0]["status"] == "absent_after_verified_release"
    assert len(result["artifacts"]) == 1


def test_terminal_release_failure_retains_proof_and_retries(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import compact_attempt
    old = tmp_path / "point-001-initial/qr.1.R.bin"
    old.parent.mkdir(); old.write_bytes(b"generated factor")
    result = {"status": "complete", "artifacts": []}
    unlink = Path.unlink
    def cannot_release(path, *args, **kwargs):
        if path == old: raise OSError("simulated storage failure")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", cannot_release)
    compact_attempt(tmp_path, result, "qr_lm_staged_jacobian")
    proof = p.read_json(tmp_path / "retention.json")
    assert old.exists() and proof["status"] == "partial" and proof["removed_bytes"] == 0
    assert proof["removed"][0]["status"] == "verified_before_release" and proof["errors"]
    monkeypatch.setattr(Path, "unlink", unlink)
    compact_attempt(tmp_path, result, "qr_lm_staged_jacobian")
    recovered = p.read_json(tmp_path / "retention.json")
    assert not old.exists() and recovered["status"] == "complete"
    assert recovered["removed_bytes"] == len(b"generated factor") and recovered["errors"]
    assert len(result["artifacts"]) == 1

def test_failed_attempt_retains_last_factor_without_accepting_covariance(tmp_path):
    from orbit_poc.numerics.retention import compact_attempt
    paths=[]
    for point, sequence in ((1, 9), (2, 1), (2, 2)):
        path=tmp_path/f"point-{point:03d}-trial/qr.{sequence}.R.bin"
        path.parent.mkdir(exist_ok=True); path.write_bytes(b"factor")
        paths.append(path)
    result={"status":"unresolved_rank", "converged":False, "covariance_valid":False, "artifacts":[]}
    compact_attempt(tmp_path, result, "qr_lm_legacy_jacobian")
    assert [path.exists() for path in paths] == [False, False, True]
    assert result["status"] == "unresolved_rank" and not result["covariance_valid"]
    assert result["artifacts"][0]["role"] == "terminal_diagnostic_qr_factor"
    assert result["artifacts"][0]["metadata"]["accepted_covariance"] is False


def test_archived_output_files_are_not_pruned(tmp_path):
    from orbit_poc.numerics.retention import compact_attempt
    path=tmp_path/"point-001-initial/qr.1.R.bin"; path.parent.mkdir(); path.write_bytes(b"archive")
    compact_attempt(tmp_path,{"status":"failed","artifacts":[]},"legacy_v3")
    assert path.is_file() and p.read_json(tmp_path/"retention.json")["removed"] == []


@pytest.mark.parametrize("physical", [False, True])
def test_output_storage_reserve_terminates_worker(tmp_path, monkeypatch, physical):
    pytest.importorskip("psutil")
    from collections import namedtuple
    source=tmp_path/"source";package=source/"src/orbit_poc/comparison";package.mkdir(parents=True)
    (package.parent/"__init__.py").write_text("");(package/"__init__.py").write_text("")
    (package/"backend.py").write_text("import time\ndef fit_job(job,root):\n time.sleep(30)\n")
    runtime={"python":p.artifact(sys.executable),"source_root":str(source),"source_sha256":p.source_snapshot(source)["sha256"],"native":p.artifact(sys.executable),"libraries":None}
    usage=namedtuple("usage","total used free")
    monkeypatch.setattr(p.shutil,"disk_usage",lambda path:usage(2**40, 0,
        1024 if not physical or str(path) == "/physical-backing" else 2**40))
    resources = replace(Resources(), physical_backing_path="/physical-backing" if physical else "")
    result=p._execute_job({"numerics_profile":"legacy_v3"},tmp_path/"attempt",runtime,resources)
    assert result["status"] == "disk_limit" and not result["covariance_valid"]
    key = "minimum_free_physical_backing_bytes" if physical else "minimum_free_output_bytes"
    assert result["harness_execution"][key] == 1024


def test_execution_context_receipt_is_frozen_and_rechecked(prepared_campaign):
    config, root, project, _, _ = prepared_campaign
    context = root.parent / "execution-context.json"
    context.write_text('{"namespace":"identical-for-all-profiles","package_tree_sha256":"fixture"}\n')
    revised = replace(config, output_dir=str(root.parent / "context-campaign"),
        execution_context=Artifact(**p.artifact(context)))
    assert p.prepare(revised, project=project)["status"] == "prepared"
    directory = Path(revised.output_dir)
    assert p.verify_manifest(revised, directory, project)["execution_context"] == p.artifact(context)
    context.write_text('{"namespace":"changed"}\n')
    with pytest.raises(p.NotReady, match="changed pinned artifact"):
        p.verify_manifest(revised, directory, project)


def test_supplemental_fortran_source_is_checked_without_changing_legacy_hash(tmp_path):
    source = tmp_path / 'source'; (source / 'groops/extension').mkdir(parents=True)
    fortran = source / 'groops/extension/native.f'; fortran.write_text('C first version\n')
    original = p.source_snapshot(source)['sha256']
    manifest = tmp_path / 'sources.json'
    p.write_json(manifest, {'schema_version': 1, 'files': [p.artifact(fortran)]})
    executable = Path(sys.executable).resolve()
    runtime = Runtime(source_root=str(source), source_sha256=original,
        python=Artifact(**p.artifact(executable)), native=Artifact(**p.artifact(executable)),
        supplemental_sources=Artifact(**p.artifact(manifest)))
    assert p.verify_runtime(runtime, tmp_path)['supplemental_sources'] == p.artifact(manifest)
    fortran.write_text('C changed version\n')
    assert p.source_snapshot(source)['sha256'] == original
    with pytest.raises(p.NotReady): p.verify_runtime(runtime, tmp_path)


def test_terminal_archive_preserves_artifacts_links_and_recovery(tmp_path, monkeypatch):
    from orbit_poc.numerics.storage import archive_attempt, inventory
    working = tmp_path / 'working' / 'attempt'; working.mkdir(parents=True)
    (working / 'result-record.json').write_text('{}')
    (working / 'final.dat').write_bytes(b'final covariance bytes')
    (working / 'alias').symlink_to('final.dat')
    expected = inventory(working)
    archive = tmp_path / 'archive'; receipt = tmp_path / 'index.json'
    original_replace = os.replace
    def interrupted(source, destination):
        if str(source).endswith('.archive-link'): raise OSError('simulated interruption after working-directory rename')
        return original_replace(source, destination)
    monkeypatch.setattr(os, 'replace', interrupted)
    with pytest.raises(OSError, match='simulated interruption'):
        archive_attempt(working, archive, receipt, reserve_bytes=1)
    assert working.with_name('.attempt.archiving').is_dir()
    assert (archive / 'attempt' / 'final.dat').read_bytes() == b'final covariance bytes'
    monkeypatch.setattr(os, 'replace', original_replace)
    saved = archive_attempt(working, archive, receipt, reserve_bytes=1)
    assert working.is_symlink() and working.resolve() == archive / 'attempt'
    assert inventory(working) == expected
    assert saved['status'] == 'complete'
    assert not working.with_name('.attempt.archiving').exists()
    assert archive_attempt(working, archive, receipt, reserve_bytes=1)['status'] == 'complete'
    (archive / 'attempt/final.dat').write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='differ'):
        archive_attempt(working, archive, receipt, reserve_bytes=1)


def test_archive_never_replaces_original_on_copy_verification_failure(tmp_path, monkeypatch):
    from orbit_poc.numerics import storage
    working = tmp_path / 'working'; working.mkdir()
    (working / 'result-record.json').write_text('{}'); (working / 'diagnostic').write_text('original')
    original = shutil.copy2
    def corrupt(source, destination, **kwargs):
        result = original(source, destination, **kwargs)
        if Path(destination).name == 'diagnostic': Path(destination).write_text('modified')
        return result
    monkeypatch.setattr(shutil, 'copy2', corrupt)
    with pytest.raises(ValueError, match='differ'):
        storage.archive_attempt(working, tmp_path / 'archive', tmp_path / 'receipt.json', reserve_bytes=1)
    assert not working.is_symlink() and (working / 'diagnostic').read_text() == 'original'


def test_gate_receipts_are_separate_from_terminal_fit_count(tmp_path):
    from orbit_poc.numerics.report import acceptance_gates, REQUIRED_GATES
    assert all(x['status'] == 'pending' for x in acceptance_gates(None))
    receipt = tmp_path / 'correctness.json'; p.write_json(receipt, {'passed': True})
    context = tmp_path / 'context.json'
    p.write_json(context, {'acceptance_gates': [{'gate': name, 'status': 'passed',
        'scope': 'Explicit independent correctness test', 'receipt': p.artifact(receipt)} for name in REQUIRED_GATES]})
    assert all(x['status'] == 'passed' for x in acceptance_gates(p.artifact(context)))
    receipt.write_text('{}')
    assert all(x['status'] == 'invalid' for x in acceptance_gates(p.artifact(context)))



def test_all_profiles_archive_terminal_failures_and_resume(prepared_campaign, monkeypatch):
    from collections import namedtuple
    from orbit_poc.numerics import storage
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: usage(2**40, 0, 2**40))
    config, root, project, _, _ = prepared_campaign
    revised = replace(config, output_dir=str(root.parent / "archival-campaign"),
                      archive_dir=str(root.parent / "archive"))
    assert p.prepare(revised, project=project)["status"] == "prepared"
    monkeypatch.setattr(p, "_execute_job", lambda *args: {"status":"failed", "converged":False, "covariance_valid":False})
    result = p.run(revised, project=project, max_attempts=3)
    assert result["terminal_attempts"] == 3
    attempts = list((Path(revised.output_dir) / "attempts").iterdir())
    assert len(attempts) == 3 and all(path.is_symlink() for path in attempts)
    assert p.run(revised, project=project, max_attempts=0)["jobs_started"] == 0
    report = create_report(revised, project=project)
    saved = p.read_json(report["report"])
    assert saved["terminal_attempts"] == 3 and saved["release_status"] == "pending"
    assert sum("archive" in row for row in saved["attempts"]) == 3


def test_unresolved_objective_gains_are_reported_without_inventing_legacy_flags():
    assert objective_resolution(None)["status"] == "unavailable"
    legacy = objective_resolution({"history": [{"actual_reduction": 1.0, "accepted": True}]})
    assert legacy["trials_without_resolution_diagnostic"] == 1
    assert legacy["accepted_unresolved_trials"] is None
    summary = objective_resolution({"history": [
        {"confirmation": True, "accepted": True},
        {"trial": 1, "actual_reduction": 1e-9, "accepted": True, "objective_reduction_numerically_resolved": False},
        {"trial": 2, "actual_reduction": -1e-9, "accepted": False, "objective_reduction_numerically_resolved": False},
        {"trial": 3, "actual_reduction": 2., "accepted": True, "objective_reduction_numerically_resolved": True},
        {"trial": 4, "actual_reduction": None, "accepted": False}]})
    assert summary["evaluated_trials"] == summary["flagged_trials"] == 3
    assert summary["unresolved_trials"] == 2 and summary["accepted_unresolved_trials"] == 1
    assert [row["trial"] for row in summary["unresolved_trial_evidence"]] == [1, 2]


def test_inexact_nuisance_progress_is_separate_from_strict_confirmation():
    assert nuisance_resolution(None)["status"] == "unavailable"
    absent = nuisance_resolution({"history": [{"trial": 1, "accepted": True}], "confirmation_checks": None})
    assert absent["accepted_floor_limited_trials"] is None
    assert absent["trials_without_profile_diagnostic"] == 1
    summary = nuisance_resolution({"history": [
        {"trial": 1, "accepted": True, "nuisance_floor_limited_before": True,
         "nuisance_floor_limited_trial": False, "nuisance_resolution_sum": 1e-8,
         "inexact_profile_forcing_ratio": .001, "gain_ratio_after_profile_resolution": .2},
        {"trial": 2, "accepted": False, "nuisance_floor_limited_before": False,
         "nuisance_floor_limited_trial": True, "reason": "unresolved_nuisance_profile_reduction"},
        {"trial": 3, "accepted": False, "nuisance_floor_limited_before": False, "reason": "closure_failed"},
        {"trial": 4, "accepted": True, "nuisance_floor_limited_before": False, "nuisance_floor_limited_trial": False},
        {"confirmation": True, "accepted": True}],
        "confirmation_checks": [{"nuisance_floor_limited": True, "stationary": False},
                                {"nuisance_floor_limited": False, "stationary": True}]})
    assert summary["status"] == "reported" and summary["flagged_trials"] == 4
    assert summary["floor_limited_trials"] == 2 and summary["accepted_floor_limited_trials"] == 1
    assert summary["unresolved_profile_rejections"] == 1 and summary["floor_limited_confirmations"] == 1
    assert [row["trial"] for row in summary["floor_limited_trial_evidence"]] == [1, 2]
    stationary = nuisance_resolution({"history": [], "confirmation_checks": [{"nuisance_floor_limited": False}]})
    assert stationary["status"] == "reported" and stationary["accepted_floor_limited_trials"] == 0


def test_online_row_compression_round_trip_and_idempotent_recovery(tmp_path, monkeypatch):
    import gzip
    from orbit_poc.numerics.retention import compress_closed_row_provenance
    folder = tmp_path / "point-001-initial"; folder.mkdir()
    source = folder / "qr.1.rows.tsv"
    content = b"row\tepoch\tsource\trhs\tcolumns\n" + b"0\t0\tobservation\t.1\t0,1,2,3,4,5\n"*10000
    source.write_bytes(content)
    original_unlink = Path.unlink
    def interrupted(path, *args, **kwargs):
        if path == source: raise OSError("interrupted before original release")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        compress_closed_row_provenance(folder)
    zipped = source.with_name(source.name + ".gz")
    assert source.read_bytes() == content and gzip.decompress(zipped.read_bytes()) == content
    assert p.read_json(source.with_name(source.name + ".compression.json"))["status"] == "verified_copy"
    monkeypatch.setattr(Path, "unlink", original_unlink)
    result = compress_closed_row_provenance(folder)
    assert len(result) == 1 and not source.exists() and result[0]["round_trip_verified"]
    assert result[0]["source"]["sha256"] == hashlib.sha256(content).hexdigest()
    assert result[0]["source"]["bytes"] == len(content)
    assert p.verify_artifact(result[0]["compressed"]) == zipped.resolve()
    again = compress_closed_row_provenance(folder)
    assert again[0]["compressed"] == result[0]["compressed"]
    assert gzip.decompress(zipped.read_bytes()) == content


def test_bad_row_compression_cannot_remove_the_original(tmp_path, monkeypatch):
    import gzip
    import io
    from orbit_poc.numerics.retention import compress_row_provenance
    source = tmp_path / "qr.7.rows.tsv"; source.write_bytes(b"full row content\n")
    real_open = gzip.open
    def corrupt_round_trip(path, *args, **kwargs):
        if str(path).endswith(".copying"): return io.BytesIO(b"different bytes")
        return real_open(path, *args, **kwargs)
    monkeypatch.setattr(gzip, "open", corrupt_round_trip)
    with pytest.raises(ValueError, match="round-trip"):
        compress_row_provenance(source)
    assert source.read_bytes() == b"full row content\n"
    assert not source.with_name(source.name + ".gz").exists()


def test_native_generated_gzip_is_verified_without_a_raw_row_file(tmp_path):
    import gzip
    from orbit_poc.numerics.retention import compress_closed_row_provenance
    folder = tmp_path / "point-001-initial"; folder.mkdir()
    source = folder / "qr.1.rows.tsv"; zipped = folder / "qr.1.rows.tsv.gz"
    content = b"native generated row provenance\n" * 100
    zipped.write_bytes(gzip.compress(content, mtime=0))
    receipt = folder / "qr.1.rows.tsv.compression.json"
    record = {"policy": "verified_row_compression_v1", "role": "closed_native_row_provenance",
        "producer": "native_zlib", "status": "complete", "round_trip_verified": True,
        "source": {"path": str(source), "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)},
        "compressed": {"path": str(zipped), "sha256": p.file_hash(zipped), "bytes": zipped.stat().st_size}}
    p.write_json(receipt, record)
    result = compress_closed_row_provenance(folder)
    assert result[0]["round_trip_verified"] and not source.exists()
    assert p.read_json(receipt)["producer"] == "native_zlib"
    record["compressed"]["bytes"] += 1; p.write_json(receipt, record)
    with pytest.raises(ValueError, match="identity changed"):
        compress_closed_row_provenance(folder)
    assert gzip.decompress(zipped.read_bytes()) == content


def test_online_factor_release_keeps_accepted_newest_and_all_diagnostics(tmp_path):
    from orbit_poc.numerics.retention import discard_inactive_factors
    factors = []
    for index in range(1, 4):
        folder = tmp_path / f"point-{index:03d}-trial"; folder.mkdir()
        factor = folder / "qr.2.R.bin"; factor.write_bytes(bytes([index])*100)
        (folder / "qr.2.factor.json").write_text('{"rank":"full"}\n')
        (folder / "qr.2.rows.tsv").write_text("all row provenance\n")
        factors.append(factor)
    released_sha = p.file_hash(factors[1])
    event = discard_inactive_factors(tmp_path, protected=[factors[0]])
    assert factors[0].exists() and not factors[1].exists() and factors[2].exists()
    assert event["status"] == "complete" and event["removed_bytes"] == 100
    assert event["removed"][0]["sha256"] == released_sha
    assert event["removed"][0]["role"] == "released_triangular_factor"
    assert len(list(tmp_path.glob("point-*/*.factor.json"))) == 3
    assert len(list(tmp_path.glob("point-*/*.rows.tsv"))) == 3
    from orbit_poc.numerics.retention import compact_attempt
    failed_result = {"status": "failed", "artifacts": []}
    compact_attempt(tmp_path, failed_result, "qr_lm_staged_jacobian")
    assert factors[0].exists() and factors[2].exists()
    assert {item["path"] for item in failed_result["artifacts"] if item["role"] == "terminal_protected_qr_factor"} == {str(factors[0]), str(factors[2])}
    assert p.read_json(tmp_path / "factor-retention.json")["events"][0]["removed"] == event["removed"]
    with pytest.raises(ValueError, match="Protected factor"):
        discard_inactive_factors(tmp_path, protected=[factors[1]])


def test_factor_release_failure_preserves_file_and_deletion_proof(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import discard_inactive_factors
    first = tmp_path / "point-001-initial/qr.1.R.bin"; first.parent.mkdir(); first.write_bytes(b"first")
    newest = tmp_path / "point-002-failed/qr.1.R.bin"; newest.parent.mkdir(); newest.write_bytes(b"newest")
    original_unlink = Path.unlink
    def cannot_remove(path, *args, **kwargs):
        if path == first: raise OSError("simulated storage failure")
        return original_unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", cannot_remove)
    event = discard_inactive_factors(tmp_path)
    assert event["status"] == "partial" and event["errors"] and event["removed_bytes"] == 0
    assert first.read_bytes() == b"first" and newest.read_bytes() == b"newest"
    assert event["removed"][0]["sha256"] == hashlib.sha256(b"first").hexdigest()
    assert event["removed"][0]["status"] == "verified_before_release"
    monkeypatch.setattr(Path, "unlink", original_unlink)
    assert discard_inactive_factors(tmp_path)["status"] == "complete"
    assert not first.exists() and newest.exists()


def test_closed_closure_compaction_keeps_current_and_unmarked_partial(tmp_path, monkeypatch):
    import gzip
    from orbit_poc.numerics.retention import compact_closed_closures
    point = tmp_path / "point-001-initial"; point.mkdir()
    closures = []
    for index in range(1, 4):
        folder = point / f"closure-{index:02d}"; folder.mkdir(); closures.append(folder)
        for name in ("orbit.dat", "variational.dat", "orbit.txt", "reference.txt", "initial_design.txt", "native.log"):
            (folder / name).write_bytes((f"closure {index} {name}\n"*20).encode())
    first = compact_closed_closures(point, closures[0])
    assert first["status"] == "complete" and first["removed"] == []
    assert (closures[0] / "orbit.dat").exists() and not (closures[0] / "orbit.txt").exists()
    assert gzip.decompress((closures[0] / "orbit.txt.gz").read_bytes()).startswith(b"closure 1 orbit.txt")
    unlink = Path.unlink
    def proof_before_delete(path, *args, **kwargs):
        if path.name.endswith(".dat"):
            receipt = p.read_json(point / "closure-retention.json")
            assert any(row["path"] == str(path) and row["sha256"] == p.file_hash(path)
                       and row["status"] == "verified_before_release" for row in receipt["events"][-1]["removed"])
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", proof_before_delete)
    second = compact_closed_closures(point, "closure-02")
    assert second["status"] == "complete" and len(second["removed"]) == 2
    assert not (closures[0] / "orbit.dat").exists() and not (closures[0] / "variational.dat").exists()
    for folder in closures[1:]:
        assert (folder / "orbit.dat").exists() and (folder / "variational.dat").exists()
    assert (closures[2] / "orbit.txt").exists()  # A later partial closure was never marked complete.
    assert (closures[0] / "reference.txt").exists() and (closures[0] / "native.log").exists()
    assert compact_closed_closures(point, closures[1])["status"] == "complete"
    from orbit_poc.numerics.retention import compact_attempt
    failed = {"status": "failed", "converged": False, "covariance_valid": False, "artifacts": []}
    compact_attempt(tmp_path, failed, "qr_lm_staged_jacobian")
    protected = [item for item in failed["artifacts"] if item["role"] == "terminal_protected_closure_binary"]
    assert len(protected) == 4 and all(item["metadata"]["accepted_covariance"] is False for item in protected)
    for folder in closures[1:]:
        assert (folder / "orbit.dat").exists() and (folder / "variational.dat").exists()


def test_closed_closure_failure_preserves_recoverable_pair_and_proof(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import compact_closed_closures
    point = tmp_path / "point-001-initial"; point.mkdir()
    for index in (1, 2):
        folder = point / f"closure-{index:02d}"; folder.mkdir()
        for name in ("orbit.dat", "variational.dat", "orbit.txt"):
            (folder / name).write_bytes(name.encode())
    compact_closed_closures(point, "closure-01")
    victim = point / "closure-01/orbit.dat"
    unlink = Path.unlink
    def fail_release(path, *args, **kwargs):
        if path == victim: raise OSError("simulated closure release failure")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_release)
    event = compact_closed_closures(point, "closure-02")
    assert event["status"] == "partial" and event["errors"] and victim.exists()
    assert (point / "closure-02/orbit.dat").exists() and (point / "closure-02/variational.dat").exists()
    assert any(row["path"] == str(victim) and row["status"] == "verified_before_release" for row in event["removed"])
    monkeypatch.setattr(Path, "unlink", unlink)
    assert compact_closed_closures(point, "closure-02")["status"] == "complete"
    assert not victim.exists()


def test_closed_closure_rejects_missing_current_or_symlink(tmp_path):
    from orbit_poc.numerics.retention import compact_closed_closures
    point = tmp_path / "point-001-initial"; point.mkdir()
    current = point / "closure-01"; current.mkdir(); (current / "orbit.dat").write_bytes(b"partial")
    with pytest.raises(ValueError, match="missing a required binary"):
        compact_closed_closures(point, current)
    assert (current / "orbit.dat").read_bytes() == b"partial"
    alias = point / "closure-02"; alias.symlink_to(current, target_is_directory=True)
    with pytest.raises(ValueError, match="regular closure directory"):
        compact_closed_closures(point, alias)
    assert not (point / "closure-retention.json").exists()


def test_completed_proposal_preserves_metrics_text_parameters_and_proof(tmp_path, monkeypatch):
    import gzip
    from orbit_poc.numerics.retention import compact_closed_proposal
    folder = tmp_path / "proposal-001"; folder.mkdir()
    binary = folder / "orbit.dat"; binary.write_bytes(b"generated proposal binary")
    content = b"trajectory rows\n" * 100
    (folder / "orbit.txt").write_bytes(content)
    (folder / "parameters.txt").write_text("0.1 0.2\n")
    (folder / "native.log").write_text("native diagnostic\n")
    metrics = {"position_change_m": .1, "density_update": .01, "pulse_update_m_s": 0.}
    unlink = Path.unlink
    def checked_release(path, *args, **kwargs):
        if path == binary:
            proof = p.read_json(folder / "proposal-retention.json")
            assert proof["binary"]["sha256"] == p.file_hash(path)
            assert proof["binary"]["status"] == "verified_before_release"
            assert proof["metrics"] == metrics
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", checked_release)
    result = compact_closed_proposal(folder, metrics)
    assert result["status"] == "complete" and not binary.exists()
    assert gzip.decompress((folder / "orbit.txt.gz").read_bytes()) == content
    assert (folder / "parameters.txt").read_text() == "0.1 0.2\n"
    assert (folder / "native.log").is_file()
    assert compact_closed_proposal(folder, metrics)["status"] == "complete"
    with pytest.raises(ValueError, match="metrics changed"):
        compact_closed_proposal(folder, {**metrics, "position_change_m": .2})


def test_partial_proposal_is_not_compacted(tmp_path):
    from orbit_poc.numerics.retention import compact_closed_proposal
    folder = tmp_path / "proposal-002"; folder.mkdir()
    binary = folder / "orbit.dat"; binary.write_bytes(b"partial failed proposal")
    with pytest.raises(ValueError, match="Missing row ledger"):
        compact_closed_proposal(folder, {"position_change_m": .1})
    assert binary.read_bytes() == b"partial failed proposal"
    assert not (folder / "proposal-retention.json").exists()


def test_proposal_release_failure_keeps_binary_and_can_retry(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import compact_closed_proposal
    folder = tmp_path / "proposal-003"; folder.mkdir()
    binary = folder / "orbit.dat"; binary.write_bytes(b"generated binary")
    (folder / "orbit.txt").write_text("full trajectory\n")
    unlink = Path.unlink
    def cannot_release(path, *args, **kwargs):
        if path == binary: raise OSError("simulated release failure")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", cannot_release)
    result = compact_closed_proposal(folder, {"position_change_m": .1})
    assert result["status"] == "partial" and binary.exists() and result["errors"]
    monkeypatch.setattr(Path, "unlink", unlink)
    result = compact_closed_proposal(folder, {"position_change_m": .1})
    assert result["status"] == "complete" and not binary.exists() and result["errors"]


def test_proposal_interruption_after_unlink_keeps_recovery_proof(tmp_path, monkeypatch):
    from orbit_poc.numerics.retention import compact_closed_proposal
    folder = tmp_path / "proposal-004"; folder.mkdir()
    binary = folder / "orbit.dat"; binary.write_bytes(b"generated binary")
    (folder / "orbit.txt").write_text("full trajectory\n")
    unlink = Path.unlink
    def interrupted_release(path, *args, **kwargs):
        result = unlink(path, *args, **kwargs)
        if path == binary: raise KeyboardInterrupt("simulated interruption")
        return result
    monkeypatch.setattr(Path, "unlink", interrupted_release)
    with pytest.raises(KeyboardInterrupt): compact_closed_proposal(folder, {"position_change_m": .1})
    assert not binary.exists()
    assert p.read_json(folder / "proposal-retention.json")["binary"]["status"] == "verified_before_release"
    monkeypatch.setattr(Path, "unlink", unlink)
    result = compact_closed_proposal(folder, {"position_change_m": .1})
    assert result["status"] == "complete" and result["binary"]["status"] == "absent_after_verified_release"


@pytest.mark.parametrize("corrupt_remaining", [False, True])
def test_archive_recovers_interrupted_verified_source_cleanup(tmp_path, monkeypatch, corrupt_remaining):
    from orbit_poc.numerics.storage import archive_attempt
    working = tmp_path / "working/attempt"; working.mkdir(parents=True)
    (working / "result-record.json").write_text('{}')
    (working / "first.dat").write_bytes(b"first exact artifact")
    (working / "second.dat").write_bytes(b"second exact artifact")
    destination = tmp_path / "archive"; receipt = tmp_path / "archive-receipt.json"
    backup = working.with_name(".attempt.archiving")
    rmtree = shutil.rmtree
    def interrupted_cleanup(path, *args, **kwargs):
        if Path(path) == backup:
            assert p.read_json(receipt)["working_copy_release_started"] is True
            (backup / "first.dat").unlink()
            raise KeyboardInterrupt("simulated interrupted cleanup")
        return rmtree(path, *args, **kwargs)
    monkeypatch.setattr(shutil, "rmtree", interrupted_cleanup)
    with pytest.raises(KeyboardInterrupt): archive_attempt(working, destination, receipt, reserve_bytes=0)
    assert working.is_symlink() and (working / "first.dat").read_bytes() == b"first exact artifact"
    assert backup.exists() and not (backup / "first.dat").exists()
    monkeypatch.setattr(shutil, "rmtree", rmtree)
    if corrupt_remaining:
        (backup / "second.dat").write_bytes(b"changed remaining artifact")
        with pytest.raises(ValueError, match="Partially released"):
            archive_attempt(working, destination, receipt, reserve_bytes=0)
        assert backup.exists() and (working / "second.dat").read_bytes() == b"second exact artifact"
    else:
        result = archive_attempt(working, destination, receipt, reserve_bytes=0)
        assert result["status"] == "complete" and result["working_copy_release_recovered"]
        assert not backup.exists() and (working / "second.dat").read_bytes() == b"second exact artifact"



def test_archive_resumes_partial_staging_with_an_existing_symlink(tmp_path, monkeypatch):
    from orbit_poc.numerics.storage import archive_attempt
    working = tmp_path / "working/attempt"; working.mkdir(parents=True)
    (working / "result-record.json").write_text('{}')
    (working / "final.dat").write_bytes(b"complete final data")
    (working / "alias").symlink_to("final.dat")
    destination = tmp_path / "archive"; receipt = tmp_path / "archive-receipt.json"
    copy = shutil.copy2
    def interrupted_copy(source, target, *args, **kwargs):
        if Path(target).name == "final.dat":
            Path(target).write_bytes(b"partial copy")
            raise KeyboardInterrupt("simulated interruption while copying")
        return copy(source, target, *args, **kwargs)
    monkeypatch.setattr(shutil, "copy2", interrupted_copy)
    with pytest.raises(KeyboardInterrupt): archive_attempt(working, destination, receipt, reserve_bytes=0)
    assert (destination / ".attempt.copying/alias").is_symlink()
    assert working.is_dir() and not working.is_symlink()
    monkeypatch.setattr(shutil, "copy2", copy)
    assert archive_attempt(working, destination, receipt, reserve_bytes=0)["status"] == "complete"
    assert (working / "alias").is_symlink() and (working / "alias").read_bytes() == b"complete final data"



def _campaign_driver_inputs(config, directory):
    configuration = directory / "launch-config.json"
    startup = directory / "startup.json"
    p.write_json(configuration, asdict(config))
    p.write_json(startup, {"status": "verified", "configuration": p.artifact(configuration),
                          "execution_context": asdict(config.execution_context)})
    return configuration, startup


@pytest.mark.parametrize("signum", [2, 15])
def test_campaign_driver_reports_interruption_and_never_retries_partial_fit(prepared_campaign, monkeypatch, signum):
    import signal
    from orbit_poc.numerics.campaign import run_to_report
    config, root, project, count, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    calls = []
    def interrupted(*args, **kwargs):
        calls.append(1)
        if signum == signal.SIGINT: raise KeyboardInterrupt("test interruption")
        os.kill(os.getpid(), signal.SIGTERM)
    monkeypatch.setattr(p, "_execute_job", interrupted)
    previous = signal.getsignal(signal.SIGTERM)
    result = run_to_report(configuration, startup, project=project)
    assert result["status"] == "interrupted" and result["exit_code"] == 128+signum
    assert signal.getsignal(signal.SIGTERM) == previous
    report = p.read_json(result["report"]["report"])
    assert len(report["attempts"]) == 150 and report["terminal_attempts"] == 0
    assert any(row["status"] == "interrupted_or_running" for row in report["attempts"])
    first_receipt = p.read_json(result["receipt"]["path"])
    assert first_receipt["phase"] == "finished" and first_receipt["signals"] == [signum]
    assert len(first_receipt["report_artifacts"]) == 2
    resumed = run_to_report(configuration, startup, project=project)
    assert resumed["status"] == "blocked" and resumed["run"]["jobs_started"] == 0
    assert len(calls) == 1  # No retry or checkpoint fabrication.
    assert resumed["receipt"]["path"] != result["receipt"]["path"]
    for item in first_receipt["report_artifacts"]: p.verify_artifact(item)


def test_campaign_driver_reports_execution_exception(prepared_campaign, monkeypatch):
    from orbit_poc.numerics.campaign import run_to_report
    config, root, project, _, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    def failed(*args, **kwargs): raise RuntimeError("execution failed")
    monkeypatch.setattr(p, "run", failed)
    result = run_to_report(configuration, startup, project=project)
    assert result["status"] == "failed" and result["exit_code"] == 1
    assert "execution failed" in result["error"] and result["report"]["expected_attempts"] == 150
    assert p.read_json(result["receipt"]["path"])["traceback"]


def test_campaign_driver_records_report_failure(prepared_campaign, monkeypatch):
    from orbit_poc.numerics import campaign
    config, root, project, _, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    original = campaign.create_report; calls = []
    def reporting(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2: raise OSError("report storage unavailable")
        return original(*args, **kwargs)
    monkeypatch.setattr(campaign, "create_report", reporting)
    monkeypatch.setattr(p, "run", lambda *args, **kwargs: {"status": "complete", "terminal_attempts": 150})
    result = campaign.run_to_report(configuration, startup, project=project)
    assert result["status"] == "failed" and result["exit_code"] == 1
    assert "report storage unavailable" in result["report_error"]
    assert p.read_json(result["receipt"]["path"])["phase"] == "finished"


def test_campaign_driver_rejects_stale_startup_and_configuration_changes(prepared_campaign, monkeypatch):
    from orbit_poc.numerics.campaign import run_to_report
    config, root, project, _, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    startup_record = p.read_json(startup); startup_record["configuration"]["sha256"] = "f"*64
    p.write_json(startup, startup_record)
    with pytest.raises(ValueError, match="Startup runtime verification"):
        run_to_report(configuration, startup, project=project)
    assert not (root / "controller").exists()
    configuration, startup = _campaign_driver_inputs(config, root)
    def change_config(*args, **kwargs):
        configuration.write_text(configuration.read_text()+"\n")
        return {"status": "complete", "terminal_attempts": 150}
    monkeypatch.setattr(p, "run", change_config)
    result = run_to_report(configuration, startup, project=project)
    assert result["status"] == "failed" and "Configuration file changed" in result["error"]
    assert result["report"]["expected_attempts"] == 150


def test_campaign_driver_resumes_terminal_results_and_reports_each_bounded_launch(prepared_campaign, monkeypatch):
    from orbit_poc.numerics.campaign import run_to_report
    config, root, project, _, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    calls = []
    def terminal_failure(*args, **kwargs):
        calls.append(1)
        return {"status": "failed", "converged": False, "covariance_valid": False,
                "error": "Controlled test failure", "artifacts": []}
    monkeypatch.setattr(p, "_execute_job", terminal_failure)
    first = run_to_report(configuration, startup, max_attempts=1, project=project)
    assert first["status"] == "partial" and first["exit_code"] == 0
    assert first["report"]["terminal_attempts"] == 1
    previous = p.read_json(first["receipt"]["path"])
    startup.write_text(startup.read_text()+"\n")  # A later verifier may republish its configured receipt path.
    second = run_to_report(configuration, startup, max_attempts=1, project=project)
    assert second["status"] == "partial" and second["report"]["terminal_attempts"] == 2
    assert len(calls) == 2
    for item in previous["report_artifacts"]: p.verify_artifact(item)
    p.verify_artifact(previous["startup_receipt"])
    p.verify_artifact(previous["configuration_copy"])



def test_campaign_driver_finishes_report_after_a_reporting_phase_signal(prepared_campaign, monkeypatch):
    import signal
    from orbit_poc.numerics import campaign
    config, root, project, _, _ = prepared_campaign
    configuration, startup = _campaign_driver_inputs(config, root)
    original = campaign.create_report; calls = []
    def reporting(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2: os.kill(os.getpid(), signal.SIGTERM)
        return original(*args, **kwargs)
    monkeypatch.setattr(campaign, "create_report", reporting)
    monkeypatch.setattr(p, "run", lambda *args, **kwargs: {"status": "partial", "terminal_attempts": 0})
    result = campaign.run_to_report(configuration, startup, project=project)
    assert result["status"] == "interrupted" and result["exit_code"] == 143
    assert result["report"]["expected_attempts"] == 150
    record = p.read_json(result["receipt"]["path"])
    assert record["phase"] == "finished" and record["signals"] == [15]


def test_report_storage_policy_requires_verified_context(tmp_path):
    from orbit_poc.numerics.report import execution_storage
    assert execution_storage(None)["status"] == "unavailable"
    context = tmp_path / "execution-context.json"
    p.write_json(context, {"storage_policy": "Common D/DrvFs output", "timing_policy": "I/O included",
                           "physical_backing_path": "/mnt/d", "acceptance_gates": []})
    reference = p.artifact(context)
    result = execution_storage(reference)
    assert result["status"] == "reported" and result["physical_backing_path"] == "/mnt/d"
    assert result["timing_policy"] == "I/O included" and "acceptance_gates" not in result
    context.write_text("{}")
    assert execution_storage(reference)["status"] == "invalid"
