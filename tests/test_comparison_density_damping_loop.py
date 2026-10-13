"""Density relaxation must preserve raw convergence and final covariance identity.

The native programs are replaced by a small, exact affine trajectory model here.
The real fit loop, damping XML builder, file updates and artifact exporter run.
This isolates orchestration invariants; it does not replace native numerical gates.
"""
from pathlib import Path
import json
import shutil
import sys
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison import backend, groops_config


def _density_fit(tmp_path, monkeypatch, failure=None):
    shared = tmp_path / "prepared"
    shared.mkdir()
    root = tmp_path / "fit"
    mjd = 60000.+np.arange(3)*30./86400.
    initial = np.array([7e6, 0., 0., 0., 7500., 0.])
    sensitivity = 1e-10 if failure == "tiny_accepted_nonconvergence" else 1.
    pattern = np.array([1., .5])
    proposed, accepted, holder = [], [], {}

    def trajectory(state, density):
        result = np.tile(state, (3, 1))
        result[:, :3] += np.arange(3)[:, None]*30.*state[None, 3:]
        result[:, 1] += sensitivity*np.array([0., 1., 4.])*sum(density)
        result[:, 4] += sensitivity*np.array([0., 2., 4.])*sum(density)/30.
        return result

    np.savetxt(shared/"orbit.dat", np.column_stack([mjd, trajectory(initial, [0., 0.])]))
    (shared/"receiver.dat").write_bytes(b"immutable receiver observations and geometry")
    (shared/"attitude.dat").write_bytes(b"immutable spacecraft attitude")
    shared_hashes = {path.name:backend.file_hash(path) for path in shared.iterdir()}
    monkeypatch.setattr(backend, "_binary", lambda job:Path(sys.executable))
    monkeypatch.setattr(backend, "_preparation", lambda job:{})

    def copy_private(prepared, private):
        private.mkdir(parents=True)
        shutil.copy2(shared/"orbit.dat", private/"orbit.dat")
        for name in ("receiver.dat", "attitude.dat"):
            (private/name).symlink_to(shared/name)
    monkeypatch.setattr(backend, "_private_data", copy_private)

    def build(prepared, private, method, parameters):
        native = {name:str(private/(name+".dat")) for name in ("orbit", "variational", "attitude")}
        Path(native["variational"]).write_bytes(b"linear model fixture")
        paths = {name:str(private/name) for name in ("orbit.txt", "output_orbit.dat", "parameters.txt",
            "covariance.txt", "observation_covariance.txt", "parameter_covariance.txt", "audit.txt")}
        outputs = dict(zip(("orbit", "orbit_native", "parameters", "covariance",
            "covariance_observations", "parameter_covariance", "preprocessing_audit"), paths.values()))
        Path(outputs["preprocessing_audit"]).write_text("same fixed observations, weights and nuisance arcs")
        np.savetxt(private/"log_density.txt", [[mjd[0], 0.], [mjd[-1], 0.]])
        estimate = ET.Element("groops")
        processing = ET.SubElement(ET.SubElement(estimate, "program"), "GnssProcessing")
        dynamic = ET.SubElement(ET.SubElement(processing, "parametrization"), "leoDynamicOrbits")
        ET.SubElement(ET.SubElement(dynamic, "ephemerides"), "jpl")
        ET.SubElement(dynamic, "integrationDegree").text = "7"
        force = ET.SubElement(ET.SubElement(dynamic, "parametrizationAcceleration"), "logDensity")
        ET.SubElement(force, "inputfileLogDensity").text = str(private/"log_density.txt")
        prior = ET.SubElement(ET.SubElement(processing, "parametrization"), "logDensityOu")
        for name, value in (("tau", "7200"), ("sigma", ".3"),
                            ("inputfileLogDensity", str(private/"log_density.txt"))):
            ET.SubElement(prior, name).text = value
        for tag, key in (("outputfileCovariance", "covariance"),
            ("outputfileCovarianceObservationEpochs", "covariance_observations"),
            ("outputfileParameterCovariance", "parameter_covariance")):
            ET.SubElement(dynamic, tag).text = outputs[key]
        for name in ("estimate", "computeCovarianceMatrix", "writeResults"):
            ET.SubElement(ET.SubElement(processing, "processingStep"), name)
        var = ET.Element("groops")
        global_node = ET.SubElement(var, "global")
        ET.SubElement(global_node, "time", label="timeStart").text = "60000"
        ET.SubElement(global_node, "time", label="timeEnd").text = "60001"
        configs = {"estimate":backend._save_xml(estimate, private/"estimate.xml"),
                   "variational":backend._save_xml(var, private/"variational.xml")}
        holder.update(date="2023-02-25", configs=configs, native_paths=native, result_paths=outputs)
        # A leftover inverse must not rescue a missing confirmation export.
        for name in ("covariance", "covariance_observations"):
            np.savetxt(outputs[name], np.column_stack([mjd, np.tile(np.eye(6).ravel(), (3, 1))]))
        return holder
    monkeypatch.setattr(groops_config, "build_fit_configs", build)

    def run(binary, configuration, directory, label, **kwargs):
        record = {"elapsed_seconds":1., "peak_rss_bytes":2048, "returncode":0,
                  "config_sha256":backend.file_hash(configuration)}
        tree = ET.parse(configuration)
        if label == "variational":
            return record
        if label == "read_previous_orbit":
            node = tree.find(".//FileConvert")
            shutil.copy2(node.findtext("inputfile"), node.findtext("outputfile"))
            return record
        reference = backend.read_native_table(root/"native-fit/log_density.txt", 2)[:, 1].copy()
        if label == "accept_step":
            node = tree.find(".//OrbitPocEvaluateVariational")
            vector = backend.read_native_table(node.findtext("inputfileParameters")).ravel()
            target = backend.read_native_table(node.findtext("inputfileInitialState")).ravel()
            # This mirrors native state reanchoring: the six state coefficients
            # are replaced so both density and initial-state steps share alpha.
            states = trajectory(target, reference+vector[:2])
            output = Path(node.findtext("outputfileOrbit"))
            np.savetxt(output, np.column_stack([mjd, states]))
            shutil.copy2(output, output.with_suffix(".txt"))
            accepted.append({"reference":reference, "increment":vector[:2],
                             "initial":target, "states":states})
            return record
        assert label == "estimate"
        computed = tree.find(".//computeCovarianceMatrix") is not None
        index = len(proposed)
        dg, di = [(0.8, 4.), (-.1, -1.), (2e-6, 1e-6), (1e-6, .5e-6)][min(index, 3)]
        if failure == "tiny_accepted_nonconvergence": dg, di = 1., 0.
        if computed and failure == "large_confirmation": dg = .1
        prior_initial = np.loadtxt(holder["native_paths"]["orbit"])[0, 1:7]
        target = prior_initial.copy(); target[0] += di
        vector = np.concatenate([dg*pattern, np.array([di, 0., 0., 0., 0., 0.])])
        states = trajectory(target, reference+vector[:2])
        outputs = holder["result_paths"]
        for name in ("orbit", "orbit_native"):
            np.savetxt(outputs[name], np.column_stack([mjd, states]))
        np.savetxt(outputs["parameters"], vector)
        proposed.append({"computed":computed, "reference":reference, "increment":vector[:2],
                         "prior_initial":prior_initial, "initial":target, "states":states})
        if computed and failure != "missing_covariance":
            blocks = np.tile((1.+reference[0])*np.eye(6), (3, 1, 1))
            if failure == "indefinite_covariance": blocks[1, 0, 0] = -1.
            for name in ("covariance", "covariance_observations"):
                epochs = mjd+1e-3 if failure == "wrong_covariance_epochs" else mjd
                np.savetxt(outputs[name], np.column_stack([epochs, blocks.reshape(3, 36)]))
            np.savetxt(outputs["parameter_covariance"], (1.+reference[0])*np.eye(8))
        return record
    monkeypatch.setattr(backend, "run_native", run)
    controls = {"maximum_outer_iterations":4}
    if failure == "tiny_accepted_nonconvergence":
        controls.update(maximum_outer_iterations=3, maximum_accepted_log_density_increment=1e-8)
    job = {"method":"groops_log_drag_ou", "parameters":{}, "stage":"synthetic",
        "source_hash":"fixture", "force_model_hash":"force", "measurement_model_hash":"measurement",
        "backend":{"retain_native_diagnostics":True}, "numerical_controls":controls}
    result = backend.fit_job(job, root)
    assert {path.name:backend.file_hash(path) for path in shared.iterdir()} == shared_hashes
    return root, result, proposed, accepted


def test_damped_state_and_density_steps_match_final_undamped_covariance(tmp_path, monkeypatch):
    root, result, proposed, accepted = _density_fit(tmp_path, monkeypatch)
    assert result["status"] == "complete" and result["covariance_valid"]
    assert [row["computed"] for row in proposed] == [False, False, False, True]
    assert len(accepted) == 3
    np.testing.assert_allclose(accepted[0]["increment"], [.5, .25])
    np.testing.assert_allclose(accepted[0]["initial"],
        proposed[0]["prior_initial"]+.625*(proposed[0]["initial"]-proposed[0]["prior_initial"]))
    np.testing.assert_allclose(accepted[1]["increment"], [-.05, -.025])
    for index, row in enumerate(accepted):
        np.testing.assert_allclose(proposed[index+1]["reference"], row["reference"]+row["increment"])
    reference = backend.read_native_table(root/"native-fit/log_density.txt", 2)[:, 1]
    posterior = backend.read_native_table(root/"posterior_log_density.txt", 2)[:, 1]
    np.testing.assert_allclose(reference, proposed[-1]["reference"])
    np.testing.assert_allclose(posterior, reference+proposed[-1]["increment"], rtol=0, atol=1e-16)
    with np.load(root/"fit.npz") as data:
        np.testing.assert_array_equal(data["states"], proposed[-1]["states"])
        np.testing.assert_allclose(data["covariance"], np.tile((1.+reference[0])*np.eye(6), (3, 1, 1)))
    history = json.loads((root/"outer_iterations.json").read_text())["iterations"]
    assert history[-2]["criteria_met"] and not history[-2]["covariance_computed"]
    assert history[-2]["density_step"]["scale"] == .5
    assert history[-1]["final_confirmation"] and history[-1]["density_step"]["scale"] == 1.
    assert history[-1]["maximum_log_density_update"] == 1e-6
    prior = ET.parse(root/"native-fit/estimate.xml").find(".//logDensityOu")
    assert prior.findtext("sigma") == ".3" and prior.findtext("tau") == "7200"


@pytest.mark.parametrize("failure", ["large_confirmation", "missing_covariance", "indefinite_covariance", "wrong_covariance_epochs"])
def test_invalid_undamped_confirmation_never_exports_a_fitted_posterior(tmp_path, monkeypatch, failure):
    root, result, proposed, _ = _density_fit(tmp_path, monkeypatch, failure)
    assert proposed[-1]["computed"]
    assert result["status"] == "failed" and not result["converged"] and not result["covariance_valid"]
    assert not (root/"fit.npz").exists() and not (root/"posterior_log_density.txt").exists()
    np.testing.assert_array_equal(backend.read_native_table(root/"native-fit/log_density.txt", 2)[:, 1],
                                  proposed[-1]["reference"])
    with np.load(root/"last_map.npz") as data:
        assert "covariance" not in data.files and "prediction_covariance" not in data.files
        np.testing.assert_array_equal(data["states"], proposed[-1]["states"])
    if failure == "large_confirmation":
        final = json.loads((root/"outer_iterations.json").read_text())["iterations"][-1]
        assert final["maximum_log_density_update"] == .1
        assert final["density_step"]["scale"] == 1.
        assert not final["criteria_met"]


def test_tiny_accepted_steps_cannot_hide_large_raw_density_updates(tmp_path, monkeypatch):
    root, result, proposed, accepted = _density_fit(tmp_path, monkeypatch, "tiny_accepted_nonconvergence")
    assert result["status"] == "failed" and not result["covariance_valid"]
    assert not any(row["computed"] for row in proposed)
    assert all(np.max(np.abs(row["increment"])) == 1e-8 for row in accepted)
    history = json.loads((root/"outer_iterations.json").read_text())["iterations"]
    assert history[-1]["maximum_orbit_change_m"] < 3e-5
    assert all(row["maximum_log_density_update"] == 1. for row in history)
    assert not any(row["criteria_met"] for row in history)
    assert not (root/"fit.npz").exists()
    with np.load(root/"last_map.npz") as data:
        assert "covariance" not in data.files
