// Diagnostic only. Replay captured coefficients, retaining native thresholds.
#include <array>
#include <cmath>
#include <cstring>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>
void recordTangentTrace(unsigned,const std::vector<double>&,double,bool);
void recordTangentProjection(unsigned,double);
#include "wideSixStateTangent.h"

struct Capture {
  double dt,T;
  std::vector<OrbitPoc::ForceJacobian> main,pre;
  OrbitPoc::Quadrature weights;
  OrbitPoc::TangentVector rhs;
};
static Capture data;
static constexpr double tolerance=2e-12;
static_assert(__FLT128_MANT_DIG__==113,"binary128 oracle required");
static OrbitPoc::TangentVector lastPhysical,bestPhysical;
void finiteNumber(long double);
static unsigned observedIteration=0,bestObservedIteration=0;
static long double observedResidual=std::numeric_limits<long double>::infinity();
static long double bestObservedResidual=std::numeric_limits<long double>::infinity();

uint64_t u64(std::istream &in) {
  unsigned char bytes[8]; in.read(reinterpret_cast<char*>(bytes),8);
  if(!in) throw std::runtime_error("truncated uint64");
  uint64_t result=0; for(unsigned i=0;i<8;i++)result|=uint64_t(bytes[i])<<(8*i);
  return result;
}
double number(std::istream &in) {
  static_assert(sizeof(double)==8 && std::numeric_limits<double>::is_iec559,"IEEE754 binary64 required");
  uint64_t bits=u64(in); double result;std::memcpy(&result,&bits,8);
  if(!std::isfinite(result))throw std::runtime_error("nonfinite captured scalar");
  return result;
}
Capture readCapture(const char *path) {
  std::ifstream in(path,std::ios::binary); if(!in)throw std::runtime_error("cannot open capture");
  char magic[16];in.read(magic,16);
  if(!in || std::memcmp(magic,"OPCTANGENT001\n\0\0",16))throw std::runtime_error("incorrect capture magic");
  const auto schema=u64(in),n=u64(in),intervals=u64(in),terms=u64(in),rhsCount=u64(in);
  if(schema!=1 || n<2 || n>1000000 || intervals!=n-1 || rhsCount!=6*n || terms>100*intervals)
    throw std::runtime_error("invalid captured dimensions");
  Capture out;out.dt=number(in);out.T=number(in);
  if(!(out.dt>0 && out.T>0))throw std::runtime_error("invalid captured time");
  out.main.resize(n);out.pre.resize(n);
  for(auto *matrix:{&out.main,&out.pre})for(auto &node:*matrix) {
    for(double &v:node.position)v=number(in);
    for(double &v:node.velocity)v=number(in);
  }
  out.weights.resize(intervals);uint64_t counted=0;
  for(auto &interval:out.weights) {
    auto count=u64(in);if(count>100 || count+counted>terms)throw std::runtime_error("invalid interval term count");
    counted+=count;
    for(uint64_t k=0;k<count;k++) {
      auto index=u64(in);if(index>=n)throw std::runtime_error("captured sample index outside grid");
      double integral=number(in),moment=number(in);
      interval.push_back({unsigned(index),integral,moment});
    }
  }
  if(counted!=terms)throw std::runtime_error("quadrature total mismatch");
  out.rhs.resize(rhsCount);for(double &v:out.rhs)v=number(in);
  if(in.peek()!=std::char_traits<char>::eof())throw std::runtime_error("unexpected trailing capture data");
  return out;
}


// Independent binary128 evaluation of the actual returned physical-double
// state. Balance velocity in the residual, without a lossy state round trip.
long double physicalQuadResidual(const OrbitPoc::TangentVector &state) {
  const unsigned n=data.main.size(),offset=3*n;
  if(state.size()!=data.rhs.size())throw std::runtime_error("oracle state shape differs");
  std::vector<__float128> acceleration(offset);
  for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
    acceleration[3*k+i]+=static_cast<__float128>(data.main[k].position[3*i+j])*state[3*k+j]
      +static_cast<__float128>(data.main[k].velocity[3*i+j])*state[offset+3*k+j];
  __float128 p[3]{},v[3]{},sum=0,norm=0;
  for(unsigned k=0;k<n;k++) {
    if(k)for(unsigned i=0;i<3;i++) {
      __float128 integral=0,moment=0;
      for(const auto &term:data.weights[k-1]) {
        integral+=static_cast<__float128>(term.integral)*acceleration[3*term.index+i];
        moment+=static_cast<__float128>(term.moment)*acceleration[3*term.index+i];
      }
      p[i]+=static_cast<__float128>(data.dt)*(v[i]+integral)-moment;v[i]+=integral;
    }
    for(unsigned i=0;i<3;i++) {
      const __float128 bp=data.rhs[3*k+i],bv=static_cast<__float128>(data.rhs[offset+3*k+i])*1000;
      const __float128 rp=bp-state[3*k+i]+p[i];
      const __float128 rv=(static_cast<__float128>(data.rhs[offset+3*k+i])-state[offset+3*k+i]+v[i])*1000;
      sum+=rp*rp+rv*rv;norm+=bp*bp+bv*bv;
    }
  }
  if(norm==0)return sum==0?0.L:std::numeric_limits<long double>::infinity();
  return std::sqrt(static_cast<long double>(sum/norm));
}
void keepState(unsigned iteration,const OrbitPoc::TangentVector &physical,long double relative) {
  lastPhysical=physical;observedIteration=iteration;observedResidual=relative;
  if(std::isfinite(relative) && relative<bestObservedResidual)
  {bestPhysical=physical;bestObservedIteration=iteration;bestObservedResidual=relative;}
}
void recordTangentTrace(unsigned iteration,const std::vector<double> &scaled,double relative,bool final) {
  auto physical=scaled;for(unsigned i=physical.size()/2;i<physical.size();i++)physical[i]*=(1./1000.);
  keepState(iteration,physical,relative);
  std::cout<<"{\"kind\":\"legacy_true_residual\",\"iteration\":"<<iteration
    <<",\"relative_residual\":";finiteNumber(relative);std::cout<<",\"final\":"<<(final?"true":"false")<<"}\n";
}
void recordTangentProjection(unsigned iteration,double relative) {
  std::cout<<"{\"kind\":\"legacy_projected_residual\",\"iteration\":"<<iteration
    <<",\"relative_residual\":";finiteNumber(relative);std::cout<<"}\n";
}
void wideTrace(unsigned iteration,const OrbitPoc::TangentVector &physical,long double internal,long double returned) {
  keepState(iteration,physical,returned);
  std::cout<<"{\"kind\":\"wide_returned_state_check\",\"iteration\":"<<iteration
    <<",\"internal_relative_residual\":";finiteNumber(internal);
  std::cout<<",\"physical_double_relative_residual\":";finiteNumber(returned);std::cout<<"}\n";
}
void finiteNumber(long double v) {if(std::isfinite(v))std::cout<<v;else std::cout<<"null";}
void oracleRecord(const char *label,unsigned iteration,const OrbitPoc::TangentVector &physical,
    long double residual=std::numeric_limits<long double>::quiet_NaN()) {
  if(physical.empty())return;
  std::cout<<"{\"kind\":\"physical_double_quad_residual\",\"selection\":\""<<label
    <<"\",\"iteration\":"<<iteration<<",\"binary_digits\":"<<__FLT128_MANT_DIG__<<",\"relative_residual\":";
  finiteNumber(std::isnan(residual)?physicalQuadResidual(physical):residual);std::cout<<"}\n";
}
int main(int argc,char **argv) {
  std::cout<<std::setprecision(21);
  if(argc!=3 || (std::string(argv[1])!="baseline" && std::string(argv[1])!="wide"))
  {std::cerr<<"usage: replay baseline|wide capture.bin\n";return 2;}
  const bool wide=std::string(argv[1])=="wide";
  try {
    data=readCapture(argv[2]);const unsigned n=data.main.size(),offset=3*n;
    std::cout<<"{\"kind\":\"input\",\"profile\":\""<<argv[1]<<"\",\"epochs\":"<<n
      <<",\"dt\":"<<data.dt<<",\"duration\":"<<data.T<<",\"tolerance\":2e-12,\"maximum_iterations\":120,\"restart\":20,\"extended_digits\":"
      <<std::numeric_limits<long double>::digits<<"}\n";
    auto integrated=[&](const OrbitPoc::TangentVector &state) {
      std::vector<long double> acceleration(offset);
      for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
        acceleration[3*k+i]+=static_cast<long double>(data.main[k].position[3*i+j])*state[3*k+j]
          +static_cast<long double>(data.main[k].velocity[3*i+j])*state[offset+3*k+j];
      return OrbitPoc::tangentIntegrate(data.weights,data.dt,acceleration);
    };
    auto integratedWide=[&](const OrbitPoc::WideTangentVector &state) {
      std::vector<long double> acceleration(offset);
      for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
        acceleration[3*k+i]+=static_cast<long double>(data.main[k].position[3*i+j])*state[3*k+j]
          +static_cast<long double>(data.main[k].velocity[3*i+j])*state[offset+3*k+j];
      return OrbitPoc::wideTangentIntegrate(data.weights,data.dt,acceleration);
    };
    const auto solved=wide?OrbitPoc::solveSixStateTangentWide(data.pre,data.dt,integratedWide,data.rhs,tolerance,120,20,wideTrace)
                          :OrbitPoc::solveSixStateTangent(data.pre,data.dt,integrated,data.rhs);
    const long double oracle=physicalQuadResidual(solved.state);
    oracleRecord("returned",solved.iterations,solved.state,oracle);
    const bool passed=std::isfinite(oracle) && oracle<=static_cast<long double>(tolerance);
    std::cout<<"{\"kind\":\"terminal\",\"status\":\""<<(passed?"passed":"failed")
      <<"\",\"kernel_status\":\"passed\",\"iterations\":"<<solved.iterations<<",\"relative_residual\":"<<solved.relativeResidual
      <<",\"physical_double_quad_relative_residual\":";finiteNumber(oracle);std::cout<<"}\n";
    return passed?0:1;
  } catch(const std::exception &error) {
    oracleRecord("best_kernel_checked",bestObservedIteration,bestPhysical);
    oracleRecord("last_checked",observedIteration,lastPhysical);
    std::cout<<"{\"kind\":\"terminal\",\"status\":\"failed\",\"kernel_status\":\"failed\",\"iterations\":"
      <<observedIteration<<",\"relative_residual\":";finiteNumber(observedResidual);std::cout<<"}\n";
    std::cerr<<error.what()<<'\n';return 1;
  }
}
