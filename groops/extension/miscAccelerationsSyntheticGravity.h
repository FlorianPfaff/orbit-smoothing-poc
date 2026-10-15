// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SYNTHETIC_GRAVITY_H
#define ORBIT_POC_SYNTHETIC_GRAVITY_H
#ifdef DOCSTRING_MiscAccelerations
static const char *docstringMiscAccelerationsSyntheticGravity = R"(\subsection{SyntheticGravity}
Central gravity and J2 with fixed CRF z symmetry axis. Only for the controlled
Tudat simulation, whose dynamics frame deliberately differs from real EOP.)";
#endif
#include "classes/miscAccelerations/miscAccelerations.h"
class MiscAccelerationsSyntheticGravity : public MiscAccelerationsBase
{
  Double GM,J2,R;
  // Share the actual configured J2 expression with the opt-in residual path.
  // The ordinary entry retains the original scalar order and vector grouping.
  void orbitPocGravityParts(const Vector3d &p,Double &r,Vector3d &j2) const
  {
    r=p.r();
    const Double z2=p.z()*p.z()/(r*r), a=1.5*J2*GM*R*R/std::pow(r,5);
    j2=Vector3d(a*p.x()*(5*z2-1),a*p.y()*(5*z2-1),a*p.z()*(5*z2-3));
  }
public:
  explicit MiscAccelerationsSyntheticGravity(Config &config)
  {
    readConfig(config,"GM",GM,Config::DEFAULT,"3.986004418e14","m3/s2");
    readConfig(config,"J2",J2,Config::DEFAULT,"1.08262668e-3","dimensionless");
    readConfig(config,"R",R,Config::DEFAULT,"6378137","m");
  }
  Vector3d acceleration(SatelliteModelPtr,const Time &,const Vector3d &p,const Vector3d &,
      const Rotary3d &,const Rotary3d &rotEarth,EphemeridesPtr) override
  {
    Double r;Vector3d j2;orbitPocGravityParts(p,r,j2);
    return rotEarth.rotate((-GM/std::pow(r,3))*p+j2);
  }
};
#endif
