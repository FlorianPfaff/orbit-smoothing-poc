// SPDX-License-Identifier: GPL-3.0-or-later
// Native diagnostic: actual synthetic force instances and archived six-state
// matrices. This does not construct a surrogate dynamics implementation.
#include "programs/program.h"
#include "files/fileMatrix.h"
#include "files/fileVariationalEquation.h"
#include "classes/forces/forces.h"

class OrbitPocStateDerivatives
{
public:
  void run(Config &config,Parallel::CommunicatorPtr);
};
GROOPS_REGISTER_PROGRAM(OrbitPocStateDerivatives,SINGLEPROCESS,"Export actual native synthetic state Jacobians and archived six-state matrices",Simulation)

void OrbitPocStateDerivatives::run(Config &config,Parallel::CommunicatorPtr)
{
  try
  {
    FileName input,output,variational,transition;ForcesPtr forces;
    readConfig(config,"inputfileStates",input,Config::OPTIONAL,"","rows of GPS MJD and six SI states");
    readConfig(config,"outputfileForceJacobian",output,Config::OPTIONAL,"","MJD, CRF acceleration, row-major position and velocity derivatives");
    readConfig(config,"forces",forces,Config::OPTIONAL,"","actual synthetic force model under test");
    readConfig(config,"inputfileVariational",variational,Config::OPTIONAL,"","single native variational archive");
    readConfig(config,"outputfileStateTransition",transition,Config::OPTIONAL,"","MJD, SI state, row-major physical six-state transition");
    if(isCreateSchema(config))return;
    if(input.empty()!=output.empty() || variational.empty()!=transition.empty() || (input.empty() && variational.empty()))
      throw(Exception("provide matching force-Jacobian and/or state-transition input/output pairs"));
    if(!input.empty())
    {
      if(!forces)throw(Exception("force Jacobian needs the synthetic forward forces"));
      Matrix states;readFileMatrix(input,states);
      if(states.columns()!=7 || !states.rows())throw(Exception("expected nonempty seven-column states"));
      Matrix rows(states.rows(),22);
      for(UInt i=0;i<states.rows();i++)
      {
        const auto time=mjd2time(states(i,0));
        const Vector3d p(states(i,1),states(i,2),states(i,3)),v(states(i,4),states(i,5),states(i,6));
        Matrix position(3,3),velocity(3,3);
        forces->orbitPocSyntheticJacobian(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr,position,velocity);
        const auto a=forces->acceleration(nullptr,time,p,v,Rotary3d(),Rotary3d(),nullptr,nullptr);
        rows(i,0)=time.mjd();for(UInt j=0;j<3;j++)rows(i,1+j)=a.vector()(j);
        for(UInt r=0;r<3;r++)for(UInt c=0;c<3;c++){rows(i,4+3*r+c)=position(r,c);rows(i,13+3*r+c)=velocity(r,c);}
      }
      writeFileMatrix(output,rows);
    }
    if(!variational.empty())
    {
      FileVariationalEquation file(variational);
      if(file.arcCount()!=1)throw(Exception("state-transition diagnostic needs one arc"));
      const auto arc=file.readArc(0);Matrix initial(6,6);
      copy(arc.PosState.row(0,3),initial.row(0,3));copy(arc.VelState.row(0,3),initial.row(3,3));
      inverse(initial);Matrix rows(arc.times.size(),43);
      for(UInt i=0;i<arc.times.size();i++)
      {
        Matrix stored(6,6);copy(arc.PosState.row(3*i,3),stored.row(0,3));copy(arc.VelState.row(3*i,3),stored.row(3,3));
        const Matrix physical=stored*initial;
        rows(i,0)=arc.times[i].mjd();
        for(UInt j=0;j<3;j++){rows(i,1+j)=arc.pos0(3*i+j,0);rows(i,4+j)=arc.vel0(3*i+j,0);}
        for(UInt r=0;r<6;r++)for(UInt c=0;c<6;c++)rows(i,7+6*r+c)=physical(r,c);
      }
      writeFileMatrix(transition,rows);
    }
  }
  catch(std::exception &e){GROOPS_RETHROW(e)}
}
