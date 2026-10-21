from pathlib import Path
import argparse,json,hashlib,shutil,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');OLD=B/'native-complete-preflight-04';D=B/'native-complete-build-02';C=D/'control';I=B/'native-complete-build-audit-02'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
a=argparse.ArgumentParser();a.add_argument('--audit',type=Path,required=True);a.add_argument('--audit-sha256',required=True);q=a.parse_args();assert sha(q.audit)==q.audit_sha256;audit=json.loads(q.audit.read_text());assert audit['passed']is True
assert sha(OLD/'control/plan.json')=='c3502769efffcd6525d588def23801cbf456fa9bd13386ffefb3a5c464785e98';old=json.loads((OLD/'control/plan.json').read_text());result=OLD/'run/preflight/result.json';r=json.loads(result.read_text());j=json.loads((OLD/'control/pipeline.json').read_text());assert r['status']=='prepared_complete_build'and j['status']=='passed_diagnostic'and j['final_cleanup']['verified'];assert audit['preflight_result']==pin(result)
for key in ('baseline_relink','installation_equivalence','supplemental_fixtures'):assert audit[key]==r[key]and sha(r[key]['path'])==r[key]['sha256']
assert r['inputs']==old['inputs'];assert q.audit.is_relative_to(I)
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(OLD/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json','run_native_complete01.py','launch_native_complete01.py'):shutil.copy2(OLD/'control'/name,C/name)
assert sha(C/'build_native_complete03.py')=='33e762b5b33a1d1f30d1966bef7190e19b0a2c348bc1d8f9fde56d3b7b798f4a'
e=json.loads(Path(old['execution']['path']).read_text());e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'));e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};e['reserved_cpu_note']='One complete serial candidate build onCPU24; empty candidate build, all611 translation units, no reuse,8GiB/2h. Source/fixture preflight separately audited. No propagation or fit.'
for path in (OLD,I):
 match=[x for x in e['read_only_bindings']if x['target']==str(path)]
 if match:assert match==[{'source':str(path),'target':str(path)}]
 else:e['read_only_bindings'].append({'source':str(path),'target':str(path)})
inputs=dict(old['inputs'],preflight_result=pin(result),preflight_audit=pin(q.audit))
for name in ('owned_driver09.py','with_correctness_namespace_09.py','build_native_complete03.py','run_native_complete01.py'):e['runtime_artifacts']['native_complete_build02_'+name]=pin(C/name)
for key in ('preflight_result','preflight_audit'):e['runtime_artifacts']['native_complete_build02_'+key]=inputs[key]
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
p=dict(old,phase='build',execution=pin(C/'execution.json'),driver=pin(C/'owned_driver09.py'),worker=pin(C/'build_native_complete03.py'),controller=pin(C/'run_native_complete01.py'),source_freeze=pin(C/'source-freeze.json'),inputs=inputs,output=str(D/'run/build-result'));save(C/'plan.json',p)
for key,v in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(v['path'],e))==v['sha256'],key
receipt={'schema':'orbit-poc-native-complete-build-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'preflight_plan':pin(OLD/'control/plan.json'),'preflight_result':pin(result),'preflight_audit':pin(q.audit),'inputs':inputs,'runtime_pin_count':len(e['runtime_artifacts']),'source_freeze':pin(C/'source-freeze.json'),'mutable_inventory':{n:[str(v)for v in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')}};save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
