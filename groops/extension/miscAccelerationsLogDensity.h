// SPDX-License-Identifier: GPL-3.0-or-later
#ifndef ORBIT_POC_MISC_ACCELERATIONS_LOG_DENSITY_H
#define ORBIT_POC_MISC_ACCELERATIONS_LOG_DENSITY_H
#ifdef DOCSTRING_MiscAccelerations
static const char *docstringMiscAccelerationsLogDensity = R"(\subsection{LogDensity}
Multiply only the configured nominal drag acceleration by the exponential of
piecewise linear log-density knots. Rebuild the force model when knots change.)";
#endif
#include "classes/miscAccelerations/miscAccelerations.h"
#include "misc/orbitPoc/logDensitySeries.h"

class MiscAccelerationsLogDensity : public MiscAccelerationsBase
{
  MiscAccelerationsPtr nominalDrag;
  std::unique_ptr<LogDensitySeries> series;
public:
  explicit MiscAccelerationsLogDensity(Config &config)
  {
    FileName path;
    readConfig(config,"nominalDrag",nominalDrag,Config::MUSTSET,"","drag only, not total force");
    readConfig(config,"inputfileLogDensity",path,Config::MUSTSET,"","GPS MJD and log multiplier");
    if(!isCreateSchema(config)) series = std::make_unique<LogDensitySeries>(path);
  }
  Vector3d acceleration(SatelliteModelPtr satellite,const Time &time,const Vector3d &position,
      const Vector3d &velocity,const Rotary3d &rotSat,const Rotary3d &rotEarth,EphemeridesPtr ephemerides) override
  {
    return series->multiplier(time)*nominalDrag->acceleration(satellite,time,position,velocity,rotSat,rotEarth,ephemerides);
  }
};
#endif
