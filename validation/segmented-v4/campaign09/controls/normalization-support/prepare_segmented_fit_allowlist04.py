#!/usr/bin/env python3
"""Seal an external, read-only fit input allowlist; never starts a process.

The production wrapper must start from an empty root and expose only this
allowlist plus separately pinned system runtime mounts. Passing this builder is
not a substitute for the required in-namespace verifier and denial probes.
"""
from pathlib import Path
import argparse,hashlib,json,os,stat
SCHEMA='orbit-poc-segmented-fit-allowlist-plan-v2'
SYNTHETIC_ACCURACY_SHA256='e58e04008615bea9e065ab655a13367f51063deffe872f383e6e122a876033b7'
FORBIDDEN_ROLES={'truth','reference_orbit','slr_validation','calibration_inputs','evaluation_inputs'}

def need(ok,message):
 if not ok:raise ValueError(message)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
 return h.hexdigest()
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def absolute(value):
 p=Path(value);need(p.is_absolute() and '..' not in p.parts and str(p)==str(p.absolute()),'Noncanonical absolute path');need(not any(p==Path(x) or Path(x) in p.parents for x in ('/proc','/sys','/dev')),'Kernel/device paths belong only to the dedicated wrapper')
 return p

def pin(p):
 p=absolute(str(p));need(p.is_file(),'Required file missing: '+str(p));s=p.stat()
 return {'path':str(p),'sha256':sha(p),'bytes':s.st_size,'resolved':str(p.resolve()),'link_target':os.readlink(p) if p.is_symlink() else None,'device':s.st_dev,'inode':s.st_ino}
def check(record):
 p=absolute(record['path']);current=pin(p)
 need(current['sha256']==record['sha256'] and ('bytes' not in record or current['bytes']==record['bytes']),'Changed required file: '+str(p))
 for k in ('resolved','link_target','device','inode'):
  if k in record:need(current[k]==record[k],'Changed file identity: '+str(p)+' '+k)
 return current

def inventory(root):
 root=absolute(str(root));need(root.is_dir() and not root.is_symlink(),'Inventory needs a real root directory')
 entries=[]
 def walk(d,relative,ancestors):
  resolved=d.resolve();need(resolved not in ancestors,'Symlink directory cycle')
  for p in sorted(d.iterdir()):
   need(p.exists(),'Dangling symlink');rel=(relative/p.name).as_posix();e={'relative':rel,'kind':'directory' if p.is_dir() else 'file','link_target':os.readlink(p) if p.is_symlink() else None,'resolved':str(p.resolve())}
   if p.is_dir():entries.append(e);walk(p,relative/p.name,ancestors|{resolved})
   else:
    need(p.is_file(),'Special file in input inventory');e.update(bytes=p.stat().st_size,sha256=sha(p));entries.append(e)
 walk(root,Path(),set());return {'schema':'orbit-poc-native-data-directory-v1','root':str(root),'entries':entries}

def artifact_nodes(value):
 if isinstance(value,dict):
  need(not (value.get('role') in FORBIDDEN_ROLES),'Evaluation role in allowlist dependency')
  if 'path' in value and 'sha256' in value:yield value
  for k,v in value.items():
   if k in FORBIDDEN_ROLES:raise ValueError('Evaluation field in blind dependency')
   yield from artifact_nodes(v)
 elif isinstance(value,list):
  for v in value:yield from artifact_nodes(v)

def derive_estimation(manifest):
 """Find files actually consumed by blind requests and exact native data trees."""
 rows={};data_directories=[]
 def add(record,reason):
  x=check(record);old=rows.get(x['path'])
  if old:need(old['sha256']==x['sha256'],'Conflicting input identity');old['reasons'].add(reason)
  else:rows[x['path']]={**x,'reasons':{reason}}
 cases=manifest['cases'];need(len(cases)==28 and len({x['case_id'] for x in cases})==28,'Expected28 prepared cases')
 need(len(manifest['attempts'])==68 and len({x['attempt_id'] for x in manifest['attempts']})==68,'Expected68 frozen attempts')
 for case in cases:
  request=case['fit_request'];need(not (FORBIDDEN_ROLES&request.keys()),'Evaluation input in fit request')
  add(case['request_artifact'],'frozen_request')
  actual=json.loads(Path(case['request_artifact']['path']).read_text());need(actual==request,'Request content differs')
  preps=[]
  for item in request['estimation_inputs']:
   for item_pin in artifact_nodes(item):add(item_pin,'estimation_input:'+item['role'])
   if item.get('metadata',{}).get('kind')=='synthetic_gnss_accuracy' or item.get('kind')=='synthetic_gnss_accuracy':add(item,'shared_model:synthetic_gnss_accuracy')
   if item.get('metadata',{}).get('kind')=='native_preparation':preps.append(item)
  need(len(preps)==1,'Need exactly one blind native preparation')
  prepared=json.loads(Path(preps[0]['path']).read_text())
  need(not(FORBIDDEN_ROLES&prepared.keys()),'Blind preparation contains evaluation fields')
  for item in artifact_nodes(prepared):add(item,'native_preparation_dependency')
  inv=prepared['native_data_inventory'];need(inventory(inv['root'])==inv,'Prepared data membership changed')
  data_directories.append(inv)
  for entry in inv['entries']:
   if entry['kind']=='file':add({'path':str(Path(inv['root'])/entry['relative']),'sha256':entry['sha256'],'bytes':entry['bytes']},'native_data_membership')
 return rows,data_directories

def shared_transmitter(path,item,rows):
 """Recognize only GPS transmitter products, never the simulated receiver."""
 import re
 path=Path(path);kind=path.parent.name
 role={'orbit':'gnss_orbits','clock':'gnss_clocks','attitude':'gnss_attitudes','signalBias':'gnss_biases'}.get(kind)
 if not role or not re.search(r'\.G[0-9]{2}\.',path.name):return False
 if not any('estimation_input:'+role in row['reasons'] for row in rows.values()):return False
 return any('native_data_membership' in row['reasons'] and Path(row['path']).parent.name==kind and Path(row['path']).name==path.name and row['sha256']==item['sha256'] and row['bytes']==item['bytes'] for row in rows.values())


def shared_observation(path,item,rows,manifest,run):
 """A full normal-coverage observation copy with explicit source/mask lineage.

 The generation pathname stays denied. This permits matching measurement bytes,
 never receiver-state, clock, ambiguity or independent reference content.
 """
 for case in manifest['cases']:
  physical=case.get('case',{});request=case.get('fit_request',{})
  if case.get('stage')!='synthetic' or request.get('stage')!='synthetic':continue
  if physical.get('duration_hours')!=72 or physical.get('coverage')!='normal':continue
  mask=physical.get('mask',{})
  if mask.get('intervals_seconds')!=[] or mask.get('duration_seconds')!=259200:continue
  if request.get('case')!=physical or request.get('mask_hash')!=canonical(mask):continue
  generation=f"{physical.get('orbit')}-{physical.get('atmosphere')}-{physical.get('seed')}-continuous72h"
  if case.get('generation_id')!=generation:continue
  epoch=physical.get('epoch','');date=epoch.split('T')[0]
  if len(date)!=10 or not date.replace('-','').isdigit():continue
  expected=Path(run)/'preparation/generation'/generation/'observations'/('GPS1B_'+date+'_C_synthetic.txt')
  if Path(path)!=expected:continue
  for ref in request.get('estimation_inputs',[]):
   if ref.get('role')!='gnss_observations':continue
   row=rows.get(ref.get('path'))
   if not row or 'estimation_input:gnss_observations' not in row['reasons']:continue
   if 'native_preparation_dependency' not in row['reasons']:continue
   if ref.get('mask_hash')!=request['mask_hash'] or type(ref.get('records')) is not int or ref['records']<=0:continue
   if ref.get('source_sha256')!=ref.get('sha256') or ref.get('sha256')!=item['sha256']:continue
   if ref.get('bytes')!=item['bytes'] or (row['sha256'],row['bytes'])!=(item['sha256'],item['bytes']):continue
   return True
 return False

def collect_support(config_pin,run_root,system_support):
 """Derive the readonly public-run verifier closure from actual sealed records.

 System helpers/library/locale files are supplied as a separately reviewed exact
 inventory; no directory-wide /usr, /etc, /lib or host-root mount is authorized.
 This never runs the verifier, loader, estimator or any subprocess.
 """
 run=absolute(run_root);files={};directories=set()
 def add(record):
  value=check(record);old=files.get(value['path']);need(old is None or old==value,'Conflicting support identity');files[value['path']]=value;return value
 def read(record):
  value=add(record);return json.loads(Path(value['path']).read_text())
 def local(path):return read(pin(path))
 def nodes(value):
  for item in artifact_nodes(value):add(item)
 def native_tree(inv):
  need(inventory(inv['root'])==inv,'Support native tree changed');directories.add(inv['root'])
  for entry in inv['entries']:
   path=str(Path(inv['root'])/entry['relative'])
   if entry['kind']=='file':add({'path':path,'sha256':entry['sha256'],'bytes':entry['bytes']})
   else:directories.add(path)
 config=read(config_pin);manifest=local(run/'manifest.json');local(run/'plan.json');local(run/'preparation-status.json')
 read(manifest['prepared_input_catalog'])
 for name in ('context.json','plan.json','latest.json'):local(run/'validation'/name)
 latest=local(run/'validation/latest.json');pipeline=read(latest['pipeline'])
 need(pipeline.get('status')=='passed','Support closure requires terminal successful public validation')
 for name in ('corrected_reference','validation_inputs','flight_input_catalog'):add(config[name])
 add(config['resources']['admission'])
 for record in config['prior_seed_protocols']:add(record)
 for runtime in manifest['runtimes'].values():
  add(runtime['build_manifest']);nodes(runtime['libraries'])
  # Runtime inventories themselves are checked here; the full data trees are
  # independently verified through the builder's exact safe-tree records.
 for name in ('dense_runtime','segmented_runtime'):add(config[name]['library_manifest'])
 validation=read(config['validation_inputs']);nodes(validation['input_artifacts']);nodes(validation['dependencies']);add(validation['source_reference'])
 for inv in validation['data_directories']:native_tree(inv)
 # Follow only the original four flight requests, not arbitrary historical
 # evaluation data referenced elsewhere in the150-case protocol metadata.
 catalog=read(config['flight_input_catalog']);read(catalog['original_plan']);original=read(catalog['original_manifest'])
 flight_ids={'retained-april24-'+coverage+'-'+method for coverage in ('normal','blackout') for method in ('groops_pulses','groops_log_drag_ou')}
 selected=[c for c in original['cases'] if c['case_id'] in flight_ids];need(len(selected)==4,'Original four flight requests missing')
 for case in selected:
  request=read(case['historical_request']);nodes(request['estimation_inputs'])
  for item in request['estimation_inputs']:
   if item.get('metadata',{}).get('kind')=='native_preparation':nodes(read(item))
   elif item.get('metadata',{}).get('kind')=='known_gnss_osb_datum_normalization':
    ledger=read(item);biases=ledger.get('bias_inputs')
    need(ledger.get('schema_version')==1 and isinstance(biases,list) and biases,'Unknown original flight normalization ledger')
    for bias in biases:add(bias)
 for step in pipeline['steps']:
  need(step['status']=='passed','Support includes a failed native gate');read(step['execution']);directory=absolute(step['directory']);local(directory/'request.json');name=step['name']
  if name in ('native-tests','correction-tests','segmented-native-tangent','segmented-structural'):add(pin(directory/'tests.xml'))
  elif 'refinement' in name:local(directory/'result/result.json')
  elif name.startswith('objective-'):local(directory/'result/validation.json')
  elif name.startswith('nuisance-replay'):local(directory/'result/receipt.json');add(pin(directory/'result/profile.xml'))
  elif name.startswith('linearization-'):nodes(local(directory/'result/validation.json'))
  else:raise ValueError('Unknown verification stage')
 need(system_support.get('schema')=='orbit-poc-segmented-system-support-files-v1' and system_support.get('files'),'Explicit system support inventory is required')
 for item in system_support['files']:add(item)
 return {'schema':'orbit-poc-segmented-fit-support-files-v1','manifest_hash':manifest['manifest_hash'],'files':[files[k] for k in sorted(files)],'directories':sorted(directories),'scope':'Readonly verification/native-input dependencies plus separately pinned system support; no production execution authorization'}

def build(plan):
 need(set(plan)=={'schema','run_root','manifest','preparation_status','validation_audit','support_inventory','safe_trees','denied_trees','known_flight_references','temporary_root'},'Unknown fit allowlist plan fields')
 need(plan['schema']==SCHEMA,'Wrong plan schema');run=absolute(plan['run_root'])
 manifest_pin=check(plan['manifest']);manifest=json.loads(Path(manifest_pin['path']).read_text())
 need(manifest['manifest_hash']==canonical({k:v for k,v in manifest.items() if k!='manifest_hash'}),'Prepared manifest identity differs')
 status_pin=check(plan['preparation_status']);status=json.loads(Path(status_pin['path']).read_text())
 need(status.get('status')=='prepared' and status.get('manifest_hash')==manifest['manifest_hash'],'Preparation not sealed')
 audit_pin=check(plan['validation_audit']);audit=json.loads(Path(audit_pin['path']).read_text())
 need(audit.get('schema')=='orbit-poc-segmented-validation-terminal-independent-review-v1' and audit.get('consistency_passed') is True and audit.get('scientific_status')=='passed_scoped_checks' and audit.get('cleanup_verified') is True,'Full native validation audit is not a verified scoped pass')
 need(audit['identity']['comparison_source_sha256']==manifest['runtimes']['segmented']['source_sha256']==manifest['runtimes']['dense']['source_sha256'] and audit['identity']['native_sha256']==manifest['runtimes']['segmented']['native']['sha256'] and audit['identity']['solver_sha256']==manifest['runtimes']['segmented']['segmented_solver']['sha256'],'Validation audit source/runtime differs from prepared benchmark')
 runplan_pin=check(audit['artifacts']['run_plan']);runplan=json.loads(Path(runplan_pin['path']).read_text());need(runplan['plan_hash']==manifest['plan_hash']==canonical({k:v for k,v in runplan.items() if k!='plan_hash'}),'Validation/benchmark execution plan differs')
 rows,datadirs=derive_estimation(manifest);estimation=set(rows)
 def add(record,reason):
  x=check(record)
  if x['path'] in rows:need(rows[x['path']]['sha256']==x['sha256'],'Conflicting read identity');rows[x['path']]['reasons'].add(reason)
  else:rows[x['path']]={**x,'reasons':{reason}}
 for item in (manifest_pin,status_pin,audit_pin):add(item,'sealed_control_metadata')
 supportpin=check(plan['support_inventory']);support=json.loads(Path(supportpin['path']).read_text())
 need(set(support)=={'schema','manifest_hash','files','directories','scope'} and support['schema']=='orbit-poc-segmented-fit-support-files-v1' and support['manifest_hash']==manifest['manifest_hash'],'Support files do not bind prepared manifest')
 for item in support['files']:add(item,'verification_metadata_or_required_native_dependency')
 safe=[]
 expected_trees=set()
 for runtime in manifest['runtimes'].values():
  expected_trees.update({('source',str(absolute(runtime['source_root']))),('python_runtime',str(absolute(runtime['python']['path']).parent.parent)),('native_runtime',str(absolute(runtime['libraries']['directory']).parent))})
 for tree in plan['safe_trees']:
  need(set(tree)=={'kind','inventory'} and tree['kind'] in ('source','python_runtime','native_runtime'),'Unknown safe tree type')
  ip=check(tree['inventory']);inv=json.loads(Path(ip['path']).read_text());need(inv==inventory(inv['root']),'Safe tree membership or bytes changed')
  need((tree['kind'],inv['root']) in expected_trees,'Safe tree is not the frozen source/runtime root')
  safe.append({'kind':tree['kind'],'root':inv['root'],'inventory':ip,'files':sum(e['kind']=='file' for e in inv['entries'])})
  for entry in inv['entries']:
   if entry['kind']=='file':add({'path':str(Path(inv['root'])/entry['relative']),'sha256':entry['sha256'],'bytes':entry['bytes']},'verified_safe_tree')
 need({(x['kind'],x['root']) for x in safe}==expected_trees and len(safe)==len(expected_trees),'Safe tree inventory must contain exactly every frozen runtime/source root')
 # All files in generation/evaluation trees are denied unless required by an
 # already-blinded estimation request. Support metadata cannot grant exceptions.
 need(str(run/'preparation/generation') in plan['denied_trees'],'Entire generation subtree must be denied')
 denies=[];denied_inv=[]
 for root in plan['denied_trees']:
  root=absolute(root);inv=inventory(root);denied_inv.append(inv)
  for entry in inv['entries']:
   if entry['kind']!='file':continue
   p=str(root/entry['relative'])
   if p in estimation:
    role_reasons={x.removeprefix('estimation_input:') for x in rows[p]['reasons'] if x.startswith('estimation_input:')}
    need(bool(role_reasons & {'attitude','gnss_observations','gnss_orbits','gnss_clocks','gnss_biases','gnss_attitudes'}),'Generation exception is not an explicit measured-input role: '+p)
    need(not any(token in Path(p).name.lower() for token in ('truth','simulation_orbit','ambiguity','receiver_clock')),'Truth-like generation file cannot be admitted as an observation')
    continue
   x=pin(p);shared=None
   if Path(p).name=='synthetic_accuracy.xml' and x['sha256']==SYNTHETIC_ACCURACY_SHA256 and any('shared_model:synthetic_gnss_accuracy' in r['reasons'] and r['sha256']==x['sha256'] and r['bytes']==x['bytes'] for r in rows.values()):shared='Exact static synthetic accuracy bytes also pinned by a synthetic_gnss_accuracy estimation artifact'
   elif shared_transmitter(p,x,rows):shared='Exact GPS transmitter conversion bytes also pinned by matching native data membership and external GNSS products'
   elif shared_observation(p,x,rows,manifest,run):shared='Exact noisy GPS observation copy pinned by a full 72-hour normal-coverage synthetic request, explicit source hash, retained mask and native preparation dependency; generation pathname remains denied'
   denies.append({**x,'reason':'Generation/evaluation file not present in blind estimation dependency closure','content_sensitive':shared is None,'shared_input_exception':shared})
 for item in plan['known_flight_references']:
  x=check(item);need(Path(x['path']).name.startswith('GNV') or item.get('role') in ('reference_orbit','slr_validation'),'Unknown flight reference role');denies.append({**x,'reason':'Flight evaluation reference','content_sensitive':True,'shared_input_exception':None})
 denied_paths={x['path'] for x in denies}|{x['resolved'] for x in denies};denied_inodes={(x['device'],x['inode']) for x in denies if x['content_sensitive']};denied_contents={(x['bytes'],x['sha256']) for x in denies if x['content_sensitive'] and x['bytes']>0}
 for path,row in rows.items():
  need(path not in denied_paths and row['resolved'] not in denied_paths and (row['device'],row['inode']) not in denied_inodes,'Denied path or hardlink in read closure: '+path)
  need((row['bytes'],row['sha256']) not in denied_contents,'Copy of denied content in read closure: '+path)
  need(not Path(path).name.startswith('GNV'),'Unlisted flight reference in allowlist')
 for tree in safe:
  root=Path(tree['root']);need(all(root!=Path(d) and root not in Path(d).parents and Path(d) not in root.parents for d in plan['denied_trees']),'Safe tree overlaps a generation/evaluation root')
 # Preserve lexical symlinks and add their exact resolved files. Wrapper must
 # create every lexical parent before readonly binding and preserve link text.
 for row in list(rows.values()):
  if row['resolved']!=row['path']:add({'path':row['resolved'],'sha256':row['sha256'],'bytes':row['bytes']},'resolved_target_of_required_input')
 temporary=absolute(plan['temporary_root']);attempts=run/'attempts';lock=run/'.segmented.lock'
 need(attempts.is_dir() and not attempts.is_symlink() and not any(attempts.iterdir()),'Benchmark attempts directory must be fresh and empty')
 need(temporary.is_dir() and not temporary.is_symlink() and not any(temporary.iterdir()),'Fit temporary directory must be fresh and empty')
 need(lock.is_file() and not lock.is_symlink() and lock.stat().st_size==0,'Exact empty regular lock file is required')
 need((lock.stat().st_dev,lock.stat().st_ino) not in denied_inodes,'Lock aliases denied input')
 need(all(x.resolve()==x for x in (attempts,temporary,lock)),'Writable paths cannot contain symlink aliases')
 for target in (attempts,temporary):
  need(all(target!=Path(x['path']) and target not in Path(x['path']).parents and Path(x['path']) not in target.parents for x in rows.values()),'Writable path overlaps an allowed file')
  need(all(target!=Path(d) and target not in Path(d).parents and Path(d) not in target.parents for d in plan['denied_trees']),'Writable path overlaps denied data')
 files=[{**row,'reasons':sorted(row['reasons'])} for _,row in sorted(rows.items())]
 directories=set(support['directories'])
 for inv in datadirs:
  directories.add(inv['root']);directories.update(str(Path(inv['root'])/e['relative']) for e in inv['entries'] if e['kind']=='directory')
 for p in directories:absolute(p)
 result={'schema':'orbit-poc-segmented-fit-read-allowlist-v2','manifest_hash':manifest['manifest_hash'],'source_plan':plan,'files':files,'directories':sorted(directories),'native_data_inventories':datadirs,'verified_safe_trees':safe,'denied_files':denies,'denied_tree_inventories':denied_inv,'writable':{'attempts':str(attempts),'temporary':str(temporary),'lock':pin(lock)},'known_attitude_scope':'Noiseless nadir attitude is intentionally derived from synthetic truth and allowed as a declared measurement input. Cartesian/clock/ambiguity truth files remain denied.','required_prelaunch_probes':['exact frozen public verify_manifest and require_passed succeed read-only','all denied canonical/resolved/known backing aliases fail open, including /proc/self/root and /proc/1/root','no inherited file descriptors above2 except expressly identified logs/control descriptors','no alternate unmasked root, host proc, host device filesystem or network access','complete emitted mount/file/symlink topology matches this allowlist; declared native data inventories remain identical'],'fit_execution_authorized':False,'scope':'Input-only namespace specification; no benchmark execution or scientific classification performed'}
 result['allowlist_hash']=canonical(result);return result

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();need(sha(a.plan)==a.sha256,'Plan changed');need(not a.output.exists(),'Output exists');v=build(json.loads(a.plan.read_text()));a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(v,sort_keys=True,indent=2)+'\n');print(json.dumps({'output':pin(a.output),'files':len(v['files']),'denied_files':len(v['denied_files']),'fit_execution_authorized':False}))
if __name__=='__main__':main()
