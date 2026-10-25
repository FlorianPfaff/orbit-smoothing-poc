// ORBIT_POC_NUISANCE_PERFORMANCE_V1
#include "misc/orbitPoc/nuisancePerformance.h"
// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_NUISANCE_LINE_SEARCH_H
#define ORBIT_POC_NUISANCE_LINE_SEARCH_H
#ifndef __linux__
#error "v3.1 transactional nuisance trials require Linux"
#endif
#include <array>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <functional>
#include <iomanip>
#include <iostream>
#include <limits>
#include <vector>
#include <cerrno>
#include <csignal>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <poll.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
#include "base/import.h"

namespace orbitPocQr
{
struct NuisanceTrial
{
  Double cost=0,change=0,alpha=0,reduction=0;
  std::array<Double,7> largestRawResidual{};
  Double receiverPositionChange=0,receiverTimeChange=0;
  std::uint64_t changedReceiverTimes=0;
  std::uint64_t support=0,rows=0,observationSignature=0,ambiguityBoundaryCrossings=0;
  long peakRssKiB=0;
  Double userSeconds=0,systemSeconds=0,wallSeconds=0;
  orbitPocNuisancePerformance::Metrics performance;
  int status=0;
  char error[512]{};
};
inline void isolateTrialDescriptors(int resultDescriptor)
{
  // Writable inherited descriptions must never share parent-file offsets.
  // Independent read-only descriptions preserve any lazy input-file position.
  DIR *directory=opendir("/proc/self/fd");if(!directory)throw(Exception("Cannot inspect trial file descriptors"));
  const int listing=dirfd(directory),null=open("/dev/null",O_RDWR|O_CLOEXEC);
  if(null<0){closedir(directory);throw(Exception("Cannot isolate nuisance trial output"));}
  std::vector<int> descriptors;
  while(auto entry=readdir(directory))
  {char *end=nullptr;const long value=std::strtol(entry->d_name,&end,10);if(end!=entry->d_name&&!*end&&value>=0&&value!=resultDescriptor&&value!=listing&&value!=null)descriptors.push_back(value);}
  for(int descriptor:descriptors)
  {
    const int flags=fcntl(descriptor,F_GETFL);struct stat info{};
    if(flags>=0&&(flags&O_ACCMODE)==O_RDONLY&&fstat(descriptor,&info)==0&&S_ISREG(info.st_mode))
    {
      const off_t position=lseek(descriptor,0,SEEK_CUR);
      const auto path="/proc/self/fd/"+std::to_string(descriptor);
      const int independent=open(path.c_str(),O_RDONLY|O_CLOEXEC);
      if(independent<0||(position>=0&&lseek(independent,position,SEEK_SET)<0)||dup2(independent,descriptor)<0)
      {if(independent>=0)close(independent);close(null);closedir(directory);throw(Exception("Cannot isolate nuisance trial input"));}
      close(independent);
    }
    else if(dup2(null,descriptor)<0){close(null);closedir(directory);throw(Exception("Cannot isolate nuisance trial descriptor"));}
  }
  close(null);closedir(directory);
}
inline void requireSerialTrialRuntime()
{
  DIR *tasks=opendir("/proc/self/task");if(!tasks)throw(Exception("Cannot verify serial nuisance trial runtime"));
  UInt count=0;while(auto entry=readdir(tasks))if(entry->d_name[0]!='.')count++;closedir(tasks);
  if(count!=1)throw(Exception("Transactional nuisance profiling requires a single-thread process"));
  for(const char *name:{"OPENBLAS_NUM_THREADS","OMP_NUM_THREADS"})
  {const char *value=std::getenv(name);if(!value||std::string(value)!="1")throw(Exception("Transactional nuisance profiling requires explicit OPENBLAS_NUM_THREADS=1 and OMP_NUM_THREADS=1"));}
}
inline NuisanceTrial isolatedNuisanceTrial(Double alpha,const std::function<NuisanceTrial(Double)> &evaluate)
{
  const auto performanceStart=orbitPocNuisancePerformance::Clock::now();
  requireSerialTrialRuntime();int pipeDescriptors[2];if(pipe2(pipeDescriptors,O_CLOEXEC)!=0)throw(Exception("Cannot create nuisance trial pipe"));
  std::cout.flush();std::cerr.flush();const pid_t parent=getpid(),child=fork();
  if(child<0){close(pipeDescriptors[0]);close(pipeDescriptors[1]);throw(Exception("Cannot fork nuisance trial"));}
  if(child==0)
  {
    close(pipeDescriptors[0]);prctl(PR_SET_PDEATHSIG,SIGKILL);
    if(getppid()!=parent)_exit(125);
    orbitPocNuisancePerformance::metrics()=orbitPocNuisancePerformance::Metrics{};
    NuisanceTrial result;result.alpha=alpha;
    try{isolateTrialDescriptors(pipeDescriptors[1]);result=evaluate(alpha);result.alpha=alpha;}
    catch(const std::exception &error){result.status=1;std::strncpy(result.error,error.what(),sizeof(result.error)-1);}
    catch(...){result.status=1;std::strncpy(result.error,"Unknown native nuisance trial error",sizeof(result.error)-1);}
    if(result.status)result.performance=orbitPocNuisancePerformance::metrics();
    const char *data=reinterpret_cast<const char*>(&result);std::size_t remaining=sizeof(result);
    while(remaining){const ssize_t count=write(pipeDescriptors[1],data,remaining);if(count<0&&errno==EINTR)continue;if(count<=0)_exit(126);data+=count;remaining-=count;}
    close(pipeDescriptors[1]);_exit(0);
  }
  close(pipeDescriptors[1]);NuisanceTrial result;result.alpha=alpha;
  char *data=reinterpret_cast<char*>(&result);std::size_t received=0;int status=0;struct rusage usage{};
  const auto deadline=std::chrono::steady_clock::now()+std::chrono::seconds(300);Bool timedOut=FALSE;
  while(received<sizeof(result))
  {
    if(std::chrono::steady_clock::now()>=deadline){timedOut=TRUE;kill(child,SIGKILL);break;}
    struct pollfd ready{pipeDescriptors[0],POLLIN,0};const int count=poll(&ready,1,100);
    if(count<0&&errno==EINTR)continue;
    if(count<0)break;
    if(count>0&&(ready.revents&(POLLIN|POLLHUP)))
    {const ssize_t bytes=read(pipeDescriptors[0],data+received,sizeof(result)-received);if(bytes<0&&errno==EINTR)continue;if(bytes<=0)break;received+=bytes;}
  }
  close(pipeDescriptors[0]);if(received<sizeof(result)&&!timedOut)kill(child,SIGKILL);
  while(wait4(child,&status,0,&usage)<0&&errno==EINTR){}
  result.peakRssKiB=usage.ru_maxrss;result.userSeconds=usage.ru_utime.tv_sec+1e-6*usage.ru_utime.tv_usec;
  result.systemSeconds=usage.ru_stime.tv_sec+1e-6*usage.ru_stime.tv_usec;
  if(timedOut||received!=sizeof(result)||!WIFEXITED(status)||WEXITSTATUS(status)!=0)
  {result.status=1;std::strncpy(result.error,timedOut?"Nuisance trial exceeded 300-second limit":"Nuisance trial exited without a complete result",sizeof(result.error)-1);}
  result.wallSeconds=orbitPocNuisancePerformance::elapsed(performanceStart);
  return result;
}
struct NuisanceProbeRound
{
  Double amplitude=0,slope=0,halfSlope=0,curvature=0,halfCurvature=0,potential=0,halfPotential=0,potentialAllowance=0,halfPotentialAllowance=0;
  std::vector<NuisanceTrial> probes;
  std::string rejection;
  Bool success=FALSE;
};
struct NuisanceSearch
{
  std::vector<NuisanceTrial> trials, arithmeticAudits, probes;
  std::vector<NuisanceProbeRound> probeHistory;
  NuisanceTrial zeroUpdateReplay;
  Double alpha=0,undampedChange=std::numeric_limits<Double>::quiet_NaN();
  Double objectiveResolution=0,probeAmplitude=0,probeSlope=0,probeHalfSlope=0,probeCurvature=0,probeHalfCurvature=0,probePotential=0,probeHalfPotential=0,probePotentialAllowance=0,probeHalfPotentialAllowance=0;
  Bool accepted=FALSE,stationary=FALSE,floorLimited=FALSE;
  std::string floorRejection;
};
inline NuisanceSearch &lastNuisanceSearch(){static NuisanceSearch value;return value;}
inline Bool nuisanceFailFastReplay()
{
  const char *raw=std::getenv("ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY");
  const std::string value=raw?raw:"0";
  if(value=="0")return FALSE;
  if(value=="1")return TRUE;
  throw(Exception("ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY must be 0 or 1"));
}
inline Bool validNuisanceTrial(const NuisanceTrial &trial,std::uint64_t support,std::uint64_t rows)
{return !trial.status&&std::isfinite(trial.cost)&&std::isfinite(trial.change)&&std::isfinite(trial.reduction)&&trial.change>=0&&trial.support==support&&trial.rows==rows;}
inline void auditNuisanceFloor(NuisanceSearch &result,Double prediction,std::uint64_t support,std::uint64_t rows,
                              const std::function<NuisanceTrial(Double)> &evaluate,
                              const std::function<NuisanceTrial(UInt)> &arithmeticAudit)
{
  auto reject=[&](const char *reason){result.floorRejection=reason;};
  if(!arithmeticAudit){reject("arithmetic_audit_unavailable");return;}
  if(!validNuisanceTrial(result.zeroUpdateReplay,support,rows)||result.zeroUpdateReplay.reduction!=0||result.zeroUpdateReplay.change!=0)
  {reject("zero_update_replay_failed");return;}
  for(const auto &trial:result.trials)if(!validNuisanceTrial(trial,support,rows))
  {reject("ordinary_trial_failed");return;}
  // These are alternate evaluations of exactly the same polynomial and range
  // equation at fixed coordinates. They estimate numerical resolution, not an
  // error enclosure, and are separate from the directional model checks below.
  for(UInt mode=1;mode<=3;mode++)
  {
    const auto trial=isolatedNuisanceTrial(0.,[&](Double){return arithmeticAudit(mode);});
    result.arithmeticAudits.push_back(trial);
    if(!validNuisanceTrial(trial,support,rows)||trial.observationSignature!=result.zeroUpdateReplay.observationSignature)
    {reject("fixed_parameter_arithmetic_audit_failed");return;}
    result.objectiveResolution=std::max(result.objectiveResolution,std::fabs(trial.reduction));
  }
  if(!(result.objectiveResolution>0)||!(prediction>0)||prediction>result.objectiveResolution)
  {reject("potential_not_within_positive_measured_resolution");return;}
  // Make curvature resolvable at both amplitudes, without unbounded excursions.
  // With local quadratic curvature 2*prediction the smaller probe has 2048
  // resolution units. A bound is a failed audit, never an implicit acceptance.
  result.probeAmplitude=std::max(64.,std::sqrt(4096.*result.objectiveResolution/prediction));
  if(!std::isfinite(result.probeAmplitude)||result.probeAmplitude>1e9)
  {reject("required_probe_amplitude_exceeds_numeric_limit");return;}
  if(!std::isfinite(result.undampedChange)||result.undampedChange<0||result.probeAmplitude*result.undampedChange>1.)
  {reject("required_probe_influence_exceeds_limit");return;}
  auto probe=[&]()
  {
    result.probes.clear();result.floorRejection.clear();
    result.probeSlope=result.probeHalfSlope=result.probeCurvature=result.probeHalfCurvature=0;
    result.probePotential=result.probeHalfPotential=result.probePotentialAllowance=result.probeHalfPotentialAllowance=0;
  for(Double alpha:{result.probeAmplitude,-result.probeAmplitude,.5*result.probeAmplitude,-.5*result.probeAmplitude})
  {
    const auto trial=isolatedNuisanceTrial(alpha,evaluate);result.probes.push_back(trial);
    if(!validNuisanceTrial(trial,support,rows)||trial.observationSignature!=result.zeroUpdateReplay.observationSignature)
    {reject("symmetric_probe_failed");return;}
    if(trial.change>1.){reject("actual_probe_influence_exceeds_limit");return;}
  }
  const Double a=result.probeAmplitude,e=result.objectiveResolution;
  result.probeCurvature=-(result.probes[0].reduction+result.probes[1].reduction);
  result.probeHalfCurvature=-(result.probes[2].reduction+result.probes[3].reduction);
  result.probeSlope=(result.probes[1].reduction-result.probes[0].reduction)/(2*a);
  result.probeHalfSlope=(result.probes[3].reduction-result.probes[2].reduction)/a;
  if(!std::isfinite(result.probeCurvature)||!std::isfinite(result.probeHalfCurvature)||
     !std::isfinite(result.probeSlope)||!std::isfinite(result.probeHalfSlope))
  {reject("nonfinite_symmetric_probe_diagnostics");return;}
  // The allowances below are explicitly empirical multiples of the measured
  // arithmetic spread: 2e per paired sum, propagated through differences.
  if(!(result.probeCurvature>16*e&&result.probeHalfCurvature>16*e))
  {reject("negative_or_unresolved_symmetric_curvature");return;}
  if(std::fabs(result.probeCurvature-4*result.probeHalfCurvature)>12*e)
  {reject("amplitude_dependent_symmetric_curvature");return;}
  if(std::fabs(result.probeSlope-result.probeHalfSlope)>8*e/a)
  {reject("amplitude_dependent_symmetric_slope");return;}
  if(std::fabs(result.probeSlope+2*prediction)>4*e/a||std::fabs(result.probeHalfSlope+2*prediction)>8*e/a)
  {reject("symmetric_slope_disagrees_with_undamped_gradient");return;}
  result.probePotential=result.probeSlope*result.probeSlope*a*a/(2*result.probeCurvature);
  result.probeHalfPotential=result.probeHalfSlope*result.probeHalfSlope*a*a/(8*result.probeHalfCurvature);
  if(!std::isfinite(result.probePotential)||!std::isfinite(result.probeHalfPotential)||
     !(result.probePotential>0&&result.probeHalfPotential>0)||result.probePotential>e||result.probeHalfPotential>e)
  {reject("empirical_quadratic_potential_exceeds_resolution");return;}
  // Propagate the same empirical slope/curvature allowances; this remains a
  // conservative empirical diagnostic, not a mathematically guaranteed bound.
  result.probePotentialAllowance=std::pow(std::fabs(result.probeSlope)+4*e/a,2)*a*a/(2*(result.probeCurvature-2*e));
  result.probeHalfPotentialAllowance=std::pow(std::fabs(result.probeHalfSlope)+8*e/a,2)*a*a/(8*(result.probeHalfCurvature-2*e));
  if(!std::isfinite(result.probePotentialAllowance)||!std::isfinite(result.probeHalfPotentialAllowance)||
     result.probePotentialAllowance>e||result.probeHalfPotentialAllowance>e)
  {reject("empirical_quadratic_potential_with_allowance_exceeds_resolution");return;}
  result.floorLimited=TRUE;
  };
  // Refine only arithmetic resolution of an already valid local quadratic.
  // Every other failure is terminal. No fitted coordinate is changed here.
  for(UInt refinement=0;refinement<5;refinement++)
  {
    probe();
    result.probeHistory.push_back({result.probeAmplitude,result.probeSlope,result.probeHalfSlope,result.probeCurvature,result.probeHalfCurvature,
      result.probePotential,result.probeHalfPotential,result.probePotentialAllowance,result.probeHalfPotentialAllowance,
      result.probes,result.floorRejection,result.floorLimited});
    if(result.floorLimited||result.floorRejection!="empirical_quadratic_potential_with_allowance_exceeds_resolution")return;
    if(refinement==4||2*result.probeAmplitude>1e9||2*result.probeAmplitude*result.undampedChange>1.)return;
    result.probeAmplitude*=2;
  }


};
inline NuisanceSearch searchNuisance(Double current,Double predicted,Double threshold,std::uint64_t support,std::uint64_t rows,
                                   const std::function<NuisanceTrial(Double)> &evaluate,
                                   const std::function<NuisanceTrial(UInt)> &arithmeticAudit={})
{
  if(!std::isfinite(current)||!std::isfinite(predicted)||threshold<=0)throw(Exception("Invalid nuisance line-search inputs"));
  const Bool failFast=nuisanceFailFastReplay(); // validate before any fork
  NuisanceSearch result;
  result.zeroUpdateReplay=isolatedNuisanceTrial(0.,evaluate);
  // A failed identity replay already makes this point inadmissible. Do not
  // spend up to seventeen further child deadlines on proposals that the
  // caller must reject. Retain the failure for the unchanged acceptance guard.
  if(failFast&&(!validNuisanceTrial(result.zeroUpdateReplay,support,rows)||
     result.zeroUpdateReplay.reduction!=0||result.zeroUpdateReplay.change!=0))
  {result.floorRejection="zero_update_replay_failed";return result;}
  for(UInt attempt=0;attempt<17;attempt++)
  {
    const Double alpha=std::ldexp(1.,-static_cast<int>(attempt));
    NuisanceTrial trial=isolatedNuisanceTrial(alpha,evaluate);
    if(!trial.status&&(!std::isfinite(trial.cost)||!std::isfinite(trial.change)||!std::isfinite(trial.reduction)||trial.change<0||trial.support!=support||trial.rows!=rows))
    {trial.status=1;std::strncpy(trial.error,"Nuisance trial changed support or returned nonfinite diagnostics",sizeof(trial.error)-1);}
    result.trials.push_back(trial);
    if(trial.status)continue;
    if(!std::isfinite(result.undampedChange))result.undampedChange=trial.change/alpha;
    // The fresh full undamped correction, never alpha times that correction,
    // is the stationarity check. No state update is needed if already small.
    if(result.undampedChange<threshold){result.stationary=TRUE;return result;}
    const Double prediction=(2*alpha-alpha*alpha)*predicted;
    if(trial.reduction>0&&prediction>0&&trial.reduction/prediction>1e-4)
    {result.accepted=TRUE;result.alpha=alpha;return result;}
  }
  auditNuisanceFloor(result,predicted,support,rows,evaluate,arithmeticAudit);
  return result;
}
inline std::string nuisanceJsonNumber(Double value)
{if(!std::isfinite(value))return "null";std::ostringstream out;out<<std::setprecision(17)<<value;return out.str();}
inline std::string nuisanceJsonError(const NuisanceTrial &trial)
{std::string value=trial.error;for(char &c:value)if(static_cast<unsigned char>(c)<32)c=' ';return value;}
inline void writeNuisanceFloorAudit(std::ostream &out,const NuisanceSearch &result)
{
  out<<'[';
  for(UInt i=0;i<result.arithmeticAudits.size();i++)
  {
    if(i)out<<',';const auto &trial=result.arithmeticAudits[i];
    out<<"{\"kind\":\"equivalent_arithmetic\",\"mode\":"<<i+1<<",\"success\":"<<(result.floorLimited?"true":"false")<<",\"support_unchanged\":"<<((!trial.status&&trial.support==result.zeroUpdateReplay.support&&trial.rows==result.zeroUpdateReplay.rows&&trial.observationSignature==result.zeroUpdateReplay.observationSignature)?"true":"false")<<",\"actual_reduction\":"<<nuisanceJsonNumber(trial.reduction)<<",\"cost\":"<<nuisanceJsonNumber(trial.cost)<<",\"status\":"<<trial.status<<",\"error\":"<<std::quoted(nuisanceJsonError(trial))<<'}';
  }
  if(!result.probes.empty())
  {
    if(!result.arithmeticAudits.empty())out<<',';
    out<<"{\"kind\":\"two_amplitude_symmetric_nuisance_probe\",\"success\":"<<(result.floorLimited?"true":"false")<<",\"support_unchanged\":"<<(result.probes.size()==4&&std::all_of(result.probes.begin(),result.probes.end(),[&](const NuisanceTrial &t){return !t.status&&t.support==result.zeroUpdateReplay.support&&t.rows==result.zeroUpdateReplay.rows&&t.observationSignature==result.zeroUpdateReplay.observationSignature;})?"true":"false")<<",\"amplitude\":"<<nuisanceJsonNumber(result.probeAmplitude)<<",\"slope\":"<<nuisanceJsonNumber(result.probeSlope)<<",\"half_slope\":"<<nuisanceJsonNumber(result.probeHalfSlope)<<",\"curvature\":"<<nuisanceJsonNumber(result.probeCurvature)<<",\"half_curvature\":"<<nuisanceJsonNumber(result.probeHalfCurvature)<<",\"empirical_quadratic_potential\":"<<nuisanceJsonNumber(result.probePotential)<<",\"half_empirical_quadratic_potential\":"<<nuisanceJsonNumber(result.probeHalfPotential)<<",\"empirical_quadratic_potential_with_allowance\":"<<nuisanceJsonNumber(result.probePotentialAllowance)<<",\"half_empirical_quadratic_potential_with_allowance\":"<<nuisanceJsonNumber(result.probeHalfPotentialAllowance)<<",\"curvature_resolution_multiple\":16,\"curvature_scaling_error_multiple\":12,\"slope_error_multiple\":4,\"amplitude_slope_error_multiple\":8,\"probes\":[";
    for(UInt i=0;i<result.probes.size();i++){if(i)out<<',';const auto &t=result.probes[i];out<<"{\"alpha\":"<<t.alpha<<",\"actual_reduction\":"<<nuisanceJsonNumber(t.reduction)<<",\"cost\":"<<nuisanceJsonNumber(t.cost)<<",\"maximum_update_m\":"<<nuisanceJsonNumber(t.change)<<",\"status\":"<<t.status<<",\"error\":"<<std::quoted(nuisanceJsonError(t))<<'}';}
    out<<"],\"probe_amplitude_policy\":\"bounded_precision_refinement_v1\",\"maximum_probe_amplitude\":1000000000,\"maximum_probe_influence_m\":1,\"maximum_probe_rounds\":5,\"probe_history\":[";
    for(UInt i=0;i<result.probeHistory.size();i++)
    {
      if(i)out<<',';const auto &r=result.probeHistory[i];
      out<<"{\"amplitude\":"<<nuisanceJsonNumber(r.amplitude)<<",\"success\":"<<(r.success?"true":"false")<<",\"rejection\":"<<std::quoted(r.rejection)
        <<",\"slope\":"<<nuisanceJsonNumber(r.slope)<<",\"half_slope\":"<<nuisanceJsonNumber(r.halfSlope)<<",\"curvature\":"<<nuisanceJsonNumber(r.curvature)<<",\"half_curvature\":"<<nuisanceJsonNumber(r.halfCurvature)
        <<",\"empirical_quadratic_potential\":"<<nuisanceJsonNumber(r.potential)<<",\"half_empirical_quadratic_potential\":"<<nuisanceJsonNumber(r.halfPotential)
        <<",\"empirical_quadratic_potential_with_allowance\":"<<nuisanceJsonNumber(r.potentialAllowance)<<",\"half_empirical_quadratic_potential_with_allowance\":"<<nuisanceJsonNumber(r.halfPotentialAllowance)<<",\"probes\":[";
      for(UInt j=0;j<r.probes.size();j++){if(j)out<<',';const auto &t=r.probes[j];out<<"{\"alpha\":"<<t.alpha<<",\"actual_reduction\":"<<nuisanceJsonNumber(t.reduction)<<",\"cost\":"<<nuisanceJsonNumber(t.cost)<<",\"maximum_update_m\":"<<nuisanceJsonNumber(t.change)<<",\"status\":"<<t.status<<",\"error\":"<<std::quoted(nuisanceJsonError(t))<<'}';}out<<"]}";
    }
    out<<"]}";
  }
  out<<']';
}
inline void writeNuisanceSearch(const std::string &path,const NuisanceSearch &result,Double objective,Double prediction)
{
  std::ofstream out(path);out<<std::setprecision(17)<<"{\"schema\":\"orbit-poc-native-nuisance-line-search-v1\",\"accepted\":"<<(result.accepted?"true":"false")
    <<",\"stationary_without_update\":"<<(result.stationary?"true":"false")<<",\"alpha\":"<<result.alpha<<",\"undamped_maximum_update_m\":";
  if(std::isfinite(result.undampedChange))out<<result.undampedChange;else out<<"null";
  out<<",\"requested_probe_amplitude\":"<<nuisanceJsonNumber(result.probeAmplitude)<<",\"requested_probe_influence_m\":"<<nuisanceJsonNumber(result.probeAmplitude*result.undampedChange)
    <<",\"maximum_probe_amplitude\":1000000000,\"maximum_probe_influence_m\":1,\"maximum_probe_rounds\":5,\"completed_probe_rounds\":"<<result.probeHistory.size();
  out<<",\"nuisance_floor_limited\":"<<(result.floorLimited?"true":"false")<<",\"nuisance_objective_resolution\":"<<result.objectiveResolution<<",\"floor_rejection\":"<<std::quoted(result.floorRejection)<<",\"nuisance_floor_audit\":";writeNuisanceFloorAudit(out,result);
  out<<",\"zero_update_replay\":{\"status\":"<<result.zeroUpdateReplay.status<<",\"cost\":"<<nuisanceJsonNumber(result.zeroUpdateReplay.cost)<<",\"actual_reduction\":"<<nuisanceJsonNumber(result.zeroUpdateReplay.reduction)<<",\"maximum_update_m\":"<<nuisanceJsonNumber(result.zeroUpdateReplay.change)
     <<",\"error\":"<<std::quoted(nuisanceJsonError(result.zeroUpdateReplay))<<"}";
  out<<",\"objective_before\":"<<objective<<",\"full_step_prediction\":"<<prediction<<",\"memory_scope\":\"child_wait4_peak_rss_only_not_simultaneous_process_tree_peak\",\"trials\":[";
  for(UInt i=0;i<result.trials.size();i++)
  {
    if(i)out<<',';const auto &trial=result.trials[i];std::string error=trial.error;for(char &value:error)if(static_cast<unsigned char>(value)<32)value=' ';
    out<<"{\"alpha\":"<<trial.alpha<<",\"status\":"<<trial.status<<",\"cost\":";
    if(std::isfinite(trial.cost))out<<trial.cost;else out<<"null";
    out<<",\"actual_reduction\":";if(std::isfinite(trial.reduction))out<<trial.reduction;else out<<"null";
    out<<",\"maximum_update_m\":";if(std::isfinite(trial.change))out<<trial.change;else out<<"null";
    out
      <<",\"largest_raw_residual_change\":[";for(UInt k=0;k<trial.largestRawResidual.size();k++){if(k)out<<',';out<<trial.largestRawResidual[k];}out<<']'
      <<",\"receiver_position_change_m\":"<<trial.receiverPositionChange<<",\"receiver_time_change_seconds\":"<<trial.receiverTimeChange<<",\"changed_receiver_times\":"<<trial.changedReceiverTimes
      <<",\"observation_signature\":"<<std::quoted(std::to_string(trial.observationSignature))<<",\"ambiguity_half_integer_crossings\":"<<trial.ambiguityBoundaryCrossings
      <<",\"peak_child_rss_bytes\":"<<static_cast<std::uint64_t>(trial.peakRssKiB)*1024<<",\"child_user_seconds\":"<<trial.userSeconds
      <<",\"child_system_seconds\":"<<trial.systemSeconds<<",\"error\":"<<std::quoted(error)<<'}';
  }
  out<<"]}\n";if(!out)throw(Exception("Cannot record nuisance line-search diagnostics"));
}
}
#endif
