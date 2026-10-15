// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_PRECISE_EQUINOCTIAL_REFERENCE_H
#define ORBIT_POC_PRECISE_EQUINOCTIAL_REFERENCE_H
#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include "syntheticForceArithmetic.h"

namespace OrbitPoc
{
// These are the existing fitted elements, not a second orbit fit. Keep l0 and
// elapsed time extended precision; the native element fields are otherwise
// doubles. This helper changes only evaluation of the Enke reference.
struct PreciseEquinoctialElements
{
  long double GM,a,h,k,p,q,l0;
};
struct PreciseReferenceState
{
  ForceTriple position{},velocity{},acceleration{};
};

inline double preciseReferenceMeanResidual(double high,long double low,double approximate,long double integral)
{
  return static_cast<double>((static_cast<long double>(high)-approximate)+low+integral);
}

inline PreciseReferenceState preciseEquinoctialReference(
    const PreciseEquinoctialElements &e,long double elapsedSeconds)
{
  static_assert(std::numeric_limits<long double>::digits>53,
                "Synthetic reference precision requires extended long double");
  for(const auto value:{e.GM,e.a,e.h,e.k,e.p,e.q,e.l0,elapsedSeconds})
    if(!std::isfinite(value))throw std::runtime_error("Nonfinite equinoctial reference input");
  const long double eccentricity2=e.h*e.h+e.k*e.k;
  if(!(e.GM>0 && e.a>0 && eccentricity2<1))
    throw std::runtime_error("Synthetic reference requires a finite elliptic orbit");
  const long double n=std::sqrt(e.GM/(e.a*e.a*e.a));
  const long double twoPi=2.L*std::acos(-1.L);
  long double lambda=std::fmod(e.l0+n*elapsedSeconds,twoPi);
  if(lambda<0)lambda+=twoPi;
  long double F=lambda;
  bool closed=false;
  for(unsigned iteration=0;iteration<100;iteration++)
  {
    const long double sine=std::sin(F),cosine=std::cos(F);
    const long double residual=(F-lambda)-e.k*sine+e.h*cosine;
    const long double correction=residual/(1.L-e.k*cosine-e.h*sine);
    const long double next=F-correction;
    if(!std::isfinite(next))throw std::runtime_error("Nonfinite eccentric-longitude iterate");
    if(next==F || std::fabs(correction)<=4.L*std::numeric_limits<long double>::epsilon()*std::max(1.L,std::fabs(F)))
    {F=next;closed=true;break;}
    F=next;
  }
  if(!closed)throw std::runtime_error("Precise eccentric longitude failed to close");
  const long double sine=std::sin(F),cosine=std::cos(F);
  const long double beta=1.L/(1.L+std::sqrt(1.L-eccentricity2));
  const long double radius=e.a*(1.L-e.h*sine-e.k*cosine);
  const long double X=e.a*((1.L-e.h*e.h*beta)*cosine+e.h*e.k*beta*sine-e.k);
  const long double Y=e.a*((1.L-e.k*e.k*beta)*sine+e.h*e.k*beta*cosine-e.h);
  const long double velocityScale=std::sqrt(e.GM*e.a)/radius;
  const long double XD=velocityScale*(e.h*e.k*beta*cosine-(1.L-e.h*e.h*beta)*sine);
  const long double YD=velocityScale*(-e.h*e.k*beta*sine+(1.L-e.k*e.k*beta)*cosine);
  const long double alpha=1.L/(1.L+e.p*e.p+e.q*e.q);
  const ForceTriple f={alpha*(1.L-e.p*e.p+e.q*e.q),alpha*2.L*e.p*e.q,-alpha*2.L*e.p};
  const ForceTriple g={alpha*2.L*e.p*e.q,alpha*(1.L+e.p*e.p-e.q*e.q),alpha*2.L*e.q};
  PreciseReferenceState result;
  for(unsigned axis=0;axis<3;axis++)
  {
    result.position[axis]=X*f[axis]+Y*g[axis];
    result.velocity[axis]=XD*f[axis]+YD*g[axis];
    result.acceleration[axis]=-e.GM/(radius*radius*radius)*result.position[axis];
  }
  return result;
}

// Match syntheticReferenceResidual's algebra while retaining the sub-double
// part of the reference coordinates. Rounding the reference before force
// subtraction would reintroduce a different reference acceleration.
inline ForceTriple preciseSyntheticReferenceResidual(const SyntheticForceParts &parts,
    const std::array<double,3> &position,const ForceTriple &reference,double referenceGM)
{
  parts.validate();
  if(!(std::isfinite(referenceGM)&&referenceGM>0))throw std::runtime_error("Invalid precise reference GM");
  ForceTriple delta{};long double radius2=0,numerator=0;
  for(unsigned axis=0;axis<3;axis++)
  {
    if(!std::isfinite(position[axis])||!std::isfinite(reference[axis]))throw std::runtime_error("Nonfinite precise reference geometry");
    delta[axis]=static_cast<long double>(position[axis])-reference[axis];
    radius2+=reference[axis]*reference[axis];
    numerator+=delta[axis]*(2.L*reference[axis]+delta[axis]);
  }
  if(!(radius2>0))throw std::runtime_error("Invalid precise reference radius");
  const long double q=numerator/radius2;
  if(!(q>-1))throw std::runtime_error("Invalid precise reference radius ratio");
  const long double f=std::expm1(-1.5L*std::log1p(q));
  const long double inverseCube=1.L/(radius2*std::sqrt(radius2));
  ForceTriple result{};
  for(unsigned axis=0;axis<3;axis++)
  {
    result[axis]=(-parts.centralGM*(delta[axis]+f*position[axis])
        +(static_cast<long double>(referenceGM)-parts.centralGM)*reference[axis])*inverseCube
        +parts.noncentral[axis];
    if(!std::isfinite(result[axis]))throw std::runtime_error("Nonfinite precise reference residual");
  }
  return result;
}
}
#endif
