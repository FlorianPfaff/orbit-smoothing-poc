#!/usr/bin/env python3
"""Make native ambiguity simulation reproducible without changing default behavior."""
from pathlib import Path
import argparse


def _canonical_includes(text):
    # Applying the seed and truth-export patches in different historical orders
    # must produce the same source bytes as a fresh application.
    return text.replace(
        "#include <random>\n#include <cstdlib>\n#include <cstdint>\n#include <fstream>\n#include <iomanip>",
        "#include <random>\n#include <fstream>\n#include <iomanip>\n#include <cstdlib>\n#include <cstdint>", 1)


def apply(source):
    path=Path(source)/"source/gnss/gnssReceiver.cpp"
    text=path.read_text()
    if "ORBIT_POC_SIMULATION_AMBIGUITIES" not in text:
        text=text.replace("#include <random>","#include <random>\n#include <fstream>\n#include <iomanip>",1)
        marker="    createTracks(transmitters, minObsCountPerTrack);\n    for(auto &track : tracks)"
        if text.count(marker)!=1:
            raise ValueError("Pinned ambiguity track creation changed")
        text=text.replace(marker,'''    std::ofstream ambiguityTruth;
    if(const char *path=std::getenv("ORBIT_POC_SIMULATION_AMBIGUITIES"))
    {
      ambiguityTruth.open(path,std::ios::out|std::ios::trunc);
      if(!ambiguityTruth) throw(Exception("cannot write simulation ambiguity truth"));
      ambiguityTruth << "# PRN type start_GPS_MJD end_GPS_MJD ambiguity_m\\n" << std::setprecision(17);
    }
    createTracks(transmitters, minObsCountPerTrack);
    for(auto &track : tracks)''',1)
        marker="      new Ambiguity(track.get(), value); // track is owner of ambiguity"
        text=text.replace(marker,'''      if(ambiguityTruth.is_open())
        for(UInt i=0;i<value.size();i++)
          if(track->types.at(i)==GnssType::PHASE)
            ambiguityTruth << track->transmitter->PRN().prn() << " " << track->types.at(i).str() << " "
              << times.at(track->idEpochStart).mjd() << " " << times.at(track->idEpochEnd).mjd() << " " << value(i) << "\\n";
'''+marker,1)
        path.write_text(text)
    if "ORBIT_POC_SIMULATION_SEED" in text:
        path.write_text(_canonical_includes(text))
        return
    text=text.replace("#include <random>","#include <random>\n#include <cstdlib>\n#include <cstdint>",1)
    old="    generator.seed(randomDevice());"
    if text.count(old)!=1:
        raise ValueError("Pinned native ambiguity generator changed")
    text=text.replace(old,'''    if(const char *seedText=std::getenv("ORBIT_POC_SIMULATION_SEED"))
    {
      const std::string seedString(seedText);
      if(seedString.empty() || seedString.find_first_not_of("0123456789")!=std::string::npos)
        throw(Exception("ORBIT_POC_SIMULATION_SEED must be an unsigned integer"));
      // FNV1a rather than std::hash: stable across implementations and processes.
      std::uint64_t nameHash=14695981039346656037ULL;
      for(unsigned char c:name()) {nameHash^=c;nameHash*=1099511628211ULL;}
      generator.seed(std::stoull(seedString)^nameHash);
    }
    else generator.seed(randomDevice());''',1)
    path.write_text(_canonical_includes(text))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    apply(parser.parse_args().source)
