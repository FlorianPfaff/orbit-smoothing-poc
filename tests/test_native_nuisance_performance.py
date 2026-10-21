"""Installer admission and compiled instrumentation/transaction isolation checks.

These tests do not replace full native GNSS state-level equivalence gates.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "groops/extension"


def _module():
    spec = importlib.util.spec_from_file_location("native_nuisance_performance", EXT / "native_nuisance_performance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _source_fixture(root):
    """Pinned hook contexts only; this is an installer, not GNSS, fixture."""
    module = _module()
    processing = root / module.PROCESSING
    processing.parent.mkdir(parents=True)
    processing.write_text('''// ORBIT_POC_SCALED_ROW_QR_V31
// ORBIT_POC_TRANSACTIONAL_NUISANCE_V31
    if(!noiseModel.arOrder)
    {
      gnss->designMatrix(normalEquationInfo, eqn, A);
      return;
    }
void GnssProcessingStep::State::buildNormals(Bool constraintsOnly, Bool solveEpochParameters)
{
  try
  {
      buildNormals(FALSE,FALSE);
      const std::string mode="profile_step";
        trial.receiverPositionChange=receiverPositionChange;trial.receiverTimeChange=receiverTimeChange;trial.changedReceiverTimes=changedReceiverTimes;
      orbitPocQr::writeNuisanceSearch(stem+".nuisance_line_search.json",search,before,prediction);
  }
}
''')
    search = root / module.SEARCH
    search.parent.mkdir(parents=True)
    search.write_bytes((EXT / "nuisanceLineSearch.h").read_bytes())
    dynamic = root / module.DYNAMIC
    dynamic.parent.mkdir(parents=True)
    dynamic.write_text("""void design() {
      matMult(1., eqn.A.column(GnssObservationEquation::idxPosRecv, 3),
              para->polynomial.at(arcNo).interpolateOffset({eqn.timeRecv}, para->PosDesign.at(arcNo), {eqn.receiver->timeRemainder(eqn.idEpoch)}, 3), A.column(para->index));
}
""")
    return module


def test_installer_is_hash_verified_and_idempotent(tmp_path):
    module = _source_fixture(tmp_path)
    receipt = module.apply(tmp_path)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert module.apply(tmp_path) == receipt
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    processing = (tmp_path / module.PROCESSING).read_text()
    assert processing.count("gnss->designMatrix(normalEquationInfo, eqn, A);") == 1
    assert "performance.skip()" not in processing
    assert receipt["runtime_default"] == "0"


@pytest.mark.parametrize("corruption", ["missing_anchor", "duplicate_anchor", "missing_prerequisite"])
def test_installer_rejects_drift_before_any_write(tmp_path, corruption):
    module = _source_fixture(tmp_path)
    p = tmp_path / module.PROCESSING
    text = p.read_text()
    if corruption == "missing_anchor":
        text = text.replace("if(!noiseModel.arOrder)", "if (noiseModel.arOrder == 0)")
    elif corruption == "duplicate_anchor":
        text += '      buildNormals(FALSE,FALSE);\n      const std::string mode="profile";\n'
    else:
        text = text.replace("ORBIT_POC_TRANSACTIONAL_NUISANCE_V31", "old_version")
    p.write_text(text)
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(ValueError):
        module.apply(tmp_path)
    assert before == {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


def test_installer_rejects_modified_installed_file(tmp_path):
    module = _source_fixture(tmp_path)
    module.apply(tmp_path)
    p = tmp_path / module.SEARCH
    p.write_text(p.read_text() + "// drift\n")
    with pytest.raises(ValueError, match="file changed"):
        module.apply(tmp_path)


def test_installer_rejects_unattributed_partial_installation(tmp_path):
    module = _source_fixture(tmp_path)
    (tmp_path / module.HEADER).write_text("// partial\n")
    with pytest.raises(ValueError, match="partial"):
        module.apply(tmp_path)


def test_installer_accepts_exact_header_copied_by_base_extension(tmp_path):
    module = _source_fixture(tmp_path)
    (tmp_path / module.HEADER).write_bytes((EXT / "nuisancePerformance.h").read_bytes())
    module.apply(tmp_path)


def test_build_flag_rejects_without_numerics_before_source_access(tmp_path):
    source, build = tmp_path / "absent-source", tmp_path / "absent-build"
    result = subprocess.run([sys.executable, str(ROOT / "scripts/build_groops.py"),
                             "--source-dir", str(source), "--build-dir", str(build),
                             "--nuisance-performance", "--configure-only"],
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 2
    assert "--nuisance-performance requires --numerics" in result.stderr
    assert not source.exists() and not build.exists()


def _build_reentry(tmp_path, monkeypatch, *, installed_segmented=False,
                   installed_wide=False, selected_segmented=False,
                   selected_wide=False, selected_nuisance=True):
    source, build = tmp_path / "source-tree", tmp_path / "build-tree"
    installer = _source_fixture(source)
    installer.apply(source)
    for present, name in ((installed_segmented, "segmented"), (installed_wide, "wide-tangent")):
        if present:
            (source / f"orbit-poc-{name}-extension.json").write_text("{}\n")
    spec = importlib.util.spec_from_file_location("build_groops_reentry", ROOT / "scripts/build_groops.py")
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    revision_calls, run_calls = [], []

    def revision(command, **kwargs):
        revision_calls.append(command)
        assert command == ["git", "-C", str(source), "rev-parse", "HEAD"]
        assert kwargs == {"text": True}
        return builder.COMMIT + "\n"

    def run(command, **kwargs):
        run_calls.append(([str(x) for x in command], kwargs))

    monkeypatch.setattr(builder.subprocess, "check_output", revision)
    monkeypatch.setattr(builder, "run", run)
    argv = ["build_groops.py", "--source-dir", str(source), "--build-dir", str(build),
            "--numerics", "--configure-only"]
    if selected_nuisance:
        argv.append("--nuisance-performance")
    if selected_segmented:
        argv.append("--segmented")
    if selected_wide:
        argv.append("--wide-tangent-candidate")
    monkeypatch.setattr(sys, "argv", argv)
    before = {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    return builder, source, build, before, run_calls, revision_calls


def test_build_reentry_requires_opt_in_before_any_installer(tmp_path, monkeypatch):
    builder, source, build, before, calls, revisions = _build_reentry(
        tmp_path, monkeypatch, selected_nuisance=False)
    with pytest.raises(ValueError, match="retain --nuisance-performance"):
        builder.main()
    assert len(revisions) == 1 and calls == []
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert not build.exists()


@pytest.mark.parametrize("installed_segmented,installed_wide,selected_segmented,selected_wide", [
    (True, False, False, False), (False, False, True, False),
    (True, True, True, False), (True, False, True, True),
])
def test_build_reentry_rejects_profile_drift_before_installer(
        tmp_path, monkeypatch, installed_segmented, installed_wide, selected_segmented, selected_wide):
    builder, source, build, before, calls, revisions = _build_reentry(
        tmp_path, monkeypatch, installed_segmented=installed_segmented,
        installed_wide=installed_wide, selected_segmented=selected_segmented,
        selected_wide=selected_wide)
    with pytest.raises(ValueError, match="profile differs"):
        builder.main()
    assert len(revisions) == 1 and calls == []
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert not build.exists()


@pytest.mark.parametrize("segmented,wide", [(False, False), (True, False), (True, True)])
def test_build_reentry_only_verifies_optional_extension_then_configures(
        tmp_path, monkeypatch, segmented, wide):
    builder, source, build, before, calls, revisions = _build_reentry(
        tmp_path, monkeypatch, installed_segmented=segmented, installed_wide=wide,
        selected_segmented=segmented, selected_wide=wide)
    builder.main()
    assert len(revisions) == 1 and len(calls) == 2
    assert calls[0] == ([sys.executable, str(EXT / "native_nuisance_performance.py"),
                         "--source", str(source)], {})
    assert calls[1][0] == ["cmake", "-S", str(source / "source"), "-B", str(build),
                          "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
                          "-DCMAKE_DISABLE_FIND_PACKAGE_MPI=ON"]
    assert "env" in calls[1][1]
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}


def test_build_reentry_failed_optional_verification_cannot_configure(tmp_path, monkeypatch):
    builder, source, build, before, calls, revisions = _build_reentry(tmp_path, monkeypatch)

    def failed_verifier(command, **kwargs):
        calls.append(([str(x) for x in command], kwargs))
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(builder, "run", failed_verifier)
    with pytest.raises(subprocess.CalledProcessError):
        builder.main()
    assert len(revisions) == 1 and len(calls) == 1
    assert calls[0][0][1] == str(EXT / "native_nuisance_performance.py")
    assert before == {p: p.read_bytes() for p in source.rglob("*") if p.is_file()}
    assert not build.exists()


@pytest.fixture(scope="module")
def compiled_probe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("nuisance-performance-probe")
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.fail("C++ compiler required for nuisance instrumentation gate")
    module = _source_fixture(directory)
    module.apply(directory)
    base = directory / "source/base"
    base.mkdir()
    (base / "import.h").write_text('''#pragma once
#include <sstream>
#include <stdexcept>
using Double=double;using UInt=unsigned;using Bool=bool;
constexpr bool TRUE=true,FALSE=false;
using Exception=std::runtime_error;
''')
    source = directory / "probe.cpp"
    source.write_text(r'''
#include <cassert>
#include <fstream>
#include "misc/orbitPoc/nuisanceLineSearch.h"
namespace perf=orbitPocNuisancePerformance;
namespace qr=orbitPocQr;
int main(int argc,char **argv)
{
  assert(argc==2);const std::string output=argv[1];
  unsetenv("ORBIT_POC_NUISANCE_INTERPOLATION_CACHE");
  unsetenv("ORBIT_POC_NUISANCE_PERFORMANCE");
  {perf::BuildMeasure build(true,false);perf::ObservationDesignMeasure design(true);}
  assert(!perf::metrics().available);
  qr::NuisanceSearch absent;perf::writeSearch(output+"/disabled.json",absent,perf::metrics());
  assert(!std::ifstream(output+"/disabled.json"));
  setenv("ORBIT_POC_NUISANCE_PERFORMANCE","invalid",1);
  bool rejected=false;try{perf::BuildMeasure build(true,false);}catch(const std::invalid_argument &){rejected=true;}
  assert(rejected);
  setenv("ORBIT_POC_NUISANCE_PERFORMANCE","1",1);
  {perf::BuildMeasure build(true,false);for(int i=0;i<5;i++){perf::ObservationDesignMeasure design(true);}}
  const auto parent=perf::metrics();
  assert(parent.available&&parent.completed&&!parent.costOnly&&parent.observationDesignCalls==5);
  auto evaluate=[](double alpha)
  {
    qr::NuisanceTrial trial;
    {
      perf::BuildMeasure build(true,true);
      for(int i=0;i<3;i++){perf::ObservationDesignMeasure design(true);}
      trial.cost=2*(1-alpha)*(1-alpha);trial.change=2*std::abs(alpha);
      trial.reduction=4*alpha-2*alpha*alpha;trial.support=41;trial.rows=7;trial.observationSignature=19;
    }
    trial.performance=perf::metrics();return trial;
  };
  auto search=qr::searchNuisance(2.,2.,1e-8,41,7,evaluate);
  assert(search.accepted&&search.alpha==1&&search.trials.size()==1);
  assert(search.zeroUpdateReplay.reduction==0);
  assert(perf::metrics().observationDesignCalls==5); // fork never updates parent
  assert(search.zeroUpdateReplay.performance.observationDesignCalls==3);
  assert(search.trials[0].performance.observationDesignCalls==3);
  assert(search.trials[0].performance.completed&&search.trials[0].performance.costOnly);
  assert(search.trials[0].wallSeconds>=search.trials[0].performance.buildWallSeconds);
  auto early=qr::isolatedNuisanceTrial(1.,[](double)->qr::NuisanceTrial{throw std::runtime_error("before build");});
  assert(early.status==1&&!early.performance.available); // not inherited parent metrics
  auto failed=qr::isolatedNuisanceTrial(1.,[](double)->qr::NuisanceTrial
  {perf::BuildMeasure build(true,true);perf::ObservationDesignMeasure design(true);throw std::runtime_error("inside build");});
  assert(failed.status==1&&failed.performance.available&&!failed.performance.completed);
  assert(failed.performance.observationDesignCalls==1);
  search.arithmeticAudits.push_back(early);search.arithmeticAudits.push_back(failed);
  qr::NuisanceProbeRound round;round.probes={search.trials[0],search.trials[0]};
  search.probeHistory.push_back(round);search.probes=round.probes;
  perf::writeSearch(output+"/performance.json",search,parent);

  // Native interpolation is called exactly once for identical represented
  // query/state keys. The helper never rounds Time or long-double remainder.
  int calls=0,owner=0,polynomial=0,design=0;
  auto compute=[&](){return ++calls;};
  auto query=[&](double fraction,long double remainder,std::uint64_t epoch=0,
                 std::uint64_t arc=0,std::uint64_t day=10,std::uint64_t receiver=0,
                 const void *keyOwner=nullptr,const void *keyPolynomial=nullptr,const void *keyDesign=nullptr)
  {
    return perf::interpolate(keyOwner?keyOwner:&owner,keyPolynomial?keyPolynomial:&polynomial,
      keyDesign?keyDesign:&design,receiver,epoch,arc,day,fraction,remainder,compute);
  };
  {perf::BuildMeasure build(true,false);assert(query(.25,0)==1);assert(query(.25,0)==2);}
  setenv("ORBIT_POC_NUISANCE_INTERPOLATION_CACHE","1",1);
  {
    perf::BuildMeasure build(true,false);
    assert(query(.25,0)==3);assert(query(.25,0)==3);
    assert(query(std::nextafter(.25,1.),0)==4);
    assert(query(.25,std::nextafter(0.L,1.L))==5);
    assert(query(.25,0.L)==6);assert(query(.25,-0.L)==7);
    assert(query(+0.,0.L)==8);assert(query(-0.,0.L)==9);
    assert(query(.25,0,1)==10);assert(query(.25,0,1,1)==11);
    assert(query(.25,0,1,1,11)==12);assert(query(.25,0,1,1,11,1)==13);
    int different=0;
    assert(query(.25,0,1,1,11,1,&different)==14);
    assert(query(.25,0,1,1,11,1,&different,&different)==15);
    assert(query(.25,0,1,1,11,1,&different,&different,&different)==16);
    setenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE","1",1);
    assert(query(.25,0,1,1,11,1,&different,&different,&different)==17);
    unsetenv("ORBIT_POC_NUMERICS_ARITHMETIC_AUDIT_MODE");
    const auto nan=std::numeric_limits<long double>::quiet_NaN();
    assert(query(.25,nan)==18);assert(query(.25,nan)==19);
    assert(perf::metrics().interpolationCacheHits==1);
    assert(perf::metrics().interpolationCalls==18);
  }
  assert(query(.25,0)==20);assert(query(.25,0)==21); // outside a build: always original
  {perf::BuildMeasure build(true,true);assert(query(.25,0)==22);assert(query(.25,0)==22);}
  // Instrumentation disabled does not lengthen cache lifetime.
  setenv("ORBIT_POC_NUISANCE_PERFORMANCE","0",1);
  {perf::BuildMeasure build(true,true);assert(query(.25,0)==23);assert(query(.25,0)==23);}
  assert(!perf::metrics().available);assert(query(.25,0)==24);
  try{perf::BuildMeasure build(true,true);assert(query(.25,0)==25);throw std::runtime_error("scope failure");}
  catch(const std::runtime_error &){}
  assert(!perf::context().active);assert(query(.25,0)==26);
  bool fail=true;int evaluations=0;
  auto maybeFail=[&](){evaluations++;if(fail)throw std::runtime_error("interpolation failed");return 42;};
  {
    perf::BuildMeasure build(true,true);
    auto invoke=[&](){return perf::interpolate(&owner,&polynomial,&design,0,0,0,10,.25,0,maybeFail);};
    try{invoke();assert(false);}catch(const std::runtime_error &){}
    fail=false;assert(invoke()==42);assert(invoke()==42);assert(evaluations==2);
  }
  setenv("ORBIT_POC_NUISANCE_INTERPOLATION_CACHE","invalid",1);
  rejected=false;try{perf::BuildMeasure build(true,false);}catch(const std::invalid_argument &){rejected=true;}
  assert(rejected&&!perf::context().active);
}
''')
    executable = directory / "probe"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-I", str(directory / "source"), str(source), "-o", str(executable)], check=True, capture_output=True, text=True, timeout=60)
    return executable


def test_compiled_metrics_reset_fork_isolation_failure_and_accounting(compiled_probe, tmp_path):
    env = dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
    subprocess.run([str(compiled_probe), str(tmp_path)], check=True, capture_output=True, text=True, env=env, timeout=30)
    result = json.loads((tmp_path / "performance.json").read_text())
    assert result["parent_row_build"]["observation_design_calls"] == 5
    assert result["zero_update_replay"]["row_build"]["observation_design_calls"] == 3
    assert len(result["ordinary_trials"]) == 1
    assert len(result["arithmetic_audits"]) == 2
    assert len(result["probe_rounds"]) == 1
    assert len(result["probe_rounds"][0]) == 2
    assert "probes" not in result
    assert not result["arithmetic_audits"][0]["row_build"]["available"]
    assert not result["arithmetic_audits"][1]["row_build"]["completed"]
