"""Close a shared nominal-force orbit before fitting stochastic force parameters.

The retained-code bootstrap determines one initial six-state estimate. Repeated
force evaluation then removes dependence on the artificial gap-filled curve.
This changes only an initialization; it contributes no observations or prior.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import numpy as np


def _standalone(source, programs, date):
    """Retain native loop globals, including a separate exact UTC offset."""
    global_node = source.find("global")
    if global_node is None or any(global_node.find(f"time[@label='{key}']") is None
                                  for key in ("timeStart", "timeEnd")):
        raise ValueError("Nominal initialization requires the source time globals")
    root = ET.Element("groops")
    root.append(deepcopy(global_node))
    for program in programs:
        program = deepcopy(program)
        for node in program.iter():
            if node.text:
                node.text = node.text.replace("{loopTime:%D}", date).replace(
                    "loopTimeEnd", "timeEnd").replace("loopTime", "timeStart")
        ET.SubElement(root, "program").append(program)
    return root


def _field(node, name, value):
    item = node.find(name)
    if item is None:
        item = ET.SubElement(node, name)
    item.text = str(value)


def _evaluation(variational, orbit, ephemerides, initial=None):
    node = ET.Element("OrbitPocEvaluateVariational")
    for name, value in (("inputfileVariational", variational), ("outputfileOrbit", orbit)):
        _field(node, name, value)
    if initial is not None:
        _field(node, "inputfileInitialState", initial)
    node.append(deepcopy(ephemerides))
    conversion = ET.Element("FileConvert")
    _field(conversion, "inputfile", orbit)
    _field(conversion, "outputfile", orbit.with_suffix(".txt"))
    return [node, conversion]


def close_nominal_reference(configured, binary, output_dir, *, maximum_iterations=10,
                            position_tolerance_m=2e-6, velocity_tolerance_m_s=3e-9,
                            timeout=7200.):
    """Replace only ``native_paths.orbit`` after fixed-initial-state closure.

    Call once per common preparation, before hashing its native artifacts. The
    receiver geometry remains the original immutable GNSS bootstrap. A failed
    closure leaves the dynamic orbit untouched and writes an explicit record.
    """
    # Lazy imports avoid a cycle when backend.prepare_job invokes this helper.
    from . import backend
    from .protocol import artifact_record, file_hash, write_json

    if (isinstance(maximum_iterations, bool) or int(maximum_iterations) != maximum_iterations
            or maximum_iterations < 1):
        raise ValueError("Nominal closure needs a positive whole iteration limit")
    if any(not np.isfinite(value) or value <= 0 for value in
           (position_tolerance_m, velocity_tolerance_m_s, timeout)):
        raise ValueError("Nominal closure tolerances and timeout must be finite and positive")
    root = Path(output_dir).resolve()
    if root.exists() and any(root.iterdir()):
        raise ValueError("Use a fresh nominal initialization directory")
    orbit = Path(configured["native_paths"]["orbit"])
    if orbit.is_symlink():
        raise ValueError("The mutable dynamic orbit must not be a shared symlink")
    immutable = {key: Path(configured["native_paths"][key]).resolve() for key in
                 ("receiver", "receiver_orbit", "receiver_attitude", "attitude", "attitude_integration")
                 if key in configured["native_paths"]}
    if configured.get("preprocessing_orbit_path"):
        immutable["preprocessing_orbit"] = Path(configured["preprocessing_orbit_path"]).resolve()
    if any(path == orbit.resolve() for path in immutable.values()):
        raise ValueError("Dynamic and immutable receiver geometry must be separate files")
    immutable_hashes = {key: file_hash(path) for key, path in immutable.items()}
    source_path = Path(configured["configs"]["variational"])
    source = ET.parse(source_path).getroot()
    propagation = deepcopy(source.find(".//PreprocessingVariationalEquation"))
    initializer = deepcopy(source.find(".//PreprocessingVariationalEquationOrbitFit"))
    if propagation is None or initializer is None:
        raise ValueError("Nominal initialization needs native propagation and a six-state initializer")
    if propagation.find("forces/miscAccelerations/logDensity") is not None:
        raise ValueError("Shared nominal preparation must precede the fitted density force wrapper")
    if any(initializer.find(name) is not None for name in
           ("parametrizationAcceleration", "stochasticPulse")):
        raise ValueError("Shared nominal initializer must estimate only six Cartesian state components")
    ephemerides = propagation.find("ephemerides")
    if ephemerides is None:
        raise ValueError("The native ephemerides configuration is required")
    root.mkdir(parents=True, exist_ok=True)
    identity = file_hash(binary)
    before = file_hash(orbit)
    bootstrap_snapshot = root / "input_bootstrap.dat"
    shutil.copy2(orbit, bootstrap_snapshot)
    if file_hash(bootstrap_snapshot) != before:
        raise ValueError("Bootstrap changed while copying the nominal initialization input")
    record = {"status": "running", "scope": "Shared fixed-initial-state nominal-force initialization; no stochastic parameters, observations or prior added",
              "native_binary_sha256": identity, "helper_sha256": file_hash(__file__),
              "source_configuration": artifact_record("nominal_configuration", source_path),
              "bootstrap_snapshot": artifact_record("initial_bootstrap", bootstrap_snapshot),
              "initial_bootstrap_orbit_sha256": before, "immutable_input_sha256": immutable_hashes,
              "physical_force_hash": configured.get("force_model_hash"), "arc": configured.get("arc"),
              "maximum_iterations": int(maximum_iterations), "position_tolerance_m": position_tolerance_m,
              "velocity_tolerance_m_s": velocity_tolerance_m_s, "iterations": [], "executions": [],
              "fixed_initial_state_scope": "Fixed only for this numerical closure; the final GNSS fit re-estimates all six initial-state components",
              "thermal_maximum_step_seconds": (float(propagation.findtext("forces/miscAccelerations/radiationPressure/orbitPocThermalMaximumStep", "1"))
                  if propagation.find("forces/miscAccelerations/radiationPressure") is not None else None),
              "atmospheric_quadrature_step_seconds": propagation.findtext("orbitPocAtmosphericQuadratureStep")}
    record_path = root / "initialization.json"
    write_json(record_path, record)

    def execute(tree, folder, label):
        folder.mkdir(parents=True, exist_ok=True)
        path = backend._save_xml(tree, folder / f"{label}.xml")
        execution = backend.run_native(binary, path, folder, label, timeout=timeout)
        record["executions"].append(execution)

    try:
        initial_dir = root / "initial"
        initial_var = initial_dir / "variational.dat"
        _field(propagation, "inputfileOrbit", bootstrap_snapshot)
        _field(propagation, "outputfileVariational", initial_var)
        for name, value in (("inputfileOrbit", bootstrap_snapshot), ("inputfileVariational", initial_var),
                            ("outputfileVariational", initial_var)):
            _field(initializer, name, value)
        # Optional outputs inherited from a template must never write elsewhere.
        for name in ("outputfileOrbit", "outputfileSolution"):
            for node in list(initializer.findall(name)):
                initializer.remove(node)
        reference = initial_dir / "nominal.dat"
        tree = _standalone(source, [propagation, initializer, *_evaluation(
            initial_var, reference, ephemerides)], configured["date"])
        execute(tree, initial_dir, "initialize")
        epochs, previous = backend._orbit(reference.with_suffix(".txt"))
        target = previous[0].copy()
        record["fixed_initial_state_si"] = target.tolist()
        record["state_epochs"] = len(epochs)
        initial_path = root / "initial_state.txt"
        initial_path.write_text("groops matrix version=20200123\nMatrix( 6 x 1 )\n"+
                               "\n".join(format(value, ".17g") for value in target)+"\n")
        closed = False
        for iteration in range(1, int(maximum_iterations)+1):
            folder = root / f"iteration-{iteration:02d}"
            node = deepcopy(propagation)
            _field(node, "inputfileOrbit", reference)
            _field(node, "outputfileVariational", folder / "variational.dat")
            current = folder / "nominal.dat"
            tree = _standalone(source, [node, *_evaluation(folder / "variational.dat", current,
                ephemerides, initial_path)], configured["date"])
            execute(tree, folder, "propagate")
            current_epochs, states = backend._orbit(current.with_suffix(".txt"))
            if epochs.shape != current_epochs.shape or not np.array_equal(epochs, current_epochs):
                raise ValueError("Native orbit epochs changed during nominal closure")
            delta = states-previous
            position_change = float(np.max(np.linalg.norm(delta[:, :3], axis=1)))
            velocity_change = float(np.max(np.linalg.norm(delta[:, 3:], axis=1)))
            closed = position_change < position_tolerance_m and velocity_change < velocity_tolerance_m_s
            record["iterations"].append({"iteration": iteration, "maximum_position_change_m": position_change,
                                         "maximum_velocity_change_m_s": velocity_change, "closed": closed})
            write_json(record_path, record)
            if closed:
                break
            previous, reference = states, current
        if not closed:
            raise RuntimeError("Nominal-force trajectory failed to close within the iteration limit")
        if file_hash(binary) != identity or file_hash(orbit) != before:
            raise ValueError("Native executable or bootstrap orbit changed during nominal closure")
        if {key: file_hash(path) for key, path in immutable.items()} != immutable_hashes:
            raise ValueError("Immutable receiver or attitude inputs changed during nominal closure")
        replacement = orbit.with_name(orbit.name + ".nominal-closure")
        if replacement.exists():
            raise ValueError("Refusing to overwrite an existing nominal-closure temporary file")
        shutil.copy2(current, replacement)
        replacement.replace(orbit)
        record.update(status="complete", converged=True, output_orbit_sha256=file_hash(orbit),
                      source_closed_orbit=artifact_record("closed_nominal_orbit", current),
                      immutable_inputs_unchanged=True)
        write_json(record_path, record)
        return record
    except Exception as error:
        execution = getattr(error, "execution", None)
        if execution is not None and execution not in record["executions"]:
            record["executions"].append(execution)
        record.update(status="failed", converged=False, error=f"{type(error).__name__}: {error}")
        write_json(record_path, record)
        raise
