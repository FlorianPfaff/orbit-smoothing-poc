from pathlib import Path
from copy import deepcopy
import hashlib,json,datetime,xml.etree.ElementTree as ET
B=Path('/home/emper/orbit-nuisance-performance/wholefit01');C=B.parent/'control'
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def read(p):return json.loads(Path(p).read_text())
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
p=read(B/'preparation.json');assert sha(B/'preparation.json')=='ca7b5cf489d01f7a78a96fddf8eaf08aa13fec4294d122bd21d011b6dc3cfd35'
original=read(p['original_request']['path']);oldprep=read(p['original_native_preparation']['path']);newprep=read(p['adapted_native_preparation']['path'])
for rec in [p['original_request'],p['original_native_preparation'],p['adapted_native_preparation'],*p['requests']]:assert sha(rec['path'])==rec['sha256']
assert p['original_request']['sha256']=='0fd71929a448587a00574216c3ebc79b9453de314beb989b9c8d4b32d333bbf1'
assert Path(p['original_request']['path']).read_bytes()==Path('/mnt/d/orbit-segmented-v4/control/campaign09-first-attempt01/request.json').read_bytes()
capture=read(B/'capture-inputs02.receipt.json');copies=read(B/'local-input-copies01.json');checked={}
def check(path,digest):
 if path in checked:assert checked[path]==digest;return
 assert sha(path)==digest,path;checked[path]=digest
for row in capture['entries']:
 assert row['local_sha256']==row['sha256_before']==row['sha256_after']==row['source']['sha256']
 assert Path(row['local_path']).stat().st_size==row['bytes'];check(row['local_path'],row['local_sha256'])
for row in copies['auxiliary']:
 assert Path(row['target']).stat().st_size==row['bytes'];check(row['target'],row['sha256'])
filemap=p['file_mappings'];inverse={v:k for k,v in filemap.items()};assert len(inverse)==len(filemap)
config_hash_inverse={r['local_sha256']:r['original_sha256'] for r in p['configuration_transformations']}
config_hash_inverse[p['adapted_native_preparation']['sha256']]=p['original_native_preparation']['sha256']
def reverse(v):
 if isinstance(v,list):return [reverse(x) for x in v]
 if isinstance(v,dict):
  out={k:reverse(x) for k,x in v.items()}
  if v.get('path') in inverse and 'sha256' in v and v['sha256'] in config_hash_inverse:out['sha256']=config_hash_inverse[v['sha256']]
  return out
 if isinstance(v,str):
  if v in inverse:return inverse[v]
  for old,new in sorted(p['prefix_mappings'].items(),key=lambda x:len(x[1]),reverse=True):
   if v==new or v.startswith(new+'/'):return old+v[len(new):]
 return v
assert reverse(newprep)==oldprep,'preparation differs beyond reversible paths/config hashes'
for change in p['configuration_transformations']:
 raw=Path(change['local_path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==change['local_sha256']
 for old,new in sorted(p['prefix_mappings'].items(),key=lambda x:len(x[1]),reverse=True):raw=raw.replace(new.encode(),old.encode())
 assert hashlib.sha256(raw).hexdigest()==change['original_sha256'];ET.fromstring(raw)
refs=[]
for key,path in newprep['configs'].items():
 for element in ET.parse(path).getroot().iter():
  value=(element.text or '').strip()
  if not value or not(element.tag.startswith('inputfile') or element.tag=='filename' and element.attrib.get('label')=='orbitPocCanonicalAttitude'):continue
  expanded=[value.replace('{prn}',f'G{i:02d}') for i in range(1,33)] if '{prn}' in value else [value]
  for name in expanded:
   name=name.replace('{loopTime:%D}',newprep['date']);generated=name==newprep['native_paths']['variational']
   assert generated or Path(name).is_file(),name
   if not generated:assert name in checked,name
   refs.append({'config':key,'tag':element.tag,'path':name,'exists':Path(name).is_file(),'generated':generated,'executed_in_full_fit':key in ('estimate','variational')})
assert refs==p['reachable_configuration_inputs'] and len(refs)==235 and not p['missing_configuration_inputs']
source=read(B/'source-inventory.json');assert canonical(source['files'])==source['sha256'];assert len(source['files'])==318
for path,digest in source['files'].items():check(str(Path(source['source_root'])/path),digest)
protocol=read(B/'input-protocol01.json');assert protocol['protocol_hash']==canonical({k:v for k,v in protocol.items() if k!='protocol_hash'})
assert protocol['order']==['cache1','cache0'];assert protocol['controls']==original['numerical_controls'];assert protocol['case']==original['case'];assert protocol['parameters']==original['parameters']
assert original['id']=='leo500-quiet-normal-groops_pulses-24h--dense_corrected'
assert original['case']['duration_hours']==24 and original['case']['seed']==610000
assert original['parameters']=={'frame':'CRF','interval_seconds':1200.0,'sigma_velocity_m_s':0.0001}
assert original['numerical_controls']['wall_time_seconds']==7200 and original['numerical_controls']['maximum_accepted_iterations']==32 and original['numerical_controls']['maximum_trial_evaluations']==96
allowed={'expected_native_binary_sha256','id','input_manifest_hash','job_sha256','protocol_hash','segmented_manifest_hash','source_hash','split'}
assert set(p['changed_request_attribution_fields'])==allowed
requests=[]
for rec in p['requests']:
 request=read(rec['path']);assert request['job_sha256']==canonical({k:v for k,v in request.items() if k!='job_sha256'})
 assert request['nuisance_performance_cache']==rec['cache'];assert request['original_frozen_request']=={**p['original_request'],'job_sha256':original['job_sha256'],'protocol_hash':original['protocol_hash']}
 assert request['protocol_hash']==request['segmented_manifest_hash']==protocol['protocol_hash'];assert request['source_hash']==source['sha256'];assert request['input_manifest_hash']==canonical(request['estimation_inputs'])
 assert request['expected_native_binary_sha256']==protocol['candidate_sha256']=='8b6986943d7836c4f4cb03278069893d3b797a5bcbd2a3f4ba763a1b27a6fcb2'
 check(request['backend']['groops_executable'],request['expected_native_binary_sha256'])
 converted=reverse(request)
 assert set(converted)==set(original)|{'nuisance_performance_cache','original_frozen_request'}
 for name in allowed:converted[name]=original[name]
 converted.pop('nuisance_performance_cache');converted.pop('original_frozen_request')
 converted['backend']['groops_executable']=original['backend']['groops_executable']
 assert converted==original,'request differs beyond declared attribution/path treatment'
 requests.append(request)
x=deepcopy(requests[0]);y=deepcopy(requests[1])
for r in (x,y):
 for k in ('id','job_sha256','nuisance_performance_cache'):r.pop(k)
assert x==y
runtime=read(B/'runtime-closures01.json');assert sha(B/'runtime-closures01.json')==protocol['runtime_closures_sha256']
a=runtime['closures']['candidate'];z=runtime['closures']['exporter'];assert a['dependencies']==z['dependencies'] and len(a['dependencies'])==14
assert a['executable']['sha256']==protocol['candidate_sha256'];assert z['executable']['sha256']==original['backend']['diagnostic_native']['sha256']==protocol['exporter_sha256']
for v in (a,z):check(v['executable']['path'],v['executable']['sha256'])
for v in a['dependencies']:check(v['path'],v['sha256'])
assert len(runtime['historical_exporter_dependency_differences'])==6
initial=newprep['nominal_initialization'];assert initial['converged'];assert initial['reproducibility_inputs']==[dict(r,path=filemap[r['path']]) for r in oldprep['nominal_initialization']['reproducibility_inputs']]
assert newprep['metadata']['reference_inputs_used'] is False
for forbidden in ('evaluation_inputs','calibration_inputs','truth','reference_orbit','slr_validation'):assert forbidden not in newprep and forbidden not in requests[0]
report={'schema':'orbit-poc-wholefit-preparation-independent-review-v1','status':'accepted_exact_case_local_relocation_pending_launch_freeze','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'preparation':pin(B/'preparation.json'),'input_protocol':pin(B/'input-protocol01.json'),'capture':pin(B/'capture-inputs02.receipt.json'),'local_copies':pin(B/'local-input-copies01.json'),'runtime_closures':pin(B/'runtime-closures01.json'),'source_inventory':pin(B/'source-inventory.json'),'audit_script':pin(Path(__file__)),'request_templates':[pin(Path(r['path'])) for r in p['requests']],'original_request':p['original_request'],'checks':{'captured_input_files_verified':len(capture['entries']),'auxiliary_files_verified':len(copies['auxiliary']),'xml_byte_roundtrips':len(p['configuration_transformations']),'configuration_references_verified':len(refs),'original_request_estimation_artifacts':len(original['estimation_inputs']),'source_files_verified':len(source['files']),'same_candidate_and_dependency_closure':True,'shared_dependency_files':len(a['dependencies']),'historical_system_library_differences_disclosed':6,'complete_inverse_preparation_and_request_equality':True,'same_inputs_initialization_priors_weights_controls':True,'all_local_hashes_verified':len(checked),'no_truth_inputs':True,'native_runs':0},'limits':protocol['resource_limits'],'scope':'Exact original first timeout case relocated locally, with same candidate/cache1-cache0. Historical exporter bytes preserved; six local system dependency differences forbid claiming historical runtime equivalence. No timings or full-fit outcome yet. Concrete launch freeze/admission remains separately required.','findings':[],'accepted_covariance':False,'release_authority':False}
out=C/'wholefit-preparation-independent-review01.json'
with out.open('x') as f:json.dump(report,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps(pin(out)),flush=True)
