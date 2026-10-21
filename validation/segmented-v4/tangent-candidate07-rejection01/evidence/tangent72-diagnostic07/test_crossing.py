from pathlib import Path
import json,struct,subprocess
import importlib.util
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('base_tests',HERE.parent/'tangent72-diagnostic01/test_replay.py')
base=importlib.util.module_from_spec(spec);spec.loader.exec_module(base)

def test_small_nontrivial_crossing_and_operator_accounting(tmp_path):
    data=bytearray(base.capture())
    for epoch in range(3):
        for axis in range(3):
            struct.pack_into('<d',data,72+8*(18*epoch+4*axis),-.001*(axis+1))
            struct.pack_into('<d',data,72+8*(18*epoch+9+4*axis),-.0001)
    p=tmp_path/'capture.bin';p.write_bytes(data)
    result=subprocess.run([str(HERE/'replay'),str(p)],capture_output=True,text=True)
    assert result.returncode==0 and not result.stderr
    rows=[json.loads(line)for line in result.stdout.splitlines()]
    crossings=[r for r in rows if r['kind']=='projected_crossing_true_check']
    assert crossings and crossings[-1]['accepted']
    assert crossings[-1]['true_relative_residual']<=2e-12
    assert rows[-1]['relative_residual']==crossings[-1]['true_relative_residual']
    counts=next(r for r in rows if r['kind']=='operator_counts')
    assert counts['arnoldi']==rows[-1]['iterations']
    assert counts['true_residual']>=len(crossings)+1
    assert counts['arnoldi']<=120
