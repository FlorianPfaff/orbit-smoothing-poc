// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_INTEGRATION_WINDOWS_H
#define ORBIT_POC_INTEGRATION_WINDOWS_H
#include "base/import.h"

// A polynomial integration window must never straddle a model knot. Its end
// points may coincide with the knot: log-density and force remain continuous.
inline std::vector<UInt> orbitPocIntegrationWindows(const std::vector<Time> &times,
    const std::vector<Time> &boundaries, UInt degree)
{
  if(times.size() <= degree || !degree)
    throw(Exception("insufficient epochs for piecewise integration"));
  const Double dt = (times.at(1)-times.front()).seconds();
  if(dt <= 0) throw(Exception("integration epochs must be increasing"));
  for(UInt i=1;i<times.size();i++)
    if(std::abs((times.at(i)-times.at(i-1)).seconds()-dt)>1e-5)
      throw(Exception("piecewise integration requires a uniform fine grid"));
  std::vector<UInt> nodes{0};
  for(const auto &time: boundaries)
    if(time>times.front() && time<times.back())
    {
      const UInt index = std::llround((time-times.front()).seconds()/dt);
      if(index>=times.size() || std::abs((times.at(index)-time).seconds())>1e-5)
        throw(Exception("pulse/density boundary must be an integration epoch"));
      nodes.push_back(index);
    }
  nodes.push_back(times.size()-1);
  std::sort(nodes.begin(),nodes.end());
  nodes.erase(std::unique(nodes.begin(),nodes.end()),nodes.end());
  std::vector<UInt> result(times.size()-1);
  for(UInt segment=0;segment+1<nodes.size();segment++)
  {
    const UInt left=nodes.at(segment), right=nodes.at(segment+1);
    if(right-left<degree)
      throw(Exception("integration grid too coarse between model boundaries"));
    for(UInt i=left;i<right;i++)
      result.at(i)=std::max(left,std::min(i>=degree/2 ? i-degree/2 : 0,right-degree));
  }
  return result;
}
#endif
