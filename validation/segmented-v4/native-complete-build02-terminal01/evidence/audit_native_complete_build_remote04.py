"""Read-only complete-build audit; no subprocesses, compilers, signals or fits."""
from pathlib import Path,PosixPath
import argparse,datetime,hashlib,importlib.util,json
ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--result-sha256',required=True);ap.add_argument('--pipeline-sha256',required=True);ap.add_argument('--verifier',required=True);ap.add_argument('--verifier-sha256',required=True);args=ap.parse_args()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb')as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def require(ok,message):
 if not ok:raise RuntimeError(message)
root=Path(args.root);require(root.is_absolute()and '..'not in root.parts,'Noncanonical build root')
resultpath=root/'run/build-result/result.json';pipelinepath=root/'control/pipeline.json'
if not resultpath.exists():resultpath=root/'run/build/result.json'
require(sha(resultpath)==args.result_sha256 and sha(pipelinepath)==args.pipeline_sha256,'Terminal pins changed')
build=json.loads(resultpath.read_bytes());pipeline=json.loads(pipelinepath.read_bytes());plan=json.loads(Path(build['plan']['path']).read_bytes());execution=json.loads(Path(plan['execution']['path']).read_bytes())
require(Path(plan['output'])/'result.json'==resultpath,'Build output path differs')
require(build['status']=='built_complete_candidate'and pipeline['returncode']==0 and pipeline['final_cleanup']['verified']is True and pipeline['final_cleanup']['errors']==[],'Actual complete build did not finish cleanly')
checked_files={}
require(set(plan['driver'])=={'path','sha256'}and plan['driver']['sha256']=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd'and sha(plan['driver']['path'])==plan['driver']['sha256'],'Unreviewed namespace alias resolver')
resolver_spec=importlib.util.spec_from_file_location('approved_owned_alias_resolver',plan['driver']['path']);resolver=importlib.util.module_from_spec(resolver_spec);resolver_spec.loader.exec_module(resolver)
original_host_path=resolver.host_path

def mapped_readonly(path,execution):
 path=Path(path)
 return any(path==Path(row['target'])or Path(row['target'])in path.parents for row in execution['read_only_bindings'])

def guarded_alias_host_path(path,execution):
 path=Path(path)
 if mapped_readonly(path,execution):return original_host_path(path,execution)
 if any(path==Path(row['source'])or Path(row['source'])in path.parents for row in execution['read_only_bindings']):return path
 raise RuntimeError('Unbound read-only alias target: '+str(path))

resolver.host_path=guarded_alias_host_path

def resolved(path):
 path=Path(path)
 if mapped_readonly(path,execution):return resolver.resolved_host_path(path,execution)
 return path

def checked(record):
 require(set(record)=={'path','sha256'},'Nonexact artifact pin')
 p=resolved(record['path']);require(p.is_file()and sha(p)==record['sha256'],'Changed artifact '+record['path']);checked_files[record['path']]=record['sha256'];return p
def load(record):return json.loads(checked(record).read_bytes())
checked(build['plan']);checked(plan['execution']);checked({'path':args.verifier,'sha256':args.verifier_sha256})
require(args.verifier_sha256=='23e8a0e54de29250a31aeb65f0bb2001614f0e70cd043d54469d9c0e6d5f6bfa','Wrong approved strict-v7 verifier')
spec=importlib.util.spec_from_file_location('approved_validation07_verifier',args.verifier);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
class MappedPath(PosixPath):
 """Retain canonical lexical paths; map only filesystem access through pinned RO bindings."""
 def open(self,*a,**kw):return Path(resolved(self)).open(*a,**kw)
 def stat(self,*a,**kw):return Path(resolved(self)).stat(*a,**kw)
v.Path=MappedPath
inputs=plan['inputs'];base=load(inputs['baseline_result']);delta=load(inputs['source_delta']);install=load(build['installation_equivalence']);request=load(inputs['installation_request']);inventory=load(request['repository_inventory']);repo=inventory['files']
receipt={'build_base_result':inputs['baseline_result'],'native_source_delta':inputs['source_delta'],'candidate_native_source_root':str(Path(execution['paths']['native_source'])/'candidate/source')}
for name in ('original_recipe_inventory','normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence'):receipt[name]=build[name]
receipt['installed_source_mapping']={r['relative']:str(Path(r['new_file']['path']).relative_to(inventory['root']))for r in delta['changes']}
documents={name:load(record)for name,record in receipt.items()if isinstance(record,dict)and set(record)=={'path','sha256'}}
require(inputs['baseline_result']['sha256']==v.BUILD_BASE_RESULT and base['native']['sha256']==v.BUILD_BASE_NATIVE,'Wrong original build lineage')
require(plan['phase']=='build'and build['source_before']==base['source_after'],'Wrong source baseline/phase')
preflight_audit=load(inputs['preflight_audit']);require(inputs['preflight_audit']['sha256']=='dce92a17c99639eb27033b000d539184716da6b4db6bcdc45706301ccf2638cf'and preflight_audit['passed']is True,'Unreviewed actual preflight')
preflight_result=load(inputs['preflight_result']);require(preflight_audit['preflight_result']==inputs['preflight_result']and preflight_result['status']=='prepared_complete_build','Preflight result binding differs')
for name in ('baseline_relink','installation_equivalence','supplemental_fixtures'):
 require(preflight_audit[name]==preflight_result[name]==build[name],'Preflight artifact binding differs: '+name)
v.verify_installed_delta(delta,inputs['baseline_result'],base['source_after'],build['source_after'],repo,receipt['installed_source_mapping'],checked)
require(build['candidate_source_sha256']==v.digest(build['source_after']),'Actual source digest differs')
v.verify_complete_build(build,receipt,documents,repo,checked)
def tree(path):
 out={}
 for p in sorted(Path(path).rglob('*')):
  require(not p.is_symlink(),'Source symlink '+str(p))
  if p.is_file():out[str(p.relative_to(path))]=sha(p)
 return out
require(tree(receipt['candidate_native_source_root'])==build['source_after'],'Actual compiled source tree changed')
base_root=Path(inputs['baseline_result']['path']).parents[2];require(tree(base_root/'native_source/source')==base['source_after'],'Preserved native source changed')
for name,h in repo.items():checked({'path':str(Path(inventory['root'])/name),'sha256':h})
# Reconstruct all external dependency paths from the actual compiler readback.
deps=load(inputs['dependency_inventory']);external={r['path']:r for r in deps['files']};require(len(external)==len(deps['files'])==420,'Original external dependency inventory differs')
require(deps['recipe_inventory']==inputs['recipe_inventory'],'External dependency recipe attribution differs')
actual_external=set()
for block in checked(build['candidate_dependencies']).read_text().strip().split('\n\n'):
 lines=block.splitlines();require(lines and ': #deps 'in lines[0]and lines[0].endswith('(VALID)'),'Invalid compiler dependency block')
 if lines[0].startswith('groops:'):continue
 rows=[x.strip()for x in lines[1:]if x.strip()];require(len(rows)==int(lines[0].split(': #deps ',1)[1].split(',',1)[0]),'Incomplete dependency block')
 for name in rows:
  p=Path(name);require(p.is_absolute(),'Relative compiler dependency')
  if not p.is_relative_to(receipt['candidate_native_source_root']):actual_external.add(name)
require(actual_external<=set(external),'Unpinned external compile dependency')
for name in actual_external:checked({'path':name,'sha256':external[name]['sha256']})
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();require(boot==pipeline['admission']['boot_id'],'Host rebooted since build')
identities={}
for identity in [pipeline['admission']['driver_identity']]+pipeline['cleanup']['identities']:identities[(identity['pid'],identity['start_ticks'])]=identity
absence=[]
for(pid,start),identity in identities.items():
 proc=Path('/proc')/str(pid)/'stat'
 if not proc.exists():absence.append({'pid':pid,'start_ticks':start,'absent':True,'live':False});continue
 raw=proc.read_text();words=raw[raw.rfind(')')+2:].split();actual_start=int(words[19]);state=words[0];require(actual_start!=start or state=='Z','Owned process remains live');absence.append({'pid':pid,'start_ticks':start,'actual_start_ticks':actual_start,'state':state,'live':False})
require(sha(resultpath)==args.result_sha256 and sha(pipelinepath)==args.pipeline_sha256,'Terminal changed during audit')
print(json.dumps({'schema':'orbit-poc-native-complete-build-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'actual_build_result':pin(resultpath),'pipeline':pin(pipelinepath),'plan':build['plan'],'execution':plan['execution'],'preflight_audit':inputs['preflight_audit'],'preflight_result':inputs['preflight_result'],'baseline_result':inputs['baseline_result'],'baseline_relink':build['baseline_relink'],'installation_equivalence':build['installation_equivalence'],'supplemental_fixtures':build['supplemental_fixtures'],'source_delta':inputs['source_delta'],'original_recipe_inventory':build['original_recipe_inventory'],'normalized_configuration':build['normalized_configuration'],'complete_compile_evidence':build['complete_compile_evidence'],'candidate_dependencies':build['candidate_dependencies'],'native':build['native'],'build_manifest':build['build_manifest'],'cmake_cache':build['cmake_cache'],'compiled_objects':611,'cpp_objects':591,'fortran_objects':20,'fortran_preprocessing':20,'complete_commands':633,'reused_objects':0,'original_external_dependency_files':420,'actual_external_dependency_files':len(actual_external),'full_source_files':len(build['source_after']),'candidate_source_sha256':build['candidate_source_sha256'],'owned_processes':absence,'boot_id':boot,'checked_artifact_count':len(checked_files),'verifier':{'path':args.verifier,'sha256':args.verifier_sha256},'filesystem_resolver':plan['driver'],'read_only_alias_symlinks_remapped':True,'scope':{'propagations':0,'fits':0,'scientific_gates':0,'release_ready':False}},indent=2,sort_keys=True))
