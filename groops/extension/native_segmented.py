#!/usr/bin/env python3
"""Export the actual discrete v3.1 operators for an opt-in v4 equality lift.

This adds no trajectory segment and no force reset. The Ar/Av integral operator
and the downstream variation-of-constants force design are distinct exports.
Both are obtained from the native instances/coefficients used by the unchanged
whole-arc evaluator. All configured output paths are optional.
"""
from pathlib import Path
import argparse
import hashlib
import json
import shutil


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Segmented export anchor mismatch: " + before[:100])
    return text.replace(before, after, 1)


def apply(source):
    root = Path(source) / "source"
    here = Path(__file__).resolve().parent
    required = root / "misc/orbitPoc/stagedVariationalBody.h"
    if not required.is_file():
        raise ValueError("Segmented export requires the installed numerics extension")
    for name in ("segmentedTangent.h", "segmentedNativeExport.h"):
        path = root / "misc/orbitPoc" / name
        if not path.exists() or path.read_bytes() != (here/name).read_bytes():
            shutil.copyfile(here/name, path)

    path = root / "base/polynomial.cpp"
    text = path.read_text()
    if "ORBIT_POC_SEGMENTED_STENCIL_CAPTURE_V4" not in text:
        text = '#include "misc/orbitPoc/segmentedNativeExport.h"\n// ORBIT_POC_SEGMENTED_STENCIL_CAPTURE_V4\n' + text
        anchor = "          copy(A.row(rowsPerEpoch*idxFirstRight, rowsPerEpoch), B.row(rowsPerEpoch*i, rowsPerEpoch));"
        text = replace(text, anchor, "          if(OrbitPoc::SegmentedExport::exact(idxFirstRight))continue;\n" + anchor)
        anchor = "        const auto weights=orbitPocQr::twofoldInterpolationWeights(nodes,derivative,sampling);"
        text = replace(text, anchor, anchor + "\n        if(OrbitPoc::SegmentedExport::twofold(idx,weights))continue;")
        anchor = "      // interpolate\n      // -----------"
        text = replace(text, anchor, "      if(OrbitPoc::SegmentedExport::ordinary(idx,coeff))continue;\n\n" + anchor)
        path.write_text(text)
    path = root / "misc/orbitPoc/piecewisePolynomial.h"
    text = path.read_text()
    if "orbitPocStencil" not in text:
        text = replace(text, '#include "base/polynomial.h"', '#include "base/polynomial.h"\n#include "misc/orbitPoc/segmentedNativeExport.h"')
        text = text[:text.rindex("\n};")] + STENCIL + text[text.rindex("\n};"):]
        path.write_text(text)

    path = root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
    text = path.read_text()
    if "orbitPocSegmentedTangentExport" not in text:
        text = replace(text, "  FileName orbitPocDerivativeDiagnostics;", "  FileName orbitPocDerivativeDiagnostics,orbitPocSegmentedTangentExport;")
        anchor = '    readConfig(config,"orbitPocDerivativeDiagnostics",orbitPocDerivativeDiagnostics,Config::OPTIONAL,"","JSON record of the opt-in six-state tangent and remaining approximations");'
        text = replace(text, anchor, anchor + '\n    readConfig(config,"orbitPocSegmentedTangentExport",orbitPocSegmentedTangentExport,Config::OPTIONAL,"","v4 JSONL actual finite-stencil tangent operator; no propagation cuts");\n    if(!isCreateSchema(config) && !orbitPocSegmentedTangentExport.empty() && orbitPocDerivativeProfile=="legacy_v3")throw(Exception("segmented tangent export requires a staged derivative profile"));')
        path.write_text(text)
    path = root / "misc/orbitPoc/stagedVariationalBody.h"
    text = path.read_text()
    if "ORBIT_POC_SEGMENTED_TANGENT_EXPORT_V4" not in text:
        text = replace(text, "  return arc;", TANGENT_EXPORT + "\n  return arc;")
        path.write_text(text)

    path = root / "misc/observation/variationalEquation.h"
    text = path.read_text()
    if "orbitPocExportSegmented" not in text:
        text = replace(text, "  void setArc(VariationalEquationArc &arc);", "  void setArc(VariationalEquationArc &arc);\n  void orbitPocExportSegmented(const FileName &path);")
        text = replace(text, "  Matrix computeIntegrand(UInt idEpoch);", "  Matrix computeIntegrand(UInt idEpoch, Matrix *nativeForce=nullptr);")
        path.write_text(text)
    path = root / "misc/observation/variationalEquation.cpp"
    text = path.read_text()
    if "ORBIT_POC_SEGMENTED_VARIATION_EXPORT_V4" not in text:
        text = '#include "misc/orbitPoc/segmentedNativeExport.h"\n#include <set>\n' + text
        text = replace(text, "Matrix VariationalEquation::computeIntegrand(UInt idEpoch)", "Matrix VariationalEquation::computeIntegrand(UInt idEpoch, Matrix *nativeForce)")
        text = replace(text, "    solveInPlace(Z, F);", "    if(nativeForce)*nativeForce=F;\n    solveInPlace(Z, F);")
        text += VARIATION_EXPORT
        path.write_text(text)
    path = root / "misc/observation/variationalEquationFromFile.h"
    text = path.read_text()
    if "orbitPocExportSegmented" not in text:
        text = replace(text, "  const VariationalEquationArc &getArc(const Time &time);", "  const VariationalEquationArc &getArc(const Time &time);\n  void orbitPocExportSegmented(const FileName &path) {if(file.arcCount()!=1)throw(Exception(\"segmented design export requires one native arc\"));variationalEquation.orbitPocExportSegmented(path);}")
        path.write_text(text)
    path = root / "programs/gnss/orbitPocEvaluateVariational.cpp"
    text = path.read_text()
    if "outputfileSegmentedDesign" not in text:
        text = replace(text, "    UInt degree, interpolationDegree;", "    UInt degree, interpolationDegree;\n    FileName segmentedDesign,segmentedReferenceDesign;Bool segmentedOnly=FALSE;")
        anchor = '    readConfig(config,"inputfileVariational",input,Config::MUSTSET,"","single native variational arc");'
        text = replace(text, anchor, anchor+'\n    readConfig(config,"outputfileSegmentedDesign",segmentedDesign,Config::OPTIONAL,"","v4 sparse variation-of-constants design JSONL");\n    readConfig(config,"outputfileSegmentedReferenceDesign",segmentedReferenceDesign,Config::OPTIONAL,"","small-gate-only exact original dense design, interleaved r/v rows");\n    readConfig(config,"segmentedExportOnly",segmentedOnly,Config::DEFAULT,"0","export the local design without allocating global PosDesign/VelDesign");')
        anchor = "    auto equation=model.integrateArc(arc.times.front(),arc.times.back(),TRUE,TRUE);"
        text = replace(text, anchor, '    if(segmentedOnly && (segmentedDesign.empty()||!segmentedReferenceDesign.empty()))throw(Exception("segmentedExportOnly needs outputfileSegmentedDesign and forbids dense reference output"));\n    if(!segmentedDesign.empty())model.orbitPocExportSegmented(segmentedDesign);\n    if(segmentedOnly)return;\n    if(!segmentedReferenceDesign.empty() && (arc.times.size()>1000||model.parameterCount()>200))throw(Exception("dense segmented reference export is bounded to small gates"));\n'+anchor+r'''
    if(!segmentedReferenceDesign.empty())
    {
      if(equation.times.size()>1000||model.parameterCount()>200)throw(Exception("dense segmented reference export is bounded to small gates"));
      Matrix reference(6*equation.times.size(),model.parameterCount());
      for(UInt i=0;i<equation.times.size();i++){copy(equation.PosDesign.row(3*i,3),reference.row(6*i,3));copy(equation.VelDesign.row(3*i,3),reference.row(6*i+3,3));}
      writeFileMatrix(segmentedReferenceDesign,reference);
    }''')
        path.write_text(text)
    install_observation_hook(root)
    install_covariance_queries(root)
    files = {name: hashlib.sha256((here/name).read_bytes()).hexdigest()
             for name in ("segmentedTangent.h", "segmentedNativeExport.h", "native_segmented.py")}
    manifest = {"schema": "orbit-poc-segmented-extension-v1", "files": files,
                "nominal_propagation": "unchanged chronological whole arc",
                "design": "actual native variation-of-constants",
                "tangent_export": "actual stored Ar/Av quadrature and interpolation halos"}
    (Path(source)/"orbit-poc-segmented-extension.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


STENCIL = r'''
  // ORBIT_POC_SEGMENTED_STENCIL_CAPTURE_V4: evaluate the native selection and
  // coefficient code with zero data columns. No replica interpolation recipe.
  std::vector<OrbitPoc::SegmentedExport::Weight> orbitPocStencil(
      const Time &query,long double remainder=0.L,Bool velocity=FALSE) const
  {
    if(segments.empty())throw(Exception("empty segmented interpolation"));
    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    const Bool precise=prefix&&*prefix;
    if(!precise&&remainder!=0)throw(Exception("relative halo requires the native precise interpolation path"));
    auto difference=[](const Time&a,const Time&b){return (static_cast<long double>(a.mjdInt())-b.mjdInt())*86400.L+(static_cast<long double>(a.mjdMod())-b.mjdMod())*86400.L;};
    const UInt segment=precise ? std::upper_bound(splitTimes.begin(),splitTimes.end(),query,[&](const Time&q,const Time&b){return difference(q,b)+remainder<0;})-splitTimes.begin() : std::upper_bound(splitTimes.begin(),splitTimes.end(),query)-splitTimes.begin();
    const auto &part=segments.at(segment);const UInt count=velocity?part.jumpCount:part.count;
    const auto &polynomial=velocity?part.jump:part.smooth;
    OrbitPoc::SegmentedExport::Capture capture;
    polynomial.interpolateOffset({query},Matrix(count,0),{remainder},1);
    if(capture.values.empty())throw(Exception("native interpolation failed to export its halo"));
    for(auto &term:capture.values)term.index+=part.first;
    return capture.values;
  }
'''

TANGENT_EXPORT = r'''
  // ORBIT_POC_SEGMENTED_TANGENT_EXPORT_V4
  if(!orbitPocSegmentedTangentExport.empty())
  {
    if(orbitFile.arcCount()!=1)throw(Exception("segmented tangent export requires one arc"));
    using namespace OrbitPoc::SegmentedExport;
    std::ofstream out(orbitPocSegmentedTangentExport.str());out.precision(17);
    if(!out)throw(Exception("cannot open segmented tangent export"));
    out<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-segmented-tangent-v1\",\"profile\":";string(out,orbitPocDerivativeProfile);
    out<<",\"epochs\":"<<epochCount<<",\"dt\":"<<deltaT<<",\"initial_velocity_scale\":"<<1/T
       <<",\"maximum_tangent_relative_residual\":"<<maximumTangentResidual
       <<",\"nominal_force_history\":\"unchanged_whole_arc\",\"new_process_priors\":false,\"forcing_design\":\"separate_native_variation_of_constants_export\"}\n";
    for(UInt i=0;i<epochCount;i++)
    {out<<"{\"kind\":\"sample\",\"channel\":\"main\",\"index\":"<<i<<",\"time\":";time(out,times.at(i));out<<',';jacobian(out,mainJac[i]);out<<",\"position_halo\":[["<<i<<",1,\"0x8p-3\",\"0x0p+0\"]],\"velocity_halo\":[["<<i<<",1,\"0x8p-3\",\"0x0p+0\"]]}\n";}
    quadrature(out,"main",mainWeights);
    if(!synthetic)
    {
      for(UInt i=0;i<dragJac.size();i++)
      {
        const auto timeValue=i<epochCount?times.at(i):orbitPocAtmosphericExtraTimes.at(i-epochCount);
        out<<"{\"kind\":\"sample\",\"channel\":\"drag\",\"index\":"<<i<<",\"time\":";time(out,timeValue);out<<',';jacobian(out,dragJac[i]);
        out<<",\"position_halo\":";weights(out,stateInterpolation.orbitPocStencil(timeValue));
        out<<",\"velocity_halo\":";weights(out,stateInterpolation.orbitPocStencil(timeValue,0.L,TRUE));out<<"}\n";
      }
      quadrature(out,"drag",orbitPocAtmosphericWeights);
    }
    out<<"{\"kind\":\"complete\"}\n";if(!out)throw(Exception("segmented tangent export failed"));
  }
'''

VARIATION_EXPORT = r'''

// ORBIT_POC_SEGMENTED_VARIATION_EXPORT_V4
void VariationalEquation::orbitPocExportSegmented(const FileName &path)
{
  using namespace OrbitPoc::SegmentedExport;
  const UInt n=arc_.times.size();if(n<2||parameterCount_<6)throw(Exception("invalid segmented native arc"));
  initIntegration();
  OrbitPoc::Quadrature weights=orbitPocEventWeights;
  if(weights.empty())
  {
    weights.resize(n-1);UInt coefficient=0,start=0;
    for(UInt k=0;k+1<n;k++)
    {
      if(!orbitPocWindows.empty()){start=orbitPocWindows.at(k);coefficient=k-start;}
      const auto &w=coeffIntegral.at(coefficient);
      for(UInt j=0;j<w.rows();j++)weights[k].push_back({static_cast<unsigned>(start+j),deltaT*w(j),0.});
      if(orbitPocWindows.empty())
      {if(k+1<(integrationDegree+1)/2||k+1+(integrationDegree+1)/2>=n)coefficient++;else start++;}
    }
  }
  std::ofstream out(path.str());out.precision(17);if(!out)throw(Exception("cannot open segmented design export"));
  out<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-segmented-design-v1\",\"epochs\":"<<n<<",\"parameter_count\":"<<parameterCount_
     <<",\"initial_parameter_offset\":"<<parameterCount_-6<<",\"initial_velocity_scale\":"<<1./(arc_.times.back()-arc_.times.front()).seconds()
     <<",\"integration_degree\":"<<integrationDegree<<",\"dt\":"<<deltaT
     <<",\"state_coordinates\":\"native_variation_constants\",\"physical_map\":\"delta_r_v=Phi*c\",\"pulse_units\":\"micrometres_per_second\",\"post_pulse\":true}\n";
  std::vector<ParameterName> names;parameterName(names);
  for(UInt i=0;i<names.size();i++){out<<"{\"kind\":\"parameter\",\"index\":"<<i<<",\"name\":";string(out,names[i].str());out<<"}\n";}
  for(UInt i=0;i<n;i++)
  {
    Matrix phi(6,6);copy(arc_.PosState.row(3*i,3),phi.row(0,3));copy(arc_.VelState.row(3*i,3),phi.row(3,3));
    out<<"{\"kind\":\"epoch\",\"index\":"<<i<<",\"time\":";time(out,arc_.times[i]);out<<",\"phi\":";matrix(out,phi);out<<"}\n";
  }
  quadrature(out,"variation_constants",weights);
  std::set<UInt> samples;for(const auto &interval:weights)for(const auto &term:interval)samples.insert(term.index);
  const Bool forceParameters=gravityCount||(parameterAcceleration&&(parameterAcceleration->parameterCount()||parameterAcceleration->parameterCountArc()));
  for(UInt index:samples)
  {
    Matrix raw,integrand;if(forceParameters)integrand=computeIntegrand(index,&raw);
    const auto &data=index<n?arc_:orbitPocExtraArc;const UInt local=index<n?index:index-n;
    out<<"{\"kind\":\"forcing\",\"index\":"<<index<<",\"time\":";time(out,data.times.at(local));
    out<<",\"native_force_trf\":";sparse(out,raw);out<<",\"integrand\":";sparse(out,integrand);out<<"}\n";
  }
  for(UInt i=0;i<timePulse.size();i++)
  {
    if(stochasticPulse.at(i).size()==0)continue;
    const auto at=std::lower_bound(arc_.times.begin(),arc_.times.end(),timePulse[i]);
    if(at==arc_.times.end()||std::fabs((*at-timePulse[i]).seconds())>1e-7)throw(Exception("segmented pulse must lie on its original native grid"));
    out<<"{\"kind\":\"pulse\",\"epoch\":"<<at-arc_.times.begin()<<",\"parameter\":"<<idxPulse+3*i<<",\"map\":";matrix(out,stochasticPulse[i]);out<<"}\n";
  }
  out<<"{\"kind\":\"complete\"}\n";if(!out)throw(Exception("segmented design export failed"));
}
'''


def install_observation_hook(root):
    path = root / "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp"
    text = path.read_text()
    if "ORBIT_POC_SEGMENTED_OBSERVATION_EXPORT_V4" in text:
        return
    text = '#include "misc/orbitPoc/scaledRowQr.h"\n' + text
    text = replace(text, "const GnssNormalEquationInfo &/*normalEquationInfo*/, const GnssObservationEquation &eqn", "const GnssNormalEquationInfo &normalEquationInfo, const GnssObservationEquation &eqn")
    anchor = "      matMult(1., eqn.A.column(GnssObservationEquation::idxPosRecv, 3),"
    text = replace(text, anchor, OBSERVATION_EXPORT + "\n" + anchor)
    path.write_text(text)


OBSERVATION_EXPORT = r'''
      // ORBIT_POC_SEGMENTED_OBSERVATION_EXPORT_V4
      if(orbitPocRowQr().capturingSegmentedRows())
      {
        const char *overridePath=std::getenv("ORBIT_POC_SEGMENTED_OBSERVATIONS");
        const std::string path=overridePath?overridePath:orbitPocRowQr().artifactStem()+".segmented_observations.jsonl";
        if(path.empty())throw(Exception("empty segmented observation export path"));
        using namespace OrbitPoc::SegmentedExport;
        std::ofstream out(path,std::ios::app);out.precision(17);if(!out)throw(Exception("cannot open segmented observation export"));
        out<<"{\"kind\":\"observation\",\"factor_stem\":";string(out,orbitPocRowQr().artifactStem());
        out<<",\"row_start\":"<<orbitPocRowQr().weightedRowCount()<<",\"receiver\":"<<eqn.receiver->idRecv()<<",\"transmitter\":"<<eqn.transmitter->idTrans()
           <<",\"epoch\":"<<eqn.idEpoch<<",\"arc\":"<<arcNo<<",\"native_first\":"<<normalEquationInfo.index(para->index)
           <<",\"native_count\":"<<para->x.rows()<<",\"time\":";time(out,eqn.timeRecv);
        out<<",\"time_remainder\":\""<<std::hexfloat<<eqn.receiver->timeRemainder(eqn.idEpoch)<<std::defaultfloat<<"\",\"halo\":";
        weights(out,para->polynomial.at(arcNo).orbitPocStencil(eqn.timeRecv,eqn.receiver->timeRemainder(eqn.idEpoch)));
        out<<",\"rows\":"<<eqn.A.rows()<<",\"position_design\":";matrix(out,eqn.A.column(GnssObservationEquation::idxPosRecv,3));out<<"}\n";
        if(!out)throw(Exception("segmented observation export failed"));
      }
'''


def install_covariance_queries(root):
    path = root / "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.cpp"
    text = path.read_text()
    if "ORBIT_POC_SEGMENTED_COVARIANCE_QUERIES_V4" not in text:
        anchor = '    if(!fileNameOrbit.empty())\n    {'
        text = replace(text, anchor, COVARIANCE_QUERIES + "\n" + anchor)
        path.write_text(text)
    # A bounded actual-native test interface exercises the same row writer and
    # native interpolation at off-grid/pulse/continuous-knot query epochs.
    path = root / "programs/gnss/orbitPocEvaluateVariational.cpp"
    text = path.read_text()
    if "outputfileSegmentedCovarianceQueries" not in text:
        text = replace(text, "    FileName segmentedDesign,segmentedReferenceDesign;Bool segmentedOnly=FALSE;",
                       "    FileName segmentedDesign,segmentedReferenceDesign,segmentedQueries,segmentedQueryReference;Bool segmentedOnly=FALSE;\n    TimeSeriesPtr segmentedQuerySeries;")
        anchor = '    readConfig(config,"segmentedExportOnly",segmentedOnly,Config::DEFAULT,"0","export the local design without allocating global PosDesign/VelDesign");'
        text = replace(text, anchor, anchor + '\n    readConfig(config,"outputfileSegmentedCovarianceQueries",segmentedQueries,Config::OPTIONAL,"","Cartesian state query stencils; bounded native gate");\n    readConfig(config,"outputfileSegmentedQueryReferenceDesign",segmentedQueryReference,Config::OPTIONAL,"","small-gate-only native dense query designs");\n    readConfig(config,"segmentedQueryTimeSeries",segmentedQuerySeries,Config::OPTIONAL,"","independent small-gate query grid; does not alter orbit output");')
        text = replace(text, '    if(segmentedOnly)return;',
                       '    if(segmentedOnly && (!segmentedQueries.empty()||!segmentedQueryReference.empty()))throw(Exception("segmentedExportOnly forbids gate-only query outputs"));\n    if(segmentedOnly)return;')
        anchor = "    std::vector<Time> outputTimes=equation.times;"
        text = replace(text, anchor, QUERY_GATE + "\n" + anchor)
        path.write_text(text)


COVARIANCE_QUERIES = r'''
    // ORBIT_POC_SEGMENTED_COVARIANCE_QUERIES_V4. This is independent of all
    // dense covariance output options and does not authorize covariance.
    const char *queryOption=std::getenv("ORBIT_POC_SEGMENTED_COVARIANCE_QUERIES");
    if(queryOption && std::string(queryOption)!="0" && std::string(queryOption)!="1")
      throw(Exception("Segmented covariance query export must be 0 or 1"));
    if(queryOption && std::string(queryOption)=="1")
    {
      if(!orbitPocRowQr().enabled()||orbitPocRowQr().artifactStem().empty()||orbitPocRowQr().isCostOnly())
        throw(Exception("Segmented covariance queries require an ordinary native QR factor"));
      using namespace OrbitPoc::SegmentedExport;
      const std::string path=orbitPocRowQr().artifactStem()+".segmented_covariance_queries.jsonl";
      std::ofstream out(path);out.precision(17);if(!out)throw(Exception("cannot open segmented covariance query export"));
      out<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-segmented-covariance-queries-v1\",\"factor_stem\":";
      string(out,orbitPocRowQr().artifactStem());out<<",\"write_suffix\":";string(out,suffix);
      out<<",\"coordinates\":\"Cartesian_SI\",\"row_order\":\"position_xyz_velocity_xyz\",\"post_pulse_velocity\":true,\"covariance_produced\":false}\n";
      UInt trajectoryCount=0,observationCount=0;
      for(auto para:parameters)
        if(para&&para->index&&para->recv->isMyRank())
        {
          const UInt first=normalEquationInfo.index(para->index),count=para->x.rows();
          std::vector<Bool> covered(gnss->times.size(),FALSE);UInt trajectoryIndex=0;
          for(UInt arcNo=0;arcNo<para->times.size();arcNo++)
          {
            const auto &times=para->times.at(arcNo);
            if(times.empty())throw(Exception("empty native trajectory query arc"));
            for(UInt i=0;i<times.size();i++,trajectoryIndex++,trajectoryCount++)
            {
              const std::vector<Weight> identity={{i,1.L,0.L}};
              stateQuery(out,"trajectory",para->recv->idRecv(),arcNo,trajectoryIndex,first,count,times[i],identity,identity);
            }
            for(UInt i=0;i<gnss->times.size();i++)
              if(!covered[i]&&gnss->times[i]>=times.front()&&gnss->times[i]<=times.back())
              {
                const auto position=para->polynomial.at(arcNo).orbitPocStencil(gnss->times[i]);
                const auto velocity=para->polynomial.at(arcNo).orbitPocStencil(gnss->times[i],0.L,TRUE);
                stateQuery(out,"nominal_observation",para->recv->idRecv(),arcNo,i,first,count,gnss->times[i],position,velocity);
                covered[i]=TRUE;observationCount++;
              }
          }
          for(Bool valid:covered)if(!valid)throw(Exception("A nominal GNSS covariance query lies outside every native arc"));
        }
      if(!trajectoryCount||!observationCount)throw(Exception("empty segmented covariance query support"));
      out<<"{\"kind\":\"complete\",\"trajectory_count\":"<<trajectoryCount<<",\"nominal_observation_count\":"<<observationCount<<"}\n";
      if(!out)throw(Exception("segmented covariance query export failed"));
    }
'''


QUERY_GATE = r'''
    // ORBIT_POC_SEGMENTED_QUERY_GATE_V4: bounded reference only, never used by
    // the production segmented covariance conditional-solve path.
    if(!segmentedQueryReference.empty()&&segmentedQueries.empty())throw(Exception("query reference needs query export"));
    if(!segmentedQueries.empty())
    {
      const auto queries=segmentedQuerySeries?segmentedQuerySeries->times():(querySeries?querySeries->times():equation.times);
      if(equation.times.size()>1000||queries.size()>1000||count>200)
        throw(Exception("segmented query gate is bounded to 1000 epochs and 200 parameters"));
      std::vector<Time> boundaries=acceleration->integrationBoundaries();
      if(boundarySeries){const auto extra=boundarySeries->times();boundaries.insert(boundaries.end(),extra.begin(),extra.end());}
      OrbitPocPiecewisePolynomial interpolation(equation.times,interpolationDegree,boundaries,pulses);
      using namespace OrbitPoc::SegmentedExport;
      std::ofstream out(segmentedQueries.str());out.precision(17);if(!out)throw(Exception("cannot open native query gate export"));
      out<<"{\"kind\":\"metadata\",\"schema\":\"orbit-poc-segmented-covariance-queries-v1\",\"factor_stem\":\"bounded_native_gate\",\"coordinates\":\"Cartesian_SI\",\"row_order\":\"position_xyz_velocity_xyz\",\"post_pulse_velocity\":true,\"covariance_produced\":false}\n";
      for(UInt i=0;i<equation.times.size();i++)
      {const std::vector<Weight> identity={{i,1.L,0.L}};stateQuery(out,"trajectory",0,0,i,0,count,equation.times[i],identity,identity);}
      for(UInt i=0;i<queries.size();i++)
        stateQuery(out,"nominal_observation",0,0,i,0,count,queries[i],interpolation.orbitPocStencil(queries[i]),interpolation.orbitPocStencil(queries[i],0.L,TRUE));
      out<<"{\"kind\":\"complete\",\"trajectory_count\":"<<equation.times.size()<<",\"nominal_observation_count\":"<<queries.size()<<"}\n";
      if(!out)throw(Exception("native query gate export failed"));
      if(!segmentedQueryReference.empty())
      {
        const Matrix position=interpolation.interpolate(queries,equation.PosDesign,3);
        const Matrix velocity=interpolation.interpolate(queries,equation.VelDesign,3,TRUE);
        Matrix reference(6*queries.size(),count);
        for(UInt i=0;i<queries.size();i++){copy(position.row(3*i,3),reference.row(6*i,3));copy(velocity.row(3*i,3),reference.row(6*i+3,3));}
        writeFileMatrix(segmentedQueryReference,reference);
      }
    }
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    print(json.dumps(apply(parser.parse_args().source), indent=2))
