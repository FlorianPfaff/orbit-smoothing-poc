// SPDX-License-Identifier: GPL-3.0-or-later
// The existing Lagrange polynomial, with query and weight roundoff retained.
#ifndef ORBIT_POC_TWOFOLD_INTERPOLATION_H
#define ORBIT_POC_TWOFOLD_INTERPOLATION_H
#include "twofoldGeometry.h"
#include <cstddef>
#include <vector>

namespace orbitPocQr
{
inline constexpr const char *queryInterpolationPrecisionVersion="twofold_query_weights_v1";

inline TwofoldGeometry twofoldInterpolationNode(long double nodeDay,long double nodeFraction,
                                                long double queryDay,long double queryFraction,
                                                long double offsetSeconds,long double sampling)
{
  requireGeometryArithmetic();
  // Subtract the tiny query remainder before rounding either time differences
  // or normalized nodes. A long-double node can otherwise erase that remainder.
  return ((TwofoldGeometry(nodeDay)-TwofoldGeometry(queryDay))*TwofoldGeometry(86400.L)
          +(TwofoldGeometry(nodeFraction)-TwofoldGeometry(queryFraction))*TwofoldGeometry(86400.L)
          -TwofoldGeometry(offsetSeconds))/TwofoldGeometry(sampling);
}

inline std::vector<TwofoldGeometry> twofoldInterpolationWeights(const std::vector<TwofoldGeometry> &nodes,
                                                               unsigned derivative,long double sampling)
{
  requireGeometryArithmetic();
  const std::size_t count=nodes.size();
  std::vector<TwofoldGeometry> weights(count);
  for(std::size_t k=0;k<count;k++)
  {
    std::vector<TwofoldGeometry> polynomial(count);polynomial[0]=TwofoldGeometry(1.L);
    std::size_t order=0;TwofoldGeometry denominator(1.L);
    for(std::size_t j=0;j<count;j++)if(j!=k)
    {
      denominator=denominator*(nodes[k]-nodes[j]);
      for(std::size_t power=order+1;power>0;power--)
        polynomial[power]=polynomial[power-1]-nodes[j]*polynomial[power];
      polynomial[0]=polynomial[0]*(-nodes[j]);order++;
    }
    if(derivative<count)
    {
      weights[k]=polynomial[derivative]/denominator;
      for(unsigned order=1;order<=derivative;order++)
        weights[k]=weights[k]*(TwofoldGeometry(order)/TwofoldGeometry(sampling));
    }
  }
  return weights;
}

template<class Value>
inline TwofoldGeometry twofoldInterpolationValue(const std::vector<TwofoldGeometry> &weights,
                                                 const Value &value,unsigned derivative,std::size_t anchor)
{
  const TwofoldGeometry reference(value(anchor));
  TwofoldGeometry localOffset;
  for(std::size_t k=0;k<weights.size();k++)
    localOffset=localOffset+weights[k]*(TwofoldGeometry(value(k))-reference);
  // Keep the local sum's low component until the final native-double split.
  return (derivative?TwofoldGeometry():reference)+localOffset;
}
}
#endif
