// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_NUMERICS_PROCESSING_STEP_H
#define ORBIT_POC_NUMERICS_PROCESSING_STEP_H
#include <cstdlib>
#include <fstream>
#include <iomanip>
#include "gnss/gnssProcessingStep/gnssProcessingStep.h"
#include "misc/orbitPoc/scaledRowQr.h"
#include "misc/orbitPoc/nuisanceLineSearch.h"

#ifdef DOCSTRING_GnssProcessingStep
static const char *docstringGnssProcessingStepOrbitPocNumerics=R"(Profile float GNSS nuisance parameters at a fixed physical orbit, then export the undamped original-row QR linearization. Observations and weights remain fixed.)";
#endif

class GnssProcessingStepOrbitPocNumerics : public GnssProcessingStepBase
{
  FileName prefix, pulseReference;
  UInt maximumIterations;
  Double threshold;
public:
  explicit GnssProcessingStepOrbitPocNumerics(Config &config)
  {
    readConfig(config,"outputfilePrefix",prefix,Config::MUSTSET,"","QR diagnostics and factors");
    readConfig(config,"inputfilePulseReference",pulseReference,Config::OPTIONAL,"","full native pulse reference vector");
    readConfig(config,"maximumNuisanceIterations",maximumIterations,Config::DEFAULT,"128","fixed-orbit nuisance profiling limit");
    readConfig(config,"nuisanceConvergenceThreshold",threshold,Config::DEFAULT,"1e-8","native update influence in metres; above measured nanometre representation floor");
    if(!isCreateSchema(config) && (!maximumIterations || !(threshold>0) || !std::isfinite(threshold)))
      throw(Exception("positive nuisance iteration limit and threshold required"));
  }
  void process(GnssProcessingStep::State &state) override
  {
    if(Parallel::size(state.normalEquationInfo.comm)!=1)
      throw(Exception("v3.1 numerical profiling is serial only"));
    setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
    setenv("ORBIT_POC_NUMERICS_SOLVER","scaled_qr_v1",1);
    setenv("ORBIT_POC_NUMERICS_LAMBDA","0",1);
    if(!pulseReference.empty()) setenv("ORBIT_POC_NUMERICS_PULSE_REFERENCE",pulseReference.str().c_str(),1);
    else unsetenv("ORBIT_POC_NUMERICS_PULSE_REFERENCE");
    setenv("ORBIT_POC_NUMERICS_MODE","profile_step",1);
    unsetenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
    unsetenv("ORBIT_POC_NUMERICS_NUISANCE_FLOOR_LIMITED");
    orbitPocQr::lastNuisanceSearch()=orbitPocQr::NuisanceSearch();
    std::ostringstream preciseThreshold;preciseThreshold<<std::setprecision(17)<<threshold;
    setenv("ORBIT_POC_NUMERICS_NUISANCE_THRESHOLD",preciseThreshold.str().c_str(),1);
    // Initial receiver positions can still reflect pre-processing clocks. A
    // zero coordinate increment synchronizes all caches before the first cost
    // or Jacobian is observed; it adds no measurement or statistical prior.
    state.gnss->aprioriParameter(state.normalEquationInfo);
    const Double initialCacheRefresh=state.gnss->updateParameter(state.normalEquationInfo,Vector(state.normalEquationInfo.parameterCount()),Matrix());
    Bool converged=FALSE,floorLimited=FALSE;
    const Bool conditionalNuisance=orbitPocQr::conditionalNuisanceEnabled();
    Double freshFullChange=0.;
    Double change=0.;
    UInt count=0, streak=0;
    std::vector<Double> changes, gradients, reductions;
    for(;count<maximumIterations;count++)
    {
      change=state.estimateSolution(nullptr, {}, {}, FALSE, FALSE, FALSE, 2.5, 1.5);
      if(!std::isfinite(change)) throw(Exception("nonfinite nuisance update"));
      changes.push_back(change);
      gradients.push_back(orbitPocRowQr().lastNuisanceGradient());
      reductions.push_back(orbitPocRowQr().lastNuisanceReduction());
      if(!std::isfinite(gradients.back()) || !std::isfinite(reductions.back()))
        throw(Exception("nonfinite nuisance stationarity diagnostic"));
      if(orbitPocQr::lastNuisanceSearch().floorLimited){floorLimited=TRUE;count++;break;}
      streak=(change<threshold)?streak+1:0;
      if(streak>=2) {converged=TRUE;count++;break;}
    }
    // Inspect a fresh undamped factor at the profiled state; it does not apply
    // another nuisance or physical correction and is the exported objective.
    if(converged||floorLimited)
    {
      setenv("ORBIT_POC_NUMERICS_MODE",(conditionalNuisance&&converged)?"linearize_confirm":"linearize",1);
      freshFullChange=state.estimateSolution(nullptr, {}, {}, FALSE, FALSE, FALSE, 2.5, 1.5);
      if(conditionalNuisance&&converged&&(!std::isfinite(freshFullChange)||freshFullChange<0||!(freshFullChange<threshold)))
        throw(Exception("Fresh full nuisance correction did not confirm strict conditional convergence"));
    }
    const auto &floorAudit=orbitPocQr::lastNuisanceSearch();
    if(floorLimited)
    {
      const Double potential=orbitPocRowQr().lastNuisanceReduction();
      if(!(potential>0&&potential<=floorAudit.objectiveResolution))
        throw(Exception("Fresh nuisance factor did not confirm empirical resolution status"));
      setenv("ORBIT_POC_NUMERICS_NUISANCE_FLOOR_LIMITED","1",1);
    }
    std::ofstream record(prefix.str()+".profile.json");
    record<<std::setprecision(17)<<"{\"schema_version\":1,\"nuisance_converged\":"<<(converged?"true":"false")
          <<",\"nuisance_floor_limited\":"<<(floorLimited?"true":"false")
          <<",\"nuisance_objective_resolution\":"<<(floorLimited?floorAudit.objectiveResolution:0.)
          <<",\"nuisance_floor_policy\":\"empirical_equivalent_arithmetic_and_symmetric_probes_v1\""
          <<",\"nuisance_floor_audit\":";orbitPocQr::writeNuisanceFloorAudit(record,floorAudit);
    if(conditionalNuisance)
    {
      record<<",\"conditional_nuisance_qr\":true,\"fresh_full_nuisance_confirmed\":"<<(converged?"true":"false")
            <<",\"fresh_full_nuisance_update_m\":";
      if(converged)record<<freshFullChange;else record<<"null";
    }
    record<<",\"iterations\":"<<count<<",\"maximum_update_m\":"<<change
          <<",\"threshold_m\":"<<threshold<<",\"required_consecutive_small_updates\":2"
          <<",\"nuisance_gradient_scaled\":"<<orbitPocRowQr().lastNuisanceGradient()
          <<",\"nuisance_predicted_reduction\":"<<orbitPocRowQr().lastNuisanceReduction()
          <<",\"initial_zero_update_cache_refresh_m\":"<<initialCacheRefresh
          <<",\"fixed_weights\":true,\"dynamic_updates\":false,\"history\":[";
    for(UInt i=0;i<changes.size();i++)
    {
      if(i)record<<',';
      record<<"{\"maximum_update_m\":"<<changes[i]<<",\"gradient_scaled\":"<<gradients[i]
            <<",\"predicted_reduction\":"<<reductions[i]<<'}';
    }
    record<<"]}\n";
    if(!record) throw(Exception("cannot write nuisance profiling receipt"));
    if(!converged&&!floorLimited) throw(Exception("nuisance profiling exhausted its iteration limit"));
  }
};
#endif
