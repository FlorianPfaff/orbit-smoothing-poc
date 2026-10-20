"""Exact typed clock-origin policy; not a substitute for native profile gates."""
from pathlib import Path
import importlib.util
import os
import subprocess
import pytest
ROOT=Path(__file__).resolve().parents[1]
@pytest.fixture(scope='module')
def fixture(tmp_path_factory):
    out=tmp_path_factory.mktemp('clock-origin')/'fixture'
    subprocess.run(['/usr/bin/g++','-std=c++17','-O1','-I',str(ROOT/'groops/extension'),str(ROOT/'tests/nuisance_warm_clock_origin_fixture.cpp'),'-o',str(out)],check=True)
    return out
@pytest.mark.parametrize('case',['one_ulp','large_guess','negative_guess','subnormal_guess','clock_mode','prior','weight','nonclock','old_policy','untyped','nonfinite_guess','refresh_clock','refresh_anchor','refresh_ionosphere'])
def test_clock_origin_contract(fixture,tmp_path,case):
    env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_')}
    subprocess.run([str(fixture),case,str(tmp_path)],check=True,env=env,capture_output=True,text=True)
def test_production_clock_hook_is_the_only_typed_binding():
    p=ROOT/'groops/extension/native_nuisance_warm.py'
    spec=importlib.util.spec_from_file_location('clock_origin_installer',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    exact='l.receiverClockGuess(coordinate+"/seconds",gnss->receivers.at(recv)->clk.at(epoch));'
    assert m.CLOCKS.count(exact)==1
    assert p.read_text().count('l.receiverClockGuess(')==1
    assert 'anchors(key+".x0Recv",x0Recv);anchors(key+".x0Trans",x0Trans);' in m.CLOCKS
    assert 'l.id(name+".anchor",double(v));l.fixed(name+".anchor",double(v));' in m.CLOCKS
