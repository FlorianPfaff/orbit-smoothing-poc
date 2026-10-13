#include "eventQuadrature.h"
#include <chrono>
#include <iostream>
#include <iomanip>
#include <cassert>
using namespace OrbitPoc;
struct Run {std::vector<double> p,v;};
Run run(double end,double dt,double mesh) {
  const auto start=std::chrono::steady_clock::now();
  const unsigned count=unsigned(std::round(end/dt))+1;
  std::vector<double> knots,extra;
  for(double t=5;t<end;t+=5)knots.push_back(t);
  auto q=eventQuadrature(count,dt,7,knots,{53.123},&extra,mesh);
  Run out;out.p.push_back(0);out.v.push_back(0);
  double p=0,v=0;unsigned long terms=0;
  for(unsigned i=0;i+1<count;i++) {
    double a=0,m=0,sum=0;
    for(const auto&t:q[i]) {
      assert(t.index>=count);double s=extra.at(t.index-count);
      const double f=std::sin(.07*s)+std::exp(.00003*s)+(s>53.123 ? 2.:0.);
      a+=t.integral*f;m+=t.moment*f;sum+=t.integral;terms++;
    }
    assert(std::abs(sum-dt)<1e-9);
    p+=dt*v+dt*a-m;v+=a;out.p.push_back(p);out.v.push_back(v);
  }
  const double elapsed=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
  std::cout<<"end="<<end<<" state_step="<<dt<<" force_step="<<mesh<<" extra_nodes="<<extra.size()<<" weight_terms="<<terms<<" seconds="<<elapsed<<"\n";
  return out;
}
int main(int argc,char**){
  std::cout<<std::setprecision(15);
  for(double mesh:{1.,.5}) {
    auto coarse=run(120.,5.,mesh),fine=run(120.,2.5,mesh);
    double dp=0,dv=0;
    for(unsigned i=0;i<coarse.p.size();i++) {
      dp=std::max(dp,std::abs(coarse.p[i]-fine.p[2*i]));
      dv=std::max(dv,std::abs(coarse.v[i]-fine.v[2*i]));
    }
    std::cout<<"nonpolynomial_state_mesh_difference_position="<<dp<<" velocity="<<dv<<"\n";
    assert(dp<1e-8 && dv<1e-10);
  }
  if(argc>1) {run(86400.,5.,1.);run(86400.,2.5,1.);run(86400.,2.5,.5);}
}
