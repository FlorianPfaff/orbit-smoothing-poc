"""Native weights must integrate real jumps without smoothing their endpoints."""
from pathlib import Path
import shutil,subprocess
import pytest
EXTENSION=Path(__file__).resolve().parents[1]/'groops/extension'

def test_one_sided_fractional_event_integrals(tmp_path):
    compiler=shutil.which('c++')
    if compiler is None:pytest.skip('C++ compiler unavailable')
    source=tmp_path/'events.cpp'
    source.write_text(r'''
#include "eventQuadrature.h"
#include <cassert>
#include <iostream>
using namespace OrbitPoc;
int main()
{
  for(double dt:{5.,2.5,1.})
  for(double jump:{18.,20.,180.})
  {
    const unsigned count=unsigned(360./dt)+1;
    std::vector<double> knots;for(double k=0;k<=360;k+=60)knots.push_back(k);
    const auto weights=eventQuadrature(count,dt,7,knots,{jump});
    // Nonzero polynomial drift and a true force jump; right limit at the event.
    auto force=[&](double t){return 1.+.01*t+.0001*t*t+(t>=jump ? 3.+.02*(t-jump) : 0.);};
    double position=0,velocity=0;
    for(unsigned i=0;i+1<count;i++)
    {
      double integral=0,moment=0,sum=0;
      for(auto term:weights[i])
      {
        integral+=term.integral*force(term.index*dt);
        moment+=term.moment*force(term.index*dt);sum+=term.integral;
      }
      assert(std::abs(sum-dt)<1e-10);
      position+=dt*velocity+dt*integral-moment;velocity+=integral;
      const double t=(i+1)*dt,h=std::max(t-jump,0.);
      const double v=t+.005*t*t+.0001*t*t*t/3.+3*h+.01*h*h;
      const double p=.5*t*t+.01*t*t*t/6.+.0001*t*t*t*t/12.+1.5*h*h+.02*h*h*h/6.;
      assert(std::abs(velocity-v)<1e-8);
      assert(std::abs(position-p)<1e-6);
    }
    // The last pre-event interval must never use an exact post-event sample.
    if(jump/dt==std::floor(jump/dt))
      {
        for(auto term:weights[unsigned(jump/dt)-1]) assert(term.index*dt<jump);
        for(auto term:weights[unsigned(jump/dt)]) assert(term.index*dt>jump);
      }
  }
  // A fractional jump can leave no native sample before a nearby density
  // knot. Actual auxiliary samples preserve degree, without duplicate nodes.
  for(double dt:{5.,2.5})
  for(double jump:{16.,59.9,60.1,119.999})
  {
    const unsigned count=unsigned(180/dt)+1;
    std::vector<double> extra;
    const auto weights=eventQuadrature(count,dt,7,{60.,120.},{jump},&extra);
    auto time=[&](unsigned index){return index<count ? index*dt : extra.at(index-count);};
    auto force=[&](double t){return .03*t*t+(t>=jump ? 4.:0.)+std::max(t-60.,0.);};
    double velocity=0,position=0;
    for(unsigned i=0;i+1<count;i++)
    {
      double integral=0,moment=0,sum=0;
      for(const auto &term:weights[i])
      {assert(std::isfinite(term.integral));sum+=term.integral;integral+=term.integral*force(time(term.index));moment+=term.moment*force(time(term.index));}
      assert(std::abs(sum-dt)<1e-9);
      position+=dt*velocity+dt*integral-moment;velocity+=integral;
      const double t=(i+1)*dt,h=std::max(t-jump,0.),k=std::max(t-60.,0.);
      assert(std::abs(velocity-(.01*t*t*t+4*h+.5*k*k))<1e-7);
      assert(std::abs(position-(.0025*t*t*t*t+2*h*h+k*k*k/6.))<1e-5);
    }
    assert(!extra.empty());
  }
  // Independent dense force samples: changing the output grid must integrate
  // the same polynomial, while the force cadence itself remains refinable.
  for(double mesh:{1.,.5})
  for(double dt:{5.,2.5})
  {
    const unsigned count=unsigned(120/dt)+1;
    std::vector<double> extra,knots;for(double k=5;k<120;k+=5)knots.push_back(k);
    const auto weights=eventQuadrature(count,dt,7,knots,{53.123},&extra,mesh);
    auto force=[](double t){return 1.+.01*t+.0001*t*t+(t>53.123 ? 2.:0.);};
    double position=0,velocity=0;
    for(unsigned i=0;i+1<count;i++)
    {
      double integral=0,moment=0;
      for(const auto &term:weights[i])
      {assert(term.index>=count);double t=extra.at(term.index-count);integral+=term.integral*force(t);moment+=term.moment*force(t);}
      position+=dt*velocity+dt*integral-moment;velocity+=integral;
    }
    const double h=120-53.123;
    assert(std::abs(velocity-(120+.005*120*120+.0001*120*120*120/3+2*h))<1e-9);
    assert(std::abs(position-(.5*120*120+.01*120*120*120/6+.0001*120*120*120*120/12+h*h))<1e-7);
  }
  // Sensitivity to a jump magnitude is the integrated step itself, independently
  // of the smooth background; this is the density-design quadrature contract.
  const auto w=eventQuadrature(73,5,7,{}, {18.});double derivative=0;
  for(auto interval:w)for(auto term:interval)derivative+=term.integral*(term.index*5>=18);
  assert(std::abs(derivative-342.)<1e-10);
}
''')
    binary=tmp_path/'events'
    subprocess.run([compiler,'-std=c++17','-O2','-I',str(EXTENSION),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
