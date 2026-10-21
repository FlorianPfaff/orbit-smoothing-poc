// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_SIX_STATE_TANGENT_H
#define ORBIT_POC_SIX_STATE_TANGENT_H
#include "syntheticForceDerivatives.h"
#include "eventQuadrature.h"
#include <algorithm>
#include <functional>
#include <limits>
#include <sstream>
#include <vector>

namespace OrbitPoc
{
using TangentVector=std::vector<double>;
using TangentOperator=std::function<TangentVector(const TangentVector &)>;
inline double tangentDot(const TangentVector &a,const TangentVector &b)
{long double sum=0;for(unsigned i=0;i<a.size();i++)sum+=static_cast<long double>(a[i])*b[i];return double(sum);}
inline double tangentNorm(const TangentVector &a) {return std::sqrt(tangentDot(a,a));}
inline void tangentAxpy(double factor,const TangentVector &x,TangentVector &y)
{for(unsigned i=0;i<x.size();i++)y[i]+=factor*x[i];}

// The same interval quadrature evaluated with local moments and extended
// accumulators. Forming t*integral(a)-integral(t*a) over a full orbital day
// loses the small residual needed by the coupled solve. No weights or physical
// model are changed: moment is the integral of (time-interval_start)*a.
inline TangentVector tangentIntegrate(const Quadrature &weights,double dt,
    const std::vector<long double> &acceleration)
{
  if(!(dt>0) || acceleration.size()%3)throw std::runtime_error("invalid tangent quadrature samples");
  const unsigned offset=3*(weights.size()+1);
  TangentVector result(2*offset);
  long double position[3]{},velocity[3]{};
  for(unsigned k=0;k<weights.size();k++)for(unsigned i=0;i<3;i++)
  {
    long double integral=0,moment=0;
    for(const auto &term:weights[k])
    {
      if(3*term.index+i>=acceleration.size())throw std::runtime_error("tangent quadrature index out of range");
      integral+=static_cast<long double>(term.integral)*acceleration[3*term.index+i];
      moment+=static_cast<long double>(term.moment)*acceleration[3*term.index+i];
    }
    position[i]+=static_cast<long double>(dt)*(velocity[i]+integral)-moment;
    velocity[i]+=integral;
    result[3*(k+1)+i]=double(position[i]);result[offset+3*(k+1)+i]=double(velocity[i]);
  }
  return result;
}

inline Vec3 tangentSolve3(Mat3 a,Vec3 b)
{
  for(unsigned j=0;j<3;j++)
  {
    unsigned pivot=j;for(unsigned i=j+1;i<3;i++)if(std::abs(a[3*i+j])>std::abs(a[3*pivot+j]))pivot=i;
    if(!(std::abs(a[3*pivot+j])>std::numeric_limits<double>::epsilon()))
      throw std::runtime_error("singular local six-state tangent preconditioner");
    if(pivot!=j){for(unsigned k=0;k<3;k++)std::swap(a[3*j+k],a[3*pivot+k]);std::swap(b[j],b[pivot]);}
    for(unsigned i=j+1;i<3;i++){double f=a[3*i+j]/a[3*j+j];for(unsigned k=j;k<3;k++)a[3*i+k]-=f*a[3*j+k];b[i]-=f*b[j];}
  }
  for(int j=2;j>=0;j--){for(unsigned k=j+1;k<3;k++)b[j]-=a[3*j+k]*b[k];b[j]/=a[3*j+j];}
  return b;
}

// Approximate inverse of the coupled Volterra operator using piecewise-linear
// acceleration. The real residual always uses the caller's high-order integral.
// State layout: all position triples followed by all velocity triples.
inline TangentVector tangentPrecondition(const std::vector<ForceJacobian> &jac,double dt,const TangentVector &b)
{
  const unsigned n=jac.size(),offset=3*n;
  if(n==0 || b.size()!=6*n || !(dt>0))throw std::runtime_error("invalid six-state tangent dimensions");
  TangentVector x=b;Vec3 integral{},position{},previous{};
  for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
    previous[i]+=jac[0].position[3*i+j]*x[j]+jac[0].velocity[3*i+j]*x[offset+j];
  for(unsigned k=1;k<n;k++)
  {
    Vec3 p{},v{},acc{};Mat3 local{};
    for(unsigned i=0;i<3;i++)
    {p[i]=b[3*k+i]+position[i]+dt*integral[i]+dt*dt*previous[i]/3;v[i]=b[offset+3*k+i]+integral[i]+dt*previous[i]/2;}
    for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
    {
      local[3*i+j]=(i==j ? 1. : 0.)-dt*dt*jac[k].position[3*i+j]/6-dt*jac[k].velocity[3*i+j]/2;
      acc[i]+=jac[k].position[3*i+j]*p[j]+jac[k].velocity[3*i+j]*v[j];
    }
    acc=tangentSolve3(local,acc);
    for(unsigned i=0;i<3;i++)
    {
      x[3*k+i]=p[i]+dt*dt*acc[i]/6;x[offset+3*k+i]=v[i]+dt*acc[i]/2;
      position[i]+=dt*integral[i]+dt*dt*(previous[i]/3+acc[i]/6);
      integral[i]+=dt*(previous[i]+acc[i])/2;previous[i]=acc[i];
    }
  }
  return x;
}

struct TangentSolveResult {TangentVector state;unsigned iterations=0;double relativeResidual=0;};

// Right-preconditioned restarted GMRES, with reorthogonalization and a checked
// true residual. This solves a tangent integral equation, not GNSS normal
// equations. Velocity is scaled only to balance the numerical residual units.
inline TangentSolveResult solveSixStateTangent(const std::vector<ForceJacobian> &jac,double dt,
    const TangentOperator &integratedAcceleration,const TangentVector &rhs,
    double tolerance=2e-12,unsigned maximumIterations=120,unsigned restart=20)
{
  const unsigned offset=3*jac.size();
  if(rhs.size()!=2*offset || !offset || !restart || !(tolerance>0))throw std::runtime_error("invalid tangent solver input");
  for(double value:rhs)if(!std::isfinite(value))throw std::runtime_error("nonfinite tangent right-hand side");
  for(const auto &node:jac)
  {for(double value:node.position)if(!std::isfinite(value))throw std::runtime_error("nonfinite position force Jacobian");
   for(double value:node.velocity)if(!std::isfinite(value))throw std::runtime_error("nonfinite velocity force Jacobian");}
  const double velocityScale=1000.;
  auto scaled=[&](TangentVector x,double factor){for(unsigned i=offset;i<x.size();i++)x[i]*=factor;return x;};
  auto op=[&](const TangentVector &x){TangentVector y=integratedAcceleration(scaled(x,1/velocityScale));
    if(y.size()!=x.size())throw std::runtime_error("tangent integral shape mismatch");
    y=scaled(y,velocityScale);for(unsigned i=0;i<y.size();i++){y[i]=x[i]-y[i];if(!std::isfinite(y[i]))throw std::runtime_error("nonfinite tangent integral");}return y;};
  auto pre=[&](const TangentVector &x){return scaled(tangentPrecondition(jac,dt,scaled(x,1/velocityScale)),velocityScale);};
  const TangentVector b=scaled(rhs,velocityScale);
  const double normB=tangentNorm(b);
  if(!std::isfinite(normB))throw std::runtime_error("nonfinite scaled tangent norm");
  TangentSolveResult result;result.state.assign(b.size(),0);
  if(normB==0)return result;
  TangentVector x=pre(b);
  while(result.iterations<maximumIterations)
  {
    TangentVector residual=b;tangentAxpy(-1,op(x),residual);
    const double beta=tangentNorm(residual);result.relativeResidual=beta/normB;
    ::recordTangentTrace(result.iterations,x,result.relativeResidual,false);
    if(result.relativeResidual<=tolerance){result.state=scaled(x,1/velocityScale);return result;}
    const unsigned capacity=std::min(restart,maximumIterations-result.iterations);
    std::vector<TangentVector> basis{residual},z;
    for(double &value:basis[0])value/=beta;
    std::vector<std::vector<double>> h(capacity+1,std::vector<double>(capacity));
    std::vector<double> cosine(capacity),sine(capacity),g(capacity+1);g[0]=beta;
    unsigned count=0;
    for(unsigned j=0;j<capacity;j++)
    {
      z.push_back(pre(basis[j]));auto w=op(z.back());
      for(unsigned pass=0;pass<2;pass++)for(unsigned i=0;i<=j;i++)
      {double projection=tangentDot(w,basis[i]);h[i][j]+=projection;tangentAxpy(-projection,basis[i],w);}
      h[j+1][j]=tangentNorm(w);const bool exhausted=h[j+1][j]<1e-30;
      if(!exhausted){for(double &value:w)value/=h[j+1][j];basis.push_back(std::move(w));}
      for(unsigned i=0;i<j;i++){double value=cosine[i]*h[i][j]+sine[i]*h[i+1][j];h[i+1][j]=-sine[i]*h[i][j]+cosine[i]*h[i+1][j];h[i][j]=value;}
      const double denominator=std::hypot(h[j][j],h[j+1][j]);
      if(!(denominator>0))throw std::runtime_error("six-state tangent Krylov breakdown");
      cosine[j]=h[j][j]/denominator;sine[j]=h[j+1][j]/denominator;
      h[j][j]=denominator;h[j+1][j]=0;g[j+1]=-sine[j]*g[j];g[j]*=cosine[j];
      count=j+1;result.iterations++;
      ::recordTangentProjection(result.iterations,std::abs(g[j+1])/normB);
      if(std::abs(g[j+1])<=tolerance*normB || exhausted)break;
    }
    std::vector<double> y(count);
    for(int j=int(count)-1;j>=0;j--){y[j]=g[j];for(unsigned k=j+1;k<count;k++)y[j]-=h[j][k]*y[k];y[j]/=h[j][j];}
    // Accumulate the complete cycle correction before rounding back to the
    // stored double state. Sequential double AXPY updates can lose cancellation
    // on long arcs even when the projected Krylov residual is small. Acceptance
    // still requires the freshly evaluated true residual at this rounded state.
    for(unsigned i=0;i<x.size();i++)
    {
      long double value=x[i];
      for(unsigned j=0;j<count;j++)value+=static_cast<long double>(y[j])*z[j][i];
      x[i]=double(value);
    }
  }
  TangentVector residual=b;tangentAxpy(-1,op(x),residual);result.relativeResidual=tangentNorm(residual)/normB;
  ::recordTangentTrace(result.iterations,x,result.relativeResidual,true);
  if(!std::isfinite(result.relativeResidual) || result.relativeResidual>tolerance)
  {
    std::ostringstream message;message.precision(17);
    message<<"six-state tangent did not meet its true residual tolerance: relative_residual="<<result.relativeResidual
           <<", tolerance="<<tolerance<<", iterations="<<result.iterations<<", rhs_norm="<<normB
           <<", solution_norm="<<tangentNorm(x)<<", epochs="<<jac.size();
    throw std::runtime_error(message.str());
  }
  result.state=scaled(x,1/velocityScale);return result;
}
}
#endif
