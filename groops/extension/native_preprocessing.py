#!/usr/bin/env python3
"""Optionally pin native cleaning geometry to the common GNSS-only bootstrap."""
from pathlib import Path
import argparse


def replace_once(text, old, new):
    if new in text:
        return text
    if text.count(old) != 1:
        raise ValueError("Pinned low-Earth-orbiter preprocessing anchor changed: " + old[:100])
    return text.replace(old, new, 1)


def apply(source):
    root = Path(source) / "source/gnss/gnssReceiverGenerator"
    header = root / "gnssReceiverGeneratorLowEarthOrbiter.h"
    text = header.read_text()
    text = replace_once(text, "  GnssReceiverPtr       recv;", """  GnssReceiverPtr       recv;
  Bool orbitPocPreprocessFromInputOrbit;
  std::vector<Vector3d> orbitPocInputPosition, orbitPocInputVelocity;
  FileName fileNameOrbitPocPreprocessingAudit;""")
    if text != header.read_text():
        header.write_text(text)
    path = root / "gnssReceiverGeneratorLowEarthOrbiter.cpp"
    text = path.read_text()
    text = replace_once(text, '#include "config/config.h"', '#include "config/config.h"\n#include <fstream>\n#include <iomanip>')
    marker = '    readConfig(config, "inputfileOrbit",               fileNameOrbit,           Config::MUSTSET,  "",     "approximate positions");'
    text = replace_once(text, marker, marker + """
    readConfig(config,"orbitPocPreprocessFromInputOrbit",orbitPocPreprocessFromInputOrbit,Config::DEFAULT,"0","use immutable input orbit for common code initialization and cleaning");
    readConfig(config,"outputfileOrbitPocPreprocessingAudit",fileNameOrbitPocPreprocessingAudit,Config::OPTIONAL,"","retained observables, fixed weights and ambiguity arcs after preprocessing");""")
    marker = '        recv->preprocessingInfo("init()");'
    text = replace_once(text, marker, """        if(orbitPocPreprocessFromInputOrbit)
        {
          orbitPocInputPosition = recv->pos;
          orbitPocInputVelocity = recv->vel;
        }
""" + marker)
    marker = "        std::vector<Vector3d> posApriori = recv->pos;"
    text = replace_once(text, marker, marker + """
        const std::vector<Vector3d> velocityApriori = recv->vel;
        if(orbitPocPreprocessFromInputOrbit)
        {
          // Dynamic-orbit initialization has already replaced receiver geometry.
          // Clean both arms using the same masked GNSS-only input geometry.
          recv->pos = orbitPocInputPosition;
          recv->vel = orbitPocInputVelocity;
        }""")
    marker = "        recv->pos = std::move(posApriori); // restore apriori positions"
    text = replace_once(text, marker, marker + "\n        if(orbitPocPreprocessFromInputOrbit) recv->vel = velocityApriori;")
    marker = "        } // if(exprSigmaPhase || exprSigmaCode)"
    text = replace_once(text, marker, marker + """

        if(!fileNameOrbitPocPreprocessingAudit.empty())
        {
          std::ofstream audit(fileNameOrbitPocPreprocessingAudit.str());
          if(!audit) throw(Exception("Cannot write common preprocessing audit"));
          audit << "# GPSMJD PRN type processed_m sigma0_m sigma_m track_start_GPSMJD track_end_GPSMJD\\n" << std::setprecision(17);
          for(UInt idEpoch=0;idEpoch<recv->idEpochSize();idEpoch++)
            if(recv->useable(idEpoch))
              for(UInt idTrans=0;idTrans<gnss->transmitters.size();idTrans++)
              {
                const GnssObservation *obs=recv->observation(idTrans,idEpoch);
                if(!obs) continue;
                for(UInt i=0;i<obs->size();i++)
                {
                  const auto &single=obs->at(i);
                  if(single.type!=GnssType::RANGE && single.type!=GnssType::PHASE) continue;
                  audit << recv->times.at(idEpoch).mjd() << " " << gnss->transmitters.at(idTrans)->name() << " "
                    << single.type.str() << " " << single.observation << " " << single.sigma0 << " " << single.sigma << " "
                    << (obs->track ? recv->times.at(obs->track->idEpochStart).mjd() : 0.) << " "
                    << (obs->track ? recv->times.at(obs->track->idEpochEnd).mjd() : 0.) << "\\n";
                }
              }
        }""")
    if text != path.read_text():
        path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
