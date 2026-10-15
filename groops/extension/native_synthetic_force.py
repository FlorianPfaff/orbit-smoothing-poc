"""Install synthetic-only CRF and reference-residual force arithmetic.

Run after the existing derivative dispatch. All values come from actual force
instances; unsupported components fail closed. Legacy/flight calls stay intact.
"""
from pathlib import Path
import shutil


SIGNATURE = """Bool orbitPocSyntheticForceParts(SatelliteModelPtr satellite,const Time &time,
      const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
      const Rotary3d &rotEarth,EphemeridesPtr ephemerides,OrbitPoc::SyntheticForceParts &parts)"""


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError("Pinned synthetic force arithmetic anchor changed: " + before[:100])
    return text.replace(before, after, 1)


def apply(source):
    root = Path(source) / "source"
    header = Path(__file__).with_name("syntheticForceArithmetic.h")
    target = root / "misc/orbitPoc" / header.name
    if not target.exists() or target.read_bytes() != header.read_bytes():
        shutil.copyfile(header, target)
    path = root / "classes/miscAccelerations/miscAccelerations.h"
    text = path.read_text()
    if "orbitPocSyntheticForceParts" not in text:
        text = replace(text, '#include "base/import.h"', '#include "base/import.h"\n#include "misc/orbitPoc/syntheticForceArithmetic.h"')
        text = replace(text, "  /// Constructor.", "  " + SIGNATURE + ";\n\n  /// Constructor.")
        text = replace(text, "virtual ~MiscAccelerationsBase() {}", "virtual ~MiscAccelerationsBase() {}\nvirtual " + SIGNATURE + " {return FALSE;}\n")
        path.write_text(text)
        path = path.with_suffix(".cpp")
        text = path.read_text() + """
// ORBIT_POC_SYNTHETIC_FORCE_ARITHMETIC_V1
Bool MiscAccelerations::orbitPocSyntheticForceParts(SatelliteModelPtr satellite,const Time &time,
    const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
    const Rotary3d &rotEarth,EphemeridesPtr ephemerides,OrbitPoc::SyntheticForceParts &parts)
{
  // Preserve the ordinary aggregate's actual satellite-state update and frames.
  if(satellite)
  {
    Vector3d positionSun;
    if(ephemerides)positionSun=ephemerides->position(time,Ephemerides::SUN);
    satellite->changeState(time,position,velocity,positionSun,rotSat,rotEarth);
  }
  OrbitPoc::SyntheticForceParts sum;
  for(auto *component:acc)
  {
    OrbitPoc::SyntheticForceParts value;
    if(!component->orbitPocSyntheticForceParts(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,value))return FALSE;
    value.validate();sum.add(value);
  }
  sum.validate();parts=sum;
  return TRUE;
}
"""
        path.write_text(text)
    for name in ("miscAccelerationsSyntheticGravity.h", "miscAccelerationsSyntheticDrag.h", "miscAccelerationsLogDensity.h"):
        path = root / "classes/miscAccelerations" / name
        text = path.read_text()
        if "orbitPocSyntheticForceParts" in text:
            continue
        if name == "miscAccelerationsLogDensity.h":
            body = """
    if(!nominalDrag->orbitPocSyntheticForceParts(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,parts))return FALSE;
    parts.scale(series->multiplier(time));parts.validate();
"""
        else:
            body = """
    // Only these synthetic classes use rotEarth solely as the output frame.
    const auto direct=acceleration(satellite,time,position,velocity,rotSat,Rotary3d(),ephemerides);
    parts.full={direct.x(),direct.y(),direct.z()};
"""
            if name == "miscAccelerationsSyntheticGravity.h":
                body += """
    Double radius;Vector3d j2;orbitPocGravityParts(position,radius,j2);
    parts.centralGM=GM;parts.noncentral={j2.x(),j2.y(),j2.z()};
"""
            else:
                body += "    parts.noncentral=parts.full;\n"
            body += "    parts.validate();\n"
        method = "\n  " + SIGNATURE + " override\n  {" + body + "    return TRUE;\n  }\n"
        text = replace(text, "\n};\n#endif", method + "};\n#endif")
        path.write_text(text)
    path = root / "classes/forces/forces.h"
    text = path.read_text()
    if "orbitPocSyntheticForceParts" not in text:
        text = replace(text, "  /// Constructor.", """  OrbitPoc::SyntheticForceParts orbitPocSyntheticForceParts(SatelliteModelPtr satellite,const Time &time,
      const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
      const Rotary3d &rotEarth,EphemeridesPtr ephemerides) const;

  /// Constructor.""")
        path.write_text(text)
        path = path.with_suffix(".cpp")
        path.write_text(path.read_text() + """
OrbitPoc::SyntheticForceParts Forces::orbitPocSyntheticForceParts(SatelliteModelPtr satellite,const Time &time,
    const Vector3d &position,const Vector3d &velocity,const Rotary3d &rotSat,
    const Rotary3d &rotEarth,EphemeridesPtr ephemerides) const
{
  OrbitPoc::SyntheticForceParts parts;
  if(orbitPocHasGravity || orbitPocHasTides || !miscAccelerations ||
      !miscAccelerations->orbitPocSyntheticForceParts(satellite,time,position,velocity,rotSat,rotEarth,ephemerides,parts))
    throw(Exception("synthetic_complete_v1 requires explicitly supported synthetic force arithmetic"));
  parts.validate();return parts;
}
""")
    path = root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
    text = path.read_text()
    if "ORBIT_POC_SYNTHETIC_FORCE_ARITHMETIC_V1" not in text:
        old = """      force.at(k) = rotEarth.at(k).inverseRotate(forces->acceleration(satellite, orbit.at(k).time, orbit.at(k).position, orbit.at(k).velocity,
                                         starCamera.at(k).rotary, rotEarth.at(k), earthRotation, ephemerides));"""
        text = replace(text, old, """      // ORBIT_POC_SYNTHETIC_FORCE_ARITHMETIC_V1
      if(orbitPocDerivativeProfile=="synthetic_complete_v1")
      {
        const auto parts=forces->orbitPocSyntheticForceParts(satellite,orbit.at(k).time,orbit.at(k).position,orbit.at(k).velocity,
            starCamera.at(k).rotary,rotEarth.at(k),ephemerides);
        force.at(k)=Vector3d(static_cast<Double>(parts.full[0]),static_cast<Double>(parts.full[1]),static_cast<Double>(parts.full[2]));
      }
      else
""" + old)
        old = """        g(3*i+0) -= epoch.acceleration.x();
        g(3*i+1) -= epoch.acceleration.y();
        g(3*i+2) -= epoch.acceleration.z();"""
        text = replace(text, old, """        if(orbitPocDerivativeProfile=="synthetic_complete_v1")
        {
          const auto parts=forces->orbitPocSyntheticForceParts(satellite,times.at(i),orbit.at(i).position,orbit.at(i).velocity,
              starCamera.at(i).rotary,rotEarth.at(i),ephemerides);
          const auto reduced=OrbitPoc::syntheticReferenceResidual(parts,
              {orbit.at(i).position.x(),orbit.at(i).position.y(),orbit.at(i).position.z()},
              {epoch.position.x(),epoch.position.y(),epoch.position.z()},GM);
          for(UInt axis=0;axis<3;axis++)g(3*i+axis)=static_cast<Double>(reduced[axis]);
        }
        else
        {
""" + old + "\n        }")
        path.write_text(text)

def apply_reference_precision(source):
    """Synthetic reference evaluation only; preserve the original installer API.

    Installed after apply(), including on fresh upstream checkouts. Keeping this
    separate also lets the earlier force-decomposition fixtures retain their
    deliberately small source skeletons without weakening anchor validation.
    """
    root = Path(source) / "source"
    header = Path(__file__).with_name("preciseEquinoctialReference.h")
    shutil.copyfile(header, root / "misc/orbitPoc" / header.name)
    path = root / "programs/preprocessing/preprocessingVariationalEquation.cpp"
    text = path.read_text()
    marker = "ORBIT_POC_PRECISE_EQUINOCTIAL_REFERENCE_V1"
    if marker in text:
        return
    text = replace(text, '#include "base/equinoctial.h"',
                   '#include "base/equinoctial.h"\n#include "misc/orbitPoc/preciseEquinoctialReference.h"')
    text = replace(text, '    Vector velRef(3*epochCount);', '''    Vector velRef(3*epochCount);
    // ORBIT_POC_PRECISE_EQUINOCTIAL_REFERENCE_V1
    std::vector<long double> orbitPocReferencePositionLow(3*epochCount),orbitPocReferenceVelocityLow(3*epochCount);
    Double orbitPocReferencePositionDifference=0,orbitPocReferenceVelocityDifference=0;''')
    anchor = '        referenceOrbit.orbit(times.at(i), epoch.position, epoch.velocity, epoch.acceleration);'
    text = replace(text, anchor, anchor + '''
        OrbitPoc::PreciseReferenceState orbitPocPreciseReference;
        if(orbitPocDerivativeProfile=="synthetic_complete_v1")
        {
          const long double elapsed=(static_cast<long double>(times.at(i).mjdInt())-referenceOrbit.tau.mjdInt())*86400.L
              +(static_cast<long double>(times.at(i).mjdMod())-referenceOrbit.tau.mjdMod())*86400.L;
          orbitPocPreciseReference=OrbitPoc::preciseEquinoctialReference(
              {referenceOrbit.GM,referenceOrbit.a,referenceOrbit.h,referenceOrbit.k,referenceOrbit.p,referenceOrbit.q,referenceOrbit.l0},elapsed);
          long double dp2=0,dv2=0;
          for(UInt axis=0;axis<3;axis++)
          {
            const long double dp=orbitPocPreciseReference.position[axis]-epoch.position.vector()(axis);
            const long double dv=orbitPocPreciseReference.velocity[axis]-epoch.velocity.vector()(axis);
            dp2+=dp*dp;dv2+=dv*dv;
            const Double roundedPosition=orbitPocPreciseReference.position[axis];
            const Double roundedVelocity=orbitPocPreciseReference.velocity[axis];
            orbitPocReferencePositionLow[3*i+axis]=orbitPocPreciseReference.position[axis]-roundedPosition;
            orbitPocReferenceVelocityLow[3*i+axis]=orbitPocPreciseReference.velocity[axis]-roundedVelocity;
          }
          orbitPocReferencePositionDifference=std::max(orbitPocReferencePositionDifference,static_cast<Double>(std::sqrt(dp2)));
          orbitPocReferenceVelocityDifference=std::max(orbitPocReferenceVelocityDifference,static_cast<Double>(std::sqrt(dv2)));
          epoch.position=Vector3d(orbitPocPreciseReference.position[0],orbitPocPreciseReference.position[1],orbitPocPreciseReference.position[2]);
          epoch.velocity=Vector3d(orbitPocPreciseReference.velocity[0],orbitPocPreciseReference.velocity[1],orbitPocPreciseReference.velocity[2]);
        }''')
    text = replace(text, '''          const auto reduced=OrbitPoc::syntheticReferenceResidual(parts,
              {orbit.at(i).position.x(),orbit.at(i).position.y(),orbit.at(i).position.z()},
              {epoch.position.x(),epoch.position.y(),epoch.position.z()},GM);''', '''          const auto reduced=OrbitPoc::preciseSyntheticReferenceResidual(parts,
              {orbit.at(i).position.x(),orbit.at(i).position.y(),orbit.at(i).position.z()},
              orbitPocPreciseReference.position,GM);''')
    path.write_text(text)
