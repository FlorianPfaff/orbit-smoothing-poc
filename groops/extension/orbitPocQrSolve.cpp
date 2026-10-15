// SPDX-License-Identifier: GPL-3.0-or-later
#define DOCSTRING docstring
static const char *docstring=R"(Native v3.1 original-row QR correctness fixture.
Reads a weighted matrix with the residual as its last column. The first
localColumns are independent epoch clocks; the first dynamicColumns of the
remaining columns are dynamics. This uses the same streaming implementation,
rank diagnosis, local recovery and selected covariance as native GNSS.)";
#include "programs/program.h"
#include "files/fileMatrix.h"
#include "base/polynomial.h"
#include "misc/orbitPoc/scaledRowQr.h"
#include "misc/orbitPoc/nuisanceLineSearch.h"
#include "misc/orbitPoc/gnssRangeResidual.h"
#include "misc/orbitPoc/piecewisePolynomial.h"
class OrbitPocQrSolve {public:void run(Config &,Parallel::CommunicatorPtr);};
GROOPS_REGISTER_PROGRAM(OrbitPocQrSolve,SINGLEPROCESS,"Native weighted-row QR validation",Simulation)
void OrbitPocQrSolve::run(Config &config,Parallel::CommunicatorPtr comm)
{
  FileName input,output,covariance,prefix,coordinateUpdates,objectiveExpansions;UInt locals,dynamics,datumReceivers,datumTransmitters,generations,failBeforeFactorGeneration;Double lambda;Bool nuisanceOnly,ionosphereColumn,datumSelection,costOnlyCheck,jointEpochLocals,interpolationFixture,rangeResidualFixture,clockTimeFixture,relativePulseFixture,precisePositionFixture,objectiveLedgerFixture;std::string nuisanceFixture,objectiveLedgerFailure;
  readConfig(config,"inputfileRows",input,Config::MUSTSET,"","weighted A followed by b");
  readConfig(config,"outputfileSolution",output,Config::MUSTSET,"","native-unit update");
  readConfig(config,"outputfileCovariance",covariance,Config::OPTIONAL,"","retained covariance, always undamped");
  readConfig(config,"outputPrefix",prefix,Config::MUSTSET,"","native factor and diagnostics prefix");
  readConfig(config,"localColumns",locals,Config::DEFAULT,"0","leading independent clock columns");
  readConfig(config,"dynamicColumns",dynamics,Config::DEFAULT,"0","leading retained dynamic columns");
  readConfig(config,"lambda",lambda,Config::DEFAULT,"0","dynamic-only scaled damping");
  readConfig(config,"nuisanceOnly",nuisanceOnly,Config::DEFAULT,"0","hold all dynamic updates at zero");
  readConfig(config,"ionosphereColumn",ionosphereColumn,Config::DEFAULT,"0","eliminate leading original-row group nuisance");
  readConfig(config,"datumSelection",datumSelection,Config::DEFAULT,"0","exercise original-row ambiguity datum selection");
  readConfig(config,"datumReceiverColumns",datumReceivers,Config::DEFAULT,"0","leading datum receiver columns");
  readConfig(config,"datumTransmitterColumns",datumTransmitters,Config::DEFAULT,"0","datum transmitter columns after receivers");
  readConfig(config,"generations",generations,Config::DEFAULT,"1","repeat identical linearization for artifact lifecycle checks");
  readConfig(config,"failBeforeFactorGeneration",failBeforeFactorGeneration,Config::DEFAULT,"0","fixture-only failed successor generation");
  readConfig(config,"inputfileCoordinateUpdates",coordinateUpdates,Config::OPTIONAL,"","exercise accumulated coordinates for overlapping bias bases");
  readConfig(config,"nuisanceFixture",nuisanceFixture,Config::OPTIONAL,"","transactional nuisance search fixture mode");
  readConfig(config,"costOnlyCheck",costOnlyCheck,Config::DEFAULT,"0","verify isolated cost-only objective preserves native files");
  readConfig(config,"jointEpochLocals",jointEpochLocals,Config::DEFAULT,"0","joint clock/VTEC epoch block after STEC elimination");
  readConfig(config,"interpolationFixture",interpolationFixture,Config::DEFAULT,"0","continuous native polynomial query regression");
  readConfig(config,"rangeResidualFixture",rangeResidualFixture,Config::DEFAULT,"0","stable corrected GNSS range equation regression");
  readConfig(config,"clockTimeFixture",clockTimeFixture,Config::DEFAULT,"0","receiver clock day-fraction precision and rollover regression");
  readConfig(config,"relativePulseFixture",relativePulseFixture,Config::DEFAULT,"0","exact pulse side with sub-Time clock offsets");
  readConfig(config,"precisePositionFixture",precisePositionFixture,Config::DEFAULT,"0","sub-double coordinate remainders in corrected range");
  readConfig(config,"objectiveLedgerFixture",objectiveLedgerFixture,Config::DEFAULT,"0","original observation/prior objective independent of group QR basis");
  readConfig(config,"objectiveLedgerFailure",objectiveLedgerFailure,Config::OPTIONAL,"","inject missing capture or misclassified prior in objective fixture");
  readConfig(config,"inputfileObjectiveExpansions",objectiveExpansions,Config::OPTIONAL,"","fixture-only before high/low and after high/low original observation residuals");
  if(isCreateSchema(config))return;
  Matrix rows;readFileMatrix(input,rows);
  if(rows.columns()<2||locals+dynamics>rows.columns()-1)throw(Exception("Invalid native QR fixture dimensions"));
  if(!objectiveExpansions.empty()&&!objectiveLedgerFixture)throw(Exception("Objective expansions require the original-objective fixture"));
  if(objectiveLedgerFixture)
  {
    if(!objectiveLedgerFailure.empty()&&objectiveLedgerFailure!="missing_capture"&&objectiveLedgerFailure!="misclassified_prior"&&objectiveLedgerFailure!="missing_capture_cost_only"&&objectiveLedgerFailure!="misclassified_prior_cost_only")
      throw(Exception("Unknown original-objective fixture failure"));
    // Columns: group B before/after, original residual before/after, row role.
    // Roles: 0 group observation (including its local prior), 1 B-empty
    // observation, 2 epoch prior, 3 global prior. No parameter solve occurs.
    if(rows.columns()!=5)throw(Exception("Original-objective fixture requires five columns"));
    Matrix expansions;
    if(!objectiveExpansions.empty())
    {
      readFileMatrix(objectiveExpansions,expansions);
      if(expansions.rows()!=rows.rows()||expansions.columns()!=4)throw(Exception("Objective expansion fixture dimensions differ"));
      for(UInt i=0;i<rows.rows();i++)
        if(rows(i,4)>=2 && (expansions(i,1)!=0. || expansions(i,3)!=0. || expansions(i,0)!=rows(i,2) || expansions(i,2)!=rows(i,3)))
          throw(Exception("Objective expansion fixture keeps native binary64 constraint targets"));
    }
    auto preciseRows=[&](const std::vector<UInt> &indices,UInt trial)
    {
      std::vector<orbitPocQr::TwofoldGeometry> result;
      for(UInt i:indices)result.emplace_back(expansions(i,2*trial),expansions(i,2*trial+1));
      return result;
    };
    std::vector<UInt> grouped,ungrouped,epochPriors,globalPriors;
    for(UInt i=0;i<rows.rows();i++)
    {
      const Double role=rows(i,4);
      if(role==0)grouped.push_back(i);else if(role==1)ungrouped.push_back(i);
      else if(role==2)epochPriors.push_back(i);else if(role==3)globalPriors.push_back(i);
      else throw(Exception("Unknown original-objective fixture row role"));
    }
    if(grouped.size()<2||ungrouped.empty()||epochPriors.empty()||globalPriors.empty())
      throw(Exception("Original-objective fixture needs grouped/plain observations and both prior types"));
    setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
    GnssNormalEquationInfo info(0,0,0,comm);info.parameterNamesOther({ParameterName("fixture","testBias")});info.calculateIndex(Vector());
    OrbitPocRowQr qr;std::vector<Double> transformedBefore,transformedAfter;
    auto build=[&](UInt trial,std::vector<Double> &transformed)
    {
      const Bool inject=!objectiveLedgerFailure.empty()&&((objectiveLedgerFailure.find("_cost_only")!=std::string::npos)==(trial==1));
      qr.begin(info);qr.beginEpoch(0,0,0);qr.context("fixture_epoch_prior");
      for(UInt i:epochPriors){qr.addRow(rows(i,2+trial),{0},{1.});transformed.push_back(rows(i,2+trial));}
      Matrix original(grouped.size(),1);Vector residual(grouped.size());
      for(UInt j=0;j<grouped.size();j++){original(j,0)=rows(grouped[j],trial);residual(j)=rows(grouped[j],2+trial);}
      qr.context("weighted_observation");
      if(!(inject&&objectiveLedgerFailure.find("missing_capture")==0))
      {
        if(objectiveExpansions.empty())qr.retainObservationResiduals(0,0,0,residual);
        else qr.retainObservationResiduals(0,0,0,residual,preciseRows(grouped,trial));
      }
      Matrix factor(original);const Vector tau=QR_decomposition(factor);
      qr.retainGroup(0,0,0,original,factor,tau,residual);Vector rotated(residual);QTransMult(factor,tau,rotated);
      for(UInt j=0;j<rotated.rows();j++)transformed.push_back(rotated(j));
      for(UInt j=1;j<rotated.rows();j++)qr.addRow(rotated(j),{0},{1.});
      Vector plain(ungrouped.size());for(UInt j=0;j<ungrouped.size();j++)plain(j)=rows(ungrouped[j],2+trial);
      if(objectiveExpansions.empty())qr.retainObservationResiduals(0,1,0,plain);
      else qr.retainObservationResiduals(0,1,0,plain,preciseRows(ungrouped,trial));
      for(UInt j=0;j<plain.rows();j++){qr.addRow(plain(j),{0},{1.});transformed.push_back(plain(j));}
      qr.finishEpoch();qr.context(inject&&objectiveLedgerFailure.find("misclassified_prior")==0?"weighted_observation":"fixture_global_prior");
      for(UInt i:globalPriors){qr.addRow(rows(i,2+trial),{0},{1.});transformed.push_back(rows(i,2+trial));}
      qr.finish();
    };
    build(0,transformedBefore);const Double before=qr.rawCost();const UInt originalCount=qr.originalObjectiveRowCount();
    qr.prepareCostOnly();build(1,transformedAfter);
    orbitPocQr::ObjectiveSum oldReduction;
    for(UInt i=0;i<transformedBefore.size();i++)oldReduction.add(.5L*(static_cast<long double>(transformedBefore[i])-transformedAfter[i])*(static_cast<long double>(transformedBefore[i])+transformedAfter[i]));
    std::ofstream receipt(output.str());receipt<<std::setprecision(17)<<"{\"before\":"<<before<<",\"after\":"<<qr.rawCost()
      <<",\"actual_reduction\":"<<qr.actualObjectiveReduction()<<",\"transformed_basis_reduction\":"<<static_cast<Double>(oldReduction.value())
      <<",\"original_rows_before\":"<<originalCount<<",\"original_rows_after\":"<<qr.originalObjectiveRowCount()<<"}\n";
    if(!receipt)throw(Exception("Cannot record original-objective fixture"));return;
  }
  if(precisePositionFixture)
  {
    const Vector3d receiver(6900000.,0.,0.),transmitter(26000000.,0.,0.);const Double c=LIGHT_VELOCITY;
    const Double measured=transmitter.x()-receiver.x()+2*DEFAULT_GM/(c*c)*std::log(transmitter.x()/receiver.x())+50.;
    const Double before=orbitPocQr::stableRangeResidual(measured,receiver,transmitter,Vector3d(),0.,0.,1.);
    Matrix answer(7,5);UInt row=0;
    for(Double shift:{-1e-8,-1e-9,-1e-10,1e-12,1e-11,1e-10,1e-9})
    {
      const Vector3d rounded(receiver.x()+shift,0.,0.);
      const Vector3d remainder(static_cast<Double>((static_cast<long double>(receiver.x())+shift)-rounded.x()),0.,0.);
      answer(row,0)=shift;answer(row,1)=orbitPocQr::stableRangeResidual(measured,rounded,transmitter,Vector3d(),0.,0.,1.,remainder)-before;
      answer(row,2)=orbitPocQr::stableRangeResidual(measured,rounded,transmitter,Vector3d(),0.,0.,1.)-before;
      answer(row,3)=rounded.x();answer(row,4)=remainder.x();row++;
    }
    writeFileMatrix(output,answer);return;
  }
  if(relativePulseFixture)
  {
    setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
    const Time boundary=date2time(2024,4,24,12,0,0);std::vector<Time> nodes;Matrix velocities(21,1);
    for(UInt i=0;i<21;i++){nodes.push_back(boundary+seconds2time(30.*i-300.));velocities(i,0)=i<10?1.:2.;}
    OrbitPocPiecewisePolynomial polynomial(nodes,3,{boundary},{boundary});Matrix answer(8,4);UInt row=0;
    for(Double shift:{-50e-9,-1e-12,-1e-13,0.,1e-13,1e-12,50e-9})
    {
      const Time rounded=orbitPocQr::stableReceiverTime(boundary,-shift);
      const long double remainder=orbitPocQr::timeRemainder(boundary,-shift,rounded);
      answer(row,0)=shift;answer(row,1)=shift<0?1.:2.;
      answer(row,2)=polynomial.interpolateOffset({rounded},velocities,{remainder},1,TRUE)(0,0);
      answer(row,3)=polynomial.interpolate({rounded},velocities,1,TRUE)(0,0);row++;
    }
    const Time before=orbitPocQr::stableReceiverTime(boundary,50e-9);
    answer(row,0)=-50e-9;answer(row,1)=1.;answer(row,2)=polynomial.interpolateOffset({before},velocities,{0.L},1,TRUE)(0,0);answer(row,3)=polynomial.interpolate({before},velocities,1,TRUE)(0,0);
    writeFileMatrix(output,answer);return;
  }
  if(clockTimeFixture)
  {
    const Time day=date2time(2024,4,24);Matrix answer(5,6);UInt row=0;
    setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
    for(Double seconds:{0.,3600.,43200.,86399.999999,86400.})
    {
      const Time nominal=day+seconds2time(seconds);Double oldError=0,newError=0,roundedPositionError=0,relativePositionError=0,derivativeError=0;
      std::vector<Time> nodes;Matrix positions(11,1);
      for(UInt i=0;i<11;i++)
      {
        const Time time=nominal+seconds2time(30.*i-150.);nodes.push_back(time);
        const long double dt=(static_cast<long double>(time.mjdInt())-nominal.mjdInt())*86400.L+(static_cast<long double>(time.mjdMod())-nominal.mjdMod())*86400.L;
        positions(i,0)=static_cast<Double>(2e6L+7000.L*dt);
      }
      Polynomial polynomial(nodes,7);
      for(Int k=-4096;k<=4096;k++)
      {
        const Double clock=(-2.2991272596286145+k*1e-6)/LIGHT_VELOCITY*(k%2 ? -1:1);
        const Time oldTime=nominal-seconds2time(clock),newTime=orbitPocQr::stableReceiverTime(nominal,clock);
        auto error=[&](const Time &time){return static_cast<Double>(std::fabs(((static_cast<long double>(time.mjdInt())-nominal.mjdInt())+(static_cast<long double>(time.mjdMod())-nominal.mjdMod()))*86400.L+clock));};
        oldError=std::max(oldError,error(oldTime));newError=std::max(newError,error(newTime));
        const long double remainder=orbitPocQr::timeRemainder(nominal,clock,newTime);
        const Double expected=static_cast<Double>(2e6L-7000.L*clock);
        roundedPositionError=std::max(roundedPositionError,std::fabs(polynomial.interpolate({newTime},positions)(0,0)-expected));
        relativePositionError=std::max(relativePositionError,std::fabs(polynomial.interpolateOffset({newTime},positions,{remainder})(0,0)-expected));
        derivativeError=std::max(derivativeError,std::fabs(polynomial.interpolateOffset({newTime},positions,{remainder},1,1)(0,0)-7000.));
        if(std::fabs(((static_cast<long double>(newTime.mjdInt())-nominal.mjdInt())+(static_cast<long double>(newTime.mjdMod())-nominal.mjdMod()))*86400.L)>1e-6L)throw(Exception("Receiver clock crossed wrong day boundary"));
      }
      answer(row,0)=seconds;answer(row,1)=oldError;answer(row,2)=newError;answer(row,3)=roundedPositionError;answer(row,4)=relativePositionError;answer(row,5)=derivativeError;row++;
    }
    writeFileMatrix(output,answer);return;
  }
  if(rangeResidualFixture)
  {
    const Vector3d recv(6800000.,120000.,340000.),trans(26000000.,-3000000.,5000000.),velocity(300.,3800.,-20.);
    const Double c=LIGHT_VELOCITY,clock=49.14767394980945/c,scale=1.000000004;
    const Double r1=trans.r(),r2=recv.r(),distance=(recv-trans).r();
    const Double geometric=distance+2*DEFAULT_GM/std::pow(c,2)*std::log((r1+r2+distance)/(r1+r2-distance))+2*inner(trans,velocity)/c;
    const Double measured=(geometric+c*clock)*scale+50.;
    const Double before=orbitPocQr::stableRangeResidual(measured,recv,trans,velocity,clock,0.,scale);
    const Double legacyBefore=measured-(geometric+c*clock)*scale;
    Matrix answer(7,4);UInt row=0;
    for(Double shift:{1e-11,1e-10,1e-9,3e-9,1e-8,1e-7,1e-5})
    {
      const Double afterClock=clock+shift/c;
      const long double expected=-(static_cast<long double>(afterClock)-clock)*c*scale;
      answer(row,0)=static_cast<Double>(expected);
      answer(row,1)=orbitPocQr::stableRangeResidual(measured,recv,trans,velocity,afterClock,0.,scale)-before;
      answer(row,2)=measured-(geometric+c*afterClock)*scale-legacyBefore;
      answer(row,3)=before;row++;
    }
    writeFileMatrix(output,answer);return;
  }
  if(interpolationFixture)
  {
    const std::string originalPrefix=orbitPocQr::env("ORBIT_POC_NUMERICS_QR_PREFIX");
    std::vector<Time> epochs;const Time start=date2time(2024,4,24,1,0,0);
    Matrix values(11,1);for(UInt i=0;i<11;i++){epochs.push_back(start+seconds2time(30*i));values(i,0)=2e6+7000*(30.*i-150.);}
    Matrix answer(14,8);UInt row=0;
    for(Double margin:{1e-7,1e-5})
    {
      Polynomial polynomial;polynomial.init(epochs,7,TRUE,FALSE,-8.1,-1.1,margin);
      for(Double factor:{-1.01,-.99,-.01,0.,.01,.99,1.01})
      {
        const Time query=epochs.at(5)+seconds2time(factor*margin);const Double dt=(query-epochs.at(5)).seconds();
        unsetenv("ORBIT_POC_NUMERICS_QR_PREFIX");const Double legacy=polynomial.interpolate({query},values)(0,0);
        setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
        const Double precise=polynomial.interpolate({query},values)(0,0),derivative=polynomial.interpolate({query},values,1,1)(0,0);
        const Matrix same=polynomial.interpolate(epochs,values);
        std::vector<Time> shifted=epochs;for(auto &time:shifted)time+=seconds2time(1e-10);
        const Matrix moved=polynomial.interpolate(shifted,values);Double arrayError=0;
        for(UInt i=0;i<epochs.size();i++)arrayError=std::max(arrayError,std::fabs(moved(i,0)-values(i,0)-7000*(shifted[i]-epochs[i]).seconds()));
        answer(row,0)=margin;answer(row,1)=dt;answer(row,2)=legacy;answer(row,3)=precise;answer(row,4)=derivative;
        answer(row,5)=2e6+7000*dt;answer(row,6)=arrayError;answer(row,7)=norm(same-values);row++;
      }
    }
    if(originalPrefix.empty())unsetenv("ORBIT_POC_NUMERICS_QR_PREFIX");else setenv("ORBIT_POC_NUMERICS_QR_PREFIX",originalPrefix.c_str(),1);
    writeFileMatrix(output,answer);return;
  }
  if(!nuisanceFixture.empty())
  {
    if(nuisanceFixture.find("floor_")==0)
    {
      const Double prediction=nuisanceFixture=="floor_numeric_cap"?1e-30:(nuisanceFixture=="floor_small_direction"?1e-16:1e-8),before=10.;Double state=.1;
      const Double direction=(nuisanceFixture=="floor_small_direction"||nuisanceFixture=="floor_numeric_cap")?2e-8:(nuisanceFixture=="floor_influence_cap"?.1:(nuisanceFixture=="floor_refine"?.0001:.001));
      std::ofstream inherited(prefix.str()+".parent.txt");inherited<<"parent\n";inherited.flush();
      auto evaluate=[&](Double alpha)
      {
        state+=alpha*direction;inherited<<"forbidden child output\n";inherited.flush();
        orbitPocQr::NuisanceTrial trial;trial.change=std::fabs(alpha)*direction;trial.support=123;trial.rows=1;trial.observationSignature=456;
        const Double slope=(nuisanceFixture=="floor_wrong_slope"?10.:2.)*prediction;
        const Double curvature=nuisanceFixture=="floor_negative_curvature"?-prediction:(nuisanceFixture=="floor_unresolved_curvature"?0.:(nuisanceFixture=="floor_weak_curvature"?.2*prediction:prediction));
        trial.reduction=slope*alpha-curvature*alpha*alpha;
        if(nuisanceFixture=="floor_amplitude")trial.reduction-=1e-9*std::pow(alpha,4);
        if(alpha>0&&alpha<=1)trial.reduction=-1e-9; // engineered finite-resolution plateau
        if(nuisanceFixture=="floor_zero_replay"&&alpha==0)trial.reduction=1e-10;
        if(nuisanceFixture=="floor_probe_support"&&std::fabs(alpha)>1)trial.support=321;
        if(nuisanceFixture=="floor_probe_exception"&&std::fabs(alpha)>1)throw(Exception("injected probe failure"));
        trial.cost=before-trial.reduction;
        if(nuisanceFixture=="floor_probe_nonfinite"&&std::fabs(alpha)>1)trial.cost=std::numeric_limits<Double>::quiet_NaN();
        if(nuisanceFixture=="floor_actual_influence"&&std::fabs(alpha)>1)trial.change=1.1;
        if(nuisanceFixture=="floor_derived_nonfinite"&&std::fabs(alpha)>1)
        {trial.reduction=-.75*std::numeric_limits<Double>::max();trial.cost=-trial.reduction;}
        return trial;
      };
      auto audit=[&](UInt mode)
      {
        auto trial=evaluate(0.);trial.reduction=(mode==1?4e-8:2e-8);trial.cost=before-trial.reduction;
        if(nuisanceFixture=="floor_zero_resolution")trial.reduction=0;
        if(nuisanceFixture=="floor_small_resolution")trial.reduction=1e-9;
        if(nuisanceFixture=="floor_audit_support")trial.support=321;
        if(nuisanceFixture=="floor_audit_nonfinite")trial.reduction=std::numeric_limits<Double>::infinity();
        if(nuisanceFixture=="floor_allowance")trial.reduction=1.000001e-8;
        if(nuisanceFixture=="floor_refine")trial.reduction=1.01e-8;
        if(nuisanceFixture=="floor_small_direction")trial.reduction=1e-8;
        if(nuisanceFixture=="floor_audit_exception")throw(Exception("injected audit failure"));
        return trial;
      };
      const auto search=orbitPocQr::searchNuisance(before,prediction,1e-8,123,1,evaluate,audit);
      if(state!=.1)throw(Exception("Floor audit or probe mutated parent state"));
      orbitPocQr::writeNuisanceSearch(output.str(),search,before,prediction);
      inherited<<"preserved\n";inherited.flush();return;
    }
    Double state=.1;const Double direction=4.95,before=.5*std::pow(1-state*state,2);
    std::ofstream inherited(prefix.str()+".parent.txt");inherited<<"parent\n";inherited.flush();
    auto evaluate=[&](Double alpha)
    {
      state+=alpha*direction;inherited<<"forbidden child output\n";inherited.flush();
      orbitPocQr::NuisanceTrial result;result.change=alpha*direction;result.cost=.5*std::pow(1-state*state,2);
      result.reduction=before-result.cost;result.support=123;result.rows=1;
      if(nuisanceFixture=="reject")result.reduction=-1;
      if(nuisanceFixture=="stationary")result.change=alpha*1e-10;
      if(nuisanceFixture=="support")result.support=321;
      if(nuisanceFixture=="exception")throw(Exception("injected child failure"));
      return result;
    };
    const auto search=orbitPocQr::searchNuisance(before,before,1e-8,123,1,evaluate);
    if(state!=.1)throw(Exception("Rejected native trial mutated parent state"));
    orbitPocQr::writeNuisanceSearch(output.str(),search,before,before);
    inherited<<"preserved\n";inherited.flush();return;
  }
  if(!coordinateUpdates.empty())
  {
    Matrix updates;readFileMatrix(coordinateUpdates,updates);const UInt n=rows.columns()-1;
    if(updates.rows()!=n)throw(Exception("Invalid accumulated-coordinate fixture dimensions"));
    Vector physical(rows.column(n));std::vector<Vector> accumulated(n);Matrix answer(n,updates.columns()+1);
    for(UInt j=0;j<n;j++)answer(j,0)=orbitPocQr::fullCoordinates(accumulated[j],rows.column(j),physical)(0);
    for(UInt k=0;k<updates.columns();k++)
    {
      for(UInt j=0;j<n;j++)orbitPocQr::accumulateCoordinates(accumulated[j],updates.slice(j,k,1,1));
      physical+=rows.column(0,n)*updates.column(k);
      for(UInt j=0;j<n;j++)answer(j,k+1)=orbitPocQr::fullCoordinates(accumulated[j],rows.column(j),physical)(0);
    }
    writeFileMatrix(output,answer);return;
  }
  if(datumSelection)
  {
    if(datumReceivers+datumTransmitters>rows.columns()-1)throw(Exception("Invalid datum fixture dimensions"));
    writeFileMatrix(output,orbitPocQr::selectDatum(rows.column(0,rows.columns()-1),datumReceivers,datumTransmitters));
    return;
  }
  const Matrix originalRows(rows);Matrix originalGroup,groupFactor;Vector groupTau;
  if(ionosphereColumn)
  {
    if(rows.columns()<3)throw(Exception("Group fixture requires retained columns"));
    originalGroup=Matrix(rows.column(0));groupFactor=originalGroup;orbitPocQr::requireRank(groupFactor,"fixture ionosphere");
    groupTau=QR_decomposition(groupFactor);Matrix transformed(rows.column(1,rows.columns()-1));QTransMult(groupFactor,groupTau,transformed);
    rows=Matrix(transformed.row(1,transformed.rows()-1));
  }
  const UInt n=rows.columns()-1;
  if(locals+dynamics>n)throw(Exception("Fixture dynamic columns exceed retained count"));
  setenv("ORBIT_POC_NUMERICS_QR_PREFIX",prefix.str().c_str(),1);
  GnssNormalEquationInfo info(locals,0,0,comm);
  for(UInt j=0;j<locals;j++)info.parameterNamesEpochOther(jointEpochLocals?0:j,{ParameterName("fixture",jointEpochLocals&&j==1?"VTEC":"clock",std::to_string(j))});
  std::vector<ParameterName> global;
  for(UInt j=locals;j<n;j++)global.push_back(ParameterName("fixture",j<locals+dynamics?(j==locals?"arc0.position0.x":j==locals+1?"arc0.velocity0.x":"logDensity"):"testBias",std::to_string(j)));
  info.parameterNamesOther(global);info.calculateIndex(Vector());
  if(!generations)throw(Exception("Fixture generations must be positive"));
  OrbitPocRowQr qr;
  for(UInt generation=0;generation<generations;generation++)
  {
  qr.begin(info);
  if(ionosphereColumn){qr.retainObservationResiduals(0,0,0,originalRows.column(originalRows.columns()-1));qr.retainGroup(0,0,0,originalGroup,groupFactor,groupTau,originalRows.column(originalRows.columns()-1));}
  auto append=[&](UInt i){std::vector<UInt> ids;std::vector<Double> values;for(UInt j=0;j<n;j++)if(rows(i,j)!=0){ids.push_back(j);values.push_back(rows(i,j));}qr.addRow(rows(i,n),ids,values);};
  auto appendEpochs=[&]()
  {
    if(jointEpochLocals)
    {qr.beginEpoch(0,0,locals);for(UInt i=0;i<rows.rows();i++)append(i);qr.finishEpoch();return;}
    for(UInt j=0;j<locals;j++)
    {qr.beginEpoch(j,j,1);for(UInt i=0;i<rows.rows();i++)if(rows(i,j)!=0){for(UInt k=0;k<locals;k++)if(k!=j&&rows(i,k)!=0)throw(Exception("Fixture has time-coupled clocks"));append(i);}qr.finishEpoch();}
    for(UInt i=0;i<rows.rows();i++){Bool local=FALSE;for(UInt j=0;j<locals;j++)local|=rows(i,j)!=0;if(!local)append(i);}
  };
  appendEpochs();
  if(generation+1==failBeforeFactorGeneration)throw(Exception("Injected fixture failure before successor factor"));
  qr.finish();const Vector undamped=qr.solve();const Vector step=qr.solve(lambda,nuisanceOnly);qr.writeDiagnostics(undamped,step,lambda);qr.writeProfileCost(qr.solve(0,TRUE));
  Vector answer=step;
  if(ionosphereColumn)
  {
    const Vector residual=originalRows.column(originalRows.columns()-1)-originalRows.column(1,n)*step;
    const Vector local=qr.recoverGroup(0,0,0,originalGroup,residual);
    answer=Vector(n+1);answer(0)=local(0);copy(step,answer.row(1,n));
  }
  if(generation+1==generations)
  {
    writeFileMatrix(output,answer);
    if(!covariance.empty()){std::vector<UInt> indices(n-locals);std::iota(indices.begin(),indices.end(),locals);writeFileMatrix(covariance,qr.covariance(indices));}
    if(costOnlyCheck)
    {
      const Double before=qr.rawCost();const auto signature=qr.supportSignature();qr.prepareCostOnly();qr.begin(info);
      if(ionosphereColumn){qr.retainObservationResiduals(0,0,0,originalRows.column(originalRows.columns()-1));qr.retainGroup(0,0,0,originalGroup,groupFactor,groupTau,originalRows.column(originalRows.columns()-1));}
      appendEpochs();
      qr.finish();std::ofstream receipt(prefix.str()+".cost_only.json");
      receipt<<std::setprecision(17)<<"{\"before\":"<<before<<",\"after\":"<<qr.rawCost()<<",\"actual_reduction\":"<<qr.actualObjectiveReduction()
             <<",\"same_support\":"<<(signature==qr.supportSignature()?"true":"false")<<"}\n";
    }
  }
  }
}
