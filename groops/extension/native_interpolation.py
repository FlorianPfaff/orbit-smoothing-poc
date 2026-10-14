#!/usr/bin/env python3
"""Install shared boundary-aware native orbit/design interpolation.

Positions include the continuous pulse endpoint. Velocity stencils exclude its
post-pulse value on the left and select the right limit at the pulse itself.
SLR installs the same boundaries before station preprocessing/light-time work.
"""
from pathlib import Path
import argparse
import shutil


def replace(text, before, after):
    if text.count(before) != 1:
        raise ValueError(f"Expected one pinned native interpolation anchor: {before[:100]!r}")
    return text.replace(before, after, 1)


def apply(source):
    source = Path(source) / "source"
    destination = source / "misc/orbitPoc/piecewisePolynomial.h"
    destination.parent.mkdir(parents=True, exist_ok=True)
    header = Path(__file__).with_name("piecewisePolynomial.h")
    if not destination.exists() or destination.read_bytes() != header.read_bytes():
        shutil.copyfile(header, destination)
    path = source / "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.h"
    text = path.read_text()
    if "OrbitPocPiecewisePolynomial" not in text:
        text = replace(text, '#include "base/import.h"', '#include "base/import.h"\n#include "misc/orbitPoc/piecewisePolynomial.h"')
        text = replace(text, "std::vector<Polynomial>        polynomial;", "std::vector<OrbitPocPiecewisePolynomial> polynomial;")
        path.write_text(text)
        cpp = path.with_suffix(".cpp")
        text = cpp.read_text()
        text = replace(text, "para->polynomial.emplace_back(para->times.back(), interpolationDegree, TRUE/*throwException*/, FALSE/*leastSquares*/, -(interpolationDegree+1.1), -1.1, 1e-7);",
                       "para->polynomial.emplace_back(para->times.back(), interpolationDegree, parametrizationAcceleration->integrationBoundaries(), pulsesInterval);")
        text = replace(text, "para->polynomial.back().interpolate(times, para->vel.back(), 3)",
                       "para->polynomial.back().interpolate(times, para->vel.back(), 3, TRUE/*velocity jumps*/)")
        text = replace(text, "para->polynomial.at(arcNo).interpolate(times, para->vel.at(arcNo), 3)",
                       "para->polynomial.at(arcNo).interpolate(times, para->vel.at(arcNo), 3, TRUE/*velocity jumps*/)")
        cpp.write_text(text)
    # Keep exact split-day Time records for downstream propagation/prediction.
    # Native instrument ASCII itself uses long double, but Python or generic
    # Matrix readers can reduce MJD to double and lose sub-microsecond timing.
    # Binary avoids relying on those intermediate readers' decimal precision.
    path = source / "gnss/gnssParametrization/gnssParametrizationLeoDynamicOrbits.h"
    text = path.read_text()
    if "fileNameOrbitNative" not in text:
        text = replace(text, "fileNameOrbit, fileNameParameter,", "fileNameOrbit, fileNameOrbitNative, fileNameParameter,")
        path.write_text(text)
        cpp = path.with_suffix(".cpp")
        text = cpp.read_text()
        anchor = '    readConfig(config, "outputfileOrbit",             fileNameOrbit,               Config::OPTIONAL, "",     "variable {station} available");'
        text = replace(text, anchor, anchor+'\n    readConfig(config,"outputfileOrbitNative",fileNameOrbitNative,Config::OPTIONAL,"","binary .dat orbit preserving native epoch precision");')
        anchor = '          InstrumentFile::write(fileNameOrbit(fileNameVariableList).appendBaseName(suffix), arcList);'
        text = replace(text, anchor, anchor+'\n          if(!fileNameOrbitNative.empty())\n            InstrumentFile::write(fileNameOrbitNative(fileNameVariableList).appendBaseName(suffix),arcList);')
        cpp.write_text(text)
    path = source / "slr/slrSatellite.h"
    text = path.read_text()
    if "orbitPocPolynomial" not in text:
        text = replace(text, '#include "base/polynomial.h"', '#include "base/polynomial.h"\n#include "misc/orbitPoc/piecewisePolynomial.h"')
        text = replace(text, "  Polynomial        polynomial;", "  Polynomial        polynomial;\n  std::shared_ptr<OrbitPocPiecewisePolynomial> orbitPocPolynomial;")
        text = replace(text, "return Vector3d(polynomial.interpolate({time}, pos));",
                       "return Vector3d(orbitPocPolynomial ? orbitPocPolynomial->interpolate({time},pos) : polynomial.interpolate({time},pos));")
        text = replace(text, "return Vector3d(polynomial.interpolate({time}, vel));",
                       "return Vector3d(orbitPocPolynomial ? orbitPocPolynomial->interpolate({time},vel,1,TRUE) : polynomial.interpolate({time},vel));")
        path.write_text(text)
    path = source / "slr/slr.h"
    text = path.read_text()
    if "orbitPocBoundaries" not in text:
        text = replace(text, "EarthRotationPtr earthRotation, SlrParametrizationPtr parametrization);",
                       "EarthRotationPtr earthRotation, SlrParametrizationPtr parametrization,\n            const std::vector<Time> &orbitPocBoundaries={}, const std::vector<Time> &orbitPocPulses={}, UInt orbitPocDegree=7);")
        path.write_text(text)
        cpp = path.with_suffix(".cpp")
        text = cpp.read_text()
        text = replace(text, "EarthRotationPtr earthRotation, SlrParametrizationPtr parametrization)\n{",
                       "EarthRotationPtr earthRotation, SlrParametrizationPtr parametrization,\n               const std::vector<Time> &orbitPocBoundaries, const std::vector<Time> &orbitPocPulses, UInt orbitPocDegree)\n{")
        text = replace(text, "    // init stations\n", "    if(!orbitPocBoundaries.empty() || !orbitPocPulses.empty())\n      for(auto satellite:satellites)\n        satellite->orbitPocPolynomial=std::make_shared<OrbitPocPiecewisePolynomial>(satellite->times,orbitPocDegree,orbitPocBoundaries,orbitPocPulses);\n\n    // init stations\n")
        cpp.write_text(text)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    apply(parser.parse_args().source)
