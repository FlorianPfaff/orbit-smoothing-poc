"""Numerical damping of a density MAP update without modifying its OU prior."""
from copy import deepcopy
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np


class DensityStepController:
    """Bound increments of the exponential force and suppress a detected two-cycle.

    This is adaptive relaxation, not an objective-monotone line search. No bound
    is imposed on the accumulated log density. Acceptance still requires a small
    *undamped* native update, followed by an undamped covariance confirmation.
    """
    def __init__(self, maximum_increment=.5, opposing_cosine=-.25, opposing_scale=.5):
        if not np.isfinite(maximum_increment) or maximum_increment <= 0:
            raise ValueError("The maximum accepted log-density increment must be positive")
        if not np.isfinite(opposing_cosine) or not -1 <= opposing_cosine < 0:
            raise ValueError("The opposing-direction cosine must be in [-1, 0)")
        if not np.isfinite(opposing_scale) or not 0 < opposing_scale < 1:
            raise ValueError("The opposing-direction scale must be in (0, 1)")
        self.maximum_increment = maximum_increment
        self.opposing_cosine = opposing_cosine
        self.opposing_scale = opposing_scale
        self.previous = None
        self.opposition_detected = False

    def choose(self, increment, *, confirmation=False):
        increment = np.asarray(increment, dtype=float)
        if increment.ndim != 1 or not np.all(np.isfinite(increment)):
            raise ValueError("A finite one-dimensional native density update is required")
        maximum = float(np.max(np.abs(increment), initial=0))
        cosine = None
        if self.previous is not None:
            denominator = float(np.linalg.norm(increment) * np.linalg.norm(self.previous))
            if denominator:
                cosine = float(np.dot(increment, self.previous) / denominator)
                self.opposition_detected |= cosine < self.opposing_cosine
        scale = min(1., self.maximum_increment / maximum) if maximum else 1.
        if self.opposition_detected:
            scale = min(scale, self.opposing_scale)
        if confirmation:
            scale = 1.  # The accepted posterior and its inverse are never damped.
        self.previous = increment.copy()
        return {"scale": scale, "direction_cosine": cosine,
                "opposition_detected": self.opposition_detected,
                "maximum_accepted_log_density_increment": scale * maximum,
                "scope": "Numerical adaptive relaxation; unchanged OU objective; no monotonicity guarantee"}


def damped_orbit_config(config, directory, vector, target_initial, scale):
    """Evaluate scaled density increments at the consistently damped initial state.

    Native variational epochs and interpolation conventions are preserved; there
    is no Python interpolation or re-encoding of orbit epochs.
    """
    from .backend import _save_xml
    from .initialization import _standalone

    directory = Path(directory)
    source = ET.parse(config["configs"]["variational"]).getroot()
    estimate = ET.parse(config["configs"]["estimate"]).getroot()
    model = estimate.find(".//leoDynamicOrbits")
    acceleration = model.find("parametrizationAcceleration")
    if acceleration is None or acceleration.find("logDensity") is None:
        raise ValueError("Damped trajectory evaluation requires the native density model")
    parameters = np.asarray(vector, dtype=float).copy()
    parameters[:-6] *= scale
    initial = np.asarray(target_initial, dtype=float)
    if initial.shape != (6,) or not np.all(np.isfinite(initial)):
        raise ValueError("Six finite physical initial-state components are required")
    for name, values in (("accepted_parameters.txt", parameters), ("accepted_initial_state.txt", initial)):
        (directory / name).write_text("groops matrix version=20200123\nMatrix( %d x 1 )\n" % len(values)
            + "\n".join(format(float(value), ".17g") for value in values) + "\n")
    orbit = directory / "accepted_orbit.dat"
    evaluate = ET.Element("OrbitPocEvaluateVariational")
    for name, value in (("inputfileVariational", config["native_paths"]["variational"]),
                        ("outputfileOrbit", orbit),
                        ("inputfileParameters", directory / "accepted_parameters.txt"),
                        ("inputfileInitialState", directory / "accepted_initial_state.txt")):
        ET.SubElement(evaluate, name).text = str(value)
    for name in ("ephemerides", "parametrizationAcceleration", "integrationDegree"):
        node = model.find(name)
        if node is not None:
            evaluate.append(deepcopy(node))
    conversion = ET.Element("FileConvert")
    ET.SubElement(conversion, "inputfile").text = str(orbit)
    ET.SubElement(conversion, "outputfile").text = str(orbit.with_suffix(".txt"))
    tree = _standalone(source, [evaluate, conversion], config["date"])
    return _save_xml(tree, directory / "accept_step.xml"), orbit
