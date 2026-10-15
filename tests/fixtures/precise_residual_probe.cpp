#include "misc/orbitPoc/preciseObservationResidual.h"
#include <iostream>
#include <iomanip>
#include <string>
struct Matrix
{
  std::size_t nr,nc;std::vector<double> data;
  Matrix(std::size_t r,std::size_t c,std::initializer_list<double> d):nr(r),nc(c),data(d){}
  std::size_t rows()const{return nr;}std::size_t columns()const{return nc;}
  double operator()(std::size_t i,std::size_t j)const{return data.at(i*nc+j);}
};
struct Vector:Matrix
{
  Vector(std::initializer_list<double> d):Matrix(d.size(),1,d){}
  double operator()(std::size_t i)const{return data.at(i);}
  double &operator()(std::size_t i){return data.at(i);}
};
int main(int argc,char **argv)
{
  using namespace orbitPocQr;std::cout<<std::setprecision(70);
  const std::string mode=argc>1?argv[1]:"chain";
  if(mode=="chain")
  {
    double stec;long double low;
    while(std::cin>>stec>>low)
    {
      PreciseResidualVector value{TwofoldGeometry(10.L,low)};double legacy=static_cast<double>(10.L+low);
      auto receiver=liftPreciseVector(Vector{.6037960671066858});
      receiver[0]=receiver[0]+TwofoldGeometry(.0003141592653589793);
      subtractPreciseVector(value,receiver);legacy-=(.6037960671066858+.0003141592653589793);
      auto transmitter=liftPreciseVector(Vector{.125,.25});transmitter[0]=transmitter[0]+TwofoldGeometry(.000021);
      transmitter[1]=transmitter[1]+TwofoldGeometry(-.000071);
      Matrix composition(1,2,{.25,.75});subtractPreciseVector(value,transformPreciseVector(composition,transmitter));
      legacy-=.25*(.125+.000021)+.75*(.25-.000071);
      Matrix ambiguity(1,2,{.19029367279836487,.24421021342456825});Vector cycles{3.25,-2.125};
      subtractPreciseVector(value,transformPreciseVector(ambiguity,liftPreciseVector(cycles)));
      legacy-=.19029367279836487*3.25+.24421021342456825*(-2.125);
      const double coefficients[4]={-.16237244751199473,-.000123456789012345,-.000000134567890123,3.45678901234e-9};
      for(unsigned i=0;i<4;i++)
      {
        subtractPreciseStec(value,0,coefficients[i],stec,i<2?1:2);
        legacy-=coefficients[i]*(i<2?stec:std::pow(stec,2));
      }
      const double weight=1./.003;value[0]=value[0]*TwofoldGeometry(weight);legacy*=weight;
      Vector rounded{0};roundPreciseResiduals(rounded,value);validatePreciseResiduals(rounded,value,true,true);
      const auto prior=-TwofoldGeometry(stec)/TwofoldGeometry(40.);
      std::cout<<stec<<' '<<low<<' '<<value[0].high<<' '<<value[0].low<<' '<<rounded(0)<<' '<<legacy<<' '<<prior.high<<' '<<prior.low<<'\n';
    }
    return 0;
  }
  if(mode=="ambiguity")
  {
    double a,b,c,d,x,y;
    while(std::cin>>a>>b>>c>>d>>x>>y)
    {
      const auto result=transformPreciseVector(Matrix(2,2,{a,b,c,d}),liftPreciseVector(Vector{x,y}));
      std::cout<<result[1].high<<' '<<result[1].low<<'\n';
    }
    return 0;
  }
  if(mode=="guards")
  {
    unsigned caught=0;Vector one{1};PreciseResidualVector precise{TwofoldGeometry(1)};
    auto fails=[&](auto operation){try{operation();}catch(const std::runtime_error&){caught++;}};
    fails([&](){validatePreciseResiduals(one,precise,false,true);});
    fails([&](){validatePreciseResiduals(one,precise,true,false);});
    fails([&](){validatePreciseResiduals(one,{},true,true);});
    fails([&](){validatePreciseResiduals(one,{TwofoldGeometry(2)},true,true);});
    fails([&](){validatePreciseResiduals(one,{TwofoldGeometry(std::numeric_limits<long double>::infinity())},true,true);});
    fails([&](){validatePreciseResiduals(Vector{std::numeric_limits<double>::infinity()},{TwofoldGeometry(std::numeric_limits<long double>::max())},true,true);});
    fails([&](){subtractPreciseVector(precise,{});});
    fails([&](){transformPreciseVector(Matrix(1,2,{1,2}),precise);});
    fails([&](){subtractPreciseStec(precise,1,1.,1.,1);});
    fails([&](){subtractPreciseStec(precise,0,1.,1.,3);});
    fails([&](){preciseElement(one,0,1,0);});
    fails([&](){roundPreciseResiduals(one,{});});
    if(!sameNativeResidual(one,Vector{1})||sameNativeResidual(one,Vector{2})||sameNativeResidual(one,Vector{1,2}))return 2;
    std::cout<<caught<<'\n';return caught==12?0:3;
  }
  return 4;
}
