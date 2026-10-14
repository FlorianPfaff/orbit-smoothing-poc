// Lightweight adapters instantiate the actual configured force headers. They
// do not stand in for a compiled GROOPS integration/trajectory test.
#include "miscAccelerationsSyntheticGravity.h"
#include "miscAccelerationsSyntheticDrag.h"
#include <iostream>
#include <iomanip>

int main()
{
  double x,y,z,vx,vy,vz,gm,j2,radius,angle,ballistic,rho,altitude,height,earth,omega;
  std::cout<<std::setprecision(30);
  while(std::cin>>x>>y>>z>>vx>>vy>>vz>>gm>>j2>>radius>>angle>>ballistic>>rho>>altitude>>height>>earth>>omega)
  {
    Config config;config.values={{"GM",gm},{"J2",j2},{"R",radius},{"ballisticCoefficient",ballistic},
      {"referenceDensity",rho},{"referenceAltitude",altitude},{"scaleHeight",height},
      {"earthRadius",earth},{"earthRotationRate",omega}};
    MiscAccelerationsSyntheticGravity gravity(config);MiscAccelerationsSyntheticDrag drag(config);
    const Vector3d p(x,y,z),v(vx,vy,vz);const Rotary3d rotation(angle);Time time;
    const auto actual=gravity.acceleration(nullptr,time,p,v,Rotary3d(),rotation,nullptr);
    // Exact old entry-point operations, including their original grouping.
    const double r=p.r(),z2=p.z()*p.z()/(r*r),a=1.5*j2*gm*radius*radius/std::pow(r,5);
    const auto original=rotation.rotate((-gm/std::pow(r,3))*p+Vector3d(a*p.x()*(5*z2-1),a*p.y()*(5*z2-1),a*p.z()*(5*z2-3)));
    OrbitPoc::SyntheticForceParts gp,dp;
    if(!gravity.orbitPocSyntheticForceParts(nullptr,time,p,v,Rotary3d(),rotation,nullptr,gp) ||
       !drag.orbitPocSyntheticForceParts(nullptr,time,p,v,Rotary3d(),rotation,nullptr,dp))return 3;
    const auto direct=gravity.acceleration(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr);
    const auto directDrag=drag.acceleration(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr);
    for(unsigned i=0;i<3;i++)if(actual[i]!=original[i] || gp.full[i]!=direct[i] || dp.full[i]!=directDrag[i])return 4;
    MiscAccelerationsBase unsupported;OrbitPoc::SyntheticForceParts ignored;
    if(unsupported.orbitPocSyntheticForceParts(nullptr,time,p,v,Rotary3d(),rotation,nullptr,ignored))return 5;
    std::cout<<gp.centralGM;
    for(auto value:gp.noncentral)std::cout<<' '<<value;
    for(auto value:dp.noncentral)std::cout<<' '<<value;
    std::cout<<'\n';
  }
}
