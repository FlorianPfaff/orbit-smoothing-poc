// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_NUISANCE_WARM_GNSS_H
#define ORBIT_POC_NUISANCE_WARM_GNSS_H
#include "misc/orbitPoc/nuisanceWarmState.h"
#include "gnss/gnssParametrization/gnssParametrization.h"
#include "gnss/gnssReceiver.h"
#include "gnss/gnssTransmitter.h"
#include <map>
namespace orbitPocWarm {
inline Ledger collect(Gnss &gnss,const GnssNormalEquationInfo &info,bool signal)
{
  Ledger l(signal);l.id("mode",signal?std::string("receiver_clock_signal_float_v1"):std::string("receiver_clock_v1"));
  require(Parallel::size(info.comm)==1,"serial execution required");
  l.id("parameters",std::uint64_t(info.parameterCount()));
  for(const auto &p:info.parameterNames())l.id("parameter",p.str());
  for(const auto i:info.blockIndices())l.id("parameter.block",std::uint64_t(i));
  l.id("receiver_separate",std::uint64_t(info.isEachReceiverSeparately));
  l.id("accumulate_epochs",std::uint64_t(info.accumulateEpochObservations));
  for(const auto selected:info.estimateReceiver)l.id("estimate_receiver",std::uint64_t(selected));
  for(const auto epoch:info.idEpochs){l.id("epoch",std::uint64_t(epoch));l.id("time.day",std::uint64_t(gnss.times.at(epoch).mjdInt()));l.id("time.fraction",double(gnss.times.at(epoch).mjdMod()));}
  gnss.parametrization->orbitPocWarmCollect(l,info);
  auto shared=[&](const std::string &key,GnssTransceiver &item)
  {
    l.id(key+".id",std::uint64_t(item.id_));l.id(key+".name",item.name());l.types(key+".types",item.signalBias.types);
    const bool selected=signal&&l.signalOwners.count(&item);l.id(key+".warm",std::uint64_t(selected));
    l.id(key+".bias_count",std::uint64_t(item.signalBias.biases.size()));
    require(item.signalBias.biases.size()==item.signalBias.types.size(),"signal-bias type/value shape mismatch");
    for(std::size_t i=0;i<item.signalBias.biases.size();i++)
    {
      auto &v=item.signalBias.biases[i];const auto bkey=key+"/bias_m/"+std::to_string(i);
      if(selected)l.value(bkey,v);else if(l.signalOwners.count(&item))l.fixed(bkey,v);else l.id(bkey,double(v));
    }
    for(const auto epoch:info.idEpochs)l.id(key+".usable",std::uint64_t(item.useable(epoch)));
  };
  for(const auto &trans:gnss.transmitters)shared("transmitter/"+std::to_string(trans->idTrans()),*trans);
  for(const auto &recv:gnss.receivers)
  {
    const auto key="receiver/"+std::to_string(recv->idRecv());shared(key,*recv);
    l.id(key+".wavelength_factor",double(recv->wavelengthFactor));
    std::map<const GnssTrack*,std::uint64_t> trackIds;
    for(std::size_t i=0;i<recv->tracks.size();i++){const auto p=recv->tracks[i].get();require(p&&p->receiver==recv.get()&&trackIds.emplace(p,i+1).second,"invalid or duplicate receiver track");}
    for(const auto epoch:info.idEpochs)
    {
      const auto ekey=key+"/epoch/"+std::to_string(epoch);
      const auto raw=recv->times.at(epoch);l.id(ekey+".raw_day",std::uint64_t(raw.mjdInt()));l.id(ekey+".raw_fraction",double(raw.mjdMod()));
      l.id(ekey+".transmitter_slots",std::uint64_t(recv->idTransmitterSize(epoch)));
      for(UInt trans=0;trans<recv->idTransmitterSize(epoch);trans++)
      {
        auto obs=recv->observation(trans,epoch);l.id(ekey+".observation_present",std::uint64_t(bool(obs)));if(!obs)continue;
        const auto okey=ekey+"/transmitter/"+std::to_string(trans);l.id(okey+".count",std::uint64_t(obs->size()));
        require(!obs->track||trackIds.count(obs->track),"observation points outside receiver track chart");
        l.id(okey+".track",obs->track?trackIds.at(obs->track):std::uint64_t(0));
        for(UInt i=0;i<obs->size();i++){const auto &v=obs->at(i);l.id(okey+".type",v.type.str());l.id(okey+".value",double(v.observation));l.id(okey+".sigma",double(v.sigma));l.id(okey+".sigma0",double(v.sigma0));}
        l.id(okey+".sigmaSTEC",double(obs->sigmaSTEC));
        l.fixed(okey+".STEC",double(obs->STEC));l.fixed(okey+".dSTEC",double(obs->dSTEC));l.fixed(okey+".sigmaSTEC",double(obs->sigmaSTEC));
      }
    }
    l.id(key+".tracks",std::uint64_t(recv->tracks.size()));
    for(const auto &track:recv->tracks){l.id(key+".track.transmitter",std::uint64_t(track->transmitter->idTrans()));l.id(key+".track.first",std::uint64_t(track->idEpochStart));l.id(key+".track.last",std::uint64_t(track->idEpochEnd));l.types(key+".track.types",track->types);}
  }
  return l;
}
}
#endif
