from pathlib import Path
import hashlib,json,shutil,importlib.util,socket
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');OLD=B/'native-complete-preflight-03';FAILED=B/'native-complete-build-01';D=B/'native-complete-preflight-04';C=D/'control';I=B/'native-complete-inputs-04'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
assert sha(OLD/'control/plan.json')=='801162ef6f4e7e6c5ae5295c31e2f3df2bf4368631ab3f69540cbc296affe7f3'
old=json.loads((OLD/'control/plan.json').read_text());prior=json.loads((OLD/'control/pipeline.json').read_text());assert prior['status']=='passed_diagnostic'and prior['final_cleanup']['verified']
failure=json.loads((FAILED/'run/build-result/result.json').read_text());j=json.loads((FAILED/'control/pipeline.json').read_text());assert j['status']=='failed_diagnostic'and j['final_cleanup']['verified']
assert failure['error']=="ValueError('Configured toolchain differs: CMAKE_MAKE_PROGRAM')" and [(x['label'],x['returncode'])for x in failure['stages']]==[('public-installer-0',0),('public-installer-1',0),('public-installer-2',0),('configure',0)]
assert not list((FAILED/'build').rglob('*.o'))
assert sha(C/'build_native_complete02.py')=='6221cf6fbb9cd9c93104db998d934c57c75cc0249fa70ec2b32d989c9686ca61'
lineage=json.loads((I/'ninja-lineage.json').read_text());original,current=lineage['cache_files'];assert original['selected']==current['selected']
ninja={'path':'/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/v3/native-env/bin/ninja','sha256':'295d6db0235d00b2dd280f732e108568cc006a49918614db3f719d5a9d2d4ebf'}
assert all('CMAKE_MAKE_PROGRAM:FILEPATH='+ninja['path']in x['selected']for x in (original,current))
allfields=json.loads((I/'all-cache-fields.json').read_text())['records'];assert allfields['engineering-02']['selected']==allfields['native-complete-build-01']['selected'];assert not any(x.startswith('CMAKE_C_COMPILER:')for x in allfields['engineering-02']['selected'])
tool=json.loads(Path(old['inputs']['toolchain']['path']).read_text());assert tool['ninja']=={'path':'/usr/bin/ninja','sha256':'a9ddfbf7e365a2e5026ed44f9173e498e37d8b71ec5e259b2c2a684f16cfa862'};tool['ninja']=ninja;save(I/'toolchain.json',tool)
for name in ('source','native_source','build','binaries','run','temporary'):assert not(D/name).exists(),name
shutil.copytree(OLD/'source',D/'source')
for name in ('native_source','build','binaries','run','temporary'):(D/name).mkdir()
for name in ('owned_driver09.py','with_correctness_namespace_09.py','source-freeze.json','run_native_complete01.py','launch_native_complete01.py'):shutil.copy2(OLD/'control'/name,C/name)
request=json.loads(Path(old['inputs']['installation_request']['path']).read_text());request['output']=str(D/'native_source/reproduction');save(I/'installation-request.json',request)
e=json.loads(Path(old['execution']['path']).read_text());e['paths'].update(root=str(D),source=str(D/'source'),control=str(C),native_source=str(D/'native_source'),build=str(D/'build'),binaries=str(D/'binaries'),run=str(D/'run'),temporary=str(D/'temporary'),wrapper=str(C/'with_correctness_namespace_09.py'));e['host']={'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()};assert not any(x['target']==str(I)for x in e['read_only_bindings']);e['read_only_bindings'].append({'source':str(I),'target':str(I)})
inputs=dict(old['inputs'],toolchain=pin(I/'toolchain.json'),installation_request=pin(I/'installation-request.json'))
for name in ('owned_driver09.py','with_correctness_namespace_09.py','build_native_complete02.py','run_native_complete01.py'):e['runtime_artifacts']['native_complete04_'+name]=pin(C/name)
for key in ('toolchain','installation_request'):e['runtime_artifacts']['native_complete04_'+key]=inputs[key]
e['runtime_artifacts']['native_complete04_ninja']=ninja
for name in ('ninja-lineage.json','all-cache-fields.json'):e['runtime_artifacts']['native_complete04_'+name]=pin(I/name)
save(C/'execution.json',e)
spec=importlib.util.spec_from_file_location('owned',C/'owned_driver09.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o);o.load_execution(C/'execution.json');assert o.source_receipt(D/'source')==json.loads((C/'source-freeze.json').read_text())['source']
p=dict(old,execution=pin(C/'execution.json'),driver=pin(C/'owned_driver09.py'),worker=pin(C/'build_native_complete02.py'),controller=pin(C/'run_native_complete01.py'),source_freeze=pin(C/'source-freeze.json'),inputs=inputs,output=str(D/'run/preflight'));save(C/'plan.json',p)
for key,v in e['runtime_artifacts'].items():assert sha(o.resolved_host_path(v['path'],e))==v['sha256'],key
receipt={'schema':'orbit-poc-native-complete-preflight-recovery-staging-v1','plan':pin(C/'plan.json'),'execution':pin(C/'execution.json'),'old_plan':pin(OLD/'control/plan.json'),'failed_pipeline':pin(FAILED/'control/pipeline.json'),'failed_result':pin(FAILED/'run/build-result/result.json'),'declared_delta':'Pin actual original native-env Ninja1.13.2; strict CXX/Fortran-only cache guard; fresh preflight outputs. Same source/installers/compiler/flags/models.','inputs':inputs,'runtime_pin_count':len(e['runtime_artifacts']),'source_freeze':pin(C/'source-freeze.json'),'mutable_inventory':{n:[str(v)for v in(D/n).iterdir()]for n in('native_source','build','binaries','run','temporary')}};save(C/'staging.json',receipt);print(json.dumps(receipt,indent=2))
