from pathlib import Path
import json,hashlib,importlib.util,datetime,socket,xml.etree.ElementTree as ET
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-capture-01';C=D/'control';R=B/'validation-04';P=B/'preparation-03'
def pin(p):
 p=Path(p);h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}
def read(p):return json.loads(Path(p).read_text())
p=read(C/'plan.json');e=read(C/'execution.json');s=read(C/'staging.json');b=read(P/'control/execution.json')
assert pin(C/'plan.json')['sha256']=='c7484680b0ffc1958121bf94bc564e50dcb4a75741d5e7ffc2ada3319b2de3ab'
assert pin(C/'execution.json')['sha256']=='d9219d2102e8148d0dbf6f8871a5cf6a652326e6135dcde5189f12352e1256c8'
assert pin(P/'control/execution.json')['sha256']=='d2297c51648d9ba1f3644cbdae36ba5a95ad289d941ec4823aca6817af923236'
assert e.keys()==b.keys()
for k in e:
 if k not in ('paths','read_only_bindings','runtime_artifacts','host','reserved_cpu_note'):assert e[k]==b[k],k
assert e['read_only_bindings']==b['read_only_bindings']+[{'source':str(R),'target':str(R)}]
for k,v in b['runtime_artifacts'].items():assert e['runtime_artifacts'][k]==v,k
assert len(e['runtime_artifacts'])==435 and len(b['runtime_artifacts'])==431
changes={k:(b['paths'][k],v)for k,v in e['paths'].items()if v!=b['paths'][k]}
assert set(changes)=={'root','source','control','native_source','build','binaries','run','temporary','wrapper'}
for k in ('root','source','control','native_source','build','binaries','run','temporary'):assert e['paths'][k]==str(D if k=='root' else D/k)
assert e['paths']['wrapper']==str(C/'with_correctness_namespace_09.py')
for k in ('execution','driver','worker','controller','native','source_freeze'):
 assert pin(p[k]['path'])['sha256']==p[k]['sha256'],k
assert p['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert p['source_freeze']['sha256']=='87ad55dcd0c4329cb4e37a37adfe3871cb85d3fb88e8a46b3cff388aa17e9f29'
assert p['global_lock']=='/mnt/seagate10tb/orbit-v31-correctness-10-florianpfaff/control/candidate09-validation.lock'
assert p['output']==str(D/'run/build-result') and len(p['inputs'])==8 and p['inputs']==s['input_attribution']
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
for k,v in p['inputs'].items():assert pin(o.resolved_host_path(v['path'],e))['sha256']==v['sha256'],k
newpins={k:v for k,v in e['runtime_artifacts'].items()if k not in b['runtime_artifacts']}
for k,v in newpins.items():assert pin(v['path'])['sha256']==v['sha256']
assert o.source_receipt(D/'source')==read(C/'source-freeze.json')['source']
assert len(read(C/'source-freeze.json')['source']['files'])==384
assert e['host']=={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
for k in ('native_source','build','binaries','run','temporary'):
 q=D/k;assert not q.is_symlink() and q.is_dir() and list(q.iterdir())==[]
assert not(C/'pipeline.json').exists() and not(C/'native-replay.log').exists()
# The concrete candidate contains only the reviewed native header insertion and reader telemetry.
inspection=read(p['inputs']['recipe_inspection']['path']);assert len(inspection['original_link_input_pins'])==637
for item in inspection['original_link_input_pins']:
 actual=Path(o.resolved_host_path(item['path'],e));stat=actual.stat()
 assert (stat.st_dev,stat.st_ino,stat.st_size)==(item['device'],item['inode'],item['bytes'])
assert p['inputs']['capture_header']['sha256']=='5d843097034b38716430ece2fc7f0706aa1b9a9f6cf01a5fe9e1b9a875405073'
reader_manifest=read(p['inputs']['reader_manifest']['path'])
for key,name in [('reader_tangent','sixStateTangent.h'),('reader_force','syntheticForceDerivatives.h'),('reader_quadrature','eventQuadrature.h')]:
 assert p['inputs'][key]['sha256']==reader_manifest['files'][name]['telemetry_sha256']
admission=o.admission(e,[])
print(json.dumps({'schema':'orbit-poc-tangent-capture-build-packet-independent-readback-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'staging':pin(C/'staging.json'),'source_freeze':pin(C/'source-freeze.json'),'base_execution':pin(P/'control/execution.json'),'source_file_count':384,'unchanged_old_runtime_pin_count':431,'new_runtime_pins':newpins,'verified_build_inputs':p['inputs'],'original_link_inputs_metadata_verified':637,'native':p['native'],'paths_changes':changes,'mutable_directories_empty':True,'admission':admission,'proposed_controller_argv':['/usr/bin/taskset','-c','24-27','/usr/bin/python3',p['controller']['path'],'--plan',str(C/'plan.json'),'--sha256',p['execution']['sha256'] if False else pin(C/'plan.json')['sha256']],'scope':'Read-only actual packet/input/source/current-host checks; no namespace or native process launched. Old runtime pin declarations are compared exactly; unchanged bulk runtime payloads are not redundantly rehashed by this audit.'},indent=2))
