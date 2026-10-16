from pathlib import Path
import json
import struct
import subprocess

HERE = Path(__file__).parent

def capture():
    header = b'OPCTANGENT001\n\0\0'+struct.pack('<5Q2d',1,3,2,4,18,.5,1.)
    jac = struct.pack('<108d', *([0.]*108))
    weights = b''.join(struct.pack('<Q',2)+struct.pack('<QddQdd',i,.25,1./24.,i+1,.25,1./12.) for i in range(2))
    rhs = struct.pack('<18d', *([1.,2.,3.]*3+[.001,.002,.003]*3))
    return header+jac+weights+rhs

def invoke(tmp_path, data):
    path=tmp_path/'capture.bin';path.write_bytes(data)
    result=subprocess.run([str(HERE/'replay'),str(path)],capture_output=True,text=True)
    return result,[json.loads(line) for line in result.stdout.splitlines()]

def test_identity_system(tmp_path):
    result,rows=invoke(tmp_path,capture())
    assert result.returncode==0 and result.stderr==''
    assert rows[-1]=={'kind':'terminal','status':'passed','iterations':0,'relative_residual':0}
    residual=next(row for row in rows if row['kind']=='true_residual')
    assert residual['native_relative_residual']==0
    assert residual['extended_residual_native_velocity_conversion']==0
    assert residual['extended_residual_exact_velocity_conversion']==0

def test_bad_magic(tmp_path):
    result,rows=invoke(tmp_path,b'x'+capture()[1:])
    assert result.returncode==1 and 'magic' in result.stderr
    assert len(rows)==1 and rows[0]['status']=='failed'

def test_truncated(tmp_path):
    result,rows=invoke(tmp_path,capture()[:-1])
    assert result.returncode==1 and 'truncated' in result.stderr
    assert rows[-1]['status']=='failed'

def test_trailing_bytes(tmp_path):
    result,rows=invoke(tmp_path,capture()+b'x')
    assert result.returncode==1 and 'trailing' in result.stderr

def test_wrong_counts(tmp_path):
    data=bytearray(capture());struct.pack_into('<Q',data,16+8*4,17)
    result,_=invoke(tmp_path,data)
    assert result.returncode==1 and 'dimensions' in result.stderr

def test_outside_sample(tmp_path):
    data=bytearray(capture());struct.pack_into('<Q',data,16+40+16+108*8+8,3)
    result,_=invoke(tmp_path,data)
    assert result.returncode==1 and 'outside' in result.stderr

def test_nonfinite(tmp_path):
    data=bytearray(capture());struct.pack_into('<d',data,len(data)-8,float('nan'))
    result,_=invoke(tmp_path,data)
    assert result.returncode==1 and 'nonfinite' in result.stderr

def test_nontrivial_krylov_and_extended_residual(tmp_path):
    data=bytearray(capture())
    for epoch in range(3):
        for axis in range(3):
            struct.pack_into('<d',data,72+8*(18*epoch+4*axis),-.001*(axis+1))
            struct.pack_into('<d',data,72+8*(18*epoch+9+4*axis),-.0001)
    result,rows=invoke(tmp_path,data)
    assert result.returncode==0 and result.stderr==''
    assert any(row['kind']=='projected_residual' for row in rows)
    residuals=[row for row in rows if row['kind']=='true_residual']
    assert residuals[0]['native_relative_residual']>1e-4
    for row in residuals:
        assert abs(row['native_relative_residual']-row['extended_residual_native_velocity_conversion'])<1e-15
    assert rows[-1]['relative_residual']<=2e-12
