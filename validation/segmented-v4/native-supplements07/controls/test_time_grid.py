"""Pure tests for the measured native endpoint-span metadata defect."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import struct
import numpy as np
import pytest
import gates as g
from test_gates import flight_data


def packed(times):
    header=(b'B'+struct.pack('<Q',10)+b'instrument'+struct.pack('<Q',8)+b'20200123'+b'   '+struct.pack('<qQQ',-6,1,361))
    return header+b''.join(struct.pack('<q10d',d,f,*([0.]*9)) for d,f in times)


def inputs():
    d=flight_data();main=[r for r in d[0] if r.get('kind')=='sample' and r['channel']=='main']
    drag=[r for r in d[0] if r.get('kind')=='sample' and r['channel']=='drag']
    return d[0][0],main,drag,d[-1]


def test_binary_time_parser_preserves_every_component():
    times=flight_data()[-1]
    assert g.retained_orbit_times(packed(times))==times


@pytest.mark.parametrize('mutation',[
    lambda b:b'X'+b[1:],lambda b:b.replace(b'instrument',b'not-a-type'),
    lambda b:b.replace(b'20200123',b'20200124'),lambda b:b[:38]+struct.pack('<q',-7)+b[46:],
    lambda b:b[:46]+struct.pack('<Q',2)+b[54:],lambda b:b[:54]+struct.pack('<Q',360)+b[62:],
    lambda b:b[:-1],lambda b:b+b'X',lambda b:b[:70]+struct.pack('<d',float('nan'))+b[78:],
    lambda b:b[:70]+struct.pack('<d',float('inf'))+b[78:],lambda b:b[:70]+struct.pack('<d',1.)+b[78:],
    lambda b:b[:62]+struct.pack('<q',60425)+b[70:],
    lambda b:b[:78]+struct.pack('<d',float('nan'))+b[86:],
])
def test_invalid_binary_orbit_rejected(mutation):
    with pytest.raises(ValueError):g.retained_orbit_times(mutation(packed(flight_data()[-1])))


@pytest.mark.parametrize('change',[
    lambda x:x[0].update(dt=math.nextafter(x[0]['dt'],math.inf)),
    lambda x:x[0].update(initial_velocity_scale=math.nextafter(x[0]['initial_velocity_scale'],math.inf)),
    lambda x:x[1][180]['time'].__setitem__(1,math.nextafter(x[1][180]['time'][1],math.inf)),
    lambda x:x[2][180]['time'].__setitem__(1,math.nextafter(x[2][180]['time'][1],math.inf)),
    lambda x:x[3].pop(),
])
def test_time_binding_rejects_any_metadata_or_component_change(change):
    x=deepcopy(inputs());change(x)
    with pytest.raises(ValueError):g.check_flight_time_grid(*x)


def test_low_component_change_hidden_by_summed_mjd_is_rejected():
    x=deepcopy(inputs());before=sum(x[1][180]['time'])
    x[1][180]['time'][1]=math.nextafter(x[1][180]['time'][1],math.inf)
    assert sum(x[1][180]['time'])==before
    with pytest.raises(ValueError,match='Time components'):g.check_flight_time_grid(*x)


def test_consistently_shifted_physical_window_rejected():
    x=deepcopy(inputs())
    for t in x[3]:t[1]+=.001
    for rows in (x[1],x[2][:361]):
        for i,r in enumerate(rows):r['time']=x[3][i][:]
    with pytest.raises(ValueError,match='prescribed'):g.check_flight_time_grid(*x)


def test_consistently_wrong_interior_grid_rejected():
    x=deepcopy(inputs())
    x[3][180][1]+=.00001
    for rows in (x[1],x[2]):rows[180]['time']=x[3][180][:]
    with pytest.raises(ValueError,match='prescribed'):g.check_flight_time_grid(*x)


def test_actual_failed_attempt_endpoint_arithmetic_regression():
    # Independently retained failed-attempt output, never renamed as a success.
    root=Path('/mnt/d/orbit-segmented-v4/control/wide-flight-pair01-terminal01')
    manifest=root/'manifest.json'
    assert hashlib.sha256(manifest.read_bytes()).hexdigest()=='e4fa1a31914c325d7cd98cfd6f0c3833dfd537a4b91f1d92d018c5ba34920c8e'
    pins={r['relative']:r for r in json.loads(manifest.read_text())['records']}
    def artifact(relative):
        content=(root/relative).read_bytes()
        assert hashlib.sha256(content).hexdigest()==pins[relative]['sha256']
        return content
    rows=[json.loads(line) for line in artifact('run/pair/export/local-tangent.jsonl').splitlines()]
    meta=rows[0];main=[r for r in rows if r.get('kind')=='sample' and r['channel']=='main']
    drag=[r for r in rows if r.get('kind')=='sample' and r['channel']=='drag']
    readback=Path('/mnt/d/orbit-segmented-v4/control/wide-flight-native-time-readback01')
    assert g.digest(readback/'manifest.json')=='38b656b3b24665f9ea90f346265c3b3c84899b774c1be76d85a0f0247f151819'
    input_pin=json.loads((root/'control/request.json').read_text())['reference_orbit']
    content=(readback/'retained/coarse/closure-03/orbit.dat').read_bytes()
    assert hashlib.sha256(content).hexdigest()==input_pin['sha256']
    times=g.retained_orbit_times(content)
    assert times==g.retained_orbit_times(artifact('run/pair/export/orbit.dat'))
    # All precise input text tokens also reproduce the retained binary Time.
    original=readback/'retained/inputs/orbit.txt'
    assert g.digest(original)=='1bd5df945ba991c7af64a077c02d4595af9902eb450a4d536a80e781dba0561d'
    from fractions import Fraction
    tokens=[Fraction(line.split()[0]) for line in original.read_text().splitlines()[3:]]
    assert times==[[int(t),float(t%1)] for t in tokens]
    assert meta['dt']!=5 and meta['dt']==5.000000000000568
    result=g.check_flight_time_grid(meta,main,drag,times)
    assert result['all_retained_time_components_identical']
    assert result['endpoint_span_seconds']==1800.0000000002046
    bad=deepcopy(meta);bad['dt']=5.
    with pytest.raises(ValueError,match='endpoint-span'):g.check_flight_time_grid(bad,main,drag,times)


def test_wrong_retained_input_hash_fails_before_decoding(tmp_path):
    p=tmp_path/'orbit.dat';p.write_bytes(packed(flight_data()[-1]))
    with pytest.raises(ValueError,match='pinned'):g.retained_orbit_times(g.verify({'path':str(p),'sha256':'0'*64}).read_bytes())
