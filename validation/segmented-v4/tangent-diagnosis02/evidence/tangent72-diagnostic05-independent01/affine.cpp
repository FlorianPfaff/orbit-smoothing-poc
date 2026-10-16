#include <vector>
#include <iostream>
int main(){std::vector<double>x{1e16};std::vector<double>y{.5,-1e16};std::vector<std::vector<double>>z{{1.},{1.}};unsigned count=2;
    // Diagnostic precision probe: one wide affine sum, one binary64 store.
    for(unsigned i=0;i<x.size();i++)
    {
      long double value=x[i];
      for(unsigned j=0;j<count;j++)value+=static_cast<long double>(y[j])*z[j][i];
      x[i]=double(value);
    }
if(x[0] != .5)return 1;std::cout<<x[0];}
