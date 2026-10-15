"""Fixed-nuisance native signal comparisons and selected covariance queries."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.groops_config import build_prediction_config
from orbit_poc.comparison.protocol import artifact_record, canonical_hash, file_hash, write_json
from orbit_poc.numerics.optimizer import NumericalFailure
from .graph import _records, _hex_extended, _coalesce


def physical_queries(point, design_path, query_path):
    """Map actual native position/velocity stencils to variation grid states."""
    design = list(_records(design_path))
    if (not design or design[-1] != {"kind":"complete"}
            or design[0].get("schema") != "orbit-poc-segmented-design-v1"):
        raise NumericalFailure("incomplete_segment_export","Missing completed physical design")
    n = design[0]["epochs"]
    dynamic = np.flatnonzero(point.dynamic)
    local = point.metadata.get("diagnostics",{}).get("local_parameters")
    if (type(n) is not int or n < 2 or type(local) is not int or local < 0
            or len(dynamic) < 6 or not np.array_equal(dynamic,np.arange(dynamic[0],dynamic[0]+len(dynamic)))
            or design[0].get("parameter_count") != len(dynamic)
            or design[0].get("initial_parameter_offset") != len(dynamic)-6
            or design[0].get("post_pulse") is not True):
        raise NumericalFailure("parameter_order","Covariance query native parameter/grid identity changed")
    epochs = [row for row in design if row["kind"] == "epoch"]
    if len(epochs) != n or [row["index"] for row in epochs] != list(range(n)):
        raise NumericalFailure("invalid_segment_graph","Physical grid identity changed")
    phi = np.array([row["phi"] for row in epochs]).reshape(n,6,6)
    if not np.isfinite(phi).all():
        raise NumericalFailure("invalid_segment_graph","Nonfinite physical query fundamental matrix")
    records = list(_records(query_path))
    if (not records or records[0].get("factor_stem") != point.metadata["factor_prefix"]
            or records[0].get("schema") != "orbit-poc-segmented-covariance-queries-v1"
            or records[0].get("kind") != "metadata" or records[-1].get("kind") != "complete"
            or records[0].get("coordinates") != "Cartesian_SI"
            or records[0].get("row_order") != "position_xyz_velocity_xyz"
            or records[0].get("post_pulse_velocity") is not True
            or records[0].get("covariance_produced") is not False):
        raise NumericalFailure("stale_segment_graph","Covariance queries do not identify the final factor")
    offset = len(point.scales)
    groups = {"trajectory": [], "nominal_observation": []}
    receiver = None
    for record in records[1:-1]:
        if record.get("kind") != "state" or record.get("set") not in groups or record.get("arc") != 0:
            raise NumericalFailure("invalid_segment_graph","Unknown selected covariance coordinate")
        if receiver is None:
            receiver = record.get("receiver")
        if (type(receiver) is not int or receiver < 0 or record.get("receiver") != receiver
                or record.get("native_first") != local+int(dynamic[0])
                or record.get("native_count") != len(dynamic)
                or type(record.get("index")) is not int
                or record["index"] != len(groups[record["set"]])):
            raise NumericalFailure("parameter_order","Covariance query block, receiver or index changed")
        epoch = record.get("time")
        if (not isinstance(epoch,list) or len(epoch) != 2
                or type(epoch[0]) is not int or not isinstance(epoch[1],(int,float))
                or not np.isfinite(epoch).all() or not 0 <= epoch[1] < 1):
            raise NumericalFailure("changed_support","Invalid split native covariance query time")
        if record["set"] == "trajectory":
            if record["index"] >= n or epoch != epochs[record["index"]]["time"]:
                raise NumericalFailure("changed_support","Trajectory query no longer matches native grid")
        previous = groups[record["set"]]
        if previous and tuple(epoch) <= tuple(previous[-1][0]["time"]):
            raise NumericalFailure("changed_support","Covariance query epochs are not strictly increasing")
        queries = []
        for row in range(6):
            terms = []
            halo = record["position_halo" if row < 3 else "velocity_halo"]
            if not isinstance(halo,list) or not halo:
                raise NumericalFailure("incomplete_segment_export","Empty Cartesian query stencil")
            indices = set()
            for index, rounded, high, low in halo:
                if type(index) is not int or not 0 <= index < n:
                    raise NumericalFailure("invalid_segment_graph","Covariance query leaves the native grid")
                if index in indices:
                    raise NumericalFailure("invalid_segment_graph","Covariance query repeats an interpolation node")
                indices.add(index)
                weight = _hex_extended(high)+_hex_extended(low)
                if (not np.isfinite(weight) or not np.isfinite(rounded)
                        or abs(float(weight)-rounded) > abs(np.spacing(rounded))):
                    raise NumericalFailure("invalid_segment_graph","Covariance interpolation coefficient changed")
                if record["set"] == "trajectory" and (len(halo) != 1 or index != record["index"] or weight != 1):
                    raise NumericalFailure("changed_support","Grid covariance must use its actual stored post-pulse state")
                terms.extend((offset+6*index+c,weight*np.longdouble(phi[index,row,c])) for c in range(6))
            queries.append(_coalesce(terms))
        groups[record["set"]].append((record,tuple(queries)))
    if (len(groups["trajectory"]) != n or not groups["nominal_observation"]
            or records[-1].get("trajectory_count") != len(groups["trajectory"])
            or records[-1].get("nominal_observation_count") != len(groups["nominal_observation"])):
        raise NumericalFailure("incomplete_segment_export","Covariance query support or final counts are incomplete")
    return groups


def covariance_is_valid(values):
    values = np.asarray(values)
    if values.ndim != 3 or values.shape[1:] != (6,6) or not np.isfinite(values).all():
        raise NumericalFailure("invalid_covariance","Invalid Cartesian covariance shape or entries")
    diagonal = np.diagonal(values,axis1=1,axis2=2)
    if np.any(diagonal <= 0) or not np.allclose(values,values.transpose(0,2,1),rtol=1e-9,atol=1e-14):
        raise NumericalFailure("invalid_covariance","Cartesian covariance is not symmetric positive definite")
    sd = np.sqrt(diagonal)
    try:
        np.linalg.cholesky(values/sd[:,:,None]/sd[:,None,:])
    except np.linalg.LinAlgError as error:
        raise NumericalFailure("invalid_covariance","Cartesian covariance is not positive definite") from error


def _signals(model, configuration, orbit, observation, directory):
    """No cleaning, nuisance fit, ambiguity reset or reference data is used."""
    directory = Path(directory)
    recipe = build_prediction_config(configuration,orbit,[{**observation,"role":"heldout_gnss_code"}],directory)
    # Preserve the complete configured interval: the legacy prediction helper
    # resolves daily-loop placeholders to one day, appropriate only for v3.
    source = ET.parse(configuration).getroot()
    start = source.findtext("global/time[@label='timeStart']")
    stop = source.findtext("global/time[@label='timeEnd']")
    if start is None or stop is None:
        raise ValueError("Signal comparison requires explicit complete arc bounds")
    dynamic = source.find(".//GnssProcessing/parametrization/leoDynamicOrbits")
    convert = ET.parse(recipe["configs"]["convert_holdout"]).getroot()
    resample = convert.find(".//OrbitPocResampleOrbit")
    for node in list(resample.findall("stochasticPulse")):
        resample.remove(node)
    if dynamic.find("stochasticPulse") is not None:
        pulse = deepcopy(dynamic.find("stochasticPulse"))
        for node in pulse.iter():
            if node.text:
                node.text = node.text.replace("loopTimeEnd",stop).replace("loopTime",start)
        resample.append(pulse)
    model.execute(convert,directory,"convert-signals")
    tree = ET.parse(recipe["configs"]["predict"]).getroot()
    program = tree.find(".//OrbitPocPredictCode")
    program.tag = "OrbitPocPredictSignals"
    ET.SubElement(program,"inputfileReceiverOrbit").text = str(orbit)
    ET.SubElement(program,"interpolationDegree").text = dynamic.findtext("interpolationDegree","7")
    pulse = dynamic.find("stochasticPulse")
    if pulse is not None:
        pulse = deepcopy(pulse)
        for node in pulse.iter():
            if node.text:
                node.text = node.text.replace("loopTimeEnd",stop).replace("loopTime",start)
        program.append(pulse)
    density = dynamic.find("parametrizationAcceleration/logDensity/inputfileLogDensity")
    if density is not None:
        ET.SubElement(program,"inputfileDensityKnots").text = density.text
    output, support = directory/"signals.txt",directory/"support.txt"
    program.find("outputfilePredictions").text = str(output)
    program.find("outputfileSupport").text = str(support)
    model.execute(tree,directory,"predict-signals",{
        "ORBIT_POC_NUMERICS_QR_PREFIX":str(directory/"precise-interpolation"),
        "ORBIT_POC_NUMERICS_SOLVER":"scaled_qr_v1"})
    rows = native.read_native_table(output,8)
    identity = [line.split() for line in support.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if len(identity) != len(rows) or any(len(row) != 3 for row in identity):
        raise NumericalFailure("changed_support","Native signal identities are incomplete")
    keys = []
    for row, entry in zip(rows,identity):
        if float(entry[0]) != row[0] or int(entry[1]) != row[1]:
            raise NumericalFailure("changed_support","Native signal support disagrees with predictions")
        keys.append(canonical_hash({"epoch":entry[0],"prn":entry[1],"signal":entry[2],
                                    "clock_seconds":row[6],"stec":row[7]}))
    if len(set(keys)) != len(keys) or not np.isfinite(rows).all() or np.any(rows[:,5] <= 0):
        raise NumericalFailure("invalid_prediction","Invalid native fixed-nuisance signal rows")
    return rows,np.asarray(keys,dtype="U64"),[artifact_record("native_fixed_nuisance_signals",output),
        artifact_record("native_fixed_nuisance_support",support)]


def prediction_artifacts(model, point):
    observations = [x for x in model.job["estimation_inputs"] if x["role"] == "gnss_observations"]
    if len(observations) != 1 or file_hash(observations[0]["path"]) != observations[0]["sha256"]:
        raise ValueError("Exactly one frozen retained GNSS observation artifact is required")
    configuration = point.metadata["configuration"]
    outputs = point.metadata["config"]["result_paths"]
    actual, ids, artifacts = _signals(model,configuration,outputs["orbit_native"],observations[0],model.root/"prediction-final")
    reference, reference_ids, weight_artifacts = _signals(model,configuration,model.prepared["native_paths"]["orbit"],
                                                        observations[0],model.root/"prediction-fixed-weights")
    if not np.array_equal(ids,reference_ids):
        raise NumericalFailure("changed_support","Physical fit changed fixed-nuisance prediction support")
    nominal = np.where(actual[:,3] == 0,.3,.003)
    sigma = np.minimum(reference[:,5],nominal)
    path = model.root/"predictions.npz"
    # y is identical across profiles; differences of these unweighted residuals
    # are precisely negative predicted-measurement differences.
    np.savez_compressed(path,row_ids=ids,values_m=actual[:,4],sigma_m=sigma)
    receipt = model.root/"prediction-policy.json"
    write_json(receipt,{"schema":"orbit-poc-segmented-prediction-check-v1",
        "scope":"Paired native code/phase differences at identical fixed nuisance values; no accuracy score",
        "values":"observed minus native prediction, metres; common observations cancel",
        "sigma":"minimum of native sigma at immutable prepared geometry and prescribed per-frequency noise",
        "fixed_geometry":artifact_record("initial_orbit",model.prepared["native_paths"]["orbit"]),
        "receiver_clock_seconds":np.unique(actual[:,6]).tolist(),"no_nuisance_refit":True,
        "native_fit_weights_unchanged":True})
    return [artifact_record("segmented_predictions",path),artifact_record("segmented_prediction_policy",receipt),
            *artifacts,*weight_artifacts]


def covariance_pairs(mjd):
    """Identical selected cross blocks for every computational layout."""
    seconds = (np.asarray(mjd)-mjd[0])*86400.
    nearest = lambda hours:int(np.argmin(abs(seconds-hours*3600.)))
    return sorted(pair for pair in {(0,len(mjd)-1),(nearest(1),nearest(2)),(nearest(4),nearest(8))}
                  if pair[0] != pair[1])


def selected_original_design(path,indices):
    """Recover selected original-coordinate maps, without a whole-arc design.

    This is a post-fit diagnostic for the archived dense binary, using the
    separately pinned native exporter. Its parameter covariance and accepted
    solution remain those of the archived corrected executable.
    """
    records = list(_records(path))
    if (not records or records[0].get("schema") != "orbit-poc-segmented-design-v1"
            or records[-1] != {"kind":"complete"}):
        raise NumericalFailure("incomplete_segment_export","Dense covariance diagnostic lacks a completed native operator")
    n,p = records[0]["epochs"],records[0]["parameter_count"]
    if any(type(i) is not int or not 0 <= i < n for i in indices) or records[0]["initial_parameter_offset"] != p-6:
        raise NumericalFailure("invalid_segment_graph","Dense covariance diagnostic coordinates changed")
    phi = {row["index"]:np.asarray(row["phi"]).reshape(6,6) for row in records if row["kind"]=="epoch"}
    forcing = {row["index"]:row["integrand"] for row in records if row["kind"]=="forcing"}
    quadrature = {row["interval"]:row["terms"] for row in records if row["kind"]=="quadrature"}
    pulses = {}
    for row in records:
        if row["kind"]=="pulse":pulses.setdefault(row["epoch"],[]).append(row)
    if set(phi) != set(range(n)) or set(quadrature) != set(range(n-1)):
        raise NumericalFailure("incomplete_segment_export","Dense covariance diagnostic grid is incomplete")
    state = np.zeros((6,p),dtype=np.longdouble);state[:,-6:] = np.eye(6)
    result = {}
    for epoch in range(n):
        if epoch:
            for sample,weight,_ in quadrature[epoch-1]:
                for component,parameter,value in forcing[sample]:
                    state[component,parameter] += np.longdouble(weight)*value
            for pulse in pulses.get(epoch,[]):
                state[:,pulse["parameter"]:pulse["parameter"]+3] += np.asarray(pulse["map"]).reshape(6,3)
        if epoch in indices:
            result[epoch] = np.asarray(phi[epoch].astype(np.longdouble)@state,dtype=float)
    return result
