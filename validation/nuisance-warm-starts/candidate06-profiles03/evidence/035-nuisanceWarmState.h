// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_NUISANCE_WARM_STATE_H
#define ORBIT_POC_NUISANCE_WARM_STATE_H
// Initialization values only. No physical, ionospheric, QR or covariance state.
#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>
namespace orbitPocWarm {
using Bytes=std::vector<unsigned char>;
inline void require(bool ok,const std::string &why){if(!ok)throw std::runtime_error("Nuisance warm state: "+why);}
inline std::string env(const char *key){const char *v=std::getenv(key);return v?v:"";}
inline bool hex(const std::string &v){return v.size()==64&&std::all_of(v.begin(),v.end(),[](char c){return (c>='0'&&c<='9')||(c>='a'&&c<='f');});}
inline std::uint32_t rotate(std::uint32_t x,unsigned n){return (x>>n)|(x<<(32-n));}
inline std::string sha256(const Bytes &input)
{
  static const std::uint32_t k[64]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
  0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
  0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
  0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
  0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
  0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
  std::array<std::uint32_t,8> h={0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
  Bytes data=input;const std::uint64_t bits=std::uint64_t(data.size())*8;data.push_back(0x80);
  while(data.size()%64!=56)data.push_back(0);for(int j=7;j>=0;j--)data.push_back((bits>>(8*j))&255);
  for(std::size_t b=0;b<data.size();b+=64)
  {
    std::uint32_t w[64];for(unsigned j=0;j<16;j++)w[j]=(std::uint32_t(data[b+4*j])<<24)|(std::uint32_t(data[b+4*j+1])<<16)|(std::uint32_t(data[b+4*j+2])<<8)|data[b+4*j+3];
    for(unsigned j=16;j<64;j++)w[j]=w[j-16]+(rotate(w[j-15],7)^rotate(w[j-15],18)^(w[j-15]>>3))+w[j-7]+(rotate(w[j-2],17)^rotate(w[j-2],19)^(w[j-2]>>10));
    auto v=h;for(unsigned j=0;j<64;j++){const auto t1=v[7]+(rotate(v[4],6)^rotate(v[4],11)^rotate(v[4],25))+((v[4]&v[5])^(~v[4]&v[6]))+k[j]+w[j];const auto t2=(rotate(v[0],2)^rotate(v[0],13)^rotate(v[0],22))+((v[0]&v[1])^(v[0]&v[2])^(v[1]&v[2]));for(unsigned z=7;z>0;z--)v[z]=v[z-1];v[4]+=t1;v[0]=t1+t2;}
    for(unsigned j=0;j<8;j++)h[j]+=v[j];
  }
  std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto v:h)out<<std::setw(8)<<v;return out.str();
}
inline void number(Bytes &out,std::uint64_t value){for(unsigned j=0;j<8;j++)out.push_back((value>>(8*j))&255);}
inline void text(Bytes &out,const std::string &value){require(value.size()<=1024*1024,"string too large");number(out,value.size());out.insert(out.end(),value.begin(),value.end());}
// Exact real-coordinate identity: IEEE -0 and +0 encode as +0. All finite
// nonzero bits (including subnormals) remain unchanged; no state is modified.
inline void real(Bytes &out,double value){static_assert(sizeof(double)==8&&std::numeric_limits<double>::is_iec559,"IEEE binary64 required");require(std::isfinite(value),"nonfinite coordinate/identity");std::uint64_t bits;std::memcpy(&bits,&value,8);if((bits&0x7fffffffffffffffULL)==0)bits=0;number(out,bits);}
struct Reader {
  const Bytes &data;std::size_t offset=0;
  std::uint64_t number(){require(data.size()-offset>=8,"truncated integer");std::uint64_t value=0;for(unsigned j=0;j<8;j++)value|=std::uint64_t(data[offset++])<<(8*j);return value;}
  std::string text(){const auto n=number();require(n<=1024*1024&&n<=data.size()-offset,"invalid string length");std::string value(data.begin()+offset,data.begin()+offset+n);offset+=n;require(value.find('\0')==std::string::npos,"embedded NUL");return value;}
  double real(){auto bits=number();double value;std::memcpy(&value,&bits,8);require(std::isfinite(value),"nonfinite imported coordinate");return value;}
};
inline Bytes read(const std::string &path){std::ifstream f(path,std::ios::binary|std::ios::ate);require(bool(f),"cannot open input");const auto n=f.tellg();require(n>=0&&n<=64*1024*1024,"invalid input length");Bytes result(static_cast<std::size_t>(n));f.seekg(0);if(n)f.read(reinterpret_cast<char*>(result.data()),n);require(bool(f),"cannot read input");return result;}
inline bool exists(const std::string &path){return ::access(path.c_str(),F_OK)==0;}
inline void writeExclusive(const std::string &path,const Bytes &bytes)
{
  const int fd=::open(path.c_str(),O_WRONLY|O_CREAT|O_EXCL,0600);require(fd>=0,"output already exists or cannot be created: "+path);
  std::size_t done=0;while(done<bytes.size()){const auto n=::write(fd,bytes.data()+done,bytes.size()-done);if(n<0&&errno==EINTR)continue;if(n<=0){::close(fd);throw std::runtime_error("Nuisance warm state: output write failed");}done+=n;}
  const int flushed=::fsync(fd),closed=::close(fd);require(flushed==0&&closed==0,"output close failed");
}
inline std::string quote(const std::string &s){std::ostringstream out;out<<'"';for(unsigned char c:s){if(c=='"'||c=='\\')out<<'\\'<<c;else if(c<32)out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<unsigned(c)<<std::dec;else out<<c;}out<<'"';return out.str();}
// Native Vector deliberately hides Matrix::operator()(row,column). Select its
// one-coordinate API without copying values or changing their representation.
template<class T> inline auto entry(const T &m,std::size_t i,std::size_t j,int)->decltype(m(i,j)){return m(i,j);}
template<class T> inline auto entry(const T &m,std::size_t i,std::size_t j,long)->decltype(m(i)){require(j==0,"vector is not a column");return m(i);}
inline const char *coldOriginPolicy(){return "receiver-clock-starting-guess-excluded-v2";}
struct Ledger {
  bool signal;Bytes chart,unchanged;std::vector<double*> bindings;std::vector<bool> initialReceiverClock;std::vector<std::string> keys;std::set<std::string> unique;std::set<const void*> signalOwners;
  explicit Ledger(bool signal):signal(signal){id("cold_origin_policy",std::string(coldOriginPolicy()));}
  void id(const std::string &key,const std::string &v){text(chart,key);text(chart,v);}
  void id(const std::string &key,std::uint64_t v){text(chart,key);number(chart,v);}
  void id(const std::string &key,double v){text(chart,key);real(chart,v);}
  void fixed(const std::string &key,double v){text(unchanged,key);real(unchanged,v);}
  void value(const std::string &key,double &v){require(unique.insert(key).second,"duplicate coordinate: "+key);require(std::isfinite(v),"nonfinite current coordinate");id("coordinate",key);keys.push_back(key);bindings.push_back(&v);initialReceiverClock.push_back(false);}
  // Receiver clk is an estimable starting guess, not its separately hashed x0
  // prior anchor. Only this typed binding is excluded from cold-origin equality.
  // Every imported/refresh value still participates in exact values() checks.
  void receiverClockGuess(const std::string &key,double &v){value(key,v);initialReceiverClock.back()=true;id("receiver_clock_initial_guess",key);}
  Bytes coldOrigin() const {require(initialReceiverClock.size()==bindings.size(),"cold-origin binding shape mismatch");Bytes result;for(std::size_t i=0;i<bindings.size();i++){require(std::isfinite(*bindings[i]),"nonfinite current coordinate");if(!initialReceiverClock[i])real(result,*bindings[i]);}return result;}
  template<class Matrix> void matrix(const std::string &key,const Matrix &m){id(key+".rows",std::uint64_t(m.rows()));id(key+".columns",std::uint64_t(m.columns()));for(std::size_t i=0;i<m.rows();i++)for(std::size_t j=0;j<m.columns();j++)id(key+".entry",double(entry(m,i,j,0)));}
  template<class Vector> void values(const std::string &key,Vector &v){id(key+".size",std::uint64_t(v.rows()));for(std::size_t i=0;i<v.rows();i++)value(key+"/"+std::to_string(i),v(i));}
  template<class Matrix> void unchangedMatrix(const std::string &key,const Matrix &m){id(key+".rows",std::uint64_t(m.rows()));id(key+".columns",std::uint64_t(m.columns()));for(std::size_t i=0;i<m.rows();i++)for(std::size_t j=0;j<m.columns();j++)fixed(key+".entry",double(entry(m,i,j,0)));}
  template<class Types> void types(const std::string &key,const Types &values){id(key+".size",std::uint64_t(values.size()));for(const auto &v:values)id(key+".type",v.str());}
  template<class Info,class Index> void index(const std::string &key,const Info &info,const Index &index){id(key+".selected",std::uint64_t(bool(index)));if(index){id(key+".index",std::uint64_t(info.index(index)));id(key+".count",std::uint64_t(info.count(index)));}}
  Bytes values() const {Bytes result;for(auto p:bindings)real(result,*p);return result;}
};
struct Snapshot {
  std::string mode,context,chart,origin,prefix,generation;std::vector<std::string> keys;std::vector<double> values;
  Bytes encode()const {Bytes b;text(b,"orbit-poc-native-nuisance-warm-state-v1");for(const auto &s:{mode,context,chart,origin,prefix,generation})text(b,s);number(b,1);number(b,keys.size());require(keys.size()==values.size(),"coordinate count mismatch");for(std::size_t i=0;i<keys.size();i++){text(b,keys[i]);real(b,values[i]);}return b;}
  static Snapshot decode(const Bytes &b){Reader r{b};require(r.text()=="orbit-poc-native-nuisance-warm-state-v1","schema mismatch");Snapshot s;s.mode=r.text();s.context=r.text();s.chart=r.text();s.origin=r.text();s.prefix=r.text();s.generation=r.text();require(s.mode=="receiver_clock_v1"||s.mode=="receiver_clock_signal_float_v1","unknown mode");require(hex(s.context)&&hex(s.chart)&&hex(s.origin),"invalid identity digest");require(!s.prefix.empty()&&!s.generation.empty(),"missing source attribution");require(r.number()==1,"source not strict/fresh/undamped/full-rank");const auto n=r.number();require(n>0&&n<=1000000,"invalid coordinate count");std::set<std::string> seen;for(std::uint64_t i=0;i<n;i++){auto key=r.text();require(!key.empty()&&seen.insert(key).second,"empty/duplicate coordinate");s.keys.push_back(key);s.values.push_back(r.real());}require(r.offset==b.size(),"trailing input bytes");return s;}
};
inline bool &chartLocked(){static bool locked=false;return locked;}
inline void beforeInitParameter(){require(!chartLocked(),"parameter chart reinitialized after warm session initialization");}
struct Session {
  bool enabled=false,signal=false,imported=false,refreshed=false;std::string mode,context,input,inputSha,output,chart,origin;Bytes coldInvariant,importedValues;
  Session(){const auto on=env("ORBIT_POC_NUISANCE_WARM_STARTS");require(on.empty()||on=="0"||on=="1","WARM_STARTS must be 0 or 1");enabled=on=="1";if(!enabled){for(const auto key:{"ORBIT_POC_NUISANCE_WARM_INPUT","ORBIT_POC_NUISANCE_WARM_INPUT_SHA256","ORBIT_POC_NUISANCE_WARM_OUTPUT","ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256","ORBIT_POC_NUISANCE_WARM_MODE"})require(env(key).empty(),"warm option supplied while disabled");return;}
    mode=env("ORBIT_POC_NUISANCE_WARM_MODE");if(mode.empty())mode="receiver_clock_signal_float_v1";require(mode=="receiver_clock_v1"||mode=="receiver_clock_signal_float_v1","unknown mode");signal=mode!="receiver_clock_v1";context=env("ORBIT_POC_NUISANCE_WARM_CONTEXT_SHA256");require(hex(context),"invalid context digest");input=env("ORBIT_POC_NUISANCE_WARM_INPUT");inputSha=env("ORBIT_POC_NUISANCE_WARM_INPUT_SHA256");require(input.empty()?inputSha.empty():hex(inputSha),"input digest required iff input supplied");output=env("ORBIT_POC_NUISANCE_WARM_OUTPUT");require(!output.empty(),"output required");require(!exists(output)&&!exists(output+".json"),"output already exists");require(!chartLocked(),"nested warm session");}
  // One native profile per fresh process. Keep the chart locked after export:
  // later parameter reinitialization must not reset imported full coordinates.
  ~Session()=default;
  void begin(Ledger &l){if(!enabled)return;require(!l.bindings.empty(),"no eligible coordinates");chart=sha256(l.chart);origin=sha256(l.coldOrigin());coldInvariant=l.unchanged;
    if(!input.empty()){const auto b=read(input);require(sha256(b)==inputSha,"input digest mismatch");const auto s=Snapshot::decode(b);require(s.mode==mode&&s.context==context&&s.chart==chart&&s.origin==origin,"mode/context/chart/cold-origin mismatch");require(s.keys==l.keys&&s.values.size()==l.bindings.size(),"coordinate chart mismatch");
      // Every parse, digest, finite and identity check completes before this loop.
      for(std::size_t i=0;i<s.values.size();i++)*l.bindings[i]=s.values[i];imported=true;}
    importedValues=l.values();chartLocked()=true;}
  void verifyRefresh(const Ledger &l){if(!enabled)return;require(sha256(l.chart)==chart&&l.values()==importedValues,"zero refresh changed imported chart/coordinates");require(l.unchanged==coldInvariant,"import/zero refresh changed cold ionosphere or prior anchors");refreshed=true;}
  void finish(const Ledger &l,bool strict,bool floor,bool fresh,const std::string &rank,const std::string &prefix,const std::string &generation)
  {
    if(!enabled)return;require(refreshed,"missing import refresh verification");require(sha256(l.chart)==chart,"profile changed chart/support");const bool eligible=strict&&!floor&&fresh&&rank=="full";std::string digest;
    if(eligible){Snapshot s;s.mode=mode;s.context=context;s.chart=chart;s.origin=origin;s.prefix=prefix;s.generation=generation;s.keys=l.keys;for(auto p:l.bindings)s.values.push_back(*p);const auto bytes=s.encode();digest=sha256(bytes);writeExclusive(output,bytes);}
    std::ostringstream r;r<<"{\"schema\":\"orbit-poc-native-nuisance-warm-state-v1\",\"mode\":"<<quote(mode)<<",\"context_sha256\":"<<quote(context)<<",\"chart_sha256\":"<<quote(chart)<<",\"cold_origin_sha256\":"<<quote(origin)<<",\"payload_sha256\":"<<(eligible?quote(digest):"null")<<",\"source_prefix\":"<<quote(prefix)<<",\"source_generation\":"<<quote(generation)<<",\"eligibility\":{\"nuisance_converged\":"<<(strict?"true":"false")<<",\"nuisance_floor_limited\":"<<(floor?"true":"false")<<",\"fresh_undamped\":"<<(fresh?"true":"false")<<",\"rank_status\":"<<quote(rank)<<"},\"imported\":{\"used\":"<<(imported?"true":"false")<<",\"path\":"<<quote(input)<<",\"sha256\":"<<quote(inputSha)<<"},\"counts\":{\"coordinates\":"<<l.bindings.size()<<"},\"invariants\":{\"target_cold_ionosphere_unchanged\":true,\"target_clock_prior_anchors_unchanged\":true},\"export_status\":"<<quote(eligible?"exported":"ineligible")<<"}\n";
    const auto body=r.str();writeExclusive(output+".json",Bytes(body.begin(),body.end()));
  }
};
}
#endif
