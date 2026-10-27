#include "base/import.h"
#include "base/equinoctial.h"
#include "files/fileInstrument.h"
#include "misc/orbitPoc/preciseEquinoctialReference.h"
void report(unsigned iteration, const Equinoctial &e) {
  std::cout << std::setprecision(20) << "{\"iteration\":" << iteration;
  const char *names[]={"GM","a","h","k","p","q","l0"};
  const long double values[]={e.GM,e.a,e.h,e.k,e.p,e.q,e.l0};
  for(unsigned i=0;i<7;i++) {
    std::cout << ",\"" << names[i] << "\":";
    if(std::isfinite(values[i])) std::cout << values[i]; else std::cout << "null";
  }
  std::cout << "}\n" << std::flush;
}
int main(int argc, char **argv) {
  try {
    if(argc!=2)return 4;
    InstrumentFile input{FileName(argv[1])};
    const OrbitArc orbit=input.readArc(0);
    const Double GM=3.986004415e14;
      UInt stagger = (orbit.size() < 100) ? 1 : orbit.size()/100;

      OrbitArc sparseOrbit;
      for(UInt k=0; k<orbit.size(); k += stagger)
        sparseOrbit.push_back(orbit.at(k));

      // Osculating orbit at first epoch
      Vector3d velocity = sparseOrbit.at(0).velocity;
      if(velocity.r()==0)
        velocity = (1/(sparseOrbit.at(1).time-sparseOrbit.at(0).time).seconds()) * (sparseOrbit.at(1).position-sparseOrbit.at(0).position);

      // We use an equinoctial orbit because Kepler is not accurate enough
      Equinoctial referenceOrbit(sparseOrbit.at(0).time, sparseOrbit.at(0).position, velocity, GM);

      report(0, referenceOrbit);
      UInt   iter    = 0;
      UInt   maxIter = 100;
      Vector dx;
      do
      {
        // We will fit to positions only
        Vector obs(3*sparseOrbit.size());
        for(UInt i=0; i<sparseOrbit.size(); i++)
        {
          const Vector3d dpos = sparseOrbit.at(i).position - referenceOrbit.position(sparseOrbit.at(i).time);
          obs(3*i+0) = dpos.x();
          obs(3*i+1) = dpos.y();
          obs(3*i+2) = dpos.z();
        }

        Matrix A(3*sparseOrbit.size(), 6);
        for(UInt i=0; i<sparseOrbit.size(); i++)
          copy(referenceOrbit.stateTransitionMatrix(sparseOrbit.at(i).time).row(0,3), A.row(3*i,3));

        dx = leastSquares(A, obs);
        referenceOrbit.a  += dx(0);
        referenceOrbit.h  += dx(1);
        referenceOrbit.k  += dx(2);
        referenceOrbit.p  += dx(3);
        referenceOrbit.q  += dx(4);
        referenceOrbit.l0 += dx(5);
        report(iter+1, referenceOrbit);
      }
      while((++iter < maxIter) && (maxabs(dx) > 1e-9));

    try {
      auto result=OrbitPoc::preciseEquinoctialReference(
        {referenceOrbit.GM,referenceOrbit.a,referenceOrbit.h,referenceOrbit.k,referenceOrbit.p,referenceOrbit.q,referenceOrbit.l0},0.L);
      std::cout << "{\"guard\":\"unexpected_success\"}\n"; return 3;
    } catch(const std::exception &e) {
      std::cout << "{\"guard_error\":\"" << e.what() << "\"}\n";
      return std::string(e.what())=="Nonfinite equinoctial reference input" ? 0 : 5;
    }
  } catch(const std::exception &e) {std::cerr << e.what() << std::endl;return 2;}
}
