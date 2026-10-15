"""Opt-in original-weighted-row QR for the pinned GROOPS GNSS pipeline.

Run after v3 extension patches. Inactive runs retain the upstream code path.
"""
from pathlib import Path
import shutil

MARKER = "ORBIT_POC_SCALED_ROW_QR_V31"
INCLUDE = '#include "misc/orbitPoc/scaledRowQr.h"\n'


def patch(path, changes):
    text = path.read_text()
    if MARKER in text:
        return
    for old, new in changes:
        if text.count(old) != 1:
            raise ValueError(f"QR patch anchor mismatch {path}: {old[:100]}")
        text = text.replace(old, new, 1)
    path.write_text('// ' + MARKER + '\n' + INCLUDE + text)


def _original_objective_hook(path):
    """One original residual capture before either the B-empty return or QR."""
    text = path.read_text()
    hook = "    if(orbitPocQr::enabled()) orbitPocRowQr().retainObservationResiduals(receiver->idRecv(),transmitter->idTrans(),idEpoch,l);\n"
    if hook in text:
        if text.count(hook) != 1:
            raise ValueError("Duplicate original-objective observation hook")
        return
    signature = "void GnssObservationEquation::eliminateGroupParameters(Bool removeRows)"
    anchor = "    if(!B.size())\n      return;"
    if text.count(signature) != 1 or text.count(anchor) != 1 or text.index(anchor) < text.index(signature):
        raise ValueError("Pinned original-objective observation hook changed")
    path.write_text(text.replace(anchor, hook + anchor, 1))


def _continuous_interpolation(source):
    """Evaluate the same interpolation polynomial continuously and stably."""
    path = source / "base/polynomial.cpp"
    text = path.read_text()
    marker = "ORBIT_POC_CONTINUOUS_INTERPOLATION_V31"
    if marker not in text:
        anchor = "    if(!derivative && !isLeastSquares && (timesNew == times)) // need interpolation?"
        replacement = """    const char *orbitPocPrefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    const Bool continuousQuery=orbitPocPrefix&&*orbitPocPrefix;
    auto exactTime=[](const Time &a,const Time &b){return a.mjdInt()==b.mjdInt()&&a.mjdMod()==b.mjdMod();};
    const Bool sameTimes=continuousQuery ? (timesNew.size()==times.size()&&std::equal(timesNew.begin(),timesNew.end(),times.begin(),exactTime)) : timesNew==times;
    if(!derivative && !isLeastSquares && sameTimes) // exact grid identity remains exact"""
        if text.count(anchor)!=1:
            raise ValueError("Continuous interpolation array identity anchor mismatch")
        text=text.replace(anchor,replacement,1)
        anchor="(std::fabs((*searchStart-timesNew.at(i)).seconds()) <= margin)"
        if text.count(anchor)!=1:
            raise ValueError("Continuous interpolation row snap anchor mismatch")
        text=text.replace(anchor,"(continuousQuery ? exactTime(*searchStart,timesNew.at(i)) : std::fabs((*searchStart-timesNew.at(i)).seconds()) <= margin)",1)
        text="// "+marker+"\n#include <cstdlib>\n"+text
    stable_marker = "ORBIT_POC_STABLE_INTERPOLATION_V31"
    if stable_marker not in text:
        anchor="      // compute interpolation coefficients\n      // ----------------------------------"
        block=r"""      // ORBIT_POC_STABLE_INTERPOLATION_V31
      // The identical degree/stencil polynomial, evaluated in local coordinates
      // and extended precision. Inverting monomials and summing Earth-sized
      // coordinates in double precision creates artificial sub-micrometre jumps.
      if(continuousQuery && !isLeastSquares)
      {
        std::vector<long double> nodes(count), weights(count);
        const Time &query=timesNew.at(i);
        for(UInt k=0;k<count;k++)
          nodes[k]=((static_cast<long double>(times.at(idx+k).mjdInt())-query.mjdInt())*86400.L+
                    (static_cast<long double>(times.at(idx+k).mjdMod())-query.mjdMod())*86400.L)/sampling;
        for(UInt k=0;k<count;k++)
        {
          std::vector<long double> polynomial(count,0.L);polynomial[0]=1.L;
          UInt order=0;long double denominator=1.L;
          for(UInt j=0;j<count;j++)if(j!=k)
          {
            denominator*=nodes[k]-nodes[j];
            for(UInt power=order+1;power>0;power--)polynomial[power]=polynomial[power-1]-nodes[j]*polynomial[power];
            polynomial[0]*=-nodes[j];order++;
          }
          if(derivative<count)
          {weights[k]=polynomial[derivative]/denominator;for(UInt order=1;order<=derivative;order++)weights[k]*=static_cast<long double>(order)/sampling;}
        }
        if(!adjoint)
          for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)
          {long double value=0;for(UInt k=0;k<count;k++)value+=weights[k]*A(rowsPerEpoch*(idx+k)+row,col);B(rowsPerEpoch*i+row,col)=static_cast<Double>(value);}
        else
          for(UInt k=0;k<count;k++)for(UInt row=0;row<rowsPerEpoch;row++)for(UInt col=0;col<A.columns();col++)
            B(rowsPerEpoch*(idx+k)+row,col)+=static_cast<Double>(weights[k]*A(rowsPerEpoch*i+row,col));
        continue;
      }

"""
        if text.count(anchor)!=1:
            raise ValueError("Stable interpolation coefficient anchor mismatch")
        text=text.replace(anchor,block+anchor,1)
    path.write_text(text)


def _stable_measurement_arithmetic(source):
    """Preserve native equations while removing avoidable clock cancellation."""
    shutil.copyfile(Path(__file__).with_name("gnssRangeResidual.h"),source/"misc/orbitPoc/gnssRangeResidual.h")
    shutil.copyfile(Path(__file__).with_name("twofoldGeometry.h"),source/"misc/orbitPoc/twofoldGeometry.h")
    marker="ORBIT_POC_STABLE_GNSS_CLOCK_RANGE_V31"
    path=source/"gnss/gnssObservation.cpp"
    text=path.read_text()
    if marker not in text:
        anchor="        l(i) -= r12;"
        if text.count(anchor)!=1:
            raise ValueError("Stable GNSS range residual anchor mismatch")
        text=text.replace(anchor,"""        l(i) = orbitPocQr::enabled() ? orbitPocQr::stableRangeResidual(l(i),posRecv,posTrans,velocityTrans,receiver->clockError(idEpoch),transmitter->clockError(idEpoch),transmitter->scaleFactor(idEpoch)) : l(i)-r12;""",1)
        path.write_text('// '+marker+'\n#include "misc/orbitPoc/gnssRangeResidual.h"\n'+text)
    path=source/"gnss/gnssReceiver.h"
    text=path.read_text()
    if marker not in text:
        anchor="Time timeCorrected(UInt idEpoch) const {return times.at(idEpoch) - seconds2time(clockError(idEpoch));}"
        if text.count(anchor)!=1:
            raise ValueError("Stable receiver clock time anchor mismatch")
        text=text.replace(anchor,"""Time timeCorrected(UInt idEpoch) const
  {
    const char *prefix=std::getenv("ORBIT_POC_NUMERICS_QR_PREFIX");
    return prefix&&*prefix ? orbitPocQr::stableReceiverTime(times.at(idEpoch),clockError(idEpoch)) : times.at(idEpoch)-seconds2time(clockError(idEpoch));
  }""",1)
        path.write_text('// '+marker+'\n#include <cstdlib>\n#include "misc/orbitPoc/gnssRangeResidual.h"\n'+text)


def apply(root):
    source = Path(root) / "source"
    from positionRemainder import require_install_state
    require_install_state(source)  # reject an old representation before any write
    _continuous_interpolation(source)
    _stable_measurement_arithmetic(source)
    from relativeQueryInterpolation import apply as relative_query_interpolation
    relative_query_interpolation(source)
    from positionRemainder import apply as position_remainder
    position_remainder(source)
    shutil.copyfile(Path(__file__).with_name("scaledRowQr.h"), source / "misc/orbitPoc/scaledRowQr.h")
    shutil.copyfile(Path(__file__).with_name("artifactReceipt.h"), source / "misc/orbitPoc/artifactReceipt.h")
    wrapper = source / "external/lapack/lapackWrapper.f"
    wrapper_text = wrapper.read_text()
    if "ORBIT_POC_TRIANGULAR_QR_V31" not in wrapper_text:
        wrapper.write_text(wrapper_text + "\n" + Path(__file__).with_name("triangularQrWrapper.f").read_text())
    design = source / "gnss/gnssDesignMatrix.cpp"
    old = "    if(orbitPocLinearTrace().enabled())\n      for(UInt r=0;r<l.rows();r++)"
    patch(design, [(old, '''    if(orbitPocRowQr().enabled())
    {
      for(UInt r=0;r<l.rows();r++)
      {
        std::vector<UInt> indices; std::vector<Double> values;
        for(UInt block : A.indexUsedBlock)
          for(UInt part=0;part<A.indexUsedParameter[block].size();part++)
            for(UInt c=0;c<A.countUsedParameter[block][part];c++)
            {
              const UInt column=A.indexUsedParameter[block][part]+c;
              const Double value=A.A(A.row+r,A.blockIndices[block]+column);
              if(value!=0) {indices.push_back(normals.blockIndex(block)+column);values.push_back(value);}
            }
        orbitPocRowQr().addRow(l(r,0),indices,values);
      }
      obsCount+=l.rows();lPl+=quadsum(l);return;
    }
''' + old)])
    processing = source / "gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    patch(processing, [
        ("    if(orbitPocLinearTrace().enabled())\n      orbitPocLinearTrace().begin", "    if(orbitPocRowQr().enabled())\n    {\n      for(const auto &noise:receiverNoiseModels) if(noise.arOrder) throw(Exception(\"v3.1 QR does not support time-correlated observation noise\"));\n      orbitPocRowQr().begin(normalEquationInfo);\n    }\n    if(orbitPocLinearTrace().enabled())\n      orbitPocLinearTrace().begin"),
        ("    UInt blockStart = 0; // first block, which is not regularized and reduced", "    UInt qrFirst=0;\n    UInt blockStart = 0; // first block, which is not regularized and reduced"),
        ("      gnss->constraintsEpoch(normalEquationInfo, idEpoch, normals, n, lPl(0), obsCount);", "      if(orbitPocRowQr().enabled())\n      {\n        const UInt count=normalEquationInfo.blockCountEpoch(idEpoch);\n        orbitPocRowQr().beginEpoch(idEpoch,normalEquationInfo.blockIndex(qrFirst),normalEquationInfo.blockIndex(qrFirst+count)-normalEquationInfo.blockIndex(qrFirst));\n        qrFirst+=count;\n        orbitPocRowQr().context(\"epoch_constraint\");\n      }\n      gnss->constraintsEpoch(normalEquationInfo, idEpoch, normals, n, lPl(0), obsCount);"),
        ("      // loop over all receivers\n      if(!constraintsOnly)", "      if(orbitPocRowQr().enabled())orbitPocRowQr().context(\"weighted_observation\");\n      // loop over all receivers\n      if(!constraintsOnly)"),
        ("      // perform following steps not every epoch", "      if(orbitPocRowQr().enabled()) {orbitPocRowQr().finishEpoch();continue;}\n\n      // perform following steps not every epoch"),
        ("    gnss->constraints(normalEquationInfo, normals, n, lPl(0), obsCount);", "    gnss->constraints(normalEquationInfo, normals, n, lPl(0), obsCount);\n    if(orbitPocRowQr().enabled())\n    {\n      for(UInt i=0;i<normals.blockCount();i++)for(UInt j=i;j<normals.blockCount();j++)\n        if(normals.isBlockUsed(i,j)) throw(Exception(\"Unsupported constraint bypassed v3.1 original weighted rows\"));\n      orbitPocRowQr().finish();\n    }"),
        ("    // setup normal equations\n    const Bool solveEpochParameters", '''    if(orbitPocRowQr().enabled())
    {
      if(searchInteger || computeWeights || adjustSigma0) throw(Exception("v3.1 QR requires float ambiguities and fixed weights"));
      buildNormals(FALSE,FALSE);
      const std::string mode=orbitPocQr::env("ORBIT_POC_NUMERICS_MODE","step");
      if(mode!="step"&&mode!="profile_step"&&mode!="linearize"&&mode!="profile"&&mode!="covariance")throw(Exception("Unknown v3.1 QR mode"));
      const Double lambda=std::stod(orbitPocQr::env("ORBIT_POC_NUMERICS_LAMBDA","0"));
      const Vector undamped=orbitPocRowQr().solve();
      const Vector profiled=orbitPocRowQr().solve(0,TRUE);
      const Vector x=(mode=="profile_step"||mode=="profile")?profiled:orbitPocRowQr().solve(lambda);
      orbitPocRowQr().writeDiagnostics(undamped,x,lambda);
      orbitPocRowQr().writeProfileCost(profiled);
      if(mode=="linearize"||mode=="profile"||mode=="covariance")
      {
        // Export the actual current residual. Redundancy was not estimated by
        // this path; NaN is explicit rather than stale preprocessing values.
        for(UInt epoch:normalEquationInfo.idEpochs)
          for(UInt recv=0;recv<gnss->receivers.size();recv++)
            if(normalEquationInfo.estimateReceiver.at(recv)&&gnss->receivers.at(recv)->isMyRank())
              for(UInt trans=0;trans<gnss->receivers.at(recv)->idTransmitterSize(epoch);trans++)
              {
                GnssObservationEquation eqn;
                if(gnss->basicObservationEquations(normalEquationInfo,recv,trans,epoch,eqn))
                  eqn.receiver->observation(trans,epoch)->setHomogenizedResiduals(eqn.types,eqn.l.row(0,eqn.types.size()),Vector(eqn.types.size(),std::numeric_limits<Double>::quiet_NaN()));
              }
        return 0.;
      }
      // Recover per-observation ionosphere conditionally before the shared
      // GNSS update. Observation support, weights and ambiguity arcs stay fixed.
      GnssDesignMatrix A(normalEquationInfo);
      Double maximumIonosphereChange=0.;
      for(UInt epoch:normalEquationInfo.idEpochs)
        for(UInt recv=0;recv<gnss->receivers.size();recv++)
          if(normalEquationInfo.estimateReceiver.at(recv)&&gnss->receivers.at(recv)->isMyRank())
            for(UInt trans=0;trans<gnss->receivers.at(recv)->idTransmitterSize(epoch);trans++)
            {
              GnssObservationEquation eqn;
              if(!gnss->basicObservationEquations(normalEquationInfo,recv,trans,epoch,eqn)||!eqn.B.size())continue;
              A.init(eqn.l.rows());gnss->designMatrix(normalEquationInfo,eqn,A);
              const Vector local=orbitPocRowQr().recoverGroup(recv,trans,epoch,eqn.B,Vector(eqn.l-A.mult(x)));
              const Vector effect=eqn.B*local;
              for(UInt i=0;i<std::min(effect.rows(),eqn.sigma.rows());i++)maximumIonosphereChange=std::max(maximumIonosphereChange,std::fabs(effect(i)*eqn.sigma(i)));
              eqn.receiver->observation(trans,epoch)->updateParameter(local);
            }
      return std::max(maximumIonosphereChange,gnss->updateParameter(normalEquationInfo,x,Matrix()));
    }
    // setup normal equations
    const Bool solveEpochParameters'''),
    ])
    patch(source / "gnss/gnssObservation.cpp", [
        ("    const Vector tau = QR_decomposition(B);", "    Matrix orbitPocOriginalB;\n    if(orbitPocQr::enabled()) {orbitPocQr::requireRank(B,\"per-observation ionosphere\");orbitPocOriginalB=B;}\n    const Vector tau = QR_decomposition(B);\n    if(orbitPocQr::enabled()) orbitPocRowQr().retainGroup(receiver->idRecv(),transmitter->idTrans(),idEpoch,orbitPocOriginalB,B,tau,l);")])
    _original_objective_hook(source / "gnss/gnssObservation.cpp")
    patch(source / "gnss/gnssParametrization/gnssParametrizationConstraints.h", [
        ("    const Double weight = 1./std::pow(sigma, 2);", "    if(orbitPocQr::enabled())\n    {\n      if(relativeToApriori) throw(Exception(\"v3.1 Gaussian constraints must penalize full parameters\"));\n      orbitPocRowQr().addPulseReference(normalEquationInfo.parameterNames(),x0);\n    }\n    const Double weight = 1./std::pow(sigma, 2);"),
        ("        orbitPocLinearTrace().addRow((bias-x0.at(index))/sigma,{index},{1./sigma});", "        if(orbitPocRowQr().enabled())\n        {orbitPocRowQr().context(name);orbitPocRowQr().addRow((bias-x0.at(index))/sigma,{index},{1./sigma});lPl+=std::pow((bias-x0.at(index))/sigma,2);obsCount++;count++;continue;}\n        orbitPocLinearTrace().addRow((bias-x0.at(index))/sigma,{index},{1./sigma});")])
    patch(source / "gnss/gnssParametrization/gnssParametrizationLogDensityOu.h", [
        ("      orbitPocLinearTrace().addRow(residual,std::vector<UInt>(ids,ids+count),std::vector<Double>(coeff,coeff+count));", "      if(orbitPocRowQr().enabled())\n      {orbitPocRowQr().context(name);orbitPocRowQr().addRow(residual,std::vector<UInt>(ids,ids+count),std::vector<Double>(coeff,coeff+count));lPl+=residual*residual;obsCount++;return;}\n      orbitPocLinearTrace().addRow(residual,std::vector<UInt>(ids,ids+count),std::vector<Double>(coeff,coeff+count));")])
    patch(source / "gnss/gnssProcessingStep/gnssProcessingStepComputeCovarianceMatrix.h", [
        ("    logStatus<<\"cholesky\"<<Log::endl;", "    if(orbitPocRowQr().enabled())\n    {\n      orbitPocRowQr().covariance(state.normals);\n      state.gnss->updateCovariance(state.normalEquationInfo,state.normals);\n      return;\n    }\n    logStatus<<\"cholesky\"<<Log::endl;")])
    # This path estimates clocks with a temporal process, which violates the
    # epoch-local elimination contract. Reject explicitly before constructing it.
    patch(source / "gnss/gnssParametrization/gnssParametrization.cpp", [
        ("    std::string type;", "    std::string type;"),
        ("    while(readConfigChoice(config, name, type, Config::OPTIONAL, \"\", \"parametrization of GNSS observations\"))\n    {", "    while(readConfigChoice(config, name, type, Config::OPTIONAL, \"\", \"parametrization of GNSS observations\"))\n    {\n      if(orbitPocQr::enabled() && type==\"clocksModel\") throw(Exception(\"v3.1 QR does not support time-coupled clocks\"));")])
    # Restore upstream independent-epoch VTEC registration. Joint epoch QR
    # eliminates VTEC and clocks together and retains conditional recovery.
    vtec = source / "gnss/gnssParametrization/gnssParametrizationIonosphereVTEC.cpp"
    text = vtec.read_text()
    native_registration = 'normalEquationInfo.parameterNamesEpochReceiver(idEpoch, idRecv, {ParameterName(recv->name(), "VTEC", "", gnss->times.at(idEpoch))})'
    old_registration = '(orbitPocQr::enabled() ? normalEquationInfo.parameterNamesReceiver(idRecv, {ParameterName(recv->name(), "VTEC", "", gnss->times.at(idEpoch))}) : ' + native_registration + ')'
    if old_registration in text:
        vtec.write_text(text.replace(old_registration, native_registration))
    elif native_registration not in text:
        raise ValueError("Native epoch VTEC registration anchor mismatch")
    _datums(source)
    # Float nuisance trials must preserve the actual observation values. The
    # native integer recentering is algebraically neutral but rounds large phase
    # values when a float ambiguity crosses a half-integer, making F discontinuous.
    ambiguity = source / "gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp"
    text = ambiguity.read_text()
    if "ORBIT_POC_FIXED_FLOAT_OBSERVATIONS_V31" not in text:
        old = "      if(ambi->value.size())"
        if text.count(old) != 1:
            raise ValueError("Float ambiguity recentering patch anchor mismatch")
        text = text.replace(old, "      if(ambi->value.size() && !orbitPocQr::enabled()) // ORBIT_POC_FIXED_FLOAT_OBSERVATIONS_V31")
        ambiguity.write_text(text)
    _nuisance_line_search(source)
    program = source / "programs/simulation/orbitPocQrSolve.cpp"
    shutil.copyfile(Path(__file__).with_name("orbitPocQrSolve.cpp"), program)
    listing = source / "sourcesCXX.txt"
    text = listing.read_text()
    if "programs/simulation/orbitPocQrSolve.cpp" not in text:
        listing.write_text(text + "\nlist(APPEND SOURCES programs/simulation/orbitPocQrSolve.cpp)\n")


def _nuisance_line_search(source):
    shutil.copyfile(Path(__file__).with_name("nuisanceLineSearch.h"), source / "misc/orbitPoc/nuisanceLineSearch.h")
    path = source / "gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    text = path.read_text()
    marker = "ORBIT_POC_TRANSACTIONAL_NUISANCE_V31"
    prefix = "// " + marker + '\n#include "misc/orbitPoc/nuisanceLineSearch.h"\n'
    if text.startswith(prefix):
        text = text[len(prefix):]
    start = text.index("      // Cache the complete undamped joint nuisance correction before any" if marker in path.read_text() else "      // Recover per-observation ionosphere conditionally before the shared")
    end = text.index("\n    }\n    // setup normal equations", start)
    text = text[:start] + r'''      // Cache the complete undamped joint nuisance correction before any
      // trial. Local STEC and retained updates are scaled together.
      struct LocalUpdate {GnssObservation *observation;Vector delta;Double influence;};
      std::vector<LocalUpdate> localUpdates;
      Double maximumJointObservationInfluence=0;
      GnssDesignMatrix A(normalEquationInfo);
      for(UInt epoch:normalEquationInfo.idEpochs)
        for(UInt recv=0;recv<gnss->receivers.size();recv++)
          if(normalEquationInfo.estimateReceiver.at(recv)&&gnss->receivers.at(recv)->isMyRank())
            for(UInt trans=0;trans<gnss->receivers.at(recv)->idTransmitterSize(epoch);trans++)
            {
              GnssObservationEquation eqn;
              if(!gnss->basicObservationEquations(normalEquationInfo,recv,trans,epoch,eqn))continue;
              A.init(eqn.l.rows());gnss->designMatrix(normalEquationInfo,eqn,A);
              Vector joint=A.mult(x);
              const Vector local=eqn.B.size()?orbitPocRowQr().recoverGroup(recv,trans,epoch,eqn.B,Vector(eqn.l-joint)):Vector();
              if(eqn.B.size())joint+=eqn.B*local;
              for(UInt i=0;i<std::min(joint.rows(),eqn.sigma.rows());i++)maximumJointObservationInfluence=std::max(maximumJointObservationInfluence,std::fabs(joint(i)*eqn.sigma(i)));
              if(!eqn.B.size())continue;
              const Vector effect=eqn.B*local;Double influence=0;
              for(UInt i=0;i<std::min(effect.rows(),eqn.sigma.rows());i++)influence=std::max(influence,std::fabs(effect(i)*eqn.sigma(i)));
              localUpdates.push_back({eqn.receiver->observation(trans,epoch),local,influence});
            }
      auto observationFingerprint=[&]()
      {
        std::uint64_t digest=14695981039346656037ULL;
        auto mix=[&](const void *pointer,std::size_t bytes){const auto data=static_cast<const unsigned char*>(pointer);for(std::size_t i=0;i<bytes;i++){digest^=data[i];digest*=1099511628211ULL;}};
        for(UInt epoch:normalEquationInfo.idEpochs)
          for(UInt recv=0;recv<gnss->receivers.size();recv++)
            if(normalEquationInfo.estimateReceiver.at(recv)&&gnss->receivers.at(recv)->isMyRank())
              for(UInt trans=0;trans<gnss->receivers.at(recv)->idTransmitterSize(epoch);trans++)
                if(const auto observation=gnss->receivers.at(recv)->observation(trans,epoch))
                {
                  mix(&epoch,sizeof(epoch));mix(&recv,sizeof(recv));mix(&trans,sizeof(trans));
                  for(UInt i=0;i<observation->size();i++)
                  {const auto &value=observation->at(i);const auto type=value.type.str();mix(type.data(),type.size());mix(&value.observation,sizeof(Double));mix(&value.sigma,sizeof(Double));mix(&value.sigma0,sizeof(Double));}
                }
        return digest;
      };
      const auto fixedObservations=observationFingerprint();std::uint64_t ambiguityCrossings=0;
      struct ReceiverBefore {GnssReceiver *receiver;UInt epoch;Time time;Vector3d position;};
      std::vector<ReceiverBefore> receiversBefore;
      for(const auto &receiver:gnss->receivers)if(receiver->isMyRank())for(UInt epoch:normalEquationInfo.idEpochs)
        if(receiver->useable(epoch))receiversBefore.push_back({receiver.get(),epoch,receiver->timeCorrected(epoch),receiver->pos.at(epoch)});
      Double receiverPositionChange=0,receiverTimeChange=0;std::uint64_t changedReceiverTimes=0;
      const Vector beforeParameters=gnss->aprioriParameter(normalEquationInfo);const auto parameterNames=normalEquationInfo.parameterNames();
      auto apply=[&](Double alpha)
      {
        Double maximum=std::fabs(alpha)*maximumJointObservationInfluence;ambiguityCrossings=0;
        for(const auto &update:localUpdates){update.observation->updateParameter(alpha*update.delta);maximum=std::max(maximum,std::fabs(alpha)*update.influence);}
        maximum=std::max(maximum,gnss->updateParameter(normalEquationInfo,alpha*x,Matrix()));
        receiverPositionChange=receiverTimeChange=0;changedReceiverTimes=0;
        for(const auto &entry:receiversBefore)
        {
          const auto after=entry.receiver->timeCorrected(entry.epoch);
          const Double dt=((static_cast<long double>(after.mjdInt())-entry.time.mjdInt())+(static_cast<long double>(after.mjdMod())-entry.time.mjdMod()))*86400.L;
          changedReceiverTimes+=(dt!=0);receiverTimeChange=std::max(receiverTimeChange,std::fabs(dt));
          receiverPositionChange=std::max(receiverPositionChange,(entry.receiver->pos.at(entry.epoch)-entry.position).r());
        }
        if(observationFingerprint()!=fixedObservations)throw(Exception("Native nuisance update changed fixed observations or weights"));
        const Vector afterParameters=gnss->aprioriParameter(normalEquationInfo);
        if(alpha==0)for(UInt i=0;i<beforeParameters.rows();i++)
          if(afterParameters(i)!=beforeParameters(i))throw(Exception("Fixed-parameter nuisance audit changed a full native coordinate"));
        for(UInt i=0;i<parameterNames.size();i++)if(parameterNames[i].type.find("ambiguity")==0)
        {
          const Double expected=beforeParameters(i)+alpha*x(i);
          if(std::fabs(afterParameters(i)-expected)>8*std::numeric_limits<Double>::epsilon()*std::max({1.,std::fabs(beforeParameters(i)),std::fabs(expected)}))throw(Exception("Native float ambiguity coordinate changed during update"));
          if(std::round(beforeParameters(i))!=std::round(expected))ambiguityCrossings++;
        }
        return maximum;
      };
      if(mode!="profile_step")return apply(1.);
      const Double before=orbitPocRowQr().rawCost(),prediction=orbitPocRowQr().lastNuisanceReduction();
      const Double threshold=std::stod(orbitPocQr::env("ORBIT_POC_NUMERICS_NUISANCE_THRESHOLD","1e-8"));
      const auto signature=orbitPocRowQr().supportSignature();const auto rows=orbitPocRowQr().weightedRowCount();
      const auto stem=orbitPocRowQr().artifactStem();
      std::ofstream nativeTimes(stem+".receiver_times.tsv");nativeTimes<<std::setprecision(17)<<"receiver\tepoch\tnative_clock_seconds\tnominal_day\tnominal_fraction\tcorrected_day\tcorrected_fraction\n";
      for(const auto &entry:receiversBefore)
      {
        const auto nominal=entry.receiver->times.at(entry.epoch);
        nativeTimes<<entry.receiver->idRecv()<<'\t'<<entry.epoch<<'\t'<<entry.receiver->clockError(entry.epoch)<<'\t'<<nominal.mjdInt()<<'\t'<<nominal.mjdMod()<<'\t'<<entry.time.mjdInt()<<'\t'<<entry.time.mjdMod()<<'\n';
      }
      nativeTimes.close();if(!nativeTimes)throw(Exception("Cannot record native receiver-time coordinates"));
      auto evaluate=[&](Double alpha)
      {
        orbitPocRowQr().prepareCostOnly();orbitPocQr::NuisanceTrial trial;
        trial.change=apply(alpha);trial.ambiguityBoundaryCrossings=ambiguityCrossings;trial.observationSignature=fixedObservations;buildNormals(FALSE,FALSE);
        trial.receiverPositionChange=receiverPositionChange;trial.receiverTimeChange=receiverTimeChange;trial.changedReceiverTimes=changedReceiverTimes;
        trial.largestRawResidual=orbitPocRowQr().largestRawResidualChange();
        trial.cost=orbitPocRowQr().rawCost();trial.reduction=orbitPocRowQr().actualObjectiveReduction();trial.support=orbitPocRowQr().supportSignature();trial.rows=orbitPocRowQr().weightedRowCount();
        return trial;
      };
      auto audit=[&](UInt mode)
      {setenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE",std::to_string(mode).c_str(),1);return evaluate(0.);};
      const auto search=orbitPocQr::searchNuisance(before,prediction,threshold,signature,rows,evaluate,audit);
      orbitPocQr::lastNuisanceSearch()=search;
      orbitPocQr::writeNuisanceSearch(stem+".nuisance_line_search.json",search,before,prediction);
      if(search.zeroUpdateReplay.status || search.zeroUpdateReplay.reduction!=0 || search.zeroUpdateReplay.change!=0)
        throw(Exception("Nuisance zero-update replay changed the objective or cached state"));
      if(search.stationary||search.floorLimited)return search.undampedChange;
      if(!search.accepted)throw(Exception("Nuisance line search rejected every trial without undamped stationarity"));
      apply(search.alpha);orbitPocRowQr().expectObjective(search.trials.back().cost);
      return search.undampedChange;
''' + text[end:]
    text = text.replace("    if(orbitPocLinearTrace().enabled())\n      orbitPocLinearTrace().begin", "    if(!orbitPocRowQr().isCostOnly() && orbitPocLinearTrace().enabled())\n      orbitPocLinearTrace().begin")
    path.write_text(prefix + text)


def _datums(source):
    """Replace datum normal matrices with original-row orthogonal/SVD stages."""
    code=source / "gnss/gnssParametrization/gnssParametrizationCodeBiases.cpp"
    text=code.read_text()
    if MARKER not in text:
        # Keep the old path byte-for-byte for compatibility; collect rows in
        # parallel and branch before any legacy factorization or normal update.
        text=text.replace("Matrix N(1+T.columns(), Matrix::SYMMETRIC);", "Matrix N(1+T.columns(), Matrix::SYMMETRIC);\n        std::vector<Matrix> qrRows;")
        text=text.replace("Matrix N(parameterCount, Matrix::SYMMETRIC);", "Matrix N(parameterCount, Matrix::SYMMETRIC);\n        std::vector<Matrix> qrRows;")
        text=text.replace("rankKUpdate(1., A, N);", "if(orbitPocQr::enabled()) qrRows.emplace_back(A); else rankKUpdate(1., A, N);")
        # Both receiver/transmitter clock-elimination stages have identical text
        # with different indentation. Operate line-wise between comments.
        import re
        text,n=re.subn(r"(?P<indent> +)// eliminate clock\n(?P<body>.*?para->Bias = T \* nullSpace\(N, TRUE\);)",lambda m:m['indent']+'''if(orbitPocQr::enabled())
        {
          const Matrix rows=orbitPocQr::concatenate(qrRows,N.columns());
          std::vector<UInt> keep(N.columns()-1);std::iota(keep.begin(),keep.end(),1);
          para->Bias=T*orbitPocQr::basis(orbitPocQr::project(rows,{0},keep),TRUE);
          orbitPocQr::recordDatum("codeBias",para->Bias);
        }
        else
        {
'''+m['indent']+'// eliminate clock\n'+m['body']+'\n        }',text,flags=re.S)
        if n!=2:raise ValueError(f"Code bias clock datum anchors: {n}")
        start=text.index("          // add zero mean of clocks and eliminate clocks")
        end=text.index("          zeroMeanDesign = nullSpace(N, FALSE).trans();",start)+len("          zeroMeanDesign = nullSpace(N, FALSE).trans();")
        old=text[start:end]
        text=text[:start]+'''          if(orbitPocQr::enabled())
          {
            Matrix rows=orbitPocQr::concatenate(qrRows,parameterCount);
            std::vector<UInt> local(parameterCount-idxClocks),keep(idxClocks);
            std::iota(local.begin(),local.end(),idxClocks);std::iota(keep.begin(),keep.end(),0);
            zeroMeanDesign=orbitPocQr::basis(orbitPocQr::project(rows,local,keep),FALSE).trans();
            orbitPocQr::recordDatum("codeBiasZeroMean",zeroMeanDesign);
          }
          else
          {
'''+old+'\n          }'+text[end:]
        text=text.replace("GnssDesignMatrix::accumulateNormals(A, Vector(zeroMeanDesign.rows()), normals, n, lPl, obsCount);", "if(orbitPocQr::enabled()) orbitPocRowQr().context(\"code_bias_full_constraint\");\n        GnssDesignMatrix::accumulateNormals(A, orbitPocQr::enabled() ? Vector(-A.mult(gnss->aprioriParameter(normalEquationInfo))) : Vector(zeroMeanDesign.rows()), normals, n, lPl, obsCount);")
        code.write_text('// '+MARKER+'\n'+INCLUDE+text)
    tec=source / "gnss/gnssParametrization/gnssParametrizationTecBiases.cpp"
    text=tec.read_text()
    if MARKER not in text:
        import re
        text=re.sub(r"(Matrix N\([^;]+, Matrix::SYMMETRIC\);)",r"\1\n        std::vector<Matrix> qrRows;",text)
        text=text.replace("rankKUpdate(1., A, N);", "if(orbitPocQr::enabled()) qrRows.emplace_back(A); else rankKUpdate(1., A, N);")
        pattern=r"(?P<indent> +)// determine eigen values\n(?P<body>.*?)(?P<target>para->Bias = N.column\(0, countZeros\);|para->Bias = T \* N.column\(0, countZeros\);|zeroMeanDesign = N.column\(0, countZeros\).trans\(\);)"
        def replacement(m):
            target=m['target']
            expr='orbitPocQr::basis(orbitPocQr::concatenate(qrRows,N.columns()),FALSE)'
            new=('para->Bias = T * '+expr+';' if '* N.' in target else 'para->Bias = '+expr+';' if 'para->Bias' in target else 'zeroMeanDesign = '+expr+'.trans();')
            value='para->Bias' if 'para->Bias' in target else 'zeroMeanDesign'
            return m['indent']+'if(orbitPocQr::enabled())\n        {\n          '+new+'\n          orbitPocQr::recordDatum("tecBias",'+value+');\n        }\n        else\n        {\n'+m['indent']+'// determine eigen values\n'+m['body']+target+'\n        }'
        text,n=re.subn(pattern,replacement,text,flags=re.S)
        if n!=3:raise ValueError(f"TEC datum anchors {n}")
        text=text.replace("GnssDesignMatrix::accumulateNormals(A, Vector(zeroMeanDesign.rows()), normals, n, lPl, obsCount);", "if(orbitPocQr::enabled()) orbitPocRowQr().context(\"tec_bias_full_constraint\");\n        GnssDesignMatrix::accumulateNormals(A, orbitPocQr::enabled() ? Vector(-A.mult(gnss->aprioriParameter(normalEquationInfo))) : Vector(zeroMeanDesign.rows()), normals, n, lPl, obsCount);")
        tec.write_text('// '+MARKER+'\n'+INCLUDE+text)
    amb=source / "gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp"
    text=amb.read_text()
    if MARKER not in text:
        start=text.index("        // block normal matrix (upper triangle)")
        end=text.index("      } // if(isMaster)",start)
        old=text[start:end]
        text=text[:start]+'''        if(orbitPocQr::enabled())
        {
          const UInt nr=idTypeRecv.size(),nt=idTypeTrans.size(),na=idTypeAmbi.size();
          UInt m=0;for(const auto &info:ambiguityInfos)m+=info.typesFreqSys.size();
          Matrix rows(m,nr+nt+na);UInt row=0;
          for(const auto &info:ambiguityInfos)
            for(UInt i=0;i<info.typesFreqSys.size();i++,row++)
            {
              const Double w=std::sqrt(info.idEpochEnd-info.idEpochStart+1.);
              if(info.idxRecv.at(i)!=NULLINDEX)rows(row,info.idxRecv.at(i))=w;
              if(info.idxTrans!=NULLINDEX)rows(row,nr+info.idxTrans)=w;
              if(info.idxAmbi!=NULLINDEX)rows(row,nr+nt+info.idxAmbi)=w;
            }
          const Vector selected=orbitPocQr::selectDatum(rows,nr,nt);
          isTrans=Vector(selected.row(nr,nt));isAmbi=Vector(selected.row(nr+nt,na));
          orbitPocQr::recordDatum("ambiguitySelection",selected);
        }
        else
        {
'''+old+'        }\n'+text[end:]
        amb.write_text('// '+MARKER+'\n'+INCLUDE+text)

    # Biases share a physical signalBias array with phase and other bias blocks.
    # Reprojecting that combined array after updates is not a parameter read:
    # overlapping bases would create spurious cross derivatives in the priors.
    coordinate_marker = "ORBIT_POC_FULL_BIAS_COORDINATES_V31"
    for stem_name in ("gnssParametrizationCodeBiases", "gnssParametrizationTecBiases"):
        header = source / "gnss/gnssParametrization" / (stem_name + ".h")
        text = header.read_text()
        if coordinate_marker not in text:
            anchor = "    Matrix             Bias;"
            if text.count(anchor) != 1:
                raise ValueError(f"Bias coordinate member anchor mismatch: {header}")
            text = text.replace(anchor, anchor + "\n    mutable Vector     orbitPocFullCoordinates;", 1)
            header.write_text("// " + coordinate_marker + "\n" + text)
        path = source / "gnss/gnssParametrization" / (stem_name + ".cpp")
        text = path.read_text()
        if coordinate_marker not in text:
            anchor = "        para->index = GnssParameterIndex();"
            if text.count(anchor) != 2:
                raise ValueError(f"Bias coordinate initialization anchor mismatch: {path}")
            text = text.replace(anchor, "        {para->index = GnssParameterIndex(); if(orbitPocQr::enabled())para->orbitPocFullCoordinates=Vector();}")
            for platform in ("trans", "recv"):
                anchor = f"leastSquares(Matrix(para->Bias), Vector(para->{platform}->signalBias.biases))"
                replacement = f"(orbitPocQr::enabled() ? Vector(orbitPocQr::fullCoordinates(para->orbitPocFullCoordinates,para->Bias,Vector(para->{platform}->signalBias.biases))) : {anchor})"
                if text.count(anchor) != 1:
                    raise ValueError(f"Bias coordinate read anchor mismatch: {path}")
                text = text.replace(anchor, replacement, 1)
            anchor = "        const Vector dBias = para->Bias * x.row(normalEquationInfo.index(para->index), para->Bias.columns());"
            if text.count(anchor) != 2:
                raise ValueError(f"Bias coordinate update anchor mismatch: {path}")
            text = text.replace(anchor, "        if(orbitPocQr::enabled()) orbitPocQr::accumulateCoordinates(para->orbitPocFullCoordinates,x.row(normalEquationInfo.index(para->index),para->Bias.columns()));\n" + anchor)
            path.write_text("// " + coordinate_marker + "\n" + text)
    path = source / "gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    text = path.read_text()
    if coordinate_marker not in text:
        anchor = "      orbitPocRowQr().begin(normalEquationInfo);"
        if text.count(anchor) != 1:
            raise ValueError("Initial full-bias coordinate capture anchor mismatch")
        text = text.replace(anchor, anchor + "\n      orbitPocRowQr().recordBiasCoordinates(gnss->aprioriParameter(normalEquationInfo)); // capture all blocks before any shared-array update", 1)
        path.write_text("// " + coordinate_marker + "\n" + text)


if __name__ == "__main__":
    import sys
    apply(sys.argv[1])
