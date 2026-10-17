"""Process-level capture parsing and certificate contract; reader built by controller."""
import json, math, pathlib, struct, subprocess, sys, tempfile
reader=pathlib.Path(sys.argv[1]).resolve()
def capture():
    # Two zero-Jacobian nodes: K=0, exact RHS solution including physical velocity.
    b=bytearray(b'OPCTANGENT001\n\0\0')
    b+=struct.pack('<5Q2d',1,2,1,0,12,1.,1.)
    b+=struct.pack('<72d',*([0.]*72))+struct.pack('<Q',0)
    rhs=[0.]*12;rhs[0]=1.;rhs[8]=.001234567890123
    b+=struct.pack('<12d',*rhs)
    return b
with tempfile.TemporaryDirectory() as tmp:
    path=pathlib.Path(tmp)/'test.bin'
    for mode in ['baseline','wide']:
        path.write_bytes(capture())
        result=subprocess.run([str(reader),mode,str(path)],capture_output=True,text=True,timeout=10)
        rows=[json.loads(line) for line in result.stdout.splitlines()]
        assert result.returncode==0,(mode,result.stderr,result.stdout)
        assert rows[-1]['status']=='passed' and rows[-1]['kernel_status']=='passed'
        assert rows[-1]['physical_double_quad_relative_residual']==0
        assert any(r.get('binary_digits')==113 for r in rows)
    mutations={
      'magic':lambda b:b.__setitem__(0,0),
      'dimension':lambda b:b.__setitem__(slice(24,32),struct.pack('<Q',1)),
      'duration':lambda b:b.__setitem__(slice(64,72),struct.pack('<d',0.)),
      'nonfinite':lambda b:b.__setitem__(slice(64,72),struct.pack('<d',math.inf)),
      'truncated':lambda b:b.__delitem__(slice(-1,None)),
      'trailing':lambda b:b.extend(b'x'),
    }
    for name,mutate in mutations.items():
        b=capture();mutate(b);path.write_bytes(b)
        for mode in ['baseline','wide']:
            result=subprocess.run([str(reader),mode,str(path)],capture_output=True,text=True,timeout=10)
            assert result.returncode==1,(name,mode,result.stdout,result.stderr)
            rows=[json.loads(line) for line in result.stdout.splitlines()]
            assert rows[-1]['status']=='failed' and rows[-1]['kernel_status']=='failed'
    for args in [[],['unknown',str(path)],['wide']]:
        result=subprocess.run([str(reader),*args],capture_output=True,text=True,timeout=10)
        assert result.returncode==2
print('2 valid profile cases,12 invalid capture cases,3 invalid invocations passed')
