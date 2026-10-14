// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_ATMOSPHERE_LOCAL_EVENTS_H
#define ORBIT_POC_ATMOSPHERE_LOCAL_EVENTS_H
#include "base/import.h"
#include "base/planets.h"
#include "base/polynomial.h"

// Reproduce the local-solar-time argument of ThermosphereJB2008::state and
// JB2008.f. DTSUB is not periodic at its 0/24-hour join, so this wrap is a true
// discontinuity of the unmodified atmospheric model, not a smoothed driver.
inline Double orbitPocJbLocalSolarPhase(const Time &time,const Vector3d &position,
                                      const Rotary3d &rotEarth)
{
  Angle longitude,latitude; Double height;
  Ellipsoid()(rotEarth.rotate(position),longitude,latitude,height);
  const Double satelliteLongitude=std::fmod(
      Double(longitude+Planets::gmst(timeGPS2UTC(time)))+2*PI,2*PI);
  Double phase=std::fmod(satelliteLongitude-Double(Planets::positionSun(time).lambda())+PI,2*PI);
  if(phase<0) phase+=2*PI;
  return phase;
}

inline std::vector<Time> orbitPocLocalMidnightEvents(const std::vector<Time> &times,
    const Matrix &positions,const std::vector<Rotary3d> &rotEarth)
{
  if(times.size()<8 || positions.rows()!=3*times.size() || positions.columns()!=1
     || rotEarth.size()!=times.size())
    throw(Exception("local atmospheric events require at least eight synchronized position/rotation samples"));
  for(UInt i=1;i<times.size();i++)
    if(!(times.at(i)>times.at(i-1)))
      throw(Exception("local atmospheric event epochs must strictly increase"));
  Polynomial polynomial(times,7);
  Matrix rotations(times.size(),9);
  std::vector<Double> phases(times.size());
  for(UInt i=0;i<times.size();i++)
  {
    const Matrix rotation=rotEarth.at(i).matrix();
    for(UInt row=0;row<3;row++)
      for(UInt column=0;column<3;column++)
        rotations(i,3*row+column)=rotation(row,column);
    phases.at(i)=orbitPocJbLocalSolarPhase(times.at(i),Vector3d(positions.row(3*i,3)),rotEarth.at(i));
  }
  auto signedPhase=[&](const Time &time)
  {
    const Matrix flat=polynomial.interpolate({time},rotations);
    Matrix rotation(3,3);
    for(UInt row=0;row<3;row++)
      for(UInt column=0;column<3;column++)
        rotation(row,column)=flat(0,3*row+column);
    const Vector3d position(polynomial.interpolate({time},positions,3));
    return std::remainder(orbitPocJbLocalSolarPhase(time,position,Rotary3d(rotation)),2*PI);
  };
  std::vector<Time> events;
  for(UInt i=1;i<times.size();i++)
  {
    if(std::abs(phases.at(i)-phases.at(i-1))<=PI) continue;
    Time left=times.at(i-1),right=times.at(i);
    Double leftValue=std::remainder(phases.at(i-1),2*PI);
    const Double rightValue=std::remainder(phases.at(i),2*PI);
    if(leftValue==0) right=left;
    else if(rightValue==0) left=right;
    else
    {
      if((leftValue<0)==(rightValue<0))
        throw(Exception("local-midnight phase wrap did not bracket a crossing"));
      for(UInt iteration=0;iteration<64 && (right-left).seconds()>1e-7;iteration++)
      {
        const Time middle=left+seconds2time(.5*(right-left).seconds());
        const Double middleValue=signedPhase(middle);
        if(middleValue==0) {left=right=middle;break;}
        if((middleValue<0)==(leftValue<0)) {left=middle;leftValue=middleValue;}
        else right=middle;
      }
    }
    const Time crossing=left+seconds2time(.5*(right-left).seconds());
    if(events.empty() || (crossing-events.back()).seconds()>1e-7)
      events.push_back(crossing);
  }
  return events;
}
#endif
