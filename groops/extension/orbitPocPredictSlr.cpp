// SPDX-License-Identifier: GPL-3.0-or-later
#define DOCSTRING docstring
static const char *docstring=R"(Evaluate withheld SLR without parameter estimation.
Uses native round-trip geometry, Shapiro delay, Earth orientation, station
displacements and a-priori meteorological/time/range corrections. GRACE-FO
prism correction follows GFZ GFO-MA-GFZ-LR-0001 Issue2 equations2-3.
Columns: GPSMJD,station,pass,residual[m],sigma[m],elevation[rad],azimuth[rad],
wavelength[m],prismCorrection[m],valid,Jx,Jy,Jz,transmitTimeDerivative[m/s].)";
#include "programs/program.h"
#include "files/fileMatrix.h"
#include "base/polynomial.h"
#include "misc/orbitPoc/piecewisePolynomial.h"
#include "misc/observation/variationalEquationFromFile.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/earthRotation/earthRotation.h"
#include "slr/slr.h"
#include "slr/slrObservation.h"
#include "slr/slrStationGenerator/slrStationGenerator.h"
#include "slr/slrSatelliteGenerator/slrSatelliteGenerator.h"

class OrbitPocPredictSlr
{
public:
  void run(Config &config,Parallel::CommunicatorPtr comm);
};
GROOPS_REGISTER_PROGRAM(OrbitPocPredictSlr,SINGLEPROCESS,"Withheld SLR prediction without adjustment",Slr)

void OrbitPocPredictSlr::run(Config &config,Parallel::CommunicatorPtr /*comm*/)
{
  try
  {
    FileName output, covarianceOutput, covarianceInput, variationalInput;
    ParametrizationAccelerationPtr acceleration;
    EphemeridesPtr ephemerides;
    TimeSeriesPtr stochasticPulse;
    UInt integrationDegree, interpolationDegree;
    TimeSeriesPtr series;
    SlrSatelliteGeneratorPtr satellites;
    SlrStationGeneratorPtr stations;
    SlrParametrizationPtr parameters;
    EarthRotationPtr rotation;
    readConfig(config,"outputfilePredictions",output,Config::MUSTSET,"","SLR residual table");
    readConfig(config,"timeSeries",series,Config::MUSTSET,"","station/EOP interpolation epochs");
    readConfig(config,"satellite",satellites,Config::MUSTSET,"","fitted GNSS orbit and measured attitude");
    readConfig(config,"station",stations,Config::MUSTSET,"","withheld normal points");
    readConfig(config,"earthRotation",rotation,Config::MUSTSET,"","EOP");
    readConfig(config,"parametrization",parameters,Config::MUSTSET,"","a-priori corrections only");
    readConfig(config,"outputfilePredictiveCovariance",covarianceOutput,Config::OPTIONAL,"","full correlated SLR predictive covariance in prediction-row order");
    readConfig(config,"inputfileParameterCovariance",covarianceInput,Config::OPTIONAL,"","native dynamic parameter marginal covariance");
    readConfig(config,"inputfileVariational",variationalInput,Config::OPTIONAL,"","final fit variational equations");
    readConfig(config,"parametrizationAcceleration",acceleration,Config::DEFAULT,"","exact final native acceleration parameterization");
    readConfig(config,"stochasticPulse",stochasticPulse,Config::DEFAULT,"","exact final native pulse epochs");
    readConfig(config,"ephemerides",ephemerides,Config::DEFAULT,"","same ephemerides as orbit fit");
    readConfig(config,"integrationDegree",integrationDegree,Config::DEFAULT,"7","");
    readConfig(config,"interpolationDegree",interpolationDegree,Config::DEFAULT,"7","");
    if(isCreateSchema(config)) return;
    Slr slr;
    const auto interpolationBoundaries=acceleration->integrationBoundaries();
    const auto pulseTimes=stochasticPulse->times();
    slr.init(series->times(),satellites,stations,rotation,parameters,interpolationBoundaries,pulseTimes,interpolationDegree);
    if(slr.satellites.size()!=1) throw(Exception("SLR validation requires exactly one usable satellite"));
    const auto satellite=slr.satellites.front();
    Matrix parameterCovariance, positionDesign;
    OrbitPocPiecewisePolynomial designPolynomial;
    const Bool projectCovariance=!covarianceOutput.empty();
    if(projectCovariance)
    {
      if(covarianceInput.empty() || variationalInput.empty()) throw(Exception("SLR covariance needs final variational and parameter covariance files"));
      FileVariationalEquation arcFile(variationalInput);
      if(arcFile.arcCount()!=1) throw(Exception("SLR covariance currently requires a single continuous variational arc"));
      const auto arc=arcFile.readArc(0);
      VariationalEquationFromFile variational;
      variational.open(variationalInput,nullptr,acceleration,stochasticPulse->times(),ephemerides,integrationDegree);
      auto equation=variational.integrateArc(arc.times.front(),arc.times.back(),TRUE,FALSE);
      positionDesign=equation.PosDesign;
      designPolynomial.init(equation.times,interpolationDegree,interpolationBoundaries,pulseTimes);
      readFileMatrix(covarianceInput,parameterCovariance);
      if(parameterCovariance.rows()!=positionDesign.columns() || parameterCovariance.columns()!=positionDesign.columns())
        throw(Exception("SLR covariance parameter order/count disagrees with final dynamic design"));
    }
    std::vector<Vector> rows;
    std::vector<Matrix> designs;
    UInt pass=0;
    for(const auto &station:slr.stations)
      for(const auto &observation:station->observations.at(0))
      {
        SlrObservationEquation eqn;
        eqn.compute(*observation,*station,*satellite,slr.funcRotationCrf2Trf,slr.funcReduceModels,FALSE);
        for(UInt i=0;i<eqn.l.rows();i++)
        {
          const Rotary3d attitude(satellite->polynomial.interpolate({eqn.timesSat.at(i)},satellite->srf2crf).trans());
          const Vector3d direction=attitude.inverseRotate(normalize(eqn.posStat.at(i)-eqn.posSat.at(i)));
          // Four front-face normals: azimuth45+90k, polar angle45deg.
          const Double cosine=0.5*(std::fabs(direction.x())+std::fabs(direction.y()))+std::sqrt(0.5)*direction.z();
          const Double wavelength=eqn.laserWavelength(i);
          const Double wavelengths[]={355e-9,425e-9,532e-9,850e-9,1064e-9};
          const Double groupIndices[]={1.5329,1.5064,1.4853,1.4657,1.4624};
          UInt index=0;
          for(UInt j=1;j<5;j++) if(std::fabs(wavelength-wavelengths[j])<std::fabs(wavelength-wavelengths[index])) index=j;
          if(std::fabs(wavelength-wavelengths[index])>1e-9)
            throw(Exception("unsupported laser wavelength for GRACE-FO prism correction"));
          const Double correction=0.0474*cosine-0.028*std::sqrt(groupIndices[index]*groupIndices[index]-(1-cosine*cosine));
          Vector row(14);
          row(0)=observation->timesTrans.at(i).mjd();
          row(1)=std::stod(station->name());
          row(2)=pass;
          row(3)=eqn.l(i)+correction;
          row(4)=eqn.sigmas0(i);
          row(5)=Double(eqn.elevationStat.at(i));
          row(6)=Double(eqn.azimutStat.at(i));
          row(7)=wavelength;
          row(8)=correction;
          row(9)=(cosine>=std::cos(0.85));
          for(UInt j=0;j<3;j++) row(10+j)=eqn.A(i,SlrObservationEquation::idxPosSat+j);
          row(13)=eqn.A(i,SlrObservationEquation::idxTime);
          for(UInt j=0;j<14;j++) if(!std::isfinite(row(j))) throw(Exception("nonfinite SLR prediction"));
          rows.push_back(row);
          if(projectCovariance)
          {
            const Matrix pos=designPolynomial.interpolate({eqn.timesSat.at(i)},positionDesign,3);
            Matrix design(1,pos.columns());
            matMult(1.,eqn.A.slice(i,SlrObservationEquation::idxPosSat,1,3),pos,design);
            designs.push_back(design);
          }
        }
        pass++;
      }
    if(rows.empty()) throw(Exception("no usable withheld SLR observations"));
    Matrix result(rows.size(),14);
    for(UInt i=0;i<rows.size();i++) for(UInt j=0;j<14;j++) result(i,j)=rows.at(i)(j);
    writeFileMatrix(output,result);
    if(projectCovariance)
    {
      Matrix design(rows.size(),parameterCovariance.rows());
      for(UInt i=0;i<rows.size();i++) copy(designs.at(i),design.row(i));
      Matrix projected(rows.size(),parameterCovariance.rows());
      matMult(1.,design,parameterCovariance,projected);
      Matrix covariance(rows.size(),rows.size());
      matMult(1.,projected,design.trans(),covariance);
      for(UInt i=0;i<rows.size();i++) covariance(i,i)+=rows.at(i)(4)*rows.at(i)(4);
      writeFileMatrix(covarianceOutput,covariance);
    }
  }
  catch(std::exception &e) {GROOPS_RETHROW(e)}
}
