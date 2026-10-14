"""The post-fit derivative diagnostic must preserve source epochs and native bytes."""
from decimal import Decimal
import importlib.util
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest


@pytest.fixture
def diagnostic(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "density_diagnostic_test", scripts / "check_density_trajectory_derivative.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("offset", [0, 18])
def test_native_diagnostic_boundaries_keep_source_time_origin(diagnostic, tmp_path, offset):
    executable = os.environ.get("ORBIT_POC_GROOPS")
    if not executable:
        pytest.skip("Set ORBIT_POC_GROOPS to exercise exact native Time construction")
    source = ET.fromstring(f"""<groops><global>
      <time label="timeStart">60424</time>
      <time label="timeEnd">timeStart+120.1/86400</time>
      <double label="arcStartOffsetSeconds">{offset}</double>
    </global></groops>""")
    tree = diagnostic.standalone_tree(source)
    node = ET.SubElement(ET.SubElement(tree, "program"), "TimeSeriesCreate")
    path = tmp_path / "boundaries.txt"
    ET.SubElement(node, "outputfileTimeSeries").text = str(path)
    series = ET.SubElement(ET.SubElement(node, "timeSeries"), "uniformSampling")
    for name, value in (("timeStart", "loopTime"), ("timeEnd", "loopTimeEnd"),
                        ("sampling", "60/86400"), ("offsetSeconds", str(offset))):
        ET.SubElement(series, name).text = value
    diagnostic.resolve_source_loop(node, "2024-04-24")
    assert series.findtext("timeStart") == "timeStart"
    assert series.findtext("timeEnd") == "timeEnd"
    config = tmp_path / "times.xml"
    ET.ElementTree(tree).write(config)
    completed = subprocess.run([str(Path(executable).resolve()), str(config)],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"})
    assert completed.returncode == 0, completed.stdout + completed.stderr
    epochs = [Decimal(line.split()[0]) for line in path.read_text().splitlines()
              if line.strip().startswith("60424")]
    assert len(epochs) == 3
    seconds = [(epoch-Decimal(60424))*86400 for epoch in epochs]
    assert max(abs(actual-Decimal(expected)) for actual, expected in
               zip(seconds, [offset, offset+60, offset+120])) < Decimal("1e-9")


def test_derivative_rejects_mismatched_native_binary(diagnostic, tmp_path):
    executable = tmp_path / "native"
    executable.write_bytes(b"original executable")
    expected = diagnostic.file_hash(executable)
    with pytest.raises(ValueError, match="exact fitted native executable"):
        diagnostic.checked_binary(executable, {}, tmp_path / "missing-hash")
    executable.write_bytes(b"changed executable")
    with pytest.raises(ValueError, match="exact fitted native executable"):
        diagnostic.checked_binary(executable, {"native_binary_sha256": expected}, tmp_path / "mismatch")
    assert not (tmp_path / "mismatch").exists()


def test_derivative_freezes_matching_native_binary(diagnostic, tmp_path):
    executable = tmp_path / "native"
    executable.write_bytes(b"matching executable")
    expected = diagnostic.file_hash(executable)
    frozen = diagnostic.checked_binary(executable, {"native_binary_sha256": expected}, tmp_path / "frozen")
    assert frozen != executable
    assert diagnostic.file_hash(frozen) == expected
