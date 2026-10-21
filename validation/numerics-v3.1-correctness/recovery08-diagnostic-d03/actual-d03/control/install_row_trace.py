#!/usr/bin/env python3
"""D03 diagnostic-only taps after the frozen source04 candidate07 extension.

All writes target a new generated GROOPS tree, never the frozen extension.
The original numerical statements remain intact except value-preserving operand
taps and an explicitly incomplete stop before the fifth QR generation.
"""
import argparse,hashlib,json,re
from pathlib import Path
MARKER='// ORBIT_POC_DIAGNOSTIC_D03_V1'
INCLUDE='#include "misc/orbitPoc/nuisanceArithmeticTrace.h"\n'

def once(text,old,new):
    if text.count(old)!=1:raise ValueError('Expected exactly one D03 anchor: '+repr(old[:100]))
    return text.replace(old,new,1)

def patched_files(source):
    changes={}
    def read(name):
        text=(source/name).read_text()
        if MARKER in text:raise ValueError('D03 refuses an already instrumented tree')
        return text
    def save(name,text):changes[name]=MARKER+'\n'+INCLUDE+text
    name='misc/orbitPoc/scaledRowQr.h';text=read(name)
    anchor='  void begin(const GnssNormalEquationInfo &info)\n  {'
    text=once(text,anchor,anchor+'\n    if(!costOnly)orbitPocD03::guard(sequence,orbitPocQr::env("ORBIT_POC_NUMERICS_QR_PREFIX"));')
    anchor='    previousStem=stem;stem=orbitPocQr::env("ORBIT_POC_NUMERICS_QR_PREFIX")+"."+std::to_string(++sequence);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::generation(stem,sequence);')
    anchor='    preciseObservationResiduals.emplace(key,precise);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::Equation traceOriginal(receiver,transmitter,epoch);\n    orbitPocD03::matrix("retained_original_native",target);\n    orbitPocD03::precise("retained_original_precise",precise);')
    anchor='    if(contextName!="weighted_observation"||observationResiduals.empty())objectiveResiduals.push_back(rhs);'
    text=once(text,anchor,anchor+'\n    if(contextName!="weighted_observation"||observationResiduals.empty())\n    {\n      orbitPocD03::Equation traceConstraint(~0ULL,~0ULL,currentEpoch);\n      orbitPocD03::text("constraint_context",contextName,sourceRows);\n      orbitPocD03::scalar("constraint_original_rhs",rhs,sourceRows);\n      orbitPocD03::sparse("constraint_original_coefficient",sourceRows,ids,values);\n    }')
    save(name,text)

    name='gnss/gnssProcessingStep/gnssProcessingStep.cpp';text=read(name)
    anchor='      // Cache the complete undamped joint nuisance correction before any'
    text=once(text,anchor,'      orbitPocD03::phase("joint");\n'+anchor)
    anchor='              if(!gnss->basicObservationEquations(normalEquationInfo,recv,trans,epoch,eqn))continue;'
    text=once(text,anchor,'              orbitPocD03::Equation traceJoint(recv,trans,epoch);\n'+anchor)
    anchor='              Vector joint=A.mult(x);'
    text=once(text,anchor,anchor+'\n              orbitPocD03::matrix("joint_global_native_influence",joint);\n              orbitPocD03::matrix("joint_local_design",eqn.B);\n              orbitPocD03::matrix("joint_original_native",eqn.l);\n              orbitPocD03::precise("joint_original_precise",eqn.orbitPocPreciseL);')
    anchor='              if(eqn.B.size())joint+=eqn.B*local;'
    text=once(text,anchor,anchor+'\n              orbitPocD03::matrix("joint_local_requested",local);\n              orbitPocD03::matrix("joint_total_native_influence",joint);')
    anchor='              localUpdates.push_back({eqn.receiver->observation(trans,epoch),local,influence});'
    text=once(text,anchor,'              orbitPocD03::registerObservation(eqn.receiver->observation(trans,epoch),recv,trans,epoch);\n'+anchor)
    anchor='      const Vector beforeParameters=gnss->aprioriParameter(normalEquationInfo);const auto parameterNames=normalEquationInfo.parameterNames();'
    text=once(text,anchor,anchor+'\n      orbitPocD03::matrix("parameter_before",beforeParameters);\n      orbitPocD03::matrix("parameter_requested",x);\n      if(orbitPocD03::selected())for(UInt i=0;i<parameterNames.size();i++)orbitPocD03::text("parameter_name",parameterNames[i].str(),i);')
    anchor='      auto apply=[&](Double alpha)\n      {'
    text=once(text,anchor,anchor+'\n        orbitPocD03::trial(alpha);')
    anchor='        const Vector afterParameters=gnss->aprioriParameter(normalEquationInfo);'
    text=once(text,anchor,anchor+'\n        orbitPocD03::matrix("parameter_before",beforeParameters);\n        orbitPocD03::matrix("parameter_requested_unscaled",x);\n        orbitPocD03::matrix("parameter_after",afterParameters);')
    save(name,text)

    name='gnss/gnssDesignMatrix.cpp';text=read(name)
    anchor='        matMult(1., A.slice(row, index, rows, count), x.row(index, count), y);'
    text=once(text,anchor,anchor+'\n        if(orbitPocD03::context().phase=="joint")\n        {\n          orbitPocD03::matrix("joint_global_design",A.slice(row,index,rows,count),index);\n          orbitPocD03::matrix("joint_global_requested_block",x.row(index,count),index);\n        }')
    save(name,text)

    name='gnss/gnssObservation.cpp';text=read(name)
    anchor='    const UInt obsCount = types_.size();'
    text=once(text,anchor,'    orbitPocD03::Equation traceEquation(receiver_.idRecv(),transmitter_.idTrans(),idEpoch_);\n'+anchor)
    anchor='    if(orbitPocPreciseInitialized)orbitPocPreciseL=orbitPocQr::liftPreciseVector(l);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::matrix("observed",l);\n    orbitPocD03::matrix("sigma",sigma);\n    orbitPocD03::scalar("receiver_clock_seconds",receiver->clockError(idEpoch));\n    orbitPocD03::scalar("transmitter_clock_seconds",transmitter->clockError(idEpoch));\n    orbitPocD03::scalar("transmitter_scale",transmitter->scaleFactor(idEpoch));\n    orbitPocD03::scalar("rDotTrans",rDotTrans);orbitPocD03::scalar("rDotRecv",rDotRecv);\n    orbitPocD03::vector3("LOS",k);')
    anchor='          orbitPocPreciseL.at(i)=orbitPocQr::stableRangeResidualExpansion('
    text=once(text,anchor,'          orbitPocD03::context().row=i;\n'+anchor)
    anchor='    receiver->signalComposition(idEpoch, types, typesTransmitted, T);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::matrix("signal_composition",T);')
    anchor='    const Vector receiverCorrection=receiver->antennaVariations('
    text=once(text,anchor,'    orbitPocD03::component("receiver_correction");\n'+anchor)
    anchor='    const Vector transmitterCorrection=transmitter->antennaVariations('
    text=once(text,anchor,'    orbitPocD03::precise("after_receiver_correction",orbitPocPreciseL);\n    orbitPocD03::component("transmitter_correction");\n'+anchor)
    anchor='    if(track && track->ambiguity)\n    {\n      l-=track->ambiguity->ambiguities(types);'
    text=once(text,anchor,'    orbitPocD03::precise("after_transmitter_correction",orbitPocPreciseL);\n    orbitPocD03::component("ambiguity");\n'+anchor)
    anchor='    if(reduceModels)\n    {\n      const Vector before=l;'
    text=once(text,anchor,'    orbitPocD03::precise("after_ambiguity",orbitPocPreciseL);\n    orbitPocD03::component("models");\n'+anchor)
    anchor='    // Homogenize\n'
    text=once(text,anchor,'    orbitPocD03::precise("after_models",orbitPocPreciseL);\n'+anchor)
    anchor='      orbitPocPreciseComplete=TRUE;'
    text=once(text,anchor,anchor+'\n      orbitPocD03::precise("complete_original_precise",orbitPocPreciseL);\n      orbitPocD03::matrix("complete_original_native",l);\n      orbitPocD03::matrix("complete_original_local_design",B);')
    anchor='    STEC  += x(0,0);\n    dSTEC += x(0,0);'
    text=once(text,anchor,'    orbitPocD03::Observation traceLocal(this);\n    orbitPocD03::scalar("local_STEC_before",STEC);orbitPocD03::scalar("local_dSTEC_before",dSTEC);\n    orbitPocD03::scalar("local_STEC_requested",x(0,0));\n'+anchor+'\n    orbitPocD03::scalar("local_STEC_after",STEC);orbitPocD03::scalar("local_dSTEC_after",dSTEC);')
    anchor='    // receiver in celestial reference frame\n'
    text=once(text,anchor,'    orbitPocD03::Equation traceGeometry(receiver.idRecv(),transmitter.idTrans(),idEpoch);\n    orbitPocD03::component("light_time");\n'+anchor)
    anchor='        const long double duration=static_cast<long double>(receiver.clockError(idEpoch))+travel;'
    text=once(text,anchor,'        orbitPocD03::extended("travel_seconds",travel);\n        orbitPocD03::scalar("receiver_clock_seconds",receiver.clockError(idEpoch));\n'+anchor+'\n        orbitPocD03::extended("duration_seconds",duration);')
    anchor='        return orbitPocQr::timeRemainder(receiver.times.at(idEpoch),duration,timeTrans);'
    text=once(text,anchor,'        orbitPocD03::time("nominal_receiver_time",receiver.times.at(idEpoch));\n        orbitPocD03::time("rounded_transmitter_time",timeTrans);\n        return orbitPocD03::extendedOperand("transmitter_time_remainder",orbitPocQr::timeRemainder(receiver.times.at(idEpoch),duration,timeTrans));')
    anchor='      velTrans=transmitter.velocityOffset(timeTrans,remainder);'
    text=once(text,anchor,anchor+'\n      orbitPocD03::vector3("receiver_position_high",posRecv);orbitPocD03::vector3("receiver_position_low",recvLow);\n      orbitPocD03::vector3("transmitter_position_high",posTrans);orbitPocD03::vector3("transmitter_position_low",transLow);\n      orbitPocD03::vector3("transmitter_velocity",velTrans);orbitPocD03::vector3("receiver_velocity",velRecv);')
    save(name,text)

    name='misc/orbitPoc/gnssRangeResidual.h';text=read(name)
    anchor='  return residual;'
    text=once(text,anchor,'  orbitPocD03::pair("range_distance",range,orbitPocD03::context().row);\n  orbitPocD03::pair("range_relativistic_dot",dot,orbitPocD03::context().row);\n  orbitPocD03::extended("range_shapiro",shapiro,orbitPocD03::context().row);\n  orbitPocD03::pair("range_geometric",geometric,orbitPocD03::context().row);\n  orbitPocD03::pair("range_clock",clock,orbitPocD03::context().row);\n  orbitPocD03::pair("range_residual",residual,orbitPocD03::context().row);\n'+anchor)
    anchor='  return geometrySqrt(geometrySquares(x,y,z)).rounded();'
    text=once(text,anchor,'  orbitPocD03::vector3("distance_a_high",a);orbitPocD03::vector3("distance_a_low",aLow);\n  orbitPocD03::vector3("distance_b_high",b);orbitPocD03::vector3("distance_b_low",bLow);\n  return orbitPocD03::pairOperand("distance_before_narrowing",geometrySqrt(geometrySquares(x,y,z))).rounded();')
    save(name,text)

    name='gnss/gnssTransceiver.h';text=read(name)
    anchor='    const Vector bias=signalBias.compute(types);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::array("shared_signal_bias_native",signalBias.biases);\n    orbitPocD03::matrix("signal_bias_operand",bias);')
    anchor='    const Vector pattern=antenna->antennaDef->antennaVariations(azimut,elevation,types,noPatternFoundAction);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::matrix("antenna_pattern_operand",pattern);')
    save(name,text)

    name='gnss/gnssTransmitter.h';text=read(name)
    anchor='    std::vector<long double> low;'
    text=once(text,anchor,'    orbitPocD03::Component traceComponent("transmitter_position_interpolation");\n'+anchor)
    anchor='    return rounded;'
    text=once(text,anchor,'    orbitPocD03::vector3("transmitter_center_rounded",base);orbitPocD03::extendedArray("transmitter_center_low",low);\n    orbitPocD03::vector3("transmitter_antenna_offset",antenna);orbitPocD03::vector3("transmitter_antenna_position",rounded);\n    if(coordinateRemainder)orbitPocD03::vector3("transmitter_antenna_remainder",*coordinateRemainder);\n'+anchor)
    anchor='  {return Vector3d(polynomial.interpolateOffset({time},vel,{remainder}));}'
    text=once(text,anchor,'  {orbitPocD03::Component traceComponent("transmitter_velocity_interpolation");return Vector3d(polynomial.interpolateOffset({time},vel,{remainder}));}')
    save(name,text)

    name='gnss/gnssReceiver.h';text=read(name)
    anchor='    const Vector3d antenna=global2local.at(idEpoch).inverseTransform(offset.at(idEpoch)),rounded=position(idEpoch);'
    text=once(text,anchor,anchor+'\n    orbitPocD03::vector3("receiver_center_high",base);orbitPocD03::vector3("receiver_center_low",low);\n    orbitPocD03::vector3("receiver_antenna_offset",antenna);orbitPocD03::vector3("receiver_antenna_position",rounded);')
    save(name,text)

    name='base/polynomial.cpp';text=read(name)
    anchor='        const auto weights=orbitPocQr::twofoldInterpolationWeights(nodes,derivative,sampling);'
    text=once(text,anchor,anchor+'\n        orbitPocD03::precise("polynomial_nodes",nodes);orbitPocD03::precise("polynomial_weights",weights);\n        orbitPocD03::scalar("polynomial_query_index",i);orbitPocD03::scalar("polynomial_rows_per_epoch",rowsPerEpoch);orbitPocD03::scalar("polynomial_sampling",sampling);orbitPocD03::scalar("polynomial_derivative",derivative);\n        orbitPocD03::scalar("polynomial_stencil_start",idx);orbitPocD03::scalar("polynomial_stencil_count",count);\n        orbitPocD03::time("polynomial_query_time",query);orbitPocD03::extended("polynomial_query_offset",offsetAt(i));\n        if(orbitPocD03::selected())for(UInt k=0;k<count;k++)\n        {orbitPocD03::time(("polynomial_node_time_"+std::to_string(k)).c_str(),times.at(idx+k));\n         orbitPocD03::matrix(("polynomial_node_value_"+std::to_string(k)).c_str(),A.row(rowsPerEpoch*(idx+k),rowsPerEpoch));}')
    anchor='            B(rowsPerEpoch*i+row,col)=static_cast<Double>(value.rounded());'
    text=once(text,anchor,'            orbitPocD03::pair("polynomial_precise_result",value,row,col);\n'+anchor+'\n            orbitPocD03::scalar("polynomial_native_result",B(rowsPerEpoch*i+row,col),row,col);')
    save(name,text)

    name='gnss/gnssParametrization/gnssParametrizationAmbiguities.cpp';text=read(name)
    anchor='  orbitPocQr::PreciseResidualVector result(types.size());UInt idx;'
    text=once(text,anchor,anchor+'\n  orbitPocD03::matrix("ambiguity_native_coordinates",this->value);\n  orbitPocD03::matrix("ambiguity_composition",T);')
    anchor='        if(T.columns()!=this->value.rows())throw(Exception("Precise ambiguity dimension mismatch"));'
    text=once(text,anchor,'        orbitPocD03::scalar("ambiguity_type_mapping",idx,idType);\n'+anchor)
    anchor='        ambi->value += dx;'
    text=once(text,anchor,'        orbitPocD03::scalar("ambiguity_global_start",normalEquationInfo.index(ambi->index));\n        orbitPocD03::matrix("ambiguity_update_before",ambi->value);orbitPocD03::matrix("ambiguity_update_requested",dx);\n'+anchor+'\n        orbitPocD03::matrix("ambiguity_update_after",ambi->value);')
    for obj,loop in [('trans','para->types.size()'),('recv','dBias.size()')]:
        anchor='        for(UInt idType=0; idType<'+loop+'; idType++)\n          para->'+obj+'->signalBias.biases.at(GnssType::index(para->'+obj+'->signalBias.types, para->types.at(idType))) += dBias(idType);'
        eqn='~0ULL,para->trans->idTrans(),~0ULL' if obj=='trans' else 'para->recv->idRecv(),~0ULL,~0ULL'
        text=once(text,anchor,'        orbitPocD03::Equation traceBias('+eqn+');\n        orbitPocD03::Component traceBiasComponent("update_phase_bias");\n        orbitPocD03::scalar("bias_global_start",normalEquationInfo.index(para->index));\n        orbitPocD03::matrix("bias_composition",para->Bias);orbitPocD03::matrix("bias_requested",dBias);\n        orbitPocD03::array("bias_update_before",para->'+obj+'->signalBias.biases);\n'+anchor+'\n        orbitPocD03::array("bias_update_after",para->'+obj+'->signalBias.biases);\n        if(orbitPocD03::selected())for(UInt idType=0;idType<dBias.size();idType++)orbitPocD03::scalar("bias_type_mapping",GnssType::index(para->'+obj+'->signalBias.types,para->types.at(idType)),idType);')
    save(name,text)

    for kind in ('CodeBiases','TecBiases'):
        name='gnss/gnssParametrization/gnssParametrization'+kind+'.cpp';text=read(name)
        for obj in ('trans','recv'):
            anchor='        for(UInt idType=0; idType<dBias.size(); idType++)\n          para->'+obj+'->signalBias.biases.at(idType) += dBias(idType);'
            eqn='~0ULL,para->trans->idTrans(),~0ULL' if obj=='trans' else 'para->recv->idRecv(),~0ULL,~0ULL'
            text=once(text,anchor,'        orbitPocD03::Equation traceBias('+eqn+');\n        orbitPocD03::Component traceBiasComponent("update_'+kind+'");\n        orbitPocD03::scalar("bias_global_start",normalEquationInfo.index(para->index));\n        orbitPocD03::matrix("bias_composition",para->Bias);orbitPocD03::matrix("bias_requested",dBias);\n        orbitPocD03::array("bias_update_before",para->'+obj+'->signalBias.biases);\n'+anchor+'\n        orbitPocD03::array("bias_update_after",para->'+obj+'->signalBias.biases);')
        save(name,text)

    name='gnss/gnssParametrization/gnssParametrizationIonosphereSTEC.cpp' ;text=read(name)
    anchor='    const Double STEC = eqn.STEC;'
    text=once(text,anchor,anchor+'\n    orbitPocD03::scalar("STEC",eqn.STEC);orbitPocD03::scalar("dSTEC",eqn.dSTEC);orbitPocD03::scalar("sigmaSTEC",eqn.sigmaSTEC);')
    anchor='      const Double f4 = f1*f3;'
    text=once(text,anchor,anchor+'\n      orbitPocD03::scalar("ionosphere_f1",f1,i);orbitPocD03::scalar("ionosphere_f2",f2,i);\n      orbitPocD03::scalar("ionosphere_f3",f3,i);orbitPocD03::scalar("ionosphere_f4",f4,i);\n      orbitPocD03::scalar("ionosphere_s",s,i);orbitPocD03::scalar("ionosphere_r",r,i);orbitPocD03::scalar("ionosphere_bending",bending,i);\n      orbitPocD03::scalar("ionosphere_Ap",Ionosphere::Ap,i);')
    for flag in ('apply1stOrder','apply2ndOrder','apply3rdOrder','applyBending','estimateSTEC','applyConstraint'):
        anchor='    const Double STEC = eqn.STEC;';text=once(text,anchor,anchor+'\n    orbitPocD03::scalar("'+flag+'",'+flag+');')
    save(name,text)

    name='gnss/gnssParametrization/gnssParametrizationIonosphereVTEC.cpp';text=read(name)
    anchor='                recv->observation(idTrans, idEpoch)->STEC += mapping(eqn.elevationRecvLocal) * (dVTEC + std::cos(eqn.azimutRecvLocal)*dgx + std::sin(eqn.azimutRecvLocal)*dgy);'
    text=once(text,anchor,'                orbitPocD03::Equation traceVtec(recv->idRecv(),idTrans,idEpoch);\n                orbitPocD03::scalar("VTEC_STEC_before",recv->observation(idTrans,idEpoch)->STEC);\n                orbitPocD03::scalar("VTEC_requested",dVTEC);orbitPocD03::scalar("VTEC_gradient_x_requested",dgx);orbitPocD03::scalar("VTEC_gradient_y_requested",dgy);\n'+anchor+'\n                orbitPocD03::scalar("VTEC_STEC_after",recv->observation(idTrans,idEpoch)->STEC);\n                orbitPocD03::shadow([&](){orbitPocD03::scalar("VTEC_mapping",mapping(eqn.elevationRecvLocal));orbitPocD03::scalar("VTEC_cos",std::cos(eqn.azimutRecvLocal));orbitPocD03::scalar("VTEC_sin",std::sin(eqn.azimutRecvLocal));});')
    save(name,text)

    name='gnss/gnssParametrization/gnssParametrizationClocks.cpp';text=read(name)
    for obj,idvar,indent in [('trans','idTrans','          '),('recv','idRecv','            ')]:
        anchor=indent+obj+'->updateClockError(idEpoch, dClock/LIGHT_VELOCITY);'
        eqn='~0ULL,idTrans,idEpoch' if obj=='trans' else 'idRecv,~0ULL,idEpoch'
        text=once(text,anchor,indent+'orbitPocD03::Equation traceClock('+eqn+');\n'+indent+'orbitPocD03::scalar("clock_seconds_before",'+obj+'->clockError(idEpoch));\n'+indent+'orbitPocD03::scalar("clock_requested_metres",dClock);\n'+indent+obj+'->updateClockError(idEpoch, orbitPocD03::operand("clock_requested_seconds",dClock/LIGHT_VELOCITY));\n'+indent+'orbitPocD03::scalar("clock_seconds_after",'+obj+'->clockError(idEpoch));')
    save(name,text)
    return changes

def digest(raw):return hashlib.sha256(raw).hexdigest()
def install(tree,receipt):
    source=tree/'source';changes=patched_files(source);header=Path(__file__).with_name('nuisanceArithmeticTrace.h');destination=source/'misc/orbitPoc/nuisanceArithmeticTrace.h'
    if destination.exists() or receipt.exists():raise ValueError('D03 destination or receipt exists')
    records={name:{'before':digest((source/name).read_bytes()),'after':digest(text.encode())} for name,text in changes.items()}
    raw=header.read_bytes();records[str(destination.relative_to(source))]={'before':None,'after':digest(raw)}
    destination.write_bytes(raw)
    for name,text in changes.items():(source/name).write_text(text)
    result={'schema':'orbit-poc-d03-install-v1','diagnostic_only':True,'tree':str(tree.resolve()),'installer_sha256':digest(Path(__file__).read_bytes()),'header_sha256':digest(raw),'files':records,'required_equivalence':'original08 versus diagnostic-off versus diagnostic-on first4generations; no gate promotion'}
    with receipt.open('x') as f:json.dump(result,f,indent=2,sort_keys=True);f.write('\n')
    return result
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--tree',type=Path,required=True);parser.add_argument('--receipt',type=Path,required=True);args=parser.parse_args();install(args.tree,args.receipt)
