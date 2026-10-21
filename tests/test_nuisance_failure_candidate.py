"""Real fork/pipe and cost-only dispatch checks for the isolated candidate.

These component checks do not authorize covariance or whole-fit success.
"""
from pathlib import Path
import json
import os
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def candidate_probe(tmp_path_factory):
    directory = tmp_path_factory.mktemp("nuisance-failure-candidate")
    (directory / "base").mkdir()
    (directory / "base/import.h").write_text("""#pragma once
#include <sstream>
#include <stdexcept>
using Double=double;using UInt=unsigned;using Bool=bool;
constexpr bool TRUE=true,FALSE=false;
using Exception=std::runtime_error;
""")
    source = directory / "probe.cpp"
    source.write_text(r'''
#include <cassert>
#include <sys/mman.h>
#include "nuisanceLineSearch.h"
#include "nuisancePerformance.h"
namespace qr=orbitPocQr;
namespace perf=orbitPocNuisancePerformance;
struct Matrix {
  unsigned rows,columns;double value=0;
  Matrix(unsigned r,unsigned c):rows(r),columns(c){}
};
int main(int argc,char **argv) {
  assert(argc==3);const std::string mode=argv[1],output=argv[2];
  if(mode=="design") {
    int calls=0,validations=0;bool badQuery=false;
    auto validate=[&](){validations++;if(badQuery)throw std::runtime_error("invalid native query");};
    auto compute=[&](){calls++;Matrix m(3,17);m.value=42;return m;};
    unsetenv("ORBIT_POC_NUISANCE_COST_ONLY_DESIGN");
    setenv("ORBIT_POC_NUISANCE_PERFORMANCE","1",1);
    {perf::BuildMeasure b(true,true);assert(perf::dynamicDesign(17,validate,compute).value==42);}
    assert(calls==1);
    setenv("ORBIT_POC_NUISANCE_COST_ONLY_DESIGN","1",1);
    {perf::BuildMeasure b(true,false);assert(perf::dynamicDesign(17,validate,compute).value==42);}
    assert(calls==2); // full linearization always executes
    {perf::BuildMeasure b(true,true);const auto z=perf::dynamicDesign(17,validate,compute);
      assert(z.value==0&&z.rows==3&&z.columns==17);
      assert(perf::metrics().omittedDynamicDesigns==1);
      bool rejected=false;try{perf::BuildMeasure nested(true,true);}catch(const std::logic_error&){rejected=true;}
      assert(rejected&&perf::context().active);
      assert(perf::dynamicDesign(17,validate,compute).value==0);
    }
    assert(calls==2&&!perf::context().active);
    assert(perf::dynamicDesign(17,validate,compute).value==42);assert(calls==3);
    setenv("ORBIT_POC_NUISANCE_COST_ONLY_DESIGN","invalid",1);
    bool rejected=false;try{perf::BuildMeasure b(true,true);}catch(const std::invalid_argument&){rejected=true;}
    assert(rejected&&!perf::context().active);
    setenv("ORBIT_POC_NUISANCE_COST_ONLY_DESIGN","1",1);
    try{perf::BuildMeasure b(true,true);throw std::runtime_error("rollback");}catch(const std::runtime_error&){}
    assert(!perf::context().active);
    {perf::BuildMeasure b(true,false);assert(perf::dynamicDesign(17,validate,compute).value==42);}
    assert(calls==4&&validations==2);
    badQuery=true;
    bool rejectedQuery=false;
    try{perf::BuildMeasure b(true,true);perf::dynamicDesign(17,validate,compute);}
    catch(const std::runtime_error&){rejectedQuery=true;}
    assert(rejectedQuery&&calls==4&&validations==3&&!perf::context().active);
    return 0;
  }
  auto count=static_cast<unsigned*>(mmap(nullptr,sizeof(unsigned),PROT_READ|PROT_WRITE,MAP_ANONYMOUS|MAP_SHARED,-1,0));
  assert(count!=MAP_FAILED);*count=0;int parentState=23;
  const auto search=qr::searchNuisance(2.,2.,1e-8,41,7,[&](double alpha){
    ++*count;parentState=99;
    if(mode=="exception"&&alpha==0)throw std::runtime_error("child \"execution\" failed\nexact message");
    qr::NuisanceTrial t;t.cost=2*(1-alpha)*(1-alpha);t.change=2*std::abs(alpha);
    t.reduction=4*alpha-2*alpha*alpha;t.support=41;t.rows=7;t.observationSignature=19;
    if(alpha==0) {
      if(mode=="reduction")t.reduction=1e-30;
      if(mode=="change")t.change=1e-30;
      if(mode=="support")t.support++;
      if(mode=="rows")t.rows++;
      if(mode=="nonfinite")t.cost=std::numeric_limits<double>::quiet_NaN();
    }
    return t;
  });
  assert(parentState==23); // fork rollback applies even on identity failure
  if(mode=="valid") {
    assert(*count==2&&search.accepted&&search.alpha==1&&search.trials.size()==1);
    assert(!search.stationary&&!search.floorLimited);
  } else {
    assert(*count==1&&!search.accepted&&!search.stationary&&!search.floorLimited);
    assert(search.trials.empty()&&search.probes.empty()&&search.arithmeticAudits.empty());
    assert(search.floorRejection=="zero_update_replay_failed");
  }
  qr::writeNuisanceSearch(output,search,2.,2.);
  munmap(count,sizeof(unsigned));
}
''')
    compiler = shutil.which("c++")
    assert compiler, "C++ compiler required for fork/pipe checks"
    executable = directory / "probe"
    subprocess.run([compiler, "-std=c++17", "-O2", "-Wall", "-Wextra", "-I", str(directory),
                    "-I", str(ROOT / "groops/extension"), str(source), "-o", str(executable)],
                   check=True, capture_output=True, text=True, timeout=60)
    return executable


@pytest.mark.parametrize("mode", ["valid", "exception", "reduction", "change", "support", "rows", "nonfinite", "design"])
def test_candidate_replay_and_cost_only_dispatch(candidate_probe, tmp_path, mode):
    result = tmp_path / "search.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("ORBIT_POC_")}
    env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY="1")
    subprocess.run([str(candidate_probe), mode, str(result)], check=True, capture_output=True,
                   text=True, env=env, timeout=30)
    if mode == "exception":
        replay = json.loads(result.read_text())["zero_update_replay"]
        assert replay["status"] == 1
        # Match the existing diagnostic convention: controls become spaces,
        # quotes round-trip through JSON. Resource data stays in its sidecar.
        assert replay["error"] == 'child "execution" failed exact message'
        assert "peak_child_rss_bytes" not in replay
