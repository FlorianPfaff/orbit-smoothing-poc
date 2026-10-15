#!/usr/bin/env python3
"""Install diagnostic-only taps AFTER the frozen candidate06 extension.

This never edits the frozen extension repository. The destination must be a new
generated GROOPS source tree. Original scalar arithmetic statements stay intact.
The only expression wrappers expose existing vector temporaries by const ref.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

MARKER = "// ORBIT_POC_DIAGNOSTIC_ROW_TRACE_D01"
INCLUDE = '#include "misc/orbitPoc/rowArithmeticTrace.h"\n'


def replace_once(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Expected exactly one diagnostic anchor: {before[:100]!r}")
    return text.replace(before, after, 1)


def patched_files(source):
    updates = {}

    def read(name):
        text = (source / name).read_text()
        if MARKER in text:
            raise ValueError(f"Diagnostic installer refuses an already instrumented tree: {name}")
        return text

    def save(name, text):
        updates[name] = MARKER + "\n" + INCLUDE + text

    name = "gnss/gnssObservation.cpp"
    text = read(name)
    text = replace_once(text, "    // Corrected range\n", "    orbitPocTrace::Equation traceEquation(receiver->idRecv(),transmitter->idTrans(),idEpoch);\n"
        "    orbitPocTrace::vector(\"observed\",l);\n"
        "    orbitPocTrace::scalar(\"receiver_clock_seconds\",receiver->clockError(idEpoch),0);\n"
        "    orbitPocTrace::scalar(\"transmitter_clock_seconds\",transmitter->clockError(idEpoch),0);\n"
        "    orbitPocTrace::scalar(\"transmitter_scale\",transmitter->scaleFactor(idEpoch),0);\n"
        "    // Corrected range\n")
    anchor = "        l(i) = orbitPocQr::enabled() ? orbitPocQr::stableRangeResidual"
    lines = text.splitlines(True)
    positions = [i for i, line in enumerate(lines) if line.startswith(anchor)]
    if len(positions) != 1:
        raise ValueError("Expected one already-installed precise range expression")
    index = positions[0]
    original = lines[index]
    lines[index] = "      {\n        orbitPocTrace::row(i);\n" + original + "        orbitPocTrace::selected(\"range_narrowed\",l(i));\n      }\n"
    text = "".join(lines)
    text = replace_once(text, "    receiver->signalComposition(idEpoch, types, typesTransmitted, T);",
        "    receiver->signalComposition(idEpoch, types, typesTransmitted, T);\n    orbitPocTrace::allVector(\"signal_composition\",T);")
    original = "    l -= receiver->antennaVariations(timeRecv, azimutRecvAnt,  elevationRecvAnt,  types);"
    text = replace_once(text, original,
        "    orbitPocTrace::component(\"receiver\");\n    orbitPocTrace::vector(\"before_receiver_antenna\",l);\n"
        "    l -= orbitPocTrace::operand(\"receiver_antenna_operand\",receiver->antennaVariations(timeRecv, azimutRecvAnt,  elevationRecvAnt,  types));\n"
        "    orbitPocTrace::vector(\"after_receiver_antenna\",l);")
    original = "    l -= T * transmitter->antennaVariations(timeTrans, azimutTrans, elevationTrans, typesTransmitted);"
    text = replace_once(text, original,
        "    orbitPocTrace::component(\"transmitter\");\n    orbitPocTrace::vector(\"before_transmitter_antenna\",l);\n"
        "    l -= orbitPocTrace::operand(\"transmitter_composed_operand\",T * orbitPocTrace::operand(\"transmitter_antenna_operand\",transmitter->antennaVariations(timeTrans, azimutTrans, elevationTrans, typesTransmitted)));\n"
        "    orbitPocTrace::vector(\"after_transmitter_antenna\",l);\n    orbitPocTrace::component(\"observation\");")
    original = "    if(track && track->ambiguity)\n      l -= track->ambiguity->ambiguities(types);     // reduce ambiguities"
    text = replace_once(text, original,
        "    orbitPocTrace::vector(\"before_ambiguity\",l);\n"
        "    if(track && track->ambiguity)\n      l -= orbitPocTrace::operand(\"ambiguity_operand\",track->ambiguity->ambiguities(types));     // reduce ambiguities\n"
        "    orbitPocTrace::vector(\"after_ambiguity\",l);")
    text = replace_once(text, "    if(reduceModels)\n      reduceModels(*this);", "    orbitPocTrace::vector(\"before_reduce_models\",l);\n    if(reduceModels)\n      reduceModels(*this);\n    orbitPocTrace::vector(\"after_reduce_models\",l);")
    text = replace_once(text, "        if(l.size()) l.row(i) *= 1/sigma(i);", "        orbitPocTrace::row(i);\n        orbitPocTrace::selected(\"homogenize_sigma\",sigma(i));\n        orbitPocTrace::selected(\"before_homogenize\",l(i));\n        if(l.size()) l.row(i) *= 1/sigma(i);\n        orbitPocTrace::selected(\"after_homogenize\",l(i));")
    anchor = "    STEC  += x(0,0);\n    dSTEC += x(0,0);"
    text = replace_once(text, anchor, '    orbitPocTrace::Observation traceObservation(this);\n    orbitPocTrace::scalar("local_STEC_before",STEC,0);\n    orbitPocTrace::scalar("local_dSTEC_before",dSTEC,0);\n    orbitPocTrace::scalar("local_STEC_delta",x(0,0),0);\n' + anchor + '\n    orbitPocTrace::scalar("local_STEC_after",STEC,0);\n    orbitPocTrace::scalar("local_dSTEC_after",dSTEC,0);')
    save(name, text)

    name = "misc/orbitPoc/gnssRangeResidual.h"
    text = read(name)
    anchor = "  return static_cast<Double>(residual.rounded());"
    text = replace_once(text, anchor,
        "  orbitPocTrace::selectedExtended(\"range_twofold_high\",residual.high);\n"
        "  orbitPocTrace::selectedExtended(\"range_twofold_low\",residual.low);\n"
        "  orbitPocTrace::selectedExtended(\"geometric_twofold_high\",geometric.high);\n"
        "  orbitPocTrace::selectedExtended(\"geometric_twofold_low\",geometric.low);\n"
        "  orbitPocTrace::selectedExtended(\"clock_twofold_high\",clock.high);\n"
        "  orbitPocTrace::selectedExtended(\"clock_twofold_low\",clock.low);\n" + anchor)
    save(name, text)

    name = "gnss/gnssTransceiver.h"
    text = read(name)
    text = replace_once(text, "    corr += signalBias.compute(types);", "    orbitPocTrace::array(\"signal_bias_native_array\",signalBias.biases);\n    corr += orbitPocTrace::operand(\"signal_bias_operand\",signalBias.compute(types));\n    orbitPocTrace::vector(\"after_signal_bias\",corr);")
    anchor = "    corr += antenna->antennaDef->antennaVariations(azimut, elevation, types, noPatternFoundAction);"
    text = replace_once(text, anchor, "    corr += orbitPocTrace::operand(\"antenna_pattern_operand\",antenna->antennaDef->antennaVariations(azimut, elevation, types, noPatternFoundAction));\n    orbitPocTrace::vector(\"after_antenna_pattern\",corr);")
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp"
    text = read(name)
    anchor = "    Vector value(types.size());\n    UInt idx;\n    if(this->value.size())"
    text = replace_once(text, anchor, "    orbitPocTrace::allVector(\"ambiguity_native_coordinates\",this->value);\n    orbitPocTrace::allVector(\"ambiguity_composition\",T);\n" + anchor)
    anchor = "          value(idType) = (T.row(idx) * this->value)(0,0);"
    text = replace_once(text, anchor, '        {\n          orbitPocTrace::scalar("ambiguity_type_mapping",idx,idType);\n' + anchor + '\n        }')
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp"
    text = read(name)
    anchor = "    const Double STEC = eqn.STEC;"
    text = replace_once(text, anchor, anchor + "\n    orbitPocTrace::scalar(\"STEC\",eqn.STEC,0);\n    orbitPocTrace::scalar(\"dSTEC\",eqn.dSTEC,0);\n    orbitPocTrace::scalar(\"sigmaSTEC\",eqn.sigmaSTEC,0);\n" + "\n".join(f'    orbitPocTrace::scalar("{flag}",{flag},0);' for flag in ["apply1stOrder", "apply2ndOrder", "apply3rdOrder", "applyBending", "estimateSTEC", "applyConstraint"]))
    anchor = "      const Double f4 = f1*f3;"
    text = replace_once(text, anchor, anchor + "\n      orbitPocTrace::row(i);\n" + "\n".join(f'      orbitPocTrace::selected("ionosphere_{key}",{value});' for key,value in [("f1","f1"),("f2","f2"),("f3","f3"),("f4","f4"),("Ap","Ionosphere::Ap"),("s","s"),("r","r"),("bending","bending")]))
    lines = text.splitlines(True)
    count = 0
    for i, line in enumerate(lines):
        if re.match(r"        if\(apply(?:1stOrder|2ndOrder|3rdOrder|Bending)\) +eqn\.l\(i\) +-=", line):
            count += 1
            stage = f"stec_operation_{count}"
            lines[i] = f'        orbitPocTrace::selected("{stage}_before",eqn.l(i));\n' + line + f'        orbitPocTrace::selected("{stage}_after",eqn.l(i));\n'
    if count != 7:
        raise ValueError(f"Expected seven unchanged STEC arithmetic statements, found {count}")
    text = "".join(lines)
    anchor = "      eqn.l(eqn.l.rows()-1)    = -eqn.dSTEC/eqn.sigmaSTEC; // constrain towards zero (0-f(x0))"
    text = replace_once(text, anchor, anchor + '\n      orbitPocTrace::scalar("STEC_prior_row",eqn.l(eqn.l.rows()-1),eqn.l.rows()-1);')
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationIonosphereVTEC.cpp"
    text = read(name)
    anchor = "                recv->observation(idTrans, idEpoch)->STEC += mapping(eqn.elevationRecvLocal) * (dVTEC + std::cos(eqn.azimutRecvLocal)*dgx + std::sin(eqn.azimutRecvLocal)*dgy);"
    text = replace_once(text, anchor, '                orbitPocTrace::Equation traceVtec(recv->idRecv(),idTrans,idEpoch);\n' + "\n".join(f'                orbitPocTrace::scalar("VTEC_{key}",{value},0);' for key,value in [("STEC_before","recv->observation(idTrans,idEpoch)->STEC"),("delta","dVTEC"),("gradient_x_delta","dgx"),("gradient_y_delta","dgy"),("elevation","eqn.elevationRecvLocal"),("azimuth","eqn.azimutRecvLocal")]) + '\n' + anchor + '\n                orbitPocTrace::scalar("VTEC_STEC_after",recv->observation(idTrans,idEpoch)->STEC,0);\n' + "\n".join(f'                orbitPocTrace::nativeShadow("VTEC_{key}",[&](){{return {value};}});' for key,value in [("mapping_shadow","mapping(eqn.elevationRecvLocal)"),("cos_shadow","std::cos(eqn.azimutRecvLocal)"),("sin_shadow","std::sin(eqn.azimutRecvLocal)")]))
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrization.cpp"
    text = read(name)
    anchor = "    for(auto b : base)\n      b->observationCorrections(eqn);"
    text = replace_once(text, anchor, "    for(auto b : base)\n    {\n      orbitPocTrace::vector((std::string(\"before_model:\")+typeid(*b).name()).c_str(),eqn.l);\n      b->observationCorrections(eqn);\n      orbitPocTrace::vector((std::string(\"after_model:\")+typeid(*b).name()).c_str(),eqn.l);\n    }")
    save(name, text)

    name = "misc/orbitPoc/scaledRowQr.h"
    text = read(name)
    anchor = '    previousStem=stem;stem=orbitPocQr::env("ORBIT_POC_NUMERICS_QR_PREFIX")+"."+std::to_string(++sequence);'
    text = replace_once(text, anchor, anchor + '\n    orbitPocTrace::begin(stem,"linearization",0.);')
    anchor = "    observationResiduals.emplace(key,Vector(target));"
    text = replace_once(text, anchor, anchor + '\n    orbitPocTrace::Equation traceRetained(receiver,transmitter,epoch);\n    orbitPocTrace::allVector("retained_original_rows",target);')
    save(name, text)

    name = "gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    text = read(name)
    anchor = "      auto evaluate=[&](Double alpha)\n      {\n        orbitPocRowQr().prepareCostOnly();"
    text = replace_once(text, anchor, '      auto evaluate=[&](Double alpha)\n      {\n        orbitPocTrace::begin(stem,"trial",alpha);\n        orbitPocRowQr().prepareCostOnly();')
    anchor = "trial.observationSignature=fixedObservations;buildNormals(FALSE,FALSE);"
    text = replace_once(text, anchor, 'trial.observationSignature=fixedObservations;orbitPocTrace::begin(stem,"trial",alpha);buildNormals(FALSE,FALSE);')
    anchor = "              localUpdates.push_back({eqn.receiver->observation(trans,epoch),local,influence});"
    text = replace_once(text, anchor, '              orbitPocTrace::registerObservation(eqn.receiver->observation(trans,epoch),recv,trans,epoch);\n' + anchor)
    anchor = "      auto apply=[&](Double alpha)\n      {"
    text = replace_once(text, anchor, anchor + '\n        orbitPocTrace::begin(orbitPocRowQr().artifactStem(),"apply",alpha);')
    save(name, text)
    return updates


def digest(value):
    return hashlib.sha256(value).hexdigest()


def install(tree, receipt):
    source = tree / "source"
    updates = patched_files(source)  # Validate every anchor before any write.
    header_path = Path(__file__).with_name("rowArithmeticTrace.h")
    header = header_path.read_bytes()
    destination = source / "misc/orbitPoc/rowArithmeticTrace.h"
    if destination.exists() or receipt.exists():
        raise ValueError("Diagnostic header/receipt destination already exists")
    records = {}
    for name, content in updates.items():
        path = source / name
        records[name] = {"before": digest(path.read_bytes()), "after": digest(content.encode())}
    destination.write_bytes(header)
    for name, content in updates.items():
        (source / name).write_text(content)
    records[str(destination.relative_to(source))] = {"before": None, "after": digest(header)}
    result = {"schema": "orbit-poc-diagnostic-row-trace-install-v1", "diagnostic_only": True,
              "tree": str(tree.resolve()), "installer_sha256": digest(Path(__file__).read_bytes()),
              "header_sha256": digest(header), "files": records,
              "required_equivalence": "original candidate06 versus diagnostic trace disabled versus enabled: exact factor, rows and step"}
    with receipt.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    install(args.tree, args.receipt)
