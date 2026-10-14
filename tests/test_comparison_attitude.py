"""Canonical atmospheric attitude must preserve upstream quaternion semantics."""
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.backend import read_native_table


def test_native_canonical_attitude_matches_upstream_resampling(tmp_path):
    binary = os.environ.get("ORBIT_POC_GROOPS")
    if not binary:
        pytest.skip("ORBIT_POC_GROOPS required for actual native attitude regression")
    epochs = np.arange(0., 200., 5.)
    angle = .04 * epochs
    quaternions = np.column_stack((np.cos(.5 * angle), np.zeros((len(angle), 2)), np.sin(.5 * angle)))
    # The physical rotation is smooth; native matrix-to-quaternion conversion
    # changes sign branches along this arc. Deliberate source sign flips are
    # also harmless to physical rotations and must not enter interpolation.
    quaternions[::3] *= -1
    camera = tmp_path / "camera.txt"
    with camera.open("w") as stream:
        stream.write(f"groops instrument version=20200123\n-7 1\n{len(epochs)}\n")
        for t, q in zip(epochs, quaternions):
            stream.write(f"{Decimal(60424)+Decimal(str(t))/Decimal(86400):.18f} " + " ".join(f"{x:.17e}" for x in q) + "\n")
    queries = tmp_path / "queries.txt"
    query_times = np.arange(2.623, 192., 2.5)
    with queries.open("w") as stream:
        stream.write(f"groops instrument version=20200123\n-3 1\n{len(query_times)}\n")
        for t in query_times:
            stream.write(f"{Decimal(60424)+Decimal(str(t))/Decimal(86400):.18f} 0\n")
    states = np.column_stack((60424 + epochs/86400, np.tile([6878137., 0., 0., 0., 7500., 0.], (len(epochs), 1))))
    np.savetxt(tmp_path / "states.txt", states, fmt="%.17e")
    tree = ET.Element("groops")
    def program(name):
        return ET.SubElement(ET.SubElement(tree, "program"), name)
    def field(parent, key, value):
        ET.SubElement(parent, key).text = str(value)
    p = program("OrbitPocForceDesign")
    for key, name in (("inputfileStates", "states.txt"), ("outputfileDesign", "forces.txt"),
                      ("inputfileStarCamera", "camera.txt"), ("outputfileAttitudeInterpolation", "rotations.txt")):
        field(p, key, tmp_path / name)
    ET.SubElement(ET.SubElement(p, "force"), "syntheticGravity")
    field(ET.SubElement(ET.SubElement(p, "attitudeTimeSeries"), "instrument"), "inputfileInstrument", queries)
    p = program("InstrumentResample")
    field(p, "inputfileInstrument", camera)
    field(p, "outputfileInstrument", tmp_path / "upstream.txt")
    interpolation = ET.SubElement(ET.SubElement(p, "method"), "polynomial")
    for key, value in (("polynomialDegree", 7), ("maxDataPointRange", -8.1), ("maxExtrapolationDistance", -1.1)):
        field(interpolation, key, value)
    field(ET.SubElement(ET.SubElement(p, "timeSeries"), "instrument"), "inputfileInstrument", queries)
    path = tmp_path / "attitude.xml"
    ET.ElementTree(tree).write(path, encoding="utf-8")
    result = subprocess.run([str(Path(binary).resolve()), str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    actual = read_native_table(tmp_path / "rotations.txt", 10)[:, 1:].reshape(-1, 3, 3)
    q = read_native_table(tmp_path / "upstream.txt", 5)[:, 1:]
    w, x, y, z = q.T
    expected = np.array([[w*w+x*x-y*y-z*z, 2*(x*y-z*w), 2*(x*z+y*w)],
                         [2*(x*y+z*w), w*w-x*x+y*y-z*z, 2*(y*z-x*w)],
                         [2*(x*z-y*w), 2*(y*z+x*w), w*w-x*x-y*y+z*z]]).transpose(2, 0, 1)
    np.testing.assert_allclose(actual, expected, rtol=0, atol=2e-14)
    np.testing.assert_allclose(actual.transpose(0, 2, 1) @ actual, np.broadcast_to(np.eye(3), actual.shape), rtol=0, atol=2e-14)
    np.testing.assert_allclose(np.linalg.det(actual), 1., rtol=0, atol=2e-14)
