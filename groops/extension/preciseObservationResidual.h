// SPDX-License-Identifier: GPL-3.0-or-later
// Coherent original GNSS residuals; QR coefficients remain native Double.
#ifndef ORBIT_POC_PRECISE_OBSERVATION_RESIDUAL_H
#define ORBIT_POC_PRECISE_OBSERVATION_RESIDUAL_H
#include "misc/orbitPoc/twofoldGeometry.h"
#include <vector>
#include <cstddef>
namespace orbitPocQr
{
using PreciseResidualVector=std::vector<TwofoldGeometry>;
inline constexpr const char *observationResidualPrecisionVersion="twofold_original_gnss_residual_v1";
template<class V> inline auto preciseElement(const V &value,std::size_t row,std::size_t column,int)
  -> decltype(value(row,column)){return value(row,column);}
template<class V> inline auto preciseElement(const V &value,std::size_t row,std::size_t column,long)
  -> decltype(value(row))
{if(column)throw std::runtime_error("Precise vector has a nonzero column");return value(row);}
template<class V> inline PreciseResidualVector liftPreciseVector(const V &value)
{
  if(value.columns()!=1)throw std::runtime_error("Precise residual requires a column vector");
  PreciseResidualVector result(value.rows());
  for(std::size_t i=0;i<result.size();i++)result[i]=TwofoldGeometry(preciseElement(value,i,0,0));
  return result;
}
inline void subtractPreciseVector(PreciseResidualVector &target,const PreciseResidualVector &correction)
{
  if(target.size()!=correction.size())throw std::runtime_error("Precise correction dimension mismatch");
  for(std::size_t i=0;i<target.size();i++)target[i]=target[i]-correction[i];
}
template<class M> inline PreciseResidualVector transformPreciseVector(const M &matrix,const PreciseResidualVector &value)
{
  if(matrix.columns()!=value.size())throw std::runtime_error("Precise composition dimension mismatch");
  PreciseResidualVector result(matrix.rows());
  for(std::size_t i=0;i<result.size();i++)for(std::size_t j=0;j<value.size();j++)
    result[i]=result[i]+TwofoldGeometry(preciseElement(matrix,i,j,0))*value[j];
  return result;
}
inline void subtractPreciseStec(PreciseResidualVector &target,std::size_t row,double coefficient,double stec,unsigned power)
{
  if(row>=target.size()||(power!=1&&power!=2))throw std::runtime_error("Invalid precise STEC term");
  const TwofoldGeometry state(stec);
  target[row]=target[row]-TwofoldGeometry(coefficient)*(power==1?state:state*state);
}
template<class V> inline void roundPreciseResiduals(V &target,const PreciseResidualVector &precise)
{
  if(target.columns()!=1||target.rows()!=precise.size())throw std::runtime_error("Incomplete precise original residual");
  for(std::size_t i=0;i<precise.size();i++)
  {
    if(!std::isfinite(precise[i].high)||!std::isfinite(precise[i].low))throw std::runtime_error("Nonfinite precise original residual");
    target(i)=static_cast<double>(precise[i].rounded());
    if(!std::isfinite(target(i)))throw std::runtime_error("Nonfinite rounded original residual");
  }
}
template<class V> inline void validatePreciseResiduals(const V &target,const PreciseResidualVector &precise,bool initialized,bool complete)
{
  if(!initialized||!complete||target.columns()!=1||target.rows()!=precise.size())
    throw std::runtime_error("Native original residual precision is missing or incomplete");
  for(std::size_t i=0;i<precise.size();i++)
    if(!std::isfinite(precise[i].high)||!std::isfinite(precise[i].low)||!std::isfinite(preciseElement(target,i,0,0))||
       static_cast<double>(precise[i].rounded())!=preciseElement(target,i,0,0))
      throw std::runtime_error("Native original residual disagrees with its precise representation");
}
template<class V> inline bool sameNativeResidual(const V &before,const V &after)
{
  if(before.rows()!=after.rows()||before.columns()!=after.columns())return false;
  for(std::size_t i=0;i<before.rows();i++)for(std::size_t j=0;j<before.columns();j++)
    if(preciseElement(before,i,j,0)!=preciseElement(after,i,j,0))return false;
  return true;
}
}
#endif
