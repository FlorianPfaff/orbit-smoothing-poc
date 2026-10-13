// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SYNTHETIC_DRAG_H
#define ORBIT_POC_SYNTHETIC_DRAG_H
#ifdef DOCSTRING_MiscAccelerations
static const char *docstringMiscAccelerationsSyntheticDrag = R"(\subsection{SyntheticDrag}
Controlled spherical exponential atmosphere, corotating about the CRF z axis.
Intended only for independent Tudat closed-loop verification.)";
#endif
#include "classes/miscAccelerations/miscAccelerations.h"
class MiscAccelerationsSyntheticDrag : public MiscAccelerationsBase
{
  Double ballisticCoefficient,referenceDensity,referenceAltitude,scaleHeight,earthRadius,earthRotationRate;
public:
  explicit MiscAccelerationsSyntheticDrag(Config &config)
  {
    readConfig(config,"ballisticCoefficient",ballisticCoefficient,Config::DEFAULT,"0.022","Cd A / mass in m2/kg");
    readConfig(config,"referenceDensity",referenceDensity,Config::DEFAULT,"5e-13","kg/m3");
    readConfig(config,"referenceAltitude",referenceAltitude,Config::DEFAULT,"500000","m");
    readConfig(config,"scaleHeight",scaleHeight,Config::DEFAULT,"60000","m");
    readConfig(config,"earthRadius",earthRadius,Config::DEFAULT,"6378137","m");
    readConfig(config,"earthRotationRate",earthRotationRate,Config::DEFAULT,"7.2921150e-5","rad/s about CRFz");
    if(!isCreateSchema(config) && (ballisticCoefficient<=0 || referenceDensity<=0 || scaleHeight<=0 || earthRadius<=0))
      throw(Exception("invalid controlled drag constants"));
  }
  Vector3d acceleration(SatelliteModelPtr,const Time &,const Vector3d &position,const Vector3d &velocity,
      const Rotary3d &,const Rotary3d &rotEarth,EphemeridesPtr) override
  {
    const Vector3d relative=velocity-Vector3d(-earthRotationRate*position.y(),earthRotationRate*position.x(),0.);
    const Double rho=referenceDensity*std::exp(-(position.r()-earthRadius-referenceAltitude)/scaleHeight);
    return rotEarth.rotate((-0.5*ballisticCoefficient*rho*relative.r())*relative);
  }
};
#endif
