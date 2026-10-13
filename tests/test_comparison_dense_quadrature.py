"""Output-grid refinement must preserve each fixed atmospheric interpolant."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_nonpolynomial_dense_mesh_consistency(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    root = Path(__file__).resolve().parents[1]
    binary = tmp_path / "dense_quadrature"
    subprocess.run([compiler, "-std=c++17", "-O2", "-I", str(root / "groops/extension"),
                    str(root / "tests/fixtures/dense_quadrature.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, capture_output=True, text=True, timeout=60)
