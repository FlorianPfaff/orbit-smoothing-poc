from pathlib import Path
import hashlib,json
HERE=Path(__file__).parent

def test_exact_production_header_plus_telemetry_only():
    manifest=json.loads((HERE/'include/manifest.json').read_text())
    expected={"sixStateTangent.h":"1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28"}
    hooks=["\n    ::recordTangentTrace(result.iterations,x,result.relativeResidual,false);","\n      ::recordTangentProjection(result.iterations,std::abs(g[j+1])/normB);","\n  ::recordTangentTrace(result.iterations,x,result.relativeResidual,true);"]
    for name,pin in manifest['files'].items():
        data=(HERE/'include'/name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==pin['telemetry_sha256']
        if name=='sixStateTangent.h':
            text=data.decode()
            for hook in hooks:
                assert text.count(hook)==1
                text=text.replace(hook,'')
            data=text.encode()
            assert pin['original_sha256']==expected[name]
        assert hashlib.sha256(data).hexdigest()==pin['original_sha256']
