// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_NUISANCE_PERFORMANCE_H
#define ORBIT_POC_NUISANCE_PERFORMANCE_H
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <exception>
#include <fstream>
#include <iomanip>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <utility>

// Engineering instrumentation only. Neither timing nor this switch enters an
// objective, convergence, rank, acceptance, covariance or numerical-floor test.
namespace orbitPocNuisancePerformance
{
using Clock=std::chrono::steady_clock;
inline double elapsed(Clock::time_point start)
{return std::chrono::duration<double>(Clock::now()-start).count();}
inline bool enabled()
{
  const char *raw=std::getenv("ORBIT_POC_NUISANCE_PERFORMANCE");
  const std::string value=raw?raw:"0";
  if(value=="0")return false;
  if(value=="1")return true;
  throw std::invalid_argument("ORBIT_POC_NUISANCE_PERFORMANCE must be 0 or 1");
}
inline bool cacheEnabled()
{
  const char *raw=std::getenv("ORBIT_POC_NUISANCE_INTERPOLATION_CACHE");
  const std::string value=raw?raw:"0";
  if(value=="0")return false;
  if(value=="1")return true;
  throw std::invalid_argument("ORBIT_POC_NUISANCE_INTERPOLATION_CACHE must be 0 or 1");
}
struct BuildContext
{
  bool active=false,cache=false;
  std::uint64_t generation=0;
};
inline BuildContext &context(){static BuildContext value;return value;}
struct Metrics
{
  std::uint64_t observationDesignCalls=0;
  std::uint64_t interpolationCalls=0,interpolationCacheHits=0,interpolationEvaluations=0;
  double buildWallSeconds=0,observationDesignWallSeconds=0;
  double interpolationWallSeconds=0;
  bool available=false,completed=false,costOnly=false,interpolationCache=false;
};
static_assert(std::is_trivially_copyable<Metrics>::value,"trial metrics must cross the existing fixed-size pipe");
inline Metrics &metrics(){static Metrics value;return value;}

class BuildMeasure
{
  bool active,qr;
  int exceptions;
  Clock::time_point start;
public:
  BuildMeasure(bool qrEnabled,bool costOnly):active(qrEnabled&&enabled()),qr(qrEnabled),exceptions(std::uncaught_exceptions()),start(active?Clock::now():Clock::time_point{})
  {
    if(qr)
    {
      // Cache lifetime is independent of diagnostic output. A fresh generation
      // also invalidates every fork-inherited entry before the child's build.
      const bool cache=cacheEnabled();
      if(context().active)throw std::logic_error("Nested native row builds are unsupported");
      if(context().generation==std::numeric_limits<std::uint64_t>::max())
        throw std::overflow_error("Native row build generation exhausted");
      context().generation++;context().active=true;context().cache=cache;
    }
    metrics()=Metrics{};
    if(active)
    {
      metrics().available=true;metrics().costOnly=costOnly;
      metrics().interpolationCache=context().cache;
    }
  }
  ~BuildMeasure()
  {
    if(qr)context().active=false;
    if(active)
    {
      metrics().buildWallSeconds=elapsed(start);
      metrics().completed=std::uncaught_exceptions()==exceptions;
    }
  }
};

struct InterpolationKey
{
  const void *owner=nullptr,*polynomial=nullptr,*design=nullptr;
  std::uint64_t receiver=0,epoch=0,arc=0,day=0;
  double fraction=0;
  long double remainder=0;
  std::string arithmeticMode;
  bool finite()const{return std::isfinite(fraction)&&std::isfinite(remainder);}
  bool operator==(const InterpolationKey &other)const
  {
    // Time::operator== has a tolerance; long-double object bytes have padding.
    // Compare represented numbers exactly and retain the sign of zero instead.
    return finite()&&other.finite()&&owner==other.owner&&polynomial==other.polynomial&&design==other.design&&
      receiver==other.receiver&&epoch==other.epoch&&arc==other.arc&&day==other.day&&
      fraction==other.fraction&&std::signbit(fraction)==std::signbit(other.fraction)&&
      remainder==other.remainder&&std::signbit(remainder)==std::signbit(other.remainder)&&
      arithmeticMode==other.arithmeticMode;
  }
};

template<class Compute> inline auto interpolate(const void *owner,const void *polynomial,const void *design,
  std::uint64_t receiver,std::uint64_t epoch,std::uint64_t arc,std::uint64_t day,
  double fraction,long double remainder,Compute &&compute)->decltype(compute())
{
  using Result=decltype(compute());
  struct Entry {std::uint64_t generation=0;InterpolationKey key;Result value;};
  // One entry of the native 3-by-parameter-count matrix. No trajectory-wide
  // Jacobian cache, cross-build reuse, interpolation approximation or rounding.
  static std::optional<Entry> entry;
  const bool measured=context().active&&metrics().available;
  if(measured)metrics().interpolationCalls++;
  const char *rawMode=std::getenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
  const InterpolationKey key{owner,polynomial,design,receiver,epoch,arc,day,fraction,remainder,rawMode?rawMode:""};
  if(context().active&&context().cache&&entry&&entry->generation==context().generation&&entry->key==key)
  {if(measured)metrics().interpolationCacheHits++;return entry->value;}
  const auto start=measured?Clock::now():Clock::time_point{};
  if(measured)metrics().interpolationEvaluations++;
  Result result;
  try{result=compute();}
  catch(...){if(measured)metrics().interpolationWallSeconds+=elapsed(start);throw;}
  if(measured)metrics().interpolationWallSeconds+=elapsed(start);
  // A failed computation is never stored. Nonfinite queries always execute the
  // original implementation, retaining its normal bounds/shape/error handling.
  if(context().active&&context().cache&&key.finite())entry=Entry{context().generation,key,result};
  return result;
}

class ObservationDesignMeasure
{
  bool active;
  Clock::time_point start;
public:
  explicit ObservationDesignMeasure(bool qrEnabled):
    active(qrEnabled&&metrics().available),start(active?Clock::now():Clock::time_point{})
  {if(active)metrics().observationDesignCalls++;}
  ~ObservationDesignMeasure()
  {if(active)metrics().observationDesignWallSeconds+=elapsed(start);}
};

inline void writeMetrics(std::ostream &out,const Metrics &m)
{
  out<<"{\"available\":"<<(m.available?"true":"false")
     <<",\"completed\":"<<(m.completed?"true":"false")
     <<",\"cost_only\":"<<(m.costOnly?"true":"false")
     <<",\"build_wall_seconds\":"<<m.buildWallSeconds
     <<",\"observation_design_wall_seconds\":"<<m.observationDesignWallSeconds
     <<",\"observation_design_calls\":"<<m.observationDesignCalls
     <<",\"interpolation_cache\":"<<(m.interpolationCache?"true":"false")
     <<",\"interpolation_calls\":"<<m.interpolationCalls
     <<",\"interpolation_cache_hits\":"<<m.interpolationCacheHits
     <<",\"interpolation_evaluations\":"<<m.interpolationEvaluations
     <<",\"interpolation_wall_seconds\":"<<m.interpolationWallSeconds<<'}';
}

template<class Trial> inline void writeTrial(std::ostream &out,const Trial &trial)
{
  out<<"{\"status\":"<<trial.status<<",\"wall_seconds\":"<<trial.wallSeconds
     <<",\"child_user_seconds\":"<<trial.userSeconds
     <<",\"child_system_seconds\":"<<trial.systemSeconds
     <<",\"peak_child_rss_bytes\":"<<static_cast<std::uint64_t>(trial.peakRssKiB)*1024
     <<",\"row_build\":";
  writeMetrics(out,trial.performance);out<<'}';
}

template<class Search> inline void writeSearch(const std::string &path,const Search &search,const Metrics &parent)
{
  if(!parent.available)return;
  std::ofstream out(path);out<<std::setprecision(17);
  out<<"{\"schema\":\"orbit-poc-nuisance-performance-v1\","
       "\"scope\":\"diagnostic_only_no_acceptance_or_statistical_changes\","
       "\"coverage\":\"search_iterations_only_final_linearization_not_emitted\","
       "\"unmeasured_parent_stages\":[\"nuisance_solves\",\"local_recovery\",\"parameter_update\"],"
       "\"timing_scope\":\"monotonic_wall_nested_design_time_included_in_row_build\","
       "\"memory_scope\":\"child_wait4_peak_rss_not_simultaneous_process_tree_peak\","
       "\"parent_row_build\":";
  writeMetrics(out,parent);
  out<<",\"zero_update_replay\":";writeTrial(out,search.zeroUpdateReplay);
  auto array=[&](const char *name,const auto &trials)
  {
    out<<",\""<<name<<"\":[";
    for(std::size_t i=0;i<trials.size();i++){if(i)out<<',';writeTrial(out,trials[i]);}
    out<<']';
  };
  array("ordinary_trials",search.trials);array("arithmetic_audits",search.arithmeticAudits);
  // The last probe vector aliases the final history entry. Serialize history
  // only, so no child is double-counted when estimating complete profiling cost.
  out<<",\"probe_rounds\":[";
  for(std::size_t i=0;i<search.probeHistory.size();i++)
  {
    if(i)out<<',';out<<'[';
    const auto &trials=search.probeHistory[i].probes;
    for(std::size_t j=0;j<trials.size();j++){if(j)out<<',';writeTrial(out,trials[j]);}
    out<<']';
  }
  out<<"]}\n";out.close();
  if(!out)throw std::runtime_error("Cannot record nuisance performance diagnostics");
}
}
#endif
