"""I/O/provenance tests. These do not replace genuine native fit acceptance."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

from orbit_poc.comparison.backend import (
    NativeExecutionError, _binary, _blind_record, _covariance, _orbit, _private_data,
    _verify_transmitters, fit_job, read_native_table, run_native,
    score_native_predictions,
)
from orbit_poc.comparison.protocol import file_hash


def test_binary_enforces_frozen_bytes_and_requires_refreeze_after_installation(tmp_path):
    binary = tmp_path / "native"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    job = {"backend": {"groops_executable": str(binary)}, "expected_native_binary_sha256": None}
    with pytest.raises(FileNotFoundError, match="new freeze"):
        _binary(job)
    job["expected_native_binary_sha256"] = file_hash(binary)
    assert _binary(job) == binary
    binary.write_text("#!/bin/sh\nexit 1\n")
    with pytest.raises(ValueError, match="SHA256"):
        _binary(job)


def test_native_matrix_orbit_covariance_reading_and_no_covariance_repair(tmp_path):
    epochs = 60000. + np.arange(3) / 86400.
    path = tmp_path / "orbit.txt"
    np.savetxt(path, np.column_stack([epochs, np.ones((3, 9))]),
               header="groops instrument version=20200123")
    mjd, states = _orbit(path)
    assert states.shape == (3, 6)
    covariance = np.tile(np.diag([1., 2., 3., 1e-12, 2e-12, 3e-12]), (3, 1, 1))
    covpath = tmp_path / "covariance.txt"
    np.savetxt(covpath, np.column_stack([epochs, covariance.reshape(3, 36)]),
               header="groops matrix version=20200123\nMatrix(3 x 37)")
    actual, invalid = _covariance(covpath, mjd)
    assert invalid == []
    np.testing.assert_array_equal(actual, covariance)
    covariance[1, 0, 0] = -1.
    np.savetxt(covpath, np.column_stack([epochs, covariance.reshape(3, 36)]))
    assert _covariance(covpath, mjd)[1] == [1]
    with pytest.raises(ValueError, match="epochs"):
        _covariance(covpath, mjd+1.)
    binary = tmp_path / "mislabelled.dat"; binary.write_text("1 2 3")
    with pytest.raises(ValueError, match="ASCII"):
        read_native_table(binary)


def test_subprocess_runtime_provenance_threads_and_timeout(tmp_path):
    # A real Python subprocess exercises the command harness, not GROOPS physics.
    program = tmp_path / "environment.py"
    program.write_text("import os\nprint(os.environ['OPENBLAS_NUM_THREADS'], os.environ['OMP_NUM_THREADS'])\n")
    record = run_native(sys.executable, program, tmp_path / "run", "environment")
    assert record["returncode"] == 0 and record["blas_openmp_threads"] == 1
    assert record["native_binary_sha256"] == file_hash(sys.executable)
    assert Path(record["log"]).read_text().strip() == "1 1"
    program.write_text("import time\ntime.sleep(10)\n")
    with pytest.raises(NativeExecutionError, match="timed out") as caught:
        run_native(sys.executable, program, tmp_path / "timeout", "wait", timeout=.1)
    assert caught.value.execution["timed_out"]
    assert caught.value.execution["elapsed_seconds"] >= .1
    assert caught.value.execution["peak_rss_bytes"] > 0
    failed = json.loads((tmp_path / "timeout/wait.execution.json").read_text())
    assert failed["timed_out"] and failed["returncode"] != 0


def test_blind_manifest_strips_evaluation_and_private_orbit_is_not_shared(tmp_path):
    source = tmp_path / "prepared"
    directory = source / "data/day"; directory.mkdir(parents=True)
    paths = {key: directory / (key+".dat") for key in ("orbit", "variational", "receiver", "attitude", "attitude_integration", "receiver_orbit", "receiver_attitude")}
    for key, path in paths.items(): path.write_text(key)
    cached = tmp_path / "cache"; cached.mkdir()
    (cached / "transmitter.dat").write_text("fixed transmitter")
    (directory / "transmitters").symlink_to(cached, target_is_directory=True)
    prepared = {"output_dir": str(source), "date": "day", "native_paths": {k:str(v) for k,v in paths.items()},
                "evaluation_inputs": [{"role":"truth", "path":"SECRET"}],
                "calibration_inputs": [{"path":"WITHHELD"}], "native_simulation":{"truth":"SECRET"}}
    blind = _blind_record(prepared)
    assert "SECRET" not in json.dumps(blind) and "WITHHELD" not in json.dumps(blind)
    assert str(paths["attitude_integration"].resolve()) in {item["path"] for item in blind["native_artifacts"]}
    private = tmp_path / "private"
    _private_data(blind, private)
    orbit = private / "data/day/orbit.dat"
    assert not orbit.is_symlink()
    orbit.write_text("updated")
    assert paths["orbit"].read_text() == "orbit"
    assert (private / "data/day/receiver.dat").is_symlink()
    assert (private / "data/day/attitude_integration.dat").is_symlink()
    for key in ("receiver_orbit", "receiver_attitude"):
        assert str(paths[key].resolve()) in {item["path"] for item in blind["native_artifacts"]}
        assert (private / ("data/day/" + key + ".dat")).is_symlink()
    assert (private / "data/day/transmitters/transmitter.dat").read_text() == "fixed transmitter"
    assert not (private / "data/day/variational.dat").exists()
    with pytest.raises(ValueError, match="only"):
        fit_job({"evaluation_inputs":[]}, tmp_path / "rejected")


def test_transmitter_products_require_common_satellites_not_total_count(tmp_path):
    configured = {"output_dir":str(tmp_path), "date":"day"}
    for folder in ("orbit", "attitude", "clock", "signalBias"):
        root = tmp_path / "data/day" / folder; root.mkdir(parents=True)
        for number in range(1, 6): (root / f"product.G{number:02d}.dat").write_bytes(b"data")
    assert len(_verify_transmitters(configured)) == 5
    (tmp_path / "data/day/clock/product.G05.dat").unlink()
    with pytest.raises(NativeExecutionError, match="five"):
        _verify_transmitters(configured)


@pytest.mark.parametrize("failure_stage", ["preparation", "native_selection", "empty_table"])
@pytest.mark.parametrize("frozen_evaluation", [False, True])
def test_unavailable_slr_preserves_independent_reference_agreement(tmp_path, monkeypatch, failure_stage, frozen_evaluation):
    from orbit_poc.comparison import backend, slr

    crd = tmp_path / "withheld.crd"; crd.write_text("excluded normal points")
    reference = tmp_path / "reference.txt"; reference.write_text("evaluation only")
    monkeypatch.setattr(backend, "_artifact", lambda result, role: str(tmp_path / role))
    monkeypatch.setattr(backend, "_binary", lambda job: Path(sys.executable))

    monkeypatch.setattr(slr, "frozen_slr_auxiliary", lambda *args: {"manifest_hash":"frozen-corrections"})

    def unavailable(*args, **kwargs):
        assert kwargs["download"] is not frozen_evaluation
        assert (kwargs["frozen_auxiliary"] is not None) is frozen_evaluation
        if failure_stage == "preparation":
            raise slr.SlrPrerequisiteError("all station records excluded by external metadata")
        return {"configs":{"predict_slr":str(tmp_path/"predict.xml")},
                "predictions":str(tmp_path/"empty.txt")}

    def native_empty(*args, **kwargs):
        if failure_stage == "native_selection":
            (tmp_path/"predict_slr.log").write_text("no usable withheld SLR observations")
            (tmp_path/"predict_slr.execution.json").write_text('{"returncode":1}')
            raise backend.NativeExecutionError("empty after native selection")
        (tmp_path/"empty.txt").write_text("# no numeric observation rows\n")
        return {"returncode":0}

    monkeypatch.setattr(slr, "build_slr_configs", unavailable)
    monkeypatch.setattr(backend, "run_native", native_empty)
    monkeypatch.setattr(backend, "_reference_agreement", lambda *args: (
        {"position_rms_m":.02, "interpretation":"reference agreement; not truth"},
        {"returncode":0}, {"role":"evaluation_reference_crf", "path":str(reference),
                              "sha256":file_hash(reference)}))
    job = {"case":{"date":"2024-05-11"}, "backend":{"auxiliary_dir":str(tmp_path)},
           "frozen_evaluation":frozen_evaluation,
           "evaluation_inputs":[{"role":"slr_validation", "path":str(crd), "sha256":file_hash(crd)}]}
    value = backend.evaluate_native_slr(job, {}, tmp_path, np.array([60000.]), np.zeros((1,6)))
    assert value["status"] == "incomplete"
    assert value["metrics"]["reference_agreement"]["position_rms_m"] == .02
    assert value["metrics"]["formal_prediction"]["observations"] == 0
    assert not value["metrics"]["predictive"]["valid"]
    assert all(Path(item["path"]).is_file() for item in value["artifacts"])


def test_native_prediction_score_projects_native_clock_and_checks_epoch_alignment():
    predictions = np.array([[60000., 1, 2., 4., 1., 0., 0., 1.0002],
                            [60000., 2, -1., 9., 0., 1., 0., .9998],
                            [60000., 3, 3., 16., 0., 0., 1., 1.0001]])
    covariance = np.diag([2., 3., 4., 1., 1., 1.])[None, ...]
    result = score_native_predictions(predictions, [60000.], covariance)
    shifted = predictions.copy(); shifted[:, 2] += 1000.*shifted[:, 7]
    actual = score_native_predictions(shifted, [60000.], covariance)
    assert result["calibration_score"]["valid"]
    assert actual["calibration_score"]["mean_nll"] == pytest.approx(result["calibration_score"]["mean_nll"], abs=1e-10)
    assert result["calibration_score"]["retained_dimensions"] == 2
    assert not score_native_predictions(predictions[:1], [60000.], covariance)["calibration_score"]["valid"]
    with pytest.raises(ValueError, match="epoch"):
        score_native_predictions(predictions, [60001.], covariance)


def test_utc_reference_joins_adjacent_files_and_scores_only_fitted_arc(tmp_path, monkeypatch):
    from orbit_poc.comparison import backend
    import xml.etree.ElementTree as ET

    paths = [tmp_path/"day1.GNV", tmp_path/"day2.GNV"]
    for path in paths: path.write_text("evaluation-only fixture")
    config = tmp_path/"fit.xml"
    config.write_text("<groops><GnssProcessing><earthRotation><file /></earthRotation></GnssProcessing></groops>")
    monkeypatch.setattr(backend, "_artifact", lambda result, role: str(config))
    fit_epochs = np.array([60000.+18/86400, 60001.+13/86400])
    all_epochs = np.array([60000., *fit_epochs, 60001.+20/86400])
    fit_states = np.ones((2,6))

    def convert(binary, xml, root, label, **kwargs):
        program = ET.parse(xml).getroot().find(".//GraceL1b2Orbit")
        assert [node.text for node in program.findall("inputfile")] == [str(p) for p in paths]
        np.savetxt(program.find("outputfileOrbit").text,
                   np.column_stack([all_epochs, np.ones((4,6)), np.zeros((4,3))]))
        return {"returncode":0}

    monkeypatch.setattr(backend, "run_native", convert)
    job = {"evaluation_inputs":[{"role":"reference_orbit", "path":str(path),
                                  "sha256":file_hash(path)} for path in reversed(paths)]}
    score, _, artifact = backend._reference_agreement(job, {}, tmp_path,
        fit_epochs, fit_states, Path(sys.executable))
    assert score["matched_epochs"] == 2 and score["unmatched_fit_epochs"] == 0
    assert score["reference_input_files"] == 2 and score["position_rms_m"] == 0
    assert not score["reference_used_in_fit"] and Path(artifact["path"]).is_file()


def test_calibration_uses_propagated_covariance_at_actual_gnss_epochs(tmp_path, monkeypatch):
    from orbit_poc.comparison import backend
    # A UTC dynamics grid (GPS seconds 18 + 5n) misses GPS observations at 30s.
    dynamics_mjd = 60000. + np.array([18., 23., 28., 33.])/86400.
    observation_mjd = 60000. + np.array([30.])/86400.
    dynamics_covariance = np.tile(np.eye(6), (4, 1, 1))
    observation_covariance = np.diag([2., 3., 4., 5., 6., 7.])[None]
    archive = tmp_path / "fit.npz"
    np.savez(archive, times=np.arange(4)*5., mjd=dynamics_mjd, states=np.zeros((4,6)),
             covariance=dynamics_covariance, prediction_mjd=observation_mjd,
             prediction_covariance=observation_covariance)
    result = {"converged": True, "covariance_valid": True, "artifacts":[
        {"role":"state_estimate", "path":str(archive), "sha256":file_hash(archive)}]}
    predictions = np.array([[observation_mjd[0], 1, 2., 4., 1., 0., 0., 1.],
                            [observation_mjd[0], 2, -1., 9., 0., 1., 0., 1.]])

    def score(job, result, root, mjd, covariance):
        np.testing.assert_array_equal(mjd, observation_mjd)
        np.testing.assert_array_equal(covariance, observation_covariance)
        return backend.score_native_predictions(predictions, mjd, covariance)

    monkeypatch.setattr(backend, "evaluate_native_code", score)
    assert backend.evaluate_job({"split":"calibration"}, result, tmp_path)["calibration_score"]["valid"]
    with pytest.raises(ValueError, match="propagate covariance"):
        backend.score_native_predictions(predictions, dynamics_mjd, dynamics_covariance)


def test_predictive_support_includes_signals_and_rejects_duplicates(tmp_path):
    predictions = np.array([[60000., 1, 2., 4., 1., 0., 0., 1.],
                            [60000., 2, -1., 9., 0., 1., 0., 1.]])
    covariance = np.eye(6)[None]
    sidecar = tmp_path / "support.txt"
    sidecar.write_text("# support\n60000 1 C1CG01 C2WG01\n60000 2 C1CG02 C2WG02\n")
    first = score_native_predictions(predictions, [60000.], covariance, support_path=sidecar)
    sidecar.write_text(sidecar.read_text().replace("C1CG02", "C1WG02"))
    second = score_native_predictions(predictions, [60000.], covariance, support_path=sidecar)
    assert first["predictive_support_sha256"] != second["predictive_support_sha256"]
    assert first["calibration_score"] == second["calibration_score"]
    with pytest.raises(ValueError, match="Duplicate"):
        score_native_predictions(predictions[[0,0]], [60000.], covariance)
    sidecar.write_text("60000 1 C1CG01 C2WG01\n")
    with pytest.raises(ValueError, match="support does not match"):
        score_native_predictions(predictions, [60000.], covariance, support_path=sidecar)
