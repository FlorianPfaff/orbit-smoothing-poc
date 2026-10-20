#!/usr/bin/env python3
"""Install opt-in typed GNSS nuisance initialization; legacy default stays off.
Apply after corrected numerics, optional segmented/wide/performance installers.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
MARKER='ORBIT_POC_NUISANCE_WARM_STATE_V1'
MANIFEST='orbit-poc-nuisance-warm-extension.json'
BASE='source/gnss/gnssParametrization/'
HEADERS=('nuisanceWarmState.h','nuisanceWarmGnss.h')

def replace(text, old, new):
    if text.count(old)!=1: raise ValueError(f'Nuisance warm anchor mismatch: {old[:100]}')
    return text.replace(old,new,1)

def declaration(text, name, body=None):
    anchor=f'  {name}(Config &config);'
    method='  void orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info) override'
    method += (' {'+body+'}\n') if body is not None else ';\n'
    return replace(text,anchor,method+anchor)

CLOCKS=r'''
void GnssParametrizationClocks::orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info)
{
  const std::string key="clocks/"+name;l.id("component",key);l.id(key+".enabled",std::uint64_t(isEnabled(info,name)));
  l.id(key+".constraint",nameConstraint);l.id(key+".apply",std::uint64_t(applyConstraint));l.id(key+".sigma",double(sigmaZeroMean));
  for(const auto &indices:indexTrans)for(const auto &index:indices)orbitPocWarm::require(!index,"estimated transmitter clocks unsupported");
  auto anchors=[&](const std::string &name,const auto &values){l.id(name+".size",std::uint64_t(values.size()));for(const auto &row:values){l.id(name+".row",std::uint64_t(row.size()));for(const auto v:row){l.id(name+".anchor",double(v));l.fixed(name+".anchor",double(v));}}};
  anchors(key+".x0Recv",x0Recv);anchors(key+".x0Trans",x0Trans);
  auto selection=[&](const std::string &name,const auto &values){l.id(name+".size",std::uint64_t(values.size()));for(auto v:values)l.id(name,std::uint64_t(v));};
  selection(key+".recv",selectedReceivers);selection(key+".trans",selectedTransmitters);selection(key+".recv_zero",selectedReceiversZeroMean);selection(key+".trans_zero",selectedTransmittersZeroMean);
  for(UInt recv=0;recv<indexRecv.size();recv++)for(UInt epoch=0;epoch<indexRecv[recv].size();epoch++)
  {
    const auto &index=indexRecv[recv][epoch];const auto coordinate=key+"/receiver/"+std::to_string(recv)+"/epoch/"+std::to_string(epoch);
    l.index(coordinate,info,index);if(index){orbitPocWarm::require(info.count(index)==1,"non-scalar receiver clock");l.value(coordinate+"/seconds",gnss->receivers.at(recv)->clk.at(epoch));}
  }
}
'''
BIAS=r'''
void CLASS::orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info)
{
  const std::string key="KIND/"+name;l.id("component",key);l.id(key+".enabled",std::uint64_t(isEnabled(info,name)));
  l.id(key+".constraint",nameConstraint);l.id(key+".apply",std::uint64_t(applyConstraint));l.id(key+".sigma",double(sigmaZeroMean));l.id(key+".linear",std::uint64_t(isLinearBias));l.matrix(key+".zero_mean",zeroMeanDesign);
  for(auto i:idxBiasTrans)l.id(key+".datum_trans",std::uint64_t(i));for(auto i:idxBiasRecv)l.id(key+".datum_recv",std::uint64_t(i));EXTRA
  for(UInt side=0;side<2;side++)
  {
    const auto &parameters=side?paraRecv:paraTrans;l.id(key+".side",std::uint64_t(side));l.id(key+".size",std::uint64_t(parameters.size()));
    for(UInt i=0;i<parameters.size();i++)
    {
      auto para=parameters[i];const auto pkey=key+"/"+std::to_string(side)+"/"+std::to_string(i);l.id(pkey+".present",std::uint64_t(bool(para)));if(!para)continue;
      l.index(pkey,info,para->index);l.matrix(pkey+".basis",para->Bias);
      if(para->index){orbitPocWarm::require(para->orbitPocFullCoordinates.rows()==para->Bias.columns()&&para->Bias.columns()==info.count(para->index),"uninitialized full bias coordinates");orbitPocWarm::require(side?bool(para->recv):bool(para->trans),"missing bias owner");l.signalOwners.insert(side?static_cast<GnssTransceiver*>(para->recv.get()):static_cast<GnssTransceiver*>(para->trans.get()));
        if(l.signal)l.values(pkey+"/full_native",para->orbitPocFullCoordinates);else l.unchangedMatrix(pkey+"/cold_full_native",para->orbitPocFullCoordinates);}
    }
  }
}
'''
AMBIGUITIES=r'''
void GnssParametrizationAmbiguities::orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info)
{
  const std::string key="ambiguities/"+name;l.id("component",key);l.id(key+".enabled",std::uint64_t(isEnabled(info,name)));l.id(key+".linear",std::uint64_t(isLinearBias));
  auto phase=[&](const std::string &side,const auto &parameters){l.id(key+side+".size",std::uint64_t(parameters.size()));for(UInt i=0;i<parameters.size();i++){auto p=parameters[i];const auto k=key+side+"/"+std::to_string(i);l.id(k+".present",std::uint64_t(bool(p)));if(!p)continue;l.index(k,info,p->index);l.types(k+".types",p->types);l.matrix(k+".basis",p->Bias);}};
  phase("/receiver",paraRecv);phase("/transmitter",paraTrans);
  for(auto p:paraRecv)if(p&&p->index)l.signalOwners.insert(static_cast<GnssTransceiver*>(p->recv.get()));
  for(auto p:paraTrans)if(p&&p->index)l.signalOwners.insert(static_cast<GnssTransceiver*>(p->trans.get()));
  UInt serial=0;for(auto ambi:getAmbiguities())
  {
    orbitPocWarm::require(ambi&&ambi->track&&ambi->track->receiver&&ambi->track->transmitter,"unsupported or incomplete ambiguity chart");
    const auto k=key+"/track/"+std::to_string(serial++);l.index(k,info,ambi->index);l.types(k+".types",ambi->types);l.matrix(k+".T",ambi->T);
    orbitPocWarm::require(!ambi->resolved.rows(),"resolved ambiguity state unsupported");
    if(ambi->index)orbitPocWarm::require(ambi->value.rows()==ambi->T.columns()&&ambi->value.rows()==info.count(ambi->index),"ambiguity coordinate shape mismatch");
    l.id(k+".receiver",std::uint64_t(ambi->track->receiver->idRecv()));l.id(k+".transmitter",std::uint64_t(ambi->track->transmitter->idTrans()));l.id(k+".first",std::uint64_t(ambi->track->idEpochStart));l.id(k+".last",std::uint64_t(ambi->track->idEpochEnd));
    if(ambi->index&&l.signal)l.values(k+"/cycles",ambi->value);else l.unchangedMatrix(k+"/cold_cycles",ambi->value);
  }l.id(key+".tracks",std::uint64_t(serial));
}
'''
VTEC=r'''
void GnssParametrizationIonosphereVTEC::orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info)
{
  const auto key="ionosphereVTEC/"+name;l.id("component",key);l.id(key+".enabled",std::uint64_t(isEnabled(info,name)));l.id(key+".R",double(mapR));l.id(key+".H",double(mapH));l.id(key+".alpha",double(mapAlpha));
  for(auto v:selectedReceivers)l.id(key+".selected",std::uint64_t(v));
  for(UInt recv=0;recv<indexVTEC.size();recv++)for(UInt epoch=0;epoch<indexVTEC[recv].size();epoch++)l.index(key+"/"+std::to_string(recv)+"/"+std::to_string(epoch),info,indexVTEC[recv][epoch]);
  for(UInt i=0;i<indexGradient.size();i++)l.index(key+".gradient/"+std::to_string(i),info,indexGradient[i]);
  for(const auto &v:VTEC)for(auto x:v)l.fixed(key+".VTEC",x);for(const auto &v:xGradient)l.unchangedMatrix(key+".xGradient",v);
  for(const auto &v:gradientX)for(auto x:v)l.fixed(key+".gradientX",x);for(const auto &v:gradientY)for(auto x:v)l.fixed(key+".gradientY",x);
}
'''

def transform(original):
    out=dict(original)
    base=BASE+'gnssParametrization.h';s=out[base]
    s=replace(s,'#include "base/import.h"','#include "base/import.h"\n#include "misc/orbitPoc/nuisanceWarmState.h"')
    s=replace(s,'  /// Constructor.','  void orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info);\n\n  /// Constructor.')
    s=replace(s,'  virtual ~GnssParametrizationBase() {}','  virtual ~GnssParametrizationBase() {}\n  virtual void orbitPocWarmCollect(orbitPocWarm::Ledger &,const GnssNormalEquationInfo &)\n  {throw(Exception("Unsupported parametrization in nuisance warm chart"));}')
    out[base]=s
    path=BASE+'gnssParametrization.cpp';s=out[path]
    anchor='void GnssParametrization::initParameter(GnssNormalEquationInfo &normalEquationInfo)\n{\n  try\n  {'
    s=replace(s,anchor,anchor+'\n    orbitPocWarm::beforeInitParameter();')
    s+='\nvoid GnssParametrization::orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info)\n{l.id("component_count",std::uint64_t(base.size()));for(auto component:base)component->orbitPocWarmCollect(l,info);}\n'
    out[path]=s
    for kind,code in (('Clocks',CLOCKS),('CodeBiases',BIAS.replace('CLASS','GnssParametrizationCodeBiases').replace('KIND','codeBiases').replace('EXTRA','l.types(key+".clock_datum",typesClockDatum);')),('TecBiases',BIAS.replace('CLASS','GnssParametrizationTecBiases').replace('KIND','tecBiases').replace('EXTRA','')),('Ambiguities',AMBIGUITIES),('IonosphereVTEC',VTEC)):
        name='GnssParametrization'+kind;h=BASE+'gnssParametrization'+kind+'.h';cpp=h[:-1]+'cpp'
        out[h]=declaration(out[h],name);out[cpp]+=code
    simple={
        'Group':'l.id("component",std::string("group"));base->orbitPocWarmCollect(l,info);',
        'SignalBiases':'l.id("component",std::string("signalBiases/"+name));l.id("signalBiases.enabled",std::uint64_t(isEnabled(info,name)));',
        'LeoDynamicOrbits':'l.id("component",std::string("leoDynamicOrbits/"+name));l.id("leoDynamicOrbits.enabled",std::uint64_t(isEnabled(info,name)));',
        'IonosphereSTEC':'l.id("component",std::string("ionosphereSTEC/"+name));l.id("ionosphereSTEC.constraint",nameConstraint);l.id("ionosphereSTEC.enabled",std::uint64_t(isEnabled(info,name)));l.id("ionosphereSTEC.first",std::uint64_t(apply1stOrder));l.id("ionosphereSTEC.second",std::uint64_t(apply2ndOrder));l.id("ionosphereSTEC.third",std::uint64_t(apply3rdOrder));l.id("ionosphereSTEC.bending",std::uint64_t(applyBending));l.id("ionosphereSTEC.estimate",std::uint64_t(estimateSTEC));l.id("ionosphereSTEC.constraint_active",std::uint64_t(applyConstraint));l.id("ionosphereSTEC.sigma_mode",std::uint64_t(isSigmaSTEC));',
        'Constraints':'l.id("component",std::string("constraints/"+name));l.id("constraints.enabled",std::uint64_t(isEnabled(info,name)));orbitPocWarm::require(!relativeToApriori,"relative constraint unsupported");l.id("constraints.sigma",double(sigma));l.id("constraints.bias",double(bias));for(auto i:parameterSelector->indexVector(info.parameterNames()))l.id("constraints.index",std::uint64_t(i));',
    }
    for kind,body in simple.items():
        h=BASE+'gnssParametrization'+kind+'.h';out[h]=declaration(out[h],'GnssParametrization'+kind,body)
    density=BASE+'gnssParametrizationLogDensityOu.h';s=out[density]
    anchor='  explicit GnssParametrizationLogDensityOu(Config &config)'
    body='  void orbitPocWarmCollect(orbitPocWarm::Ledger &l,const GnssNormalEquationInfo &info) override\n  {l.id("component",std::string("logDensityOu/"+name));l.id("logDensityOu.enabled",std::uint64_t(isEnabled(info,name)));l.id("logDensityOu.tau",double(tau));l.id("logDensityOu.sigma",double(sigma));for(auto i:selector->indexVector(info.parameterNames()))l.id("logDensityOu.index",std::uint64_t(i));for(const auto &t:series->times){l.id("logDensityOu.day",std::uint64_t(t.mjdInt()));l.id("logDensityOu.fraction",double(t.mjdMod()));}}\n'
    out[density]=replace(s,anchor,body+anchor)
    step='source/gnss/gnssProcessingStep/gnssProcessingStepOrbitPocNumerics.h';s=out[step]
    s=replace(s,'#include "misc/orbitPoc/nuisanceLineSearch.h"','#include "misc/orbitPoc/nuisanceLineSearch.h"\n#include "misc/orbitPoc/nuisanceWarmGnss.h"')
    s=replace(s,'    if(Parallel::size(state.normalEquationInfo.comm)!=1)','    orbitPocWarm::Session warm;\n    if(Parallel::size(state.normalEquationInfo.comm)!=1)')
    anchor='    state.gnss->aprioriParameter(state.normalEquationInfo);'
    s=replace(s,anchor,anchor+'\n    if(warm.enabled){auto cold=orbitPocWarm::collect(*state.gnss,state.normalEquationInfo,warm.signal);warm.begin(cold);}')
    anchor='    Bool converged=FALSE,floorLimited=FALSE;'
    s=replace(s,anchor,'    if(warm.enabled)warm.verifyRefresh(orbitPocWarm::collect(*state.gnss,state.normalEquationInfo,warm.signal));\n'+anchor)
    anchor='    if(!converged&&!floorLimited) throw(Exception("nuisance profiling exhausted its iteration limit"));'
    s=replace(s,anchor,'    if(warm.enabled)warm.finish(orbitPocWarm::collect(*state.gnss,state.normalEquationInfo,warm.signal),converged,floorLimited,converged||floorLimited,orbitPocRowQr().rankInfo().status,prefix.str(),orbitPocRowQr().artifactStem());\n'+anchor)
    out[step]=s
    return {key:'// '+MARKER+'\n'+value for key,value in out.items()}

def paths():
    names=['gnssParametrization.h','gnssParametrization.cpp']
    for k in ('Clocks','CodeBiases','TecBiases','Ambiguities','IonosphereVTEC'):
        names += ['gnssParametrization'+k+'.h','gnssParametrization'+k+'.cpp']
    names += ['gnssParametrization'+k+'.h' for k in ('Group','SignalBiases','LeoDynamicOrbits','IonosphereSTEC','Constraints','LogDensityOu')]
    return [BASE+name for name in names]+['source/gnss/gnssProcessingStep/gnssProcessingStepOrbitPocNumerics.h']

def digest(data):return hashlib.sha256(data).hexdigest()
def apply(root):
    root=Path(root);here=Path(__file__).resolve().parent
    inputs={name:digest((here/name).read_bytes()) for name in ('native_nuisance_warm.py',*HEADERS)}
    expected=set(paths())|{'source/misc/orbitPoc/'+name for name in HEADERS}
    manifest_path=root/MANIFEST
    if manifest_path.exists():
        manifest=json.loads(manifest_path.read_text())
        if manifest.get('installer_inputs')!=inputs or set(manifest.get('installed_files',{}))!=expected:raise ValueError('Installed nuisance warm implementation differs')
        for name,value in manifest['installed_files'].items():
            if digest((root/name).read_bytes())!=value:raise ValueError(f'Installed nuisance warm file changed: {name}')
        return manifest
    original={name:(root/name).read_bytes() for name in paths()}
    if any(MARKER.encode() in data for data in original.values()):raise ValueError('Unattributed partial nuisance warm installation')
    for name in HEADERS:
        installed=root/'source/misc/orbitPoc'/name
        if installed.exists() and installed.read_bytes()!=(here/name).read_bytes():raise ValueError('Unattributed nuisance warm header')
    if b'ORBIT_POC_FULL_BIAS_COORDINATES_V31' not in original[BASE+'gnssParametrizationCodeBiases.h'] or b'ORBIT_POC_TRANSACTIONAL_NUISANCE_V31' not in (root/'source/gnss/gnssProcessingStep/gnssProcessingStep.cpp').read_bytes():raise ValueError('Corrected numerics extension required')
    updated={name:value.encode() for name,value in transform({name:data.decode() for name,data in original.items()}).items()}
    updated.update({'source/misc/orbitPoc/'+name:(here/name).read_bytes() for name in HEADERS})
    manifest={'schema':'orbit-poc-nuisance-warm-extension-v1','runtime_default':'0','runtime_environment':'ORBIT_POC_NUISANCE_WARM_STARTS','runtime_values':['0','1'],'modes':['receiver_clock_v1','receiver_clock_signal_float_v1'],'default_mode':'receiver_clock_signal_float_v1','scientific_models_and_thresholds':'unchanged','import_scope':'initialization_only_non_ionosphere','installer_inputs':inputs,'previous_files':{name:digest(data) for name,data in original.items()},'installed_files':{name:digest(data) for name,data in updated.items()}}
    for name,data in updated.items():(root/name).write_bytes(data)
    manifest_path.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
    return manifest
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--source',required=True)
    print(json.dumps(apply(parser.parse_args().source),sort_keys=True,indent=2))
