// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SYNTHETIC_FORCE_DERIVATIVES_H
#define ORBIT_POC_SYNTHETIC_FORCE_DERIVATIVES_H
#include <array>
#include <cmath>
#include <stdexcept>

// SI, inertial Cartesian coordinates; row-major 3x3 Jacobians. These routines
// receive the constants from the actual forward-force instance, not defaults.
namespace OrbitPoc
{
using Vec3 = std::array<double,3>;
using Mat3 = std::array<double,9>;
struct ForceJacobian { Mat3 position{}, velocity{}; };
inline double norm3(const Vec3 &x) {return std::sqrt(x[0]*x[0]+x[1]*x[1]+x[2]*x[2]);}

inline ForceJacobian syntheticGravityJacobian(const Vec3 &p,double gm,double j2,double radius)
{
  const double r=norm3(p), r2=r*r;
  if(!(r>0)) throw std::runtime_error("gravity Jacobian at zero radius");
  const double central=gm/(r2*r), z2=p[2]*p[2]/r2;
  const double c=1.5*j2*gm*radius*radius/std::pow(r,5);
  ForceJacobian out;
  for(unsigned i=0;i<3;i++) for(unsigned j=0;j<3;j++)
  {
    const double q=5*z2-(i==2 ? 3. : 1.);
    const double dz2=2*p[2]*(j==2 ? 1. : 0.)/r2-2*z2*p[j]/r2;
    out.position[3*i+j]=central*(3*p[i]*p[j]/r2-(i==j ? 1. : 0.))
      +c*((i==j ? q : 0.)+p[i]*(5*dz2-5*p[j]*q/r2));
  }
  return out;
}

inline ForceJacobian syntheticDragJacobian(const Vec3 &p,const Vec3 &v,double ballistic,
    double referenceDensity,double referenceAltitude,double scaleHeight,double earthRadius,double omega)
{
  const double r=norm3(p);
  if(!(r>0) || !(scaleHeight>0)) throw std::runtime_error("invalid drag Jacobian geometry");
  const Vec3 u{v[0]+omega*p[1],v[1]-omega*p[0],v[2]};
  const double speed=norm3(u),rho=referenceDensity*std::exp(-(r-earthRadius-referenceAltitude)/scaleHeight);
  ForceJacobian out;
  if(speed==0) return out; // |u|u is differentiable at the origin, derivative zero.
  const double c=-0.5*ballistic*rho;
  const Mat3 duDr{0,omega,0,-omega,0,0,0,0,0};
  for(unsigned i=0;i<3;i++) for(unsigned j=0;j<3;j++)
    out.velocity[3*i+j]=c*((i==j ? speed : 0.)+u[i]*u[j]/speed);
  for(unsigned i=0;i<3;i++) for(unsigned j=0;j<3;j++)
  {
    out.position[3*i+j]=c*speed*u[i]*(-p[j]/(r*scaleHeight));
    for(unsigned k=0;k<3;k++) out.position[3*i+j]+=out.velocity[3*i+k]*duDr[3*k+j];
  }
  return out;
}
}
#endif
