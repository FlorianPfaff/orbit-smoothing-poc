// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_PARAMETRIZATION_ACCELERATION_LOG_DENSITY_H
#define ORBIT_POC_PARAMETRIZATION_ACCELERATION_LOG_DENSITY_H
#ifdef DOCSTRING_ParametrizationAcceleration
static const char *docstringParametrizationAccelerationLogDensity = R"(\subsection{LogDensity}
Sensitivities to dimensionless log-density knot increments at a fixed outer
linearization. Uses the same nominal drag and knot file as the force model.)";
#endif
#include "classes/parametrizationAcceleration/parametrizationAcceleration.h"
#include "classes/miscAccelerations/miscAccelerations.h"
#include "misc/orbitPoc/logDensitySeries.h"
#include "misc/orbitPoc/atmosphereEvents.h"

class ParametrizationAccelerationLogDensity : public ParametrizationAccelerationBase
{
  MiscAccelerationsPtr nominalDrag;
  std::unique_ptr<LogDensitySeries> series;
  Bool atmosphereEvents=FALSE;
  Double atmosphereQuadratureStep=1.;
public:
  explicit ParametrizationAccelerationLogDensity(Config &config)
  {
    FileName path;
    readConfig(config,"nominalDrag",nominalDrag,Config::MUSTSET,"","same nominal drag as logDensity force");
    readConfig(config,"inputfileLogDensity",path,Config::MUSTSET,"","current outer linearization");
    readConfig(config,"orbitPocAtmosphereEvents",atmosphereEvents,Config::DEFAULT,"0","same UTC driver events as the atmospheric force");
    readConfig(config,"orbitPocAtmosphericQuadratureStep",atmosphereQuadratureStep,Config::DEFAULT,"1","atmospheric force and sensitivity quadrature cadence in seconds");
    if(!(atmosphereQuadratureStep>0.)) throw(Exception("positive atmospheric quadrature cadence required"));
    if(!isCreateSchema(config)) series = std::make_unique<LogDensitySeries>(path);
  }
  Bool isPerArc() const override {return FALSE;}
  std::vector<Time> integrationBoundaries() const override {return series ? series->times : std::vector<Time>();}
  std::vector<Time> integrationDiscontinuities(const Time &start,const Time &end) const override
  {return atmosphereEvents ? orbitPocAtmosphereEvents(start,end) : std::vector<Time>();}
  Double integrationAtmosphereStep() const override {return atmosphereQuadratureStep;}
  Bool setInterval(const Time &,const Time &) override {return FALSE;}
  UInt parameterCount() const override {return series ? series->times.size() : 0;}
  void parameterName(std::vector<ParameterName> &name) const override
  {
    for(const auto &time : series->times)
      name.emplace_back("satellite","logDensity","",time,time);
  }
  void compute(SatelliteModelPtr satellite,const Time &time,const Vector3d &position,const Vector3d &velocity,
      const Rotary3d &rotSat,const Rotary3d &rotEarth,EphemeridesPtr ephemerides,MatrixSliceRef A) override
  {
    const auto [i,w] = series->weights(time);
    const Vector a = (series->multiplier(time)*nominalDrag->acceleration(
        satellite,time,position,velocity,rotSat,rotEarth,ephemerides)).vector();
    for(UInt row=0;row<3;row++)
    {
      A(row,i)   = (1-w)*a(row);
      A(row,i+1) = w*a(row);
    }
  }
};
#endif
