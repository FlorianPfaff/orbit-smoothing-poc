// Actual native Polynomial/Matrix exercise; linked with the selected GROOPS build.
#include "base/import.h"
#include "base/polynomial.h"
#include "misc/orbitPoc/nuisancePerformance.h"
#include <iomanip>
#include <limits>
#include <memory>

int main(int argc, char **argv)
{
  if(argc != 3) return 2;
  const std::string queryKind=argv[1], scope=argv[2];
  if(scope!="cost" && scope!="full" && scope!="outside") return 2;
  std::vector<Time> times;
  for(UInt i=0;i<4;i++) times.emplace_back(60000, Double(10*i)/86400.);
  // Explicit zero extrapolation makes the invalid-domain tests unambiguous.
  Polynomial polynomial(times,3,TRUE,FALSE,40.,0.);
  Matrix design(12,5);
  for(UInt epoch=0;epoch<4;epoch++)
    for(UInt axis=0;axis<3;axis++)
      for(UInt column=0;column<5;column++)
        design(3*epoch+axis,column)=10.*(axis+1)+(column+1)*10.*epoch;
  Time query(60000,5./86400.);
  long double remainder=0.L;
  if(queryKind=="grid") query=times.at(1);
  else if(queryKind=="offgrid") {}
  else if(queryKind=="remainder") remainder=1e-9L;
  else if(queryKind=="negative_remainder") remainder=-1e-9L;
  else if(queryKind=="negative_zero") remainder=-0.L;
  else if(queryKind=="outside_before") query=Time(60000,-20./86400.);
  else if(queryKind=="outside_after") query=Time(60000,50./86400.);
  else if(queryKind=="nan_remainder") remainder=std::numeric_limits<long double>::quiet_NaN();
  else if(queryKind=="infinite_remainder") remainder=std::numeric_limits<long double>::infinity();
  else if(queryKind=="oversized_remainder") remainder=2e-8L;
  else return 2;
  UInt validations=0,computations=0;
  Matrix result;
  std::string error;
  try
  {
    // This is the exact zero-column validator and original interpolation call
    // used by the native Leo design hook; no Matrix or Polynomial API stubs.
    auto invoke=[&]()
    {
      return orbitPocNuisancePerformance::dynamicDesign(design.columns(),
        [&](){validations++;polynomial.interpolateOffset({query},design.column(0,0),{remainder},3);},
        [&](){computations++;return polynomial.interpolateOffset({query},design,{remainder},3);});
    };
    if(scope=="outside") result=invoke();
    else
    {
      orbitPocNuisancePerformance::BuildMeasure build(TRUE,scope=="cost");
      result=invoke();
    }
  }
  catch(const std::exception &exception){error=exception.what();}
  if(orbitPocNuisancePerformance::context().active) return 3;
  bool allZero=true,allFinite=true;
  Double maximum=0.,difference=0.;
  if(error.empty())
  {
    if(result.rows()!=3||result.columns()!=5) return 4;
    const Matrix direct=polynomial.interpolateOffset({query},design,{remainder},3);
    for(UInt row=0;row<result.rows();row++)
      for(UInt column=0;column<result.columns();column++)
      {
        const Double value=result(row,column);
        allZero=allZero&&(value==0.);allFinite=allFinite&&std::isfinite(value);
        maximum=std::max(maximum,std::fabs(value));
        difference=std::max(difference,std::fabs(value-direct(row,column)));
      }
  }
  // GROOPS stack strings can contain newlines; std::quoted alone is not JSON.
  std::string escaped;
  for(unsigned char value:error)
  {
    if(value=='\\'||value=='"'){escaped+='\\';escaped+=char(value);}
    else if(value=='\n')escaped+="\\n";
    else if(value=='\r')escaped+="\\r";
    else if(value=='\t')escaped+="\\t";
    else if(value<32)escaped+=' ';
    else escaped+=char(value);
  }
  std::cout<<std::setprecision(17)<<"{\"rejected\":"<<(!error.empty()?"true":"false")
    <<",\"error\":\""<<escaped<<"\",\"validations\":"<<validations<<",\"computations\":"<<computations
    <<",\"rows\":"<<result.rows()<<",\"columns\":"<<result.columns()
    <<",\"all_zero\":"<<(allZero?"true":"false")<<",\"all_finite\":"<<(allFinite?"true":"false")
    <<",\"maximum_absolute_value\":"<<maximum<<",\"difference_from_native_full_interpolation\":"<<difference
    <<",\"context_active_after\":false,\"omitted_dynamic_designs\":"<<orbitPocNuisancePerformance::metrics().omittedDynamicDesigns
    <<"}\n";
  return 0;
}
