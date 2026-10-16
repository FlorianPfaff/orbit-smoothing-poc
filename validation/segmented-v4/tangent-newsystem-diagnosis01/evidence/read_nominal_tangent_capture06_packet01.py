from pathlib import Path
import json,hashlib,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');D=B/'tangent-telemetry-03';C=D/'control';R=B/'validation-05';P=B/'preparation-04'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
 raw=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'value':json.loads(raw)}
plan=read(C/'plan.json');e=read(C/'execution.json');base=read(P/'control/execution.json');assert plan['sha256']=='9b5f6d2d8b63c99984255d40dc9bfa32ecfd25db80349ca67fc57eb610f0e15f';assert e['sha256']=='4d5fe801d090dd8677ad117c68c8e20c622d706064af1ac232abcd9fd03ba981'
p=plan['value'];ev=e['value'];bv=base['value'];assert p['execution']['sha256']==e['sha256'];spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
for name,pin in p['inputs'].items():assert sha(o.resolved_host_path(pin['path'],ev))==pin['sha256'],name
for name in ('worker','controller','driver','source_freeze','native'):assert sha(p[name]['path'])==p[name]['sha256'],name
expected={'template':'5b3546116812bc1578f47f0358aff3c503d7f5c95b9928bff724370e710b52bc','initial_orbit':'316d7d669e62d79000080102b2bca8df02c7385c3c9fdf582dfddbd0949ebc41','original_log':'85e70ecb592e4abe75adb4fcb686e40772cc88f5cb66c9e4cfa05b96fd30b5ab','request':'4e47d0bebf1c02948f47d8d1ed8649b3e85ac8490d26dcd1ddc7937d862b5f16','build_result':'ef09acfedede1e55e1a4184cf02a48c500a4ec7a10ec41aa79179e718ac06c74'}
assert all(p['inputs'][name]['sha256']==digest for name,digest in expected.items())
fixtures=read(p['inputs']['fixture_manifest']['path']);assert len(fixtures['value']['files'])==9
for pin in fixtures['value']['files'].values():assert sha(pin['path'])==pin['sha256']
assert fixtures['value']['files']['replay.cpp']['sha256']=='d5a4e875afdf24b662e666a75c31d0f4af87af22ef0f55f5881aed67d2a57db0'
for key,value in bv['runtime_artifacts'].items():assert ev['runtime_artifacts'][key]==value,key
assert ev['read_only_bindings']==bv['read_only_bindings']+[{'source':str(R),'target':str(R)},{'source':str(B/'tangent-capture-05'),'target':str(B/'tangent-capture-05')}]
result={'schema':'independent-tangent-telemetry03-packet-readback-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':plan,'execution':e,'base_execution':{'path':base['path'],'sha256':base['sha256']},'fixture_manifest':fixtures,'runtime_declarations_preserved':len(bv['runtime_artifacts']),'runtime_declarations_total':len(ev['runtime_artifacts']),'admission':o.admission(ev,[]),'mutable_inventory':{name:[str(x)for x in Path(ev['paths'][name]).iterdir()]for name in ('native_source','build','binaries','run','temporary')},'pipeline_present':(C/'pipeline.json').exists(),'native_calls':0}
print(json.dumps(result,indent=2))
