// Compile the actual scalar arithmetic block from stagedVariationalBody.h.
// No GROOPS libraries, propagation or scientific data are used by this fixture.
#include <iomanip>
#include <iostream>
using Double=double;

int main()
{
#include "mean_residual_arithmetic.inc"
  double reference,approximate,integral;
  std::cout<<std::setprecision(17);
  while(std::cin>>reference>>approximate>>integral)
  {
    const double absolute=reference+integral;
    std::cout<<meanResidual(reference,approximate,integral)<<' '
             <<restoreMean(approximate,integral)<<' '
             <<absolute-approximate<<'\n';
  }
  return std::cin.eof() ? 0 : 1;
}
