#define main replayMain
#include "replay.cpp"
#undef main
int main(int argc,char **argv) {
  if(argc!=2)return 2;
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
