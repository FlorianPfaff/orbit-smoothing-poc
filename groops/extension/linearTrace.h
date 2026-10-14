// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_LINEAR_TRACE_H
#define ORBIT_POC_LINEAR_TRACE_H
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include "base/import.h"
#include "gnss/gnssNormalEquationInfo.h"
#include "parallel/matrixDistributed.h"

// Opt-in, small serial correctness fixture. Exports weighted rows BEFORE A'A,
// so an independent QR/GTSAM solve can test native assembly and elimination.
class OrbitPocLinearTrace
{
  std::string prefix, stem;
  UInt sequence=0, row=0;
  std::ofstream design, rhs;
public:
  OrbitPocLinearTrace() {const char *value=std::getenv("ORBIT_POC_LINEAR_TRACE"); if(value) prefix=value;}
  Bool enabled() const {return !prefix.empty();}
  void begin(const GnssNormalEquationInfo &info,const Vector &apriori,Bool reduced)
  {
    if(!enabled()) return;
    if(Parallel::size(info.comm)!=1 || info.parameterCount()>2000 || reduced)
      throw(Exception("Linear trace requires serial, <=2000 parameters and keepEpochNormalsInMemory"));
    design.close(); rhs.close();
    stem=prefix+"."+std::to_string(++sequence); row=0;
    design.open(stem+".design.tsv"); rhs.open(stem+".rhs.tsv");
    std::ofstream names(stem+".parameters.tsv");
    if(!design || !rhs || !names) throw(Exception("Cannot open linear trace output"));
    design<<std::setprecision(17); rhs<<std::setprecision(17); names<<std::setprecision(17);
    const auto parameters=info.parameterNames();
    for(UInt i=0;i<parameters.size();i++) names<<i<<'\t'<<apriori(i)<<'\t'<<parameters.at(i).str()<<'\n';
  }
  void addRow(Double target,const std::vector<UInt> &indices,const std::vector<Double> &values)
  {
    if(!enabled()) return;
    if(stem.empty() || indices.size()!=values.size()) throw(Exception("Invalid linear trace row"));
    rhs<<row<<'\t'<<target<<'\n';
    for(UInt j=0;j<indices.size();j++)
      if(values[j]!=0.) design<<row<<'\t'<<indices[j]<<'\t'<<values[j]<<'\n';
    row++;
  }
  void delta(const Vector &x)
  {
    if(!enabled()) return;
    design.flush(); rhs.flush();
    std::ofstream out(stem+".delta.txt"); out<<std::setprecision(17);
    if(!out) throw(Exception("Cannot write linear trace solution"));
    for(UInt i=0;i<x.rows();i++) out<<x(i)<<'\n';
  }
  void fullStructure(MatrixDistributed &N)
  {
    if(!enabled()) return;
    for(UInt i=0;i<N.blockCount();i++) for(UInt j=i;j<N.blockCount();j++)
    {
      N.setBlock(i,j);
      if(!N.N(i,j).size()) N.N(i,j)=(i==j) ? Matrix(N.blockSize(i),Matrix::SYMMETRIC) : Matrix(N.blockSize(i),N.blockSize(j));
    }
  }
  void covariance(const MatrixDistributed &N)
  {
    if(!enabled()) return;
    design.flush(); rhs.flush();
    std::ofstream out(stem+".covariance.tsv"); out<<std::setprecision(17);
    if(!out) throw(Exception("Cannot write linear trace covariance"));
    for(UInt i=0;i<N.blockCount();i++) for(UInt j=i;j<N.blockCount();j++)
      for(UInt r=0;r<N.blockSize(i);r++) for(UInt c=(i==j?r:0);c<N.blockSize(j);c++)
        out<<N.blockIndex(i)+r<<'\t'<<N.blockIndex(j)+c<<'\t'<<N.N(i,j)(r,c)<<'\n';
  }
};
inline OrbitPocLinearTrace &orbitPocLinearTrace() {static OrbitPocLinearTrace trace; return trace;}
#endif
