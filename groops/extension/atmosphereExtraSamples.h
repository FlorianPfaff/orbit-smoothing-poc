// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_ATMOSPHERE_EXTRA_SAMPLES_H
#define ORBIT_POC_ATMOSPHERE_EXTRA_SAMPLES_H
#include "files/fileVariationalEquation.h"
#include "misc/orbitPoc/piecewisePolynomial.h"

// Interpolate smooth reference geometry, never force values across a model
// event. Callers reevaluate the unchanged native atmosphere and its density
// derivative at these genuine auxiliary quadrature epochs.
inline VariationalEquationArc orbitPocAtmosphereExtraSamples(
    const VariationalEquationArc &arc,const std::vector<Time> &queries,
    const std::vector<Time> &boundaries,const std::vector<Time> &pulses)
{
  VariationalEquationArc result;result.times=queries;
  if(queries.empty()) return result;
  OrbitPocPiecewisePolynomial state(arc.times,7,boundaries,pulses);
  result.pos0=state.interpolate(queries,arc.pos0,3);
  result.vel0=state.interpolate(queries,arc.vel0,3,TRUE);
  if(arc.PosState.columns()) result.PosState=state.interpolate(queries,arc.PosState,3);
  if(arc.VelState.columns()) result.VelState=state.interpolate(queries,arc.VelState,3,TRUE);
  Matrix earth(3*arc.times.size(),3);
  std::vector<Time> attitudeTimes;std::vector<UInt> attitudeIndices;
  for(UInt i=0;i<arc.times.size();i++)
  {
    copy(arc.rotEarth.at(i).matrix(),earth.row(3*i,3));
    const double elapsed=(arc.times.at(i)-arc.times.front()).seconds();
    if(std::abs(elapsed-5.*std::round(elapsed/5.))<2e-7)
    {attitudeTimes.push_back(arc.times.at(i));attitudeIndices.push_back(i);}
  }
  // The declared attitude curve is the original five-second known support,
  // independently of the state grid being refined. No averaging is applied.
  if(attitudeTimes.size()<8) throw(Exception("canonical atmospheric attitude requires eight five-second support epochs"));
  StarCameraArc canonicalAttitude;
  for(UInt i=0;i<attitudeTimes.size();i++)
  {
    StarCameraEpoch epoch;epoch.time=attitudeTimes.at(i);
    epoch.rotary=arc.rotSat.at(attitudeIndices.at(i));canonicalAttitude.push_back(epoch);
  }
  // Reuse upstream semantics: Arc::matrix unwraps quaternion signs before
  // interpolation, and StarCameraEpoch::setData normalizes afterward.
  const Matrix quaternions=canonicalAttitude.matrix().column(1,4);
  Polynomial earthPolynomial(arc.times,7,TRUE,FALSE,-8.1,-1.1,1e-7);
  Polynomial attitude(attitudeTimes,7,TRUE,FALSE,-8.1,-1.1,1e-7);
  const Matrix e=earthPolynomial.interpolate(queries,earth,3),s=attitude.interpolate(queries,quaternions);
  for(UInt i=0;i<queries.size();i++)
  {
    StarCameraEpoch epoch;epoch.setData(Vector(s.row(i,1).trans()));
    result.rotEarth.emplace_back(e.row(3*i,3));result.rotSat.push_back(epoch.rotary);
  }
  return result;
}
#endif
