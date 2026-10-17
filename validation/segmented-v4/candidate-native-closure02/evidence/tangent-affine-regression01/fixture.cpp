#include <iostream>
#include <iomanip>
#include <string>
#include "sixStateTangent.h"
#include "coefficients01.h"
int main(){
 const unsigned dim=9;std::vector<OrbitPoc::ForceJacobian>jac(3);
 OrbitPoc::TangentVector rhs(18),last;for(unsigned i=0;i<dim;i++)rhs[i]=initialRhs[i];
 auto integrated=[&](const OrbitPoc::TangentVector&x){last=x;OrbitPoc::TangentVector y(18);for(unsigned i=0;i<dim;i++){long double value=0;for(unsigned j=0;j<dim;j++)value+=static_cast<long double>(B[i][j])*x[j];y[i]=double(value);}return y;};
 bool passed=false;unsigned iterations=120;double reported=0;std::string error;
 try{const auto result=OrbitPoc::solveSixStateTangent(jac,1.,integrated,rhs);passed=true;iterations=result.iterations;reported=result.relativeResidual;}catch(const std::runtime_error&e){error=e.what();}
 __float128 ss=0,nn=0;
 for(unsigned i=0;i<dim;i++){__float128 value=static_cast<__float128>(rhs[i])-last[i];for(unsigned j=0;j<dim;j++)value+=static_cast<__float128>(B[i][j])*last[j];ss+=value*value;nn+=static_cast<__float128>(rhs[i])*rhs[i];}
 std::cout<<std::setprecision(21)<<"{\"passed\":"<<(passed?"true":"false")<<",\"iterations\":"<<iterations<<",\"reported_residual\":"<<reported<<",\"independent_quad_residual\":"<<std::sqrt(static_cast<long double>(ss/nn))<<",\"error\":\""<<error<<"\"}\n";
}
