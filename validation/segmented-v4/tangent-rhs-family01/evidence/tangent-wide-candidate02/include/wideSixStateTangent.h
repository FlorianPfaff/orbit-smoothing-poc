// Diagnostic candidate: extended arithmetic with explicit native-double acceptance.
#ifndef ORBIT_POC_WIDE_SIX_STATE_TANGENT_H
#define ORBIT_POC_WIDE_SIX_STATE_TANGENT_H
#include "sixStateTangent.h"
#include <array>

namespace OrbitPoc {
using WideTangentVector=std::vector<long double>;
using WideTangentOperator=std::function<WideTangentVector(const WideTangentVector &)>;
using WideTangentTrace=std::function<void(unsigned,const TangentVector &,long double,long double)>;

inline long double wideTangentDot(const WideTangentVector &a,const WideTangentVector &b)
{
  TangentCompensatedSum sum;
  for(unsigned i=0;i<a.size();i++)sum.add(a[i]*b[i]);
  return sum.value();
}
inline long double wideTangentNorm(const WideTangentVector &a)
{return std::sqrt(wideTangentDot(a,a));}
inline void wideTangentAxpy(long double factor,const WideTangentVector &a,WideTangentVector &b)
{for(unsigned i=0;i<a.size();i++)b[i]+=factor*a[i];}

// Same stored quadrature as tangentIntegrate. Keep extended output for K*x;
// the existing double-output force/RHS construction remains a separate API.
inline WideTangentVector wideTangentIntegrate(const Quadrature &weights,double dt,
    const std::vector<long double> &acceleration)
{
  if(!(dt>0) || acceleration.size()%3)throw std::runtime_error("invalid wide tangent samples");
  const unsigned offset=3*(weights.size()+1);
  WideTangentVector result(2*offset);
  TangentCompensatedSum position[3],velocity[3];
  for(unsigned k=0;k<weights.size();k++)for(unsigned i=0;i<3;i++)
  {
    TangentCompensatedSum integral,moment;
    for(const auto &term:weights[k])
    {
      if(3*term.index+i>=acceleration.size())throw std::runtime_error("wide tangent sample outside grid");
      integral.add(static_cast<long double>(term.integral)*acceleration[3*term.index+i]);
      moment.add(static_cast<long double>(term.moment)*acceleration[3*term.index+i]);
    }
    position[i].add(static_cast<long double>(dt)*velocity[i].high);
    position[i].add(static_cast<long double>(dt)*velocity[i].low);
    position[i].add(static_cast<long double>(dt)*integral.high);
    position[i].add(static_cast<long double>(dt)*integral.low);
    position[i].add(-moment.high);position[i].add(-moment.low);
    velocity[i].add(integral.high);velocity[i].add(integral.low);
    result[3*(k+1)+i]=position[i].value();
    result[offset+3*(k+1)+i]=velocity[i].value();
  }
  return result;
}
using WideTangentVec3=std::array<long double,3>;
using WideTangentMat3=std::array<long double,9>;
inline WideTangentVec3 wideTangentSolve3(WideTangentMat3 a,WideTangentVec3 b)
{
  for(unsigned j=0;j<3;j++)
  {
    unsigned pivot=j;for(unsigned i=j+1;i<3;i++)if(std::abs(a[3*i+j])>std::abs(a[3*pivot+j]))pivot=i;
    // Preserve the existing local-pivot rejection limit.
    if(!(std::abs(a[3*pivot+j])>std::numeric_limits<double>::epsilon()))
      throw std::runtime_error("singular wide tangent preconditioner");
    if(pivot!=j){for(unsigned k=0;k<3;k++)std::swap(a[3*j+k],a[3*pivot+k]);std::swap(b[j],b[pivot]);}
    for(unsigned i=j+1;i<3;i++)
    {const long double f=a[3*i+j]/a[3*j+j];for(unsigned k=j;k<3;k++)a[3*i+k]-=f*a[3*j+k];b[i]-=f*b[j];}
  }
  for(int j=2;j>=0;j--){for(unsigned k=j+1;k<3;k++)b[j]-=a[3*j+k]*b[k];b[j]/=a[3*j+j];}
  return b;
}
inline WideTangentVector wideTangentPrecondition(const std::vector<ForceJacobian> &jac,
    double dt,const WideTangentVector &b)
{
  const unsigned n=jac.size(),offset=3*n;
  if(!n || b.size()!=6*n || !(dt>0))throw std::runtime_error("invalid wide tangent dimensions");
  const long double d=dt;WideTangentVector x=b;
  WideTangentVec3 integral{},position{},previous{};
  for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
    previous[i]+=static_cast<long double>(jac[0].position[3*i+j])*x[j]
                 +static_cast<long double>(jac[0].velocity[3*i+j])*x[offset+j];
  for(unsigned k=1;k<n;k++)
  {
    WideTangentVec3 p{},v{},acc{};WideTangentMat3 local{};
    for(unsigned i=0;i<3;i++)
    {p[i]=b[3*k+i]+position[i]+d*integral[i]+d*d*previous[i]/3.L;v[i]=b[offset+3*k+i]+integral[i]+d*previous[i]/2.L;}
    for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
    {
      local[3*i+j]=(i==j?1.L:0.L)-d*d*jac[k].position[3*i+j]/6.L-d*jac[k].velocity[3*i+j]/2.L;
      acc[i]+=static_cast<long double>(jac[k].position[3*i+j])*p[j]
              +static_cast<long double>(jac[k].velocity[3*i+j])*v[j];
    }
    acc=wideTangentSolve3(local,acc);
    for(unsigned i=0;i<3;i++)
    {
      x[3*k+i]=p[i]+d*d*acc[i]/6.L;x[offset+3*k+i]=v[i]+d*acc[i]/2.L;
      position[i]+=d*integral[i]+d*d*(previous[i]/3.L+acc[i]/6.L);
      integral[i]+=d*(previous[i]+acc[i])/2.L;previous[i]=acc[i];
    }
  }
  return x;
}

// New explicit interface. The original double API and its defaults are intact.
// The accepted object is the returned physical binary64 state, after velocity
// unscaling. Neither its unrounded precursor nor a damped/projected residual
// can certify convergence.
inline TangentSolveResult solveSixStateTangentWide(const std::vector<ForceJacobian> &jac,
    double dt,const WideTangentOperator &integratedAcceleration,const TangentVector &rhs,
    double tolerance=2e-12,unsigned maximumIterations=120,unsigned restart=20,
    const WideTangentTrace &trace={})
{
  const unsigned offset=3*jac.size();
  if(std::numeric_limits<long double>::digits<=std::numeric_limits<double>::digits)
    throw std::runtime_error("extended tangent arithmetic unavailable");
  if(!offset || rhs.size()!=2*offset || !restart || !(dt>0) || !std::isfinite(dt)
      || !(tolerance>0) || !std::isfinite(tolerance))throw std::runtime_error("invalid wide tangent input");
  for(double v:rhs)if(!std::isfinite(v))throw std::runtime_error("nonfinite wide tangent RHS");
  for(const auto &j:jac)
  {for(double v:j.position)if(!std::isfinite(v))throw std::runtime_error("nonfinite wide position Jacobian");
   for(double v:j.velocity)if(!std::isfinite(v))throw std::runtime_error("nonfinite wide velocity Jacobian");}
  auto scale=[&](WideTangentVector x){for(unsigned i=offset;i<x.size();i++)x[i]*=1000.L;return x;};
  auto unscale=[&](WideTangentVector x){for(unsigned i=offset;i<x.size();i++)x[i]/=1000.L;return x;};
  auto integral=[&](const WideTangentVector &physical)
  {
    auto y=integratedAcceleration(physical);
    if(y.size()!=physical.size())throw std::runtime_error("wide tangent integral shape mismatch");
    for(long double v:y)if(!std::isfinite(v))throw std::runtime_error("nonfinite wide tangent integral");
    return y;
  };
  auto op=[&](const WideTangentVector &x)
  {auto y=scale(integral(unscale(x)));for(unsigned i=0;i<y.size();i++)y[i]=x[i]-y[i];return y;};
  auto pre=[&](const WideTangentVector &x)
  {return scale(wideTangentPrecondition(jac,dt,unscale(x)));};
  const WideTangentVector physicalRhs(rhs.begin(),rhs.end()),b=scale(physicalRhs);
  const long double normB=wideTangentNorm(b);
  if(!std::isfinite(normB))throw std::runtime_error("nonfinite wide tangent norm");
  TangentSolveResult result;result.state.assign(rhs.size(),0.);
  if(normB==0)return result;
  WideTangentVector x=pre(b);
  auto checkReturned=[&](long double internalResidual)
  {
    auto physical=unscale(x);
    for(unsigned i=0;i<physical.size();i++)
    {result.state[i]=static_cast<double>(physical[i]);physical[i]=result.state[i];}
    auto residual=integral(physical);
    for(unsigned i=0;i<residual.size();i++)residual[i]+=physicalRhs[i]-physical[i];
    const long double relative=wideTangentNorm(scale(residual))/normB;
    result.relativeResidual=static_cast<double>(relative);
    if(trace)trace(result.iterations,result.state,internalResidual,relative);
    return std::isfinite(relative) && relative<=static_cast<long double>(tolerance);
  };
  while(result.iterations<maximumIterations)
  {
    auto residual=b;wideTangentAxpy(-1.L,op(x),residual);
    const long double beta=wideTangentNorm(residual);
    if(checkReturned(beta/normB))return result;
    if(!(beta>0) || !std::isfinite(beta))throw std::runtime_error("wide tangent cannot certify returned state");
    const unsigned capacity=std::min(restart,maximumIterations-result.iterations);
    std::vector<WideTangentVector> basis{residual},z;
    for(long double &v:basis[0])v/=beta;
    std::vector<std::vector<long double>> h(capacity+1,std::vector<long double>(capacity));
    std::vector<long double> cosine(capacity),sine(capacity),g(capacity+1);g[0]=beta;
    unsigned count=0;
    for(unsigned j=0;j<capacity;j++)
    {
      z.push_back(pre(basis[j]));auto w=op(z.back());
      for(unsigned pass=0;pass<2;pass++)for(unsigned i=0;i<=j;i++)
      {const long double projection=wideTangentDot(w,basis[i]);h[i][j]+=projection;wideTangentAxpy(-projection,basis[i],w);}
      h[j+1][j]=wideTangentNorm(w);const bool exhausted=h[j+1][j]<1e-30L;
      if(!exhausted){for(long double &v:w)v/=h[j+1][j];basis.push_back(std::move(w));}
      for(unsigned i=0;i<j;i++)
      {const long double v=cosine[i]*h[i][j]+sine[i]*h[i+1][j];h[i+1][j]=-sine[i]*h[i][j]+cosine[i]*h[i+1][j];h[i][j]=v;}
      const long double denominator=std::hypot(h[j][j],h[j+1][j]);
      if(!(denominator>0))throw std::runtime_error("wide tangent Krylov breakdown");
      cosine[j]=h[j][j]/denominator;sine[j]=h[j+1][j]/denominator;
      h[j][j]=denominator;h[j+1][j]=0;g[j+1]=-sine[j]*g[j];g[j]*=cosine[j];
      count=j+1;result.iterations++;
      if(std::abs(g[j+1])<=static_cast<long double>(tolerance)*normB || exhausted)break;
    }
    std::vector<long double> y(count);
    for(int j=int(count)-1;j>=0;j--)
    {y[j]=g[j];for(unsigned k=j+1;k<count;k++)y[j]-=h[j][k]*y[k];y[j]/=h[j][j];}
    for(unsigned i=0;i<x.size();i++)
    {TangentCompensatedSum value;value.add(x[i]);for(unsigned j=0;j<count;j++)value.add(y[j]*z[j][i]);x[i]=value.value();}
  }
  auto residual=b;wideTangentAxpy(-1.L,op(x),residual);
  if(checkReturned(wideTangentNorm(residual)/normB))return result;
  std::ostringstream message;message.precision(17);
  message<<"wide tangent returned double state did not meet true residual tolerance: relative_residual="
         <<result.relativeResidual<<", tolerance="<<tolerance<<", iterations="<<result.iterations;
  throw std::runtime_error(message.str());
}
}
#endif
