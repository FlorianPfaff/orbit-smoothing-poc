#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include "syntheticForceArithmetic.h"

int main(int argc,char **argv)
{
  const std::string mode=argc>1?argv[1]:"residual";
  std::cout<<std::setprecision(30);
  try
  {
    if(mode=="composition")
    {
      OrbitPoc::SyntheticForceParts gravity,drag;
      double gm,weight,outer,nc[3],full[3],d[3];
      while(std::cin>>gm>>weight>>outer>>nc[0]>>nc[1]>>nc[2]>>full[0]>>full[1]>>full[2]>>d[0]>>d[1]>>d[2])
      {
        gravity.centralGM=gm;gravity.noncentral={nc[0],nc[1],nc[2]};gravity.full={full[0],full[1],full[2]};
        drag={};drag.full=drag.noncentral={d[0],d[1],d[2]};drag.scale(weight);
        gravity.add(drag);gravity.scale(outer);gravity.validate();
        std::cout<<gravity.centralGM;
        for(auto value:gravity.full)std::cout<<' '<<value;
        for(auto value:gravity.noncentral)std::cout<<' '<<value;
        std::cout<<'\n';
      }
    }
    else
    {
      std::array<double,3> p{},r{};double gm,ref,n[3];
      while(std::cin>>p[0]>>p[1]>>p[2]>>r[0]>>r[1]>>r[2]>>gm>>ref>>n[0]>>n[1]>>n[2])
      {
        OrbitPoc::SyntheticForceParts parts;parts.centralGM=gm;parts.noncentral={n[0],n[1],n[2]};
        const auto value=OrbitPoc::syntheticReferenceResidual(parts,p,r,ref);
        for(auto x:value)std::cout<<x<<' ';std::cout<<'\n';
      }
    }
  }
  catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 2;}
}
