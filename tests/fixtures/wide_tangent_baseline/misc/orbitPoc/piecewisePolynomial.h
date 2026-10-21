// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_PIECEWISE_POLYNOMIAL_H
#define ORBIT_POC_PIECEWISE_POLYNOMIAL_H
#include "base/import.h"
#include "base/polynomial.h"
#include "misc/orbitPoc/segmentedNativeExport.h"

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
  // ORBIT_POC_RELATIVE_QUERY_INTERPOLATION_V31
  Matrix interpolateOffset(const std::vector<Time> &timesNew, const_MatrixSliceRef A,
                     const std::vector<long double> &offsetSeconds, UInt rowsPerEpoch=1, Bool valuesJump=FALSE, std::vector<long double> *preciseValues=nullptr, std::vector<long double> *coordinateRemainders=nullptr) const
  {
    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    // ORBIT_POC_PRECISE_POSITION_REMAINDER_V31_PAIR2
    if(!prefix||!*prefix)
    {
      const Matrix values=interpolate(timesNew,A,rowsPerEpoch,valuesJump);
      if(preciseValues){preciseValues->resize(values.rows()*values.columns());for(UInt row=0;row<values.rows();row++)for(UInt col=0;col<values.columns();col++)preciseValues->at(row*values.columns()+col)=values(row,col);}
      if(coordinateRemainders)coordinateRemainders->assign(values.rows()*values.columns(),0.L);
      return values;
    }
    if(preciseValues)preciseValues->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);
    if(coordinateRemainders)coordinateRemainders->assign(rowsPerEpoch*timesNew.size()*A.columns(),0.L);
    if(!offsetSeconds.empty()&&offsetSeconds.size()!=timesNew.size())throw(Exception("Piecewise relative query shape mismatch"));
    auto offsetAt=[&](UInt index){return offsetSeconds.empty()?0.L:offsetSeconds.at(index);};
    auto difference=[](const Time &a,const Time &b){return (static_cast<long double>(a.mjdInt())-b.mjdInt())*86400.L+(static_cast<long double>(a.mjdMod())-b.mjdMod())*86400.L;};
    auto segmentAt=[&](UInt i){return std::upper_bound(splitTimes.begin(),splitTimes.end(),timesNew.at(i),[&](const Time &query,const Time &boundary){return difference(query,boundary)+offsetAt(i)<0;})-splitTimes.begin();};
    if(segments.empty() || A.rows()!=rowsPerEpoch*epochCount)
      throw(Exception("piecewise orbit interpolation data shape mismatch"));
    if(timesNew.size()==1)
    {
      const UInt index=segmentAt(0);
      const auto &part=segments.at(index);
      const UInt count=valuesJump ? part.jumpCount : part.count;
      const auto &polynomial=valuesJump ? part.jump : part.smooth;
      return polynomial.interpolateOffset(timesNew,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsetSeconds,rowsPerEpoch,0,FALSE,preciseValues,coordinateRemainders);
    }
    Matrix output(rowsPerEpoch*timesNew.size(),A.columns());
    std::vector<std::vector<UInt>> indices(segments.size());
    for(UInt i=0;i<timesNew.size();i++)
    {
      // Exact boundary epochs use the right segment and therefore preserve the
      // native t>=pulse convention. No averaging or smoothing of jumps occurs.
      const UInt segment=segmentAt(i);
      indices.at(segment).push_back(i);
    }
    for(UInt segment=0;segment<segments.size();segment++)
    {
      auto &order=indices.at(segment);
      if(order.empty()) continue;
      std::stable_sort(order.begin(),order.end(),[&](UInt a,UInt b){return difference(timesNew.at(a),timesNew.at(b))+offsetAt(a)-offsetAt(b)<0;});
      std::vector<Time> queries;std::vector<long double> offsets;
      for(UInt index:order){queries.push_back(timesNew.at(index));offsets.push_back(offsetAt(index));}
      const auto &part=segments.at(segment);
      const UInt count=valuesJump ? part.jumpCount : part.count;
      const auto &polynomial=valuesJump ? part.jump : part.smooth;
      std::vector<long double> exact,low;
      const Matrix values=polynomial.interpolateOffset(queries,A.row(rowsPerEpoch*part.first,rowsPerEpoch*count),offsets,rowsPerEpoch,0,FALSE,preciseValues?&exact:nullptr,coordinateRemainders?&low:nullptr);
      if(preciseValues)for(UInt i=0;i<order.size();i++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)preciseValues->at((rowsPerEpoch*order.at(i)+row)*A.columns()+col)=exact.at((rowsPerEpoch*i+row)*A.columns()+col);
      if(coordinateRemainders)for(UInt i=0;i<order.size();i++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)coordinateRemainders->at((rowsPerEpoch*order.at(i)+row)*A.columns()+col)=low.at((rowsPerEpoch*i+row)*A.columns()+col);
      for(UInt i=0;i<order.size();i++) copy(values.row(rowsPerEpoch*i,rowsPerEpoch),output.row(rowsPerEpoch*order.at(i),rowsPerEpoch));
    }
    return output;
  }
  // ORBIT_POC_SEGMENTED_STENCIL_CAPTURE_V4: evaluate the native selection and
  // coefficient code with zero data columns. No replica interpolation recipe.
  std::vector<OrbitPoc::SegmentedExport::Weight> orbitPocStencil(
      const Time &query,long double remainder=0.L,Bool velocity=FALSE) const
  {
    if(segments.empty())throw(Exception("empty segmented interpolation"));
    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    const Bool precise=prefix&&*prefix;
    if(!precise&&remainder!=0)throw(Exception("relative halo requires the native precise interpolation path"));
    auto difference=[](const Time&a,const Time&b){return (static_cast<long double>(a.mjdInt())-b.mjdInt())*86400.L+(static_cast<long double>(a.mjdMod())-b.mjdMod())*86400.L;};
    const UInt segment=precise ? std::upper_bound(splitTimes.begin(),splitTimes.end(),query,[&](const Time&q,const Time&b){return difference(q,b)+remainder<0;})-splitTimes.begin() : std::upper_bound(splitTimes.begin(),splitTimes.end(),query)-splitTimes.begin();
    const auto &part=segments.at(segment);const UInt count=velocity?part.jumpCount:part.count;
    const auto &polynomial=velocity?part.jump:part.smooth;
    OrbitPoc::SegmentedExport::Capture capture;
    polynomial.interpolateOffset({query},Matrix(count,0),{remainder},1);
    if(capture.values.empty())throw(Exception("native interpolation failed to export its halo"));
    for(auto &term:capture.values)term.index+=part.first;
    return capture.values;
  }

};
#endif
