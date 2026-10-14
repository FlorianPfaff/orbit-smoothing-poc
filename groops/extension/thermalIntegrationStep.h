// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_THERMAL_INTEGRATION_STEP_H
#define ORBIT_POC_THERMAL_INTEGRATION_STEP_H
#include <algorithm>

// Never extrapolate absorbed pressure or advance the thermal state beyond the
// requested force epoch. The configurable maximum is independently refined;
// exact integer-step arithmetic at the default reproduces the upstream update.
inline double orbitPocThermalStep(const double remainingSeconds, const double maximumStep=1.)
{
  return std::min(maximumStep, remainingSeconds);
}
#endif
