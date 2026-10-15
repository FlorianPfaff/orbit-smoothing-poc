"""Versioned coherent GNSS residual arithmetic, after all native extensions.

The Double QR matrices, native nuisance states, coefficients, physical models
and weights are unchanged. Original residual expansions survive until objective
capture; the Double QR target is rounded from that same completed expansion.
"""
from pathlib import Path
import re
import shutil

MARKER = "ORBIT_POC_PRECISE_ORIGINAL_RESIDUAL_V1"
INCLUDE = '#include "misc/orbitPoc/preciseObservationResidual.h"\n'
LEGACY_CAPTURE = "    if(orbitPocQr::enabled()) orbitPocRowQr().retainObservationResiduals(receiver->idRecv(),transmitter->idTrans(),idEpoch,l);"
PRECISE_CAPTURE = "orbitPocRowQr().retainObservationResiduals(receiver->idRecv(),transmitter->idTrans(),idEpoch,l,orbitPocPreciseL);"


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"Precise residual anchor mismatch: {old[:110]!r}")
    return text.replace(old, new, 1)


def patches(source):
    result = {}

    def read(name):
        return (source / name).read_text()

    def save(name, text):
        result[name] = "// " + MARKER + "\n" + INCLUDE + text

    name = "gnss/gnssObservation.h"
    text = read(name)
    text = once(text, "  Vector l;            ///< weighted reduced observations", "  Vector l;            ///< weighted reduced observations\n"
        "  orbitPocQr::PreciseResidualVector orbitPocPreciseL; ///< complete original weighted residual\n"
        "  Bool orbitPocPreciseInitialized=FALSE, orbitPocPreciseComplete=FALSE;\n"
        "  UInt orbitPocPreciseRevision=0; ///< explicit supported reducer updates")
    save(name, text)

    name = "gnss/gnssObservation.cpp"
    text = read(name)
    text = once(text, "    l           = Vector(obsCount);", "    l           = Vector(obsCount);\n"
        "    orbitPocPreciseInitialized=orbitPocQr::enabled();orbitPocPreciseComplete=FALSE;\n"
        "    orbitPocPreciseRevision=0;orbitPocPreciseL.clear();")
    text = once(text, "    // Corrected range\n", "    if(orbitPocPreciseInitialized)orbitPocPreciseL=orbitPocQr::liftPreciseVector(l);\n\n    // Corrected range\n")
    pattern = r"        l\(i\) = orbitPocQr::enabled\(\) \? orbitPocQr::stableRangeResidual\(([^\n]+)\) : l\(i\)-r12;"
    matches = list(re.finditer(pattern, text))
    if len(matches) != 1:
        raise ValueError("Expected the final native precise-coordinate range call")
    arguments = matches[0].group(1)
    replacement = """      {
        if(orbitPocPreciseInitialized)
        {
          orbitPocPreciseL.at(i)=orbitPocQr::stableRangeResidualExpansion(""" + arguments + """);
          l(i)=static_cast<Double>(orbitPocPreciseL.at(i).rounded());
        }
        else l(i)-=r12;
      }"""
    text = text[:matches[0].start()] + replacement + text[matches[0].end():]
    original = """    l -= receiver->antennaVariations(timeRecv, azimutRecvAnt,  elevationRecvAnt,  types);
    l -= T * transmitter->antennaVariations(timeTrans, azimutTrans, elevationTrans, typesTransmitted);
    if(track && track->ambiguity)
      l -= track->ambiguity->ambiguities(types);     // reduce ambiguities
    if(reduceModels)
      reduceModels(*this);"""
    updated = """    orbitPocQr::PreciseResidualVector receiverCorrectionPrecise,transmitterCorrectionPrecise;
    const Vector receiverCorrection=receiver->antennaVariations(timeRecv,azimutRecvAnt,elevationRecvAnt,types,
        orbitPocPreciseInitialized?&receiverCorrectionPrecise:nullptr);
    l-=receiverCorrection;
    if(orbitPocPreciseInitialized)orbitPocQr::subtractPreciseVector(orbitPocPreciseL,receiverCorrectionPrecise);
    const Vector transmitterCorrection=transmitter->antennaVariations(timeTrans,azimutTrans,elevationTrans,typesTransmitted,
        orbitPocPreciseInitialized?&transmitterCorrectionPrecise:nullptr);
    l-=T*transmitterCorrection;
    if(orbitPocPreciseInitialized)orbitPocQr::subtractPreciseVector(orbitPocPreciseL,orbitPocQr::transformPreciseVector(T,transmitterCorrectionPrecise));
    if(track && track->ambiguity)
    {
      l-=track->ambiguity->ambiguities(types);
      if(orbitPocPreciseInitialized)orbitPocQr::subtractPreciseVector(orbitPocPreciseL,track->ambiguity->orbitPocPreciseAmbiguities(types));
    }
    if(reduceModels)
    {
      const Vector before=l;const UInt revision=orbitPocPreciseRevision;
      reduceModels(*this);
      if(orbitPocPreciseInitialized && (orbitPocPreciseL.size()!=l.rows() ||
          (revision==orbitPocPreciseRevision && !orbitPocQr::sameNativeResidual(before,l))))
        throw(Exception("Observation reducer bypassed precise original residuals"));
    }"""
    text = once(text, original, updated)
    text = once(text, "        if(l.size()) l.row(i) *= 1/sigma(i);", "        if(l.size()) l.row(i) *= 1/sigma(i);\n"
        "        if(orbitPocPreciseInitialized)orbitPocPreciseL.at(i)=orbitPocPreciseL.at(i)*orbitPocQr::TwofoldGeometry(1/sigma(i));")
    boundary = "        if(B.size()) B.row(i) *= 1/sigma(i);\n      }"
    text = once(text, boundary, boundary + "\n    if(orbitPocPreciseInitialized)\n    {\n"
        "      orbitPocQr::roundPreciseResiduals(l,orbitPocPreciseL);\n"
        "      orbitPocPreciseComplete=TRUE;\n    }")
    old = LEGACY_CAPTURE
    text = once(text, old, "    if(orbitPocQr::enabled())\n    {\n"
        "      orbitPocQr::validatePreciseResiduals(l,orbitPocPreciseL,orbitPocPreciseInitialized,orbitPocPreciseComplete);\n"
        "      orbitPocRowQr().retainObservationResiduals(receiver->idRecv(),transmitter->idTrans(),idEpoch,l,orbitPocPreciseL);\n    }")
    save(name, text)

    name = "gnss/gnssTransceiver.h"
    text = read(name)
    old = "  Vector antennaVariations(const Time &time, Angle azimut, Angle elevation, const std::vector<GnssType> &type) const;"
    text = once(text, old, "  Vector antennaVariations(const Time &time, Angle azimut, Angle elevation, const std::vector<GnssType> &type,\n      orbitPocQr::PreciseResidualVector *precise=nullptr) const;")
    old = "inline Vector GnssTransceiver::antennaVariations(const Time &time, Angle azimut, Angle elevation, const std::vector<GnssType> &types) const"
    text = once(text, old, old.replace(") const", ", orbitPocQr::PreciseResidualVector *precise) const"))
    text = once(text, "    corr += signalBias.compute(types);", "    const Vector bias=signalBias.compute(types);\n    corr += bias;\n    if(precise)*precise=orbitPocQr::liftPreciseVector(bias);")
    old = "    corr += antenna->antennaDef->antennaVariations(azimut, elevation, types, noPatternFoundAction);"
    text = once(text, old, "    const Vector pattern=antenna->antennaDef->antennaVariations(azimut,elevation,types,noPatternFoundAction);\n"
        "    corr+=pattern;\n    if(precise)\n    {\n      if(precise->size()!=pattern.rows())throw(Exception(\"Precise antenna dimension mismatch\"));\n"
        "      for(UInt i=0;i<pattern.rows();i++)precise->at(i)=precise->at(i)+orbitPocQr::TwofoldGeometry(pattern(i));\n    }")
    save(name, text)

    name = "gnss/gnssReceiver.h"
    text = read(name)
    old = "  virtual Vector ambiguities(const std::vector<GnssType> &type) const = 0;"
    text = once(text, old, old + "\n  virtual orbitPocQr::PreciseResidualVector orbitPocPreciseAmbiguities(const std::vector<GnssType> &/*type*/) const\n"
        "  {throw(Exception(\"Unsupported ambiguity implementation for precise original residuals\"));}")
    save(name, text)

    name = "gnss/gnssReceiver.cpp"
    text = read(name)
    old = "      Vector ambiguities(const std::vector<GnssType> &types) const override\n      {"
    text = once(text, old, "      orbitPocQr::PreciseResidualVector orbitPocPreciseAmbiguities(const std::vector<GnssType> &types) const override\n"
        "      {return orbitPocQr::liftPreciseVector(ambiguities(types));}\n\n" + old)
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationAmbiguities.h"
    text = read(name)
    old = "    Vector ambiguities(const std::vector<GnssType> &types) const override;"
    text = once(text, old, old + "\n    orbitPocQr::PreciseResidualVector orbitPocPreciseAmbiguities(const std::vector<GnssType> &types) const override;")
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp"
    text = read(name)
    text += """
// Original native coefficients T [cycles -> metres], accumulated without narrowing.
orbitPocQr::PreciseResidualVector GnssParametrizationAmbiguities::Ambiguity::orbitPocPreciseAmbiguities(const std::vector<GnssType> &types) const
{
  orbitPocQr::PreciseResidualVector result(types.size());UInt idx;
  if(this->value.size())
    for(UInt idType=0;idType<types.size();idType++)
      if(types.at(idType).isInList(this->types,idx))
      {
        if(T.columns()!=this->value.rows())throw(Exception("Precise ambiguity dimension mismatch"));
        for(UInt j=0;j<T.columns();j++)result[idType]=result[idType]+
            orbitPocQr::TwofoldGeometry(T(idx,j))*orbitPocQr::TwofoldGeometry(this->value(j));
      }
  return result;
}
"""
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp"
    text = read(name)
    terms = [
        ("apply1stOrder", "-Ionosphere::Ap/f2", "-Ionosphere::Ap/f2 * STEC", 1),
        ("apply2ndOrder", "-s/2/f3", "-s/2/f3 * STEC", 1),
        ("apply3rdOrder", "-r/3/f4", "-r/3/f4 * std::pow(STEC, 2)", 2),
        ("applyBending", "bending/f4", "bending/f4*std::pow(STEC, 2)", 2),
        ("apply1stOrder", "Ionosphere::Ap/f2", "Ionosphere::Ap/f2 * STEC", 1),
        ("apply2ndOrder", "s/f3", "s/f3  * STEC", 1),
        ("apply3rdOrder", "r/f4", "r/f4 * std::pow(STEC, 2)", 2),
    ]
    for flag, coefficient, expression, power in terms:
        pattern = r"(?P<line>        if\(" + flag + r"\) +eqn\.l\(i\) +-= +" + re.escape(expression) + r";[^\n]*)"
        matches = list(re.finditer(pattern, text))
        if len(matches) != 1:
            raise ValueError(f"Precise STEC anchor mismatch: {expression}")
        match = matches[0]
        text = text[:match.end()] + f"\n        if({flag} && eqn.orbitPocPreciseInitialized)orbitPocQr::subtractPreciseStec(eqn.orbitPocPreciseL,i,{coefficient},STEC,{power});" + text[match.end():]
    old = "      eqn.l(eqn.l.rows()-1)    = -eqn.dSTEC/eqn.sigmaSTEC; // constrain towards zero (0-f(x0))"
    text = once(text, old, old + "\n      if(eqn.orbitPocPreciseInitialized)\n      {\n"
        "        if(eqn.orbitPocPreciseL.size()+1!=eqn.l.rows())throw(Exception(\"Missing precise STEC prior row\"));\n"
        "        eqn.orbitPocPreciseL.push_back(-orbitPocQr::TwofoldGeometry(eqn.dSTEC)/orbitPocQr::TwofoldGeometry(eqn.sigmaSTEC));\n      }")
    boundary = "      eqn.B(eqn.B.rows()-1, 0) =  1./eqn.sigmaSTEC;        // in TECU\n    }"
    text = once(text, boundary, boundary + "\n    if(eqn.orbitPocPreciseInitialized)eqn.orbitPocPreciseRevision++;")
    save(name, text)

    name = "gnss/gnssParametrization/gnssParametrization.cpp"
    text = read(name)
    old = "    for(auto b : base)\n      b->observationCorrections(eqn);"
    text = once(text, old, "    for(auto b : base)\n    {\n"
        "      const Vector before=eqn.l;const UInt revision=eqn.orbitPocPreciseRevision;\n"
        "      b->observationCorrections(eqn);\n"
        "      if(eqn.orbitPocPreciseInitialized && (eqn.orbitPocPreciseL.size()!=eqn.l.rows() ||\n"
        "          (revision==eqn.orbitPocPreciseRevision && !orbitPocQr::sameNativeResidual(before,eqn.l))))\n"
        "        throw(Exception(\"Parametrization reducer bypassed precise original residuals\"));\n    }")
    save(name, text)

    for reducer in ["TemporalBias", "Troposphere"]:
        name = f"gnss/gnssParametrization/gnssParametrization{reducer}.cpp"
        text = read(name)
        signature = f"void GnssParametrization{reducer}::observationCorrections(GnssObservationEquation &eqn) const"
        start = text.index(signature)
        end = text.index("\n}\n",start)+3
        before, body, after = text[:start], text[start:end], text[end:]
        anchor = "    auto para = parameters.at(eqn.transmitter->idTrans());" if reducer == "TemporalBias" else "    auto para = parameters.at(eqn.receiver->idRecv());"
        body = once(body, anchor, anchor + f'\n    if(para && eqn.orbitPocPreciseInitialized)throw(Exception("{reducer} is unsupported by precise original GNSS residuals"));')
        save(name, before + body + after)
    return result


def apply(root):
    source = Path(root) / "source"
    targets = ["gnss/gnssObservation.h", "gnss/gnssObservation.cpp", "gnss/gnssTransceiver.h",
               "gnss/gnssReceiver.h", "gnss/gnssReceiver.cpp",
               "gnss/gnssParametrization/gnssParametrizationAmbiguities.h",
               "gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp",
               "gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp",
               "gnss/gnssParametrization/gnssParametrization.cpp",
               "gnss/gnssParametrization/gnssParametrizationTemporalBias.cpp",
               "gnss/gnssParametrization/gnssParametrizationTroposphere.cpp"]
    installed = [MARKER in (source / name).read_text() for name in targets]
    header = Path(__file__).with_name("preciseObservationResidual.h")
    destination = source / "misc/orbitPoc/preciseObservationResidual.h"
    if all(installed):
        if not destination.is_file() or destination.read_bytes()!=header.read_bytes():
            raise ValueError("Precise residual header changed after installation")
        # The preceding row installer recognizes only its original four-argument
        # hook and may reinsert it when the complete extension is applied again.
        observation=source/"gnss/gnssObservation.cpp"
        text=observation.read_text()
        if text.count(PRECISE_CAPTURE)!=1 or text.count(LEGACY_CAPTURE)>1:
            raise ValueError("Installed precise residual capture changed")
        if LEGACY_CAPTURE in text:
            observation.write_text(text.replace(LEGACY_CAPTURE+"\n","",1))
        return
    if any(installed):
        raise ValueError("Partially installed precise original residual extension")
    if "stableRangeResidualExpansion" not in (source / "misc/orbitPoc/gnssRangeResidual.h").read_text():
        raise ValueError("Precise original residual requires the expansion-return range API")
    updates = patches(source)  # Validate every anchor before writing.
    shutil.copyfile(header, destination)
    for name, content in updates.items():
        (source / name).write_text(content)


if __name__ == "__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    apply(parser.parse_args().root)
