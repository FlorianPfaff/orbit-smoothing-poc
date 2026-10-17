// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SEGMENTED_TANGENT_H
#define ORBIT_POC_SEGMENTED_TANGENT_H
#include "sixStateTangent.h"
#include <array>
#include <cstddef>
#include <map>
#include <stdexcept>
#include <utility>

namespace OrbitPoc { namespace SegmentedTangent {
// All coefficients describe deterministic equalities. They are never whitened
// by an invented process standard deviation. Native free parameters have a
// separate index space from the six auxiliary coordinates at each grid epoch.
struct Term {std::size_t column; double value;};
struct Row {std::vector<Term> auxiliary, parameter; double target=0.;};
using Stencil=std::vector<Term>;
using Matrix6=std::array<double,36>;
struct Sample {ForceJacobian jacobian; Stencil position, velocity;};
struct Channel {std::vector<Sample> samples; Quadrature weights;};
struct Forcing {unsigned component; std::size_t parameter; double value;};
struct Pulse {std::size_t epoch, parameter; std::array<double,18> map;};

inline void finite(double x)
{if(!std::isfinite(x))throw std::runtime_error("nonfinite segmented tangent coefficient");}
inline std::size_t stateId(std::size_t epoch,unsigned component)
{if(component>=6)throw std::runtime_error("invalid segmented state component");return 6*epoch+component;}
inline Stencil compress(const std::map<std::size_t,long double> &values)
{
  Stencil result;
  for(const auto &entry:values)
  {const double value=static_cast<double>(entry.second);finite(value);if(value!=0.)result.push_back({entry.first,value});}
  return result;
}
inline void validate(const Channel &channel,std::size_t epochs)
{
  if(epochs<2||channel.weights.size()+1!=epochs)throw std::runtime_error("segmented quadrature shape mismatch");
  for(const auto &sample:channel.samples)
  {
    for(double x:sample.jacobian.position)finite(x);
    for(double x:sample.jacobian.velocity)finite(x);
    if(sample.position.empty()||sample.velocity.empty())throw std::runtime_error("missing interpolation halo");
    for(const auto &stencil:{sample.position,sample.velocity})for(const auto &term:stencil)
    {if(term.column>=epochs)throw std::runtime_error("interpolation halo outside full arc");finite(term.value);}
  }
  for(const auto &interval:channel.weights)for(const auto &term:interval)
  {if(term.index>=channel.samples.size())throw std::runtime_error("quadrature sample outside channel");finite(term.integral);finite(term.moment);}
}

// Local difference of x=b+K*x, using exactly the stored quadrature integral and
// first moment. Stencils may span a computational cut: no new physical boundary
// or integration window is inserted. Layout is [r0,v0,r1,v1,...].
inline std::vector<Row> tangentRows(std::size_t epochs,double dt,
    const std::vector<Channel> &channels,const std::vector<double> &rhs)
{
  if(epochs<2||!(dt>0)||!std::isfinite(dt)||rhs.size()!=6*epochs)
    throw std::runtime_error("invalid segmented tangent shape");
  for(double x:rhs)finite(x);
  for(const auto &channel:channels)validate(channel,epochs);
  std::vector<Row> rows(6*epochs);
  for(unsigned c=0;c<6;c++){rows[c].auxiliary={{c,1.}};rows[c].target=rhs[c];}
  for(std::size_t k=0;k+1<epochs;k++)for(unsigned c=0;c<6;c++)
  {
    auto &row=rows[stateId(k+1,c)];std::map<std::size_t,long double> values;
    values[stateId(k+1,c)]=1;values[stateId(k,c)]=-1;
    long double target=static_cast<long double>(rhs[stateId(k+1,c)])-rhs[stateId(k,c)];
    if(c<3){values[stateId(k,c+3)]=-dt;target-=static_cast<long double>(dt)*rhs[stateId(k,c+3)];}
    for(const auto &channel:channels)for(const auto &term:channel.weights[k])
    {
      const auto &sample=channel.samples[term.index];
      const long double factor=c<3 ? static_cast<long double>(dt)*term.integral-term.moment : term.integral;
      for(unsigned j=0;j<3;j++)
      {
        for(const auto &w:sample.position)values[stateId(w.column,j)]-=factor*sample.jacobian.position[3*(c%3)+j]*w.value;
        for(const auto &w:sample.velocity)values[stateId(w.column,j+3)]-=factor*sample.jacobian.velocity[3*(c%3)+j]*w.value;
      }
    }
    row.auxiliary=compress(values);row.target=static_cast<double>(target);finite(row.target);
  }
  return rows;
}

// The actual downstream GROOPS force columns are variation-of-constants
// quadratures, not a second forced solve of x=b+K*x. Keep that discretization:
// c[k+1]-c[k] = sum(w*Phi(sample)^-1*[0;B])*theta + pulse jump.
// Physical grid state is Phi[k]*c[k]. Initial six native coordinates occupy
// the final six original parameter columns, including native velocity scaling.
inline std::vector<Row> variationRows(std::size_t epochs,std::size_t parameters,
    const Quadrature &weights,const std::vector<std::vector<Forcing>> &forcing,
    const std::vector<Pulse> &pulses)
{
  if(epochs<2||parameters<6||weights.size()+1!=epochs)
    throw std::runtime_error("invalid variation-of-constants dimensions");
  for(const auto &sample:forcing)for(const auto &term:sample)
  {if(term.component>=6||term.parameter>=parameters-6)throw std::runtime_error("invalid force parameter mapping");finite(term.value);}
  for(const auto &pulse:pulses)
  {
    if(pulse.epoch==0||pulse.epoch>=epochs-1||pulse.parameter+3>parameters-6)
      throw std::runtime_error("pulse is not an interior native parameter block");
    for(double value:pulse.map)finite(value);
  }
  std::vector<Row> rows(6*epochs);
  for(unsigned c=0;c<6;c++)
  {rows[c].auxiliary={{c,1}};rows[c].parameter={{parameters-6+c,-1}};}
  for(std::size_t k=0;k+1<epochs;k++)for(unsigned c=0;c<6;c++)
  {
    auto &row=rows[stateId(k+1,c)];row.auxiliary={{stateId(k,c),-1},{stateId(k+1,c),1}};
    std::map<std::size_t,long double> values;
    for(const auto &weight:weights[k])
    {
      if(weight.index>=forcing.size())throw std::runtime_error("force quadrature sample missing");
      finite(weight.integral);
      for(const auto &term:forcing[weight.index])if(term.component==c)
        values[term.parameter]-=static_cast<long double>(weight.integral)*term.value;
    }
    for(const auto &pulse:pulses)if(pulse.epoch==k+1)
      for(unsigned j=0;j<3;j++)values[pulse.parameter+j]-=pulse.map[3*c+j];
    row.parameter=compress(values);
  }
  return rows;
}

// A measurement's native interpolation halo composes with the stored Phi at
// each support epoch. No interpolation of Phi*c across an invented cut occurs.
inline Stencil observationRow(const std::vector<Matrix6> &phi,const Stencil &halo,
    const std::array<double,6> &stateDesign)
{
  std::map<std::size_t,long double> values;
  for(double value:stateDesign)finite(value);
  if(halo.empty())throw std::runtime_error("empty observation interpolation halo");
  for(const auto &term:halo)
  {
    if(term.column>=phi.size())throw std::runtime_error("observation halo outside arc");
    finite(term.value);
    for(unsigned c=0;c<6;c++)for(unsigned r=0;r<6;r++)
    {finite(phi[term.column][6*r+c]);values[stateId(term.column,c)]+=static_cast<long double>(term.value)*stateDesign[r]*phi[term.column][6*r+c];}
  }
  return compress(values);
}

inline double residual(const Row &row,const std::vector<double> &auxiliary,
    const std::vector<double> &parameters={})
{
  long double value=-row.target;
  for(const auto &term:row.auxiliary)value+=static_cast<long double>(term.value)*auxiliary.at(term.column);
  for(const auto &term:row.parameter)value+=static_cast<long double>(term.value)*parameters.at(term.column);
  return static_cast<double>(value);
}
}}
#endif
