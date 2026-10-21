// SPDX-License-Identifier: GPL-3.0-or-later
// Numerical gate: evaluate the native variational model at fixed parameters and
// optionally reanchor its six state columns to one physical initial state.
#include "programs/program.h"
#include "files/fileInstrument.h"
#include "files/fileMatrix.h"
#include "files/fileVariationalEquation.h"
#include "classes/timeSeries/timeSeries.h"
#include "classes/ephemerides/ephemerides.h"
#include "classes/parametrizationAcceleration/parametrizationAcceleration.h"
#include "misc/observation/variationalEquationFromFile.h"
#include "misc/orbitPoc/piecewisePolynomial.h"

class OrbitPocEvaluateVariational
{
public:
  void run(Config &config, Parallel::CommunicatorPtr comm);
};
GROOPS_REGISTER_PROGRAM(OrbitPocEvaluateVariational,SINGLEPROCESS,
                       "Evaluate fixed native variational parameters with optional state reanchoring",Orbit)

void OrbitPocEvaluateVariational::run(Config &config, Parallel::CommunicatorPtr)
{
  try
  {
    FileName input, output, parametersFile, initialFile, outputParameters, epochReference, epochDifferences, boundaryDifferences, initialDesign;
    ParametrizationAccelerationPtr acceleration;
    EphemeridesPtr ephemerides;
    TimeSeriesPtr pulseSeries, querySeries, boundarySeries;
    UInt degree, interpolationDegree;
    FileName segmentedDesign,segmentedReferenceDesign,segmentedQueries,segmentedQueryReference;Bool segmentedOnly=FALSE;
    TimeSeriesPtr segmentedQuerySeries;
    Double epochSampling;
    readConfig(config,"inputfileVariational",input,Config::MUSTSET,"","single native variational arc");
    readConfig(config,"outputfileSegmentedDesign",segmentedDesign,Config::OPTIONAL,"","v4 sparse variation-of-constants design JSONL");
    readConfig(config,"outputfileSegmentedReferenceDesign",segmentedReferenceDesign,Config::OPTIONAL,"","small-gate-only exact original dense design, interleaved r/v rows");
    readConfig(config,"segmentedExportOnly",segmentedOnly,Config::DEFAULT,"0","export the local design without allocating global PosDesign/VelDesign");
    readConfig(config,"outputfileSegmentedCovarianceQueries",segmentedQueries,Config::OPTIONAL,"","Cartesian state query stencils; bounded native gate");
    readConfig(config,"outputfileSegmentedQueryReferenceDesign",segmentedQueryReference,Config::OPTIONAL,"","small-gate-only native dense query designs");
    readConfig(config,"segmentedQueryTimeSeries",segmentedQuerySeries,Config::OPTIONAL,"","independent small-gate query grid; does not alter orbit output");
    readConfig(config,"outputfileOrbit",output,Config::MUSTSET,"","evaluated CRF state in SI units");
    readConfig(config,"inputfileParameters",parametersFile,Config::OPTIONAL,"","full native parameter vector; default zero");
    readConfig(config,"inputfileInitialState",initialFile,Config::OPTIONAL,"","six SI Cartesian components at first arc epoch");
    readConfig(config,"outputfileParameters",outputParameters,Config::OPTIONAL,"","parameters after state reanchoring");
    readConfig(config,"outputfileInitialStateDesign",initialDesign,Config::OPTIONAL,"","v3.1 six physical initial-state rows versus all native dynamic columns");
    readConfig(config,"parametrizationAcceleration",acceleration,Config::DEFAULT,"","same acceleration design as fitted model");
    readConfig(config,"stochasticPulse",pulseSeries,Config::OPTIONAL,"","same impulse times as fitted model");
    readConfig(config,"ephemerides",ephemerides,Config::DEFAULT,"jpl","same native ephemerides");
    readConfig(config,"integrationDegree",degree,Config::DEFAULT,"7","same native quadrature degree");
    readConfig(config,"timeSeries",querySeries,Config::OPTIONAL,"","optional off-grid evaluation epochs");
    readConfig(config,"interpolationBoundaries",boundarySeries,Config::OPTIONAL,"","additional continuous force knots for fixed-force diagnostics");
    readConfig(config,"interpolationDegree",interpolationDegree,Config::DEFAULT,"7","same piecewise interpolation as native fitted orbit");
    readConfig(config,"inputfileEpochReference",epochReference,Config::OPTIONAL,"","diagnostic orbit whose native Time records are compared with model epochs");
    readConfig(config,"outputfileEpochDifferences",epochDifferences,Config::OPTIONAL,"","native Time subtraction: row index, reference minus model seconds");
    readConfig(config,"epochSamplingSeconds",epochSampling,Config::DEFAULT,"0","optional exact nominal epoch-grid interval for regression");
    readConfig(config,"outputfileBoundaryEpochDifferences",boundaryDifferences,Config::OPTIONAL,"","native model-knot minus nearest exact grid epoch seconds");
    if(isCreateSchema(config)) return;
    FileVariationalEquation stored(input);
    if(stored.arcCount()!=1) throw(Exception("numerical gate requires exactly one variational arc"));
    auto arc=stored.readArc(0);
    if(arc.times.empty()) throw(Exception("empty native variational arc"));
    std::vector<Time> pulses=pulseSeries ? pulseSeries->times() : std::vector<Time>();
    VariationalEquationFromFile model;
    model.open(input,nullptr,acceleration,pulses,ephemerides,degree);
    if(segmentedOnly && (segmentedDesign.empty()||!segmentedReferenceDesign.empty()))throw(Exception("segmentedExportOnly needs outputfileSegmentedDesign and forbids dense reference output"));
    if(!segmentedDesign.empty())model.orbitPocExportSegmented(segmentedDesign);
    if(segmentedOnly && (!segmentedQueries.empty()||!segmentedQueryReference.empty()))throw(Exception("segmentedExportOnly forbids gate-only query outputs"));
    if(segmentedOnly)return;
    if(!segmentedReferenceDesign.empty() && (arc.times.size()>1000||model.parameterCount()>200))throw(Exception("dense segmented reference export is bounded to small gates"));
    auto equation=model.integrateArc(arc.times.front(),arc.times.back(),TRUE,TRUE);
    if(!segmentedReferenceDesign.empty())
    {
      if(equation.times.size()>1000||model.parameterCount()>200)throw(Exception("dense segmented reference export is bounded to small gates"));
      Matrix reference(6*equation.times.size(),model.parameterCount());
      for(UInt i=0;i<equation.times.size();i++){copy(equation.PosDesign.row(3*i,3),reference.row(6*i,3));copy(equation.VelDesign.row(3*i,3),reference.row(6*i+3,3));}
      writeFileMatrix(segmentedReferenceDesign,reference);
    }
    const UInt count=model.parameterCount();
    if(count<6) throw(Exception("native model lacks six state columns"));
    if(!initialDesign.empty())
    {
      Matrix design(6,count);
      copy(equation.PosDesign.row(0,3),design.row(0,3));
      copy(equation.VelDesign.row(0,3),design.row(3,3));
      writeFileMatrix(initialDesign,design);
    }
    Vector x(count);
    if(!parametersFile.empty())
    {
      Matrix values; readFileMatrix(parametersFile,values);
      if(values.rows()!=count || values.columns()!=1) throw(Exception("parameter vector must be count by one"));
      copy(values,x);
    }
    if(!initialFile.empty())
    {
      Matrix target; readFileMatrix(initialFile,target);
      if(target.rows()!=6 || target.columns()!=1) throw(Exception("initial state must be six by one"));
      for(UInt i=count-6;i<count;i++) x(i)=0.;
      Matrix N(6,6); Vector rhs(6);
      copy(equation.PosDesign.slice(0,count-6,3,6),N.row(0,3));
      copy(equation.VelDesign.slice(0,count-6,3,6),N.row(3,3));
      Matrix position=equation.pos0, velocity=equation.vel0;
      matMult(1.,equation.PosDesign,x,position);
      matMult(1.,equation.VelDesign,x,velocity);
      for(UInt i=0;i<3;i++)
      {
        rhs(i)=target(i,0)-position(i,0);
        rhs(i+3)=target(i+3,0)-velocity(i,0);
      }
      const Matrix state=solve(N,rhs);
      for(UInt i=0;i<6;i++) x(count-6+i)=state(i,0);
    }
    Matrix position=equation.pos0, velocity=equation.vel0;
    matMult(1.,equation.PosDesign,x,position);
    matMult(1.,equation.VelDesign,x,velocity);

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

    std::vector<Time> outputTimes=equation.times;
    if(querySeries)
    {
      std::vector<Time> boundaries=acceleration->integrationBoundaries();
      if(boundarySeries)
      {
        const auto extra=boundarySeries->times();
        boundaries.insert(boundaries.end(),extra.begin(),extra.end());
      }
      OrbitPocPiecewisePolynomial interpolation(equation.times,interpolationDegree,boundaries,pulses);
      outputTimes=querySeries->times();
      position=interpolation.interpolate(outputTimes,position,3);
      velocity=interpolation.interpolate(outputTimes,velocity,3,TRUE);
    }
    OrbitArc result;
    for(UInt i=0;i<outputTimes.size();i++)
    {
      OrbitEpoch epoch; epoch.time=outputTimes[i];
      epoch.position=Vector3d(position.row(3*i,3));
      epoch.velocity=Vector3d(velocity.row(3*i,3));
      result.push_back(epoch);
    }
    InstrumentFile::write(output,result);
    if(!epochReference.empty() || !epochDifferences.empty())
    {
      if(epochReference.empty() || epochDifferences.empty())
        throw(Exception("epoch-precision regression needs both reference and difference paths"));
      const OrbitArc reference=InstrumentFile::read(epochReference);
      if(reference.size()!=outputTimes.size()) throw(Exception("epoch-reference count mismatch"));
      Matrix differences(outputTimes.size(),epochSampling>0 ? 3 : 2);
      for(UInt i=0;i<outputTimes.size();i++)
      {
        differences(i,0)=i;
        differences(i,1)=(reference.at(i).time-outputTimes.at(i)).seconds();
        if(epochSampling>0)
          differences(i,2)=(outputTimes.at(i)-(outputTimes.front()+seconds2time(i*epochSampling))).seconds();
      }
      writeFileMatrix(epochDifferences,differences);
    }
    if(!boundaryDifferences.empty())
    {
      if(epochSampling<=0) throw(Exception("boundary epoch regression needs positive epochSamplingSeconds"));
      auto boundaries=acceleration->integrationBoundaries();
      boundaries.insert(boundaries.end(),pulses.begin(),pulses.end());
      Matrix differences(boundaries.size(),2);
      for(UInt i=0;i<boundaries.size();i++)
      {
        const auto index=std::llround((boundaries.at(i)-equation.times.front()).seconds()/epochSampling);
        differences(i,0)=i;
        differences(i,1)=(boundaries.at(i)-(equation.times.front()+seconds2time(index*epochSampling))).seconds();
      }
      writeFileMatrix(boundaryDifferences,differences);
    }
    if(!outputParameters.empty()) writeFileMatrix(outputParameters,x);
    logInfo<<"Numerical gate evaluates one native linearization; state reanchoring is linearized."<<Log::endl;
  }
  catch(std::exception &error) { GROOPS_RETHROW(error) }
}
