// Standalone tests of the same C++ derivative and tangent kernels linked into
// GROOPS. Forward accelerations below are independently written for FD checks.
#include "sixStateTangent.h"
#include "finiteDifferenceForceJacobian.h"
#include "eventQuadrature.h"
#include <cassert>
#include <iostream>
#include <string>
using namespace OrbitPoc;

Vec3 gravity(Vec3 p)
{
  const double mu=3.986004418e14,r=norm3(p),q=p[2]*p[2]/(r*r),j=1.5*1.08262668e-3*mu*6378137.*6378137./std::pow(r,5);
  return {-mu*p[0]/std::pow(r,3)+j*p[0]*(5*q-1),-mu*p[1]/std::pow(r,3)+j*p[1]*(5*q-1),-mu*p[2]/std::pow(r,3)+j*p[2]*(5*q-3)};
}
Vec3 drag(Vec3 p,Vec3 v)
{
  Vec3 u{v[0]+7.2921150e-5*p[1],v[1]-7.2921150e-5*p[0],v[2]};
  double factor=-.5*.022*5e-13*std::exp(-(norm3(p)-6378137.-500000.)/60000.)*norm3(u);
  for(double &x:u)x*=factor;
  return u;
}
void forces()
{
  for(double altitude:{250000.,500000.,1000000.,20200000.})for(Vec3 direction:std::vector<Vec3>{{1.,.2,.3},{-.4,.7,.8},{0.,0.,1.}})
  {
    const double magnitude=norm3(direction);Vec3 p=direction;for(double &x:p)x*=(6378137.+altitude)/magnitude;
    Vec3 v{-4000.,5000.,3000.};const auto a=syntheticGravityJacobian(p,3.986004418e14,1.08262668e-3,6378137.);
    const auto b=syntheticDragJacobian(p,v,.022,5e-13,500000.,60000.,6378137.,7.2921150e-5);
    for(unsigned c=0;c<6;c++)
    {
      const double step=c<3 ? 1. : .01;auto pp=p,pm=p,vp=v,vm=v;
      (c<3?pp:vp)[c%3]+=step;(c<3?pm:vm)[c%3]-=step;
      const auto gp=gravity(pp),gm=gravity(pm),dp=drag(pp,vp),dm=drag(pm,vm);
      for(unsigned r=0;r<3;r++)
      {
        double observed=(gp[r]-gm[r])/(2*step),expected=(c<3?a.position:a.velocity)[3*r+c%3];
        assert(std::abs(observed-expected)<3e-14+1e-7*std::abs(expected));
        observed=(dp[r]-dm[r])/(2*step);expected=(c<3?b.position:b.velocity)[3*r+c%3];
        assert(std::abs(observed-expected)<1e-22+1e-6*std::abs(expected));
      }
    }
    // A gravity Hessian is symmetric; its vacuum trace is zero, including J2.
    double trace=0;for(unsigned r=0;r<3;r++){trace+=a.position[4*r];for(unsigned c=0;c<3;c++)assert(std::abs(a.position[3*r+c]-a.position[3*c+r])<1e-20);}
    assert(std::abs(trace)<1e-20);
  }
  const Vec3 p{6878137.,0,0},v{0,7.2921150e-5*p[0],0};
  const auto zero=syntheticDragJacobian(p,v,.022,5e-13,500000.,60000.,6378137.,7.2921150e-5);
  for(double value:zero.position)assert(value==0);
  for(double value:zero.velocity)assert(value==0);
}
void finite_difference()
{
  const Vec3 p{6878137.,250000.,300000.},v{-1000.,7200.,2000.};
  const auto refined=refinedForceJacobian(drag,p,v);
  const auto exact=syntheticDragJacobian(p,v,.022,5e-13,500000.,60000.,6378137.,7.2921150e-5);
  assert(refined.evaluations==25);assert(refined.maximumRelativeDifference<1e-6);
  assert(refined.minimumPositionStep==.5 && refined.maximumPositionStep==.5);
  assert(refined.minimumVelocityStep==.0005 && refined.maximumVelocityStep==.0005);
  const auto larger=refinedForceJacobian(drag,p,v,1000.,1e-3);
  assert(larger.minimumPositionStep==500. && larger.maximumPositionStep==500.);
  for(unsigned i=0;i<9;i++)
  {assert(std::abs(larger.jacobian.position[i]-exact.position[i])<5e-21);assert(std::abs(larger.jacobian.velocity[i]-exact.velocity[i])<1e-18);}
  for(unsigned i=0;i<9;i++)
  {assert(std::abs(refined.jacobian.position[i]-exact.position[i])<5e-21);assert(std::abs(refined.jacobian.velocity[i]-exact.velocity[i])<1e-18);}
  auto nearZero=[](const Vec3 &p,const Vec3 &){return Vec3{0,0,5e-16*p[2]+1e-15*std::sin(.01*p[2])};};
  bool roundoffRejected=false;
  try{refinedForceJacobian(nearZero,{0,0,0},{0,0,0},1000.,1e-3);}
  catch(const std::runtime_error &){roundoffRejected=true;}assert(roundoffRejected);
  const auto bounded=refinedForceJacobian(nearZero,{0,0,0},{0,0,0},1000.,1e-3,2e-3,4,1e-15,1e-17);
  assert(bounded.maximumPositionAbsoluteDifference<=2e-18);
  assert(bounded.maximumPositionUnflooredRelativeDifference>2e-3);
  assert(bounded.positionFloorAppliedColumns==3);
  bool rejected=false;
  try{refinedForceJacobian([](const Vec3 &p,const Vec3 &){return Vec3{p[0]>=0?1.:0.,0.,0.};},{0.,0.,0.},{0.,0.,0.});}
  catch(const std::runtime_error &){rejected=true;}assert(rejected);
}
void oscillator(bool fullDay=false)
{
  const unsigned n=fullDay ? 17281 : 401;
  const double dt=fullDay ? 5. : .5,omega=fullDay ? .001 : .03,gamma=fullDay ? 1e-7 : .004;const unsigned offset=3*n;
  std::vector<ForceJacobian> jac(n);
  for(auto &j:jac)for(unsigned i=0;i<3;i++){j.position[4*i]=-omega*omega;j.velocity[4*i]=-gamma;}
  const auto quadrature=eventQuadrature(n,dt,7,{60.,120.,180.},{});
  auto integrate=[&](const TangentVector &x)
  {
    std::vector<long double> acceleration(offset);
    for(unsigned i=0;i<offset;i++)acceleration[i]=-static_cast<long double>(omega*omega)*x[i]-static_cast<long double>(gamma)*x[offset+i];
    return tangentIntegrate(quadrature,dt,acceleration);
  };
  TangentVector rhs(2*offset);for(unsigned i=0;i<n;i++)rhs[3*i]=1.;
  const auto result=solveSixStateTangent(jac,dt,integrate,rhs);
  assert(result.relativeResidual<2e-12);assert(result.iterations>0);
  const double wd=std::sqrt(omega*omega-gamma*gamma/4);
  for(unsigned i=0;i<n;i++)
  {
    const double t=i*dt,decay=std::exp(-gamma*t/2),p=decay*(std::cos(wd*t)+gamma/(2*wd)*std::sin(wd*t));
    const double v=-decay*omega*omega/wd*std::sin(wd*t);
    assert(std::abs(result.state[3*i]-p)<5e-10);assert(std::abs(result.state[offset+3*i]-v)<5e-12);
  }
  // Match native variation-of-constants pulse handling: Phi(t) Phi(tp)^-1
  // times a 1 micrometre/s impulse. The epoch at tp exports the post-pulse state.
  TangentVector velocityBasis(2*offset);const unsigned jump=120;
  for(unsigned i=0;i<n;i++){velocityBasis[3*i]=i*dt;velocityBasis[offset+3*i]=1.;}
  const auto second=solveSixStateTangent(jac,dt,integrate,velocityBasis);
  const double determinant=result.state[3*jump]*second.state[offset+3*jump]-second.state[3*jump]*result.state[offset+3*jump];
  const double c0=-second.state[3*jump]*1e-6/determinant,c1=result.state[3*jump]*1e-6/determinant;
  for(unsigned i=jump;i<n;i++)
  {
    const double t=(i-jump)*dt,decay=std::exp(-gamma*t/2);
    const double p=c0*result.state[3*i]+c1*second.state[3*i];
    const double v=c0*result.state[offset+3*i]+c1*second.state[offset+3*i];
    assert(std::abs(p-1e-6*decay*std::sin(wd*t)/wd)<1e-13);
    assert(std::abs(v-1e-6*decay*(std::cos(wd*t)-gamma/(2*wd)*std::sin(wd*t)))<1e-15);
    if(i==jump){assert(std::abs(p)<1e-18);assert(std::abs(v-1e-6)<1e-20);}
  }
  const auto zero=solveSixStateTangent(jac,dt,integrate,TangentVector(2*offset));assert(zero.iterations==0);
  bool rejected=false;try{solveSixStateTangent(jac,dt,integrate,rhs,1e-30,1);}catch(const std::runtime_error &){rejected=true;}assert(rejected);
  rejected=false;rhs[0]=std::numeric_limits<double>::quiet_NaN();
  try{solveSixStateTangent(jac,dt,integrate,rhs);}catch(const std::runtime_error &){rejected=true;}assert(rejected);
}
// A circular orbit has a rotating, indefinite gravity Hessian and secular
// along-track STM growth. A constant oscillator does not exercise the full-day
// cancellation that occurred in the actual eccentric-orbit resource preflight.
void day_kepler()
{
  const unsigned n=17281,offset=3*n;const double dt=5.,omega=.00113,T=(n-1)*dt;
  std::vector<ForceJacobian> jac(n);std::vector<double> knots;
  for(double t=60;t<T;t+=60)knots.push_back(t);
  const auto quadrature=eventQuadrature(n,dt,7,knots,{});
  for(unsigned k=0;k<n;k++)
  {
    const Vec3 radial{std::cos(omega*k*dt),std::sin(omega*k*dt),0};
    for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
      jac[k].position[3*i+j]=omega*omega*(3*radial[i]*radial[j]-(i==j?1.:0.));
  }
  auto integrate=[&](const TangentVector &x)
  {
    std::vector<long double> acceleration(offset);
    for(unsigned k=0;k<n;k++)for(unsigned i=0;i<3;i++)for(unsigned j=0;j<3;j++)
      acceleration[3*k+i]+=static_cast<long double>(jac[k].position[3*i+j])*x[3*k+j];
    return tangentIntegrate(quadrature,dt,acceleration);
  };
  for(unsigned column=0;column<6;column++)
  {
    Vec3 r0{},v0{};if(column<3)r0[column]=1;else v0[column-3]=1/T;
    v0[0]+=omega*r0[1];v0[1]-=omega*r0[0]; // inertial to rotating initial velocity
    TangentVector rhs(2*offset);
    for(unsigned k=0;k<n;k++){rhs[3*k+column%3]=column<3?1:k*dt/T;if(column>=3)rhs[offset+3*k+column%3]=1/T;}
    const auto solved=solveSixStateTangent(jac,dt,integrate,rhs);
    assert(solved.relativeResidual<=2e-12);
    for(unsigned k=0;k<n;k++)
    {
      const double angle=omega*k*dt,c=std::cos(angle),s=std::sin(angle);
      Vec3 p{(4-3*c)*r0[0]+s/omega*v0[0]+2*(1-c)/omega*v0[1],
             6*(s-angle)*r0[0]+r0[1]-2*(1-c)/omega*v0[0]+(4*s-3*angle)/omega*v0[1],
             c*r0[2]+s/omega*v0[2]};
      Vec3 v{3*omega*s*r0[0]+c*v0[0]+2*s*v0[1],
             6*omega*(c-1)*r0[0]-2*s*v0[0]+(4*c-3)*v0[1],
             -omega*s*r0[2]+c*v0[2]};
      v[0]-=omega*p[1];v[1]+=omega*p[0];
      const Vec3 inertialP{c*p[0]-s*p[1],s*p[0]+c*p[1],p[2]};
      const Vec3 inertialV{c*v[0]-s*v[1],s*v[0]+c*v[1],v[2]};
      for(unsigned i=0;i<3;i++)
      {assert(std::abs(solved.state[3*k+i]-inertialP[i])<3e-8);assert(std::abs(solved.state[offset+3*k+i]-inertialV[i])<1e-10);}
    }
  }
}
int main(int argc,char **argv)
{
  if(argc!=2)return 2;
  const std::string mode=argv[1];
  if(mode=="forces")forces();else if(mode=="finite_difference")finite_difference();else if(mode=="oscillator")oscillator();else if(mode=="day_oscillator")oscillator(true);else if(mode=="day_kepler")day_kepler();else return 2;
  std::cout<<mode<<" passed\n";
}
