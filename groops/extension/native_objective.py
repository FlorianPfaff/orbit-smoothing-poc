"""Opt-in v3.1 fixed-orbit nuisance profiling and physical design export."""
from pathlib import Path
import shutil
import sys


def apply(source):
    source = Path(source) / "source"
    here = Path(__file__).parent
    name = "gnssProcessingStepOrbitPocNumerics.h"
    shutil.copyfile(here/name, source/"gnss/gnssProcessingStep"/name)
    path = source/"gnss/gnssProcessingStep/gnssProcessingStep.cpp"
    text = path.read_text()
    marker = "ORBIT_POC_NUMERICS_OBJECTIVE_V1"
    if marker not in text:
        include = '#include "gnss/gnssProcessingStep/gnssProcessingStepEstimate.h"'
        registration = 'GROOPS_REGISTER_CLASS(GnssProcessingStep, "gnssProcessingStepType",'
        choice = '      if(readConfigChoiceElement(config, "estimate",'
        for anchor in (include, registration, choice):
            if text.count(anchor) != 1:
                raise ValueError("Pinned objective patch anchor changed: " + anchor)
        text = text.replace(include, include+'\n#include "gnss/gnssProcessingStep/'+name+'"', 1)
        text = text.replace(registration, registration+'\n                      GnssProcessingStepOrbitPocNumerics,', 1)
        text = text.replace(choice, '      if(readConfigChoiceElement(config, "orbitPocNumerics", type, "v3.1 fixed-orbit nuisance profiling"))\n        bases.push_back(new GnssProcessingStepOrbitPocNumerics(config));\n'+choice, 1)
        path.write_text('// '+marker+'\n'+text)
    # Fixed physical trials contain full pulses and a physical initial state.
    # Their reference contribution is part of the mean, not a new fitted step.
    header = source/"gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.h"
    cpp = header.with_suffix(".cpp")
    h, c = header.read_text(), cpp.read_text()
    marker = "ORBIT_POC_NUMERICS_REFERENCE_V1"
    if marker not in h:
        anchor = "  std::vector<Time>              pulses;"
        if h.count(anchor) != 1:
            raise ValueError("Pinned physical reference declaration changed")
        h = h.replace(anchor, "  FileName fileNameNumericsReference; // "+marker+"\n"+anchor, 1)
        anchor = "    pulses = stochasticPulse->times();"
        c = c.replace("    if(isCreateSchema(config)) return;", '    readConfig(config,"inputfileNumericsReferenceParameters",fileNameNumericsReference,Config::OPTIONAL,"","fixed physical mean parameters; excluded from increments");\n    if(isCreateSchema(config)) return;', 1)
        anchor = "        para->x = Vector(file.parameterCount());"
        if c.count(anchor) != 1:
            raise ValueError("Pinned physical reference initialization changed")
        c = c.replace(anchor, anchor+'''\n        Matrix orbitPocReference(file.parameterCount(),1);
        if(!fileNameNumericsReference.empty())
        {
          readFileMatrix(fileNameNumericsReference,orbitPocReference);
          if(orbitPocReference.rows()!=file.parameterCount() || orbitPocReference.columns()!=1)
            throw(Exception("Fixed physical reference parameter count differs from native dynamics"));
        }''', 1)
        anchor = "            para->vel.emplace_back(variationalEquation.vel0);"
        if c.count(anchor) != 1:
            raise ValueError("Pinned physical reference mean changed")
        c = c.replace(anchor, anchor+'''\n            if(!fileNameNumericsReference.empty())
            {
              matMult(1.,variationalEquation.PosDesign,orbitPocReference,para->pos.back());
              matMult(1.,variationalEquation.VelDesign,orbitPocReference,para->vel.back());
            }''', 1)
        header.write_text(h)
        cpp.write_text('// '+marker+'\n'+c)


if __name__ == "__main__":
    apply(sys.argv[1])
