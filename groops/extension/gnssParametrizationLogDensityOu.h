// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_GNSS_PARAMETRIZATION_LOG_DENSITY_OU_H
#define ORBIT_POC_GNSS_PARAMETRIZATION_LOG_DENSITY_OU_H
#ifdef DOCSTRING_GnssParametrization
static const char *docstringGnssParametrizationLogDensityOu = R"(\subsection{LogDensityOu}
Stationary initial and exact discrete OU constraints on the FULL log-density
series, including the reference knots and accumulated GNSS parameter updates.
All selected parameters must belong to one satellite and match knot order.)";
#endif
#include "base/import.h"
#include "gnss/gnss.h"
#include "gnss/gnssParametrization/gnssParametrization.h"
#include "classes/parameterSelector/parameterSelector.h"
#include "misc/orbitPoc/logDensitySeries.h"
#include "misc/orbitPoc/linearTrace.h"

class GnssParametrizationLogDensityOu : public GnssParametrizationBase
{
  std::string name;
  ParameterSelectorPtr selector;
  std::unique_ptr<LogDensitySeries> series;
  Double tau, sigma;
  Gnss *gnss = nullptr;
public:
  explicit GnssParametrizationLogDensityOu(Config &config)
  {
    FileName path;
    readConfig(config,"name",name,Config::DEFAULT,"constraint.logDensityOu","");
    readConfig(config,"parameters",selector,Config::MUSTSET,"","single satellite logDensity knots in order");
    readConfig(config,"inputfileLogDensity",path,Config::MUSTSET,"","same reference as density force");
    readConfig(config,"tau",tau,Config::MUSTSET,"","seconds");
    readConfig(config,"sigma",sigma,Config::MUSTSET,"","stationary log-density standard deviation");
    if(isCreateSchema(config)) return;
    if(!std::isfinite(tau) || !std::isfinite(sigma) || tau<=0 || sigma<=0)
      throw(Exception("OU tau and sigma must be finite and positive"));
    series = std::make_unique<LogDensitySeries>(path);
  }
  void init(Gnss *value,Parallel::CommunicatorPtr) override {gnss=value;}
  void constraints(const GnssNormalEquationInfo &info,MatrixDistributed &N,
      std::vector<Matrix> &rhs,Double &lPl,UInt &obsCount) const override
  {
    if(!isEnabled(info,name)) return;
    auto indices = selector->indexVector(info.parameterNames());
    indices.erase(std::remove(indices.begin(),indices.end(),NULLINDEX),indices.end());
    if(indices.size()!=series->times.size())
      throw(Exception("OU selection must match every reference density knot exactly once"));
    auto unique=indices;
    std::sort(unique.begin(),unique.end());
    if(std::adjacent_find(unique.begin(),unique.end())!=unique.end())
      throw(Exception("OU selection contains duplicate parameters"));
    const auto names=info.parameterNames();
    const auto object=names.at(indices.front()).object;
    for(UInt k=0;k<indices.size();k++)
      if(names.at(indices[k]) != ParameterName(object,"logDensity","",series->times[k],series->times[k]))
        throw(Exception("OU selection must contain one satellite's logDensity parameters in exact knot order"));
    const Vector x = gnss->aprioriParameter(info);
    auto row = [&](UInt first,Double a,UInt second,Double b,Double s)
    {
      const UInt ids[2] = {indices.at(first),indices.at(second)};
      const Double coeff[2] = {a/s,b/s};
      const UInt count = (first==second) ? 1 : 2;
      const Double residual = -(a*(series->values(first)+x(ids[0]))+
                                 b*(series->values(second)+x(ids[1])))/s;
      orbitPocLinearTrace().addRow(residual,std::vector<UInt>(ids,ids+count),std::vector<Double>(coeff,coeff+count));
      for(UInt j=0;j<count;j++)
      {
        const UInt bj=N.index2block(ids[j]);
        if(Parallel::isMaster(info.comm))
          rhs.at(bj)(ids[j]-N.blockIndex(bj),0) += coeff[j]*residual;
        for(UInt k=j;k<count;k++)
        {
          UInt r=ids[j],c=ids[k];
          if(c<r) std::swap(r,c);
          const UInt br=N.index2block(r),bc=N.index2block(c);
          N.setBlock(br,bc);
          if(N.isMyRank(br,bc)) N.N(br,bc)(r-N.blockIndex(br),c-N.blockIndex(bc)) += coeff[j]*coeff[k];
        }
      }
      if(Parallel::isMaster(info.comm)) {lPl+=residual*residual;obsCount++;}
    };
    row(0,1.,0,0.,sigma);
    for(UInt k=1;k<indices.size();k++)
    {
      const Double dt=(series->times.at(k)-series->times.at(k-1)).seconds();
      row(k-1,-std::exp(-dt/tau),k,1.,sigma*std::sqrt(-std::expm1(-2*dt/tau)));
    }
  }
};
#endif
