// Exact zero encoding regression; this is not a native GNSS equivalence test.
#include "nuisanceWarmState.h"
#include <iostream>
using namespace orbitPocWarm;
void check(bool value){if(!value)throw std::runtime_error("zero fixture assertion");}
std::uint64_t bits(double value){std::uint64_t b;std::memcpy(&b,&value,8);return b;}
double from(std::uint64_t b){double value;std::memcpy(&value,&b,8);return value;}
struct State {
  double coordinate=0.,basis=0.,invariant=0.,physical=7123456.125;
  Ledger ledger(bool signal=true){Ledger l(signal);l.id("basis",basis);l.value("receiver_clock_seconds",coordinate);l.fixed("cold_ionosphere_and_anchor",invariant);return l;}
  std::vector<std::uint64_t> all()const{return {bits(coordinate),bits(basis),bits(invariant),bits(physical)};}
};
void set(State &s,const std::string &category,double value){
  if(category=="coordinate"||category=="all")s.coordinate=value;
  if(category=="chart"||category=="all")s.basis=value;
  if(category=="invariant"||category=="all")s.invariant=value;
}
void configure(const std::string &root,const std::string &mode){
  setenv("ORBIT_POC_NUISANCE_WARM_STARTS","1",1);
  setenv("ORBIT_POC_NUISANCE_WARM_MODE",mode.c_str(),1);
  setenv("ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256",std::string(64,'a').c_str(),1);
  setenv("ORBIT_POC_NUISANCE_WARM_OUTPUT",(root+"/output").c_str(),1);
}
int main(int argc,char **argv){try{
  check(argc>=2);const std::string operation=argv[1];
  if(operation=="codec"){
    // A bitwise reference independent of the candidate encoder preserves every
    // finite nonzero representation, including sign and the two smallest bins.
    const std::uint64_t values[]={0,0x8000000000000000ULL,1,2,0x8000000000000001ULL,
      0x8000000000000002ULL,0x0010000000000000ULL,0x8010000000000000ULL,
      0x3ff0000000000000ULL,0x3ff0000000000001ULL,0xbff0000000000000ULL,
      0xbff0000000000001ULL,0x7fefffffffffffffULL,0xffefffffffffffffULL};
    for(auto original:values){double value=from(original);Bytes encoded;real(encoded,value);
      const auto expected=(original&0x7fffffffffffffffULL)?original:0;
      check(encoded.size()==8);for(unsigned i=0;i<8;i++)check(encoded[i]==((expected>>(8*i))&255));
      Reader reader{encoded};check(bits(reader.real())==expected);check(bits(value)==original);
    }
    Bytes positive,negative;real(positive,0.);real(negative,-0.);check(positive==negative);
    return 0;
  }
  check(argc>=7);const std::string root=argv[2],category=argv[3],mode=argv[4];
  const auto beforeBits=std::stoull(argv[5],nullptr,16),afterBits=std::stoull(argv[6],nullptr,16);
  State state;set(state,category,from(beforeBits));configure(root,mode);
  if(operation=="reject_nonfinite"){
    const auto original=state.all();bool rejected=false;
    try{auto l=state.ledger();(void)l.values();}catch(const std::exception &e){check(std::string(e.what()).find("nonfinite")!=std::string::npos);rejected=true;}
    check(rejected&&state.all()==original&&!exists(root+"/output"));return 0;
  }
  if(operation=="import"||operation=="reject_import"){
    check(argc==8);const std::string input=argv[7];auto bytes=read(input);
    setenv("ORBIT_POC_NUISANCE_WARM_INPUT",input.c_str(),1);
    setenv("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256",sha256(bytes).c_str(),1);
  }
  Session session;auto l=state.ledger(session.signal);const auto original=state.all();
  if(operation=="reject_import"){
    bool rejected=false;try{session.begin(l);}catch(const std::exception &e){check(std::string(e.what()).find("mismatch")!=std::string::npos);rejected=true;}
    check(rejected&&state.all()==original&&!exists(root+"/output"));return 0;
  }
  session.begin(l);
  if(operation=="export"||operation=="reject_refresh")check(state.all()==original);
  else {check(operation=="import"&&session.imported);check(state.basis==from(beforeBits)||category!="chart");check(bits(state.physical)==original[3]);}
  set(state,category,from(afterBits));const auto refreshed=state.all();
  if(operation=="reject_refresh"){
    bool rejected=false;try{session.verifyRefresh(state.ledger(session.signal));}catch(const std::exception &e){check(std::string(e.what()).find("Nuisance warm state:")==0);rejected=true;}
    check(rejected&&state.all()==refreshed&&!exists(root+"/output"));return 0;
  }
  session.verifyRefresh(state.ledger(session.signal));check(state.all()==refreshed);
  session.finish(state.ledger(session.signal),true,false,true,"full",root+"/qr",root+"/qr.3");
  check(state.all()==refreshed&&bits(state.physical)==original[3]);
  auto snapshot=Snapshot::decode(read(root+"/output"));check(snapshot.values.size()==1);
  check(bits(snapshot.values[0])==0);check(exists(root+"/output.json"));return 0;
}catch(const std::exception &e){std::cerr<<e.what()<<'\n';return 1;}}
