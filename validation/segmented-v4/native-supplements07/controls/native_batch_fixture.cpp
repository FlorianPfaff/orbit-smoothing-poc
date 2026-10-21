// Supplemental diagnostic draft: links the actual installed native objects.
// No search, Time comparison, Polynomial or piecewise algorithm is replicated.
#include "base/import.h"
#include "misc/orbitPoc/piecewisePolynomial.h"
#include "misc/orbitPoc/wideInterpolationExport.h"
#include <cstdlib>
#include <iostream>
#include <sstream>
#include <limits>
namespace W=OrbitPoc::WideInterpolation;
namespace E=OrbitPoc::WideInterpolationExport;
static void need(bool ok,const char *why){if(!ok)throw std::runtime_error(why);}
static std::string hex(long double v){std::ostringstream s;s<<std::hexfloat<<v;return s.str();}
static std::string encoded(const W::Stencil&s,std::size_t n){std::ostringstream o;E::stencil(o,s,n);return o.str();}
static Time timeAt(long double seconds){return Time(60000,0)+seconds2time(seconds);}
static void emit(const char *name,const std::vector<Time>& grid,const std::vector<Time>& queries,
 const Matrix &data,const Matrix &native,const std::vector<W::Stencil>& metadata,
 const char *channel,bool precise)
{
 need(metadata.size()==queries.size(),"missing actual batch output metadata");
 std::cout<<"{\"kind\":\"case\",\"name\":\""<<name<<"\",\"channel\":\""<<channel
 <<"\",\"precise\":"<<(precise?"true":"false")<<",\"grid\":[";
 for(std::size_t i=0;i<grid.size();i++){if(i)std::cout<<',';std::cout<<"["<<grid[i].mjdInt()<<",\""<<hex(grid[i].mjdMod())<<"\",\""<<hex(data(i,0))<<"\"]";}
 std::cout<<"],\"outputs\":[";
 for(std::size_t i=0;i<queries.size();i++){
  if(i)std::cout<<',';
  const long double actual=W::evaluate(metadata[i],[&](std::size_t k){return static_cast<long double>(data(k,0));});
  std::cout<<"{\"slot\":"<<i<<",\"time\":["<<queries[i].mjdInt()<<",\""<<hex(queries[i].mjdMod())
  <<"\"],\"native\":\""<<hex(native(i,0))<<"\",\"wide\":\""<<hex(actual)<<"\",\"stencil\":"<<encoded(metadata[i],grid.size())<<'}';
 }
 std::cout<<"]}\n";
}
int main()
{
 try{
  need(TIME_EPSILON>0 && TIME_EPSILON<1e-4,"unexpected installed Time epsilon");
  std::cout<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-native-batch-fixture-v1\",\"time_epsilon\":\""<<hex(TIME_EPSILON)<<"\",\"long_double_digits\":"<<std::numeric_limits<long double>::digits<<"}\n";
  std::vector<Time> times;for(unsigned i=0;i<33;i++)times.push_back(timeAt(5.L*i));
  Matrix data(times.size(),1);for(unsigned i=0;i<times.size();i++)data(i,0)=1.25+i*.37+(i%3)*.012;
  auto run=[&](const char *name,const std::vector<Time>&q,const Matrix&a,bool precise,bool jump,bool cut){
   if(precise)setenv("ORBIT_POC_NUMERICS_QR_PREFIX","supplemental-batch",1);else unsetenv("ORBIT_POC_NUMERICS_QR_PREFIX");
   unsetenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
   const std::vector<Time> boundaries=cut?std::vector<Time>{times[16]}:std::vector<Time>{};
   // Match staged propagation: boundary list is passed in both positions.
   OrbitPocPiecewisePolynomial interpolation(times,7,boundaries,boundaries);
   const Matrix actual=interpolation.interpolate(q,a,1,jump);
   const auto metadata=interpolation.orbitPocWideStateStencils(q,jump);
   emit(name,times,q,a,actual,metadata,jump?"velocity":"position",precise);
   return metadata;
  };
  std::vector<Time> mixed{timeAt(112),timeAt(12),timeAt(84),timeAt(12),timeAt(154),timeAt(78),times[16],timeAt(82)};
  run("unsorted_repeated",mixed,data,true,false,true);
  run("ordinary",mixed,data,false,false,true);
  run("singleton",{timeAt(11.25L)},data,true,false,false);
  auto identities=run("same_times",times,data,true,false,false);
  const long double low=1.L+std::ldexp(1.L,-60);
  need(low!=1.L,"long double does not retain chosen low part");
  for(std::size_t i=0;i<identities.size();i++)need(identities[i].mode==W::Mode::exact && W::evaluate(identities[i],[&](std::size_t){return low;})==low,"sameTimes lost exact low-part identity");
  const Time q1=times[10]+seconds2time(1.2L*TIME_EPSILON),q2=times[10]+seconds2time(.4L*TIME_EPSILON);
  need(!(q1<q2)&&!(q2<q1),"requested near-Time pair not tolerant equivalent");
  auto pair=run("near_epsilon",{q1,q2},data,true,false,false);
  // Scalar selection is diagnostic coverage only: never used for batch acceptance.
  auto scalar=run("near_epsilon_scalar_control",{q2},data,true,false,false);
  const bool differs=encoded(pair[1],times.size())!=encoded(scalar[0],times.size());
  need(differs,"near-Time case did not exercise stateful batch selection distinction");
  std::cout<<"{\"kind\":\"coverage\",\"scalar_batch_distinction\":true,\"identity_low_hex\":\""<<hex(low)<<"\"}\n";
  std::vector<Time> edge{timeAt(78),times[16],timeAt(82)};
  Matrix position(times.size(),1),velocity(times.size(),1),continuous(times.size(),1);
  for(unsigned i=0;i<times.size();i++){const double t=5.*i;position(i,0)=t+(t>=80?7.*(t-80):0);velocity(i,0)=3.+.01*t+(i>=16?7.:0.);continuous(i,0)=3.+.01*t;}
  auto ps=run("pulse_position",edge,position,true,false,true);
  auto vs=run("pulse_velocity",edge,velocity,true,true,true);
  auto ds=run("density_velocity",edge,continuous,true,true,true);
  run("density_position",edge,continuous,true,false,true);
  for(auto i:vs[0].indices)need(i<16,"left pulse velocity uses post-pulse endpoint");
  for(auto i:vs[1].indices)need(i>=16,"exact pulse velocity does not use right segment");
  need(vs[1].mode==W::Mode::exact && vs[1].indices[0]==16,"exact pulse is not post-pulse grid identity");
  need(ds[1].mode==W::Mode::exact && ds[1].indices[0]==16,"density exact boundary identity changed");
  std::cout<<"{\"kind\":\"complete\",\"cases\":10}\n";return 0;
 }catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}
}
