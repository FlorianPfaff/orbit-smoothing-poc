"""Primary MAP scheduling must never substitute stale or fabricated covariance."""
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison import backend, groops_config


def _fake_native_fit(tmp_path, monkeypatch, method="groops_log_drag_ou", failure=None, *, retain_native=True):
    """Exercise the real wrapper and XML selection with deterministic native I/O."""
    root = tmp_path / "fit"
    observed = []
    holder = {}
    density = method == "groops_log_drag_ou"
    count = 8 if density else 9
    mjd = 60000. + np.arange(3) * 30. / 86400.
    monkeypatch.setattr(backend, "_binary", lambda job: Path(sys.executable))
    monkeypatch.setattr(backend, "_preparation", lambda job: {})
    monkeypatch.setattr(backend, "_private_data", lambda *args: None)

    def build(prepared, private, method, parameters):
        private.mkdir(parents=True)
        paths = {key: str(private / filename) for key, filename in {
            "orbit":"orbit.txt", "orbit_native":"output_orbit.dat", "parameters":"parameters.txt",
            "covariance":"covariance.txt", "covariance_observations":"observation_covariance.txt",
            "parameter_covariance":"parameter_covariance.txt", "preprocessing_audit":"audit.txt",
        }.items()}
        native = {key:str(private / (key+".dat")) for key in ("orbit", "variational", "attitude")}
        for path in native.values(): Path(path).write_bytes(b"native fixture")
        Path(paths["preprocessing_audit"]).write_text("unchanged observations\n")
        tree = ET.Element("groops")
        processing = ET.SubElement(ET.SubElement(tree, "program"), "GnssProcessing")
        dynamic = ET.SubElement(ET.SubElement(processing, "parametrization"), "leoDynamicOrbits")
        for tag, key in (("outputfileCovariance", "covariance"),
                         ("outputfileParameterCovariance", "parameter_covariance"),
                         ("outputfileCovarianceObservationEpochs", "covariance_observations")):
            ET.SubElement(dynamic, tag).text = paths[key]
        for step in (("estimate", "resolveAmbiguities", "estimate") if method.endswith("_ar") else ("estimate",)):
            ET.SubElement(ET.SubElement(processing, "processingStep"), step)
        for step in ("computeCovarianceMatrix", "writeResults"):
            ET.SubElement(ET.SubElement(processing, "processingStep"), step)
        estimate = backend._save_xml(tree, private / "estimate.xml")
        variational = backend._save_xml(ET.Element("variational"), private / "variational.xml")
        if density:
            np.savetxt(private / "log_density.txt", [[mjd[0], 0.], [mjd[-1], 0.]])
        config = {"configs":{"estimate":str(estimate), "variational":str(variational)},
                  "result_paths":paths, "native_paths":native}
        holder.update(config)
        # A stale valid-looking covariance must never rescue a missing final output.
        for key in ("covariance", "covariance_observations"):
            np.savetxt(paths[key], np.column_stack([mjd, np.tile(np.eye(6).ravel(), (3, 1))]))
        return config

    monkeypatch.setattr(groops_config, "build_fit_configs", build)

    def run(binary, config_path, directory, label, **kwargs):
        record = {"elapsed_seconds":1., "peak_rss_bytes":1024, "returncode":0,
                  "config_sha256":backend.file_hash(config_path)}
        if label != "estimate": return record
        tree = ET.parse(config_path)
        processing = tree.find(".//GnssProcessing")
        steps = [list(step)[0].tag for step in processing.findall("processingStep")]
        computed = "computeCovarianceMatrix" in steps
        outputs = {node.tag for node in processing.findall("parametrization/leoDynamicOrbits/*")}
        observed.append({"computed":computed, "steps":steps, "outputs":outputs})
        assert computed == ("outputfileCovariance" in outputs)
        assert computed == ("outputfileCovarianceObservationEpochs" in outputs)
        assert (computed and retain_native) == ("outputfileParameterCovariance" in outputs)
        if computed and failure == "native_final":
            raise backend.NativeExecutionError("final inverse failed", execution=record)
        states = np.tile([7e6, 0., 0., 0., 7500., 0.], (3,1))
        if failure == "nonconverged": states[:, 0] += len(observed)
        if failure == "final_not_small" and computed: states[:, 0] += 1.
        np.savetxt(holder["result_paths"]["orbit"], np.column_stack([mjd, states]))
        Path(holder["result_paths"]["orbit_native"]).write_bytes(b"estimated native orbit")
        parameters = np.zeros(count)
        if density and len(observed) == 1: parameters[:2] = .01
        np.savetxt(holder["result_paths"]["parameters"], parameters)
        if computed and failure != "missing_final":
            blocks = np.tile(np.eye(6), (3,1,1))
            if failure == "invalid_final": blocks[1,0,0] = -1.
            for key in ("covariance", "covariance_observations"):
                np.savetxt(holder["result_paths"][key], np.column_stack([mjd, blocks.reshape(3,36)]))
            if "parameter_covariance" in holder["result_paths"]:
                np.savetxt(holder["result_paths"]["parameter_covariance"], np.eye(count))
        return record

    monkeypatch.setattr(backend, "run_native", run)
    job = {"method":method, "parameters":{}, "stage":"synthetic", "source_hash":"fixture",
           "force_model_hash":"force", "measurement_model_hash":"measurement",
           "backend":{"retain_native_diagnostics":retain_native},
           "numerical_controls":{"maximum_outer_iterations":3}}
    result = backend.fit_job(job, root)
    return root, result, observed


@pytest.mark.parametrize("method", ["groops_pulses", "groops_log_drag_ou"])
def test_primary_covariance_only_at_final_confirmation(tmp_path, monkeypatch, method):
    root, result, observed = _fake_native_fit(tmp_path, monkeypatch, method)
    assert result["status"] == "complete" and result["converged"] and result["covariance_valid"]
    assert [row["computed"] for row in observed] == [False, False, True]
    assert result["metadata"]["final_covariance_confirmation"]
    assert result["metadata"]["covariance_schedule"] == "final_confirmation_only"
    history = json.loads((root / "outer_iterations.json").read_text())["iterations"]
    assert [row["covariance_valid"] for row in history] == [None, None, True]
    assert history[0]["invalid_covariance_epochs"] is None
    with np.load(root / "fit.npz") as data:
        assert data["covariance"].shape == (3,6,6)
        assert data["prediction_covariance"].shape == (3,6,6)
    assert (root / "native-fit/estimate_map.xml").exists()


def test_native_ar_covariance_and_resolution_sequence_unchanged(tmp_path, monkeypatch):
    _, result, observed = _fake_native_fit(tmp_path, monkeypatch, "groops_pulses_ar")
    assert result["converged"] and result["covariance_valid"]
    assert [row["computed"] for row in observed] == [True, True, True]
    assert all(row["steps"] == ["estimate", "resolveAmbiguities", "estimate", "computeCovarianceMatrix", "writeResults"] for row in observed)
    assert result["metadata"]["covariance_schedule"] == "every_iteration_native_ar"


@pytest.mark.parametrize("failure", ["native_final", "missing_final", "invalid_final", "final_not_small", "nonconverged"])
def test_unaccepted_final_fit_preserves_map_without_claiming_covariance(tmp_path, monkeypatch, failure):
    root, result, observed = _fake_native_fit(tmp_path, monkeypatch, failure=failure)
    assert result["status"] == "failed" and not result["converged"] and not result["covariance_valid"]
    assert not (root / "fit.npz").exists()
    assert result["elapsed_seconds"] >= 0 and result["peak_rss_bytes"] == 1024
    diagnostic = next(item for item in result["artifacts"] if item["role"] == "last_map_diagnostics")
    assert not diagnostic["metadata"]["covariance_included"]
    with np.load(diagnostic["path"]) as data:
        assert data["states"].shape == (3,6) and data["parameters"].shape == (8,)
        assert "covariance" not in data.files and "prediction_covariance" not in data.files
    runtime = json.loads((root / "native_runtime.json").read_text())
    assert runtime["execution"] and runtime["error"]
    if failure == "nonconverged": assert not any(row["computed"] for row in observed)
    if failure == "missing_final": assert not (root / "native-fit/covariance.txt").exists()
