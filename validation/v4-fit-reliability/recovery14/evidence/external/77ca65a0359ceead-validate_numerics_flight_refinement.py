#!/usr/bin/env python3
"""Check closed staged flight propagation and native code predictions under refinement.

This is the predeclared Apr24 development window, with one fixed physical initial
state and no estimation. The comparison jointly refines the state grid, thermal
step and atmospheric quadrature. Native code and carrier equations are evaluated at identical fixed nuisance
values; the raw residuals are used only for paired numerical differences.
"""
from copy import deepcopy
from pathlib import Path
import argparse
import json
import time
import xml.etree.ElementTree as ET

import numpy as np

from orbit_poc.comparison import backend as native
from orbit_poc.comparison.data import split_gps1b
from orbit_poc.comparison.initialization import _field, _standalone
from orbit_poc.comparison.protocol import file_hash, write_json
from orbit_poc.numerics.backend import PhysicalState
from check_flight_refinement import resample
from validate_comparison_native import add_offgrid_interpolation
from validate_numerics_flight_derivatives import prepare
from numerics_refinement_helpers import predict_signals, compare_signals


def check(prepared, binary, directory, start_seconds=42300., duration=1800.):
    model, configured, state, result = prepare(prepared, binary, directory, start_seconds, duration)
    root = Path(directory).resolve()
    result.update(schema="flight-staged-refinement-3.1", diagnostic_source_sha256=file_hash(__file__),
                  signal_diagnostic_source_sha256=file_hash(Path(__file__).with_name("numerics_refinement_helpers.py")),
                  scope="Apr24 30-minute development window at fixed initial state and zero pulses; joint grid, thermal and atmospheric refinement; no accuracy claim")
    write_json(root / "result.json", result)
    source_manifest = json.loads(Path(prepared).read_text())
    original_propagation=ET.parse(source_manifest["configs"]["variational"]).find(".//PreprocessingVariationalEquation")
    original_radiation=original_propagation.findall("forces/miscAccelerations/radiationPressure")
    thermal_steps=[float(node.findtext("orbitPocThermalMaximumStep", "1")) for node in original_radiation]
    atmosphere_step=float(original_propagation.findtext("orbitPocAtmosphericQuadratureStep", "1"))
    if not thermal_steps or any(value<=0 for value in [*thermal_steps,atmosphere_step]):
        raise ValueError("Invalid actual flight numerical controls")
    coarse_source=ET.parse(configured["configs"]["variational"]).getroot()
    for node,step in zip(coarse_source.findall(".//PreprocessingVariationalEquation/forces/miscAccelerations/radiationPressure"),thermal_steps):
        _field(node,"orbitPocThermalMaximumStep",step)
    native._save_xml(coarse_source,configured["configs"]["variational"])
    result.update(actual_config_sha256=file_hash(configured["configs"]["variational"]),
        thermal_maximum_step_seconds=thermal_steps,
        controls={"coarse": {"state_seconds":5.,"thermal_seconds":thermal_steps,"atmosphere_seconds":atmosphere_step},
                  "fine": {"state_seconds":2.5,"thermal_seconds":[step/2 for step in thermal_steps],"atmosphere_seconds":atmosphere_step/2}})
    write_json(root / "result.json",result)
    try:
        coarse_dir = root / "coarse"
        coarse_dir.mkdir()
        coarse_config = deepcopy(configured)
        coarse = model._close(state, coarse_config, coarse_dir, True)
        fine_dir = root / "fine"
        fine_dir.mkdir()
        source = ET.parse(configured["configs"]["variational"]).getroot()
        # Resampling fixes the physical attitude curve and numerical initial
        # curve while changing only the native force quadrature grid.
        sampling = ET.Element("groops")
        resample(sampling, coarse[0], fine_dir / "seed.dat", coarse[4][0], duration, 2.5)
        resample(sampling, root / "inputs/attitude.txt", fine_dir / "attitude.dat", coarse[4][0], duration, 2.5)
        model.execute(sampling, fine_dir, "resample")
        propagation = source.find(".//PreprocessingVariationalEquation")
        _field(propagation, "inputfileStarCamera", fine_dir / "attitude.dat")
        _field(propagation, "orbitPocAtmosphericQuadratureStep", atmosphere_step/2)
        for node,step in zip(propagation.findall("forces/miscAccelerations/radiationPressure"),thermal_steps):
            _field(node, "orbitPocThermalMaximumStep", step/2)
        fine_config = deepcopy(configured)
        fine_config["configs"]["variational"] = str(native._save_xml(source, fine_dir / "variational.xml"))
        fine_state = PhysicalState(state.initial.copy(), state.force.copy(), fine_dir / "seed.dat")
        fine = model._close(fine_state, fine_config, fine_dir, True)
        compared = {}
        common, ia, ib = np.intersect1d(coarse[4], fine[4], return_indices=True)
        if len(common) != len(coarse[4]):
            raise ValueError("Refined grid omits coarse native epochs")
        compared["aligned_position_maximum_m"] = float(np.max(np.linalg.norm(coarse[5][ia,:3]-fine[5][ib,:3], axis=1)))
        exported = []
        for label, output, config in (("coarse", coarse, coarse_config), ("fine", fine, fine_config)):
            folder = root / label
            tree = ET.parse(config["configs"]["variational"]).getroot()
            programs = model._evaluation(config, tree, output[1], folder / "fixed_orbit.dat", output[2])
            evaluate = _standalone(tree, programs, configured["date"])
            add_offgrid_interpolation(evaluate, folder, coarse[4][0], duration, 5.)
            # The shared evaluator already adds an interpolation degree.
            for element in evaluate.findall(".//OrbitPocEvaluateVariational"):
                entries=element.findall("interpolationDegree")
                for duplicate in entries[1:]:element.remove(duplicate)
            model.execute(evaluate, folder, "offgrid")
            exported.append(native.read_native_table(folder / "offgrid_orbit.txt", 10))
        if not np.array_equal(exported[0][:,0], exported[1][:,0]):
            raise ValueError("Native off-grid query epochs differ")
        compared["offgrid_position_maximum_m"] = float(np.max(np.linalg.norm(exported[0][:,1:4]-exported[1][:,1:4], axis=1)))
        # These retained development observations are reused only to compare
        # numerical predictions. They are not held-out accuracy validation.
        observations = next(item for item in source_manifest["estimation_inputs"] if item["role"] == "gnss_observations")
        selected = split_gps1b(observations["path"], configured["date"], root / "observations",
            {"intervals_seconds": [], "cadence_seconds": 30, "time_scale": "UTC"},
            arc_start_offset_seconds=start_seconds+source_manifest["arc"]["gps_start_offset_seconds"], duration_hours=duration/3600)["retained"]
        prediction_input = {**selected, "role": "heldout_gnss_code"}
        # Rebuild private transmitter products from the archived precise inputs.
        # Historical conversion directories may be temporary symlinks; never
        # repair or overwrite the protected v3 preparation in place.
        products=root/"native-products"
        conversion=ET.parse(source_manifest["configs"]["convert_gnss"]).getroot()
        original_root=source_manifest["output_dir"]
        for node in conversion.iter():
            if node.text:node.text=node.text.replace(original_root,str(products))
        destinations=[node.text for node in conversion.iter()
            if node.text and (node.tag.startswith("outputfile") or node.tag=="directory")]
        if not destinations or any(not value.startswith(str(products)+"/") for value in destinations):
            raise ValueError("Private transmitter conversion contains an output outside the diagnostic directory")
        model.execute(conversion,products,"convert_transmitters")
        product_files=[path for name in ("orbit","attitude","clock","signalBias")
            for path in (products/"data"/configured["date"]/name).glob("*.G??.*") if path.is_file()]
        result["converted_transmitter_hashes"]={str(path.relative_to(products)):file_hash(path) for path in product_files}
        fitting = ET.parse(source_manifest["configs"]["estimate"]).getroot()
        for node in fitting.iter():
            if node.text:node.text=node.text.replace(original_root,str(products))
        global_node=fitting.find("global")
        canonical=global_node.find("filename[@label='orbitPocCanonicalAttitude']")
        if canonical is None:canonical=ET.SubElement(global_node,"filename",label="orbitPocCanonicalAttitude")
        canonical.text=str(root / "inputs/attitude.txt")
        dynamic=fitting.find(".//GnssProcessing/parametrization/leoDynamicOrbits")
        for name in ("stochasticPulse", "parametrizationAcceleration"):
            for node in list(dynamic.findall(name)):dynamic.remove(node)
        fit_path=native._save_xml(fitting, root / "prediction_recipe.xml")
        predictions=[]
        for label,output in (("coarse",coarse),("fine",fine)):
            predictions.append(predict_signals(model,fit_path,output[0],prediction_input,root / label / "predictions"))
        signals=compare_signals(*predictions)
        result.update(status="complete",passed=compared["aligned_position_maximum_m"]<3e-5 and compared["offgrid_position_maximum_m"]<3e-5 and signals["passed"],
            metrics=compared,native_signals=signals,signal_prediction_mode="QR-enabled native Polynomial query evaluation; fixed nuisance values",offgrid_epochs=len(exported[0]),
            code_threshold_m=.003,carrier_threshold_m=3e-5,
            carrier_limitation="Complete native phase equations are differenced at identical fixed nuisance values. Absolute phase residuals are not scored as known ambiguities.",
            physical_initial_sha256=file_hash(coarse_dir / "physical_initial.txt"),
            nominal_attitude_sha256=file_hash(root / "inputs/attitude.txt"),
            retained_observation_sha256=observations["sha256"],selected_observation_sha256=selected["sha256"],
            elapsed_seconds=time.monotonic()-model.start,propagations=model.propagations)
        write_json(root / "result.json", result)
        return result
    except Exception as error:
        result.update(status="failed",error=str(error),propagations=model.propagations)
        write_json(root / "result.json", result)
        raise


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("prepared","binary","output"):parser.add_argument("--"+name,type=Path,required=True)
    args=parser.parse_args()
    result=check(args.prepared,args.binary,args.output)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["passed"] else 1)
