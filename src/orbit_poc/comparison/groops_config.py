"""Native GROOPS flight processing, derived from its published LEO example.

All orbit initialization is recomputed from retained GNSS code.  Reference and
SLR files never enter the XML generation interface.  Density runs require the
project's native logDensity extension and an outer relinearization loop.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from .data import (GROOPS_DATA, artifact, canonical_hash, code_bootstrap,
                   fetch_url, normalize_mask, reuse_auxiliary_manifest, sha256_file, split_gps1b,
                   verify_manifest, write_json, screen_flight_inputs)

TEMPLATES = Path(__file__).resolve().parents[3] / "groops" / "templates"


def _add(parent, tag, text=None, **attributes):
    element = ET.SubElement(parent, tag, attributes)
    if text is not None:
        element.text = str(text)
    return element


def _program(root, name):
    return _add(_add(root, "program"), name)


def _save(root, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return str(path.resolve())


def _rotation(parent, auxiliary):
    file = _add(_add(parent, "earthRotation"), "file")
    _add(file, "inputfileEOP", auxiliary / "earthRotation/timeSeries_EOP_rapid_IAU2000_desai.dat")
    _add(file, "interpolationDegree", 3)


def _template(name, scenario, root, auxiliary, date, mjd):
    source = Path(scenario) / name if scenario else TEMPLATES / name
    tree = ET.parse(source).getroot()
    for parent in tree.iter():
        for child in list(parent):
            if child.attrib.get("disabled") == "1":
                parent.remove(child)
    for node in tree.iter():
        label = node.attrib.get("label")
        if label == "timeStart": node.text = str(mjd)
        if label == "timeEnd": node.text = "timeStart+1"
        if label == "groopsDataDir": node.text = str(auxiliary)
        if label == "tmpDir": node.text = str(root / "tmp")
        if node.text:
            node.text = node.text.replace("{groopsDataDir}", str(auxiliary))
            if node.text.startswith(("data/", "output/")):
                node.text = str(root / node.text)
    return tree


def fetch_flight_auxiliary(auxiliary_dir, *, download=True):
    """Add IGS20 transmitter metadata for CODE's 2024 reference convention."""
    root = Path(auxiliary_dir).resolve()
    if (root/"flight_auxiliary_manifest.json").exists():
        return reuse_auxiliary_manifest(root,"flight_auxiliary_manifest.json")
    paths = ["gnss/transmitter/antennaDefinition/igs/igs20/antennaDefinition_igs20.dat"]
    paths += [f"gnss/transmitter/transmitterInfo/igs/igs20/transmitterInfo_igs20.G{i:02d}.xml"
              for i in range(1, 33)]
    sources = [fetch_url(GROOPS_DATA + p, root / p, download=download) for p in paths]
    manifest = {"status": "complete", "sources": sources,
                "total_bytes": sum(x["bytes"] for x in sources)}
    write_json(root / "flight_auxiliary_manifest.json", manifest)
    return manifest


def _select(manifest, role, suffix=None):
    matches = [x for x in manifest["estimation_inputs"] if x["role"] == role
               and (suffix is None or x["path"].endswith(suffix))]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {role} input ({suffix}): {len(matches)}")
    return matches[0]["path"]


def _exact_mjd(mjd, offset_seconds):
    """Emit decimal GPS MJD without first rounding its fractional day to float64."""
    from decimal import Decimal
    return format(Decimal(str(mjd))+Decimal(str(offset_seconds))/Decimal(86400), '.18f')


def _extra_exports(processing, root, date):
    receiver=processing.find("receiver/lowEarthOrbiter")
    flag=receiver.find("orbitPocPreprocessFromInputOrbit")
    for old in list(receiver.findall("outputfileOrbitPocPreprocessingAudit")):receiver.remove(old)
    if flag is not None and flag.text=="1":
        _add(receiver,"outputfileOrbitPocPreprocessingAudit",root/"output"/date/"preprocessing_audit.txt")
    dynamic=processing.find("parametrization/leoDynamicOrbits")
    node=dynamic.find("outputfileOrbitNative")
    if node is None: node=_add(dynamic,"outputfileOrbitNative")
    node.text=str(root/"output"/date/f"gracefo1_orbit_{date}.dat")
    node=dynamic.find("outputfileParameterCovariance")
    if node is None: node=_add(dynamic,"outputfileParameterCovariance")
    node.text=str(root/"output"/date/"parameter_covariance.txt")
    node=dynamic.find("outputfileCovarianceObservationEpochs")
    if node is None: node=_add(dynamic,"outputfileCovarianceObservationEpochs")
    node.text=str(root/"output"/date/"state_covariance_observations.txt")
    for step in list(processing.findall("processingStep")):
        if step.find("writeAprioriSolution") is not None: processing.remove(step)
    # GROOPS consumes an XML category by cycling unmatched siblings to the end.
    # Keep every parametrization before every ordered processingStep, otherwise
    # a late-added prior rotates the output step ahead of the estimators.
    steps = list(processing.findall("processingStep"))
    for step in steps: processing.remove(step)
    for step in steps: processing.append(step)
    for residual in processing.findall("processingStep/writeResiduals"):
        export=residual.find("outputfilePhaseRecovery")
        if export is None: export=_add(residual,"outputfilePhaseRecovery")
        export.text=str(root/"output"/date/"phase_recovery.txt")
    solution=_add(_add(processing,"processingStep"),"writeAprioriSolution")
    _add(solution,"outputfileAprioriSolution",root/"output"/date/"full_apriori_solution.txt")
    _add(solution,"outputfileParameterNames",root/"output"/date/"full_parameter_names.txt")


def _arc_offset(tree):
    node=tree.find("global/double[@label='arcStartOffsetSeconds']")
    return float(node.text) if node is not None else 0.


def _resample_at_receiver_epochs(tree, source, destination, receiver):
    """Interpolate a smooth geometry input at exact native observation times."""
    p = _program(tree, "InstrumentResample")
    _add(p, "inputfileInstrument", source)
    _add(p, "outputfileInstrument", destination)
    polynomial = _add(_add(p, "method"), "polynomial")
    for tag, value in (("polynomialDegree", 7), ("maxDataPointRange", -8.1),
                       ("maxExtrapolationDistance", -1.1)):
        _add(polynomial, tag, value)
    _add(_add(_add(p, "timeSeries"), "instrument"), "inputfileInstrument", receiver)


def _pulse_grid(parent,spacing,offset):
    for old in list(parent.findall("stochasticPulse")):parent.remove(old)
    grid=_add(_add(parent,"stochasticPulse"),"uniformSampling")
    _add(grid,"timeStart","loopTime")
    # Guard the final point without constructing a fractional absolute start.
    _add(grid,"timeEnd",f"loopTimeEnd-{1.5*spacing}/86400")
    _add(grid,"sampling",f"{spacing:g}/86400")
    _add(grid,"offsetSeconds",format(offset+spacing,'.17g'))


def _flight_event_fields(three,four):
    """Keep the native one-sided atmospheric quadrature recipe synchronized."""
    p=three.find(".//PreprocessingVariationalEquation")
    for tag in ("orbitPocAtmosphericForce","orbitPocAtmosphericHasDensityKnots","orbitPocAtmosphericQuadratureStep"):
        for old in list(p.findall(tag)):p.remove(old)
    for parent in four.iter():
        for tag in ("orbitPocAtmosphereEvents","orbitPocAtmosphericQuadratureStep"):
            for old in list(parent.findall(tag)):parent.remove(old)
    forces=p.find("forces")
    atmospheric=None
    for wrapper in forces.findall("miscAccelerations"):
        if wrapper.find("atmosphericDrag") is not None or wrapper.find("logDensity/nominalDrag/atmosphericDrag") is not None:
            atmospheric=list(wrapper)[0];break
    if atmospheric is not None:
        _add(p,"orbitPocAtmosphericForce").append(deepcopy(atmospheric))
        _add(p,"orbitPocAtmosphericQuadratureStep",1)
        if atmospheric.tag=="logDensity":_add(p,"orbitPocAtmosphericHasDensityKnots",1)
        for density in four.findall(".//parametrizationAcceleration/logDensity"):
            if density.find("nominalDrag/atmosphericDrag") is not None:
                _add(density,"orbitPocAtmosphereEvents",1)
                _add(density,"orbitPocAtmosphericQuadratureStep",1)


def _flight_thermal_step(three):
    """Explicit campaign setting validated independently at 0.1 versus 0.05s.

    Keep the stock template/native default untouched. Apply before hashing the
    shared force recipe, and preserve it when cloning either flight estimator.
    """
    forces = three.find(".//PreprocessingVariationalEquation/forces")
    if forces.find("miscAccelerations/atmosphericDrag") is None and forces.find("miscAccelerations/logDensity/nominalDrag/atmosphericDrag") is None:
        return
    for radiation in forces.findall("miscAccelerations/radiationPressure"):
        node = radiation.find("orbitPocThermalMaximumStep")
        if node is None: node = _add(radiation, "orbitPocThermalMaximumStep")
        node.text = "0.1"


def _official_ar_steps(three, four):
    """Separate stock20min unregularized/AR reference, not the primary float arm."""
    processing=four.find(".//GnssProcessing")
    for param in list(processing.findall("parametrization")):
        if param.find("constraints/name") is not None and param.find("constraints/name").text=="constraint.pulses":
            processing.remove(param)
    dynamic=processing.find("parametrization/leoDynamicOrbits")
    initializer=three.find(".//PreprocessingVariationalEquationOrbitFit")
    for parent in (dynamic,initializer):
        _pulse_grid(parent,1200.,_arc_offset(three))
    receiver=processing.find("receiver/lowEarthOrbiter")
    receiver.find("supportsIntegerAmbiguities").text="1"
    for tag in ("orbitPocPreprocessFromInputOrbit","outputfileOrbitPocPreprocessingAudit"):
        for old in list(receiver.findall(tag)):receiver.remove(old)
    old=[s for s in processing.findall("processingStep") if s.find("estimate") is not None or s.find("resolveAmbiguities") is not None]
    index=list(processing).index(old[0])
    for step in old: processing.remove(step)
    stock=ET.parse(TEMPLATES/"04groopsGnssProcessing.xml").getroot().find(".//GnssProcessing")
    steps=[s for s in stock.findall("processingStep") if s.find("estimate") is not None or s.find("resolveAmbiguities") is not None]
    for offset,step in enumerate(steps): processing.insert(index+offset,deepcopy(step))


def build_day_configs(data_manifest: dict, scenario_dir: str | Path | None,
                      auxiliary_dir: str | Path, output_dir: str | Path, *,
                      method="groops_pulses", mask=None,
                      pulse_interval_seconds=1200., pulse_sigma_velocity_m_s=1e-4,
                      density_knot_seconds=60., density_tau_seconds=7200.,
                      density_sigma_log=0.3, inputfile_log_density=None,
                      integration_step_seconds=5., duration_hours=24.) -> dict:
    """Prepare native configs; a successful return is not a successful fit.

    Pulse coefficients and their native Gaussian prior use micrometres/second,
    while the public argument is metres/second.  Pulse axes are inertial CRF.
    Shared native preprocessing is based on the same GNSS-only bootstrap; model
    fitting uses fixed nominal measurement sigmas, without residual reweighting.
    """
    verify_manifest(data_manifest)
    if method not in ("groops_pulses", "groops_log_drag_ou", "groops_pulses_ar"):
        raise ValueError("unknown comparison method")
    if not all(math.isfinite(x) and x > 0 for x in
               (pulse_interval_seconds, pulse_sigma_velocity_m_s, density_knot_seconds,
                density_tau_seconds, density_sigma_log)):
        raise ValueError("model intervals and standard deviations must be finite and positive")
    duration_seconds = float(duration_hours)*3600
    if not 0 < duration_seconds <= 86400 or duration_seconds % density_knot_seconds or duration_seconds % pulse_interval_seconds:
        raise ValueError("knot and pulse spacing must divide the daily arc")
    root, auxiliary = Path(output_dir).resolve(), Path(auxiliary_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if data_manifest.get("mission") == "GRACE-FO-1":
        screening = screen_flight_inputs(data_manifest, root / "flight_screening.json")
        if screening["status"] != "eligible":
            raise ValueError("fixed flight day excluded by metadata screening: " + ", ".join(screening["exclusion_reasons"]))
    date = data_manifest["date"]
    mjd = (datetime.fromisoformat(date)-datetime(1858, 11, 17)).days
    arc = data_manifest.get("arc",{})
    arc_offset=float(arc.get("gps_start_offset_seconds",0.))
    include_endpoint=arc.get("time_scale")=="UTC"
    if not math.isfinite(integration_step_seconds) or integration_step_seconds<=0:
        raise ValueError("integration step must be finite and positive")
    if include_endpoint and (integration_step_seconds>5 or abs(5/integration_step_seconds-round(5/integration_step_seconds))>1e-12):
        raise ValueError("flight integration grid must subdivide the canonical5s attitude grid")
    if data_manifest.get("mission")=="GRACE-FO-1" and (arc.get("time_scale")!="UTC" or arc_offset!=18):
        raise ValueError("flight inputs must be assembled as a verified UTC day")
    mask = normalize_mask(mask)
    masked = split_gps1b(_select(data_manifest, "gnss_observations", ".txt"), date,
                         root / "preprocessing", mask,arc_start_offset_seconds=arc_offset,duration_hours=duration_hours)
    bootstrap = code_bootstrap(masked["retained"]["path"], _select(data_manifest, "gnss_orbits"),
                               _select(data_manifest, "gnss_clocks"), date,
                               root / "preprocessing/bootstrap_trf.txt", mask=mask,
                               integration_step_seconds=integration_step_seconds, duration_hours=duration_hours,
                               arc_start_offset_seconds=arc_offset,include_endpoint=include_endpoint)
    # All auxiliary models are verified before constructing any runnable config.
    auxiliary_records = []
    for name in ("auxiliary_manifest.json", "flight_auxiliary_manifest.json"):
        manifest = reuse_auxiliary_manifest(auxiliary, name)
        auxiliary_records.extend(manifest["sources"])
    d = root / "data" / date / "gracefo"
    d.mkdir(parents=True, exist_ok=True)
    paths = {"receiver": d/f"gracefo1_gnssReceiver_{date}.dat",
             "orbit": d/f"gracefo1_orbit_{date}.dat",
             "attitude": d/f"gracefo1_starCamera_{date}.dat",
             "receiver_orbit": d/f"gracefo1_receiverOrbit_{date}.dat",
             "receiver_attitude": d/f"gracefo1_receiverStarCamera_{date}.dat",
             "variational": d/f"gracefo1_variational_{date}.dat"}
    if include_endpoint and integration_step_seconds!=5:
        paths["attitude_integration"]=d/f"gracefo1_starCamera_integration_{date}.dat"
    one = _template("01groopsConvert.xml", scenario_dir, root, auxiliary, date, mjd)
    replacements = {"Sp3Format2Orbit": ("inputfile", "gnss_orbits"),
                    "GnssOrbex2StarCamera": ("inputfileOrbex", "gnss_attitudes"),
                    "GnssClockRinex2InstrumentClock": ("inputfileClockRinex", "gnss_clocks"),
                    "GnssSinexBias2SignalBias": ("inputfileSinexBias", "gnss_biases")}
    for tag, (field, role) in replacements.items():
        for program in one.iter(tag):
            program.find(field).text = _select(data_manifest, role)
            # The pinned GROOPS version removed this unused legacy option.
            for obsolete in list(program.findall("inputfileGlonassSignalDefinition")):
                program.remove(obsolete)
    two = ET.Element("groops")
    p = _program(two, "GraceL1b2GnssReceiver")
    _add(p, "outputfileGnssReceiver", paths["receiver"])
    _add(p, "inputfile", masked["retained"]["path"])
    p = _program(two, "GroopsAscii2Orbit")
    _add(p, "outputfileOrbit", paths["orbit"])
    _rotation(p, auxiliary)
    _add(p, "inputfile", bootstrap["path"])
    # Decimal MJD bootstrap import passes through binary64. Canonicalize times
    # natively before differentiation/integration to avoid sub-microsecond jitter.
    p = _program(two, "InstrumentResample")
    _add(p, "outputfileInstrument", paths["orbit"])
    _add(p, "inputfileInstrument", paths["orbit"])
    interpolation = _add(_add(p, "method"), "polynomial")
    for tag,value in (("polynomialDegree",7),("maxDataPointRange",300),("maxExtrapolationDistance",1)):
        _add(interpolation,tag,value)
    grid = _add(_add(p,"timeSeries"),"uniformSampling")
    _add(grid,"timeStart",mjd)
    endpoint_operator='+' if include_endpoint else '-'
    _add(grid,"timeEnd",f"{mjd}+({duration_hours*3600}{endpoint_operator}{0.5*integration_step_seconds})/86400")
    _add(grid,"sampling",f"{integration_step_seconds}/86400")
    if arc_offset:_add(grid,"offsetSeconds",format(arc_offset,'.17g'))
    p = _program(two, "OrbitAddVelocityAndAcceleration")
    _add(p, "outputfileOrbit", paths["orbit"])
    _add(p, "inputfileOrbit", paths["orbit"])
    _add(p, "polynomialDegree", 7)
    attitude_entry = next(x for x in data_manifest["estimation_inputs"] if x["role"] == "attitude")
    if attitude_entry.get("format", attitude_entry.get("metadata", {}).get("format")) == "groops_instrument":
        p = _program(two, "FileConvert")
        _add(p, "outputfile", paths["attitude"])
        _add(p, "inputfile", attitude_entry["path"])
    else:
        p = _program(two, "GraceL1b2StarCamera")
        _add(p, "outputfileStarCamera", paths["attitude"])
        _add(p, "inputfile", _select(data_manifest, "attitude"))
    p = _program(two, "InstrumentResample")
    _add(p, "outputfileInstrument", paths["attitude"])
    _add(p, "inputfileInstrument", paths["attitude"])
    polynomial = _add(_add(p, "method"), "polynomial")
    for tag, value in (("polynomialDegree", 1), ("maxDataPointRange", 300),
                       ("maxExtrapolationDistance", 100)):
        _add(polynomial, tag, value)
    if include_endpoint:
        # The physical attitude curve is fixed at the canonical5s provider
        # samples, independently of dynamics refinement. GNSS/SLR use this file.
        grid=_add(_add(p,"timeSeries"),"uniformSampling")
        for tag,value in (("timeStart",mjd),("timeEnd",f"{mjd}+({duration_seconds}+2.5)/86400"),
                          ("sampling","5/86400"),("offsetSeconds",format(arc_offset,'.17g'))):_add(grid,tag,value)
        if "attitude_integration" in paths:
            p=_program(two,"InstrumentResample")
            _add(p,"inputfileInstrument",paths["attitude"])
            _add(p,"outputfileInstrument",paths["attitude_integration"])
            polynomial=_add(_add(p,"method"),"polynomial")
            for tag,value in (("polynomialDegree",7),("maxDataPointRange",-8.1),("maxExtrapolationDistance",-1.1)):_add(polynomial,tag,value)
            _add(_add(_add(p,"timeSeries"),"instrument"),"inputfileInstrument",paths["orbit"])
    else:
        _add(_add(_add(p, "timeSeries"), "instrument"), "inputfileInstrument", paths["orbit"])
    # The native LEO receiver matches input geometry within timeMargin=0.1s;
    # it does not interpolate the UTC18+5n dynamics grid onto GPS30n epochs.
    # Derive both inputs from the common bootstrap/canonical attitude, using
    # the converted retained observations as the exact epoch authority.
    _resample_at_receiver_epochs(two, paths["orbit"], paths["receiver_orbit"], paths["receiver"])
    _resample_at_receiver_epochs(two, paths["attitude"], paths["receiver_attitude"], paths["receiver"])
    three = _template("03groopsVariational.xml", scenario_dir, root, auxiliary, date, mjd)
    _flight_thermal_step(three)
    three.find(".//PreprocessingVariationalEquation/inputfileStarCamera").text=str(paths.get("attitude_integration",paths["attitude"]))
    boundaries = _add(_add(three.find(".//PreprocessingVariationalEquation"), "integrationBoundaries"),
                      "uniformSampling")
    _add(boundaries, "timeStart", "loopTime")
    _add(boundaries, "timeEnd", "loopTimeEnd")
    _add(boundaries, "sampling", f"{density_knot_seconds}/86400")
    if arc_offset:_add(boundaries,"offsetSeconds",format(arc_offset,'.17g'))
    # Pre-fit coefficients become unrecorded offsets in the reference trajectory.
    # Keep this initializer to six state components so final pulse priors are
    # centred on physically zero pulses, rather than zero additional increments.
    initializer = three.find(".//PreprocessingVariationalEquationOrbitFit")
    for pulse in list(initializer.findall("stochasticPulse")):
        initializer.remove(pulse)
    four = _template("04groopsGnssProcessing.xml", scenario_dir, root, auxiliary, date, mjd)
    processing = four.find(".//GnssProcessing")
    series = processing.find("timeSeries")
    series.clear()
    uniform = _add(series, "uniformSampling")
    _add(uniform, "timeStart", "loopTime")
    observation_offset=math.ceil(arc_offset/mask['cadence_seconds'])*mask['cadence_seconds']
    end_guard=observation_offset-arc_offset+0.5*mask['cadence_seconds']
    _add(uniform, "timeEnd", f"loopTimeEnd-{end_guard}/86400")
    _add(uniform, "sampling", f"{mask['cadence_seconds']}/86400")
    if observation_offset:_add(uniform,"offsetSeconds",format(observation_offset,'.17g'))
    receiver = processing.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileOrbit").text = str(paths["receiver_orbit"])
    receiver.find("inputfileStarCamera").text = str(paths["receiver_attitude"])
    _add(four.find("global"), "filename", paths["attitude"], label="orbitPocCanonicalAttitude")
    for node in four.iter():
        if node.text: node.text = node.text.replace("igsR3", "igs20")
    for step in list(processing.findall("processingStep")):
        if step.find("resolveAmbiguities") is not None:
            processing.remove(step)
    processing.find("receiver/lowEarthOrbiter/supportsIntegerAmbiguities").text = "0"
    _add(processing.find("receiver/lowEarthOrbiter"),"orbitPocPreprocessFromInputOrbit",1)
    for node in processing.findall(".//estimate/computeWeights") + processing.findall(".//estimate/adjustSigma0"):
        node.text = "0"
    dynamic = processing.find("parametrization/leoDynamicOrbits")
    _add(dynamic, "outputfileParameters", root / "output" / date / "orbit_parameters.txt")
    _add(dynamic, "outputfileCovariance", root / "output" / date / "state_covariance.txt")
    _add(processing.find("parametrization/clocks"), "outputfileClockReceiver",
         root / "output" / date / "receiver_clock.txt")
    final_write = next(s for s in processing.findall("processingStep") if s.find("writeResults") is not None)
    index = list(processing).index(final_write)
    covariance_step = ET.Element("processingStep")
    _add(covariance_step, "computeCovarianceMatrix")
    processing.insert(index, covariance_step)
    residuals = _add(_add(processing, "processingStep"), "writeResiduals")
    _add(_add(residuals, "selectReceivers"), "all")
    _add(residuals, "outputfileResiduals", root / "output" / date / "gnss_residuals.dat")
    # Export the native common measurement recipe before attaching either prior.
    shared_measurement = deepcopy(processing)
    for param in list(shared_measurement.findall("parametrization")):
        if param.find("leoDynamicOrbits") is not None:
            shared_measurement.remove(param)
    for node in shared_measurement.iter():
        if node.text: node.text = node.text.replace(str(root), "{job}")
    base_forces = three.find(".//PreprocessingVariationalEquation/forces")
    nominal_drag = deepcopy(base_forces.find("miscAccelerations/atmosphericDrag"))
    shared_forces = ET.tostring(base_forces, encoding="unicode").replace(str(auxiliary), "{auxiliary}")
    if method in ("groops_pulses", "groops_pulses_ar"):
        for parent in (three, four):
            for pulse in parent.findall(".//stochasticPulse/uniformSampling"):
                pulse.find("timeStart").text = "loopTime"
                pulse.find("timeEnd").text = f"loopTimeEnd-{1.5*pulse_interval_seconds}/86400"
                pulse.find("sampling").text = f"{pulse_interval_seconds:g}/86400"
                _add(pulse,"offsetSeconds",format(arc_offset+pulse_interval_seconds,'.17g'))
        constraint = _add(_add(processing, "parametrization"), "constraints")
        _add(constraint, "name", "constraint.pulses")
        wildcard = _add(_add(constraint, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "stochasticPulse.*"),
                           ("temporal", "*"), ("interval", "*")):
            _add(wildcard, tag, value)
        _add(constraint, "sigma", pulse_sigma_velocity_m_s * 1e6)
        _add(constraint, "bias", 0)
        _add(constraint, "relativeToApriori", 0)
    else:
        # The nominal drag is the only force scaled by exp(g).
        log_density = Path(inputfile_log_density).resolve() if inputfile_log_density else root / "log_density.txt"
        if not log_density.exists():
            with log_density.open("w") as stream:
                for i in range(round(duration_seconds/density_knot_seconds)+1):
                    stream.write(f"{_exact_mjd(mjd, arc_offset+i*density_knot_seconds)} 0\n")
        for wrapper in base_forces.findall("miscAccelerations"):
            drag = wrapper.find("atmosphericDrag")
            if drag is not None:
                wrapper.remove(drag)
                density = _add(wrapper, "logDensity")
                _add(density, "nominalDrag").append(drag)
                _add(density, "inputfileLogDensity", log_density)
        for parent in (three, four):
            for element in parent.iter():
                for pulse in list(element.findall("stochasticPulse")):
                    element.remove(pulse)
        acceleration = _add(_add(dynamic, "parametrizationAcceleration"), "logDensity")
        _add(acceleration, "nominalDrag").append(nominal_drag)
        _add(acceleration, "inputfileLogDensity", log_density)
        ou = _add(_add(processing, "parametrization"), "logDensityOu")
        _add(ou, "name", "constraint.logDensityOu")
        selector = _add(_add(ou, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "logDensity"), ("temporal", "*"), ("interval", "*")):
            _add(selector, tag, value)
        _add(ou, "inputfileLogDensity", log_density)
        _add(ou, "tau", density_tau_seconds)
        _add(ou, "sigma", density_sigma_log)
    for tree in (one,three,four):
        _add(tree.find("global"),"double",arc_offset,label="arcStartOffsetSeconds")
    if method == "groops_pulses_ar":
        _official_ar_steps(three, four)
    _flight_event_fields(three,four)
    # Clock support must include bracketing native GPS epochs at both ends.
    for intervals in one.findall(".//GnssClockRinex2InstrumentClock/intervals"):
        intervals.clear(); grid=_add(intervals,"uniformSampling")
        _add(grid,"timeStart","timeStart");_add(grid,"timeEnd","timeStart+2");_add(grid,"sampling",2)
    for tree in (one, three, four):
        tree.find("global/time[@label='timeEnd']").text = f"timeStart+{duration_seconds}/86400"
        for interval in tree.findall(".//timeIntervals/timeIntervals/uniformSampling/sampling"):
            interval.text = f"{duration_seconds}/86400"
    _extra_exports(processing, root, date)
    config_paths = {}
    for label, tree in (("convert_gnss", one), ("convert_receiver", two),
                        ("variational", three), ("estimate", four)):
        config_paths[label] = _save(tree, root / f"{label}.xml")
        if "GNV1B" in Path(config_paths[label]).read_text():
            raise AssertionError("reference orbit leaked into estimation XML")
    estimation = [x for x in data_manifest["estimation_inputs"] if x["role"] != "gnss_observations"]
    estimation += [masked["retained"], bootstrap]
    for entry in auxiliary_records:
        role = "earth_orientation" if "/earthRotation/" in entry["path"] else "force_auxiliary"
        estimation.append({**entry, "role": role})
    preprocessing = {"mask": mask, "mask_hash": canonical_hash(mask), "bootstrap": bootstrap,
                     "receiver_conversion": "GraceL1b2GnssReceiver",
                     "observation_cadence_seconds": mask["cadence_seconds"],"arc":arc,
                     "observation_grid":"GPS-midnight multiples, restricted to UTC arc" if arc_offset else "elapsed/GPS grid",
                     "receiver_geometry_grid":"exact retained native GNSS observation epochs",
                     "receiver_attitude_interpolation":"degree7 normalized continuous-sign quaternion interpolation of canonical attitude",
                     "boundary_osb_policy":"known primary-day minus active-day bias added before masking; no track reset" if arc_offset else None,
                     "integration_step_seconds": integration_step_seconds,
                     "epoch_grid": "native uniform sampling after ASCII bootstrap import, before differentiation",
                     "bootstrap_provenance": "gnss_only", "reference_inputs_used": False,
                     "native_outlier_preprocessing": "same code bootstrap and receiver configuration for both models",
                     "estimation_reweighting": method=="groops_pulses_ar", "ambiguity_policy": "integer_native_reference" if method=="groops_pulses_ar" else "float",
                     "preprocessing_geometry":"native dynamic orbit" if method=="groops_pulses_ar" else "immutable masked GNSS-code bootstrap"}
    # Hashes describe common physical/measurement models, excluding the prior.
    common_aux = sorted((Path(x["path"]).relative_to(auxiliary).as_posix(), x["sha256"])
                        for x in auxiliary_records)
    result = {"schema_version": 1, "status": "configured", "method": method, "date": date,
              "output_dir": str(root), "duration_hours": duration_hours, "arc":arc, "configs": config_paths,
              "native_paths": {k: str(v) for k, v in paths.items()},
              "preprocessing_orbit_path":str(paths["receiver_orbit"]),
              "result_paths": {"orbit": str(root / "output" / date / f"gracefo1_orbit_{date}.txt"),
                               "orbit_native": str(root / "output" / date / f"gracefo1_orbit_{date}.dat"),
                               "parameters": str(root / "output" / date / "orbit_parameters.txt"),
                               "covariance": str(root / "output" / date / "state_covariance.txt"),
                               "covariance_observations": str(root / "output" / date / "state_covariance_observations.txt"),
                               "receiver_clock": str(root / "output" / date / "receiver_clock.txt"),
                               "residuals": str(root / "output" / date / "gnss_residuals.dat"),
                               "parameter_covariance": str(root / "output" / date / "parameter_covariance.txt"),
                               "apriori_solution": str(root / "output" / date / "full_apriori_solution.txt"),
                               "parameter_names": str(root / "output" / date / "full_parameter_names.txt"),
                               "phase_recovery": str(root / "output" / date / "phase_recovery.txt"),
                               "preprocessing_audit":str(root/"output"/date/"preprocessing_audit.txt")},
              "estimation_inputs": estimation, "evaluation_inputs": data_manifest["evaluation_inputs"],
              "calibration_inputs": [masked["heldout"]] if masked["heldout"]["records"] else [],
              "force_model_hash": canonical_hash([shared_forces, common_aux]),
              "measurement_model_hash": canonical_hash(ET.tostring(shared_measurement, encoding="unicode")),
              "preprocessing_hash": canonical_hash({"mask": mask,"arc":arc, "bootstrap_sha256": bootstrap["sha256"],
                                                      "retained_sha256": masked["retained"]["sha256"]}),
              "preprocessing": preprocessing, "mask_hash": canonical_hash(mask),
              "metadata": {"pulse_frame": "CRF", "pulse_parameter_unit": "um/s",
                           "pulse_sigma_velocity_m_s": pulse_sigma_velocity_m_s,
                           "pulse_sigma_native_um_s": pulse_sigma_velocity_m_s*1e6,
                           "density_outer_relinearization_required": method == "groops_log_drag_ou",
                           "density_knot_seconds": density_knot_seconds,
                           "integration_step_seconds": integration_step_seconds,
                           "attitude_numerical_model": "canonical5s provider samples with degree7 native interpolation; common to dynamics, GNSS and SLR" if include_endpoint else "synthetic prescribed attitude",
                           "native_execution_verified": False}}
    write_json(root / "preparation_manifest.json", result)
    return result


def run_native_preparation(manifest: dict, groops_executable: str | Path) -> dict:
    """Execute product/receiver conversion only; orbit fitting is backend-owned."""
    root = Path(manifest["output_dir"])
    execution = []
    for key in ("convert_gnss", "convert_receiver"):
        logfile = root / f"{key}.log"
        started = time.monotonic()
        with logfile.open("w") as stream:
            process = subprocess.run([str(Path(groops_executable).resolve()), manifest["configs"][key]],
                                     cwd=root, stdout=stream, stderr=subprocess.STDOUT, check=False)
        execution.append({"config": key, "returncode": process.returncode,
                          "elapsed_seconds": time.monotonic()-started, "log": str(logfile)})
        if process.returncode:
            raise RuntimeError(f"GROOPS {key} failed; see {logfile}")
    required = [manifest["native_paths"][x] for x in ("receiver", "orbit", "attitude", "attitude_integration", "receiver_orbit", "receiver_attitude") if x in manifest["native_paths"]]
    if any(not Path(p).is_file() or not Path(p).stat().st_size for p in required):
        raise RuntimeError("native conversion did not produce all required outputs")
    day = root / "data" / manifest["date"]
    transmitters = None
    for folder in ("orbit", "attitude", "clock", "signalBias"):
        present = {p.name.split(".")[-2] for p in (day/folder).glob("*.G??.*")
                   if p.stat().st_size > 0}
        transmitters = present if transmitters is None else transmitters & present
    if len(transmitters or ()) < 5:
        raise RuntimeError("native conversion has fewer than five complete GPS transmitter products")
    result = {**manifest, "status": "prepared", "native_execution": execution,
              "metadata": {**manifest["metadata"], "native_execution_verified": True,
                           "complete_transmitter_products": sorted(transmitters)}}
    write_json(root / "preparation_manifest.json", result)
    return result


def build_fit_configs(prepared_blind: dict, new_root: str | Path, method: str,
                      parameters: dict, inputfile_log_density=None) -> dict:
    """Clone prepared native recipes without ingestion, truth, or re-bootstrap.

    The caller populates private converted-data paths (immutable transmitter,
    receiver, attitude inputs; mutable copy of the orbit).  Synthetic nominal
    force substitutions already present in the prepared XML are preserved.
    """
    if method not in ("groops_pulses", "groops_log_drag_ou", "groops_pulses_ar"):
        raise ValueError("unknown comparison method")
    source_root = Path(prepared_blind["output_dir"]).resolve()
    root = Path(new_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    date = prepared_blind["date"]
    duration_hours = float(prepared_blind.get("duration_hours",24))
    duration_seconds = duration_hours*3600
    trees = {key: ET.parse(value).getroot() for key, value in prepared_blind["configs"].items()}
    for tree in trees.values():
        for node in tree.iter():
            if node.text:
                node.text = node.text.replace(str(source_root), str(root))
    three, four = trees["variational"], trees["estimate"]
    processing = four.find(".//GnssProcessing")
    dynamic = processing.find("parametrization/leoDynamicOrbits")
    immutable_bootstrap=prepared_blind.get("preprocessing_orbit_path",prepared_blind["native_paths"]["orbit"])
    receiver=processing.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileOrbit").text=str(Path(immutable_bootstrap).resolve())
    receiver.find("inputfileStarCamera").text = str(Path(prepared_blind["native_paths"].get(
        "receiver_attitude", prepared_blind["native_paths"]["attitude"])).resolve())
    flag=receiver.find("orbitPocPreprocessFromInputOrbit")
    if flag is None:flag=_add(receiver,"orbitPocPreprocessFromInputOrbit")
    flag.text="1"
    # Remove previous model-specific estimands and priors, not shared nuisance
    # parameters or force/correction settings.
    for name in ("stochasticPulse", "parametrizationAcceleration"):
        for element in list(dynamic.findall(name)):
            dynamic.remove(element)
    for parent in (three, four):
        for node in parent.iter():
            for pulse in list(node.findall("stochasticPulse")):
                node.remove(pulse)
    for param in list(processing.findall("parametrization")):
        if param.find("logDensityOu") is not None or param.find("constraints/name") is not None and param.find("constraints/name").text == "constraint.pulses":
            processing.remove(param)
    forces = three.find(".//PreprocessingVariationalEquation/forces")
    drag_wrapper = None
    for wrapper in forces.findall("miscAccelerations"):
        density = wrapper.find("logDensity")
        if density is not None:
            nominal = density.find("nominalDrag")
            children = list(nominal)
            if len(children) != 1:
                raise ValueError("expected one nominal drag acceleration choice")
            drag = deepcopy(children[0])
            wrapper.remove(density)
            wrapper.append(drag)
        if wrapper.find("atmosphericDrag") is not None or wrapper.find("syntheticDrag") is not None:
            drag_wrapper = wrapper
    if drag_wrapper is None:
        raise ValueError("prepared physics does not identify a nominal drag component")
    _flight_thermal_step(three)
    if method in ("groops_pulses", "groops_pulses_ar"):
        spacing = 1200. if method == "groops_pulses_ar" else float(parameters["interval_seconds"])
        sigma = float(parameters.get("sigma_velocity_m_s",1e-4))
        if not math.isfinite(spacing) or not math.isfinite(sigma) or min(spacing, sigma) <= 0:
            raise ValueError("invalid pulse parameters")
        _pulse_grid(dynamic,spacing,_arc_offset(three))
        constraint = _add(_add(processing, "parametrization"), "constraints")
        _add(constraint, "name", "constraint.pulses")
        selector = _add(_add(constraint, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "stochasticPulse.*"), ("temporal", "*"), ("interval", "*")):
            _add(selector, tag, value)
        _add(constraint, "sigma", sigma*1e6)
        _add(constraint, "bias", 0)
        _add(constraint, "relativeToApriori", 0)
    else:
        tau, sigma = float(parameters["tau_seconds"]), float(parameters["sigma_log_density"])
        spacing = float(parameters.get("knot_seconds", 60))
        if not all(math.isfinite(v) and v > 0 for v in (tau, sigma, spacing)):
            raise ValueError("invalid OU parameters")
        density_path = Path(inputfile_log_density).resolve() if inputfile_log_density else root / "log_density.txt"
        if not density_path.exists():
            mjd = (datetime.fromisoformat(date)-datetime(1858, 11, 17)).days
            with density_path.open("w") as stream:
                for i in range(round(duration_seconds/spacing)+1):
                    stream.write(f"{_exact_mjd(mjd, _arc_offset(three)+i*spacing)} 0\n")
        drag = next(x for x in drag_wrapper if x.tag in ("atmosphericDrag", "syntheticDrag"))
        drag_wrapper.remove(drag)
        wrapper = _add(drag_wrapper, "logDensity")
        _add(wrapper, "nominalDrag").append(deepcopy(drag))
        _add(wrapper, "inputfileLogDensity", density_path)
        acceleration = _add(_add(dynamic, "parametrizationAcceleration"), "logDensity")
        _add(acceleration, "nominalDrag").append(deepcopy(drag))
        _add(acceleration, "inputfileLogDensity", density_path)
        prior = _add(_add(processing, "parametrization"), "logDensityOu")
        _add(prior, "name", "constraint.logDensityOu")
        selector = _add(_add(prior, "parameters"), "wildcard")
        for tag, value in (("object", "*"), ("type", "logDensity"), ("temporal", "*"), ("interval", "*")):
            _add(selector, tag, value)
        _add(prior, "inputfileLogDensity", density_path)
        _add(prior, "tau", tau)
        _add(prior, "sigma", sigma)
    if method == "groops_pulses_ar":
        _official_ar_steps(three, four)
    else:
        for step in list(processing.findall("processingStep")):
            if step.find("resolveAmbiguities") is not None: processing.remove(step)
        processing.find("receiver/lowEarthOrbiter/supportsIntegerAmbiguities").text = "0"
        for node in processing.findall(".//estimate/computeWeights") + processing.findall(".//estimate/adjustSigma0"): node.text = "0"
    _flight_event_fields(three,four)
    _extra_exports(processing, root, date)
    paths = {key: _save(tree, root / f"{key}.xml") for key, tree in trees.items()}
    result = {"date": date, "duration_hours": duration_hours, "arc":prepared_blind.get("arc",{}),
              "preprocessing_orbit_path":str(Path(immutable_bootstrap).resolve()), "method": method, "output_dir": str(root), "configs": paths,
              "native_paths": {k: v.replace(str(source_root), str(root)) for k, v in prepared_blind["native_paths"].items()},
              "result_paths": {k: v.replace(str(source_root), str(root)) for k, v in prepared_blind["result_paths"].items()}}
    result["result_paths"].update({"orbit_native": str(root/"output"/date/f"gracefo1_orbit_{date}.dat"),
                                     "covariance_observations": str(root/"output"/date/"state_covariance_observations.txt"),
                                     "parameter_covariance": str(root/"output"/date/"parameter_covariance.txt"),
                                     "apriori_solution": str(root/"output"/date/"full_apriori_solution.txt"),
                                     "parameter_names": str(root/"output"/date/"full_parameter_names.txt"),
                                     "phase_recovery": str(root/"output"/date/"phase_recovery.txt"),
                                     "preprocessing_audit":str(root/"output"/date/"preprocessing_audit.txt")})
    result.update({key: prepared_blind[key] for key in ("force_model_hash", "measurement_model_hash", "preprocessing_hash", "mask_hash")})
    return result


def build_prediction_config(fit_config_path, fitted_orbit_path, calibration_inputs,
                            output_dir):
    """Predict withheld code with native corrections, without refitting anything."""
    hidden = [x for x in calibration_inputs if x["role"] == "heldout_gnss_code"]
    if len(hidden) != 1 or sha256_file(hidden[0]["path"]) != hidden[0]["sha256"]:
        raise ValueError("prediction requires one verified held-out code artifact")
    root = Path(output_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    native_receiver = root / "heldout_receiver.dat"
    convert = ET.Element("groops")
    p = _program(convert, "GraceL1b2GnssReceiver")
    _add(p, "outputfileGnssReceiver", native_receiver)
    _add(p, "inputfile", hidden[0]["path"])
    fitted = ET.parse(fit_config_path).getroot()
    gnss = fitted.find(".//GnssProcessing")
    # The native receiver directly matches geometry epochs instead of
    # interpolating them. Retain piecewise orbit interpolation at pulse/density
    # knots and the same canonical attitude curve used during estimation.
    sampled_orbit, sampled_attitude = root/"heldout_orbit.dat", root/"heldout_attitude.dat"
    p = _program(convert, "OrbitPocResampleOrbit")
    _add(p, "inputfileOrbit", Path(fitted_orbit_path).resolve())
    _add(p, "outputfileOrbit", sampled_orbit)
    _add(_add(_add(p, "timeSeries"), "instrument"), "inputfileInstrument", native_receiver)
    dynamic = gnss.find("parametrization/leoDynamicOrbits")
    for tag in ("parametrizationAcceleration", "stochasticPulse", "interpolationDegree"):
        for node in dynamic.findall(tag): p.append(deepcopy(node))
    canonical_attitude = fitted.find("global/filename[@label='orbitPocCanonicalAttitude']")
    if canonical_attitude is None:
        raise ValueError("prediction requires the fitted configuration's canonical attitude provenance")
    _resample_at_receiver_epochs(convert, canonical_attitude.text, sampled_attitude, native_receiver)
    predict = ET.Element("groops")
    global_variables = fitted.find("global")
    if global_variables is not None:
        convert.insert(0, deepcopy(global_variables))
        predict.append(deepcopy(global_variables))
    p = _program(predict, "OrbitPocPredictCode")
    predictions = root / "heldout_predictions.txt"
    _add(p, "outputfilePredictions", predictions)
    predictive_support = root / "heldout_prediction_support.txt"
    _add(p, "outputfileSupport", predictive_support)
    _add(_add(_add(p, "timeSeries"), "instrument"), "inputfileInstrument", native_receiver)
    for tag in ("timeMargin", "transmitter", "receiver", "earthRotation"):
        p.append(deepcopy(gnss.find(tag)))
    receiver = p.find("receiver/lowEarthOrbiter")
    receiver.find("inputfileObservations").text = str(native_receiver)
    receiver.find("inputfileOrbit").text = str(sampled_orbit)
    receiver.find("inputfileStarCamera").text = str(sampled_attitude)
    # lowEarthOrbiter requires the configuration subtree at construction, even
    # though OrbitPocPredictCode never invokes receiver preprocessing or a fit.
    # Runtime daily-loop variables must be resolved when cloning a standalone
    # predictor. The GNSS fit itself is nested inside the official daily loop.
    start = float(fitted.find("global/time[@label='timeStart']").text)
    from datetime import timedelta
    date = (datetime(1858, 11, 17)+timedelta(days=start)).strftime("%Y-%m-%d")
    for original in gnss.findall("parametrization"):
        if any(original.find(tag) is not None for tag in ("ionosphereSTEC", "ionosphereVTEC", "signalBiases")):
            clone = deepcopy(original)
            # Do not write receiver products during prediction.
            for parent in clone.iter():
                for child in list(parent):
                    if child.tag.startswith("outputfile"):
                        parent.remove(child)
            p.append(clone)
    for tree in (convert, p):
        for node in tree.iter():
            if node.text:
                node.text = node.text.replace("{loopTime:%D}", date).replace("loopTimeEnd", str(start+1)).replace("loopTime", str(start))
    return {"configs": {"convert_holdout": _save(convert, root/"convert_holdout.xml"),
                         "predict": _save(predict, root/"predict.xml")},
            "predictions": str(predictions), "predictive_support": str(predictive_support),
            "receiver_orbit": str(sampled_orbit),
            "receiver_attitude": str(sampled_attitude)}
