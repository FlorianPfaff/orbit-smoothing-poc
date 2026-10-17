#include <vector>
#include <cmath>
#include <random>
#include <iostream>
#include <iomanip>
#include <cstdint>
static std::vector<double> last;
static double residual;
static unsigned iteration;
void recordTangentTrace(unsigned k,const std::vector<double>&x,double r,bool){last=x;residual=r;iteration=k;}
void recordTangentProjection(unsigned,double){}
#include "sixStateTangent.h"
int main(){
 std::cout<<std::setprecision(21);
 const unsigned dim=12;std::vector<OrbitPoc::ForceJacobian>jac(4);
 for(unsigned power=13;power<=18;power++)for(unsigned seed=1;seed<=200;seed++){
  std::mt19937 rng(seed);double Q[dim][dim]{};
  for(unsigned i=0;i<dim;i++)Q[i][i]=1;
  for(unsigned k=0;k<dim;k++){
   double v[dim],norm=0;for(auto&x:v){x=(int(rng()%2001)-1000)/1024.;norm+=x*x;}
   for(unsigned i=0;i<dim;i++){double dot=0;for(unsigned j=0;j<dim;j++)dot+=Q[i][j]*v[j];for(unsigned j=0;j<dim;j++)Q[i][j]-=2*dot*v[j]/norm;}
  }
  double B[dim][dim];for(unsigned i=0;i<dim;i++)for(unsigned j=0;j<dim;j++){
   long double a=0;for(unsigned k=0;k<dim;k++)a+=static_cast<long double>(Q[i][k])*std::ldexp(1.,-int(power*k/(dim-1)))*Q[j][k];
   B[i][j]=(i==j?1.:0.)-double(a);
  }
  OrbitPoc::TangentVector b(2*dim);for(unsigned i=0;i<dim;i++)b[i]=(int(rng()%2001)-1000)/1024.+.013*(i+1);
  auto op=[&](const OrbitPoc::TangentVector&x){OrbitPoc::TangentVector y(2*dim);for(unsigned i=0;i<dim;i++){long double v=0;for(unsigned j=0;j<dim;j++)v+=static_cast<long double>(B[i][j])*x[j];y[i]=double(v);}return y;};
  bool passed=false;last.clear();residual=0;iteration=0;
  try{auto r=OrbitPoc::solveSixStateTangent(jac,1.,op,b);passed=true;}catch(const std::runtime_error&){}
  __float128 ss=0,nn=0;
  if(last.empty())return 2;
  for(unsigned i=0;i<dim;i++){__float128 v=static_cast<__float128>(b[i])-last[i];for(unsigned j=0;j<dim;j++)v+=static_cast<__float128>(B[i][j])*last[j];ss+=v*v;nn+=static_cast<__float128>(b[i])*b[i];}
  std::cout<<power<<','<<seed<<','<<passed<<','<<iteration<<','<<residual<<','<<std::sqrt(static_cast<long double>(ss/nn))<<'\n';
 }
}
