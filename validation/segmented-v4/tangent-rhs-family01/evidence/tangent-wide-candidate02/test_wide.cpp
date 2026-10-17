// Focused diagnostic regressions. No production budgets/tolerances are changed.
#define ORBIT_POC_TANGENT_REPLAY_NO_MAIN
#include "replay.cpp"
#undef ORBIT_POC_TANGENT_REPLAY_NO_MAIN
#include <functional>
void require(bool ok,const char *what){if(!ok)throw std::runtime_error(what);}
void rejects(const std::function<void()> &f,const std::string &part) {
  try{f();}catch(const std::exception &e){require(std::string(e.what()).find(part)!=std::string::npos,"unexpected exception");return;}
  throw std::runtime_error("expected rejection");
}
int main() {
  using namespace OrbitPoc;
  std::vector<ForceJacobian> jac(2);TangentVector rhs(12,0.);rhs[0]=1.;rhs[7]=.003;
  auto zero=[](const WideTangentVector &x){return WideTangentVector(x.size(),0.L);};
  auto identity=solveSixStateTangentWide(jac,1.,zero,rhs);
  require(identity.state==rhs && identity.iterations==0 && identity.relativeResidual==0,"identity solve");
  auto zr=solveSixStateTangentWide(jac,1.,zero,TangentVector(12,0.));
  require(zr.iterations==0 && zr.relativeResidual==0,"zero RHS");
  auto half=[](WideTangentVector x){for(auto &v:x)v*=.5L;return x;};
  auto one=solveSixStateTangentWide(jac,1.,half,rhs,2e-12,1,20);
  require(one.iterations==1,"final budget must check actual returned state");
  for(unsigned i=0;i<rhs.size();i++)require(one.state[i]==2*rhs[i],"scalar solved value");
  auto initial=solveSixStateTangentWide(jac,1.,zero,rhs,2e-12,0,20);
  require(initial.iterations==0 && initial.state==rhs,"zero budget exact initial check");
  rejects([&]{solveSixStateTangentWide(jac,1.,half,rhs,2e-12,0,20);},"did not meet");
  rejects([&]{solveSixStateTangentWide(jac,1.,[](const WideTangentVector&){return WideTangentVector(2);},rhs);},"shape mismatch");
  rejects([&]{solveSixStateTangentWide(jac,1.,[](WideTangentVector x){x[0]=std::numeric_limits<long double>::infinity();return x;},rhs);},"nonfinite wide tangent integral");
  rejects([&]{solveSixStateTangentWide(jac,1.,[](WideTangentVector x){return x;},rhs);},"Krylov breakdown");
  auto nonfinite=rhs;nonfinite[0]=std::numeric_limits<double>::quiet_NaN();
  rejects([&]{solveSixStateTangentWide(jac,1.,zero,nonfinite);},"nonfinite wide tangent RHS");
  auto singular=jac;singular[1].position[0]=6.;
  rejects([&]{solveSixStateTangentWide(singular,1.,zero,rhs);},"singular wide tangent preconditioner");

  // An internal solution is insufficient if conversion to the public binary64
  // archive misses the requested tolerance. This intentionally tight test
  // threshold is local to this counterexample, never a campaign setting.
  TangentVector tight(12,0.);tight[0]=1.;bool witnessed=false;unsigned checks=0;
  auto decimal=[](WideTangentVector x){for(auto &v:x)v*=.3L;return x;};
  rejects([&]{solveSixStateTangentWide(jac,1.,decimal,tight,1e-19,4,20,
      [&](unsigned,const TangentVector &,long double internal,long double returned){
        checks++;if(internal<=static_cast<long double>(1e-19) && returned>static_cast<long double>(1e-19))witnessed=true;
      });},"wide tangent");
  require(checks>=2 && witnessed,"rounded-state rejection counterexample not exercised");

  Quadrature weights(1);weights[0]={{0,1.,0.},{1,1.,0.},{2,1.,0.}};
  std::vector<long double> acc(9);acc[0]=1e20L;acc[3]=1.;acc[6]=-1e20L;
  auto integrated=wideTangentIntegrate(weights,1.,acc);
  require(integrated[3]==1.L && integrated[9]==1.L,"compensated quadrature cancellation");

  // Exact stored-coefficient, coupled velocity case. Rectangle quadrature is
  // intentionally tiny and causal, so the analytic trajectory is independent.
  data=Capture{};data.dt=1.;data.T=2.;data.main.resize(3);data.pre.resize(3);data.weights.resize(2);data.rhs.assign(18,0.);
  data.main[0].velocity[0]=.5;data.main[1].velocity[0]=.5;data.main[2].velocity[0]=.5;
  data.weights[0]={{0,1.,.5}};data.weights[1]={{1,1.,.5}};
  data.rhs[9]=1.;data.rhs[12]=1.;data.rhs[15]=1.;
  TangentVector exact(18,0.);exact[3]=.25;exact[6]=1.125;exact[9]=1.;exact[12]=1.5;exact[15]=2.25;
  require(physicalQuadResidual(exact)==0.L,"independent113-bit velocity-coupled oracle");
  auto coupled=[&](const WideTangentVector &x){std::vector<long double>a(9);for(unsigned k=0;k<3;k++)a[3*k]=.5L*x[9+3*k];return wideTangentIntegrate(data.weights,1.,a);};
  auto coupledResult=solveSixStateTangentWide(data.pre,1.,coupled,data.rhs);
  require(physicalQuadResidual(coupledResult.state)<1e-17L,"complete coupled solve certificate");
  exact[15]=std::nextafter(exact[15],std::numeric_limits<double>::infinity());
  require(physicalQuadResidual(exact)>0.L,"oracle must inspect returned velocity bits");
  data.main.assign(3,{});data.weights.assign(2,{});data.rhs.assign(18,0.);
  require(physicalQuadResidual(TangentVector(18,0.))==0.L,"zero oracle denominator");
  exact.assign(18,0.);exact[0]=1.;require(!std::isfinite(physicalQuadResidual(exact)),"nonzero zero-RHS residual");
  std::cout<<"wide diagnostic focused regressions passed\n";
}
