// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SEGMENTED_NATIVE_EXPORT_H
#define ORBIT_POC_SEGMENTED_NATIVE_EXPORT_H
#include "segmentedTangent.h"
#include "twofoldGeometry.h"
#include <fstream>
#include <iomanip>
#include <string>

namespace OrbitPoc { namespace SegmentedExport {
struct Weight {std::size_t index; long double high,low;};
inline thread_local std::vector<Weight> *capturedStencil=nullptr;
struct Capture
{
  std::vector<Weight> values;
  Capture(){if(capturedStencil)throw std::runtime_error("nested interpolation stencil capture");capturedStencil=&values;}
  ~Capture(){capturedStencil=nullptr;}
  Capture(const Capture&)=delete;Capture&operator=(const Capture&)=delete;
};
inline bool exact(std::size_t index)
{if(!capturedStencil)return false;capturedStencil->push_back({index,1,0});return true;}
template<class Weights> inline bool twofold(std::size_t first,const Weights &weights)
{
  if(!capturedStencil)return false;
  for(std::size_t k=0;k<weights.size();k++)capturedStencil->push_back({first+k,weights[k].high,weights[k].low});
  return true;
}
template<class Vector> inline bool ordinary(std::size_t first,const Vector &weights)
{
  if(!capturedStencil)return false;
  for(std::size_t k=0;k<weights.rows();k++)capturedStencil->push_back({first+k,weights(k),0});
  return true;
}
inline void string(std::ostream &out,const std::string &text)
{
  out<<'"';for(unsigned char c:text)
  {if(c=='"'||c=='\\')out<<'\\'<<char(c);else if(c<32){const char *h="0123456789abcdef";out<<"\\u00"<<h[c>>4]<<h[c&15];}else out<<char(c);}out<<'"';
}
template<class Matrix> inline void matrix(std::ostream &out,const Matrix &value)
{
  out<<'[';for(std::size_t i=0;i<value.rows();i++)for(std::size_t j=0;j<value.columns();j++)
  {const auto x=value(i,j);SegmentedTangent::finite(x);if(i||j)out<<',';out<<x;}out<<']';
}
template<class Matrix> inline void sparse(std::ostream &out,const Matrix &value)
{
  out<<'[';bool first=true;for(std::size_t i=0;i<value.rows();i++)for(std::size_t j=0;j<value.columns();j++)
  {const double x=value(i,j);SegmentedTangent::finite(x);if(x==0)continue;if(!first)out<<',';first=false;out<<'['<<i<<','<<j<<','<<x<<']';}out<<']';
}
inline void weights(std::ostream &out,const std::vector<Weight> &values)
{
  out<<'[';bool first=true;for(const auto &w:values)
  {
    if(!std::isfinite(w.high)||!std::isfinite(w.low))throw std::runtime_error("nonfinite exported interpolation weight");
    if(!first)out<<',';
    first=false;out<<'['<<w.index<<','<<static_cast<double>(w.high+w.low)<<",\"";
    out<<std::hexfloat<<w.high<<"\",\""<<w.low<<std::defaultfloat<<'"'<<']';
  }out<<']';
}
template<class Time> inline void time(std::ostream &out,const Time &value)
{out<<'['<<value.mjdInt()<<','<<value.mjdMod()<<']';}
// These six Cartesian query rows contain no covariance and no dense dynamic
// design. The caller supplies the actual native position/velocity stencils.
template<class Time> inline void stateQuery(std::ostream &out,const char *set,
    std::size_t receiver,std::size_t arc,std::size_t index,std::size_t first,
    std::size_t count,const Time &epoch,const std::vector<Weight> &position,
    const std::vector<Weight> &velocity)
{
  if(position.empty()||velocity.empty()||count<6)
    throw std::runtime_error("incomplete Cartesian covariance query");
  out<<"{\"kind\":\"state\",\"set\":";string(out,set);
  out<<",\"receiver\":"<<receiver<<",\"arc\":"<<arc<<",\"index\":"<<index
     <<",\"native_first\":"<<first<<",\"native_count\":"<<count<<",\"time\":";
  time(out,epoch);out<<",\"position_halo\":";weights(out,position);
  out<<",\"velocity_halo\":";weights(out,velocity);out<<"}\n";
}
inline void quadrature(std::ostream &out,const char *channel,const Quadrature &value)
{
  for(std::size_t i=0;i<value.size();i++)
  {
    out<<"{\"kind\":\"quadrature\",\"channel\":";string(out,channel);out<<",\"interval\":"<<i<<",\"terms\":[";
    bool first=true;for(const auto &term:value[i])
    {SegmentedTangent::finite(term.integral);SegmentedTangent::finite(term.moment);if(!first)out<<',';first=false;out<<'['<<term.index<<','<<term.integral<<','<<term.moment<<']';}out<<"]}\n";
  }
}
inline void jacobian(std::ostream &out,const ForceJacobian &value)
{
  out<<"\"Ar\":[";for(unsigned j=0;j<9;j++){SegmentedTangent::finite(value.position[j]);if(j)out<<',';out<<value.position[j];}
  out<<"],\"Av\":[";for(unsigned j=0;j<9;j++){SegmentedTangent::finite(value.velocity[j]);if(j)out<<',';out<<value.velocity[j];}out<<']';
}
}}
#endif
