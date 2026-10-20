// Isolated typed-state tests. This does not replace actual GNSS profile gates.
#include "nuisanceWarmState.h"
#include <iostream>
using namespace orbitPocWarm;
void check(bool value){if(!value)throw std::runtime_error("fixture assertion");}
struct SingleIndexVector {double data[2]={1.25,-2.5};std::size_t rows()const{return 2;}std::size_t columns()const{return 1;}double operator()(std::size_t i)const{return data[i];}};
struct DoubleIndexMatrix {double data[2]={1.25,-2.5};std::size_t rows()const{return 2;}std::size_t columns()const{return 1;}double operator()(std::size_t i,std::size_t j)const{check(j==0);return data[i];}};
struct Target {
  double clock=0.000123456789012345,code=1.25,tec=-2.5,bias=4.125,ambiguity=0,iono=3.75,anchor=0.75;
  Ledger ledger(){Ledger l(true);l.id("prior_anchor",anchor);l.id("clock.epoch",std::uint64_t(125));l.id("datum.basis",0.375);l.id("observation.sigma",0.003);l.id("track",std::uint64_t(4));l.value("clock_seconds",clock);l.value("code_full_m",code);l.value("tec_full_m",tec);l.value("shared_bias_m",bias);l.value("float_cycles",ambiguity);l.fixed("STEC",iono);l.fixed("clock_anchor",anchor);return l;}
};
Snapshot snapshot(Ledger &l){Snapshot s;s.mode="receiver_clock_signal_float_v1";s.context=std::string(64,'a');s.chart=sha256(l.chart);s.origin=sha256(l.values());s.prefix="source/qr";s.generation="source/qr.010";s.keys=l.keys;s.values={0.000123456781234567,-4.5,7.75,1.23456789012345,4288.5};return s;}
void settings(const std::string &output){setenv("ORBIT_POC_NUISANCE_WARM_STARTS","1",1);setenv("ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256",std::string(64,'a').c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_OUTPUT",output.c_str(),1);}
int main(int argc,char **argv)
{
  try {
    check(argc==3);const std::string kind=argv[1],root=argv[2],output=root+"/output",input=root+"/input";
    if(kind=="matrix_vector") {const SingleIndexVector v;const DoubleIndexMatrix m;Ledger a(true),b(true);a.matrix("entry",v);b.matrix("entry",m);a.unchangedMatrix("constant",v);b.unchangedMatrix("constant",m);check(a.chart==b.chart&&a.unchanged==b.unchanged);return 0;}
    if(kind=="sha") {check(sha256({})=="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");const std::string abc="abc";check(sha256(Bytes(abc.begin(),abc.end()))=="ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");check(sha256(Bytes(1000000,'a'))=="cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");return 0;}
    if(kind=="disabled"){Session s;check(!s.enabled);beforeInitParameter();return 0;}
    settings(output);Target t;auto l=t.ledger();const auto original=l.values();auto s=snapshot(l);
    if(kind=="roundtrip") {s.values[4]=-0.;const auto b=s.encode();const auto decoded=Snapshot::decode(b);check(decoded.encode()==b);check(std::signbit(decoded.values[4]));return 0;}
    if(kind=="floor"||kind=="nonfresh"||kind=="rank"||kind=="nonconverged"||kind=="export")
    {Session session;session.begin(l);session.verifyRefresh(t.ledger());t.code=9.;t.ambiguity=1.2;auto final=t.ledger();session.finish(final,kind!="nonconverged"&&kind!="floor",kind=="floor",kind!="nonfresh",kind=="rank"?"unresolved":"full","source/qr","source/qr.010");check(exists(output)==(kind=="export"));check(exists(output+".json"));return 0;}
    if(kind=="unknown_switch")setenv("ORBIT_POC_NUISANCE_WARM_STARTS","yes",1);
    if(kind=="unknown_mode")setenv("ORBIT_POC_NUISANCE_WARM_MODE","unrecognized",1);
    if(kind=="disabled_option")setenv("ORBIT_POC_NUISANCE_WARM_STARTS","0",1);
    if(kind=="bad_context")setenv("ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256","bad",1);
    if(kind=="existing_output")writeExclusive(output,{});
    if(kind=="existing_receipt")writeExclusive(output+".json",{});
    if(kind=="context")s.context=std::string(64,'b');
    if(kind=="chart")s.chart=std::string(64,'b');
    if(kind=="origin")s.origin=std::string(64,'b');
    if(kind=="mode")s.mode="receiver_clock_v1";
    if(kind=="unknown_record")s.keys.back()="unknown";
    if(kind=="duplicate_record")s.keys.back()=s.keys.front();
    if(kind=="missing_record"){s.keys.pop_back();s.values.pop_back();}
    if(kind=="prior") {t.anchor=1.;l=t.ledger();}
    if(kind=="weight")l.id("new_weight",0.5);
    if(kind=="basis")l.id("changed_basis",0.25);
    if(kind=="raw_epoch")l.id("changed_epoch",std::uint64_t(126));
    if(kind=="track")l.id("changed_track",std::uint64_t(5));
    auto b=s.encode();if(kind=="trailing")b.push_back(0);if(kind=="truncated")b.pop_back();
    if(kind=="late_nan"){const std::uint64_t nan=0x7ff8000000000001ULL;for(unsigned j=0;j<8;j++)b[b.size()-8+j]=(nan>>(8*j))&255;}
    if(kind=="schema")b[8]='X';
    if(kind=="ineligible_source"){Reader r{b};for(unsigned i=0;i<7;i++)r.text();b[r.offset]=0;}
    if(kind=="oversized_string")for(unsigned i=0;i<8;i++)b[i]=255;
    writeExclusive(input,b);setenv("ORBIT_POC_NUISANCE_WARM_INPUT",input.c_str(),1);setenv("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256",sha256(b).c_str(),1);
    if(kind=="digest")setenv("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256",std::string(64,'b').c_str(),1);
    if(kind=="missing_digest")unsetenv("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256");
    if(kind=="orphan_digest")unsetenv("ORBIT_POC_NUISANCE_WARM_INPUT");
    bool rejected=false;
    try {
      Session session;session.begin(l);
      if(kind=="import"||kind=="lock"||kind=="refresh_iono"||kind=="refresh_anchor"||kind=="refresh_coordinate"){
        check(l.values()!=original);check(t.code==-4.5&&t.tec==7.75&&t.ambiguity==4288.5&&t.iono==3.75&&t.anchor==0.75);
        if(kind=="refresh_iono")t.iono+=1.;if(kind=="refresh_anchor")t.anchor+=1.;if(kind=="refresh_coordinate")t.code+=1.;
        session.verifyRefresh(t.ledger());if(kind=="lock")beforeInitParameter();
      }else throw std::runtime_error("bad seed unexpectedly accepted");
    } catch(const std::exception &e){if(std::string(e.what()).find("Nuisance warm state:")!=0)throw;rejected=true;}
    if(kind=="import"){check(!rejected);bool locked=false;try{beforeInitParameter();}catch(const std::exception &){locked=true;}check(locked);return 0;}
    check(rejected);if(kind!="lock"&&kind.find("refresh_")!=0)check(l.values()==original);
    check(!exists(output)||kind=="existing_output");std::cout<<"passed "<<kind<<"\n";return 0;
  }catch(const std::exception &e){std::cerr<<e.what()<<"\n";return 1;}
}
