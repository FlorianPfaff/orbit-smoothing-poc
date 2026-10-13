#!/usr/bin/env python3
"""Apply explicit knot-bounded quadrature to the pinned GROOPS implementation.

The physical trajectory and its force sensitivities use the same segmentation.
Pulses are native instantaneous CRF transitions, evaluated after the jump at
their epoch; the polynomial quadrature never interpolates across a density knot.
"""
from pathlib import Path
import argparse
import shutil


def replace(text, before, after):
    if before not in text:
        raise ValueError("Pinned GROOPS integration patch no longer matches: " + before[:100])
    return text.replace(before, after, 1)


def apply(source):
    root = Path(source) / "source"
    header = Path(__file__).with_name("integrationWindows.h")
    destination = root / "misc/orbitPoc/integrationWindows.h"
    if not destination.exists() or header.read_bytes() != destination.read_bytes():
        shutil.copyfile(header, destination)
    h = root / "classes/parametrizationAcceleration/parametrizationAcceleration.h"
    text = h.read_text()
    if "integrationBoundaries()" not in text:
        text = replace(text, "  /// Constructor.", "  std::vector<Time> integrationBoundaries() const;\n\n  /// Constructor.")
        text = replace(text, "virtual ~ParametrizationAccelerationBase() {}", "virtual ~ParametrizationAccelerationBase() {}\nvirtual std::vector<Time> integrationBoundaries() const {return {};}\n")
        h.write_text(text)
        cpp = h.with_suffix(".cpp")
        cpp.write_text(cpp.read_text() + '''
std::vector<Time> ParametrizationAcceleration::integrationBoundaries() const
{
  std::vector<Time> result;
  for(auto item : parameter)
  {
    const auto times = item->integrationBoundaries();
    result.insert(result.end(),times.begin(),times.end());
  }
  std::sort(result.begin(),result.end());
  result.erase(std::unique(result.begin(),result.end()),result.end());
  return result;
}
''')
    h = root / "misc/observation/variationalEquation.h"
    text = h.read_text()
    if "orbitPocWindows" not in text:
        h.write_text(replace(text, "  void   initIntegration();", "  std::vector<UInt> orbitPocWindows;\n  UInt orbitPocWindowStart = NULLINDEX;\n\n  void   initIntegration();"))
        cpp = h.with_suffix(".cpp")
        text = cpp.read_text()
        text = replace(text, '#include "base/import.h"', '#include "base/import.h"\n#include "misc/orbitPoc/integrationWindows.h"')
        text = replace(text, "    initIntegration();\n\n    // init pulses", '''    std::vector<Time> boundaries = parameterAcceleration ? parameterAcceleration->integrationBoundaries() : std::vector<Time>();
    boundaries.insert(boundaries.end(),timePulse.begin(),timePulse.end());
    orbitPocWindows = boundaries.empty() ? std::vector<UInt>() : orbitPocIntegrationWindows(arc_.times,boundaries,integrationDegree);
    initIntegration();

    // init pulses''')
        text = replace(text, "    idIntegrand  = Integrand.size();", "    idIntegrand  = Integrand.size();\n    orbitPocWindowStart = 0;")
        text = replace(text, "    while(idEpochAlpha < idEpoch)\n    {", '''    if(!orbitPocWindows.empty())
    {
      while(idEpochAlpha < idEpoch)
      {
        const UInt start=orbitPocWindows.at(idEpochAlpha);
        if(start!=orbitPocWindowStart)
        {
          const UInt shift=start-orbitPocWindowStart;
          if(shift<Integrand.size())
          {
            for(UInt j=0;j+shift<Integrand.size();j++) Integrand.at(j)=std::move(Integrand.at(j+shift));
            for(UInt j=Integrand.size()-shift;j<Integrand.size();j++) Integrand.at(j)=computeIntegrand(start+j);
          }
          else
            for(UInt j=0;j<Integrand.size();j++) Integrand.at(j)=computeIntegrand(start+j);
          orbitPocWindowStart=start;
        }
        const auto &weights=coeffIntegral.at(idEpochAlpha-start);
        for(UInt j=0;j<weights.rows();j++) axpy(deltaT*weights(j),Integrand.at(j),Alpha);
        idEpochAlpha++;
      }
      return;
    }

    while(idEpochAlpha < idEpoch)
    {''')
        cpp.write_text(text)
    cpp = root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
    text = cpp.read_text()
    if "orbitPocWindows" not in text:
        text = replace(text, '#include "programs/program.h"', '#include "programs/program.h"\n#include "classes/timeSeries/timeSeries.h"\n#include "misc/orbitPoc/integrationWindows.h"')
        text = replace(text, "  UInt                           integrationDegree;", "  UInt                           integrationDegree;\n  TimeSeriesPtr                  integrationBoundaries;\n  std::vector<UInt>              orbitPocWindows;")
        marker='    readConfig(config, "integrationDegree", integrationDegree, Config::DEFAULT,  "7",   "integration of forces by polynomial approximation of degree n");'
        text = replace(text, marker, marker+'\n    readConfig(config,"integrationBoundaries",integrationBoundaries,Config::OPTIONAL,"","model knots; quadrature does not cross them");')
        marker='    const Double      deltaT        = T/(epochCount-1);'
        text = replace(text, marker, marker+'\n    orbitPocWindows = integrationBoundaries ? orbitPocIntegrationWindows(times,integrationBoundaries->times(),integrationDegree) : std::vector<UInt>();')
        marker='    for(UInt i=0; i<epochCount-1; i++)\n    {'
        revised=marker+'''\n      if(!orbitPocWindows.empty())
        idx = evalPoint = i-orbitPocWindows.at(i);'''
        if text.count(marker)!=2:
            raise ValueError("Expected both native quadrature loops")
        text=text.replace(marker,revised)
        cpp.write_text(text)


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source",type=Path)
    apply(parser.parse_args().source)
