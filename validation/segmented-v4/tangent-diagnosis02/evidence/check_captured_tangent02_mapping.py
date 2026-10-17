from pathlib import Path
import json,hashlib
b=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');c=b/'tangent-standalone-02/control';e=json.loads((c/'execution.json').read_text());p=json.loads((c/'plan.json').read_text());bindings=e['read_only_bindings'][-2:];assert bindings==[{'source':str(b/'tangent-capture-03'),'target':str(b/'tangent-capture-03')},{'source':str(b/'tangent-telemetry-02'),'target':str(b/'tangent-telemetry-02')}];w=[Path(e['paths'][x])for x in ('native_source','build','binaries','run','temporary','control')]+[Path(p['output'])]
for item in bindings:
 for side in item.values():
  r=Path(side);assert r.resolve()==r
  for x in w:assert x.resolve()==x and x!=r and r not in x.parents and x not in r.parents
print(json.dumps({'passed':True,'plan_sha256':hashlib.sha256((c/'plan.json').read_bytes()).hexdigest(),'execution_sha256':hashlib.sha256((c/'execution.json').read_bytes()).hexdigest(),'bindings':bindings,'writable_paths':[str(x)for x in w]},indent=2))
