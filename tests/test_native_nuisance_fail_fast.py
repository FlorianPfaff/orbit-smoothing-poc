"""Opt-in replay rejection without changing the original native QR suite.

The GROOPS cases require ORBIT_POC_V31_NATIVE.  The independent callback probe
compiles the production search header, with only GROOPS's scalar aliases stubbed;
it exercises real fork isolation, not a Python replacement for the controller.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

import pytest


FLAG = "ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY"
EXTENSION = Path(__file__).resolve().parents[1] / "groops" / "extension"
INVALID_OPTIONS = ("", "2", "-1", "true", "false", "01", "1 ", " 0")


def _environment(value: str | None) -> dict[str, str]:
    env = dict(os.environ)
    env.pop(FLAG, None)
    if value is not None:
        env[FLAG] = value
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1",
               MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    return env


@pytest.fixture(scope="module")
def native() -> str:
    value = os.environ.get("ORBIT_POC_V31_NATIVE")
    if not value:
        pytest.skip("set ORBIT_POC_V31_NATIVE to the isolated candidate executable")
    assert Path(value).is_file(), value
    return value


def _native_search(native: str, directory: Path, mode: str, flag: str | None,
                   *, success: bool = True) -> dict | None:
    (directory / "rows.txt").write_text(
        "groops matrix version=20200123\nMatrix( 1 x 2 )\n1 0\n")
    root = ET.Element("groops")
    program = ET.SubElement(ET.SubElement(root, "program"), "OrbitPocQrSolve")
    fields = {"inputfileRows": directory / "rows.txt",
              "outputfileSolution": directory / "search.json",
              "outputPrefix": directory / "qr", "nuisanceFixture": mode}
    for name, value in fields.items():
        ET.SubElement(program, name).text = str(value)
    config = directory / "run.xml"
    ET.ElementTree(root).write(config)
    result = subprocess.run([native, str(config)], cwd=directory,
                            env=_environment(flag), capture_output=True,
                            text=True, timeout=60)
    (directory / "native.log").write_text(result.stdout + result.stderr)
    if not success:
        assert result.returncode != 0
        assert f"{FLAG} must be 0 or 1" in result.stdout + result.stderr
        assert not (directory / "search.json").exists()
        # The fixture opens this before calling the controller.  No successful
        # search continuation or child write may be mistaken for completion.
        assert (directory / "qr.parent.txt").read_text() == "parent\n"
        return None
    assert result.returncode == 0, result.stdout + result.stderr
    assert (directory / "qr.parent.txt").read_text() == "parent\npreserved\n"
    return json.loads((directory / "search.json").read_text())


@pytest.mark.parametrize("flag", [None, "0", "1"], ids=["default", "legacy", "early"])
@pytest.mark.parametrize("mode", ["reject", "support", "exception", "floor_zero_replay"])
def test_native_invalid_replay_keeps_legacy_work_unless_opted_in(native, tmp_path, mode, flag):
    report = _native_search(native, tmp_path, mode, flag)
    assert report["accepted"] is False
    assert report["stationary_without_update"] is False
    assert report["nuisance_floor_limited"] is False
    assert report["alpha"] == 0
    assert len(report["trials"]) == (0 if flag == "1" else 17)
    replay = report["zero_update_replay"]
    if mode == "exception":
        assert replay["status"] != 0
        assert "injected child failure" in replay["error"]
    elif mode in ("reject", "floor_zero_replay"):
        assert replay["status"] == 0
        assert replay["actual_reduction"] != 0
    if flag == "1":
        assert report["floor_rejection"] == "zero_update_replay_failed"
        assert report["undamped_maximum_update_m"] is None
        assert report["nuisance_floor_audit"] == []
    elif mode in ("support", "exception"):
        assert all(trial["status"] != 0 for trial in report["trials"])


@pytest.mark.parametrize("flag", [None, "0", "1"], ids=["default", "legacy", "early"])
@pytest.mark.parametrize("mode", ["accept", "stationary"])
def test_native_valid_replay_preserves_acceptance_and_stationarity(native, tmp_path, mode, flag):
    report = _native_search(native, tmp_path, mode, flag)
    replay = report["zero_update_replay"]
    assert replay["status"] == 0
    assert replay["actual_reduction"] == 0
    assert replay["maximum_update_m"] == 0
    assert report["nuisance_floor_limited"] is False
    if mode == "accept":
        assert report["accepted"] is True
        assert report["stationary_without_update"] is False
        assert report["alpha"] == .25
        assert len(report["trials"]) == 3
        assert report["undamped_maximum_update_m"] == 4.95
        assert report["trials"][-1]["actual_reduction"] > 0
    else:
        assert report["accepted"] is False
        assert report["stationary_without_update"] is True
        assert report["alpha"] == 0
        assert len(report["trials"]) == 1
        assert report["undamped_maximum_update_m"] == 1e-10


@pytest.mark.parametrize("flag", INVALID_OPTIONS)
def test_native_rejects_noncanonical_flag_values(native, tmp_path, flag):
    _native_search(native, tmp_path, "accept", flag, success=False)


@pytest.fixture(scope="module")
def callback_probe(tmp_path_factory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("a C++17 compiler is required for the production-header callback probe")
    directory = tmp_path_factory.mktemp("nuisance-fail-fast-callback")
    (directory / "base").mkdir()
    (directory / "base" / "import.h").write_text(
        "#pragma once\n#include <sstream>\n#include <stdexcept>\n"
        "using Double=double;using UInt=unsigned;using Bool=bool;\n"
        "constexpr bool TRUE=true,FALSE=false;using Exception=std::runtime_error;\n")
    shutil.copyfile(EXTENSION / "nuisanceLineSearch.h", directory / "nuisanceLineSearch.h")
    source = directory / "probe.cpp"
    source.write_text(r'''
#include "nuisanceLineSearch.h"
int main(int argc,char **argv)
{
  if(argc!=3)return 2;
  const std::string output=argv[1],callbacks=argv[2];
  double parentState=42.;
  auto evaluate=[&](double alpha)
  {
    // Open after descriptor isolation: this proves whether any callback ran.
    std::ofstream marker(callbacks,std::ios::app);marker<<std::setprecision(17)<<alpha<<'\n';marker.close();
    parentState=-1.;
    orbitPocQr::NuisanceTrial trial;trial.support=123;trial.rows=1;
    trial.change=std::fabs(alpha);trial.reduction=alpha==0.?0.:-1.;trial.cost=10.-trial.reduction;
    return trial;
  };
  try
  {
    const auto search=orbitPocQr::searchNuisance(10.,1.,1e-8,123,1,evaluate);
    if(parentState!=42.)throw(Exception("callback mutated parent state"));
    orbitPocQr::writeNuisanceSearch(output,search,10.,1.);
    return 0;
  }
  catch(const std::exception &error){std::cerr<<error.what()<<'\n';return 23;}
}
''')
    binary = directory / "probe"
    result = subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra",
                             "-I", str(directory), str(source), "-o", str(binary)],
                            text=True, capture_output=True, timeout=60)
    (directory / "compile.log").write_text(result.stdout + result.stderr)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("flag", [None, "0", "1"], ids=["default", "legacy", "early"])
def test_valid_zero_replay_does_not_shortcut_rejected_proposals(callback_probe, tmp_path, flag):
    output, callbacks = tmp_path / "search.json", tmp_path / "callbacks.txt"
    result = subprocess.run([str(callback_probe), str(output), str(callbacks)],
                            env=_environment(flag), text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(output.read_text())
    assert report["accepted"] is False
    assert report["stationary_without_update"] is False
    assert report["nuisance_floor_limited"] is False
    assert report["floor_rejection"] == "arithmetic_audit_unavailable"
    assert report["zero_update_replay"]["actual_reduction"] == 0
    assert report["zero_update_replay"]["maximum_update_m"] == 0
    assert report["undamped_maximum_update_m"] == 1
    assert len(report["trials"]) == 17
    assert [float(line) for line in callbacks.read_text().splitlines()] == [
        0., *[2. ** -attempt for attempt in range(17)]]


@pytest.mark.parametrize("flag", INVALID_OPTIONS)
def test_invalid_flag_is_rejected_before_any_child_callback(callback_probe, tmp_path, flag):
    output, callbacks = tmp_path / "search.json", tmp_path / "callbacks.txt"
    result = subprocess.run([str(callback_probe), str(output), str(callbacks)],
                            env=_environment(flag), text=True, capture_output=True, timeout=30)
    assert result.returncode == 23
    assert f"{FLAG} must be 0 or 1" in result.stderr
    assert not callbacks.exists()
    assert not output.exists()
