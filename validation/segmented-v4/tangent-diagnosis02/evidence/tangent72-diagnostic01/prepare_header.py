"""Make a telemetry-only copy; do not alter the numerical expressions."""
from pathlib import Path
import hashlib
import json
import shutil
import sys

source, target = map(Path, sys.argv[1:])
target.mkdir(exist_ok=False)
files = {}
for name in ('sixStateTangent.h', 'syntheticForceDerivatives.h', 'eventQuadrature.h'):
    original = (source/name).read_bytes()
    value = original.decode()
    if name == 'sixStateTangent.h':
        replacements = [
            ('result.relativeResidual=beta/normB;',
             'result.relativeResidual=beta/normB;\n    ::recordTangentTrace(result.iterations,x,result.relativeResidual,false);'),
            ('count=j+1;result.iterations++;',
             'count=j+1;result.iterations++;\n      ::recordTangentProjection(result.iterations,std::abs(g[j+1])/normB);'),
            ('result.relativeResidual=tangentNorm(residual)/normB;\n  if(',
             'result.relativeResidual=tangentNorm(residual)/normB;\n  ::recordTangentTrace(result.iterations,x,result.relativeResidual,true);\n  if('),
        ]
        for before, after in replacements:
            assert value.count(before) == 1, before
            value = value.replace(before, after)
    output = value.encode()
    (target/name).write_bytes(output)
    files[name] = {'original_sha256': hashlib.sha256(original).hexdigest(),
                   'telemetry_sha256': hashlib.sha256(output).hexdigest()}
(target/'manifest.json').write_text(json.dumps({'schema': 'tangent-telemetry-only-v1', 'files': files}, indent=2)+'\n')
