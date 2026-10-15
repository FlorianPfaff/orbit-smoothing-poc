// Standalone use of the production helper; Decimal supplies the independent oracle.
#include "twofoldInterpolation.h"
#include <array>
#include <iomanip>
#include <iostream>
#include <string>

int main()
{
  constexpr unsigned count=8;
  auto sample=[](unsigned k){const double t=k*30.;return 6871000.125+3000*t+0.0625*t*t;};
  std::cout<<std::setprecision(36);
  for(unsigned boundary=0;boundary<2;boundary++)
    for(unsigned derivative:{0U,1U,2U,8U})for(unsigned anchor:{0U,4U,7U})
      for(long double offset:{0.L,1e-18L,-1e-18L,1e-12L})
      {
        const long double day=60000;
        const double query=boundary?0.:47./86400.;
        std::vector<orbitPocQr::TwofoldGeometry> nodes(count);
        std::array<long double,count> oldNodes{},oldWeights{};
        for(unsigned k=0;k<count;k++)
        {
          const double fraction=boundary?(k<4?1.+(static_cast<int>(k)-4)*30./86400.:(k-4)*30./86400.):k*30./86400.;
          const long double nodeDay=day-(boundary&&k<4?1:0);
          nodes[k]=orbitPocQr::twofoldInterpolationNode(nodeDay,fraction,day,query,offset,30.L);
          oldNodes[k]=((nodeDay-day)*86400.L+(static_cast<long double>(fraction)-query)*86400.L-offset)/30.L;
        }
        const auto weights=orbitPocQr::twofoldInterpolationWeights(nodes,derivative,30.L);
        const auto value=orbitPocQr::twofoldInterpolationValue(weights,sample,derivative,anchor);
        const double rounded=static_cast<double>(value.rounded());
        const long double low=(value-orbitPocQr::TwofoldGeometry(rounded)).rounded();
        for(unsigned k=0;k<count;k++)
        {
          std::array<long double,count> polynomial{};polynomial[0]=1;
          unsigned order=0;long double denominator=1;
          for(unsigned j=0;j<count;j++)if(j!=k)
          {
            denominator*=oldNodes[k]-oldNodes[j];
            for(unsigned power=order+1;power>0;power--)polynomial[power]=polynomial[power-1]-oldNodes[j]*polynomial[power];
            polynomial[0]*=-oldNodes[j];order++;
          }
          if(derivative<count)
          {
            oldWeights[k]=polynomial[derivative]/denominator;
            for(unsigned order=1;order<=derivative;order++)oldWeights[k]*=static_cast<long double>(order)/30.L;
          }
        }
        long double oldLocal=0;
        for(unsigned k=0;k<count;k++)oldLocal+=oldWeights[k]*(static_cast<long double>(sample(k))-sample(anchor));
        const long double oldCenter=derivative?0.L:sample(anchor);
        const double oldRounded=static_cast<double>(oldCenter+oldLocal);
        const long double oldLow=(oldCenter-oldRounded)+oldLocal;
        orbitPocQr::TwofoldGeometry partition;
        for(const auto &weight:weights)partition=partition+weight;
        std::cout<<boundary<<' '<<derivative<<' '<<anchor<<' '<<offset<<' '
                 <<value.high<<' '<<value.low<<' '<<rounded<<' '<<low<<' '
                 <<oldRounded<<' '<<oldLow<<' '<<partition.high<<' '<<partition.low<<'\n';
      }
}
