// Exercise the production collect() body with small GNSS-shaped objects.
// Full native profile equivalence remains a separate integration gate.
#include "nuisanceWarmState.h"
#include <memory>
using UInt=unsigned long;
struct Time {double day=60000,fraction=0;double mjdInt()const{return day;}double mjdMod()const{return fraction;}};
struct Type {std::string value;std::string str()const{return value;}};
struct Bias {std::vector<Type> types{{"C1"},{"L1"}};std::vector<double> biases{1.,2.};};
struct GnssTransceiver {unsigned id_=0;Bias signalBias;std::string name()const{return "receiver";}bool useable(unsigned)const{return true;}};
struct GnssTransmitter:GnssTransceiver {unsigned idTrans()const{return id_;}};
struct GnssReceiver;
struct GnssTrack {GnssReceiver *receiver=nullptr;GnssTransmitter *transmitter=nullptr;unsigned idEpochStart=0,idEpochEnd=0;std::vector<Type> types{{"L1"}};};
struct Single {Type type{"C1"};double observation=25.,sigma=.3,sigma0=.3;};
struct Observation {GnssTrack *track=nullptr;double STEC=1.,dSTEC=0.,sigmaSTEC=20.;std::vector<Single> values{{}};unsigned size()const{return values.size();}const Single&at(unsigned i)const{return values.at(i);}};
struct GnssReceiver:GnssTransceiver {std::vector<Time> times{{60000,0},{60000,.1}};double wavelengthFactor=1.;std::vector<std::shared_ptr<GnssTrack>> tracks;std::vector<Observation> observations{{},{}};double clock=1.e-6;unsigned idRecv()const{return id_;}unsigned idTransmitterSize(unsigned)const{return 1;}Observation *observation(unsigned,unsigned epoch){return &observations.at(epoch);}};
struct GnssNormalEquationInfo {int comm=0;bool isEachReceiverSeparately=false,accumulateEpochObservations=false;std::vector<unsigned> estimateReceiver{1},idEpochs{0,1};unsigned parameterCount()const{return 1;}std::vector<Type> parameterNames()const{return {{"clock"}};}std::vector<unsigned> blockIndices()const{return {0,1};}};
namespace Parallel {inline int size(int){return 1;}}
struct Param {GnssReceiver *recv;void orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &){l.value("clock",recv->clock);l.signalOwners.insert(recv);}};
struct Gnss {std::vector<Time> times{{60000,0},{60000,.1}};std::vector<std::shared_ptr<GnssTransmitter>> transmitters;std::vector<std::shared_ptr<GnssReceiver>> receivers;std::shared_ptr<Param> parametrization;};
#include "nuisanceWarmGnss.h"
#include <iostream>
int main(int argc,char **argv){try {
  orbitPocWarm::require(argc==2,"fixture argument");const std::string mode=argv[1];Gnss gnss;GnssNormalEquationInfo info;
  auto recv=std::make_shared<GnssReceiver>();auto trans=std::make_shared<GnssTransmitter>();gnss.receivers={recv};gnss.transmitters={trans};gnss.parametrization=std::make_shared<Param>();gnss.parametrization->recv=recv.get();
  for(unsigned i=0;i<2;i++){auto track=std::make_shared<GnssTrack>();track->receiver=recv.get();track->transmitter=trans.get();track->idEpochStart=i;track->idEpochEnd=i;recv->tracks.push_back(track);recv->observations[i].track=track.get();}
  const auto before=orbitPocWarm::collect(gnss,info,true);const auto beforeValues=before.values();bool shouldReject=false;
  if(mode=="track_swap")std::swap(recv->observations[0].track,recv->observations[1].track);
  else if(mode=="track_null")recv->observations[0].track=nullptr;
  else if(mode=="duplicate_track"){recv->tracks.push_back(recv->tracks[0]);shouldReject=true;}
  else if(mode=="nonmember_track"){static GnssTrack rogue;recv->observations[0].track=&rogue;shouldReject=true;}
  else if(mode=="wrong_receiver"){recv->tracks[0]->receiver=nullptr;shouldReject=true;}
  else if(mode=="raw_time")recv->times[0].fraction=std::nextafter(recv->times[0].fraction,1.);
  else if(mode=="clock_value")recv->clock=1.2;
  else if(mode=="observation_value")recv->observations[0].values[0].observation=26.;
  else if(mode=="weight")recv->observations[0].values[0].sigma=.4;
  else if(mode=="bias_shape"){recv->signalBias.biases.push_back(3.);shouldReject=true;}
  else orbitPocWarm::require(false,"unknown fixture");
  bool rejected=false;try{const auto after=orbitPocWarm::collect(gnss,info,true);orbitPocWarm::require(!shouldReject,"collector failed to reject malformed chart");
    if(mode=="clock_value")orbitPocWarm::require(before.chart==after.chart&&beforeValues!=after.values(),"corrected clock contaminated raw chart");
    else orbitPocWarm::require(before.chart!=after.chart,"changed chart not detected");
  }catch(const std::exception &){if(!shouldReject)throw;rejected=true;}
  orbitPocWarm::require(rejected==shouldReject,"rejection mismatch");return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
