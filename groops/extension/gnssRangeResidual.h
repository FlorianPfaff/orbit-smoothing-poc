// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_GNSS_RANGE_RESIDUAL_H
#define ORBIT_POC_GNSS_RANGE_RESIDUAL_H
#include "base/import.h"
#include <cstdlib>
#include <string>
namespace orbitPocQr
{
// Avoid first normalizing a tiny negative duration to a fraction near one day.
// The final Time still has its native double day-fraction precision.
inline Time stableReceiverTime(const Time &nominal,long double clockSeconds)
{
  return Time(nominal.mjdInt(),static_cast<Double>(static_cast<long double>(nominal.mjdMod())-clockSeconds/86400.L));
}
// Preserve the part of nominal-clock which cannot be represented by Time.
// Subtract split day components before combining with the small clock value.
inline long double timeRemainder(const Time &nominal,long double clockSeconds,const Time &rounded)
{
  return -clockSeconds-((static_cast<long double>(rounded.mjdInt())-nominal.mjdInt())*86400.L+
                       (static_cast<long double>(rounded.mjdMod())-nominal.mjdMod())*86400.L);
}
// The native corrected-range equation, evaluated before rounding the small
// clock correction onto a 20,000-km geometric range. The statistical model,
// time/position inputs, relativistic terms and transmitter scale are unchanged.
inline Double stableRangeResidual(Double measured,const Vector3d &receiverPosition,
                                  const Vector3d &transmitterPosition,const Vector3d &transmitterVelocity,
                                  Double receiverClock,Double transmitterClock,Double scale,
                                  const Vector3d &receiverRemainder=Vector3d(),const Vector3d &transmitterRemainder=Vector3d())
{
  const long double rx=static_cast<long double>(receiverPosition.x())+receiverRemainder.x(),ry=static_cast<long double>(receiverPosition.y())+receiverRemainder.y(),rz=static_cast<long double>(receiverPosition.z())+receiverRemainder.z();
  const long double tx=static_cast<long double>(transmitterPosition.x())+transmitterRemainder.x(),ty=static_cast<long double>(transmitterPosition.y())+transmitterRemainder.y(),tz=static_cast<long double>(transmitterPosition.z())+transmitterRemainder.z();
  const long double dx=rx-tx,dy=ry-ty,dz=rz-tz;
  const char *auditMode=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
  const Bool reverse=auditMode&&std::string(auditMode)=="3";
  auto squares=[&](long double x,long double y,long double z){return reverse?z*z+y*y+x*x:x*x+y*y+z*z;};
  const long double range=std::sqrt(squares(dx,dy,dz)),r1=std::sqrt(squares(tx,ty,tz)),r2=std::sqrt(squares(rx,ry,rz));
  const long double c=LIGHT_VELOCITY;
  const long double dot=reverse?tz*transmitterVelocity.z()+ty*transmitterVelocity.y()+tx*transmitterVelocity.x():tx*transmitterVelocity.x()+ty*transmitterVelocity.y()+tz*transmitterVelocity.z();
  const long double geometric=range+2.L*DEFAULT_GM/(c*c)*std::log((r1+r2+range)/(r1+r2-range))+2.L*dot/c;
  const long double clock=c*(static_cast<long double>(receiverClock)-transmitterClock);
  return static_cast<Double>((static_cast<long double>(measured)-geometric*scale)-clock*scale);
}
inline long double preciseDistance(const Vector3d &a,const Vector3d &aLow,const Vector3d &b,const Vector3d &bLow)
{
  const long double x=(static_cast<long double>(a.x())-b.x())+(static_cast<long double>(aLow.x())-bLow.x());
  const long double y=(static_cast<long double>(a.y())-b.y())+(static_cast<long double>(aLow.y())-bLow.y());
  const long double z=(static_cast<long double>(a.z())-b.z())+(static_cast<long double>(aLow.z())-bLow.z());
  return std::sqrt(x*x+y*y+z*z);
}
}
#endif
