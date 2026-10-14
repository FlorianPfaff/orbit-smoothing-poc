// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_PIECEWISE_POLYNOMIAL_H
#define ORBIT_POC_PIECEWISE_POLYNOMIAL_H
#include "base/import.h"
#include "base/polynomial.h"

// A fitted pulse orbit is continuous in position but has a right-continuous
// velocity jump. Density knots are continuous in both, with nonsmooth higher
// derivatives. Never let a polynomial stencil cross either type of boundary.
class OrbitPocPiecewisePolynomial
{
  struct Segment
  {
    UInt first, count, jumpCount;
    Polynomial smooth, jump;
  };
  std::vector<Time> splitTimes;
  std::vector<Segment> segments;
  UInt epochCount=0;

public:
  OrbitPocPiecewisePolynomial() {}
  OrbitPocPiecewisePolynomial(const std::vector<Time> &times, UInt degree,
      const std::vector<Time> &boundaries, const std::vector<Time> &pulses)
  {init(times,degree,boundaries,pulses);}

  void init(const std::vector<Time> &times, UInt degree,
      const std::vector<Time> &boundaries, const std::vector<Time> &pulses)
  {
    if(times.size()<=degree || !degree)
      throw(Exception("insufficient epochs for piecewise orbit interpolation"));
    epochCount=times.size(); splitTimes.clear(); segments.clear();
    std::vector<UInt> nodes{0};
    std::vector<UInt> jumpNodes;
    auto insert=[&](const Time &time, Bool jump)
    {
      if(time<=times.front() || time>=times.back()) return;
      auto found=std::lower_bound(times.begin(),times.end(),time);
      UInt index=std::distance(times.begin(),found);
      if(index && std::abs((times.at(index-1)-time).seconds())<std::abs((times.at(index)-time).seconds())) index--;
      if(std::abs((times.at(index)-time).seconds())>1e-5)
        throw(Exception("pulse/density interpolation boundary must be a native grid epoch"));
      nodes.push_back(index);
      if(jump) jumpNodes.push_back(index);
    };
    for(const auto &time:boundaries) insert(time,FALSE);
    for(const auto &time:pulses) insert(time,TRUE);
    nodes.push_back(times.size()-1);
    std::sort(nodes.begin(),nodes.end());
    nodes.erase(std::unique(nodes.begin(),nodes.end()),nodes.end());
    for(UInt i=0;i+1<nodes.size();i++)
    {
      Segment segment;
      segment.first=nodes.at(i); segment.count=nodes.at(i+1)-segment.first+1;
      const Bool jump=std::find(jumpNodes.begin(),jumpNodes.end(),nodes.at(i+1))!=jumpNodes.end();
      segment.jumpCount=segment.count-(jump ? 1 : 0);
      if(segment.jumpCount<=degree)
        throw(Exception("native grid too coarse for the chosen piecewise interpolation degree"));
      std::vector<Time> smooth(times.begin()+segment.first,times.begin()+segment.first+segment.count);
      segment.smooth.init(smooth,degree,TRUE,FALSE,-(degree+1.1),-1.1,1e-7);
      if(jump) smooth.pop_back(); // the endpoint contains the POST-pulse velocity
      segment.jump.init(smooth,degree,TRUE,FALSE,-(degree+1.1),-1.1,1e-7);
      segments.push_back(std::move(segment));
      if(i+2<nodes.size()) splitTimes.push_back(times.at(nodes.at(i+1)));
    }
  }

  Matrix interpolate(const std::vector<Time> &timesNew, const_MatrixSliceRef A,
                     UInt rowsPerEpoch=1, Bool valuesJump=FALSE) const
  {
    if(segments.empty() || A.rows()!=rowsPerEpoch*epochCount)
      throw(Exception("piecewise orbit interpolation data shape mismatch"));
    if(timesNew.size()==1)
    {
      const UInt index=std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.front())-splitTimes.begin();
      const auto &part=segments.at(index);
      const UInt count=valuesJump ? part.jumpCount : part.count;
      const auto &polynomial=valuesJump ? part.jump : part.smooth;
      return polynomial.interpolate(timesNew,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),rowsPerEpoch);
    }
    Matrix output(rowsPerEpoch*timesNew.size(),A.columns());
    std::vector<std::vector<UInt>> indices(segments.size());
    for(UInt i=0;i<timesNew.size();i++)
    {
      // Exact boundary epochs use the right segment and therefore preserve the
      // native t>=pulse convention. No averaging or smoothing of jumps occurs.
      const UInt segment=std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.at(i))-splitTimes.begin();
      indices.at(segment).push_back(i);
    }
    for(UInt segment=0;segment<segments.size();segment++)
    {
      auto &order=indices.at(segment);
      if(order.empty()) continue;
      std::stable_sort(order.begin(),order.end(),[&](UInt a,UInt b){return timesNew.at(a)<timesNew.at(b);});
      std::vector<Time> queries;
      for(UInt index:order) queries.push_back(timesNew.at(index));
      const auto &part=segments.at(segment);
      const UInt count=valuesJump ? part.jumpCount : part.count;
      const auto &polynomial=valuesJump ? part.jump : part.smooth;
      const Matrix values=polynomial.interpolate(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),rowsPerEpoch);
      for(UInt i=0;i<order.size();i++) copy(values.row(rowsPerEpoch*i,rowsPerEpoch),output.row(rowsPerEpoch*order.at(i),rowsPerEpoch));
    }
    return output;
  }
};
#endif
