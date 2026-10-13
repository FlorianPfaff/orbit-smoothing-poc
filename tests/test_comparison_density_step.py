"""Adaptive relaxation keeps the fitted OU model and raw convergence criterion."""
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.backend import read_native_table
from orbit_poc.comparison.density_step import DensityStepController, damped_orbit_config


def test_two_cycle_is_damped_without_changing_fixed_point():
    controller = DensityStepController()
    estimate = 0.
    history = []
    # The undamped fixed-point iteration is g -> 1-2g: it diverges, while its
    # unique stationary point is 1/3. The same raw equation is used when damped.
    for _ in range(32):
        raw = np.array([1.-3.*estimate])
        step = controller.choose(raw)
        history.append((estimate, raw[0], step["scale"]))
        estimate += step["scale"] * raw[0]
    assert controller.opposition_detected
    assert abs(estimate-1./3.) < 1e-9
    assert abs(history[-1][1]) < 1e-8
    assert all(abs(scale*increment) <= .5 for _, increment, scale in history)


def test_exponential_force_can_reach_large_density_without_clipping():
    controller = DensityStepController()
    estimate = 0.
    for _ in range(48):
        force = np.exp(estimate)
        # Scalar least squares (exp(g)-10000)^2 + g^2: the prior remains g^2,
        # and only the numerical Gauss-Newton update is relaxed.
        raw = np.array([(force*(10000.-force)-estimate)/(force*force+1.)])
        step = controller.choose(raw)
        estimate += step["scale"] * raw[0]
    assert estimate > 9.
    assert abs(raw[0]) < 1e-8
    assert abs(np.exp(estimate)-10000.) < .001


def test_final_confirmation_is_undamped_even_after_opposition():
    controller = DensityStepController()
    controller.choose(np.array([2., -1.]))
    opposed = controller.choose(np.array([-2., 1.]))
    assert opposed["scale"] == .25
    confirmed = controller.choose(np.array([-1e-5, 1e-5]), confirmation=True)
    assert confirmed["opposition_detected"]
    assert confirmed["scale"] == 1.
    assert confirmed["maximum_accepted_log_density_increment"] == 1e-5


@pytest.mark.parametrize("parameters", [dict(maximum_increment=0), dict(maximum_increment=np.inf),
    dict(opposing_cosine=.1), dict(opposing_scale=1), dict(opposing_scale=0)])
def test_invalid_numerical_controls_rejected(parameters):
    with pytest.raises(ValueError):
        DensityStepController(**parameters)


def test_native_damped_configuration_preserves_epochs_and_full_density_prior(tmp_path):
    source = tmp_path / "variational.xml"
    source.write_text('<groops><global><time label="timeStart">60424</time>'
        '<time label="timeEnd">60425</time></global></groops>')
    estimate = tmp_path / "estimate.xml"
    estimate.write_text('''<groops><program><GnssProcessing><parametrization>
      <leoDynamicOrbits><ephemerides><jpl/></ephemerides><integrationDegree>7</integrationDegree>
        <parametrizationAcceleration><logDensity><inputfileLogDensity>full-reference.txt</inputfileLogDensity>
          <timeSeries><uniformSampling><timeStart>loopTime</timeStart><offsetSeconds>18</offsetSeconds>
          </uniformSampling></timeSeries></logDensity></parametrizationAcceleration>
      </leoDynamicOrbits></parametrization><parametrization><logDensityOu>
        <tau>7200</tau><sigma>0.3</sigma></logDensityOu></parametrization>
      </GnssProcessing></program></groops>''')
    original = estimate.read_bytes()
    config = {"date":"2024-04-24", "configs":{"variational":source, "estimate":estimate},
              "native_paths":{"variational":tmp_path / "variational.dat"}}
    vector = np.arange(9, dtype=float)
    target = np.array([7e6, 0., 1., 0., 7500., 3.])
    path, orbit = damped_orbit_config(config, tmp_path, vector, target, .25)
    tree = ET.parse(path)
    node = tree.find(".//OrbitPocEvaluateVariational")
    parameters = read_native_table(node.findtext("inputfileParameters")).ravel()
    np.testing.assert_array_equal(parameters[:3], .25*vector[:3])
    # These six columns are replaced by native physical-state reanchoring.
    np.testing.assert_array_equal(parameters[3:], vector[3:])
    np.testing.assert_array_equal(read_native_table(node.findtext("inputfileInitialState")).ravel(), target)
    assert node.findtext(".//timeStart") == "timeStart"
    assert node.findtext(".//offsetSeconds") == "18"
    assert tree.findtext("global/time[@label='timeStart']") == "60424"
    assert orbit.suffix == ".dat"
    assert estimate.read_bytes() == original  # No damping term or modified OU row.
    assert tree.find(".//logDensityOu") is None  # Only numerical trajectory evaluation.
