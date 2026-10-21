"""Supplemental numerical regression; the frozen native suites are unchanged."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def test_compensated_quadrature_keeps_velocity_low_part(tmp_path):
    compiler = shutil.which("c++")
    assert compiler is not None, "C++ compiler required for this native correctness gate"
    binary = tmp_path / "compensated-quadrature"
    subprocess.run(
        [compiler, "-std=c++17", "-O3", "-DNDEBUG", "-Wall", "-Wextra",
         "-I", str(ROOT / "groops/extension"),
         str(ROOT / "tests/fixtures/tangent_compensated_quadrature.cpp"),
         "-o", str(binary)], check=True, capture_output=True, text=True, timeout=90,
    )
    result = subprocess.run([str(binary)], check=True, capture_output=True,
                            text=True, timeout=30)
    assert result.stdout == "compensated quadrature regression passed\n"
