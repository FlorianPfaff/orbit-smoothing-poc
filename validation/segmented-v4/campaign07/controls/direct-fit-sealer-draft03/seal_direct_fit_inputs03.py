#!/usr/bin/env python3
"""Seal actual completed preparation into reviewed blind-namespace metadata.

No subprocess, namespace, estimator, or native executable is started. All new
files stay under one fresh metadata output directory. Existing scientific
inputs, manifests, outputs and controls are never changed.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import importlib.util
import json
import os
import posixpath

HELPERS={
 'allowlist':'96590e63316b2e385a2ea82e8ab78fc286a6da43552d8d603450604d64f61ab6',
 'planner':'d69f59841f4aefe91432de02f1422e41006bc618cb6d7a48b90be0482f0028f7',
 'probe':'92036c1c8bca62522dbad0069a1a5c63bb8e290aec439bbbfd9e3945d5d1719d',
 'wrapper':'85c961e0ac62f0e8b8a85e34930505776aa1027a1bbc51b2428d5be939cc692a',
 'inner':'24b12ce5c08ef5f8d821470736728202b993034bbc337b1191d320e32ea16af0',
 'state_checker':'4fcf8703fc985edd7d553649d825f31c850557953be205a1f22a8372cabff964',
}
KEYS={'schema','helper','preparation_plan','preparation_controller','execution','config',
 'validation_audit','system_support','helpers','taskset','bubblewrap','control',
 'temporary','attempts','known_flight_references','additional_denied_trees','output_root'}
OUTPUTS=('support-core.json','allowlist-core-plan.json','allowlist-core.json',
 'probe-spec.json','inner-plan.json','support-final.json','allowlist-plan.json',
 'allowlist.json','backing-map.json','mount-input.json','skeleton-request.json',
 'mount-plan.json','invocation.json','correspondence.json','result.json')

def need(ok,why):
 if not ok:raise ValueError(why)
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as stream:
  for data in iter(lambda:stream.read(1048576),b''):h.update(data)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def canonical(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def path(value):
 need(isinstance(value,str) and value.startswith('/') and posixpath.normpath(value)==value and '\0' not in value,'Noncanonical path')
 p=Path(value);need(str(p.resolve())==value,'Path contains a symlink ancestor');return p
def checked(p):
 need(isinstance(p,dict) and set(p)=={'path','sha256'},'Exact path/hash pin required')
 q=Path(p['path']);need(q.is_absolute() and q.is_file() and sha(q)==p['sha256'],'Pinned input changed');return q
def read(p):return json.loads(checked(p).read_bytes())
def identity(p):
 p=path(str(p));need(p.is_dir() and not p.is_symlink(),'Canonical directory required');s=p.stat();return {'path':str(p),'device':s.st_dev,'inode':s.st_ino}
def disjoint(a,b):return a!=b and a not in b.parents and b not in a.parents
def write(p,value):
 with Path(p).open('x') as stream:json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')
 return pin(p)
def module(name,p):
 s=importlib.util.spec_from_file_location(name,checked(p));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def context(p):
 """Require the real terminal28/68 artifacts before producing any plan/output."""
 need(set(p)==KEYS and p['schema']=='orbit-poc-direct-fit-sealing-request-v1','Unknown sealing request')
 need(p['helper']==pin(Path(__file__).resolve()),'Sealer identity differs')
 need(set(p['helpers'])==set(HELPERS),'Exact reviewed helper set required')
 for key,digest in HELPERS.items():
  checked(p['helpers'][key]);need(p['helpers'][key]['sha256']==digest,'Unreviewed builder/helper: '+key)
 for k in ('taskset','bubblewrap'):checked(p[k])
 need(p['taskset']['path']=='/usr/bin/taskset' and p['bubblewrap']['path']=='/usr/bin/bwrap','Exact system commands required')
 pp=read(p['preparation_plan']);cp=read(p['preparation_controller']);e=read(p['execution']);cfg=read(p['config']);audit=read(p['validation_audit'])
 need(pp['schema']=='orbit-poc-segmented-preparation-owned-plan-v1' and pp['execution']==p['execution'] and pp['config']==p['config'] and pp['validation_audit']==p['validation_audit'],'Preparation plan identity differs')
 need(cp['schema']=='orbit-poc-segmented-preparation-owned-run-v1' and cp['status']=='prepared' and cp['benchmark_attempts']==0 and cp['final_cleanup']['verified'] is True and cp['final_cleanup']['errors']==[],'Preparation not complete and clean')
 need({k:cp['plan'][k] for k in ('path','sha256')}==p['preparation_plan'],'Preparation controller references another plan')
 need([x['phase'] for x in cp['checks']]==['before','after'] and all(x['status']=='complete' and x['returncode']==0 for x in cp['checks']) and cp['preparation']['status']=='complete' and cp['preparation']['returncode']==0,'Preparation checks/execution incomplete')
 after=read(cp['checks'][1]['result'])
 need(after['schema']=='orbit-poc-segmented-preparation-state-check-v1' and after['phase']=='after' and after['status']=='passed' and after['config']==p['config'],'After-check identity differs')
 need(all(after['prepared'][k]==v for k,v in {'cases':28,'attempts':68,'benchmark_fit_count':0}.items()),'Actual28case/68attempt preparation is required')
 need(audit['schema']=='orbit-poc-segmented-validation-terminal-independent-review-v1' and audit['consistency_passed'] is True and audit['scientific_status']=='passed_scoped_checks' and audit['cleanup_verified'] is True,'Validation audit not a scoped clean pass')
 need(after['source_sha256']==cfg['segmented_runtime']['source_sha256']==cfg['dense_runtime']['source_sha256']==audit['identity']['comparison_source_sha256'],'Source identity differs')
 need(after['validation']['status']=='passed' and {k:after['validation']['pipeline'][k] for k in ('path','sha256')}==pp['pipeline'],'Validation pipeline differs')
 need(cfg['resources']['reserved_cpu_ids']==[24] and cfg['resources']['threads']==1 and cfg['resources']['maximum_process_tree_rss_bytes']==8589934592 and e['fit_cpu']==24,'Frozen numerical resources differ')
 run=path(e['paths']['run']);need(cfg['output_dir']==str(run),'Direct run path differs')
 mp=after['prepared']['manifest'];need(mp['path']==str(run/'manifest.json'),'Manifest is outside actual preparation')
 manifest=read(mp);need(manifest['manifest_hash']==canonical({k:v for k,v in manifest.items() if k!='manifest_hash'}),'Actual manifest hash differs')
 for name in ('dense','segmented'):
  rt=manifest['runtimes'][name];configured=cfg[name+'_runtime']
  need(rt['source_root']==configured['source_root'] and rt['source_sha256']==configured['source_sha256'] and
       all(rt[key][field]==configured[key][field] for key in ('python','native') for field in ('path','sha256')),
       'Actual manifest runtime differs from frozen config: '+name)
 need(len(manifest['cases'])==28 and len(manifest['attempts'])==68 and len({x['case_id'] for x in manifest['cases']})==28 and len({x['attempt_id'] for x in manifest['attempts']})==68,'Actual manifest inventory incomplete')
 status_pin=pin(run/'preparation-status.json');status=read(status_pin)
 need(status['status']=='prepared' and status['manifest_hash']==manifest['manifest_hash'],'Public preparation status differs')
 catalog=read({k:manifest['prepared_input_catalog'][k] for k in ('path','sha256')})
 need(catalog['schema']=='orbit-poc-segmented-input-catalog-v1' and {x['case_id'] for x in catalog['entries']}=={x['case_id'] for x in manifest['cases']} and len(catalog['entries'])==28,'Actual prepared catalog differs')
 for key in ('control','temporary','attempts'):need(p[key]==identity(p[key]['path']),'Directory identity changed: '+key)
 control=path(p['control']['path']);temporary=path(p['temporary']['path']);attempts=path(p['attempts']['path']);out=path(p['output_root'])
 need(attempts==run/'attempts' and path(e['paths']['temporary']) in temporary.parents,'Writable fit directory is not an exact direct path')
 need(not any(attempts.iterdir()) and not any(temporary.iterdir()),'Fit directories must be fresh and empty')
 lock=run/'.segmented.lock';need(lock.is_file() and not lock.is_symlink() and lock.stat().st_size==0,'Exact empty statistical lock required')
 need(out.parent==control and not out.exists() and not out.is_symlink(),'Use one fresh output child of sealing control')
 protected=[run,path(e['paths']['source']),path(e['paths']['root']),path(pp['control_root']),temporary]
 need(all(disjoint(control,q) for q in protected),'Sealing control overlaps preparation/evidence/runtime')
 for row in e['read_only_bindings']:
  need(all(disjoint(control,Path(row[k])) and disjoint(control,Path(row[k]).resolve()) for k in ('source','target')),'Sealing control overlaps frozen alias')
 system=read(p['system_support']);need(system.get('schema')=='orbit-poc-segmented-system-support-files-v1' and system.get('files'),'Exact reviewed system-support inventory required')
 # Known reference aliases may exist only inside the frozen readonly view.
 # Resolve them through the exact original owned driver, including its symlink
 # checks, rather than reading a missing or unrelated canonical host path.
 reference_backings=[]
 if p['known_flight_references']:
  need(pp['driver']['sha256']=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd','Unreviewed reference backing resolver')
  resolver=module('reviewed_reference_backing_resolver',pp['driver'])
  refs={ref['path']:ref for ref in p['known_flight_references']}
  need(len(refs)==len(p['known_flight_references']),'Duplicate reference path')
  for ref in p['known_flight_references']:
   name=ref['path'];need(isinstance(name,str) and name.startswith('/') and posixpath.normpath(name)==name,'Noncanonical reference alias')
   backing=resolver.resolved_host_path(name,e);checked({'path':str(backing),'sha256':ref['sha256']})
   need(str(backing) in refs and refs[str(backing)]['sha256']==ref['sha256'],'Both canonical and physical reference pins are required')
   for binding in e['read_only_bindings']:
    source=Path(binding['source']).resolve()
    if source==backing or source in backing.parents:
     alias=str(Path(binding['target'])/backing.relative_to(source))
     if resolver.resolved_host_path(alias,e)==backing:
      need(alias in refs and refs[alias]['sha256']==ref['sha256'],'Every declared canonical reference alias must be pinned')
   st=backing.stat();reference_backings.append({'canonical':name,'backing':str(backing),'sha256':ref['sha256'],'bytes':st.st_size,'device':st.st_dev,'inode':st.st_ino})
 need(isinstance(p['additional_denied_trees'],list) and len(set(p['additional_denied_trees']))==len(p['additional_denied_trees']),'Duplicate denied roots')
 for q in p['additional_denied_trees']:need(path(q).is_dir(),'Missing denied tree')
 return {'manifest':manifest,'manifest_pin':mp,'status_pin':status_pin,'config':cfg,'execution':e,'after':after,'system_support':system,'known_reference_backings':reference_backings}

def make_plan(request):
 c=context(request);out=Path(request['output_root'])
 trees=set()
 for rt in c['manifest']['runtimes'].values():trees.update({('source',rt['source_root']),('python_runtime',str(Path(rt['python']['path']).parent.parent)),('native_runtime',str(Path(rt['libraries']['directory']).parent))})
 names=(*OUTPUTS,*('safe-tree-%02d.json'%i for i in range(len(trees))),'run-skeleton','failure.json')
 return {'schema':'orbit-poc-direct-fit-sealing-plan-v1','request':request,
  'manifest':c['manifest_pin'],'preparation_status':c['status_pin'],
  'manifest_hash':c['manifest']['manifest_hash'],
  'planned_outputs':{name:str(out/name) for name in names},
  'native_executions':0,'fit_execution_authorized':False}

def link_inventory(allow):
 """Record actual parent/file symlinks, including canonical libc aliases."""
 links={}
 requested={r['path'] for r in allow['files']}|set(allow['directories'])
 for row in allow['files']:
  for p in [Path(row['path']),*Path(row['path']).parents]:
   if p.is_symlink():links[str(p)]=os.readlink(p)
 for tree in allow['verified_safe_trees']:
  inv=json.loads(Path(tree['inventory']['path']).read_text())
  for r in inv['entries']:
   if r['link_target'] is not None:links[inv['root']+'/'+r['relative']]=r['link_target']
 for inv in allow['native_data_inventories']:
  for r in inv['entries']:
   if r['link_target'] is not None:links[inv['root']+'/'+r['relative']]=r['link_target']
 return [{'path':name,'target':target} for name,target in sorted(links.items())]

def backing(name,links,execution,planner):
 matches=[]
 for i,r in enumerate(execution['read_only_bindings']):
  target=planner.links_resolve(r['target'],links)
  if planner.within(name,target):matches.append((len(PurePosixPath(target).parts),i,r['source']+name[len(target):]))
 return str(Path(max(matches)[2] if matches else name).resolve())

def probe_spec(p,c,allow,new_paths,probe):
 links={r['path']:r['target'] for r in link_inventory(allow)};denied=set()
 for row in allow['denied_files']:
  for name in (row['path'],row['resolved']):
   denied.add(name);resolved=probe.link_resolve(name,links);denied.add(resolved)
   for binding in c['execution']['read_only_bindings']:
    target=probe.link_resolve(binding['target'],links)
    if probe.within(resolved,target):
     back=posixpath.normpath(binding['source']+resolved[len(target):]);denied.add(back);denied.add(str(Path(back).resolve()))
 roots={r['root'] for r in allow['verified_safe_trees']}
 readonly=roots|{allow['source_plan']['run_root']}|set(new_paths)
 readonly.update(r['resolved'] for r in allow['files'] if not any(probe.within(r['resolved'],root) for root in roots))
 source=c['config']['segmented_runtime']['source_root']
 spec={'schema':probe.SCHEMA,'config':p['config'],'run_root':allow['source_plan']['run_root'],
  'source_root':source,'public_api_files':{name:pin(Path(source)/'src/orbit_poc/segmented'/name) for name in probe.API_NAMES},
  'manifest_hash':allow['manifest_hash'],'source_sha256':c['after']['source_sha256'],
  'host_namespaces':{key:os.readlink('/proc/self/ns/'+key) for key in ('pid','net')},
  'denied_paths':sorted(denied),'protected_readonly_targets':sorted(readonly),
  'writable':{**{k:allow['writable'][k] for k in ('attempts','temporary')},'lock':allow['writable']['lock']['path']}}
 return probe.validate_spec(spec)

def seal(plan):
 need(set(plan)=={'schema','request','manifest','preparation_status','manifest_hash','planned_outputs','native_executions','fit_execution_authorized'} and plan['schema']=='orbit-poc-direct-fit-sealing-plan-v1','Unknown sealing plan')
 p=plan['request'];need(make_plan(p)==plan,'Sealing inputs or output specification changed');c=context(p)
 out=Path(p['output_root']);out.mkdir();artifacts={}
 def save(name,value):
  q=write(out/name,value);artifacts[name]=q;return q
 try:
  a=module('reviewed_allowlist',p['helpers']['allowlist']);m=module('reviewed_mount_planner',p['helpers']['planner']);probe=module('reviewed_probe',p['helpers']['probe']);wrapper=module('reviewed_wrapper',p['helpers']['wrapper'])
  support=a.collect_support(p['config'],c['execution']['paths']['run'],c['system_support'])
  files={r['path']:r for r in support['files']}
  for q in [p['taskset'],*[p['helpers'][k] for k in ('probe','inner','state_checker')]]:
   r=a.pin(q['path']);need(r['sha256']==q['sha256'],'Inner helper changed');files[r['path']]=r
  support['files']=[files[k] for k in sorted(files)];sp=save('support-core.json',support)
  trees=set()
  for rt in c['manifest']['runtimes'].values():trees.update({('source',rt['source_root']),('python_runtime',str(Path(rt['python']['path']).parent.parent)),('native_runtime',str(Path(rt['libraries']['directory']).parent))})
  inventories=[]
  for index,(kind,root) in enumerate(sorted(trees)):
   ip=save('safe-tree-%02d.json'%index,a.inventory(root));inventories.append({'kind':kind,'inventory':ip})
  ap={'schema':a.SCHEMA,'run_root':c['execution']['paths']['run'],'manifest':plan['manifest'],
   'preparation_status':plan['preparation_status'],'validation_audit':p['validation_audit'],'support_inventory':sp,
   'safe_trees':inventories,'denied_trees':sorted(set([c['execution']['paths']['run']+'/preparation/generation',*p['additional_denied_trees']])),
   'known_flight_references':p['known_flight_references'],'temporary_root':p['temporary']['path']}
  save('allowlist-core-plan.json',ap);core=a.build(ap);save('allowlist-core.json',core)
  spec=probe_spec(p,c,core,[str(out/'probe-spec.json'),str(out/'inner-plan.json')],probe);spec_pin=save('probe-spec.json',spec)
  inner={'schema':'orbit-poc-segmented-blind-inner-campaign-v1','helper':p['helpers']['inner'],'config':p['config'],
   'probe_helper':p['helpers']['probe'],'probe_spec':spec_pin,'state_checker':p['helpers']['state_checker']}
  inner_pin=save('inner-plan.json',inner)
  support['files']+= [a.pin(spec_pin['path']),a.pin(inner_pin['path'])];support['files'].sort(key=lambda r:r['path'])
  ap['support_inventory']=save('support-final.json',support);save('allowlist-plan.json',ap)
  allow=a.build(ap);allow_pin=save('allowlist.json',allow)
  links_list=link_inventory(allow);links={r['path']:r['target'] for r in links_list}
  mapping={'schema':m.MAP_SCHEMA,'allowlist_sha256':allow_pin['sha256'],'execution':m.host_pin(p['execution']['path']),
   'canonical_symlinks':links_list,
   'files':[{'canonical':name,'backing':m.host_pin(backing(name,links,c['execution'],m))} for name in sorted({r['resolved'] for r in allow['files']})],
   'inventories':[{'canonical':r['inventory']['path'],'backing':m.host_pin(backing(m.links_resolve(r['inventory']['path'],links),links,c['execution'],m))} for r in allow['verified_safe_trees']],
   'safe_trees':[{'canonical':r['root'],'backing':identity(backing(r['root'],links,c['execution'],m))} for r in allow['verified_safe_trees']],
   'writable':{'attempts':p['attempts'],'temporary':p['temporary'],'lock':m.host_pin(allow['writable']['lock']['path'])}}
  skeleton=out/'run-skeleton';skeleton.mkdir();mapping['run_skeleton']=identity(skeleton)
  mapping_pin=save('backing-map.json',mapping)
  mi={'schema':m.SCHEMA,'allowlist':m.host_pin(allow_pin['path']),'mapping':m.host_pin(mapping_pin['path'])};save('mount-input.json',mi)
  sr=m.skeleton_spec(mi);save('skeleton-request.json',sr)
  for row in sorted(sr['skeleton']['entries'],key=lambda r:(len(Path(r['relative']).parts),r['relative'])):
   target=skeleton/row['relative'];target.parent.mkdir(parents=True,exist_ok=True)
   if row['kind']=='directory':target.mkdir(exist_ok=True)
   elif row['kind']=='symlink':target.symlink_to(row['link_target'])
   else:target.touch(exist_ok=False)
  mount=m.build(mi);mount_pin=save('mount-plan.json',mount)
  correspondence=probe.verify_spec_correspondence(spec,mount,allow,mapping)
  invocation={'schema':'orbit-poc-segmented-fit-namespace-invocation-v1','wrapper':p['helpers']['wrapper'],'fresh_planner':p['helpers']['planner'],
   'resume_planner':None,'mount_plan':mount_pin,'bubblewrap':p['bubblewrap'],'config':p['config'],
   'python':c['config']['segmented_runtime']['python'],'taskset':p['taskset'],'inner_helper':p['helpers']['inner'],
   'inner_plan':inner_pin,'probe_helper':p['helpers']['probe'],'probe_spec':spec_pin}
  prepared=wrapper.prepare(invocation,m,None,probe)
  need(prepared['prefix']==0 and prepared['command'][1:3]==['-c','24'],'Fresh numerical namespace CPU/prefix differs')
  save('invocation.json',invocation);save('correspondence.json',correspondence)
  # Recheck original immutable input pins after potentially lengthy inventories.
  for q in [p[k] for k in ('preparation_plan','preparation_controller','execution','config','validation_audit','system_support')]+[plan['manifest'],plan['preparation_status']]:checked(q)
  result={'schema':'orbit-poc-direct-fit-sealing-result-v1','status':'sealed_metadata','manifest':plan['manifest'],
   'manifest_hash':plan['manifest_hash'],'artifacts':artifacts,'files':len(allow['files']),'denied_files':len(allow['denied_files']),
   'conditional_host_correspondence':correspondence,'known_reference_backings':c['known_reference_backings'],'native_executions':0,'fit_attempts':0,'fit_execution_authorized':False,
   'required_next':'Independent artifact review and actual unchanged empty-root positive/denial probes under owned admission before fit launch.'}
  save('result.json',result);return result
 except BaseException as error:
  write(out/'failure.json',{'schema':'orbit-poc-direct-fit-sealing-failure-v1','status':'failed','error':repr(error),'artifacts':artifacts,
   'native_executions':0,'fit_attempts':0,'prior_outputs_preserved':True});raise

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--plan',required=True);parser.add_argument('--sha256',required=True);args=parser.parse_args()
 result=seal(read({'path':args.plan,'sha256':args.sha256}));print(json.dumps({k:result[k] for k in ('status','manifest_hash','files','denied_files','native_executions','fit_attempts','fit_execution_authorized')}))
if __name__=='__main__':main()
