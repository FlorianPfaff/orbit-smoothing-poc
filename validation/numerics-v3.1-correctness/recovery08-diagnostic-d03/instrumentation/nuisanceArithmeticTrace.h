// Diagnostic D03 only. No estimator arithmetic or acceptance changes.
#ifndef ORBIT_POC_D03_NUISANCE_ARITHMETIC_TRACE_H
#define ORBIT_POC_D03_NUISANCE_ARITHMETIC_TRACE_H
#include <cerrno>
#include <cfenv>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <sys/stat.h>
#include <unistd.h>
namespace orbitPocD03 {
struct Context {std::string stem,phase="unassigned",component;unsigned long long generation=0,receiver=~0ULL,transmitter=~0ULL,epoch=~0ULL,row=0;double alpha=0;};
inline Context &context(){static thread_local Context c;return c;}
inline unsigned long long &event(){static thread_local unsigned long long v=0;return v;}
inline unsigned long long &evaluation(){static thread_local unsigned long long v=0;return v;}
inline const char *directory(){const char *p=std::getenv("ORBIT_POC_D03_DIRECTORY");return p&&*p?p:nullptr;}
inline bool selected(){const auto &c=context();return directory()&&c.generation==4&&(c.phase=="baseline"||c.phase=="joint"||(c.phase=="trial"&&(c.alpha==0.||c.alpha==1.)));}
struct Preserve {int error=errno;fenv_t state;Preserve(){if(std::fegetenv(&state))throw std::runtime_error("D03 cannot save floating environment");}~Preserve(){std::fesetenv(&state);errno=error;}};
inline void write(const char *stage,const char *kind,unsigned long long row,unsigned long long index,const std::string &value,const std::string &bits)
{
 if(!selected())return;Preserve saved;const char *d=directory();struct stat info;
 if(d[0]!='/'||::stat(d,&info)||!S_ISDIR(info.st_mode))throw std::runtime_error("D03 trace directory must exist and be absolute");
 const auto &c=context();const char *audit=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
 std::ofstream f(std::string(d)+"/nuisance-trace-"+std::to_string(static_cast<long long>(::getpid()))+".tsv",std::ios::app);
 f<<c.stem<<'\t'<<c.phase<<'\t'<<std::hexfloat<<c.alpha<<'\t'<<c.receiver<<'\t'<<c.transmitter<<'\t'<<c.epoch<<'\t'<<row<<'\t'<<c.component<<'\t'<<stage<<'\t'<<kind<<'\t'<<index<<'\t'<<value<<'\t'<<bits<<'\t'<<evaluation()<<'\t'<<++event()<<'\t'<<(audit?audit:"0")<<'\n';f.close();if(!f)throw std::runtime_error("D03 trace write failed");
}
inline void scalar(const char *stage,double value,unsigned long long row=0,unsigned long long index=0)
{if(!selected())return;Preserve saved;std::uint64_t bits;static_assert(sizeof(bits)==sizeof(value),"D03 requires binary64");std::memcpy(&bits,&value,sizeof(bits));std::ostringstream a,b;a<<std::hexfloat<<value;b<<std::hex<<std::setfill('0')<<std::setw(16)<<bits;write(stage,"double",row,index,a.str(),b.str());}
inline void extended(const char *stage,long double value,unsigned long long row=0,unsigned long long index=0)
{if(!selected())return;Preserve saved;std::ostringstream a;a<<std::hexfloat<<value;write(stage,"long_double",row,index,a.str(),"-");}
inline void text(const char *stage,const std::string &value,unsigned long long row=0,unsigned long long index=0)
{if(!selected())return;if(value.find_first_of("\t\r\n")!=std::string::npos)throw std::runtime_error("D03 text contains delimiter");write(stage,"text",row,index,value,"-");}
inline void generation(const std::string &stem,unsigned long long value){auto &c=context();c.stem=stem;c.generation=value;c.phase="baseline";c.alpha=0.;++evaluation();}
inline void phase(const char *value){context().phase=value;++evaluation();}
inline void trial(double alpha){context().phase="trial";context().alpha=alpha;++evaluation();}
inline void component(const char *value){context().component=value;}
struct Equation {Context saved;Equation(unsigned long long receiver,unsigned long long transmitter,unsigned long long epoch):saved(context()){auto &c=context();c.receiver=receiver;c.transmitter=transmitter;c.epoch=epoch;c.row=0;c.component.clear();}~Equation(){context()=saved;}};
struct Component {std::string saved;explicit Component(const char *name):saved(context().component){component(name);}~Component(){context().component=saved;}};
inline void guard(unsigned long long completed,const std::string &prefix)
{
 const char *limit=std::getenv("ORBIT_POC_D03_MAX_GENERATIONS");if(!limit)return;
 if(std::string(limit)!="4")throw std::runtime_error("D03 generation limit must be exactly4");
 if(completed<4)return;Preserve saved;std::ofstream f(prefix+".diagnostic-incomplete.json");
 f<<"{\"schema\":\"orbit-poc-d03-generation-stop-v1\",\"diagnostic_only\":true,\"scientific_complete\":false,\"completed_generations\":4,\"reason\":\"bounded diagnostic stopped before generation5\"}\n";f.close();if(!f)throw std::runtime_error("D03 cannot record diagnostic stop");
 throw std::runtime_error("D03 diagnostic generation limit reached; scientific validation incomplete");
}
template<class V> inline auto element(const V &v,unsigned long long i,unsigned long long j,int)->decltype(v(i,j)){return v(i,j);}
template<class V> inline auto element(const V &v,unsigned long long i,unsigned long long j,long)->decltype(v(i)){if(j)throw std::runtime_error("D03 vector has multiple columns");return v(i);}
template<class V> inline void matrix(const char *stage,const V &v,unsigned long long columnOffset=0)
{if(!selected())return;for(unsigned long long i=0;i<v.rows();i++)for(unsigned long long j=0;j<v.columns();j++)scalar(stage,element(v,i,j,0),i,columnOffset+j);}
template<class V> inline void vector3(const char *stage,const V &v){if(!selected())return;scalar(stage,v.x(),0);scalar(stage,v.y(),1);scalar(stage,v.z(),2);}
template<class V> inline void array(const char *stage,const V &v){if(!selected())return;for(unsigned long long i=0;i<v.size();i++)scalar(stage,v.at(i),i);}
template<class V> inline void extendedArray(const char *stage,const V &v){if(!selected())return;for(unsigned long long i=0;i<v.size();i++)extended(stage,v.at(i),i);}
template<class V> inline void pair(const char *stage,const V &v,unsigned long long row=0,unsigned long long index=0)
{extended((std::string(stage)+".high").c_str(),v.high,row,index);extended((std::string(stage)+".low").c_str(),v.low,row,index);}
template<class V> inline void precise(const char *stage,const V &v){if(!selected())return;for(unsigned long long i=0;i<v.size();i++)pair(stage,v.at(i),i);}
template<class T> inline void time(const char *stage,const T &value){if(!selected())return;scalar((std::string(stage)+".day").c_str(),value.mjdInt());scalar((std::string(stage)+".fraction").c_str(),value.mjdMod());}
template<class T> inline T pairOperand(const char *stage,T value){pair(stage,value,context().row);return value;}
template<class T> inline T operand(const char *stage,T value){scalar(stage,value);return value;}
template<class T> inline T extendedOperand(const char *stage,T value){extended(stage,value);return value;}
template<class F> inline void shadow(const F &f){if(selected()){Preserve saved;f();}}
inline std::map<const void*,std::tuple<unsigned long long,unsigned long long,unsigned long long>> &observations(){static thread_local std::map<const void*,std::tuple<unsigned long long,unsigned long long,unsigned long long>> m;return m;}
inline void registerObservation(const void *p,unsigned long long r,unsigned long long t,unsigned long long e){if(directory())observations()[p]=std::make_tuple(r,t,e);}
struct Observation {Context saved;explicit Observation(const void *p):saved(context()){auto found=observations().find(p);if(found!=observations().end())std::tie(context().receiver,context().transmitter,context().epoch)=found->second;}~Observation(){context()=saved;}};
template<class I,class V> inline void sparse(const char *stage,unsigned long long row,const I &ids,const V &values)
{if(!selected())return;if(ids.size()!=values.size())throw std::runtime_error("D03 sparse row size mismatch");for(unsigned long long k=0;k<ids.size();k++)scalar(stage,values[k],row,ids[k]);}
}
#endif
