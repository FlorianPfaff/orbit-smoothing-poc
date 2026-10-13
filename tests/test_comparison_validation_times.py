"""Validation epochs must preserve the exact UTC-day native time origin."""
from decimal import Decimal
import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest


@pytest.mark.parametrize("offset", [0, 18])
def test_offgrid_epochs_use_exact_native_seconds(tmp_path, offset):
    source = Path(__file__).resolve().parents[1] / "scripts/validate_comparison_native.py"
    spec = importlib.util.spec_from_file_location("native_validation_time_test", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tree = ET.Element("groops")
    evaluate = ET.SubElement(ET.SubElement(tree, "program"), "OrbitPocEvaluateVariational")
    ET.SubElement(evaluate, "outputfileOrbit").text = "unused.dat"
    module.add_offgrid_interpolation(tree, tmp_path, 60424 + offset / 86400., 120., 5.)
    rows = (tmp_path / "offgrid_epochs.txt").read_text().splitlines()[3:]
    seconds = [(Decimal(row.split()[0]) - Decimal(60424)) * Decimal(86400) - offset for row in rows]
    for expected in (Decimal("0.123"), Decimal("59.877"), Decimal("60"), Decimal("60.123")):
        assert min(abs(second - expected) for second in seconds) < Decimal("1e-10")
    boundaries = tree.findall("program")[-1].find(".//interpolationBoundaries/uniformSampling")
    assert boundaries.findtext("timeStart") == "60424"
    assert boundaries.findtext("offsetSeconds") == str(offset)
