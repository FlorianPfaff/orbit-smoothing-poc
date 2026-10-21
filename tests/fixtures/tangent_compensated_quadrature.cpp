// An exact piecewise-constant-acceleration regression for the production kernel.
// Explicit failures remain active when the native build defines NDEBUG.
#include "sixStateTangent.h"
#include <iostream>
#include <stdexcept>
using namespace OrbitPoc;

int main()
{
  const long double big=std::ldexp(1.L,80);
  for(long double sign : {1.L,-1.L})
  {
    TangentCompensatedSum sum;
    sum.add(sign*big);sum.add(sign);sum.add(-sign*big);
    if(sum.value()!=sign)throw std::runtime_error("lost compensated cancellation");
    Quadrature weights(4);
    std::vector<long double> acceleration(12);
    const long double samples[4]={big,1.L,-3.L*big,2.L*big};
    for(unsigned k=0;k<4;k++)
    {
      weights[k].push_back({k,1.,.5});
      acceleration[3*k]=sign*samples[k];
    }
    const auto state=tangentIntegrate(weights,1.,acceleration);
    // Integrating four unit intervals gives v=sum(a)=1 and
    // p=3.5*a0+2.5*a1+1.5*a2+0.5*a3=2.5 before applying sign.
    // This requires carrying the low part of velocity into later positions.
    if(state.size()!=30 || state[12]!=sign*2.5 || state[27]!=sign)
      throw std::runtime_error("lost compensated velocity contribution to position");
    for(unsigned k=0;k<5;k++)for(unsigned axis=1;axis<3;axis++)
      if(state[3*k+axis]!=0 || state[15+3*k+axis]!=0)
        throw std::runtime_error("changed zero acceleration axis");
  }
  std::cout<<"compensated quadrature regression passed\n";
}
