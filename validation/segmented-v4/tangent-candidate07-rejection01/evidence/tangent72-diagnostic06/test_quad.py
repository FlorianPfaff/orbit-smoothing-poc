from pathlib import Path
from decimal import Decimal, localcontext
import importlib.util
import json
import subprocess

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('reader1_tests',HERE.parent/'tangent72-diagnostic01/test_replay.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def test_quad_residual_known_identity(tmp_path):
    data=tmp_path/'identity.bin';data.write_bytes(base.capture())
    result=subprocess.run([str(HERE/'probe'),str(data)],capture_output=True,text=True)
    assert result.returncode==0 and result.stderr==''
    rows=result.stdout.splitlines()
    assert Decimal(rows[0])==1 and Decimal(rows[1])==0
    with localcontext() as context:
        context.prec=70
        expected=Decimal('.25')/Decimal(84).sqrt()
        assert abs(Decimal(rows[2])-expected)<Decimal('1e-20')
    diagnostic=json.loads(rows[3]);assert diagnostic['kind']=='quad_residual'
    assert diagnostic['binary_digits']==113
    assert abs(diagnostic['relative_residual_native_velocity_conversion']-float(expected))<1e-18
    assert rows[4].startswith('{"kind":"true_residual"')

def test_original_reader_fixtures(tmp_path):
    # Run the existing eight checks against reader02, without changing them.
    original=base.HERE;base.HERE=HERE
    try:
        for name in sorted(n for n in dir(base) if n.startswith('test_')):
            sub=tmp_path/name;sub.mkdir();getattr(base,name)(sub)
    finally:
        base.HERE=original
