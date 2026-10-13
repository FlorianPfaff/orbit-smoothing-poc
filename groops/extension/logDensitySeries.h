// SPDX-License-Identifier: GPL-3.0-or-later
// V3 comparison extension to GROOPS. Times are GPS MJD, coefficients dimensionless.
#ifndef ORBIT_POC_LOG_DENSITY_SERIES_H
#define ORBIT_POC_LOG_DENSITY_SERIES_H
#include "base/import.h"
#include "files/fileMatrix.h"
#include <algorithm>
#include <cmath>

class LogDensitySeries
{
public:
  std::vector<Time> times;
  Vector values;
  explicit LogDensitySeries(const FileName &path)
  {
    // Plain two-column ASCII by contract. Parse epoch separately at extended
    // precision, as native instrument ASCII does; Matrix would cast MJD to a
    // double before splitting the integer day and lose sub-microsecond timing.
    std::ifstream stream(path.str());
    if(!stream) throw(Exception("cannot open log density knot file"));
    std::vector<Double> coefficients;
    std::string line;
    while(std::getline(stream,line))
    {
      const auto first=line.find_first_not_of(" \t\r");
      if(first==std::string::npos || line.at(first)=='#') continue;
      std::istringstream record(line);
      LongDouble mjd; Double value; std::string extra;
      if(!(record>>mjd>>value) || (record>>extra))
        throw(Exception("log density file must contain plain GPS MJD and log multiplier pairs"));
      if(!std::isfinite(mjd) || !std::isfinite(value))
        throw(Exception("nonfinite log density knot"));
      const Int day=static_cast<Int>(std::floor(mjd));
      times.emplace_back(day,static_cast<Double>(mjd-day));
      coefficients.push_back(value);
      if(times.size()>1 && !(times.back()>times.at(times.size()-2)))
        throw(Exception("log density knots must be strictly increasing"));
    }
    if(times.size()<2) throw(Exception("log density file requires at least two knots"));
    values=Vector(coefficients.size());
    for(UInt i=0;i<coefficients.size();i++) values(i)=coefficients.at(i);
  }

  std::pair<UInt,Double> weights(const Time &time) const
  {
    // Permit roundoff at endpoints, never extrapolate across missing data.
    if((time-times.front()).seconds() < -1e-5 || (time-times.back()).seconds()>1e-5)
      throw(Exception("density evaluation outside knot interval"));
    auto it = std::upper_bound(times.begin(), times.end(), time);
    UInt i = (it==times.begin()) ? 0 : std::distance(times.begin(),it)-1;
    i = std::min<UInt>(i, times.size()-2);
    Double w = (time-times.at(i)).seconds()/(times.at(i+1)-times.at(i)).seconds();
    return {i,std::max(0.,std::min(1.,w))};
  }

  Double multiplier(const Time &time) const
  {
    const auto [i,w] = weights(time);
    const Double result = std::exp((1-w)*values(i)+w*values(i+1));
    if(!std::isfinite(result) || result<=0)
      throw(Exception("nonfinite or underflowed density multiplier"));
    return result;
  }
};
#endif
