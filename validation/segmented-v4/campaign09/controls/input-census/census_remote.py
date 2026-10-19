from pathlib import Path
import datetime,hashlib,importlib.util,json,os,xml.etree.ElementTree as ET
B=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff');S=B/'fit-seal-control-07/sealed-inputs-03';R=B/'validation-07/run'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def need(v,m):
 if not v:raise ValueError(m)
def module(name,p,digest):
 need(sha(p)==digest,'Changed control '+str(p));s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
driver=module('resolver',B/'validation-07/control/owned_driver09.py','72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd')
execution=B/'preparation-07/control/execution.json';need(sha(execution)=='b6fa593f108beaabc8d2e8a6d6ce2e9e06aba9954b6ed9c1425b96b9fb89f6c3','Changed execution');E=json.loads(execution.read_text())
planner=module('planner',B/'fit-seal-control-07/plan_segmented_fit_namespace02.py','2a00bb3fa57bef3c034e3ab96348c6f720d25af5473e65efb9a5a6dc5a7d68d2')
mountfile=S/'mount-plan.json';need(sha(mountfile)=='937e2bf3cb2dae31e459950f912593058cf2f58a30cc77c218794fe295ee6826','Changed mount plan');mount=json.loads(mountfile.read_text());allow=json.loads((S/'allowlist.json').read_text());need(sha(S/'allowlist.json')=='a768ddf14c8ebb7fb11e4752c9787da407f7db77ee618176ae2946ce32c4ed3d','Changed allowlist')
links={r['path']:r['target'] for r in mount['canonical_symlinks']};links.update({'/usr/lib64/'+n:'/usr/lib/x86_64-linux-gnu/'+n for n in ('libc.so.6','libdl.so.2','libm.so.6','libmvec.so.1','libpthread.so.0','libutil.so.1')})
requirements={};metadata={};sources=[];payload={}
def add(pin,reason):
 need(isinstance(pin,dict) and isinstance(pin.get('path'),str) and isinstance(pin.get('sha256'),str) and len(pin['sha256'])==64,'Invalid required pin '+reason)
 path=pin['path'];need(path.startswith('/'),'Nonabsolute required path '+path)
 if path in requirements:need(requirements[path]['sha256']==pin['sha256'],'Conflicting required pin '+path);requirements[path]['reasons'].add(reason)
 else:requirements[path]={'path':path,'sha256':pin['sha256'],'reasons':{reason}}
 return path
def real(path):return driver.resolved_host_path(path,E)
def read(pin,reason):
 path=add(pin,reason)
 if path not in metadata:
  backing=real(path);data=backing.read_bytes();need(hashlib.sha256(data).hexdigest()==pin['sha256'],'Changed metadata '+path);metadata[path]={'canonical':path,'backing':str(backing),'sha256':pin['sha256'],'bytes':len(data)};payload[path]=json.loads(data)
 return payload[path]
def local(path,reason):
 p=real(str(path));return read({'path':str(path),'sha256':sha(p)},reason)
def nodes(value,reason):
 if isinstance(value,dict):
  if 'path' in value and 'sha256' in value:add(value,reason)
  for item in value.values():nodes(item,reason)
 elif isinstance(value,list):
  for item in value:nodes(item,reason)
def tree(inv,reason):
 for row in inv['entries']:
  if row['kind']=='file':add({'path':inv['root'].rstrip('/')+'/'+row['relative'],'sha256':row['sha256']},reason)
def request_inputs(req,reason,normalization=False):
 nodes(req['estimation_inputs'],reason+':nested_estimation')
 for item in req['estimation_inputs']:
  kind=item.get('metadata',{}).get('kind')
  if kind=='native_preparation':
   prepared=read(item,reason+':_preparation');nodes(prepared.get('native_artifacts',[]),reason+':native_artifacts')
   if 'native_data_inventory' in prepared:tree(prepared['native_data_inventory'],reason+':native_data_inventory')
  if normalization and kind=='known_gnss_osb_datum_normalization':
   normalized=read(item,reason+':flight_normalization_proofs');need(normalized.get('schema_version')==1 and normalized.get('bias_inputs'),'Invalid normalization ledger');nodes(normalized['bias_inputs'],reason+':flight_normalization_bias_inputs')
config=local(B/'validation-07/control/segmented-v4.json','probe:config');manifest=local(R/'manifest.json','verify_manifest');plan=local(R/'plan.json','freeze_plan');local(R/'preparation-status.json','preparation_status');local(R/'prepared-input-catalog.json','verify_manifest:catalog')
need(manifest['manifest_hash']=='63f3010564c6da76c0f92a007ed1fbe057d610d44cccb6b5e4f509afafbf2251','Changed manifest identity')
for case in manifest['cases']:
 req=read(case['request_artifact'],'frozen_request:'+case['case_id']);need(req==case['fit_request'],'Changed frozen request');request_inputs(req,'frozen_request:'+case['case_id'],case['stage']=='flight')
catalog=read(config['flight_input_catalog'],'flight_sources:catalog');read(catalog['original_plan'],'flight_sources:original_plan');original=read(catalog['original_manifest'],'flight_sources:original_manifest');ids={'retained-april24-'+coverage+'-'+method for coverage in ('normal','blackout') for method in ('groops_pulses','groops_log_drag_ou')}
selected=[x for x in original['cases'] if x['case_id'] in ids];need(len(selected)==4,'Missing original four flight cases')
for case in selected:request_inputs(read(case['historical_request'],'flight_sources:historical_request:'+case['case_id']),'flight_sources:'+case['case_id'],True)
for pin in config['prior_seed_protocols']:read(pin,'seed_inventory')
reference=read(config['corrected_reference'],'corrected_reference')
for role in ('dense_runtime','segmented_runtime'):
 runtime=config[role]
 for key in ('native','python','build_manifest','segmented_solver'):
  if runtime[key].get('path'):add(runtime[key],'verify_runtime:'+role+':'+key)
 libraries=read(runtime['library_manifest'],'verify_library_manifest:'+role);nodes(libraries['files'],'runtime_library_files');add(libraries['loader'],'runtime_loader');nodes(libraries['executables'],'runtime_executable_dependencies')
 for name,pin in libraries['runtime_trees'].items():tree(read(pin,'runtime_inventory:'+name),'runtime_tree:'+name)
source_root=config['segmented_runtime']['source_root'];source=plan['source'];need(source['sha256']==config['segmented_runtime']['source_sha256'],'Changed frozen source')
source_rows=source['files']
if isinstance(source_rows,dict):
 for name,digest in source_rows.items():add({'path':source_root+'/'+name,'sha256':digest},'source_snapshot')
else:
 for row in source_rows:add({'path':source_root+'/'+row['path'],'sha256':row['sha256']},'source_snapshot')
validation=read(config['validation_inputs'],'validation.verify_inputs');nodes(validation['input_artifacts'],'validation_original_inputs');nodes(validation['dependencies'],'validation_dependencies');read(validation['source_reference'],'validation_source_reference')
for inv in validation['data_directories']:tree(inv,'validation_native_data')
for role in ('density_request','pulse_request','full_day_request'):
 req=read(validation['input_artifacts'][role],'validation_request:'+role);request_inputs(req,'validation_request:'+role)
flight=read(validation['input_artifacts']['flight_prepared'],'validation_flight_prepared');nodes(flight['estimation_inputs'],'validation_flight_estimation_inputs')
for name in ('context.json','plan.json'):local(R/'validation'/name,'validation:'+name)
latest=local(R/'validation/latest.json','validation:latest');pipeline=read(latest['pipeline'],'validation:pipeline')
for step in pipeline['steps']:
 name=step['name'];directory=Path(step['directory']);result=read(step['execution'],'validation_execution:'+name);local(directory/'request.json','validation_request:'+name)
 if name in ('native-tests','correction-tests','segmented-native-tangent','segmented-structural'):
  path=directory/'tests.xml';add({'path':str(path),'sha256':sha(real(str(path)))},'validation_junit:'+name)
 elif 'refinement' in name:local(directory/'result/result.json','refinement_result:'+name)
 elif name.startswith('objective-'):local(directory/'result/validation.json','objective_validation:'+name)
 elif name.startswith('nuisance-replay'):
  data=local(directory/'result/receipt.json','nuisance_receipt:'+name);path=directory/'result/profile.xml';add({'path':str(path),'sha256':data['replay_profile_sha256']},'nuisance_executed_xml:'+name)
 elif name.startswith('linearization-'):nodes(local(directory/'result/validation.json','linearization_result:'+name),'linearization_nested:'+name)
 else:raise ValueError('Unknown stage')
# Replay XML explicit input aliases are hashed directly by validation.verify_inputs.
for role,prefix in (('old_nuisance_replay','old'),('candidate1_nuisance_replay','new')):
 pin=validation['input_artifacts'][role];data=real(pin['path']).read_bytes();need(hashlib.sha256(data).hexdigest()==pin['sha256'],'Changed original XML');xml=ET.fromstring(data)
 for tag,key in (('inputfileVariational','variational'),('inputfileNumericsReferenceParameters','reference'),('inputfileLogDensity','density')):
  for node in xml.iter(tag):add({'path':node.text.strip(),'sha256':validation['input_artifacts'][prefix+'_replay_'+key]['sha256']},'validation_replay_explicit_alias:'+role)
# Verify the frozen source files driving this independently selected read graph.
for name in ('src/orbit_poc/segmented/protocol.py','src/orbit_poc/segmented/validation.py','src/orbit_poc/segmented/report.py','src/orbit_poc/comparison/backend.py'):
 p=source_root+'/'+name;r=requirements[p];backing=real(p);need(sha(backing)==r['sha256'],'Verifier source changed');sources.append({'path':p,'backing':str(backing),'sha256':r['sha256']})
missing=[];different=[];covered=0
for path,row in sorted(requirements.items()):
 row['reasons']=sorted(row['reasons']);resolved=planner.links_resolve(path,links);row['namespace_resolved']=resolved;backing=mount['verified_file_backings'].get(resolved)
 if backing is not None and backing['sha256']==row['sha256']:row['classification']='covered';covered+=1;continue
 row['classification']='namespace_hash_differs' if backing else 'namespace_file_absent'
 try:
  physical=real(path);s=physical.stat();actual=sha(physical);row.update(host_backing=str(physical),host_sha256=actual,host_bytes=s.st_size,host_device=s.st_dev,host_inode=s.st_ino,host_matches_expected=actual==row['sha256'],host_lstat_mode=physical.lstat().st_mode)
 except (OSError,ValueError) as error:row['host_error']=repr(error)
 row['other_namespace_paths_same_sha']=[p for p,b in mount['verified_file_backings'].items() if b['sha256']==row['sha256']]
 row['denied_matches']=[{k:r[k] for k in ('path','resolved','sha256','bytes','reason','content_sensitive') if k in r} for r in allow['denied_files'] if path in (r['path'],r['resolved']) or row['sha256']==r['sha256']]
 (different if backing else missing).append(row)
value={'schema':'orbit-poc-public-verifier-read-closure-census-v1','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'hostname':os.uname().nodename,'boot':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'mount_plan':{'path':str(mountfile),'sha256':sha(mountfile)},'allowlist':{'path':str(S/'allowlist.json'),'sha256':sha(S/'allowlist.json')},'sources':sources,'metadata_reads':list(metadata.values()),'required_file_count':len(requirements),'covered_count':covered,'missing_count':len(missing),'different_hash_count':len(different),'missing':missing,'different_hash':different,'requirements':[requirements[k] for k in sorted(requirements)],'scope':'Independent explicit read graph of verify_manifest and require_passed at zero prefix; no public verifier execution, native/loader process, namespace, mutation, or bulk required-file rehash. Only required JSON/source metadata and uncovered artifacts are read/hashed.'}
print(json.dumps(value,sort_keys=True))
