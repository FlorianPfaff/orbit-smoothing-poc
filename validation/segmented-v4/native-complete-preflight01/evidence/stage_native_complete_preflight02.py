from pathlib import Path
import hashlib,json,shutil,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');OLD=B/'native-complete-preflight-01';D=B/'native-complete-preflight-02';C=D/'control';I=B/'native-complete-inputs-02'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
assert sha(OLD/'control/plan.json')=='d1537fb72b6e796ff0be1360d8382b2a5f77586cd303914a9fee310b418f0a19';old=json.loads((OLD/'control/plan.json').read_text());j=json.loads((OLD/'control/pipeline.json').read_text());assert j['status']=='failed_diagnostic'and j['final_cleanup']['verified']
f=json.loads((OLD/'run/preflight/result.json').read_text());assert f['status']=='failed'and f['stages']==[]
probe=I/'namespace-identities.json';assert sha(probe)=='d2f31197a53e1787931c41581e1b2548f114c7e393bbfaa23b5d24735a9c4ca1';x=json.loads(probe.read_text());assert x['count']==637 and len(x['different'])==6 and not x['dependency_differences'];assert all(r['fields']==['resolved_path']for r in x['different'])
links=json.loads(Path(old['inputs']['link_inventory']['path']).read_text());assert len(links['inputs'])==len(x['actual_links'])
for a,b in zip(links['inputs'],x['actual_links']):assert {k:v for k,v in a.items()if k!='resolved_path'}=={k:v for k,v in b.items()if k!='resolved_path'}
links['inputs']=x['actual_links'];save(I/'link-inventory.json',links)
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists()
shutil.copytree(OLD/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json','build_native_complete01.py','run_native_complete01.py','launch_native_complete01.py'):shutil.copy2(OLD/'control'/name,C/name)
request=json.loads(Path(old['inputs']['installation_request']['path']).read_text());request['output']=str(D/'native_source/reproduction');save(I/'installation-request.json',request)
e=json.loads(Path(old['execution']['path']).read_text());e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'));e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};assert not any(r['target']==str(I)for r in e['read_only_bindings']);e['read_only_bindings'].append({'source':str(I),'target':str(I)})
inputs=dict(old['inputs'],link_inventory=pin(I/'link-inventory.json'),installation_request=pin(I/'installation-request.json'))
# Preserve every old declaration and append the exact new controls/metadata.
for name in ('owned_driver09.py','with_correctness_namespace_09.py','build_native_complete01.py','run_native_complete01.py'):e['runtime_artifacts']['native_complete02_'+name]=pin(C/name)
for key in ('link_inventory','installation_request'):e['runtime_artifacts']['native_complete02_'+key]=inputs[key]
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
p=dict(old,execution=pin(C/'execution.json'),driver=pin(C/'owned_driver09.py'),worker=pin(C/'build_native_complete01.py'),controller=pin(C/'run_native_complete01.py'),source_freeze=pin(C/'source-freeze.json'),inputs=inputs,output=str(D/'run/preflight'));save(C/'plan.json',p)
for key,v in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(v['path'],e))==v['sha256'],key
receipt={'schema':'orbit-poc-native-complete-preflight-recovery-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'old_plan':pin(OLD/'control/plan.json'),'failed_pipeline':pin(OLD/'control/pipeline.json'),'failed_result':pin(OLD/'run/preflight/result.json'),'namespace_identity_probe':pin(probe),'only_identity_field_delta':'Six actual bind-mounted sysroot resolved_path fields; SHA/bytes/inode/device/linktext unchanged. No worker or policy change.','inputs':inputs,'runtime_pin_count':len(e['runtime_artifacts']),'source_freeze':pin(C/'source-freeze.json'),'mutable_inventory':{n:[str(v)for v in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')}};save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
