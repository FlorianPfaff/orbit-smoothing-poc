// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_BLOCKED_VARIATIONAL_EVALUATION_H
#define ORBIT_POC_BLOCKED_VARIATIONAL_EVALUATION_H
#include "base/import.h"
#include "files/fileMatrix.h"
#include <cstdlib>
#include <limits>

// A storage change in the fixed-parameter evaluator only. Each block still
// contains EVERY original parameter column. The one native model instance
// advances chronologically; no force, integration, pulse or knot is restarted.
namespace OrbitPoc
{
inline UInt variationalBlockEpochs()
{
  const char *raw=std::getenv("ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS");
  if(!raw)return 0;
  const std::string value(raw);
  if(value.empty() || (value.size()>1 && value.front()=='0'))
    throw(Exception("Variational block epochs must be a canonical integer in [0,65536]"));
  UInt count=0;
  for(char c:value)
  {
    if(c<'0'||c>'9'||count>6553 || (count==6553&&c>'6'))
      throw(Exception("Variational block epochs must be a canonical integer in [0,65536]"));
    count=10*count+UInt(c-'0');
  }
  return count;
}

struct BlockedVariationalEvaluation
{
  Matrix position,velocity;
  Vector parameters;
  UInt blocks=0,maximumBlockEpochs=0;
};

template<class NativeModel>
BlockedVariationalEvaluation evaluateVariationalBlocks(NativeModel &model,
    const std::vector<Time> &times,UInt blockEpochs,const FileName &parametersFile,
    const FileName &initialFile,const FileName &initialDesign)
{
  if(times.empty()||!blockEpochs||blockEpochs>65536)
    throw(Exception("Invalid fixed-parameter variational block geometry"));
  const UInt count=model.parameterCount();
  if(count<6)throw(Exception("native model lacks six state columns"));
  BlockedVariationalEvaluation result;
  result.parameters=Vector(count);
  if(!parametersFile.empty())
  {
    Matrix values;readFileMatrix(parametersFile,values);
    if(values.rows()!=count||values.columns()!=1)
      throw(Exception("parameter vector must be count by one"));
    copy(values,result.parameters);
  }
  Matrix target;
  if(!initialFile.empty())
  {
    readFileMatrix(initialFile,target);
    if(target.rows()!=6||target.columns()!=1)
      throw(Exception("initial state must be six by one"));
    for(UInt i=count-6;i<count;i++)result.parameters(i)=0.;
  }
  result.position=Matrix(3*times.size(),1);
  result.velocity=Matrix(3*times.size(),1);
  for(UInt first=0;first<times.size();)
  {
    const UInt length=std::min(blockEpochs,UInt(times.size()-first));
    // integrateArc owns a persistent chronological Alpha accumulator. It does
    // not reset that accumulator when a subsequent block starts later.
    auto equation=model.integrateArc(times.at(first),times.at(first+length-1),TRUE,TRUE);
    if(model.parameterCount()!=count||equation.times.size()!=length||
       equation.PosDesign.rows()!=3*length||equation.VelDesign.rows()!=3*length||
       equation.PosDesign.columns()!=count||equation.VelDesign.columns()!=count||
       equation.pos0.rows()!=3*length||equation.vel0.rows()!=3*length||
       equation.pos0.columns()!=1||equation.vel0.columns()!=1)
      throw(Exception("Blocked native variational shape or parameter identity changed"));
    for(UInt i=0;i<length;i++)
      if(equation.times.at(i).mjdInt()!=times.at(first+i).mjdInt()||
         equation.times.at(i).mjdMod()!=times.at(first+i).mjdMod())
        throw(Exception("Blocked native variational epoch identity changed"));
    if(first==0)
    {
      if(!initialDesign.empty())
      {
        Matrix design(6,count);
        copy(equation.PosDesign.row(0,3),design.row(0,3));
        copy(equation.VelDesign.row(0,3),design.row(3,3));
        writeFileMatrix(initialDesign,design);
      }
      if(!initialFile.empty())
      {
        Matrix N(6,6);Vector rhs(6);
        copy(equation.PosDesign.slice(0,count-6,3,6),N.row(0,3));
        copy(equation.VelDesign.slice(0,count-6,3,6),N.row(3,3));
        Matrix position=equation.pos0,velocity=equation.vel0;
        matMult(1.,equation.PosDesign,result.parameters,position);
        matMult(1.,equation.VelDesign,result.parameters,velocity);
        for(UInt i=0;i<3;i++)
        {rhs(i)=target(i,0)-position(i,0);rhs(i+3)=target(i+3,0)-velocity(i,0);}
        const Matrix state=solve(N,rhs);
        for(UInt i=0;i<6;i++)result.parameters(count-6+i)=state(i,0);
      }
    }
    Matrix position=equation.pos0,velocity=equation.vel0;
    matMult(1.,equation.PosDesign,result.parameters,position);
    matMult(1.,equation.VelDesign,result.parameters,velocity);
    copy(position,result.position.row(3*first,3*length));
    copy(velocity,result.velocity.row(3*first,3*length));
    result.blocks++;result.maximumBlockEpochs=std::max(result.maximumBlockEpochs,length);
    first+=length;
    // All block design matrices are destroyed here, before the next block's
    // allocation. Only the O(epoch count) evaluated state survives.
  }
  return result;
}
}
#endif
