// Cold-origin semantics only; real GNSS target equivalence is a separate gate.
#include "nuisanceWarmState.h"
#include <iostream>
using namespace orbitPocWarm;
void check(bool v){if(!v)throw std::runtime_error("clock-origin fixture assertion");}
struct State {
  double clock=1.6122875691377576e-7,other=2.5,anchor=35.25,weight=4.,ionosphere=0.,physical=7123456.;
  Ledger ledger(bool signal=true,bool typed=true){Ledger l(signal);l.id("prior_anchor",anchor);l.fixed("prior_anchor",anchor);l.id("weight",weight);if(typed)l.receiverClockGuess("receiver/0/clock_seconds",clock);else l.value("receiver/0/clock_seconds",clock);l.value("full_bias",other);l.fixed("cold_ionosphere",ionosphere);return l;}
  Bytes all()const {Bytes b;for(auto v:{clock,other,anchor,weight,ionosphere,physical})real(b,v);return b;}
};
int main(int argc,char **argv){try{
  check(argc==3);std::string action=argv[1],root=argv[2];State source,target;
  auto sourceLedger=source.ledger();auto oldClock=source.clock;source.clock=std::nextafter(source.clock,INFINITY);
  check(sha256(sourceLedger.coldOrigin())==sha256(target.ledger().coldOrigin()));
  check(sourceLedger.values()!=target.ledger().values());source.clock=oldClock;
  Snapshot s;s.mode="receiver_clock_signal_float_v1";s.context=std::string(64,'a');s.chart=sha256(source.ledger().chart);s.origin=sha256(source.ledger().coldOrigin());s.prefix="source/qr";s.generation="source/qr.7";s.keys=source.ledger().keys;s.values={.00023456789,7.25};
  target.clock=std::nextafter(target.clock,INFINITY);
  if(action=="large_guess")target.clock=9.25;
  if(action=="negative_guess")target.clock=-9.25;
  if(action=="subnormal_guess")target.clock=std::numeric_limits<double>::denorm_min();
  if(action=="prior")target.anchor=std::nextafter(target.anchor,INFINITY);
  if(action=="weight")target.weight=std::nextafter(target.weight,INFINITY);
  if(action=="nonclock")target.other=std::nextafter(target.other,INFINITY);
  if(action=="nonfinite_guess")target.clock=INFINITY;
  if(action=="old_policy"){
    auto legacy=source.ledger();Bytes prefix;text(prefix,"cold_origin_policy");text(prefix,coldOriginPolicy());
    check(legacy.chart.size()>prefix.size()&&std::equal(prefix.begin(),prefix.end(),legacy.chart.begin()));legacy.chart.erase(legacy.chart.begin(),legacy.chart.begin()+prefix.size());s.chart=sha256(legacy.chart); // Keep matching origin: the old chart policy alone must reject.
  }
  if(action=="untyped")s.chart=sha256(source.ledger(true,false).chart);
  if(action=="clock_mode")s.mode="receiver_clock_v1";
  auto bytes=s.encode();writeExclusive(root+"/input",bytes);
  setenv("ORBIT_POC_NUISANCE_WARM_STARTS","1",1);setenv("ORBIT_POC_NUISANCE_WARM_MODE",s.mode.c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256",s.context.c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_INPUT",(root+"/input").c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256",sha256(bytes).c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_OUTPUT",(root+"/output").c_str(),1);
  bool reject=action=="prior"||action=="weight"||action=="nonclock"||action=="old_policy"||action=="untyped"||action=="nonfinite_guess";
  Bytes before;if(action!="nonfinite_guess")before=target.all();bool rejected=false;Session session;
  try{auto l=target.ledger(session.signal);session.begin(l);}catch(const std::exception &e){check(std::string(e.what()).find("Nuisance warm state:")==0);rejected=true;}
  if(reject){check(rejected&&!session.imported&&!exists(root+"/output"));if(action=="nonfinite_guess")check(std::isinf(target.clock)&&target.other==2.5&&target.anchor==35.25&&target.ionosphere==0.);else check(target.all()==before);return 0;}
  check(!rejected&&session.imported&&target.clock==s.values[0]&&target.other==s.values[1]);check(target.anchor==35.25&&target.weight==4.&&target.ionosphere==0.&&target.physical==7123456.);
  if(action=="refresh_clock")target.clock=std::nextafter(target.clock,INFINITY);
  if(action=="refresh_anchor")target.anchor=std::nextafter(target.anchor,INFINITY);
  if(action=="refresh_ionosphere")target.ionosphere=std::numeric_limits<double>::denorm_min();
  const bool badRefresh=action=="refresh_clock"||action=="refresh_anchor"||action=="refresh_ionosphere";before=target.all();rejected=false;
  try{session.verifyRefresh(target.ledger(session.signal));}catch(const std::exception &e){rejected=true;}
  check(rejected==badRefresh&&target.all()==before);if(badRefresh){check(!exists(root+"/output"));return 0;}
  session.finish(target.ledger(session.signal),true,false,true,"full",root+"/qr",root+"/qr.7");check(target.all()==before);
  auto exported=Snapshot::decode(read(root+"/output"));check(exported.values==s.values&&exported.origin==s.origin&&exported.chart==s.chart);return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
