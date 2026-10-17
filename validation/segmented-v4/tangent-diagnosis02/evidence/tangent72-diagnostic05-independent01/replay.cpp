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
#include "sixStateTangent.h"

struct Capture {
  double dt,T;
  std::vector<OrbitPoc::ForceJacobian> main,pre;
  OrbitPoc::Quadrature weights;
  OrbitPoc::TangentVector rhs;
};
static Capture data;
static std::vector<double> lastState;
static unsigned lastIteration=0;
static double lastResidual=0;

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

// Independent extended-precision evaluation on the same captured coefficients.
// The native callback's binary64 velocity conversion is optionally reproduced.
long double preciseResidual(const std::vector<double>& scaled,bool nativeVelocityConversion) {
  const unsigned n=data.main.size(),offset=3*n;
  std::vector<long double> acceleration(offset);
  for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++) {
    const long double velocity=nativeVelocityConversion ?
      static_cast<long double>(scaled[offset+3*k+j]*(1./1000.)) :
      static_cast<long double>(scaled[offset+3*k+j])/1000.L;
    acceleration[3*k+i]+=static_cast<long double>(data.main[k].position[3*i+j])*scaled[3*k+j]
      +static_cast<long double>(data.main[k].velocity[3*i+j])*velocity;
  }
  long double p[3]{},v[3]{},sum=0,norm=0;
  for(unsigned k=0;k<n;k++) {
    if(k) for(unsigned i=0;i<3;i++) {
      long double integral=0,moment=0;
      for(const auto &term:data.weights[k-1]) {
        integral+=static_cast<long double>(term.integral)*acceleration[3*term.index+i];
        moment+=static_cast<long double>(term.moment)*acceleration[3*term.index+i];
      }
      p[i]+=static_cast<long double>(data.dt)*(v[i]+integral)-moment;v[i]+=integral;
    }
    for(unsigned i=0;i<3;i++) {
      const double bp=data.rhs[3*k+i],bv=data.rhs[offset+3*k+i]*1000.;
      const long double rp=static_cast<long double>(bp)-scaled[3*k+i]+p[i];
      const long double rv=static_cast<long double>(bv)-scaled[offset+3*k+i]+1000.L*v[i];
      sum+=rp*rp+rv*rv;norm+=static_cast<long double>(bp)*bp+static_cast<long double>(bv)*bv;
    }
  }
  return std::sqrt(sum/norm);
}
long double quadResidual(const std::vector<double>& scaled,bool nativeVelocityConversion) {
  const unsigned n=data.main.size(),offset=3*n;
  std::vector<__float128> acceleration(offset);
  for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++) {
    const __float128 velocity=nativeVelocityConversion ?
      static_cast<__float128>(scaled[offset+3*k+j]*(1./1000.)) :
      static_cast<__float128>(scaled[offset+3*k+j])/1000.L;
    acceleration[3*k+i]+=static_cast<__float128>(data.main[k].position[3*i+j])*scaled[3*k+j]
      +static_cast<__float128>(data.main[k].velocity[3*i+j])*velocity;
  }
  __float128 p[3]{},v[3]{},sum=0,norm=0;
  for(unsigned k=0;k<n;k++) {
    if(k) for(unsigned i=0;i<3;i++) {
      __float128 integral=0,moment=0;
      for(const auto &term:data.weights[k-1]) {
        integral+=static_cast<__float128>(term.integral)*acceleration[3*term.index+i];
        moment+=static_cast<__float128>(term.moment)*acceleration[3*term.index+i];
      }
      p[i]+=static_cast<__float128>(data.dt)*(v[i]+integral)-moment;v[i]+=integral;
    }
    for(unsigned i=0;i<3;i++) {
      const double bp=data.rhs[3*k+i],bv=data.rhs[offset+3*k+i]*1000.;
      const __float128 rp=static_cast<__float128>(bp)-scaled[3*k+i]+p[i];
      const __float128 rv=static_cast<__float128>(bv)-scaled[offset+3*k+i]+1000.L*v[i];
      sum+=rp*rp+rv*rv;norm+=static_cast<__float128>(bp)*bp+static_cast<__float128>(bv)*bv;
    }
  }
  return std::sqrt(static_cast<long double>(sum/norm));
}
void recordTangentTrace(unsigned iter,const std::vector<double>&x,double residual,bool final) {
  lastState=x;lastIteration=iter;lastResidual=residual;
  if(final || iter==6)std::cout<<"{\"kind\":\"quad_residual\",\"iteration\":"<<iter
    <<",\"binary_digits\":"<<__FLT128_MANT_DIG__
    <<",\"relative_residual_native_velocity_conversion\":"<<quadResidual(x,true)
    <<",\"relative_residual_exact_velocity_conversion\":"<<quadResidual(x,false)<<"}\n"<<std::flush;
  std::cout<<"{\"kind\":\"true_residual\",\"iteration\":"<<iter<<",\"final\":"<<(final?"true":"false")
    <<",\"native_relative_residual\":"<<residual
    <<",\"extended_residual_native_velocity_conversion\":"<<preciseResidual(x,true)
    <<",\"extended_residual_exact_velocity_conversion\":"<<preciseResidual(x,false)
    <<",\"native_solution_norm\":"<<OrbitPoc::tangentNorm(x)<<"}\n"<<std::flush;
}
void recordTangentProjection(unsigned iter,double residual) {
  std::cout<<"{\"kind\":\"projected_residual\",\"iteration\":"<<iter<<",\"relative_residual\":"<<residual<<"}\n";
}

int main(int argc,char **argv) {
  std::cout<<std::setprecision(21);
  if(argc!=2){std::cerr<<"usage: replay captured-system.bin\n";return 2;}
  try {
    data=readCapture(argv[1]);const unsigned n=data.main.size(),offset=3*n;
    std::cout<<"{\"kind\":\"input\",\"epochs\":"<<n<<",\"dt\":"<<data.dt<<",\"duration\":"<<data.T
      <<",\"tolerance\":2e-12,\"maximum_iterations\":120,\"restart\":20,\"extended_digits\":"
      <<std::numeric_limits<long double>::digits<<"}\n";
    auto integrated=[&](const OrbitPoc::TangentVector &state) {
      std::vector<long double> acceleration(offset);
      for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
        acceleration[3*k+i]+=static_cast<long double>(data.main[k].position[3*i+j])*state[3*k+j]
          +static_cast<long double>(data.main[k].velocity[3*i+j])*state[offset+3*k+j];
      return OrbitPoc::tangentIntegrate(data.weights,data.dt,acceleration);
    };
    const auto solved=OrbitPoc::solveSixStateTangent(data.pre,data.dt,integrated,data.rhs);
    std::cout<<"{\"kind\":\"accepted_quad_residual\",\"iteration\":"<<lastIteration
      <<",\"binary_digits\":"<<__FLT128_MANT_DIG__
      <<",\"relative_residual_native_velocity_conversion\":"<<quadResidual(lastState,true)
      <<",\"relative_residual_exact_velocity_conversion\":"<<quadResidual(lastState,false)<<"}\n"<<std::flush;
    std::cout<<"{\"kind\":\"terminal\",\"status\":\"passed\",\"iterations\":"<<solved.iterations
      <<",\"relative_residual\":"<<solved.relativeResidual<<"}\n";return 0;
  } catch(const std::exception &error) {
    // Native diagnostic strings contain no quotes or newlines; keep arbitrary
    // reader errors out of JSON and preserve them on stderr instead.
    std::cerr<<error.what()<<'\n';
    std::cout<<"{\"kind\":\"terminal\",\"status\":\"failed\",\"iterations\":"<<lastIteration
      <<",\"relative_residual\":"<<lastResidual<<"}\n";return 1;
  }
}
