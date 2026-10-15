#!/usr/bin/env python3
"""Install the opt-in v3.1 coupled six-state derivatives into a disposable tree.

Run after all v3 patches. Legacy configurations keep the old numerical path.
Synthetic derivatives are dispatched through the actual force instances, so
constants and log-density scaling cannot diverge from forward propagation.
"""
from pathlib import Path
import argparse
import shutil


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Pinned GROOPS derivative anchor changed: " + before[:100])
    return text.replace(before, after, 1)


SIGNATURE = """Bool orbitPocStateJacobian(SatelliteModelPtr satellite,const Time &time,
      const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
      const Rotary3d &rotEarth,EphemeridesPtr ephemerides,MatrixSliceRef positionJac,MatrixSliceRef velocityJac)"""


def apply(source):
    root = Path(source) / "source"
    here = Path(__file__).resolve().parent
    target = root / "misc/orbitPoc"
    target.mkdir(parents=True, exist_ok=True)
    for name in ("syntheticForceDerivatives.h", "sixStateTangent.h", "finiteDifferenceForceJacobian.h", "stagedVariationalBody.h"):
        if not (target / name).exists() or (here / name).read_bytes() != (target / name).read_bytes():
            shutil.copyfile(here / name, target / name)
    for name in ("orbitPocStateDerivatives.cpp", "orbitPocPredictSignals.cpp"):
        destination = root / "programs/gnss" / name
        if not destination.exists() or (here / name).read_bytes() != destination.read_bytes():
            shutil.copyfile(here / name, destination)
        path = root / "sourcesCXX.txt"
        text = path.read_text()
        if "programs/gnss/" + name not in text:
            text = replace(text, "programs/gnss/gnssSimulateReceiver.cpp", "programs/gnss/gnssSimulateReceiver.cpp\nprograms/gnss/" + name)
            path.write_text(text)

    path = root / "classes/miscAccelerations/miscAccelerations.h"
    text = path.read_text()
    if "orbitPocStateJacobian" not in text:
        text = replace(text, "  /// Constructor.", "  " + SIGNATURE + ";\n\n  /// Constructor.")
        text = replace(text, "virtual ~MiscAccelerationsBase() {}", "virtual ~MiscAccelerationsBase() {}\nvirtual " + SIGNATURE + " {return FALSE;}\n")
        path.write_text(text)
        path = path.with_suffix(".cpp")
        text = path.read_text() + """
// ORBIT_POC_SIX_STATE_DERIVATIVES_V31
Bool MiscAccelerations::orbitPocStateJacobian(SatelliteModelPtr satellite,const Time &time,
    const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
    const Rotary3d &rotEarth,EphemeridesPtr ephemerides,MatrixSliceRef positionJac,MatrixSliceRef velocityJac)
{
  for(auto *component:acc)
  {
    Matrix p(3,3),v(3,3);
    if(!component->orbitPocStateJacobian(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,p,v))return FALSE;
    axpy(1.,p,positionJac);axpy(1.,v,velocityJac);
  }
  return TRUE;
}
"""
        path.write_text(text)

    implementations = {
        "miscAccelerationsSyntheticGravity.h": """
    const auto jac=OrbitPoc::syntheticGravityJacobian({position.x(),position.y(),position.z()},GM,J2,R);
""",
        "miscAccelerationsSyntheticDrag.h": """
    const auto jac=OrbitPoc::syntheticDragJacobian({position.x(),position.y(),position.z()},
        {velocity.x(),velocity.y(),velocity.z()},ballisticCoefficient,referenceDensity,referenceAltitude,scaleHeight,earthRadius,earthRotationRate);
""",
    }
    for name, body in implementations.items():
        path = root / "classes/miscAccelerations" / name
        text = path.read_text()
        if "orbitPocStateJacobian" not in text:
            text = replace(text, '#include "classes/miscAccelerations/miscAccelerations.h"', '#include "classes/miscAccelerations/miscAccelerations.h"\n#include "misc/orbitPoc/syntheticForceDerivatives.h"')
            method = "\n  " + SIGNATURE + " override\n  {" + body + """
    for(UInt i=0;i<3;i++)for(UInt j=0;j<3;j++)
    {positionJac(i,j)=jac.position[3*i+j];velocityJac(i,j)=jac.velocity[3*i+j];}
    return TRUE;
  }
"""
            text = replace(text, "\n};\n#endif", method + "};\n#endif")
            path.write_text(text)

    path = root / "classes/miscAccelerations/miscAccelerationsLogDensity.h"
    text = path.read_text()
    if "orbitPocStateJacobian" not in text:
        method = "\n  " + SIGNATURE + " override\n  {\n" + """
    if(!nominalDrag->orbitPocStateJacobian(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,positionJac,velocityJac))return FALSE;
    const Double multiplier=series->multiplier(time);positionJac*=multiplier;velocityJac*=multiplier;
    return TRUE;
  }
"""
        text = replace(text, "\n};\n#endif", method + "};\n#endif")
        path.write_text(text)

    path = root / "classes/forces/forces.h"
    text = path.read_text()
    if "orbitPocSyntheticJacobian" not in text:
        text = replace(text, "  /// Constructor.", """  // V3.1 derives from the actual force objects, never a duplicated recipe.
  void orbitPocSyntheticJacobian(SatelliteModelPtr satellite,const Time &time,
      const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
      const Rotary3d &rotEarth,EphemeridesPtr ephemerides,MatrixSliceRef positionJac,MatrixSliceRef velocityJac) const;
  Tensor3d orbitPocForwardGravityGradient(const Time &time,const Vector3d &position,const Rotary3d &rotEarth) const;

  /// Constructor.""")
        text = replace(text, "private:\n", "private:\n  Bool orbitPocHasGravity=FALSE,orbitPocHasTides=FALSE;\n")
        path.write_text(text)
        path = path.with_suffix(".cpp")
        text = path.read_text()
        text = replace(text, '    readConfig(config, "gravityfield",', '    orbitPocHasGravity=readConfig(config, "gravityfield",')
        text = replace(text, '    readConfig(config, "tides",', '    orbitPocHasTides=readConfig(config, "tides",')
        text += """
void Forces::orbitPocSyntheticJacobian(SatelliteModelPtr satellite,const Time &time,
    const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
    const Rotary3d &rotEarth,EphemeridesPtr ephemerides,MatrixSliceRef positionJac,MatrixSliceRef velocityJac) const
{
  if(orbitPocHasGravity || orbitPocHasTides || !miscAccelerations ||
      !miscAccelerations->orbitPocStateJacobian(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,positionJac,velocityJac))
    throw(Exception("synthetic_complete_v1 requires only analytically supported synthetic force components"));
}

Tensor3d Forces::orbitPocForwardGravityGradient(const Time &time,const Vector3d &position,const Rotary3d &rotEarth) const
{
  if(!orbitPocHasGravity || !gravityfield)throw(Exception("flight_gravity_drag_v1 requires the configured forward gravity field"));
  return rotEarth.inverseRotate(gravityfield->gravityGradient(time,rotEarth.rotate(position)));
}
"""
        path.write_text(text)

    path = root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
    text = path.read_text()
    if "ORBIT_POC_SIX_STATE_DERIVATIVES_V31" not in text:
        text = replace(text, '#include "programs/program.h"', '#include "programs/program.h"\n#include "misc/orbitPoc/sixStateTangent.h"\n#include "misc/orbitPoc/finiteDifferenceForceJacobian.h"')
        text = replace(text, "  ForcesPtr                      forces;", """  ForcesPtr                      forces;
  // ORBIT_POC_SIX_STATE_DERIVATIVES_V31
  std::string orbitPocDerivativeProfile="legacy_v3";
  FileName orbitPocDerivativeDiagnostics;""")
        anchor = '    readConfig(config, "forces",                      forces,                 Config::MUSTSET,   "", "");'
        text = replace(text, anchor, anchor + """
    readConfig(config,"orbitPocDerivativeProfile",orbitPocDerivativeProfile,Config::DEFAULT,"legacy_v3","legacy_v3, synthetic_complete_v1, or flight_gravity_drag_v1");
    readConfig(config,"orbitPocDerivativeDiagnostics",orbitPocDerivativeDiagnostics,Config::OPTIONAL,"","JSON record of the opt-in six-state tangent and remaining approximations");
    if(!isCreateSchema(config) && orbitPocDerivativeProfile!="legacy_v3" && orbitPocDerivativeProfile!="synthetic_complete_v1" && orbitPocDerivativeProfile!="flight_gravity_drag_v1")
      throw(Exception("unknown orbitPocDerivativeProfile"));""")
        text = replace(text, "      tensor.at(i)      = rotEarth.at(i).inverseRotate(gradientfield->gravityGradient(orbit.at(i).time, posEarth));", "      if(orbitPocDerivativeProfile==\"legacy_v3\")\n        tensor.at(i) = rotEarth.at(i).inverseRotate(gradientfield->gravityGradient(orbit.at(i).time, posEarth));")
        text = replace(text, "    // State matrix: position partial derivatives with respect to boundary values", '#include "misc/orbitPoc/stagedVariationalBody.h"\n\n    // State matrix: position partial derivatives with respect to boundary values')
        path.write_text(text)
    # Also upgrade early development trees bearing the v3.1 marker.
    text = path.read_text()
    anchor = '    readConfig(config, "gradientfield",     gradientfield,     Config::MUSTSET,'
    if anchor in text:
        text = replace(text, anchor, '    readConfig(config, "gradientfield",     gradientfield,     orbitPocDerivativeProfile=="legacy_v3" ? Config::MUSTSET : Config::OPTIONAL,')
        path.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
