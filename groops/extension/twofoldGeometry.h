// SPDX-License-Identifier: GPL-3.0-or-later
// Versioned high/low GNSS geometry; same physical observation equation.
#ifndef ORBIT_POC_TWOFOLD_GEOMETRY_H
#define ORBIT_POC_TWOFOLD_GEOMETRY_H
#include <cmath>
#include <cfenv>
#if defined(__FAST_MATH__)
#error "high_low_geometry_v2 forbids fast-math reassociation"
#endif
#include <limits>
#include <stdexcept>
namespace orbitPocQr
{
inline constexpr const char *geometryPrecisionVersion="high_low_geometry_v2";
static_assert(std::numeric_limits<long double>::digits>=64,"high_low_geometry_v2 requires at least64 significand bits");
inline void requireGeometryArithmetic()
{if(std::fegetround()!=FE_TONEAREST)throw(std::runtime_error("high_low_geometry_v2 requires round-to-nearest"));}
// A long-double expansion. Every component is a native long double; fma
// retains the product error. Requires round-to-nearest and no fast-math.
struct TwofoldGeometry
{
  long double high=0, low=0;
  TwofoldGeometry()=default;
  TwofoldGeometry(long double a,long double b=0):high(a),low(b){}
  static TwofoldGeometry sum(long double a,long double b)
  {
    const long double s=a+b,v=s-a;
    return {s,(a-(s-v))+(b-v)};
  }
  long double rounded()const{return high+low;}
};
inline TwofoldGeometry operator-(const TwofoldGeometry &a){return {-a.high,-a.low};}
inline TwofoldGeometry operator+(const TwofoldGeometry &a,const TwofoldGeometry &b)
{
  const auto s=TwofoldGeometry::sum(a.high,b.high);
  return TwofoldGeometry::sum(s.high,s.low+(a.low+b.low));
}
inline TwofoldGeometry operator-(const TwofoldGeometry &a,const TwofoldGeometry &b){return a+(-b);}
inline TwofoldGeometry operator*(const TwofoldGeometry &a,const TwofoldGeometry &b)
{
  const long double p=a.high*b.high;
  const long double error=std::fma(a.high,b.high,-p);
  return TwofoldGeometry::sum(p,((error+a.high*b.low)+a.low*b.high)+a.low*b.low);
}
inline TwofoldGeometry operator/(const TwofoldGeometry &a,const TwofoldGeometry &b)
{
  const long double first=a.high/b.high;
  const auto remainder=a-b*TwofoldGeometry(first);
  return TwofoldGeometry::sum(first,remainder.rounded()/b.high);
}
inline TwofoldGeometry geometrySqrt(const TwofoldGeometry &a)
{
  if(a.high==0 && a.low==0)return {};
  const long double first=std::sqrt(a.high);
  const auto remainder=a-TwofoldGeometry(first)*TwofoldGeometry(first);
  return TwofoldGeometry::sum(first,(remainder/TwofoldGeometry(2*first)).rounded());
}
inline TwofoldGeometry geometrySquares(const TwofoldGeometry &x,const TwofoldGeometry &y,const TwofoldGeometry &z,bool reverse=false)
{return reverse?z*z+y*y+x*x:x*x+y*y+z*z;}
}
#endif
