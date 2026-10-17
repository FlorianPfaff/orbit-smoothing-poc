// Diagnostic only: original expressions retain their native arithmetic.
#ifndef ORBIT_POC_ROW_ARITHMETIC_TRACE_H
#define ORBIT_POC_ROW_ARITHMETIC_TRACE_H
#include <cerrno>
#include <cfenv>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <tuple>
#include <typeinfo>
#include <sys/stat.h>
#include <unistd.h>
namespace orbitPocTrace
{
struct Context
{
  std::string stem, phase="unassigned", component;
  double alpha=0;
  unsigned long long receiver=0,transmitter=0,epoch=0,row=0;
  bool equation=false;
};
inline Context &context(){static thread_local Context value;return value;}
inline unsigned long long &evaluation(){static thread_local unsigned long long value=0;return value;}
inline unsigned long long &event(){static thread_local unsigned long long value=0;return value;}
inline const char *directory(){const char *v=std::getenv("ORBIT_POC_ROW_TRACE_DIRECTORY");return v&&*v?v:nullptr;}
inline bool blockSelected()
{
  const auto &c=context();if(!c.equation||c.receiver!=0)return false;
  return (c.transmitter==13&&c.epoch==30)||(c.transmitter==4&&c.epoch==115)||
         (c.transmitter==16&&c.epoch==8)||(c.transmitter==9&&(c.epoch==114||c.epoch==113));
}
inline bool rowSelected(unsigned long long row)
{
  const auto &c=context();if(!blockSelected())return false;
  return (c.transmitter==13&&c.epoch==30&&row==5)||(c.transmitter==4&&c.epoch==115&&row==1)||
         (c.transmitter==16&&c.epoch==8&&row==4)||(c.transmitter==9&&c.epoch==114&&row==4)||
         (c.transmitter==9&&c.epoch==113&&row==5);
}
struct PreserveEnvironment
{
  int savedErrno=errno;fenv_t state;
  PreserveEnvironment(){if(std::fegetenv(&state))throw std::runtime_error("Cannot snapshot diagnostic floating environment");}
  ~PreserveEnvironment(){std::fesetenv(&state);errno=savedErrno;}
};
inline void write(const char *stage,const char *kind,unsigned long long row,unsigned long long index,const std::string &value,const std::string &bits)
{
  const char *dir=directory();if(!dir||!blockSelected())return;
  PreserveEnvironment preserve;
  struct stat info;if(dir[0]!='/'||::stat(dir,&info)||!S_ISDIR(info.st_mode))throw std::runtime_error("Diagnostic trace directory must already exist and be absolute");
  const auto &c=context();
  // Never retain a writable descriptor across nuisance-trial forks.
  const std::string path=std::string(dir)+"/row-trace-"+std::to_string(static_cast<long long>(::getpid()))+".tsv";
  std::ofstream file(path,std::ios::app);
  const char *audit=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
  file<<c.stem<<'\t'<<c.phase<<'\t'<<std::hexfloat<<c.alpha<<'\t'<<c.receiver<<'\t'<<c.transmitter<<'\t'<<c.epoch<<'\t'<<row<<'\t'<<c.component<<'\t'<<stage<<'\t'<<kind<<'\t'<<index<<'\t'<<value<<'\t'<<bits<<'\t'<<evaluation()<<'\t'<<++event()<<'\t'<<(audit?audit:"0")<<'\n';
  file.close();if(!file)throw std::runtime_error("Diagnostic row trace write failed");
}
inline void scalar(const char *stage,double value,unsigned long long row,unsigned long long index=0)
{
  if(!directory()||!blockSelected())return;
  PreserveEnvironment preserve;std::uint64_t bits;static_assert(sizeof(bits)==sizeof(value),"binary64 trace required");std::memcpy(&bits,&value,sizeof(bits));
  std::ostringstream encoded,raw;encoded<<std::hexfloat<<value;raw<<std::hex<<std::setfill('0')<<std::setw(16)<<bits;
  write(stage,"double",row,index,encoded.str(),raw.str());
}
inline void extended(const char *stage,long double value,unsigned long long row,unsigned long long index=0)
{
  if(!directory()||!blockSelected())return;
  PreserveEnvironment preserve;std::ostringstream encoded;encoded<<std::hexfloat<<value;
  // hexfloat is exact and excludes indeterminate x87 padding bytes.
  write(stage,"long_double",row,index,encoded.str(),"-");
}
inline void begin(const std::string &stem,const char *phase,double alpha)
{if(directory()){context().stem=stem;context().phase=phase;context().alpha=alpha;++evaluation();}}
struct Equation
{
  Context saved;
  Equation(unsigned long long receiver,unsigned long long transmitter,unsigned long long epoch):saved(context())
  {auto &c=context();c.receiver=receiver;c.transmitter=transmitter;c.epoch=epoch;c.row=0;c.equation=true;c.component.clear();}
  ~Equation(){context()=saved;}
};
inline std::map<const void *,std::tuple<unsigned long long,unsigned long long,unsigned long long>> &observations()
{static thread_local std::map<const void *,std::tuple<unsigned long long,unsigned long long,unsigned long long>> result;return result;}
inline void registerObservation(const void *pointer,unsigned long long receiver,unsigned long long transmitter,unsigned long long epoch)
{if(directory()){Equation scope(receiver,transmitter,epoch);if(blockSelected())observations()[pointer]=std::make_tuple(receiver,transmitter,epoch);}}
struct Observation
{
  Context saved;
  explicit Observation(const void *pointer):saved(context())
  {
    if(!directory())return;auto found=observations().find(pointer);context().equation=false;
    if(found!=observations().end()){auto &c=context();std::tie(c.receiver,c.transmitter,c.epoch)=found->second;c.equation=true;c.row=0;c.component="local_STEC_update";}
  }
  ~Observation(){context()=saved;}
};
inline void row(unsigned long long value){context().row=value;}
inline void component(const char *value){context().component=value;}
// GROOPS Vector hides Matrix's two-index operator with its one-index operator.
// Prefer the actual two-index API, falling back only for a vector expression.
template<class V> inline auto element(const V &values,unsigned long long i,unsigned long long j,int)
  -> decltype(values(i,j)) {return values(i,j);}
template<class V> inline auto element(const V &values,unsigned long long i,unsigned long long j,long)
  -> decltype(values(i))
{if(j!=0)throw std::runtime_error("One-index diagnostic operand has multiple columns");return values(i);}
template<class V> inline void vector(const char *stage,const V &values)
{
  if(!directory()||!blockSelected())return;
  for(unsigned long long i=0;i<values.rows();i++)if(rowSelected(i))scalar(stage,element(values,i,0,0),i);
}
template<class V> inline void allVector(const char *stage,const V &values)
{
  if(!directory()||!blockSelected())return;
  for(unsigned long long i=0;i<values.rows();i++)for(unsigned long long j=0;j<values.columns();j++)scalar(stage,element(values,i,j,0),i,j);
}
template<class V> inline const V &operand(const char *stage,const V &values)
{allVector(stage,values);return values;}
template<class V> inline void array(const char *stage,const V &values)
{
  if(!directory()||!blockSelected())return;
  for(unsigned long long i=0;i<values.size();i++)scalar(stage,values.at(i),context().row,i);
}
inline void selected(const char *stage,double value)
{if(rowSelected(context().row))scalar(stage,value,context().row);}
inline void selectedExtended(const char *stage,long double value)
{if(rowSelected(context().row))extended(stage,value,context().row);}
template<class F> inline void nativeShadow(const char *stage,const F &function)
{if(directory()&&blockSelected()){PreserveEnvironment preserve;scalar(stage,function(),context().row);}}
}
#endif
