#define main replayMain
#include "replay.cpp"
#undef main
int main(int argc,char **argv) {
  if(argc!=2)return 2;
  if(std::string(argv[1])=="--compensation") {
    const long double big=std::ldexp(1.L,80);
    OrbitPoc::TangentCompensatedSum sum;
    sum.add(big);sum.add(1.L);sum.add(-big);
    if(sum.value()!=1.L)throw std::runtime_error("compensated cancellation failed");
    OrbitPoc::Quadrature weights(4);
    std::vector<long double> acceleration(12);
    const long double samples[4]={big,1.L,-3.L*big,2.L*big};
    for(unsigned k=0;k<4;k++) {weights[k].push_back({k,1.,.5});acceleration[3*k]=samples[k];}
    const auto state=OrbitPoc::tangentIntegrate(weights,1.,acceleration);
    // Exact piecewise-constant acceleration: v_final=sum(a)=1;
    // p_final=3.5*a0+2.5*a1+1.5*a2+0.5*a3=2.5.
    if(state[12]!=2.5 || state[15+12]!=1.)
      throw std::runtime_error("compensated velocity carry into position failed");
    for(unsigned k=0;k<5;k++)for(unsigned axis=1;axis<3;axis++)
      if(state[3*k+axis]!=0 || state[15+3*k+axis]!=0)
        throw std::runtime_error("compensated integration changed zero axis");
    std::cout<<"compensated cancellation and coupled chronological integral passed\n";
    return 0;
  }

  data=readCapture(argv[1]);
  std::vector<double> x(data.rhs.size(),0);
  std::cout<<std::setprecision(21);
  std::cout<<quadResidual(x,true)<<'\n';
  x=data.rhs;
  for(unsigned k=x.size()/2;k<x.size();k++)x[k]*=1000.;
  std::cout<<quadResidual(x,true)<<'\n';
  x[0]+=.25;
  std::cout<<quadResidual(x,true)<<'\n';
  recordTangentTrace(120,x,1.,true);
}
