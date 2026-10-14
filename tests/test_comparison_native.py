"""Executable native gates; set ORBIT_POC_GROOPS to the pinned extended binary."""
from pathlib import Path
import os
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.backend import read_native_table


@pytest.fixture
def native_binary():
    value = os.environ.get("ORBIT_POC_GROOPS")
    if not value:
        pytest.skip("ORBIT_POC_GROOPS is required for actual native gates")
    path = Path(value).resolve()
    assert path.is_file(), "The explicitly requested native binary is missing"
    return path


def _configuration(directory, knots, states):
    np.savetxt(directory / "knots.txt", knots, fmt="%.16e")
    np.savetxt(directory / "states.txt", states, fmt="%.16e")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocForceDesign")
    for tag, name in (("inputfileStates", "states.txt"), ("outputfileDesign", "design.txt"),
                      ("outputfileIntegrationWindows", "windows.txt")):
        ET.SubElement(program, tag).text = str(directory / name)
    for tag in ("force", "parametrizationAcceleration"):
        density = ET.SubElement(ET.SubElement(program, tag), "logDensity")
        ET.SubElement(ET.SubElement(density, "nominalDrag"), "syntheticDrag")
        ET.SubElement(density, "inputfileLogDensity").text = str(directory / "knots.txt")
    path = directory / "gate.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    return path


def _run(binary, config, directory):
    result = subprocess.run([str(binary), str(config)], cwd=directory, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    return read_native_table(directory / "design.txt", 13)


def test_native_density_derivatives_and_piecewise_quadrature(native_binary, tmp_path):
    times = 60000 + np.arange(0., 125., 5.) / 86400
    states = np.column_stack((times, np.tile([6878137., 700., 1200., -1., 7400., 100.], (len(times), 1))))
    knots = np.column_stack((60000 + np.array([0., 60., 120.]) / 86400, [.13, -.24, .31]))
    config = _configuration(tmp_path, knots, states)
    original = _run(native_binary, config, tmp_path)
    actual = original[:, 4:].reshape(-1, 3, 3)
    step = 1e-5
    for index in range(3):
        up, down = knots.copy(), knots.copy()
        up[index, 1] += step
        down[index, 1] -= step
        _configuration(tmp_path, up, states)
        plus = _run(native_binary, config, tmp_path)[:, 1:4]
        _configuration(tmp_path, down, states)
        minus = _run(native_binary, config, tmp_path)[:, 1:4]
        np.testing.assert_allclose((plus-minus)/(2*step), actual[:, :, index], rtol=1e-5, atol=1e-12)
    windows = read_native_table(tmp_path / "windows.txt", 3).astype(int)
    assert len(windows) == len(times)-1
    for interval, left, right in windows:
        segment_left = 0 if interval < 12 else 12
        segment_right = 12 if interval < 12 else 24
        assert segment_left <= left <= interval < interval+1 <= right <= segment_right


def test_native_rejects_grid_that_cannot_resolve_knots(native_binary, tmp_path):
    times = 60000 + np.arange(0., 150., 30.) / 86400
    states = np.column_stack((times, np.tile([6878137., 0., 0., 0., 7400., 0.], (len(times), 1))))
    knots = np.column_stack((60000 + np.array([0., 60., 120.]) / 86400, [0., 0., 0.]))
    config = _configuration(tmp_path, knots, states)
    result = subprocess.run([str(native_binary), str(config)], cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert result.returncode != 0
    assert "insufficient epochs" in result.stdout + result.stderr or "grid too coarse" in result.stdout + result.stderr
