// External unbuilt draft03: typed export of ACTUAL batch metadata.
#ifndef ORBIT_POC_WIDE_INTERPOLATION_EXPORT_H
#define ORBIT_POC_WIDE_INTERPOLATION_EXPORT_H
#include "wideInterpolationStencil.h"
#include <iomanip>
#include <ostream>
#include <set>
namespace OrbitPoc { namespace WideInterpolationExport {
inline WideInterpolation::Stencil identity(std::size_t epoch)
{
  WideInterpolation::Stencil s;s.mode=WideInterpolation::Mode::exact;
  s.indices={epoch};s.weights={orbitPocQr::TwofoldGeometry(1.L)};return s;
}
inline void stencil(std::ostream &out,const WideInterpolation::Stencil &s,std::size_t epochs)
{
  using WideInterpolation::Mode;
  if(s.indices.empty()||s.indices.size()!=s.weights.size()||s.derivative!=0)
    throw std::runtime_error("invalid typed tangent interpolation metadata");
  if(s.mode!=Mode::exact&&s.mode!=Mode::ordinary&&s.mode!=Mode::anchoredTwofold)
    throw std::runtime_error("unset typed tangent interpolation mode");
  if(s.mode==Mode::exact&&(s.indices.size()!=1||s.weights[0].high!=1.L||s.weights[0].low!=0.L))
    throw std::runtime_error("typed exact stencil is not identity");
  if(s.mode==Mode::anchoredTwofold&&s.anchor>=s.indices.size())
    throw std::runtime_error("typed interpolation anchor outside stencil");
  std::set<std::size_t> seen;
  for(std::size_t k=0;k<s.indices.size();k++)
    if(s.indices[k]>=epochs||!seen.insert(s.indices[k]).second||
       !std::isfinite(s.weights[k].high)||!std::isfinite(s.weights[k].low))
      throw std::runtime_error("invalid typed tangent interpolation term");
  const auto flags=out.flags();const auto precision=out.precision();
  out<<"{\"mode\":\""<<(s.mode==Mode::exact?"exact":s.mode==Mode::ordinary?"ordinary":"anchored_twofold")
     <<"\",\"derivative\":0,\"anchor\":";
  if(s.mode==Mode::anchoredTwofold)out<<s.anchor;else out<<"null";
  out<<",\"terms\":[";
  for(std::size_t k=0;k<s.indices.size();k++)
  {
    if(k)out<<',';
    out<<'['<<s.indices[k]<<",\""<<std::hexfloat<<s.weights[k].high<<"\",\""<<s.weights[k].low<<"\"]"<<std::defaultfloat;
  }
  out<<"]}";out.flags(flags);out.precision(precision);
}
}}
#endif
