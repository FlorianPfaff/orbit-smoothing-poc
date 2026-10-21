// External unbuilt draft02. Metadata follows the ACTUAL batch traversal.
#ifndef ORBIT_POC_WIDE_INTERPOLATION_STENCIL_H
#define ORBIT_POC_WIDE_INTERPOLATION_STENCIL_H
#include "twofoldInterpolation.h"
#include <array>
#include <utility>
namespace OrbitPoc { namespace WideInterpolation {
enum class Mode {unset, exact, ordinary, anchoredTwofold};
struct Stencil
{
  Mode mode=Mode::unset;
  std::vector<std::size_t> indices;
  std::vector<orbitPocQr::TwofoldGeometry> weights;
  std::size_t anchor=0;
  unsigned derivative=0;
};
struct Capture;
struct QueryMapping {std::size_t first=0;std::vector<std::size_t> outputs;};
inline thread_local Capture *destination=nullptr;
inline thread_local const QueryMapping *queryMapping=nullptr;
struct Capture
{
  std::vector<Stencil> values;
  std::vector<bool> seen;
  std::size_t epochs;
  Capture(std::size_t count,std::size_t epochCount):values(count),seen(count,false),epochs(epochCount)
  {
    if(destination||queryMapping)throw std::runtime_error("nested wide interpolation capture");
    if(!epochs)throw std::runtime_error("empty wide interpolation input grid");
    destination=this;
  }
  ~Capture(){destination=nullptr;}
  Capture(const Capture&)=delete;Capture&operator=(const Capture&)=delete;
  std::vector<Stencil> take()
  {
    if(queryMapping)throw std::runtime_error("wide interpolation mapping still active");
    for(std::size_t i=0;i<seen.size();i++)
      if(!seen[i]||values[i].mode==Mode::unset)throw std::runtime_error("native interpolation omitted query metadata");
    return std::move(values);
  }
};
// A no-op unless explicitly capturing. The caller supplies the SAME output
// order and segment offset already selected by piecewise interpolate().
struct Mapping
{
  QueryMapping value;
  bool active=false;
  template<class Order> Mapping(const Order &order,std::size_t first)
  {
    if(!destination)return;
    if(queryMapping)throw std::runtime_error("nested wide interpolation query mapping");
    value.first=first;
    for(auto i:order)
    {
      if(static_cast<std::size_t>(i)>=destination->values.size())
        throw std::runtime_error("wide interpolation output index outside capture");
      value.outputs.push_back(static_cast<std::size_t>(i));
    }
    queryMapping=&value;active=true;
  }
  ~Mapping(){if(active)queryMapping=nullptr;}
  Mapping(const Mapping&)=delete;Mapping&operator=(const Mapping&)=delete;
};
inline void store(std::size_t query,Stencil value)
{
  if(!destination||!queryMapping||query>=queryMapping->outputs.size())
    throw std::runtime_error("wide interpolation query mapping missing");
  const std::size_t output=queryMapping->outputs[query];
  if(destination->seen[output])throw std::runtime_error("repeated wide interpolation query metadata");
  for(auto &index:value.indices)
  {
    if(queryMapping->first>=destination->epochs||index>=destination->epochs-queryMapping->first)
      throw std::runtime_error("wide interpolation input index outside grid");
    index+=queryMapping->first;
  }
  destination->values[output]=std::move(value);destination->seen[output]=true;
}
inline bool exact(std::size_t query,std::size_t index)
{
  if(!destination)return false;
  Stencil s;s.mode=Mode::exact;s.indices={index};s.weights={orbitPocQr::TwofoldGeometry(1.L)};
  store(query,std::move(s));return true;
}
inline bool exactGrid(std::size_t count)
{
  if(!destination)return false;
  if(!queryMapping||queryMapping->outputs.size()!=count)
    throw std::runtime_error("exact-grid wide metadata shape mismatch");
  for(std::size_t i=0;i<count;i++)exact(i,i);
  return true;
}
template<class Weights> inline bool twofold(std::size_t query,std::size_t first,
    const Weights &weights,std::size_t actualAnchor,unsigned derivative)
{
  if(!destination)return false;
  Stencil s;s.mode=Mode::anchoredTwofold;s.anchor=actualAnchor;s.derivative=derivative;
  for(std::size_t k=0;k<weights.size();k++)
  {s.indices.push_back(first+k);s.weights.emplace_back(weights[k].high,weights[k].low);}
  store(query,std::move(s));return true;
}
template<class Weights> inline bool ordinary(std::size_t query,std::size_t first,const Weights &weights)
{
  if(!destination)return false;
  Stencil s;s.mode=Mode::ordinary;
  for(std::size_t k=0;k<weights.rows();k++)
  {s.indices.push_back(first+k);s.weights.emplace_back(static_cast<long double>(weights(k)));}
  store(query,std::move(s));return true;
}
template<class Value> inline long double evaluate(const Stencil &s,const Value &value)
{
  if(s.indices.empty()||s.indices.size()!=s.weights.size()||s.derivative!=0)
    throw std::runtime_error("invalid wide position/velocity interpolation stencil");
  for(std::size_t k=0;k<s.indices.size();k++)
    if(!std::isfinite(s.weights[k].high)||!std::isfinite(s.weights[k].low)||!std::isfinite(value(s.indices[k])))
      throw std::runtime_error("nonfinite wide interpolation input");
  if(s.mode==Mode::exact)
  {
    if(s.indices.size()!=1)throw std::runtime_error("invalid exact wide interpolation stencil");
    return value(s.indices.front());
  }
  if(s.mode==Mode::anchoredTwofold)
  {
    if(s.anchor>=s.indices.size())throw std::runtime_error("wide interpolation anchor outside stencil");
    return orbitPocQr::twofoldInterpolationValue(s.weights,
        [&](std::size_t k){return value(s.indices[k]);},0,s.anchor).rounded();
  }
  if(s.mode==Mode::ordinary)
  {
    orbitPocQr::TwofoldGeometry sum;
    for(std::size_t k=0;k<s.indices.size();k++)
      sum=sum+s.weights[k]*orbitPocQr::TwofoldGeometry(value(s.indices[k]));
    return sum.rounded();
  }
  throw std::runtime_error("unset wide interpolation stencil");
}
}}
#endif
