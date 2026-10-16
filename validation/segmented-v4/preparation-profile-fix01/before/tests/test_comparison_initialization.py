"""Initialization preserves the frozen receiver geometry and exact native epochs."""
from decimal import Decimal
from pathlib import Path
import os
import runpy
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison import backend
from orbit_poc.comparison.initialization import _standalone, close_nominal_reference


def prepared(tmp_path):
    paths = {}
    for name in ("orbit", "receiver", "receiver_orbit", "receiver_attitude", "attitude"):
        path = tmp_path / (name + ".dat")
        path.write_bytes(name.encode())
        paths[name] = str(path)
    source = ET.fromstring("""<groops><global>
      <time label="timeStart">60424</time><time label="timeEnd">timeStart+120.1/86400</time>
      </global><program><PreprocessingVariationalEquation><forces><syntheticGravity/></forces>
      <ephemerides><jpl/></ephemerides></PreprocessingVariationalEquation></program>
      <program><PreprocessingVariationalEquationOrbitFit/></program></groops>""")
    config = tmp_path / "variational.xml"
    ET.ElementTree(source).write(config)
    return {"date":"2024-04-24", "native_paths":paths, "configs":{"variational":str(config)},
            "preprocessing_orbit_path":paths["receiver_orbit"]}


def fake_native(monkeypatch, offsets):
    calls = []
    state = np.array([[1.,2.,3.,4.,5.,6.], [11.,12.,13.,14.,15.,16.]])

    def execute(binary, config, output_dir, label, **kwargs):
        tree = ET.parse(config)
        node = tree.find(".//OrbitPocEvaluateVariational")
        orbit = Path(node.findtext("outputfileOrbit"))
        current = state.copy()
        current[1, 0] += offsets[len(calls)]
        if calls:
            assert tree.find(".//PreprocessingVariationalEquationOrbitFit") is None
            fixed = backend.read_native_table(node.findtext("inputfileInitialState")).ravel()
            np.testing.assert_array_equal(fixed, state[0])
        assert node.find("parametrizationAcceleration") is None
        assert node.find("stochasticPulse") is None
        orbit.parent.mkdir(parents=True, exist_ok=True)
        orbit.write_bytes(current.tobytes())
        np.savetxt(orbit.with_suffix(".txt"), np.c_[np.array([60424.,60424.+5/86400]), current, np.zeros((2,3))])
        calls.append(str(config))
        return {"returncode":0, "config":str(config)}

    monkeypatch.setattr(backend, "run_native", execute)
    return calls


def test_closure_replaces_only_dynamic_orbit_after_convergence(tmp_path, monkeypatch):
    config = prepared(tmp_path)
    binary = tmp_path / "native"; binary.write_bytes(b"fixed binary")
    original = {key:Path(value).read_bytes() for key,value in config["native_paths"].items()}
    calls = fake_native(monkeypatch, [0., .01, .0100005])
    result = close_nominal_reference(config, binary, tmp_path/"closure")
    assert result["converged"] and len(result["iterations"]) == 2
    assert len(calls) == 3
    assert result["immutable_inputs_unchanged"]
    for key,path in config["native_paths"].items():
        if key == "orbit": assert Path(path).read_bytes() != original[key]
        else: assert Path(path).read_bytes() == original[key]


def test_nonclosure_never_overwrites_bootstrap(tmp_path, monkeypatch):
    config = prepared(tmp_path)
    binary = tmp_path / "native"; binary.write_bytes(b"fixed binary")
    original = Path(config["native_paths"]["orbit"]).read_bytes()
    fake_native(monkeypatch, [0.,1.])
    with pytest.raises(RuntimeError, match="failed to close"):
        close_nominal_reference(config,binary,tmp_path/"closure",maximum_iterations=1)
    assert Path(config["native_paths"]["orbit"]).read_bytes() == original
    import json
    assert json.loads((tmp_path/"closure/initialization.json").read_text())["status"] == "failed"


def test_dynamic_orbit_cannot_alias_receiver_geometry(tmp_path):
    config = prepared(tmp_path)
    config["native_paths"]["receiver_orbit"] = config["native_paths"]["orbit"]
    with pytest.raises(ValueError, match="separate files"):
        close_nominal_reference(config,tmp_path/"unused",tmp_path/"closure")


def test_common_preparation_helper_retains_closure_hashes_and_execution(tmp_path, monkeypatch):
    config = prepared(tmp_path)
    binary = tmp_path / "native"; binary.write_bytes(b"fixed binary")
    fake_native(monkeypatch, [0., .01, .0100005])
    receiver_before = Path(config["native_paths"]["receiver_orbit"]).read_bytes()
    executions = backend._close_prepared_nominal_reference(config, binary, tmp_path/"prepare")
    assert len(executions) == 3
    evidence = config["nominal_initialization"]
    assert evidence["converged"] and evidence["iterations"] == 2
    blind = backend._blind_record(config)
    roles = {item["role"] for item in blind["native_artifacts"]}
    assert {"nominal_initialization", "fixed_initial_state"} <= roles
    for item in blind["native_artifacts"]:
        assert backend.file_hash(item["path"]) == item["sha256"]
    assert Path(config["native_paths"]["receiver_orbit"]).read_bytes() == receiver_before


def test_reused_synthetic_preparation_closes_reference_before_blinding(tmp_path, monkeypatch):
    import json
    from orbit_poc.comparison import groops_config, synthetic
    script = Path(__file__).resolve().parents[1]/"scripts/validate_comparison_native.py"
    diagnostic = runpy.run_path(str(script))
    config = prepared(tmp_path)
    config.update(output_dir=str(tmp_path), estimation_inputs=[],
        force_model_hash="force", measurement_model_hash="measurement",
        preprocessing_hash="preprocessing", mask_hash="mask")
    config["configs"]["convert_receiver"] = config["configs"]["variational"]
    binary = tmp_path/"native"; binary.write_bytes(b"fixed binary")
    case = {"epoch":"2024-04-24T00:00:00", "seed":300000, "orbit":"leo500",
        "atmosphere":"quiet", "duration_hours":1., "mask":{"intervals_seconds":[[1200,1800]]}}
    raw = {"status":"observations_ready", "case":case, "estimation_inputs":[],
        "evaluation_inputs":[], "native_simulation":{"noise":synthetic.NOISE_MODEL,
        "simulation_wavelength_factor":1.}}
    manifest=tmp_path/"manifest.json"; manifest.write_text(json.dumps(raw))
    monkeypatch.setattr(groops_config,"build_day_configs",lambda *a,**k:config)
    diagnostic["prepare_existing_observations"].__globals__["configure_synthetic_forces"] = lambda value,*a:value
    monkeypatch.setattr(backend,"_link_cached_transmitters",lambda *a:{"reused":True})
    monkeypatch.setattr(backend,"_verify_transmitters",lambda *a:None)
    calls = fake_native(monkeypatch,[0.,.01,.0100005])
    execute=backend.run_native
    monkeypatch.setattr(backend,"run_native",lambda binary,path,root,label,**kw:
        {"label":label} if label=="convert_receiver" else execute(binary,path,root,label,**kw))
    job={"case":case,"backend":{"groops_executable":str(binary),
        "example_directory":"unused","auxiliary_dir":"unused"}}
    result=diagnostic["prepare_existing_observations"](manifest,job,tmp_path/"reused")
    assert len(calls)==3 and len(result["native_execution"])==5
    assert result["nominal_initialization"]["converged"]
    assert result["native_binary_sha256"]==backend.file_hash(binary)
    blind=json.loads((tmp_path/"reused/native_preparation.json").read_text())
    assert blind["nominal_initialization"]==result["nominal_initialization"]
    assert all(backend.file_hash(item["path"])==item["sha256"] for item in blind["native_artifacts"])


@pytest.mark.parametrize("offset", [0,18])
def test_native_closure_loop_boundaries_use_offset_once(tmp_path, offset):
    binary = os.environ.get("ORBIT_POC_GROOPS")
    if not binary: pytest.skip("Set ORBIT_POC_GROOPS for native Time regression")
    config = prepared(tmp_path)
    source = ET.parse(config["configs"]["variational"]).getroot()
    program = ET.fromstring(f"""<TimeSeriesCreate><outputfileTimeSeries>{tmp_path/'times.txt'}</outputfileTimeSeries>
      <timeSeries><uniformSampling><timeStart>loopTime</timeStart><timeEnd>loopTimeEnd</timeEnd>
      <sampling>60/86400</sampling><offsetSeconds>{offset}</offsetSeconds></uniformSampling></timeSeries></TimeSeriesCreate>""")
    tree = _standalone(source,[program],config["date"])
    path = tmp_path/'times.xml'; ET.ElementTree(tree).write(path)
    execution = subprocess.run([str(Path(binary).resolve()),str(path)],capture_output=True,text=True,timeout=30,
        env={**os.environ,"OPENBLAS_NUM_THREADS":"1","OMP_NUM_THREADS":"1"})
    assert execution.returncode == 0, execution.stdout+execution.stderr
    seconds=[(Decimal(line.split()[0])-60424)*86400 for line in (tmp_path/'times.txt').read_text().splitlines()
             if line.strip().startswith('60424')]
    assert len(seconds)==3
    assert max(abs(second-(offset+60*i)) for i,second in enumerate(seconds)) < Decimal('1e-9')
