"""Exercise the C++ step helper installed in native radiation-pressure physics."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import pytest

EXTENSION = Path(__file__).resolve().parents[1] / "groops/extension"


def test_thermal_endpoint_and_integer_equivalence(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("Native C++ compiler unavailable")
    source = tmp_path / "endpoint.cpp"
    source.write_text(r'''
#include "thermalIntegrationStep.h"
#include <cassert>
#include <cmath>
#include <utility>
std::pair<double,double> advance(double time, double target, bool patched)
{
  double absorbed=0., temperature=300.;
  while(time < target)
  {
    const double dt=patched ? orbitPocThermalStep(target-time) : 1.;
    const double fraction=dt/(target-time);
    if(patched) assert(fraction>0 && fraction<=1);
    absorbed += fraction*(1.-absorbed);
    temperature += dt/1000.*(absorbed-.01*temperature);
    time += dt;
    if(patched) assert(time<=target);
  }
  return {time,temperature};
}
int main()
{
  assert(advance(0.,2.5,true).first==2.5);
  assert(advance(2.5,5.,true).first==5.);
  assert(advance(0.,2.5,false).first==3.); // reproduce upstream defect
  for(int target=1;target<=100;target++)
    assert(advance(0.,target,true)==advance(0.,target,false));
  assert(orbitPocThermalStep(.125)==.125);
  assert(orbitPocThermalStep(5.)==1.);
  for(double maximum:{.5,.25,.1,.05})
  {
    double elapsed=0.;
    while(elapsed<2.5)
    {
      const double dt=orbitPocThermalStep(2.5-elapsed,maximum);
      assert(dt>0. && dt<=maximum && dt<=2.5-elapsed);
      elapsed+=dt;
    }
    assert(elapsed==2.5);
  }
}
''')
    binary = tmp_path / "endpoint"
    subprocess.run([compiler, "-std=c++17", "-I", str(EXTENSION), str(source),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)


def test_thermal_patch_idempotence(tmp_path):
    spec = importlib.util.spec_from_file_location("native_thermal", EXTENSION / "native_thermal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = tmp_path / "source/classes/miscAccelerations/miscAccelerationsRadiationPressure.h"
    target.parent.mkdir(parents=True)
    target.write_text('''#include "classes/miscAccelerations/miscAccelerations.h"
  Double                      factorSun, factorEarth, factorThermal;
    readConfig(config, "factorThermalRadiation",          factorThermal,    Config::DEFAULT,  "1.0",  "Thermal (re-)radiation is multiplied by this factor");
          constexpr Double dt = 1.; // integration step size [seconds]
          while(state->time < time)
          {
            axpy(dt/(time-state->time).seconds(), absorbedPressure - state->absorbedPressure, state->absorbedPressure);
          }
''')
    module.apply(tmp_path)
    first = target.read_bytes()
    module.apply(tmp_path)
    assert target.read_bytes() == first
    assert b"orbitPocThermalStep((time-state->time).seconds(), orbitPocThermalMaximumStep)" in first
    assert b'Config::DEFAULT, "1"' in first
    assert b"std::isfinite(orbitPocThermalMaximumStep)" in first
    assert (tmp_path / "source/misc/orbitPoc/thermalIntegrationStep.h").read_bytes() == (EXTENSION / "thermalIntegrationStep.h").read_bytes()
