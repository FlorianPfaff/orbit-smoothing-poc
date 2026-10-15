// SPDX-License-Identifier: GPL-3.0-or-later
// Numerical refinement only: compare complete native code/phase equations at
// identical fixed nuisance values. Unknown phase ambiguities cancel in paired
// differences; these rows are never interpreted as validation residual scores.
#include "programs/program.h"
#include <fstream>
#include <iomanip>
#include "files/fileMatrix.h"
#include "files/fileInstrument.h"
#include "misc/orbitPoc/piecewisePolynomial.h"
#include "misc/orbitPoc/logDensitySeries.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/earthRotation/earthRotation.h"
#include "gnss/gnss.h"
#include "gnss/gnssObservation.h"
#include "gnss/gnssTransmitterGenerator/gnssTransmitterGenerator.h"
#include "gnss/gnssReceiverGenerator/gnssReceiverGenerator.h"

class OrbitPocPredictSignals
{
public:
  void run(Config &config,Parallel::CommunicatorPtr comm);
};
GROOPS_REGISTER_PROGRAM(OrbitPocPredictSignals,SINGLEPROCESS,"Numerical refinement of native dual-frequency code and carrier predictions",Gnss)

void OrbitPocPredictSignals::run(Config &config,Parallel::CommunicatorPtr comm)
{
  try
  {
    FileName output,supportFile,receiverOrbit,densityKnots;TimeSeriesPtr series,pulseSeries;Double margin;UInt interpolationDegree;
    std::vector<Double> fixedClockOffsets;
    GnssTransmitterGeneratorPtr transmitters;GnssReceiverGeneratorPtr receivers;
    GnssParametrizationPtr parameters;EarthRotationPtr rotation;
    readConfig(config,"outputfilePredictions",output,Config::MUSTSET,"","MJD, PRN, frequency Hz, phase flag, residual m, sigma m, receiver clock s, STEC");
    readConfig(config,"outputfileSupport",supportFile,Config::MUSTSET,"","exact signal identities for paired numerical comparisons");
    readConfig(config,"timeSeries",series,Config::MUSTSET,"","receive epochs");
    readConfig(config,"timeMargin",margin,Config::DEFAULT,"0.1","seconds");
    readConfig(config,"fixedReceiverClockOffsetSeconds",fixedClockOffsets,Config::OPTIONAL,"",
               "optional fixed offsets cycled across epochs for numerical interpolation checks only; no fitting");
    readConfig(config,"inputfileReceiverOrbit",receiverOrbit,Config::OPTIONAL,"","full closed CRF orbit for clock-corrected receiver cache refresh");
    readConfig(config,"inputfileDensityKnots",densityKnots,Config::OPTIONAL,"","same fixed density-knot boundaries as the numerical estimator");
    readConfig(config,"stochasticPulse",pulseSeries,Config::OPTIONAL,"","same fixed pulse boundaries as the numerical estimator");
    readConfig(config,"interpolationDegree",interpolationDegree,Config::DEFAULT,"7","same piecewise interpolation degree as the numerical estimator");
    readConfig(config,"transmitter",transmitters,Config::MUSTSET,"","same precise products");
    readConfig(config,"receiver",receivers,Config::MUSTSET,"","same observations and supplied physical trajectory");
    readConfig(config,"earthRotation",rotation,Config::MUSTSET,"","same EOP");
    readConfig(config,"parametrization",parameters,Config::DEFAULT,"","fixed apriori corrections only; no estimation");
    if(isCreateSchema(config))return;
    Gnss gnss;gnss.init({},series->times(),seconds2time(margin),transmitters,receivers,rotation,parameters,comm);
    if(gnss.receivers.size()!=1)throw(Exception("signal refinement needs exactly one receiver"));
    const auto recv=gnss.receivers.front();std::vector<Vector> rows;std::vector<std::string> support;
    for(const Double value:fixedClockOffsets)
      if(!std::isfinite(value) || std::abs(value)>1e-3)
        throw(Exception("signal-refinement clock offsets must be finite and at most one millisecond"));
    if(!fixedClockOffsets.empty())
    {
      if(receiverOrbit.empty())throw(Exception("nonzero fixed clocks require the full receiver orbit for cache refresh"));
      for(UInt epoch=0;epoch<gnss.times.size();epoch++)recv->clk.at(epoch)=fixedClockOffsets.at(epoch%fixedClockOffsets.size());
    }
    if(!receiverOrbit.empty())
    {
      // Mirror LeoDynamicOrbits::updateParameter's zero-coordinate update:
      // clocks change receive times, so its cached marker state must be rebuilt.
      // Use the same native interpolation class, degree, knots and pulse sides.
      const OrbitArc orbit=InstrumentFile::read(receiverOrbit);
      std::vector<Time> times,queries,boundaries,pulses;
      std::vector<long double> queryRemainders;
      Matrix position(3*orbit.size(),1),velocity(3*orbit.size(),1);
      for(UInt i=0;i<orbit.size();i++)
      {
        times.push_back(orbit.at(i).time);
        copy(orbit.at(i).position.vector(),position.row(3*i,3));
        copy(orbit.at(i).velocity.vector(),velocity.row(3*i,3));
      }
      if(!densityKnots.empty())boundaries=LogDensitySeries(densityKnots).times;
      if(pulseSeries)pulses=pulseSeries->times();
      OrbitPocPiecewisePolynomial polynomial(times,interpolationDegree,boundaries,pulses);
      for(UInt epoch=0;epoch<gnss.times.size();epoch++)
        if(recv->useable(epoch))
        {
          queries.push_back(recv->timeCorrected(epoch));
          queryRemainders.push_back(recv->timeRemainder(epoch));
        }
      std::vector<long double> coordinateLow;
      const Matrix interpolatedPosition=polynomial.interpolateOffset(queries,position,queryRemainders,3,FALSE,nullptr,&coordinateLow);
      const Matrix interpolatedVelocity=polynomial.interpolateOffset(queries,velocity,queryRemainders,3,TRUE);
      if(coordinateLow.size()!=3*queries.size())throw(Exception("signal refinement precise receiver state shape mismatch"));
      recv->orbitPocPositionRemainder.resize(recv->times.size());
      UInt index=0;Double maximumChange=0;
      for(UInt epoch=0;epoch<gnss.times.size();epoch++)if(recv->useable(epoch))
      {
        const Vector3d p(interpolatedPosition.row(3*index,3));
        maximumChange=std::max(maximumChange,(p-recv->pos.at(epoch)).r());
        recv->orbitPocPositionRemainder.at(epoch)=Vector3d(
            static_cast<Double>(coordinateLow.at(3*index)),
            static_cast<Double>(coordinateLow.at(3*index+1)),
            static_cast<Double>(coordinateLow.at(3*index+2)));
        recv->pos.at(epoch)=p;recv->vel.at(epoch)=Vector3d(interpolatedVelocity.row(3*index,3));index++;
      }
      logInfo<<"Fixed-clock receiver cache refreshed with native piecewise interpolation; maximum change "<<maximumChange<<" m"<<Log::endl;
    }
    for(UInt epoch=0;epoch<gnss.times.size();epoch++)
    {
      if(!recv->useable(epoch))continue;
      for(UInt trans=0;trans<recv->idTransmitterSize(epoch);trans++)
      {
        auto obs=recv->observation(trans,epoch);
        if(!obs || !gnss.transmitters.at(trans)->useable(epoch))continue;
        if(obs->track)throw(Exception("signal refinement must not use fitted ambiguity tracks"));
        std::vector<GnssType> types;obs->observationList(GnssObservation::RANGE | GnssObservation::PHASE,types);
        GnssObservationEquation eqn(*obs,*recv,*gnss.transmitters.at(trans),gnss.funcRotationCrf2Trf,
                                    gnss.funcReduceModels,epoch,FALSE,types);
        for(UInt i=0;i<eqn.types.size();i++)
        {
          const auto type=eqn.types.at(i);
          if(type!=GnssType::GPS || (type!=GnssType::L1 && type!=GnssType::L2) ||
             (type!=GnssType::RANGE && type!=GnssType::PHASE))continue;
          Vector row(8);row(0)=gnss.times.at(epoch).mjd();row(1)=type.prn();row(2)=type.frequency();
          row(3)=type==GnssType::PHASE ? 1 : 0;row(4)=eqn.l(i);row(5)=eqn.sigma0(i);
          row(6)=recv->clockError(epoch);row(7)=obs->STEC;
          if(!std::isfinite(row(4)) || !(row(5)>0))throw(Exception("invalid native signal refinement row"));
          rows.push_back(row);support.push_back(type.str());
        }
      }
    }
    if(rows.empty())throw(Exception("no native dual-frequency signal refinement rows"));
    Matrix result(rows.size(),8);
    for(UInt i=0;i<rows.size();i++)for(UInt j=0;j<8;j++)result(i,j)=rows[i](j);
    writeFileMatrix(output,result);
    std::ofstream audit(supportFile.str());if(!audit)throw(Exception("cannot write signal refinement support"));
    audit<<"# GPSMJD PRN signal\n"<<std::setprecision(17);
    for(UInt i=0;i<rows.size();i++)audit<<rows[i](0)<<" "<<rows[i](1)<<" "<<support[i]<<"\n";
    if(!audit)throw(Exception("signal refinement support write failed"));
  }
  catch(std::exception &e){GROOPS_RETHROW(e)}
}
