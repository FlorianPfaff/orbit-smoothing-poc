// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_FINITE_DIFFERENCE_FORCE_JACOBIAN_H
#define ORBIT_POC_FINITE_DIFFERENCE_FORCE_JACOBIAN_H
#include "syntheticForceDerivatives.h"
#include <algorithm>
#include <functional>
#include <sstream>
#include <limits>

namespace OrbitPoc
{
struct RefinedForceJacobian
{
  ForceJacobian jacobian;
  double maximumRelativeDifference=0;
  unsigned evaluations=0,maximumRefinements=0,positionFloorAppliedColumns=0,velocityFloorAppliedColumns=0;
  double maximumPositionAbsoluteDifference=0,maximumVelocityAbsoluteDifference=0;
  double maximumPositionUnflooredRelativeDifference=0,maximumVelocityUnflooredRelativeDifference=0;
  double minimumPositionStep=std::numeric_limits<double>::infinity(),maximumPositionStep=0;
  double minimumVelocityStep=std::numeric_limits<double>::infinity(),maximumVelocityStep=0;
};
// The callback is ONLY the atmospheric component, at fixed time and attitude.
// Calling it on the whole force would advance thermal history out of order.
// The callback must restore/reevaluate its nominal satellite state afterwards.
inline RefinedForceJacobian refinedForceJacobian(
    const std::function<Vec3(const Vec3 &,const Vec3 &)> &force,const Vec3 &p,const Vec3 &v,
    double positionStep=1.,double velocityStep=1e-3,double relativeTolerance=2e-3,unsigned refinements=4,
    double positionDerivativeFloor=1e-20,double velocityDerivativeFloor=1e-17)
{
  if(!(positionStep>0) || !(velocityStep>0) || !(relativeTolerance>0) || !refinements || !(positionDerivativeFloor>0) || !(velocityDerivativeFloor>0))
    throw std::runtime_error("invalid force finite-difference settings");
  RefinedForceJacobian result;
  for(unsigned column=0;column<6;column++)
  {
    const bool velocity=column>=3;const unsigned axis=column%3;
    auto difference=[&](double step)
    {
      auto plusP=p,minusP=p,plusV=v,minusV=v;
      (velocity ? plusV : plusP)[axis]+=step;(velocity ? minusV : minusP)[axis]-=step;
      const Vec3 plus=force(plusP,plusV),minus=force(minusP,minusV);
      Vec3 derivative;for(unsigned i=0;i<3;i++)derivative[i]=(plus[i]-minus[i])/(2*step);
      result.evaluations+=2;return derivative;
    };
    double step=velocity ? velocityStep : positionStep;Vec3 coarse=difference(step);bool accepted=false;
    double lastRelative=0,lastNorm=0;
    for(unsigned iteration=1;iteration<=refinements;iteration++)
    {
      step*=.5;const Vec3 fine=difference(step);Vec3 delta;
      for(unsigned i=0;i<3;i++)delta[i]=fine[i]-coarse[i];
      // A near-zero column is judged against a dimensional absolute floor.
      const double floor=velocity ? velocityDerivativeFloor : positionDerivativeFloor;
      const double relative=norm3(delta)/std::max(floor,norm3(fine));
      lastRelative=relative;lastNorm=norm3(fine);
      if(!std::isfinite(relative))throw std::runtime_error("nonfinite atmospheric force derivative");
      if(relative<=relativeTolerance)
      {
        const double absolute=norm3(delta),unfloored=absolute/std::max(1e-300,norm3(fine));
        if(velocity)
        {
          result.maximumVelocityAbsoluteDifference=std::max(result.maximumVelocityAbsoluteDifference,absolute);
          result.maximumVelocityUnflooredRelativeDifference=std::max(result.maximumVelocityUnflooredRelativeDifference,unfloored);
          result.velocityFloorAppliedColumns+=(norm3(fine)<floor);
        }
        else
        {
          result.maximumPositionAbsoluteDifference=std::max(result.maximumPositionAbsoluteDifference,absolute);
          result.maximumPositionUnflooredRelativeDifference=std::max(result.maximumPositionUnflooredRelativeDifference,unfloored);
          result.positionFloorAppliedColumns+=(norm3(fine)<floor);
        }
        for(unsigned i=0;i<3;i++)(velocity ? result.jacobian.velocity : result.jacobian.position)[3*i+axis]=(4*fine[i]-coarse[i])/3;
        if(velocity)
        {result.minimumVelocityStep=std::min(result.minimumVelocityStep,step);result.maximumVelocityStep=std::max(result.maximumVelocityStep,step);}
        else
        {result.minimumPositionStep=std::min(result.minimumPositionStep,step);result.maximumPositionStep=std::max(result.maximumPositionStep,step);}
        result.maximumRelativeDifference=std::max(result.maximumRelativeDifference,relative);
        result.maximumRefinements=std::max(result.maximumRefinements,iteration);accepted=true;break;
      }
      coarse=fine;
    }
    if(!accepted)
    {
      std::ostringstream message;message.precision(17);
      message<<"atmospheric force derivative failed step-halving refinement: column="<<column
             <<", step="<<step<<", relative_difference="<<lastRelative<<", derivative_norm="<<lastNorm;
      throw std::runtime_error(message.str());
    }
  }
  force(p,v);result.evaluations++; // Restore nominal macro geometry, including the last coordinate perturbation.
  return result;
}
}
#endif
