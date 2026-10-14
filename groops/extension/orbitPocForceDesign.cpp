// SPDX-License-Identifier: GPL-3.0-or-later
#define DOCSTRING docstring
static const char *docstring=R"(Export native forces and force-parameter partials
for numerical verification. Input states are rows of GPS MJD, CRF position[m]
and velocity[m/s]. Test rotations are identity. Output has MJD, three TRF
accelerations and row-major force partials.)";
#include "programs/program.h"
#include "files/fileMatrix.h"
#include "files/fileInstrument.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/miscAccelerations/miscAccelerations.h"
#include "classes/parametrizationAcceleration/parametrizationAcceleration.h"
#include "misc/orbitPoc/integrationWindows.h"
#include "misc/orbitPoc/atmosphereLocalEvents.h"
#include "misc/orbitPoc/atmosphereExtraSamples.h"

class OrbitPocForceDesign
{
public:
  void run(Config &config,Parallel::CommunicatorPtr);
};
GROOPS_REGISTER_PROGRAM(OrbitPocForceDesign,SINGLEPROCESS,"Native force derivative verification",Simulation)

void OrbitPocForceDesign::run(Config &config,Parallel::CommunicatorPtr)
{
  try
  {
    FileName input,output,windows,localEvents,localPhase,attitudeInput,attitudeOutput;
    TimeSeriesPtr attitudeQueries;
    MiscAccelerationsPtr force;
    ParametrizationAccelerationPtr parameters;
    readConfig(config,"inputfileStates",input,Config::MUSTSET,"","MJD,x,y,z,vx,vy,vz");
    readConfig(config,"outputfileDesign",output,Config::MUSTSET,"","force and row-major derivatives");
    readConfig(config,"outputfileIntegrationWindows",windows,Config::OPTIONAL,"","piecewise polynomial window indices");
    readConfig(config,"outputfileLocalEvents",localEvents,Config::OPTIONAL,"","JB local-midnight crossings: GPS MJD and seconds from first input epoch");
    readConfig(config,"outputfileLocalSolarPhase",localPhase,Config::OPTIONAL,"","GPS MJD and native JB wrapped local-solar phase in radians");
    readConfig(config,"inputfileStarCamera",attitudeInput,Config::OPTIONAL,"","diagnostic canonical attitude samples matching input states");
    readConfig(config,"attitudeTimeSeries",attitudeQueries,Config::OPTIONAL,"","diagnostic attitude interpolation epochs");
    readConfig(config,"outputfileAttitudeInterpolation",attitudeOutput,Config::OPTIONAL,"","GPS MJD and row-major canonical atmospheric rotation matrix");
    readConfig(config,"force",force,Config::MUSTSET,"","native model under test");
    readConfig(config,"parametrizationAcceleration",parameters,Config::DEFAULT,"","parameters under test");
    if(isCreateSchema(config))return;
    Matrix states;
    readFileMatrix(input,states);
    if(states.columns()!=7 || !states.rows())throw(Exception("expected nonempty7column states"));
    const UInt count=parameters->parameterCount();
    Matrix result(states.rows(),4+3*count);
    std::vector<Time> times;
    for(UInt i=0;i<states.rows();i++)
    {
      const Time time=mjd2time(states(i,0));
      times.push_back(time);
      const Vector3d p(states(i,1),states(i,2),states(i,3)),v(states(i,4),states(i,5),states(i,6));
      const auto a=force->acceleration(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr);
      Matrix A(3,count),B(3,parameters->parameterCountArc());
      parameters->compute(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr,A,B);
      result(i,0)=time.mjd(); result(i,1)=a.x();result(i,2)=a.y();result(i,3)=a.z();
      for(UInt r=0;r<3;r++)for(UInt c=0;c<count;c++)result(i,4+r*count+c)=A(r,c);
    }
    writeFileMatrix(output,result);
    if(!attitudeOutput.empty())
    {
      if(attitudeInput.empty() || !attitudeQueries) throw(Exception("attitude diagnostic requires star camera and query epochs"));
      const StarCameraArc camera=InstrumentFile::read(attitudeInput);
      if(camera.size()!=states.rows()) throw(Exception("attitude/state diagnostic count mismatch"));
      VariationalEquationArc reference;reference.times=camera.times();
      reference.pos0=Matrix(3*states.rows(),1);reference.vel0=Matrix(3*states.rows(),1);
      reference.rotEarth.resize(states.rows());
      for(UInt i=0;i<states.rows();i++)
      {
        for(UInt k=0;k<3;k++) {reference.pos0(3*i+k,0)=states(i,1+k);reference.vel0(3*i+k,0)=states(i,4+k);}
        reference.rotSat.push_back(camera.at(i).rotary);
      }
      const auto interpolated=orbitPocAtmosphereExtraSamples(reference,attitudeQueries->times(),{},{});
      Matrix rows(interpolated.times.size(),10);
      for(UInt i=0;i<interpolated.times.size();i++)
      {
        rows(i,0)=interpolated.times.at(i).mjd();
        const auto rotation=interpolated.rotSat.at(i).matrix();
        for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++)rows(i,1+3*r+c)=rotation(r,c);
      }
      writeFileMatrix(attitudeOutput,rows);
    }
    if(!localEvents.empty() || !localPhase.empty())
    {
      Matrix position(3*states.rows(),1),phase(states.rows(),2);
      std::vector<Rotary3d> rotations(states.rows());
      for(UInt i=0;i<states.rows();i++)
      {
        const Vector3d p(states(i,1),states(i,2),states(i,3));
        copy(p.vector(),position.row(3*i,3));
        phase(i,0)=times.at(i).mjd();
        phase(i,1)=orbitPocJbLocalSolarPhase(times.at(i),p,rotations.at(i));
      }
      if(!localPhase.empty()) writeFileMatrix(localPhase,phase);
      if(!localEvents.empty())
      {
        const auto events=orbitPocLocalMidnightEvents(times,position,rotations);
        Matrix rows(events.size(),2);
        for(UInt i=0;i<events.size();i++)
        {rows(i,0)=events.at(i).mjd();rows(i,1)=(events.at(i)-times.front()).seconds();}
        writeFileMatrix(localEvents,rows);
      }
    }
    if(!windows.empty())
    {
      const auto indices=orbitPocIntegrationWindows(times,parameters->integrationBoundaries(),7);
      Matrix rows(indices.size(),3);
      for(UInt i=0;i<indices.size();i++) {rows(i,0)=i;rows(i,1)=indices.at(i);rows(i,2)=indices.at(i)+7;}
      writeFileMatrix(windows,rows);
    }
  }
  catch(std::exception &e) {GROOPS_RETHROW(e)}
}
