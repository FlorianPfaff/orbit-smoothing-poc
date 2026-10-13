#!/usr/bin/env python3
"""Correct the pinned upstream thermal integrator's fractional-second endpoint.

Upstream's unconditional one-second Euler step overshoots e.g. 2.5 s and
extrapolates the last absorbed-pressure update. This patch preserves that Euler
model, clipping the final fractional step. Native time rounding can also change
complete integer-grid runs; no bitwise-equivalence claim is made.
"""
from pathlib import Path
import argparse
import shutil


def apply(source):
    source = Path(source) / "source"
    target = source / "misc/orbitPoc/thermalIntegrationStep.h"
    target.parent.mkdir(parents=True, exist_ok=True)
    helper = Path(__file__).with_name("thermalIntegrationStep.h")
    if not target.exists() or target.read_bytes() != helper.read_bytes():
        shutil.copyfile(helper, target)
    path = source / "classes/miscAccelerations/miscAccelerationsRadiationPressure.h"
    text = path.read_text()
    include = '#include "misc/orbitPoc/thermalIntegrationStep.h"'
    before = """          constexpr Double dt = 1.; // integration step size [seconds]
          while(state->time < time)
          {
"""
    previous = """          // ORBIT_POC_THERMAL_ENDPOINT_V1: preserve the exact requested epoch.
          while(state->time < time)
          {
            const Double dt = orbitPocThermalStep((time-state->time).seconds());
"""
    after = previous.replace("orbitPocThermalStep((time-state->time).seconds())",
                             "orbitPocThermalStep((time-state->time).seconds(), orbitPocThermalMaximumStep)")
    if after not in text:
        anchor = previous if previous in text else before
        if text.count(anchor) != 1:
            raise ValueError("Pinned thermal integration endpoint anchor changed")
        text = text.replace(anchor, after, 1)
    marker = "ORBIT_POC_THERMAL_MAXIMUM_STEP_V2"
    if marker not in text:
        anchor = "  Double                      factorSun, factorEarth, factorThermal;"
        if text.count(anchor) != 1:
            raise ValueError("Pinned thermal parameter anchor changed")
        text = text.replace(anchor, anchor + "\n  Double                      orbitPocThermalMaximumStep; // " + marker, 1)
        anchor = '    readConfig(config, "factorThermalRadiation",          factorThermal,    Config::DEFAULT,  "1.0",  "Thermal (re-)radiation is multiplied by this factor");'
        if text.count(anchor) != 1:
            raise ValueError("Pinned thermal configuration anchor changed")
        text = text.replace(anchor, anchor + '\n    readConfig(config, "orbitPocThermalMaximumStep", orbitPocThermalMaximumStep, Config::DEFAULT, "1", "Maximum clipped Euler thermal step in seconds; independently refine numerical setting");\n    if(!isCreateSchema(config) && (!std::isfinite(orbitPocThermalMaximumStep) || orbitPocThermalMaximumStep<=0))\n      throw(Exception("Thermal maximum step must be finite and positive"));', 1)
    if include not in text:
        anchor = '#include "classes/miscAccelerations/miscAccelerations.h"'
        if text.count(anchor) != 1:
            raise ValueError("Pinned thermal include anchor changed")
        text = text.replace(anchor, anchor + "\n" + include, 1)
    if text != path.read_text():
        path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
