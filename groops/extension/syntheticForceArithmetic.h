// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SYNTHETIC_FORCE_ARITHMETIC_H
#define ORBIT_POC_SYNTHETIC_FORCE_ARITHMETIC_H
#include <array>
#include <cmath>
#include <stdexcept>

namespace OrbitPoc
{
using ForceTriple = std::array<long double,3>;
// Filled only by the actual configured synthetic force instances. Full force
// and noncentral force stay separate until reference gravity is subtracted.
struct SyntheticForceParts
{
  long double centralGM=0;
  ForceTriple full{},noncentral{};
  void add(const SyntheticForceParts &other)
  {
    centralGM+=other.centralGM;
    for(unsigned i=0;i<3;i++){full[i]+=other.full[i];noncentral[i]+=other.noncentral[i];}
  }
  void scale(long double multiplier)
  {
    centralGM*=multiplier;
    for(unsigned i=0;i<3;i++){full[i]*=multiplier;noncentral[i]*=multiplier;}
  }
  void validate() const
  {
    if(!std::isfinite(centralGM))throw std::runtime_error("non-finite configured synthetic central GM");
    for(unsigned i=0;i<3;i++)if(!std::isfinite(full[i])||!std::isfinite(noncentral[i]))
      throw std::runtime_error("non-finite configured synthetic acceleration");
  }
};

// Algebraically a_c(position; actual GM)-a_c(reference; reference GM), plus
// the configured J2/drag/etc. No assumption that the two GMs are equal.
inline ForceTriple syntheticReferenceResidual(const SyntheticForceParts &parts,
    const std::array<double,3> &position,const std::array<double,3> &reference,double referenceGM)
{
  parts.validate();
  if(!std::isfinite(referenceGM)||!(referenceGM>0))
    throw std::runtime_error("invalid synthetic reference GM");
  ForceTriple delta{};long double radius2=0,numerator=0;
  for(unsigned i=0;i<3;i++)
  {
    if(!std::isfinite(position[i])||!std::isfinite(reference[i]))
      throw std::runtime_error("non-finite synthetic reference geometry");
    delta[i]=static_cast<long double>(position[i])-reference[i];
    radius2+=static_cast<long double>(reference[i])*reference[i];
    numerator+=delta[i]*(2.L*reference[i]+delta[i]);
  }
  if(!(radius2>0)||!std::isfinite(radius2))throw std::runtime_error("invalid synthetic reference radius");
  const long double q=numerator/radius2;
  if(!(q>-1)||!std::isfinite(q))throw std::runtime_error("invalid synthetic residual radius ratio");
  const long double f=std::expm1(-1.5L*std::log1p(q));
  const long double inverseCube=1.L/(radius2*std::sqrt(radius2));
  ForceTriple result{};
  for(unsigned i=0;i<3;i++)
  {
    result[i]=(-parts.centralGM*(delta[i]+f*position[i])
       +(static_cast<long double>(referenceGM)-parts.centralGM)*reference[i])*inverseCube
       +parts.noncentral[i];
    if(!std::isfinite(result[i]))throw std::runtime_error("non-finite synthetic reference residual");
  }
  return result;
}
}
#endif
