"""Independent Tudat trajectories observed with the native GROOPS GNSS model.

Only generation reads truth.  The returned estimation manifest contains receiver
measurements, known attitude and transmitter products; bootstrap is deferred until
masking by the common flight preprocessor.  No approximate range formula is used.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import fcntl
import xml.etree.ElementTree as ET

import numpy as np
from scipy.spatial.transform import Rotation

from .data import CODE_PRODUCTS, artifact, canonical_hash, fetch_url, sha256_file, write_json
from .groops_config import _add, _save, _template

SIGNALS = ("C1CG**", "C1WG**", "C2WG**", "L1CG**", "L1WG**", "L2WG**")
WAVELENGTHS = {"1": 299792458. / 1575.42e6, "2": 299792458. / 1227.60e6}
NOISE_MODEL = {"code_sigma_m": 0.3, "phase_sigma_m": 0.003,
               "distribution": "independent Gaussian per signal and observation",
               "angular_dependence": "constant"}


def write_synthetic_accuracy(path):
    """Constant native accuracy pattern, shared by simulation and inference."""
    root = ET.Element("groops", type="antennaDefinition", version="20190429")
    _add(root, "antennaCount", 1)
    antenna = _add(root, "antenna")
    for tag, text in (("name", "GRACEC-MAIN"), ("serial", ""), ("radome", ""),
                      ("comment", "Synthetic v3 independent constant code/phase noise")):
        _add(antenna, tag, text)
    patterns = _add(antenna, "pattern")
    _add(patterns, "count", len(SIGNALS))
    for signal in SIGNALS:
        cell = _add(patterns, "cell")
        _add(cell, "type", signal)
        offset = _add(cell, "offset")
        for axis in "xyz":
            _add(offset, axis, 0)
        _add(cell, "dZenit", 90.)
        matrix = _add(cell, "pattern")
        _add(matrix, "type", 0)
        _add(matrix, "rows", 1)
        _add(matrix, "columns", 3)
        sigma = NOISE_MODEL["code_sigma_m" if signal.startswith("C") else "phase_sigma_m"]
        for column in range(3):
            ET.SubElement(matrix, "cell", row="0", col=str(column)).text = str(sigma)
    return _save(root, path)


def read_receiver_ascii(path):
    """Read native ASCII GNSSRECEIVER arcs, rejecting unsupported constellations."""
    lines = Path(path).read_text().splitlines()
    if not lines or not lines[0].startswith("groops instrument version="):
        raise ValueError("Native GNSS receiver must be exported as GROOPS ASCII")
    tokens = iter(" ".join(line.split("#", 1)[0] for line in lines[1:]).split())
    try:
        if int(next(tokens)) != -11:
            raise ValueError("Expected GNSSRECEIVER instrument type -11")
        arcs = int(next(tokens))
        epochs = []
        for _ in range(arcs):
            for _ in range(int(next(tokens))):
                mjd = np.longdouble(next(tokens))
                types = [next(tokens) for _ in range(int(next(tokens)))]
                satellites = [next(tokens) for _ in range(int(next(tokens)))]
                observations = [float(next(tokens)) for _ in range(int(next(tokens)))]
                clock = float(next(tokens))
                if any(len(s) < 6 or s[3] != "G" for s in satellites):
                    raise ValueError("Synthetic export currently supports GPS only")
                if len(observations) != len(types) * len(satellites):
                    raise ValueError("Incomplete native receiver observation matrix")
                if not np.all(np.isfinite(observations)) or not np.isfinite(clock):
                    raise ValueError("Nonfinite native receiver observations")
                epochs.append({"mjd": mjd, "types": types, "satellites": satellites,
                               "observations": np.asarray(observations).reshape(len(satellites), len(types)),
                               "clock_seconds": clock})
        if next(tokens, None) is not None:
            raise ValueError("Unexpected trailing native receiver data")
    except StopIteration as error:
        raise ValueError("Truncated native receiver file") from error
    if not epochs or any(a["mjd"] >= b["mjd"] for a, b in zip(epochs, epochs[1:])):
        raise ValueError("Receiver epochs must be nonempty and strictly ordered")
    return epochs


def receiver_to_gps1b(source, target, *, seed, mjd_start, slips=True):
    """Lossless metre-valued code/phase export plus paired, seeded cycle slips.

    A per-PRN random stream determines slip epoch and integer jumps, independently
    of masks and observation order. Native initial ambiguities are already present.
    Receiver clock truth is deliberately omitted from the exported measurements.
    """
    epochs = read_receiver_ascii(source)
    records, slip_records = [], []
    schedules = {}
    duration = float((epochs[-1]["mjd"]-np.longdouble(mjd_start))*86400)
    for epoch in epochs:
        required = [epoch["types"].index(s) if s in epoch["types"] else None for s in SIGNALS]
        if any(i is None for i in required):
            raise ValueError("Native simulation lacks one of the six required GPS code/phase signals")
        elapsed = float((epoch["mjd"]-np.longdouble(mjd_start))*86400)
        microseconds = int(np.rint((epoch["mjd"]-np.longdouble("51544.5"))*86400*1e6))
        # GROOPS long-double output supports microsecond timing; synthetic epochs
        # are on the exact 30-second GPS grid, remove decimal roundoff only.
        if abs(microseconds / 1e6 - round(microseconds / 1e6)) < 2e-6:
            microseconds = round(microseconds / 1e6) * 1000000
        seconds, fraction = divmod(microseconds, 1000000)
        for satellite, values in zip(epoch["satellites"], epoch["observations"]):
            prn = int(satellite[4:6])
            if prn not in schedules:
                rng = np.random.default_rng(np.random.SeedSequence([int(seed), 7139, prn]))
                when = float(rng.uniform(.3, .7)*duration)
                jumps = rng.integers(10, 60, size=2) * rng.choice([-1, 1], size=2)
                schedules[prn] = when, jumps
                slip_records.append({"prn": prn, "elapsed_seconds": when,
                                     "cycles_l1": int(jumps[0]), "cycles_l2": int(jumps[1])})
            selected = values[required].copy()
            when, jumps = schedules[prn]
            if slips and elapsed >= when:
                selected[3:5] += jumps[0] * WAVELENGTHS["1"]
                selected[5] += jumps[1] * WAVELENGTHS["2"]
            records.append(f"{seconds} {fraction} C {prn} 0 0000000000111111 00000000 " +
                           " ".join(f"{value:.10f}" for value in selected))
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"header:\n    num_records: {len(records)}\n# End of YAML header\n" + "\n".join(records) + "\n")
    return {"records": len(records), "epochs": len(epochs), "cycle_slips_enabled": bool(slips),
            "slips": slip_records if slips else [], "seed": int(seed), "receiver_clock_exported": False}


def write_truth_instruments(truth_path, directory, epoch):
    """Export independent CRF trajectory and a known nadir-pointing attitude."""
    with np.load(truth_path, allow_pickle=False) as truth:
        times, states = truth["times"], truth["states"]
    if states.shape != (len(times), 6) or not np.all(np.diff(times) > 0):
        raise ValueError("Truth must contain ordered SI Cartesian states")
    # Synthetic epoch labels use GPS; controlled dynamics are autonomous. Native
    # EOP rotation is used only by the common GNSS observation model.
    start = (datetime.fromisoformat(epoch)-datetime(1858, 11, 17)).total_seconds()/86400
    mjd = np.longdouble(start) + times.astype(np.longdouble)/86400
    acceleration = np.gradient(states[:, 3:], times, axis=0, edge_order=2)
    radius = states[:, :3] / np.linalg.norm(states[:, :3], axis=1)[:, None]
    normal = np.cross(states[:, :3], states[:, 3:])
    normal /= np.linalg.norm(normal, axis=1)[:, None]
    tangent = np.cross(normal, radius)
    # GRACE antenna points along -SRF-z; SRF x=tangent, y=-normal, z=-radial.
    frames = np.stack((tangent, -normal, -radius), axis=2)
    quaternion = Rotation.from_matrix(frames).as_quat(scalar_first=True)
    for i in range(1, len(quaternion)):
        if quaternion[i] @ quaternion[i-1] < 0:
            quaternion[i] *= -1
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True)
    orbit_path, attitude_path = root / "simulation_orbit.txt", root / "known_attitude.txt"
    for path, kind, values in ((orbit_path, -6, np.c_[states, acceleration]),
                               (attitude_path, -7, quaternion)):
        with path.open("w") as stream:
            stream.write(f"groops instrument version=20200123\n{kind} 1\n{len(times)}\n")
            for time, row in zip(mjd, values):
                stream.write(np.format_float_positional(time, precision=18) + " " +
                             " ".join(f"{value:.16e}" for value in row) + "\n")
    return {"orbit": str(orbit_path), "attitude": str(attitude_path), "mjd_start": start,
            "frame": "CRF/J2000", "time_scale": "GPS",
            "attitude_convention": "SRF x=along-track,y=-normal,z=nadir; known without noise"}


def simulation_configs(case, instruments, products, output_dir, backend):
    """Build runnable native conversion and observation simulation configs."""
    root = Path(output_dir).resolve()
    auxiliary = Path(backend["auxiliary_dir"]).resolve()
    scenario = backend.get("example_directory") or None
    date = case["epoch"][:10]
    mjd = instruments["mjd_start"]
    convert = _template("01groopsConvert.xml", scenario, root, auxiliary, date, mjd)
    roles = {entry["role"]: entry["path"] for entry in products}
    for tag, field, role in (("Sp3Format2Orbit", "inputfile", "gnss_orbits"),
                             ("GnssClockRinex2InstrumentClock", "inputfileClockRinex", "gnss_clocks"),
                             ("GnssOrbex2StarCamera", "inputfileOrbex", "gnss_attitudes"),
                             ("GnssSinexBias2SignalBias", "inputfileSinexBias", "gnss_biases")):
        for node in convert.iter(tag):
            node.find(field).text = roles[role]
    simulate = _template("04groopsGnssProcessing.xml", scenario, root, auxiliary, date, mjd)
    p = simulate.find(".//GnssProcessing")
    p.tag = "GnssSimulateReceiver"
    for node in list(p):
        if node.tag == "processingStep" or (node.tag == "parametrization" and
                any(node.find(tag) is not None for tag in ("leoDynamicOrbits", "ambiguities", "constraints"))):
            p.remove(node)
    for node in p.iter():
        if node.text:
            node.text = node.text.replace("igsR3", "igs20")
    receiver = p.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileOrbit").text = instruments["orbit"]
    receiver.find("inputfileStarCamera").text = instruments["attitude"]
    receiver.find("inputfileAccuracyDefinition").text = write_synthetic_accuracy(root/"synthetic_accuracy.xml")
    receiver.remove(receiver.find("inputfileObservations"))
    receiver.find("supportsIntegerAmbiguities").text = "0"
    # Same-frequency signal ambiguities must differ by full cycles: native
    # preprocessing repairs full-cycle offsets before sharing their ambiguity.
    receiver.find("wavelengthFactor").text = "1"
    series = p.find("timeSeries")
    series.clear()
    uniform = _add(series, "uniformSampling")
    _add(uniform, "timeStart", mjd)
    _add(uniform, "timeEnd", f"{mjd}+({case['duration_hours']}*3600-{case['cadence']})/86400")
    _add(uniform, "sampling", f"{case['cadence']}/86400")
    receiver_output = root / "receiver_unmasked.txt"
    _add(p, "outputfileGnssReceiver", receiver_output)
    _add(p, "outputfileClock", root / "simulated_clock.txt")
    for signal in SIGNALS:
        _add(p, "observationType", signal)
    for tag, sigma, salt in (("noiseObservation", 1., 17011), ("noiseClockReceiver", 30., 29131)):
        white = _add(_add(p, tag), "white")
        _add(white, "sigma", sigma)
        _add(white, "initRandom", int(case["seed"])+salt)
    return {"convert_gnss": _save(convert, root/"convert_transmitters.xml"),
            "simulate": _save(simulate, root/"simulate_receiver.xml"),
            "receiver": str(receiver_output)}


def _execute(executable, config, root, seed):
    log = Path(config).with_suffix(".log")
    environment = {**os.environ, "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                   "ORBIT_POC_SIMULATION_SEED": str(int(seed)),
                   "ORBIT_POC_SIMULATION_AMBIGUITIES": str(Path(config).with_name("ambiguity_truth.txt"))}
    with log.open("w") as stream:
        run = subprocess.run([str(executable), str(config)], cwd=root, env=environment,
                             stdout=stream, stderr=subprocess.STDOUT, check=False)
    if run.returncode:
        raise RuntimeError(f"Native synthetic generation failed ({run.returncode}); see {log}")
    return {"config": artifact(config, "generation_config"), "log": str(log), "returncode": run.returncode}


def compact_generation(root, redundant, retained):
    """Audit and remove only reproducible duplicates after final inputs exist."""
    root = Path(root).resolve()
    retained = {Path(path).resolve() for path in retained}
    if any(not path.is_file() or path.stat().st_size == 0 for path in retained):
        raise ValueError("Completed observation, attitude, and evaluation artifacts must precede pruning")
    records = []
    for item in redundant:
        path = Path(item)
        if not path.is_file() or path.is_symlink():
            continue
        path = path.resolve()
        path.relative_to(root)  # Never delete shared cached products.
        if path in retained:
            raise ValueError("A retained scientific artifact cannot be pruned")
        records.append({"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size,
            "status": "deleted_after_verified_observation_export",
            "reason": "Reproducible generation duplicate; retained GPS1B, attitude, and evaluation NPZ are authoritative"})
        path.unlink()
    return records


def prepare_synthetic_case(case, workdir, backend_cfg):
    """Generate real native GNSS measurements; common masked preprocessing follows.

    Returns ``observations_ready``, never a fit or accepted scientific result.
    Native executable and Tudat are required; there is no approximate fallback.
    """
    from ..simulator import generate
    from .data import fetch_example_auxiliary
    from .groops_config import fetch_flight_auxiliary
    backend = asdict(backend_cfg) if is_dataclass(backend_cfg) else dict(backend_cfg)
    root = Path(workdir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    fetch_example_auxiliary(backend.get("example_directory"), backend["auxiliary_dir"])
    fetch_flight_auxiliary(backend["auxiliary_dir"])
    date = case["epoch"][:10]
    day = datetime.fromisoformat(date)
    if day.year != 2024 or float(case["cadence"]) != 30:
        raise ValueError("Frozen synthetic native protocol requires 2024 products and 30-second GNSS")
    products = []
    for role, suffix in (("gnss_orbits", "05M_ORB.SP3"), ("gnss_clocks", "30S_CLK.CLK"),
                         ("gnss_biases", "01D_OSB.BIA"), ("gnss_attitudes", "30S_ATT.OBX")):
        name = f"COD0OPSFIN_2024{day.timetuple().tm_yday:03d}0000_01D_{suffix}.gz"
        rec = fetch_url(CODE_PRODUCTS+name, Path(backend["cache_dir"])/"gnss"/name)
        products.append(artifact(rec["path"], role, source_url=rec["url"]))
    truth_config = {**case, "cadence": 5, "truth_step_seconds": 5, "coverage": "normal", "truth_profile": "controlled"}
    if case.get("truth_model") == "tudat_mixed_force_stress_gnss":
        truth_config["extra_acceleration"] = mixed_force_specification(case["seed"])
    generated = generate(truth_config, root/"generation", truth_backend="tudat",
                         tudat_python=backend.get("tudat_python") or None)
    truth_path = Path(generated["truth"])
    instruments = write_truth_instruments(truth_path, root/"generation", case["epoch"])
    configs = simulation_configs(case, instruments, products, root/"generation", backend)
    conversion = cached_transmitter_conversion(case, instruments, products, root/"generation", backend)
    execution = [conversion, _execute(backend["groops_executable"], configs["simulate"], root/"generation", case["seed"])]
    observation_path = root/"observations"/f"GPS1B_{date}_C_synthetic.txt"
    export = receiver_to_gps1b(configs["receiver"], observation_path, seed=case["seed"],
                              mjd_start=instruments["mjd_start"])
    # Store explicit MJD alongside elapsed times for native post-fit comparison.
    with np.load(truth_path, allow_pickle=False) as truth:
        values = {key: truth[key] for key in truth.files}
    values["mjd"] = instruments["mjd_start"] + values["times"]/86400
    simulated_epochs = read_receiver_ascii(configs["receiver"])
    values["receiver_clock_mjd"] = np.asarray([e["mjd"] for e in simulated_epochs], dtype=float)
    values["receiver_clock_seconds"] = np.asarray([e["clock_seconds"] for e in simulated_epochs])
    ambiguity_file = root/"generation"/"ambiguity_truth.txt"
    if not ambiguity_file.is_file():
        raise RuntimeError("Native ambiguity truth export is required for the synthetic recovery gate")
    values["ambiguity_truth_text"] = np.asarray(ambiguity_file.read_text())
    values["cycle_slips_json"] = np.asarray(json.dumps(export["slips"]))
    evaluation_path = root/"evaluation"/"truth.npz"
    evaluation_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(evaluation_path, **values)
    result = {"schema_version": 1, "status": "observations_ready", "date": date,
              "stage": "synthetic", "mission": "synthetic-GRACE-receiver", "case": case,
              "duration_hours": case["duration_hours"],
              "estimation_inputs": [*products, artifact(observation_path, "gnss_observations"),
                  artifact(instruments["attitude"], "attitude", format="groops_instrument")],
              "evaluation_inputs": [artifact(evaluation_path, "truth", frame="CRF/J2000", time_scale="GPS")],
              "native_simulation": {"engine": "GnssSimulateReceiver", "seed": case["seed"],
                  "ambiguity_injection": "independent integer cycles per signal; same-frequency fractional bias is coherent",
                  "simulation_wavelength_factor": 1.,
                  "independent_trajectory": "TudatPy", "truth_sha256": sha256_file(truth_path),
                  "simulation_configs": configs, "execution": execution, "export": export,
                  "transmitter_cache": conversion,
                  "measurement_parity": "shared native observation model; numerical gate still required",
                  "noise": {**NOISE_MODEL, "receiver_clock_sigma_m": 30.,
                            "accuracy_definition_sha256": sha256_file(root/"generation"/"synthetic_accuracy.xml")},
                  "mask_applied": False, "bootstrap_performed": False},
              "missing": ["masked_gnss_only_bootstrap", "common_native_preparation", "numerical_parity_gate"]}
    retention = {"retain_native_diagnostics": bool(backend.get("retain_native_diagnostics", False)),
                 "deleted_outputs": []}
    if not retention["retain_native_diagnostics"]:
        retention["deleted_outputs"] = compact_generation(root,
            [configs["receiver"], instruments["orbit"], generated["truth"], generated["dataset"],
             root/"generation"/"simulated_clock.txt", ambiguity_file],
            [observation_path, instruments["attitude"], evaluation_path])
    result["native_simulation"]["retention"] = retention
    write_json(root/"data_manifest.json", result)
    return result


def configure_synthetic_forces(configured, case, backend=None):
    """Replace the flight force recipe identically for both controlled-truth arms.

    Native acceleration choices use a fixed CRF-z J2 and rigid atmosphere.  The
    native variational gravity gradient remains degree two and therefore requires
    the independent derivative/convergence gates before campaign acceptance.
    """
    result = deepcopy(configured)
    # Native fits privately clone data/, preserving this immutable shared input.
    accuracy = write_synthetic_accuracy(Path(result["output_dir"])/"data"/"synthetic_accuracy.xml")
    gravity_parameters = {"GM": 3.986004418e14, "J2": 1.08262668e-3, "R": 6378137.}
    drag_parameters = {"ballisticCoefficient": .022, "referenceDensity": 5e-13,
                       "referenceAltitude": 500000., "scaleHeight": 60000.,
                       "earthRadius": 6378137., "earthRotationRate": 7.2921150e-5}
    native_recipe = {"gravity": gravity_parameters, "drag": drag_parameters,
                     "axes": "CRF-z", "empirical_acceleration": False}
    def drag_node(parent):
        node = _add(parent, "syntheticDrag")
        for key, value in drag_parameters.items():
            _add(node, key, value)
    for label in ("variational", "estimate"):
        path = result["configs"][label]
        tree = ET.parse(path).getroot()
        # UTC driver discontinuities belong to the flight atmosphere only.
        # Remove its separately integrated force and sensitivity event flags
        # before replacing the common model with continuous synthetic drag.
        for parent in tree.iter():
            for child in list(parent):
                if child.tag in {"orbitPocAtmosphericForce", "orbitPocAtmosphereEvents", "orbitPocAtmosphericHasDensityKnots", "orbitPocAtmosphericQuadratureStep"}:
                    parent.remove(child)
        for forces in tree.findall(".//PreprocessingVariationalEquation/forces"):
            previous = forces.find("miscAccelerations/logDensity")
            wrapper = deepcopy(previous) if previous is not None else None
            forces.clear()
            gravity = _add(_add(forces, "miscAccelerations"), "syntheticGravity")
            for key, value in gravity_parameters.items():
                _add(gravity, key, value)
            acceleration = _add(forces, "miscAccelerations")
            if wrapper is None:
                drag_node(acceleration)
            else:
                nominal = wrapper.find("nominalDrag")
                nominal.clear()
                drag_node(nominal)
                acceleration.append(wrapper)
        for nominal in tree.findall(".//parametrizationAcceleration/logDensity/nominalDrag"):
            nominal.clear()
            drag_node(nominal)
        for noise in tree.findall(".//receiver/lowEarthOrbiter/inputfileAccuracyDefinition"):
            noise.text = accuracy
        for gradient in tree.findall(".//gradientfield/potentialCoefficients/maxDegree"):
            gradient.text = "2"
        _save(tree, path)
    result["force_model_hash"] = canonical_hash(native_recipe)
    result["measurement_model_hash"] = canonical_hash({"common_native_corrections":
        result.get("measurement_model_hash"), "synthetic_noise": NOISE_MODEL,
        "accuracy_definition_sha256": sha256_file(accuracy)})
    result.setdefault("estimation_inputs", []).append(artifact(accuracy, "force_auxiliary", kind="synthetic_gnss_accuracy"))
    result.setdefault("metadata", {})["synthetic_noise"] = {**NOISE_MODEL,
        "accuracy_definition_sha256": sha256_file(accuracy)}
    result.setdefault("metadata", {})["synthetic_force_recipe"] = native_recipe
    result["metadata"]["variational_gradient_gate_required"] = True
    write_json(Path(result["output_dir"])/"preparation_manifest.json", result)
    return result


def mixed_force_specification(seed):
    """Frozen secondary stress: small unmodeled radial and cross-track forces."""
    phases = np.random.default_rng(np.random.SeedSequence([int(seed), 8819])).uniform(0., 2*np.pi, 2)
    return {"radial_amplitude_m_s2": 2e-8, "normal_amplitude_m_s2": 2e-8,
            "radial_period_seconds": 7200., "normal_period_seconds": 5400.,
            "radial_phase": float(phases[0]), "normal_phase": float(phases[1]), "seed": int(seed)}


def cached_transmitter_conversion(case, instruments, products, generation_dir, backend):
    """Reuse deterministic daily transmitter conversion across masks and seeds."""
    auxiliary = Path(backend["auxiliary_dir"]).resolve()
    auxiliary_hashes = {}
    for name in ("auxiliary_manifest.json", "flight_auxiliary_manifest.json"):
        manifest_path = auxiliary/name
        if not manifest_path.is_file():
            raise FileNotFoundError("Verified common auxiliary manifests are required: " + str(manifest_path))
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["sources"]:
            if sha256_file(entry["path"]) != entry["sha256"]:
                raise ValueError("Common auxiliary input changed: " + entry["path"])
        auxiliary_hashes[name] = sha256_file(manifest_path)
    identity = {"date": case["epoch"][:10], "products": sorted((p["role"], p["sha256"]) for p in products),
                "auxiliary_manifests": auxiliary_hashes,
                "executable_sha256": sha256_file(backend["groops_executable"]),
                "generator_sha256": sha256_file(__file__),
                "configuration_builder_sha256": sha256_file(Path(__file__).with_name("groops_config.py")),
                "template_sha256": sha256_file(Path(backend["example_directory"])/"01groopsConvert.xml")}
    cache = Path(backend["cache_dir"]).resolve()/"native-transmitters"/canonical_hash(identity)
    cache.mkdir(parents=True, exist_ok=True)
    record_path = cache/"conversion.json"
    with (cache/".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if record_path.exists():
            record = json.loads(record_path.read_text())
            for entry in record["artifacts"]:
                if sha256_file(entry["path"]) != entry["sha256"]:
                    raise ValueError("Cached transmitter product changed: " + entry["path"])
        else:
            configs = simulation_configs(case, instruments, products, cache, backend)
            execution = _execute(backend["groops_executable"], configs["convert_gnss"], cache, case["seed"])
            outputs = sorted((cache/"data"/identity["date"]).rglob("*"))
            artifacts = [artifact(path, "native_transmitter_product") for path in outputs if path.is_file()]
            if not artifacts:
                raise RuntimeError("Native transmitter conversion produced no artifacts")
            record = {"identity": identity, "execution": execution, "artifacts": artifacts}
            write_json(record_path, record)
        source = cache/"data"/identity["date"]
        target = Path(generation_dir)/"data"/identity["date"]
        target.mkdir(parents=True, exist_ok=True)
        for directory in source.iterdir():
            destination = target/directory.name
            if destination.exists() and (not destination.is_symlink() or destination.resolve() != directory.resolve()):
                raise ValueError("Conflicting native transmitter directory: " + str(destination))
            if not destination.exists():
                destination.symlink_to(directory, target_is_directory=True)
    return {"shared_cache": str(record_path), "identity": identity, "converted_products": len(record["artifacts"])}
