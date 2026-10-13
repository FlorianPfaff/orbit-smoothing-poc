// SPDX-License-Identifier: GPL-3.0-or-later
#define DOCSTRING docstring
static const char *docstring=R"(Predict held-out dual-frequency GPS code using the
native GNSS correction pipeline and a supplied orbit. No orbit or ambiguity is
estimated. Output columns: GPS MJD, PRN, ionosphere-free code residual [m],
measurement variance [m2], three CRF position derivatives, receiver clock
derivative [m/m]. Estimate the unknown epoch clock by projection in the caller.
Receiver code biases common to the GPS constellation share the clock offset.)";
#include "programs/program.h"
#include <fstream>
#include <iomanip>
#include "files/fileMatrix.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/earthRotation/earthRotation.h"
#include "gnss/gnss.h"
#include "gnss/gnssObservation.h"
#include "gnss/gnssTransmitterGenerator/gnssTransmitterGenerator.h"
#include "gnss/gnssReceiverGenerator/gnssReceiverGenerator.h"

class OrbitPocPredictCode
{
public:
  void run(Config &config,Parallel::CommunicatorPtr comm);
};
GROOPS_REGISTER_PROGRAM(OrbitPocPredictCode,SINGLEPROCESS,"Native held-out code prediction",Gnss)

void OrbitPocPredictCode::run(Config &config,Parallel::CommunicatorPtr comm)
{
  try
  {
    FileName output, supportFile;
    TimeSeriesPtr series;
    Double margin;
    GnssTransmitterGeneratorPtr transmitters;
    GnssReceiverGeneratorPtr receivers;
    GnssParametrizationPtr parameters;
    EarthRotationPtr rotation;
    readConfig(config,"outputfilePredictions",output,Config::MUSTSET,"","MJD,PRN,residual,variance,Jx,Jy,Jz,Jclock");
    readConfig(config,"outputfileSupport",supportFile,Config::OPTIONAL,"","GPS MJD, PRN and the two selected code signal types");
    readConfig(config,"timeSeries",series,Config::MUSTSET,"","held-out receive epochs");
    readConfig(config,"timeMargin",margin,Config::DEFAULT,"0.1","seconds");
    readConfig(config,"transmitter",transmitters,Config::MUSTSET,"","same products as estimation");
    readConfig(config,"receiver",receivers,Config::MUSTSET,"","held-out observations, fitted orbit");
    readConfig(config,"earthRotation",rotation,Config::MUSTSET,"","same EOP as estimation");
    readConfig(config,"parametrization",parameters,Config::DEFAULT,"","apriori observation corrections only");
    if(isCreateSchema(config)) return;
    Gnss gnss;
    gnss.init({},series->times(),seconds2time(margin),transmitters,receivers,rotation,parameters,comm);
    if(gnss.receivers.size()!=1) throw(Exception("prediction requires exactly one receiver"));
    auto recv=gnss.receivers.front();
    std::vector<Vector> rows;
    std::vector<std::string> support;
    // No receiver preprocessing: withheld observations cannot change cleaning,
    // ambiguity arcs or the fitted trajectory. Only an epoch clock is centered
    // for numerical accuracy, then eliminated in the external predictive score.
    for(UInt epoch=0;epoch<gnss.times.size();epoch++)
    {
      if(!recv->useable(epoch)) continue;
      std::vector<Vector> current;
      std::vector<std::string> currentSupport;
      for(UInt iteration=0;iteration<3;iteration++)
      {
        current.clear();
        currentSupport.clear();
        Double clockRhs=0,clockNormal=0;
        for(UInt trans=0;trans<recv->idTransmitterSize(epoch);trans++)
        {
          auto obs=recv->observation(trans,epoch);
          if(!obs || !gnss.transmitters.at(trans)->useable(epoch)) continue;
          std::vector<GnssType> codes;
          obs->observationList(GnssObservation::RANGE,codes);
          GnssObservationEquation eqn(*obs,*recv,*gnss.transmitters.at(trans),gnss.funcRotationCrf2Trf,
                                    gnss.funcReduceModels,epoch,FALSE,codes);
          UInt first=NULLINDEX,second=NULLINDEX;
          for(UInt i=0;i<eqn.types.size();i++)
          {
            const auto type=eqn.types.at(i);
            if(type!=GnssType::GPS || type!=GnssType::RANGE) continue;
            if(type==GnssType::L1 && first==NULLINDEX) first=i;
            if(type==GnssType::L2 && second==NULLINDEX) second=i;
          }
          if(first==NULLINDEX || second==NULLINDEX) continue;
          const Double f1=eqn.types.at(first).frequency(),f2=eqn.types.at(second).frequency();
          const Double a=f1*f1/(f1*f1-f2*f2),b=-f2*f2/(f1*f1-f2*f2);
          Vector row(8);
          row(0)=gnss.times.at(epoch).mjd();
          row(1)=eqn.types.at(first).prn();
          row(2)=a*eqn.l(first)+b*eqn.l(second);
          row(3)=a*a*eqn.sigma0(first)*eqn.sigma0(first)+b*b*eqn.sigma0(second)*eqn.sigma0(second);
          for(UInt k=0;k<3;k++) row(4+k)=a*eqn.A(first,GnssObservationEquation::idxPosRecv+k)+b*eqn.A(second,GnssObservationEquation::idxPosRecv+k);
          row(7)=a*eqn.A(first,GnssObservationEquation::idxClockRecv)+b*eqn.A(second,GnssObservationEquation::idxClockRecv);
          if(!std::isfinite(row(2)) || !(row(3)>0)) throw(Exception("invalid held-out code prediction"));
          clockRhs+=row(7)*row(2)/row(3);
          clockNormal+=row(7)*row(7)/row(3);
          current.push_back(row);
          currentSupport.push_back(eqn.types.at(first).str()+" "+eqn.types.at(second).str());
        }
        if(iteration<2 && clockNormal>0) recv->updateClockError(epoch,clockRhs/clockNormal/LIGHT_VELOCITY);
      }
      rows.insert(rows.end(),current.begin(),current.end());
      support.insert(support.end(),currentSupport.begin(),currentSupport.end());
    }
    if(rows.empty()) throw(Exception("no held-out dual-frequency GPS code predictions"));
    Matrix result(rows.size(),8);
    for(UInt i=0;i<rows.size();i++) for(UInt j=0;j<8;j++) result(i,j)=rows.at(i)(j);
    writeFileMatrix(output,result);
    if(!supportFile.empty())
    {
      std::ofstream audit(supportFile.str());
      if(!audit) throw(Exception("Cannot write native predictive support"));
      audit << "# GPSMJD PRN first_code_type second_code_type\n" << std::setprecision(17);
      for(UInt i=0;i<rows.size();i++)
        audit << rows.at(i)(0) << " " << rows.at(i)(1) << " " << support.at(i) << "\n";
      if(!audit) throw(Exception("Native predictive support write failed"));
    }
  }
  catch(std::exception &e) {GROOPS_RETHROW(e)}
}
