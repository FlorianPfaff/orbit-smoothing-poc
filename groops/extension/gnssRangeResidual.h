// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_GNSS_RANGE_RESIDUAL_H
#define ORBIT_POC_GNSS_RANGE_RESIDUAL_H
#include "base/import.h"
#include "misc/orbitPoc/twofoldGeometry.h"
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
inline TwofoldGeometry stableRangeResidualExpansion(Double measured,const Vector3d &receiverPosition,
                                  const Vector3d &transmitterPosition,const Vector3d &transmitterVelocity,
                                  Double receiverClock,Double transmitterClock,Double scale,
                                  const Vector3d &receiverRemainder=Vector3d(),const Vector3d &transmitterRemainder=Vector3d())
{
  requireGeometryArithmetic();
  const TwofoldGeometry rx(receiverPosition.x(),receiverRemainder.x()),ry(receiverPosition.y(),receiverRemainder.y()),rz(receiverPosition.z(),receiverRemainder.z());
  const TwofoldGeometry tx(transmitterPosition.x(),transmitterRemainder.x()),ty(transmitterPosition.y(),transmitterRemainder.y()),tz(transmitterPosition.z(),transmitterRemainder.z());
  const auto dx=rx-tx,dy=ry-ty,dz=rz-tz;
  const char *auditMode=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
  const Bool reverse=auditMode&&std::string(auditMode)=="3";
  const auto range=geometrySqrt(geometrySquares(dx,dy,dz,reverse));
  const auto r1=geometrySqrt(geometrySquares(tx,ty,tz,reverse)),r2=geometrySqrt(geometrySquares(rx,ry,rz,reverse));
  const long double c=LIGHT_VELOCITY;
  const auto dot=reverse?tz*TwofoldGeometry(transmitterVelocity.z())+ty*TwofoldGeometry(transmitterVelocity.y())+tx*TwofoldGeometry(transmitterVelocity.x()):tx*TwofoldGeometry(transmitterVelocity.x())+ty*TwofoldGeometry(transmitterVelocity.y())+tz*TwofoldGeometry(transmitterVelocity.z());
  // Log rounding is multiplied by millimetres, never by the orbital range.
  const long double shapiro=2.L*DEFAULT_GM/(c*c)*std::log(((r1+r2+range)/(r1+r2-range)).rounded());
  const auto geometric=range+TwofoldGeometry(shapiro)+TwofoldGeometry(2.L)*dot/TwofoldGeometry(c);
  const auto clock=TwofoldGeometry(c)*(TwofoldGeometry(receiverClock)-TwofoldGeometry(transmitterClock));
  const auto residual=TwofoldGeometry(measured)-geometric*TwofoldGeometry(scale)-clock*TwofoldGeometry(scale);
  return residual;
}
// Preserve the established Double API for legacy callers and native fixtures.
inline Double stableRangeResidual(Double measured,const Vector3d &receiverPosition,
                                  const Vector3d &transmitterPosition,const Vector3d &transmitterVelocity,
                                  Double receiverClock,Double transmitterClock,Double scale,
                                  const Vector3d &receiverRemainder=Vector3d(),const Vector3d &transmitterRemainder=Vector3d())
{
  return static_cast<Double>(stableRangeResidualExpansion(measured,receiverPosition,transmitterPosition,transmitterVelocity,
      receiverClock,transmitterClock,scale,receiverRemainder,transmitterRemainder).rounded());
}
inline long double preciseDistance(const Vector3d &a,const Vector3d &aLow,const Vector3d &b,const Vector3d &bLow)
{
  requireGeometryArithmetic();
  const auto x=TwofoldGeometry(a.x(),aLow.x())-TwofoldGeometry(b.x(),bLow.x());
  const auto y=TwofoldGeometry(a.y(),aLow.y())-TwofoldGeometry(b.y(),bLow.y());
  const auto z=TwofoldGeometry(a.z(),aLow.z())-TwofoldGeometry(b.z(),bLow.z());
  return geometrySqrt(geometrySquares(x,y,z)).rounded();
}
}
#endif
