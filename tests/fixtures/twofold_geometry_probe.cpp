#include "twofoldGeometry.h"
#include <cfenv>
#include <iomanip>
#include <iostream>
#include <string>
using namespace orbitPocQr;
int main(int argc,char **argv)
{
  if(argc!=2 || std::numeric_limits<long double>::digits!=64 || std::fegetround()!=FE_TONEAREST)return 2;
  const double measured=std::stod(argv[1]);
  std::cout<<std::setprecision(30)<<std::scientific;
  const double rh[]={6871000.125,-1200300.375,2450060.5},th[]={15400000.75,21300000.125,11600000.5};
  const double rl[]={1.37e-10,-4.2e-11,8.91e-11},tl[]={-3.4e-10,1.21e-10,3.2e-11};
  const double v[]={-1234.5,2781.25,992.125};
  for(int changed=0;changed<2;changed++)
  {
    TwofoldGeometry r[3],t[3],delta[3];
    for(int k=0;k<3;k++)
    {
      const double low=(changed&&k==0)?static_cast<double>(static_cast<long double>(rl[k])+2.025e-14L):rl[k];
      r[k]=TwofoldGeometry(rh[k],low);t[k]=TwofoldGeometry(th[k],tl[k]);delta[k]=r[k]-t[k];
    }
    const auto range=geometrySqrt(geometrySquares(delta[0],delta[1],delta[2]));
    const auto r1=geometrySqrt(geometrySquares(t[0],t[1],t[2])),r2=geometrySqrt(geometrySquares(r[0],r[1],r[2]));
    const long double c=299792458.L,gm=static_cast<double>(3.986004418e14);
    const auto dot=t[0]*TwofoldGeometry(v[0])+t[1]*TwofoldGeometry(v[1])+t[2]*TwofoldGeometry(v[2]);
    const long double shapiro=2*gm/(c*c)*std::log(((r1+r2+range)/(r1+r2-range)).rounded());
    const auto geometric=range+TwofoldGeometry(shapiro)+TwofoldGeometry(2)*dot/TwofoldGeometry(c);
    const auto clock=TwofoldGeometry(c)*(TwofoldGeometry(static_cast<double>(3.812e-6))-TwofoldGeometry(static_cast<double>(4.3e-8)));
    const auto scale=TwofoldGeometry(static_cast<double>(1.000000000001));
    const auto residual=TwofoldGeometry(measured)-geometric*scale-clock*scale;
    std::cout<<(changed?"shifted":"nominal")<<" "<<residual.high<<" "<<residual.low<<" "<<static_cast<double>(residual.rounded())<<"\n";
  }
}
