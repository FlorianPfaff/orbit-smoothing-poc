from pathlib import Path
import json,hashlib,datetime,importlib.util
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');C=B/'tangent-capture-05/control';R=B/'validation-05';P=B/'preparation-04'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):
 raw=Path(p).read_bytes();return {'path':str(p),'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'value':json.loads(raw)}
plan=read(C/'plan.json');e=read(C/'execution.json');base=read(P/'control/execution.json');assert plan['sha256']=='c4896bf4fffc0fdcea286901ace5418353c006310496a87ff4b7ff68a5f86170';assert e['sha256']=='d917652710176b72c864af6d819ffe2bdccab9be43f070f75eece8705a3d7971'
p=plan['value'];ev=e['value'];bv=base['value'];assert p['execution']['sha256']==e['sha256']
for name,pin in p['inputs'].items():assert sha(pin['path'])==pin['sha256'],name
for name in ('worker','controller','driver','source_freeze','native'):assert sha(p[name]['path'])==p[name]['sha256'],name
assert p['native']['sha256']=='eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'
for key,value in bv['runtime_artifacts'].items():assert ev['runtime_artifacts'][key]==value,key
assert ev['read_only_bindings']==bv['read_only_bindings']+[{'source':str(R),'target':str(R)}]
assert ev['read_only_bindings'].count({'source':str(B/'tangent-precision-01'),'target':str(B/'tangent-precision-01')})==1
spec=importlib.util.spec_from_file_location('owned',p['driver']['path']);o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json')
result={'schema':'independent-capture-build05-packet-readback-v1','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':plan,'execution':e,'base_execution':{'path':base['path'],'sha256':base['sha256']},'source_freeze':read(C/'source-freeze.json'),'input_pins_verified':p['inputs'],'runtime_declarations_preserved':len(bv['runtime_artifacts']),'runtime_declarations_total':len(ev['runtime_artifacts']),'admission':o.admission(ev,[]),'mutable_inventory':{name:[str(x)for x in Path(ev['paths'][name]).iterdir()]for name in ('native_source','build','binaries','run','temporary')},'pipeline_present':(C/'pipeline.json').exists(),'native_calls':0}
print(json.dumps(result,indent=2))
