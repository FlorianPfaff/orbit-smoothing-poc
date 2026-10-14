// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_EVENT_QUADRATURE_H
#define ORBIT_POC_EVENT_QUADRATURE_H
#include <algorithm>
#include <cmath>
#include <map>
#include <stdexcept>
#include <vector>
namespace OrbitPoc {
struct QuadratureTerm {unsigned index; double integral, moment;};
using Quadrature = std::vector<std::vector<QuadratureTerm>>;
// Sample times are uniform. Breaks can lie between samples. Continuous knots
// admit their shared endpoint. Exclude exact jump epochs on both sides: a
// reverse local-midnight crossing has the left limit at the wrapped phase zero.
// moment integrates (t - interval_start)*f, avoiding large absolute epochs.
inline Quadrature eventQuadrature(unsigned count,double dt,unsigned degree,
    std::vector<double> knots,std::vector<double> jumps,std::vector<double>*additionalTimes=nullptr,double quadratureStep=0.)
{
  if(count<2 || !(dt>0)) throw std::runtime_error("invalid event quadrature grid");
  const double end=(count-1)*dt, eps=2e-7;
  std::vector<double> boundaries{0,end};
  for(double x:knots) if(x>eps && x<end-eps) boundaries.push_back(x);
  for(double x:jumps) if(x>eps && x<end-eps) boundaries.push_back(x);
  std::sort(boundaries.begin(),boundaries.end());
  boundaries.erase(std::unique(boundaries.begin(),boundaries.end(),[=](double a,double b){return std::abs(a-b)<eps;}),boundaries.end());
  auto isJump=[&](double x){return std::any_of(jumps.begin(),jumps.end(),[=](double y){return std::abs(x-y)<eps;});};
  // Build each segment once. Short segments use only auxiliary, evenly
  // spaced interior nodes: mixing these with native nodes can create nearly
  // coincident Lagrange abscissae and destroy conditioning.
  if(quadratureStep>0 && !additionalTimes) throw std::runtime_error("dense quadrature requires auxiliary evaluations");
  if(additionalTimes) additionalTimes->clear();
  std::vector<std::vector<std::pair<double,unsigned>>> segmentSamples;
  for(unsigned b=0;b+1<boundaries.size();b++)
  {
    const double left=boundaries[b],right=boundaries[b+1];
    const double mesh=quadratureStep>0 ? quadratureStep : dt;
    const int first=std::max(0,int(std::ceil((left+(isJump(left)?eps:-eps))/mesh)));
    const int last=int(std::floor((right+(isJump(right)?-eps:eps))/mesh));
    std::vector<std::pair<double,unsigned>> samples;
    if(additionalTimes && (quadratureStep>0 || last-first+1<int(degree+1)))
    {
      const unsigned number=last-first+1<int(degree+1) ? degree+1 : last-first+1;
      for(unsigned k=0;k<number;k++)
      {
        const double t=last-first+1<int(degree+1) ? left+(right-left)*(k+.5)/number : (first+k)*mesh;
        additionalTimes->push_back(t);
        samples.emplace_back(t,count+additionalTimes->size()-1);
      }
    }
    else
      for(int k=first;k<=last && k<int(count);k++) samples.emplace_back(k*dt,k);
    if(samples.empty()) throw std::runtime_error("event segment has no force samples");
    segmentSamples.push_back(std::move(samples));
  }
  Quadrature result(count-1);
  for(unsigned i=0;i+1<count;i++)
  {
    const double from=i*dt,to=(i+1)*dt;
    std::vector<double> cuts{from,to};
    for(double x:boundaries) if(x>from+eps && x<to-eps) cuts.push_back(x);
    if(quadratureStep>0)
      for(double x=(std::floor((from+eps)/quadratureStep)+1)*quadratureStep;x<to-eps;x+=quadratureStep) cuts.push_back(x);
    std::sort(cuts.begin(),cuts.end());
    cuts.erase(std::unique(cuts.begin(),cuts.end(),[=](double a,double b){return std::abs(a-b)<eps;}),cuts.end());
    std::map<unsigned,std::pair<long double,long double>> weights;
    for(unsigned piece=0;piece+1<cuts.size();piece++)
    {
      const double a=cuts[piece],b=cuts[piece+1],mid=.5*(a+b);
      const auto hi=std::upper_bound(boundaries.begin(),boundaries.end(),mid);
      const auto &allowed=segmentSamples.at((hi-boundaries.begin())-1);
      const unsigned n=std::min(degree+1,unsigned(allowed.size()));
      const int center=std::lower_bound(allowed.begin(),allowed.end(),std::pair<double,unsigned>{mid,0})-allowed.begin();
      const unsigned start=std::max(0,std::min(int(allowed.size()-n),center-int(n/2)));
      const long double origin=allowed[start].first/dt;
      const long double lo=a/dt-origin,up=b/dt-origin;
      for(unsigned k=0;k<n;k++)
      {
        std::vector<long double> polynomial{1};
        for(unsigned j=0;j<n;j++) if(j!=k)
        {
          std::vector<long double> next(polynomial.size()+1);
          const long double xj=allowed[start+j].first/dt-origin;
          const long double xk=allowed[start+k].first/dt-origin;
          for(unsigned p=0;p<polynomial.size();p++)
          {next[p]-=xj*polynomial[p]/(xk-xj);next[p+1]+=polynomial[p]/(xk-xj);}
          polynomial.swap(next);
        }
        long double integral=0,moment=0;
        for(unsigned p=0;p<polynomial.size();p++)
        {
          const long double w=(std::pow(up,int(p+1))-std::pow(lo,int(p+1)))/(p+1);
          integral+=polynomial[p]*w;
          moment+=polynomial[p]*((std::pow(up,int(p+2))-std::pow(lo,int(p+2)))/(p+2)+(origin-i)*w);
        }
        auto &value=weights[allowed[start+k].second];value.first+=dt*integral;value.second+=dt*dt*moment;
      }
    }
    for(auto [index,value]:weights) result[i].push_back({index,double(value.first),double(value.second)});
  }
  return result;
}
}
#endif
