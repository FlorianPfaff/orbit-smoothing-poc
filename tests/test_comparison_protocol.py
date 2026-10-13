"""Protocol tests use explicit fake backends, never scientific result claims."""
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from orbit_poc.comparison.config import ComparisonConfig, config_from_dict
from orbit_poc.comparison import protocol as p


@pytest.fixture(autouse=True)
def fixed_source(monkeypatch):
    monkeypatch.setattr(p, "source_snapshot", lambda: {"sha256": "a" * 64, "files": {}})


def artifact(root, role, name=None, **metadata):
    root.mkdir(parents=True, exist_ok=True)
    path = root / (name or role)
    path.write_text(role)
    return p.artifact_record(role, path, **metadata)


def fake_acceptance(config, root):
    """Explicit orchestration fixture, never real numerical acceptance evidence."""
    from orbit_poc.comparison.gates import PRECALIBRATION_GATES
    frozen = p.freeze_protocol(config, root)
    evidence = artifact(root, "fake_test_evidence")
    record = {"schema_version": 3, "protocol_hash": frozen["protocol_hash"], "gates": {
        name: {"passed": True, "completed_at": f"2026-01-01T00:00:0{i}+00:00",
               "artifacts": [evidence]} for i, name in enumerate(PRECALIBRATION_GATES)}}
    record["evidence_hash"] = p.canonical_hash(record)
    p.write_json(root / "acceptance-gates.json", record)
    return record


class FakeBackend:
    def __init__(self):
        self.calls = []

    def prepare_job(self, job, directory):
        self.calls.append(job)
        inputs = [artifact(directory, role) for role in (
            "gnss_observations", "gnss_orbits", "gnss_clocks", "attitude",
            "spacecraft_metadata", "earth_orientation", "force_auxiliary")]
        inputs.append(artifact(directory, "bootstrap_orbit", provenance="gnss_only"))
        result = {"status": "prepared", "estimation_inputs": inputs,
                  "evaluation_inputs": [artifact(directory, "truth")],
                  "force_model_hash": "b" * 64, "measurement_model_hash": "c" * 64,
                  "preprocessing_hash": "d" * 64, "mask_hash": p.canonical_hash(job["case"]["mask"])}
        if job["split"] == "calibration":
            result["calibration_inputs"] = [artifact(directory, "heldout_gnss_code")]
        return result

    def fit_job(self, job, directory):
        self.calls.append(job)
        assert "evaluation_inputs" not in job
        assert "calibration_inputs" not in job
        assert all(record["role"] in p.ESTIMATION_ROLES for record in job["estimation_inputs"])
        return {"status": "complete", "converged": True, "covariance_valid": True,
                "covariance_scope": "marginalized", "parameter_blocks": ["orbit", "clock", "ambiguity"],
                "artifacts": [artifact(directory, "test_fit")], "parameters": job["parameters"]}

    def evaluate_job(self, job, result, directory):
        self.calls.append(job)
        result = {"status": "complete", "artifacts": [artifact(directory, "test_score")]}
        if job["split"] == "calibration":
            assert "evaluation_inputs" not in job
            assert all(item["role"] == "heldout_gnss_code" for item in job["calibration_inputs"])
            result["calibration_score"] = {"valid": True, "mean_nll": 1., "retained_dimensions": 5}
            result["predictive_support_sha256"] = "a" * 64
        else:
            assert job.get("frozen_evaluation") is True
            result["metrics"] = {"position_rmse_m": 1.}
        return result


def test_defaults_define_full_independent_campaign():
    config = ComparisonConfig().validate()
    assert len(p.case_matrix(config, "synthetic", "calibration")) == 48
    assert len(p.case_matrix(config, "synthetic", "evaluation")) == 800
    assert len(p.case_matrix(config, "flight", "calibration")) == 12
    assert len(p.case_matrix(config, "flight", "evaluation")) == 12
    assert len(p.initial_candidates(config, "groops_pulses")) == 16
    assert len(p.initial_candidates(config, "groops_log_drag_ou")) == 16
    assert config.synthetic.cadence_seconds == 30
    assert config.density.knot_seconds == 60
    assert config.synthetic.evaluation_seeds[0] == 400000


def test_different_native_preprocessing_blocks_candidate_or_arm_comparison(tmp_path):
    class ChangedWeightsBackend(FakeBackend):
        def fit_job(self, job, directory):
            return {**super().fit_job(job, directory), "native_binary_sha256": "b" * 64,
                    "metadata": {"preprocessing_audit_sha256": p.canonical_hash(job["parameters"])}}
    config = ComparisonConfig()
    frozen = p.freeze_protocol(config, tmp_path)
    backend = ChangedWeightsBackend()
    runner = p.Runner(tmp_path, backend=backend)
    case = p.case_matrix(config, "synthetic", "calibration")[0]
    prepared = p._prepared(runner, frozen, "synthetic", "calibration", case)
    first = p._fit(runner, frozen, "synthetic", "calibration", case, prepared,
                   "groops_pulses", {"sigma_velocity_m_s": .001})
    assert first["status"] == "complete"
    with pytest.raises(p.BackendBlocked, match="Common preprocessing differs"):
        p._fit(runner, frozen, "synthetic", "calibration", case, prepared,
               "groops_log_drag_ou", {"sigma_log_density": .3})


@pytest.mark.parametrize("change", [
    {"unrecognized": 1}, {"density": {"mystery": 2}}, {"density": {"knot_seconds": True}},
    {"flight": {"ambiguity_policy": "integer"}}, {"density": {"empirical_acceleration": True}},
    {"synthetic": {"calibration_seeds": [1, 1, 2, 3, 4, 5]}},
    {"synthetic": {"evaluation_seeds": list(range(42, 92))}},
    {"pulses": {"sigma_velocity_m_s": [1, 2, 3, float("nan")]}}
])
def test_invalid_or_unknown_protocol_options_rejected(change):
    with pytest.raises(ValueError):
        config_from_dict(change)


def test_stage_mask_conventions_are_explicit():
    config = ComparisonConfig()
    synthetic = p.case_matrix(config, "synthetic", "calibration")[0]
    flight = p.case_matrix(config, "flight", "calibration")[0]
    assert synthetic["mask"] == {"intervals_seconds": [[42300, 44100]], "cadence_seconds": 30., "time_scale": "elapsed"}
    assert flight["mask"]["time_scale"] == "UTC"
    assert flight["mask"]["cadence_seconds"] == 30


def test_config_freeze_roundtrips_json_and_rejects_changes(tmp_path):
    config = ComparisonConfig()
    one = p.freeze_protocol(config, tmp_path)
    assert p.freeze_protocol(config, tmp_path)["protocol_hash"] == one["protocol_hash"]
    changed = config_from_dict({"name": "different"})
    with pytest.raises(ValueError, match="Frozen protocol"):
        p.freeze_protocol(changed, tmp_path)


def test_native_executable_bytes_enter_protocol_and_job_identity(tmp_path):
    binary = tmp_path / "native"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    config = config_from_dict({"backend": {"groops_executable": str(binary)}})
    frozen = p.freeze_protocol(config, tmp_path / "one")
    assert frozen["native_binary"] == {"path": str(binary), "sha256": p.file_hash(binary)}
    job = p._job(frozen, "synthetic", "calibration", "prepare", {})
    assert job["expected_native_binary_sha256"] == p.file_hash(binary)
    binary.write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(ValueError, match="Frozen protocol"):
        p.freeze_protocol(config, tmp_path / "one")
    changed = p.freeze_protocol(config, tmp_path / "two")
    assert p._job(changed, "synthetic", "calibration", "prepare", {})["id"] != job["id"]


def test_native_executable_missing_is_recorded_and_retention_is_boolean(tmp_path):
    config = config_from_dict({"backend": {"groops_executable": str(tmp_path / "absent")}})
    frozen = p.freeze_protocol(config, tmp_path)
    assert frozen["native_binary"] is None
    assert p._job(frozen, "synthetic", "calibration", "prepare", {})["expected_native_binary_sha256"] is None
    assert config.backend.retain_native_diagnostics is False
    with pytest.raises(ValueError, match="bool"):
        config_from_dict({"backend": {"retain_native_diagnostics": 1}})


def test_blind_inputs_reject_truth_and_unproven_bootstrap(tmp_path):
    backend = FakeBackend()
    config = ComparisonConfig()
    case = p.case_matrix(config, "synthetic", "calibration")[0]
    job = {"stage": "synthetic", "split": "calibration", "case": case}
    record = backend.prepare_job(job, tmp_path)
    assert p.validate_prepared(record, job)
    with pytest.raises(ValueError, match="Disallowed"):
        p.validate_estimation_inputs(record["estimation_inputs"] + record["evaluation_inputs"])
    record["estimation_inputs"][-1].pop("provenance")
    with pytest.raises(ValueError, match="GNSS-only"):
        p.validate_prepared(record, job)


def test_mask_and_artifact_changes_reject_resume(tmp_path):
    config = ComparisonConfig()
    case = p.case_matrix(config, "synthetic", "calibration")[0]
    job = {"stage": "synthetic", "split": "calibration", "case": case}
    record = FakeBackend().prepare_job(job, tmp_path)
    record["mask_hash"] = "0" * 64
    with pytest.raises(ValueError, match="mask"):
        p.validate_prepared(record, job)
    record["mask_hash"] = p.canonical_hash(case["mask"])
    Path(record["estimation_inputs"][0]["path"]).write_text("modified")
    with pytest.raises(ValueError, match="modified artifact"):
        p.validate_prepared(record, job)


def test_zero_budget_queues_without_backend_or_completion(tmp_path):
    backend = FakeBackend()
    result = p.prepare(ComparisonConfig(), tmp_path, backend=backend, max_jobs=0)
    assert not backend.calls
    assert result["status"] == "incomplete"
    assert result["complete"] is False
    assert any(json.loads(path.read_text())["status"] == "queued" for path in tmp_path.glob("jobs/*/result.json"))


def test_prepared_inputs_are_not_a_completed_experiment(tmp_path):
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    backend = FakeBackend()
    result = p.prepare(config, tmp_path, backend=backend)
    assert result["status"] == "prepared" and not result["complete"]
    assert result["jobs_started"] == 12
    resumed = p.prepare(config, tmp_path, backend=backend)
    assert resumed["jobs_started"] == 0 and len(backend.calls) == 12


def test_backend_block_remains_explicit(tmp_path):
    class Blocked:
        def prepare_job(self, job, directory):
            return {"status": "blocked", "error": "Native executable absent"}
    result = p.prepare(ComparisonConfig(), tmp_path, backend=Blocked())
    assert result["status"] == "blocked" and not result["complete"]
    assert "Native executable absent" in result["error"]


def test_boundaries_expand_only_when_improving():
    grid = p.initial_candidates(ComparisonConfig(), "groops_pulses")
    scores = {p.canonical_hash(c): -c["sigma_velocity_m_s"] for c in grid}
    expanded, diagnosis = p.expand_candidates("groops_pulses", grid, scores)
    assert not diagnosis["adequate"]
    assert max(c["sigma_velocity_m_s"] for c in expanded) == pytest.approx(.1)
    assert len(expanded) == 16
    _, flat = p.expand_candidates("groops_pulses", grid, {p.canonical_hash(c): 1. for c in grid})
    assert flat["adequate"]


def test_calibration_is_scored_after_blind_fit_and_selection_frozen(tmp_path):
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    fake_acceptance(config, tmp_path)
    backend = FakeBackend()
    result = p.calibrate(config, tmp_path, backend=backend)
    assert result["complete"] and result["selection_hash"]
    assert len([c for c in backend.calls if c["kind"] == "fit"]) == 384
    assert len([c for c in backend.calls if c["kind"] == "evaluate"]) == 384
    frozen = p.freeze_protocol(config, tmp_path)
    assert p._selection(config, tmp_path, frozen, "synthetic")["complete"]
    evidence = Path(result["evidence"][0]["path"])
    evidence.write_text("{}")
    with pytest.raises(ValueError, match="evidence changed"):
        p._selection(config, tmp_path, frozen, "synthetic")


def test_parallel_calibration_preserves_pairing_and_result_identity(tmp_path):
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    fake_acceptance(config, tmp_path)
    result = p.calibrate(config, tmp_path, backend=FakeBackend(), workers=3)
    assert result["complete"] and result["concurrent_workers"] == 3
    assert len(result["runs"]) == 384
    for row in result["runs"]:
        record = p.read_json(row["result_path"])
        assert record["status"] == "complete"
        assert record["calibration_score"]["mean_nll"] == row["score"]["mean_nll"]
    resumed = p.calibrate(config, tmp_path, backend=FakeBackend(), workers=2)
    assert resumed["jobs_started"] == 0
    assert resumed["selection_hash"] == result["selection_hash"]


def test_calibration_round_spans_candidates_without_changing_scores_or_failures(tmp_path, monkeypatch):
    from threading import Event, Lock
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    initial = p.initial_candidates
    grids = {method: [initial(config, method)[i] for i in (0, 1, 4, 5)] for method in config.methods}
    monkeypatch.setattr(p, "initial_candidates", lambda config, method: grids[method])
    first = {method: p.canonical_hash(grid[0]) for method, grid in grids.items()}
    class ConcurrentCandidates(FakeBackend):
        def __init__(self, require_overlap=False):
            super().__init__()
            self.require_overlap = require_overlap
            self.lock = Lock()
            self.events = {method: Event() for method in config.methods}
            self.active = {method: {} for method in config.methods}
            self.maximum_candidates = {method: 0 for method in config.methods}
        def fit_job(self, job, directory):
            method, key = job["method"], p.canonical_hash(job["parameters"])
            with self.lock:
                active = self.active[method]
                active[key] = active.get(key, 0) + 1
                self.maximum_candidates[method] = max(self.maximum_candidates[method], len(active))
                if len(active) > 1:
                    self.events[method].set()
            try:
                if self.require_overlap and key == first[method]:
                    assert self.events[method].wait(5), "No second candidate entered while the first was active"
                if (key == first[method] and job["case"]["seed"] == config.synthetic.calibration_seeds[0]
                        and job["case"]["holdout_minutes"] == 30):
                    return {"status": "failed", "error": "Controlled numerical failure for one candidate/arc"}
                return super().fit_job(job, directory)
            finally:
                with self.lock:
                    active[key] -= 1
                    if not active[key]:
                        del active[key]
        def evaluate_job(self, job, result, directory):
            scored = super().evaluate_job(job, result, directory)
            # Unequal support sizes must not replace equal holdout/arc weights.
            short = job["case"]["holdout_minutes"] == 30
            scored["calibration_score"].update(mean_nll=1. if short else 3.,
                                                retained_dimensions=10 if short else 40)
            return scored
    serial_root, parallel_root = tmp_path / "serial", tmp_path / "parallel"
    for root in (serial_root, parallel_root):
        fake_acceptance(config, root)
    serial = p.calibrate(config, serial_root, backend=ConcurrentCandidates(), workers=1)
    backend = ConcurrentCandidates(require_overlap=True)
    parallel = p.calibrate(config, parallel_root, backend=backend, workers=24)
    assert all(value >= 2 for value in backend.maximum_candidates.values())
    assert serial["complete"] and parallel["complete"]
    assert serial["selections"] == parallel["selections"]
    assert serial["boundary_diagnostics"] == parallel["boundary_diagnostics"]
    fields = ("case", "method", "parameters", "expansion_round", "status", "valid", "evaluation_status", "error", "score")
    rows = lambda value: [{key: row.get(key) for key in fields} for row in value["runs"]]
    assert rows(serial) == rows(parallel)
    assert len(parallel["runs"]) == 96 and sum(not row["valid"] for row in parallel["runs"]) == 2
    assert all(value["selected_mean_nll"] == 2. for value in parallel["boundary_diagnostics"]["leo500"].values())
    resumed = p.calibrate(config, parallel_root, backend=FakeBackend(), workers=2)
    assert resumed["jobs_started"] == 0 and resumed["selection_hash"] == parallel["selection_hash"]
    assert rows(resumed) == rows(parallel)


def test_exhausted_boundary_search_freezes_best_and_discloses_claim_limit(tmp_path, monkeypatch):
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    fake_acceptance(config, tmp_path)
    initial = p.initial_candidates
    monkeypatch.setattr(p, "initial_candidates", lambda config, method: initial(config, method)[:1])
    def expanding(method, candidates, scores, tolerance):
        winner = candidates[0]
        field = "sigma_velocity_m_s" if method == "groops_pulses" else "sigma_log_density"
        return [{**winner, field: winner[field] * 2}], {
            "adequate": False, "winner": winner, "mean_nll": scores[p.canonical_hash(winner)],
            "boundaries": [{"parameter": field, "improving": True, "edge": "upper"}]}
    monkeypatch.setattr(p, "expand_candidates", expanding)
    class Improving(FakeBackend):
        def evaluate_job(self, job, result, directory):
            value = super().evaluate_job(job, result, directory)
            parameters = job["fit_result"]["parameters"]
            scale = parameters.get("sigma_velocity_m_s", parameters.get("sigma_log_density"))
            value["calibration_score"]["mean_nll"] = -scale
            return value
    result = p.calibrate(config, tmp_path, backend=Improving())
    assert result["complete"] and not result["calibration_adequate"]
    assert result["status"] == "complete_boundary_limited"
    assert len(result["calibration_disclosures"]) == 2
    for method in config.methods:
        diagnosis = result["boundary_diagnostics"]["leo500"][method]
        assert diagnosis["expansion_round"] == 2 and len(diagnosis["round_history"]) == 3
        assert result["selections"]["leo500"][method] == diagnosis["winner"]
    frozen = p.freeze_protocol(config, tmp_path)
    assert p._selection(config, tmp_path, frozen, "synthetic")["complete"]
    result["calibration_disclosures"] = []
    p.write_json(tmp_path / "calibration-synthetic.json", result)
    with pytest.raises(ValueError, match="selection has been modified"):
        p._selection(config, tmp_path, frozen, "synthetic")


def test_hash_cache_invalidates_same_size_rewrites(tmp_path):
    file = tmp_path / "input.dat"
    file.write_bytes(b"before")
    first = p.file_hash(file)
    assert p.file_hash(file) == first
    file.write_bytes(b"after!")
    assert p.file_hash(file) != first


def test_evaluation_cannot_start_without_frozen_selection(tmp_path):
    with pytest.raises(ValueError, match="freeze calibration"):
        p.run(ComparisonConfig(), tmp_path, backend=FakeBackend())


def test_existing_cli_registers_v3_without_changing_v2():
    from orbit_poc.cli import parser
    args = parser().parse_args(["comparison", "prepare", "--config", "config.json"])
    assert args.comparison_command == "prepare" and args.stage == "synthetic"
    assert parser().parse_args(["fit", "--dataset", "x", "--output-dir", "y"]).solver == "gtsam"


def test_calibration_masks_preserve_independent_arcs_and_canonical_numbers():
    from orbit_poc.comparison.data import normalize_mask
    cases = p.case_matrix(ComparisonConfig(), "synthetic", "calibration")
    assert len({c["arc_id"] for c in cases}) == 24
    for arc in {c["arc_id"] for c in cases}:
        assert {c["holdout_minutes"] for c in cases if c["arc_id"] == arc} == {30, 120}
    for case in cases:
        assert p.canonical_hash(case["mask"]) == p.canonical_hash(normalize_mask(case["mask"]))


def test_calibration_requires_both_holdouts_for_each_independent_arc(tmp_path):
    class MissingShortHoldout(FakeBackend):
        def evaluate_job(self, job, fit_result, directory):
            result = super().evaluate_job(job, fit_result, directory)
            if job['case']['holdout_minutes'] == 30:
                result['calibration_score']['valid'] = False
            return result
    config = config_from_dict({'synthetic': {'orbits': ['leo500']}})
    fake_acceptance(config, tmp_path)
    result = p.calibrate(config, tmp_path, backend=MissingShortHoldout())
    assert not result['complete'] and not result.get('selection_hash')
    assert all(not result['boundary_diagnostics']['leo500'][method]['adequate'] for method in config.methods)


def test_calibration_weights_each_holdout_equally_not_by_observation_count(tmp_path):
    class DifferentDurations(FakeBackend):
        def evaluate_job(self, job, fit_result, directory):
            result = super().evaluate_job(job, fit_result, directory)
            short = job['case']['holdout_minutes'] == 30
            result['calibration_score'].update(mean_nll=1 if short else 3,
                                              retained_dimensions=100 if short else 400)
            return result
    config = config_from_dict({'synthetic': {'orbits': ['leo500']}})
    fake_acceptance(config, tmp_path)
    result = p.calibrate(config, tmp_path, backend=DifferentDurations())
    assert result['complete']
    assert all(result['boundary_diagnostics']['leo500'][method]['mean_nll'] == 2 for method in config.methods)


def test_snapshot_includes_native_extensions_and_all_configuration_templates(tmp_path, monkeypatch):
    monkeypatch.undo()
    names=['groops/extension/model.h','groops/extension/apply_extension.py',
           'groops/templates/observations.txt','groops/templates/forces.xml','configs/protocol.json']
    for name in names:
        file=tmp_path/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(name)
    snapshot=p.source_snapshot(tmp_path)
    assert set(snapshot['files'])==set(names)
    (tmp_path/names[0]).write_text('changed scientific source')
    assert p.source_snapshot(tmp_path)['sha256']!=snapshot['sha256']


def test_primary_cell_is_predeclared_and_in_every_manifest(tmp_path):
    config=ComparisonConfig()
    assert config.primary_cell==('leo500','disturbed','blackout')
    with pytest.raises(ValueError,match='primary cell'):
        config_from_dict({'primary_cell':['leo300','quiet','normal']})
    record=p.prepare(config,tmp_path,backend=FakeBackend(),max_jobs=0)
    assert record['primary_cell']==['leo500','disturbed','blackout']


def test_production_calibration_requires_ordered_unchanged_gate_evidence(tmp_path):
    from orbit_poc.comparison.gates import validate_gates
    config = ComparisonConfig()
    frozen = p.freeze_protocol(config, tmp_path)
    backend = FakeBackend()
    with pytest.raises(ValueError, match="Acceptance gates"):
        p.calibrate(config, tmp_path, backend=backend)
    assert not backend.calls
    record = fake_acceptance(config, tmp_path)
    assert validate_gates(tmp_path, frozen)["evidence_hash"] == record["evidence_hash"]
    record["gates"]["numerical_accuracy"]["completed_at"] = "2025-01-01T00:00:00+00:00"
    record.pop("evidence_hash")
    record["evidence_hash"] = p.canonical_hash(record)
    p.write_json(tmp_path / "acceptance-gates.json", record)
    with pytest.raises(ValueError, match="ordered UTC"):
        validate_gates(tmp_path, frozen)
    fake_acceptance(config, tmp_path)
    (tmp_path / "fake_test_evidence").write_text("mutated")
    with pytest.raises(ValueError, match="modified"):
        validate_gates(tmp_path, frozen)


def test_metadata_excluded_flight_day_is_recorded_without_stopping_other_days(tmp_path, monkeypatch):
    config = ComparisonConfig()
    fake_acceptance(config, tmp_path)
    cases = p.case_matrix(config, "flight", "evaluation")[:2]
    cases[1] = {**cases[1], "date": "2024-05-08"}
    monkeypatch.setattr(p, "case_matrix", lambda *args: cases)
    monkeypatch.setattr(p, "_selection", lambda *args: {"selection_hash": "f" * 64,
        "calibration_adequate": True, "calibration_disclosures": [],
        "selections": {"GRACEFO1": {method: p.initial_candidates(config, method)[0] for method in config.methods}}})
    class ExcludedDay(FakeBackend):
        def prepare_job(self, job, directory):
            if job["case"]["date"] == "2024-05-07":
                return {"status": "excluded", "reason": "Orbital maneuver in fixed metadata",
                        "artifacts": [artifact(directory, "screening")]}
            return super().prepare_job(job, directory)
    result = p.run(config, tmp_path, stage="flight", backend=ExcludedDay())
    assert result["complete"] and result["expected_fits"] == 4
    assert [row["status"] for row in result["runs"]] == ["excluded", "excluded", "complete", "complete"]
    assert not result["all_fits_valid"]


def test_unavailable_flight_slr_preserves_independent_reference_metrics(tmp_path):
    class IncompleteFlight:
        def evaluate_job(self, job, result, directory):
            return {"status": "incomplete", "error": "No calibrated SLR station",
                    "metrics": {"formal_prediction": {"status": "unavailable"},
                                "reference_agreement": {"position_rms_m": .03}},
                    "artifacts": [artifact(directory, "evaluation_metrics")]}
    job = {"kind": "evaluate", "id": "flight-evaluation-test", "stage": "flight", "split": "evaluation", "fit_result": {}}
    runner = p.Runner(tmp_path, backend=IncompleteFlight())
    result = runner.execute(job)
    assert result["status"] == "incomplete"
    assert result["metrics"]["reference_agreement"]["position_rms_m"] == .03
    assert runner.execute(job) == result and runner.started == 1


@pytest.mark.parametrize("change", ["candidate", "method", "missing"])
def test_calibration_predictive_support_changes_block_selection(tmp_path, change):
    class ChangingSupport(FakeBackend):
        def evaluate_job(self, job, fit_result, directory):
            result = super().evaluate_job(job, fit_result, directory)
            if change == "missing":
                result.pop("predictive_support_sha256")
            elif (change == "method" and job["method"] == "groops_log_drag_ou" or
                  change == "candidate" and fit_result["parameters"].get("sigma_velocity_m_s", 1e-5) != 1e-5):
                result["predictive_support_sha256"] = "b" * 64
            return result
    config = config_from_dict({"synthetic": {"orbits": ["leo500"]}})
    fake_acceptance(config, tmp_path)
    result = p.calibrate(config, tmp_path, backend=ChangingSupport(), workers=2)
    assert result["status"] == "blocked" and not result["complete"]
    assert "predictive support" in result["error"]
    assert not result.get("selection_hash")


def test_predictive_support_guard_is_holdout_specific_and_rechecks_resume(tmp_path):
    runner = p.Runner(tmp_path)
    cases = p.case_matrix(ComparisonConfig(), "synthetic", "calibration")[:2]
    prepared = {"calibration_inputs": [{"role": "heldout_gnss_code", "sha256": "f" * 64}]}
    for case, support in zip(cases, ("a" * 64, "b" * 64)):
        p._check_predictive_support(runner, "synthetic", case, prepared, {"predictive_support_sha256": support})
        p._check_predictive_support(runner, "synthetic", case, prepared, {"predictive_support_sha256": support})
    with pytest.raises(p.BackendBlocked, match="differs"):
        p._check_predictive_support(runner, "synthetic", cases[0], prepared, {"predictive_support_sha256": "c" * 64})


def test_compact_checkpoint_retains_scored_arrays_and_verifies_resume_bytes(tmp_path):
    class LargeScore:
        def evaluate_job(self, job, result, directory):
            return {"status": "complete", "artifacts": [artifact(directory, "score")],
                    "calibration_score": {"valid": True, "mean_nll": 1., "retained_dimensions": 10},
                    "epoch_scores": [{"projected_residual": list(range(5000)),
                                      "projected_covariance": list(range(5000))}]}
    job = {"id": "large-score", "kind": "evaluate", "stage": "synthetic", "split": "calibration", "fit_result": {}}
    runner = p.Runner(tmp_path, backend=LargeScore())
    result = runner.execute(job)
    record = runner.records[0]
    assert "result" not in record and "job" not in record
    assert len(json.dumps(record)) < 2000
    assert Path(record["result_path"]).stat().st_size > 100000
    assert p.read_result_record(record)["epoch_scores"] == result["epoch_scores"]
    assert p.Runner(tmp_path).execute(job) == result
    changed = {**result, "status": "running"}
    p.write_json(record["result_path"], changed)
    # Even changing a terminal status to running must not bypass integrity.
    with pytest.raises(ValueError, match="result bytes changed"):
        p.Runner(tmp_path).execute(job)


def test_compact_run_report_loads_metrics_and_preserves_failed_details(tmp_path, monkeypatch):
    from orbit_poc.comparison.report import create_report
    config = ComparisonConfig()
    fake_acceptance(config, tmp_path)
    case = p.case_matrix(config, "synthetic", "evaluation")[0]
    monkeypatch.setattr(p, "case_matrix", lambda *args: [case])
    monkeypatch.setattr(p, "_selection", lambda *args: {"selection_hash": "f" * 64,
        "calibration_adequate": True, "calibration_disclosures": [],
        "selections": {case["orbit"]: {method: p.initial_candidates(config, method)[0] for method in config.methods}}})
    class FailedArm(FakeBackend):
        def fit_job(self, job, directory):
            if job["method"] == "groops_log_drag_ou":
                return {"status": "failed", "error": "Native convergence failure",
                        "diagnostics": {"full_error_history": [1., 2., 3.]}}
            return super().fit_job(job, directory)
        def evaluate_job(self, job, result, directory):
            value = super().evaluate_job(job, result, directory)
            value["metrics"]["position_rmse_m"] = 123.456
            return value
    manifest = p.run(config, tmp_path, backend=FailedArm())
    assert all("fit" not in row and "evaluation" not in row for row in manifest["runs"])
    assert manifest["runs"][0]["evaluation_record"]["result_sha256"]
    create_report(manifest, tmp_path / "report")
    report = p.read_json(tmp_path / "report" / "report.json")
    assert report["failures"][0]["error"] == "Native convergence failure"
    failed = p.read_result_record(manifest["runs"][1]["fit_record"])
    assert failed["diagnostics"]["full_error_history"] == [1., 2., 3.]
    assert "123.456" in (tmp_path / "report" / "index.html").read_text()
    evaluation = manifest["runs"][0]["evaluation_record"]
    changed = p.read_result_record(evaluation)
    changed["metrics"]["position_rmse_m"] = 99.
    p.write_json(evaluation["result_path"], changed)
    with pytest.raises(ValueError, match="result bytes changed"):
        create_report(manifest, tmp_path / "changed-report")


def report_fixture(root):
    config = ComparisonConfig()
    frozen = p.freeze_protocol(config, root)
    calibration = {**p._manifest("calibration", "synthetic", frozen), "complete": True,
                   "status": "complete", "selections": {}, "evidence": [],
                   "calibration_adequate": True, "calibration_disclosures": [],
                   "boundary_diagnostics": {}}
    calibration["selection_hash"] = p.canonical_hash(p._selection_payload(calibration))
    run = {**p._manifest("evaluation", "synthetic", frozen), "campaign": "primary",
           "selection_hash": calibration["selection_hash"], "status": "incomplete"}
    p.write_json(root / "calibration-synthetic.json", calibration)
    p.write_json(root / "run-synthetic.json", run)
    return config, run, calibration


@pytest.mark.parametrize("field", ["protocol_hash", "source_hash", "selection_hash", "stage", "campaign"])
def test_protocol_report_rejects_mixed_run_provenance(tmp_path, field):
    config, run, _ = report_fixture(tmp_path)
    run[field] = "different"
    p.write_json(tmp_path / "run-synthetic.json", run)
    with pytest.raises(ValueError, match="Run report"):
        p.report(config, tmp_path)
    assert not (tmp_path / "report-synthetic" / "index.html").exists()


@pytest.mark.parametrize("change", ["missing", "incomplete", "source", "evidence"])
def test_protocol_report_requires_matching_unchanged_calibration(tmp_path, change):
    config, run, calibration = report_fixture(tmp_path)
    path = tmp_path / "calibration-synthetic.json"
    if change == "missing":
        path.unlink()
    else:
        if change == "incomplete":
            calibration["complete"] = False
        elif change == "source":
            calibration["source_hash"] = "different"
        else:
            result = tmp_path / "calibration-result.json"
            p.write_json(result, {"status": "failed", "error": "original"})
            calibration["evidence"] = [{"path": str(result), "sha256": p.file_hash(result)}]
            calibration["selection_hash"] = p.canonical_hash(p._selection_payload(calibration))
            run["selection_hash"] = calibration["selection_hash"]
            p.write_json(tmp_path / "run-synthetic.json", run)
            p.write_json(result, {"status": "failed", "error": "modified"})
        p.write_json(path, calibration)
    with pytest.raises(ValueError, match="[Cc]alibration"):
        p.report(config, tmp_path)


def test_protocol_report_accepts_matched_partial_run_and_no_run(tmp_path):
    config, _, _ = report_fixture(tmp_path)
    paths = p.report(config, tmp_path)
    summary = p.read_json(paths["summary"])
    assert summary["status"] == "incomplete" and not summary["orchestration_complete"]
    (tmp_path / "run-synthetic.json").unlink()
    (tmp_path / "calibration-synthetic.json").unlink()
    paths = p.report(config, tmp_path)
    summary = p.read_json(paths["summary"])
    assert summary["status"] == "not_run" and not summary["orchestration_complete"]
