// SPDX-License-Identifier: GPL-3.0-or-later
// Preserve the fitted model's continuous position and right-continuous pulse
// velocity when supplying native receiver geometry at observation epochs.
#include "programs/program.h"
#include "files/fileInstrument.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/parametrizationAcceleration/parametrizationAcceleration.h"
#include "misc/orbitPoc/piecewisePolynomial.h"

class OrbitPocResampleOrbit
{
public:
  void run(Config &config, Parallel::CommunicatorPtr comm);
};
GROOPS_REGISTER_PROGRAM(OrbitPocResampleOrbit,SINGLEPROCESS,
                       "Sample a fitted orbit at native receiver epochs without crossing model knots",Orbit)

void OrbitPocResampleOrbit::run(Config &config, Parallel::CommunicatorPtr)
{
  try
  {
    FileName input, output;
    TimeSeriesPtr queries, pulseSeries, boundarySeries;
    ParametrizationAccelerationPtr acceleration;
    UInt degree;
    readConfig(config,"inputfileOrbit",input,Config::MUSTSET,"","full fitted native Cartesian orbit");
    readConfig(config,"outputfileOrbit",output,Config::MUSTSET,"","position and velocity at exact query epochs");
    readConfig(config,"timeSeries",queries,Config::MUSTSET,"","retained or withheld native observation epochs");
    readConfig(config,"parametrizationAcceleration",acceleration,Config::DEFAULT,"","fitted acceleration model supplies continuous knots");
    readConfig(config,"stochasticPulse",pulseSeries,Config::OPTIONAL,"","fitted impulse epochs");
    readConfig(config,"interpolationBoundaries",boundarySeries,Config::OPTIONAL,"","additional continuous interpolation boundaries");
    readConfig(config,"interpolationDegree",degree,Config::DEFAULT,"7","same degree as fitted native model");
    if(isCreateSchema(config)) return;
    const OrbitArc orbit=InstrumentFile::read(input);
    const auto times=orbit.times(), timesNew=queries->times();
    if(times.empty() || timesNew.empty()) throw(Exception("orbit and query epochs must not be empty"));
    for(const auto &time:timesNew)
      if(time<times.front() || time>times.back())
        throw(Exception("receiver geometry query lies outside the fitted orbit"));
    auto boundaries=acceleration->integrationBoundaries();
    if(boundarySeries)
    {
      const auto extra=boundarySeries->times();
      boundaries.insert(boundaries.end(),extra.begin(),extra.end());
    }
    const auto pulses=pulseSeries ? pulseSeries->times() : std::vector<Time>();
    const OrbitPocPiecewisePolynomial interpolation(times,degree,boundaries,pulses);
    Matrix position(3*orbit.size(),1), velocity(3*orbit.size(),1);
    for(UInt i=0;i<orbit.size();i++)
    {
      copy(orbit.at(i).position.vector(),position.row(3*i,3));
      copy(orbit.at(i).velocity.vector(),velocity.row(3*i,3));
    }
    position=interpolation.interpolate(timesNew,position,3,FALSE);
    velocity=interpolation.interpolate(timesNew,velocity,3,TRUE);
    OrbitArc result;
    for(UInt i=0;i<timesNew.size();i++)
    {
      OrbitEpoch epoch; epoch.time=timesNew.at(i);
      epoch.position=Vector3d(position.row(3*i,3));
      epoch.velocity=Vector3d(velocity.row(3*i,3));
      result.push_back(epoch);
    }
    InstrumentFile::write(output,result);
    logInfo<<"Receiver orbit sampled at "<<result.size()<<" exact observation epochs"<<Log::endl;
  }
  catch(std::exception &error) { GROOPS_RETHROW(error) }
}
