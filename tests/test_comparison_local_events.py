"""Exercise actual native local-time crossing detection, not a Python replica."""
from pathlib import Path
import os
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.backend import read_native_table


def _run(binary, directory, states, *, events=False):
    np.savetxt(directory / "states.txt", states, fmt="%.18e")
    root = ET.Element("groops")
    node = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocForceDesign")
    for tag, name in (("inputfileStates", "states.txt"), ("outputfileDesign", "design.txt"),
                      ("outputfileLocalSolarPhase", "phase.txt")):
        ET.SubElement(node, tag).text = str(directory / name)
    if events:
        ET.SubElement(node, "outputfileLocalEvents").text = str(directory / "events.txt")
    ET.SubElement(ET.SubElement(node, "force"), "syntheticGravity")
    path = directory / "events.xml"
    ET.ElementTree(root).write(path, encoding="utf-8")
    result = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-2000:]+result.stderr[-2000:]
    return read_native_table(directory / "phase.txt", 2)


@pytest.mark.parametrize("direction", [-1, 1])
@pytest.mark.parametrize("step", [2.5, 5.])
def test_native_fractional_local_midnight_and_no_noon_event(tmp_path, direction, step):
    value = os.environ.get("ORBIT_POC_GROOPS")
    if not value:
        pytest.skip("ORBIT_POC_GROOPS is required for actual native local-time events")
    binary = Path(value).resolve()
    seconds = np.arange(0., 120.+step/2, step)
    mjd = 60424+seconds/86400
    states = np.column_stack((mjd, np.tile([7e6, 0., 100., 0., 0., 0.], (len(seconds), 1))))
    baseline = _run(binary, tmp_path, states)
    # Native phase supplies only the astronomical offset. Rotation then imposes
    # a known smooth phase sweep with one independently specified crossing.
    native_seconds = (mjd-mjd[0])*86400
    crossing = 53.123
    for offset, expected_count in ((0., 1), (np.pi, 0)):
        target = offset+direction*.001*(native_seconds-crossing)
        rotation = target-baseline[:, 1]
        states[:, 1] = 7e6*np.cos(rotation)
        states[:, 2] = 7e6*np.sin(rotation)
        phase = _run(binary, tmp_path, states, events=True)
        np.testing.assert_allclose(np.remainder(phase[:, 1]-target+np.pi, 2*np.pi)-np.pi,
                                   0., atol=5e-14)
        if expected_count:
            rows = read_native_table(tmp_path / "events.txt", 2)
            assert rows.shape[0] == expected_count
            assert abs(rows[0, 1]-crossing) < 2e-6
        else:
            with pytest.raises(ValueError, match="No consistent numeric table"):
                read_native_table(tmp_path / "events.txt", 2)
