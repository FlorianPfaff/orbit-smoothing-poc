// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_ATMOSPHERE_EVENTS_H
#define ORBIT_POC_ATMOSPHERE_EVENTS_H
#include "base/import.h"
#include "misc/orbitPoc/eventQuadrature.h"
inline std::vector<Time> orbitPocAtmosphereEvents(const Time &start,const Time &end)
{
  // JB2008 daily lagged solar indices and HWM14 three-hour Ap steps are
  // contained in this hourly UTC grid. DTC is continuous but has hourly kinks.
  std::vector<Time> result;
  Time utc(timeGPS2UTC(start).mjdInt(),0.);
  for(;timeUTC2GPS(utc)<=end;utc+=seconds2time(3600.))
  {const Time time=timeUTC2GPS(utc);if(time>=start)result.push_back(time);}
  return result;
}
inline OrbitPoc::Quadrature orbitPocEventQuadrature(const std::vector<Time>&times,
    const std::vector<Time>&knots,const std::vector<Time>&jumps,UInt degree,std::vector<Time>*extraTimes=nullptr,Double quadratureStep=0.)
{
  std::vector<double> k,j;
  for(const auto &time:knots) k.push_back((time-times.front()).seconds());
  for(const auto &time:jumps) j.push_back((time-times.front()).seconds());
  // The canonical degree-seven attitude interpolant changes stencil at its
  // five-second support epochs. Respect these continuous-curve joins too;
  // otherwise a force polynomial would cross a derivative discontinuity.
  if(quadratureStep>0)
    for(double t=5.;t<(times.back()-times.front()).seconds();t+=5.) k.push_back(t);
  const double dt=(times.back()-times.front()).seconds()/(times.size()-1);
  std::vector<double> extras;
  const auto result=OrbitPoc::eventQuadrature(times.size(),dt,degree,k,j,extraTimes ? &extras : nullptr,quadratureStep);
  if(extraTimes)
  {extraTimes->clear();for(double t:extras)extraTimes->push_back(times.front()+seconds2time(t));}
  return result;
}
#endif
