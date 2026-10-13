#!/usr/bin/env python3
"""Export physical phase nuisance terms without altering native estimation."""
from pathlib import Path
import argparse


def _fix_phase_equation(text):
    marker="                if(phaseRecovery.is_open())"
    if marker not in text or "const GnssObservationEquation recoveryEq" in text:return text
    a=text.index(marker);b=text.index("                epoch.time = eqn.timeRecv;",a)
    block=text[a:b].replace("eqn.","recoveryEq.")
    insertion="""                  std::vector<GnssType> phaseTypes;
                  for(UInt i=0;i<obs.size();i++)
                    if(obs.at(i).type==GnssType::PHASE) phaseTypes.push_back(obs.at(i).type);
                  const GnssObservationEquation recoveryEq(obs,*recv,*state.gnss->transmitters.at(idTrans),
                      state.gnss->funcRotationCrf2Trf,state.gnss->funcReduceModels,idEpoch,FALSE,phaseTypes);
"""
    block=block.replace("                  const Vector ambiguity=",insertion+"                  const Vector ambiguity=",1)
    return text[:a]+block+text[b:]


def apply(source):
    source=Path(source)/'source'
    path=source/'gnss/gnssObservation.h';text=path.read_text()
    if 'orbitPocOriginalObservation' not in text:
        marker='  Double   observation; ///< original observations'
        assert text.count(marker)==1
        text=text.replace(marker,marker+'\n  Double orbitPocOriginalObservation=0.; ///< diagnostics only: input before preprocessing\n  Double orbitPocWindupCorrection=0.; ///< diagnostics only: removed carrier windup [m]')
        path.write_text(text)
    path=source/'gnss/gnssObservation.cpp';text=path.read_text()
    if 'orbitPocOriginalObservation' not in text:
        marker='    // phase wind-up\n'
        assert text.count(marker)==1
        text=text.replace(marker,'    for(UInt i=0;i<size();i++) at(i).orbitPocOriginalObservation=at(i).observation;\n\n'+marker,1)
        marker='        at(i).observation -= phaseWindup/(2*PI) * (at(i).type.wavelength());'
        assert text.count(marker)==1
        text=text.replace(marker,'''      {
        at(i).orbitPocWindupCorrection=phaseWindup/(2*PI)*(at(i).type.wavelength());
        at(i).observation -= at(i).orbitPocWindupCorrection;
      }''',1)
        path.write_text(text)
    path=source/'gnss/gnssProcessingStep/gnssProcessingStepWriteResiduals.h';text=path.read_text()
    if 'outputfilePhaseRecovery' in text:
        text=_fix_phase_equation(text)
        path.write_text(text)
        return
    text=text.replace('#include "config/config.h"','#include "config/config.h"\n#include <fstream>\n#include <iomanip>',1)
    text=text.replace('FileName            fileNameResiduals;','FileName            fileNameResiduals, fileNamePhaseRecovery;',1)
    marker='    readConfig(config, "outputfileResiduals", fileNameResiduals, Config::MUSTSET, "output/residuals_{loopTime:%D}.{station}.dat", "variable {station} available");'
    assert text.count(marker)==1
    text=text.replace(marker,marker+'\n    readConfig(config,"outputfilePhaseRecovery",fileNamePhaseRecovery,Config::OPTIONAL,"","diagnostic physical phase terms; no effect on estimation");',1)
    marker='        GnssReceiverArc arc;'
    assert text.count(marker)==1
    text=text.replace(marker,'''        std::ofstream phaseRecovery;
        if(!fileNamePhaseRecovery.empty())
        {
          VariableList recoveryVariables;
          recoveryVariables.setVariable("station",recv->name());
          phaseRecovery.open(fileNamePhaseRecovery(recoveryVariables).str());
          if(!phaseRecovery) throw(Exception("cannot open diagnostic phase recovery output"));
          phaseRecovery << "# GPSMJD PRN type input_m processed_m removed_windup_m fitted_ambiguity_m receiver_bias_m transmitter_bias_m STEC TEC_factor_m residual_m sigma_m clock_m track_start_GPSMJD track_end_GPSMJD\\n" << std::setprecision(17);
        }
'''+marker,1)
    marker='                epoch.time = eqn.timeRecv;'
    assert text.count(marker)==1
    text=text.replace(marker,'''                if(phaseRecovery.is_open())
                {
                  const Vector ambiguity=(eqn.track && eqn.track->ambiguity) ? eqn.track->ambiguity->ambiguities(eqn.types) : Vector(eqn.types.size());
                  const Vector biasRecv=recv->signalBias.compute(eqn.types);
                  const Vector biasTrans=eqn.A.column(GnssObservationEquation::idxUnit+eqn.types.size(),eqn.typesTransmitted.size()) * eqn.transmitter->signalBias.compute(eqn.typesTransmitted);
                  for(UInt i=0;i<eqn.types.size();i++)
                    if(eqn.types.at(i)==GnssType::PHASE)
                    {
                      const auto &single=obs.at(eqn.types.at(i));
                      phaseRecovery << recv->times.at(idEpoch).mjd() << " " << prn.prn() << " " << eqn.types.at(i).str() << " "
                        << single.orbitPocOriginalObservation << " " << single.observation << " " << single.orbitPocWindupCorrection << " "
                        << ambiguity(i) << " " << biasRecv(i) << " " << biasTrans(i) << " " << obs.STEC << " " << eqn.types.at(i).ionosphericFactor() << " "
                        << eqn.l(i) << " " << single.sigma << " " << LIGHT_VELOCITY*recv->clockError(idEpoch) << " "
                        << (eqn.track ? recv->times.at(eqn.track->idEpochStart).mjd() : 0.) << " "
                        << (eqn.track ? recv->times.at(eqn.track->idEpochEnd).mjd() : 0.) << "\\n";
                    }
                }
'''+marker,1)
    path.write_text(_fix_phase_equation(text))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('source',type=Path);apply(p.parse_args().source)
