"""Native signal-difference checks shared by numerical refinement diagnostics."""
from pathlib import Path
from copy import deepcopy
import xml.etree.ElementTree as ET
import json
import numpy as np
from orbit_poc.comparison import backend as native
from orbit_poc.comparison.groops_config import build_prediction_config


def predict_signals(model, fit_config, orbit, observations, directory):
    """All nuisance values remain fixed; no cleaning, fitting, or clock centering."""
    directory=Path(directory)
    recipe=build_prediction_config(fit_config,orbit,[{**observations,"role":"heldout_gnss_code"}],directory)
    model.execute(ET.parse(recipe["configs"]["convert_holdout"]).getroot(),directory,"convert_signals")
    tree=ET.parse(recipe["configs"]["predict"]).getroot()
    program=tree.find(".//OrbitPocPredictCode")
    program.tag="OrbitPocPredictSignals"
    # Exercise receiver/attitude interpolation near both historical snap
    # margins, in both directions, as well as ordinary nonzero clock offsets.
    clock_offsets=[5e-8,-5e-8,5e-6,-5e-6,2e-5,-2e-5]
    for offset in clock_offsets:
        ET.SubElement(program,"fixedReceiverClockOffsetSeconds").text=format(offset,".17g")
    ET.SubElement(program,"inputfileReceiverOrbit").text=str(orbit)
    dynamic=ET.parse(fit_config).find(".//GnssProcessing/parametrization/leoDynamicOrbits")
    if dynamic is None:raise ValueError("Signal refinement needs the estimator's interpolation specification")
    ET.SubElement(program,"interpolationDegree").text=dynamic.findtext("interpolationDegree","7")
    pulse=dynamic.find("stochasticPulse")
    if pulse is not None:
        pulse=deepcopy(pulse)
        # Fitting recipes may sit inside a native date loop. The prediction
        # program is standalone and already carries equivalent day globals.
        for node in pulse.iter():
            if node.text:node.text=node.text.replace("loopTimeEnd","timeEnd").replace("loopTime","timeStart")
        program.append(pulse)
    density=dynamic.find("parametrizationAcceleration/logDensity/inputfileLogDensity")
    if density is not None:ET.SubElement(program,"inputfileDensityKnots").text=density.text
    output,support=directory/"signals.txt",directory/"signal_support.txt"
    program.find("outputfilePredictions").text=str(output)
    program.find("outputfileSupport").text=str(support)
    # The actual opt-in GNSS estimator disables tolerance-based grid snapping.
    # Set its environment before native construction so this diagnostic uses
    # the identical interpolation branch, without solving nuisance parameters.
    environment={"ORBIT_POC_NUMERICS_QR_PREFIX":str(directory/"interpolation-audit"),
                 "ORBIT_POC_NUMERICS_SOLVER":"scaled_qr_v1"}
    (directory/"prediction_mode.json").write_text(json.dumps({
        "schema":"orbit-poc-signal-refinement-mode-v1", "environment":environment,
        "native_program":"OrbitPocPredictSignals", "nuisance_fitting":False,
        "fixed_receiver_clock_offsets_seconds":clock_offsets,
        "receiver_cache_refresh":"Exact native OrbitPocPiecewisePolynomial at corrected receive times plus sub-Time remainders, including original pulse/density boundaries",
        "receiver_position_rounding":"Preserve sub-double interpolation remainders for the native stable range equation",
        "interpolation_policy":"Same QR-enabled native Polynomial relative-query evaluation and exact boundary sides as the numerical estimator"},indent=2)+"\n")
    model.execute(tree,directory,"predict_signals",environment=environment)
    rows=native.read_native_table(output,8)
    if not np.array_equal(np.unique(rows[:,6]),np.sort(clock_offsets)):
        raise ValueError("Native signal refinement did not preserve every prescribed fixed clock offset")
    return rows,support.read_text()


def compare_signals(first,second,code_sigma=.3,phase_sigma=.003):
    a,support_a=first;b,support_b=second
    if a.shape!=b.shape or not np.array_equal(a[:,:4],b[:,:4]) or support_a!=support_b:
        raise ValueError("Complete native signal identities changed under numerical refinement")
    if not np.array_equal(a[:,6:],b[:,6:]):
        raise ValueError("Fixed receiver clock/STEC differ under refinement")
    difference=np.abs(a[:,4]-b[:,4])
    # Prediction is unweighted. Flight accuracy patterns are evaluated at the
    # supplied geometry, so their diagnostic sigma can shift at roundoff level.
    # Freeze the coarse sigmas for BOTH numerical differences instead of using
    # either refined weights or a fitted objective.
    result={"fixed_nuisance_values_identical":True,
        "receiver_clock_values_seconds":np.unique(a[:,6]).tolist(),
        "comparison_weights_frozen":True,"comparison_weight_source":"coarse native sigma shared by both predictions",
        "raw_native_sigmas_identical":bool(np.array_equal(a[:,5],b[:,5])),
        "raw_native_sigma_maximum_relative_change":float(np.max(np.abs(a[:,5]-b[:,5])/a[:,5])),"signals":[]}
    for phase,label,sigma in ((0,"code",code_sigma),(1,"carrier",phase_sigma)):
        for frequency in (1575420000.,1227600000.):
            selected=(a[:,3]==phase)&(a[:,2]==frequency)
            if not selected.any():raise ValueError("Native refinement lacks a dual-frequency code/phase component")
            # Demand one percent of both the specified independent per-frequency
            # benchmark noise and the native sigma where the latter is smaller.
            tolerance=.01*np.minimum(a[selected,5],sigma)
            result["signals"].append({"observable":label,"frequency_hz":frequency,"rows":int(selected.sum()),
                "assumed_sigma_m":sigma,"minimum_native_sigma_m":float(a[selected,5].min()),
                "maximum_difference_m":float(difference[selected].max()),
                "maximum_fraction_of_sigma":float((difference[selected]/np.minimum(a[selected,5],sigma)).max()),
                "passed":bool(np.all(difference[selected]<tolerance))})
    result["passed"]=all(row["passed"] for row in result["signals"])
    result["limitation"]="Paired numerical differences at fixed nuisance values; absolute residuals, especially unknown carrier ambiguities, are not scored."
    return result
