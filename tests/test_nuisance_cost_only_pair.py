"""Frozen cost-only treatment binding and unchanged scientific rejection gates."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys

import pytest

ROOT = Path(__file__).parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


check = load("cost_only_checker", ROOT / "scripts/check_nuisance_cost_only_pair.py")
fixture = load("existing_pair_fixture", ROOT / "tests/test_nuisance_performance_pair.py")
write = fixture.write


def pin(path):
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def reseal(root):
    freeze_path = root / "freeze.json"
    freeze = json.loads(freeze_path.read_text())
    for job in freeze["jobs"]:
        execution_path = Path(job["profile"]).parent / "profile.execution.json"
        if execution_path.exists():
            execution = json.loads(execution_path.read_text())
            execution["freeze_sha256"] = pin(freeze_path)["sha256"]
            write(execution_path, execution)


def campaign(tmp_path, *, method="pulses", accumulate=0, floor=False):
    native = tmp_path / "native"; native.write_bytes(b"never executed synthetic native")
    runner = tmp_path / "runner.py"; runner.write_text("# never executed\n")
    supervisor_source = tmp_path / "supervisor.py"; supervisor_source.write_text("# never executed\n")
    library = tmp_path / "runtime.so"; library.write_bytes(b"frozen runtime library")
    build = write(tmp_path / "build.json", {"executable_sha256": pin(native)["sha256"]})
    fixed = dict(check.FIXED_NATIVE, **{key: "1" for key in check.THREAD_KEYS}, LD_LIBRARY_PATH="/fixed/runtime")
    old_jobs, jobs = [], []
    for meth in check.PRIOR:
        input_file = tmp_path / (meth + ".input"); input_file.write_text("physical data and nonzero prior\n")
        for acc in (0, 1):
            original_root = tmp_path / f"source-{meth}-{acc}"; original_root.mkdir()
            original = original_root / "profile.xml"
            original.write_text(f'<groops><global><filename label="tmpDir">{original_root}/tmp</filename></global>'
                f'<inputfileObservations>{input_file}</inputfileObservations><physicalScale>1</physicalScale>'
                f'<accumulateEpochObservations>{acc}</accumulateEpochObservations>'
                f'<outputfilePrefix>{original_root}/qr</outputfilePrefix>'
                f'<outputfileOrbit>{original_root}/output/orbit.txt</outputfileOrbit></groops>')
            old_jobs.append({"method": meth, "accumulate": acc, "cache": 1, "profile": str(original),
                             "profile_sha256": pin(original)["sha256"], "input_files": [pin(input_file)]})
            for flag in (0, 1):
                name = f"{meth}-accumulate{acc}-cost{flag}"
                run = fixture.make_run(tmp_path / name, cpu=float(flag + 1), floor=floor)
                profile = run / "profile.xml"
                profile.write_bytes(original.read_bytes().replace(str(original_root).encode(), str(run).encode()))
                job = {"name": name, "method": meth, "accumulate": acc, "cost_only_design": flag, "cache": 1,
                       "profile": str(profile), "profile_sha256": pin(profile)["sha256"],
                       "source_profile": pin(original), "input_files": [pin(input_file)]}
                jobs.append(job)
                argv = ["/usr/bin/taskset", "-c", "0", str(native), str(profile)]
                supervisor = json.loads((run / "supervisor.json").read_text()); supervisor["argv"] = argv
                write(run / "supervisor.json", supervisor)
                execution = json.loads((run / "profile.execution.json").read_text())
                execution.update(command=argv, supervisor_sha256=pin(run / "supervisor.json")["sha256"],
                    config_sha256=job["profile_sha256"], native_binary_sha256=pin(native)["sha256"],
                    accumulate_epoch_observations=acc, cost_only_design=flag, cache=1,
                    environment=dict(fixed, ORBIT_POC_NUISANCE_COST_ONLY_DESIGN=str(flag),
                                     ORBIT_POC_NUMERICS_QR_PREFIX=str(run / "qr")))
                write(run / "profile.execution.json", execution)
                for generation in (1, 2, 3):
                    (run / f"qr.{generation}.rows.tsv").write_text("row\tepoch\tsource\trhs\tcolumns\n"
                        f"0\t0\tweighted_observation\t2\t0\n1\t0\t{check.PRIOR[meth]}\t0.5\t0\n")
                    if generation == 3:
                        continue
                    search = json.loads((run / f"qr.{generation}.nuisance_line_search.json").read_text())
                    row = {"available": True, "completed": True, "cost_only": False,
                        "cost_only_design": bool(flag), "omitted_dynamic_designs": 0,
                        "interpolation_cache": True, "interpolation_calls": 2,
                        "interpolation_cache_hits": 1, "interpolation_evaluations": 1,
                        "build_wall_seconds": 1., "observation_design_wall_seconds": .5,
                        "observation_design_calls": 2, "interpolation_wall_seconds": .2}
                    child_row = dict(row, cost_only=True, omitted_dynamic_designs=2 if flag else 0,
                        interpolation_calls=0 if flag else 2, interpolation_cache_hits=0 if flag else 1,
                        interpolation_evaluations=0 if flag else 1)
                    child = {"status": 0, "wall_seconds": 1., "row_build": child_row}
                    trial = {**child, **{k: search["trials"][0][k] for k in check.base.STRIPPED_TRIAL_FIELDS}}
                    write(run / f"qr.{generation}.nuisance_performance.json", {
                        "schema": "orbit-poc-nuisance-performance-v1", "parent_row_build": row,
                        "zero_update_replay": child, "ordinary_trials": [trial], "arithmetic_audits": [], "probe_rounds": []})
    preparation = write(tmp_path / "preparation.json", {"schema": "orbit-poc-nuisance-pair-preparation-v1", "jobs": old_jobs})
    write(tmp_path / "freeze.json", {"schema": "orbit-poc-cost-only-pair-freeze-v1", "cpu": 0,
        "one_numerical_thread": True, "native": pin(native), "runner": pin(runner), "build_manifest": pin(build),
        "supervisor": pin(supervisor_source), "libraries": [pin(library)],
        "source_preparation": pin(preparation), "environment_fixed": fixed, "jobs": jobs})
    reseal(tmp_path)
    return (tmp_path / f"{method}-accumulate{accumulate}-cost0",
            tmp_path / f"{method}-accumulate{accumulate}-cost1")


def change(path, mutate):
    value = json.loads(path.read_text()); mutate(value); write(path, value)


@pytest.mark.parametrize("method,accumulate", [(m, a) for m in check.PRIOR for a in (0, 1)])
def test_accepts_exact_science_and_measured_treatment_without_full_fit_claim(tmp_path, method, accumulate):
    off, on = campaign(tmp_path, method=method, accumulate=accumulate)
    result = check.compare(off, on)
    assert result["passed"], result["issues"]
    assert result["artifact_equality"] and result["cost_only_pair_verified"]
    assert result["scientific_comparison_count"] > 30
    assert result["removed_fields"]["nuisance_line_search.trials[*]"] == list(check.base.STRIPPED_TRIAL_FIELDS)
    assert all(result[k] is False for k in ("accepted_covariance", "whole_fit_convergence_established",
                                           "full_fit_verified", "release_authority"))
    assert result["frozen_experiment"]["observed"][1]["metrics"]["omitted_dynamic_designs"] > 0


@pytest.mark.parametrize("field,value", [("cost_only_design", 0), ("cost_only_design", True), ("cache", 0),
    ("accumulate_epoch_observations", 1), ("blas_openmp_threads", 2), ("input_identity_after", "unchecked"),
    ("native_binary_sha256", "a"*64), ("freeze_sha256", "b"*64), ("environment", {}),
    ("owned_process_group_cleaned", False), ("returncode", 1), ("timed_out", True)])
def test_execution_binding_rejects_even_with_identical_science(tmp_path, field, value):
    off, on = campaign(tmp_path)
    change(on / "profile.execution.json", lambda x: x.__setitem__(field, value))
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["passed"]


@pytest.mark.parametrize("key", ["native", "runner", "build_manifest", "source_preparation", "supervisor"])
def test_frozen_files_rehashed_from_actual_bytes(tmp_path, key):
    off, on = campaign(tmp_path)
    freeze = json.loads((tmp_path / "freeze.json").read_text())
    path = Path(freeze[key]["path"]); path.write_bytes(path.read_bytes() + b" ")
    assert not check.compare(off, on)["passed"]


@pytest.mark.parametrize("key", ["supervisor", "libraries"])
def test_missing_runtime_controller_inventory_rejected(tmp_path, key):
    off, on = campaign(tmp_path)
    change(tmp_path / "freeze.json", lambda x: x.pop(key))
    reseal(tmp_path)
    assert not check.compare(off, on)["passed"]


def test_build_must_bind_native_even_when_both_files_resealed(tmp_path):
    off, on = campaign(tmp_path)
    write(tmp_path / "build.json", {"executable_sha256": "a"*64})
    change(tmp_path / "freeze.json", lambda x: x.__setitem__("build_manifest", pin(tmp_path / "build.json")))
    reseal(tmp_path)
    assert not check.compare(off, on)["passed"]


def test_pinned_runtime_symlink_is_supported_and_actual_target_is_rehashed(tmp_path):
    off, on = campaign(tmp_path)
    library = tmp_path / "library.so.1.2"; library.write_bytes(b"runtime bytes")
    alias = tmp_path / "library.so.1"; alias.symlink_to(library)
    change(tmp_path / "freeze.json", lambda x: x.__setitem__("libraries", [pin(alias)]))
    reseal(tmp_path)
    result = check.compare(off, on)
    assert result["passed"], result["issues"]
    assert any(p["requested_path"] == str(alias) and p["path"] == str(library)
               for p in result["frozen_experiment"]["provenance"])
    library.write_bytes(b"changed runtime")
    assert not check.compare(off, on)["passed"]


def test_actual_input_mutation_rejected(tmp_path):
    off, on = campaign(tmp_path)
    (tmp_path / "pulses.input").write_text("changed physical input")
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["cost_only_pair_verified"]


def test_resealed_incomplete_input_inventory_rejected(tmp_path):
    off, on = campaign(tmp_path)
    change(tmp_path / "freeze.json", lambda x: x["jobs"][0].__setitem__("input_files", []))
    reseal(tmp_path)
    assert not check.compare(off, on)["passed"]


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "cache", "bool", "cpu", "environment"])
def test_resealed_invalid_freeze_rejected(tmp_path, mutation):
    off, on = campaign(tmp_path)
    def mutate(x):
        if mutation == "missing": x["jobs"].pop()
        elif mutation == "duplicate": x["jobs"][-1] = x["jobs"][0]
        elif mutation == "cache": x["jobs"][-1]["cache"] = 0
        elif mutation == "bool": x["jobs"][-1]["accumulate"] = True
        elif mutation == "cpu": x["cpu"] = 2
        else: x["environment_fixed"]["ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS"] = "64"
    change(tmp_path / "freeze.json", mutate); reseal(tmp_path)
    assert not check.compare(off, on)["passed"]


def test_resealed_xml_physics_change_rejected(tmp_path):
    off, on = campaign(tmp_path)
    xml = on / "profile.xml"; xml.write_bytes(xml.read_bytes().replace(b"<physicalScale>1", b"<physicalScale>2"))
    change(tmp_path / "freeze.json", lambda x: next(j for j in x["jobs"] if j["profile"] == str(xml)).__setitem__("profile_sha256", pin(xml)["sha256"]))
    change(on / "profile.execution.json", lambda x: x.__setitem__("config_sha256", pin(xml)["sha256"]))
    reseal(tmp_path)
    result = check.compare(off, on)
    assert not result["passed"] and any("substitution" in x["message"] for x in result["issues"])


def test_root_substitution_cannot_rewrite_input_paths(tmp_path):
    source_path, actual_path = tmp_path / "old/profile.xml", tmp_path / "new/profile.xml"
    source = f'<groops><inputfileObservations>{source_path.parent}/data</inputfileObservations></groops>'.encode()
    actual = source.replace(str(source_path.parent).encode(), str(actual_path.parent).encode())
    with pytest.raises(ValueError, match="non-output"):
        check.verify_xml(source, actual, source_path, actual_path, 0)


@pytest.mark.parametrize("field,value", [("cost_only_design", False), ("omitted_dynamic_designs", 0),
    ("cost_only", False), ("interpolation_cache", False), ("available", False), ("completed", False),
    ("interpolation_calls", 1), ("omitted_dynamic_designs", True)])
def test_child_measurements_must_demonstrate_cost_only_omission(tmp_path, field, value):
    off, on = campaign(tmp_path)
    change(on / "qr.1.nuisance_performance.json", lambda x: x["zero_update_replay"]["row_build"].__setitem__(field, value))
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["passed"]


def test_parent_and_disabled_children_cannot_omit_designs(tmp_path):
    off, on = campaign(tmp_path)
    change(on / "qr.1.nuisance_performance.json", lambda x: x["parent_row_build"].__setitem__("omitted_dynamic_designs", 1))
    assert not check.compare(off, on)["passed"]
    change(on / "qr.1.nuisance_performance.json", lambda x: x["parent_row_build"].__setitem__("omitted_dynamic_designs", 0))
    change(off / "qr.1.nuisance_performance.json", lambda x: x["ordinary_trials"][0]["row_build"].__setitem__("omitted_dynamic_designs", 1))
    assert not check.compare(off, on)["passed"]


@pytest.mark.parametrize("name", ["qr.2.nuisance_performance.json", "qr.3.R.bin", "qr.1.rows.tsv", "qr.2.receiver_times.tsv"])
def test_missing_evidence_rejected_even_on_both_sides(tmp_path, name):
    off, on = campaign(tmp_path)
    (off / name).unlink(); (on / name).unlink()
    assert not check.compare(off, on)["passed"]


@pytest.mark.parametrize("rhs", ["0", "nan"])
def test_equal_missing_nonzero_prior_evidence_rejected(tmp_path, rhs):
    off, on = campaign(tmp_path)
    for run in (off, on):
        path = run / "qr.1.rows.tsv"; path.write_text(path.read_text().replace("\t0.5\t", f"\t{rhs}\t"))
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["passed"]


@pytest.mark.parametrize("name,field,value", [("qr.profile.json", "threshold_m", 1e-6),
    ("qr.3.diagnostics.json", "lambda", 1), ("qr.3.diagnostics.json", "rank_status", "deficient")])
def test_unchanged_scientific_gates_reject_equal_invalid_results(tmp_path, name, field, value):
    off, on = campaign(tmp_path)
    for run in (off, on): change(run / name, lambda x: x.__setitem__(field, value))
    result = check.compare(off, on)
    assert result["artifact_equality"] and not result["passed"]


@pytest.mark.parametrize("field", ["full_step_prediction", "wall_seconds"])
def test_no_additional_scientific_json_fields_stripped(tmp_path, field):
    off, on = campaign(tmp_path)
    change(on / "qr.1.nuisance_line_search.json", lambda x: x.__setitem__(field, 17.))
    assert not check.compare(off, on)["passed"]


def test_binary_one_ulp_change_rejected(tmp_path):
    off, on = campaign(tmp_path)
    (on / "qr.3.R.bin").write_bytes(struct.pack("<QQd", 1, 1, 2.0000000000000004))
    assert not check.compare(off, on)["passed"]


def test_compressed_rows_preserve_exact_scientific_payload(tmp_path):
    off, on = campaign(tmp_path)
    rows = on / "qr.1.rows.tsv"; rows.with_suffix(".tsv.gz").write_bytes(gzip.compress(rows.read_bytes())); rows.unlink()
    assert check.compare(off, on)["passed"]


def test_floor_equality_remains_progress_only(tmp_path):
    off, on = campaign(tmp_path, floor=True)
    result = check.compare(off, on)
    assert result["passed"] and result["accepted_covariance"] is False
    assert all(x["profile_classification"] == "floor_limited_progress_only" for x in result["runs"])


def test_off_off_cross_accumulation_and_missing_run_reject(tmp_path):
    off, on = campaign(tmp_path)
    assert not check.compare(off, off)["passed"]
    assert not check.compare(off, tmp_path / "pulses-accumulate1-cost1")["passed"]
    result = check.compare(off, tmp_path / "absent")
    assert not result["passed"] and len(result["runs"]) == 2


def test_cli_refuses_to_overwrite_output_and_inputs_are_unchanged(tmp_path, monkeypatch):
    off, on = campaign(tmp_path)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    output = tmp_path / "result.json"
    monkeypatch.setattr(sys, "argv", [str(ROOT / "scripts/check_nuisance_cost_only_pair.py"), str(off), str(on), "--output", str(output)])
    assert check.main() == 0
    assert json.loads(output.read_text())["passed"]
    with pytest.raises(FileExistsError): check.main()
    assert all(Path(p).read_bytes() == data for p, data in before.items())
