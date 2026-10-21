from pathlib import Path
import json,hashlib,os,socket,datetime
R=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-04');C=R/'control'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def art(p):return {'path':str(p),'sha256':sha(p)}
a=C/'validation04-startup-addendum01.json';assert sha(a)=='ff370480ea3250346a5b559c8af08b9a58231c70198807649339673693dddb46';v=json.loads(a.read_text())
checked=[]
for q in list(v['base'].values())+list(v['helpers'].values())+[v['preserved_probe'],v['preserved_smoke']]:
 assert sha(q['path'])==q['sha256'],q;checked.append(q)
old=Path(v['preserved_probe']['path']).read_text();new=Path(v['helpers']['validation04_startup_probe.py']['path']).read_text()
assert new==old.replace("else 301","else 303").replace('validation03-startup-probe-v1','validation04-startup-probe-v1')
old=Path(v['preserved_smoke']['path']).read_text();new=Path(v['helpers']['smoke_segmented_validation04_02.py']['path']).read_text()
assert new==old.replace('validation03_startup_probe.py','validation04_startup_probe.py')
assert v['expected_collections']=={'segmented-native-tangent':3,'segmented-structural':303}
assert v['command']==['/usr/bin/taskset','-c','24-27','/usr/bin/python3',v['helpers']['smoke_segmented_validation04_02.py']['path'],'--execution-sha256',v['base']['execution']['sha256'],'--config-sha256',v['base']['config']['sha256'],'--probe-sha256',v['helpers']['validation04_startup_probe.py']['sha256']]
assert v['fresh_output']==str(R/'staging/namespace-smoke-01') and not Path(v['fresh_output']).exists()
e=json.loads((C/'execution.json').read_text());mutable=['run','temporary','cache','scratch','validation'];absence={k:not Path(e['paths'][k]).exists() for k in mutable};assert all(absence.values()),absence
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot=='95156dd4-0d4c-499d-a214-8883a2d650fa'
print(json.dumps({'passed':True,'observed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'host':socket.gethostname(),'boot_id':boot,'addendum':art(a),'checked_pins':checked,'exact_probe_count_schema_delta':True,'exact_smoke_probe_filename_delta':True,'fresh_startup_absent':True,'production_outputs_absent':absence,'command':v['command'],'scope':'Read-only current metadata and exact source text; no namespace, native work or full runtime rescan.'},indent=2))
