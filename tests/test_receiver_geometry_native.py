"""Actual native receiver orbit resampling across a controlled velocity jump."""
from decimal import Decimal
import os
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from orbit_poc.comparison.backend import read_native_table


def _orbit(path, seconds):
    with path.open("w") as stream:
        stream.write("groops instrument version=20200123\n# ORBIT\n-6 1\n")
        stream.write(str(len(seconds))+"\n")
        for t in seconds:
            epoch = Decimal(60424)+(Decimal(18)+Decimal(str(t)))/Decimal(86400)
            x = 7e6+3*t+.02*t*t+max(t-90, 0.)
            vx = 3+.04*t+(1. if t>=90 else 0.)
            stream.write(f"{epoch:.18f} {x:.17e} {1000+.1*t:.17e} 0 {vx:.17e} .1 0 0 0 0\n")


def test_native_receiver_resampling_respects_pulse_velocity_jump(tmp_path):
    executable = os.environ.get("ORBIT_POC_GROOPS")
    if not executable:
        pytest.skip("ORBIT_POC_GROOPS is required for native receiver geometry validation")
    _orbit(tmp_path/"orbit.txt", np.arange(0.,185.,5.))
    queries=np.array([0.,12.,87.,90.,92.,177.,180.])
    _orbit(tmp_path/"queries.txt", queries)
    root=ET.Element("groops")
    p=ET.SubElement(ET.SubElement(root,"program"),"OrbitPocResampleOrbit")
    for key,value in (("inputfileOrbit",tmp_path/"orbit.txt"),("outputfileOrbit",tmp_path/"sampled.txt")):
        ET.SubElement(p,key).text=str(value)
    series=ET.SubElement(ET.SubElement(p,"timeSeries"),"instrument")
    ET.SubElement(series,"inputfileInstrument").text=str(tmp_path/"queries.txt")
    pulse=ET.SubElement(ET.SubElement(p,"stochasticPulse"),"uniformSampling")
    for key,value in (("timeStart","60424"),("timeEnd","60424"),("sampling","1"),("offsetSeconds","108")):
        ET.SubElement(pulse,key).text=value
    config=tmp_path/"resample.xml"
    ET.ElementTree(root).write(config,encoding="utf-8",xml_declaration=True)
    result=subprocess.run([executable,str(config)],capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    sampled=read_native_table(tmp_path/"sampled.txt",10)
    expected=7e6+3*queries+.02*queries**2+np.maximum(queries-90,0.)
    expected_velocity=3+.04*queries+(queries>=90)
    # Absolute Earth-radius coordinates incur sub-micrometre cancellation in
    # the stock degree-seven polynomial solve; the pulse error would be cm.
    np.testing.assert_allclose(sampled[:,1],expected,rtol=0,atol=1e-6)
    np.testing.assert_allclose(sampled[:,4],expected_velocity,rtol=0,atol=1e-9)
    # In particular, the epoch exactly at the pulse has the post-pulse velocity.
    assert sampled[3,4]==pytest.approx(7.6,abs=1e-9)
    actual_tokens=[line.split()[0] for line in (tmp_path/"sampled.txt").read_text().splitlines()
                   if len(line.split())==10 and not line.startswith("#")]
    query_tokens=[line.split()[0] for line in (tmp_path/"queries.txt").read_text().splitlines()
                  if len(line.split())==10 and not line.startswith("#")]
    assert max(abs(Decimal(a)-Decimal(b))*86400 for a,b in zip(actual_tokens,query_tokens))<Decimal("1e-9")
