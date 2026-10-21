"""Read-only actual preflight audit. Never compiles, signals or launches processes."""
from pathlib import Path
import argparse,datetime,hashlib,importlib.util,json,os
from fractions import Fraction
ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);ap.add_argument('--result-sha256',required=True);ap.add_argument('--pipeline-sha256',required=True);ap.add_argument('--verifier',required=True);ap.add_argument('--verifier-sha256',required=True);args=ap.parse_args()
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb')as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()
def pin(path):return {'path':str(path),'sha256':sha(path)}
def require(ok,message):
 if not ok:raise RuntimeError(message)
root=Path(args.root);require(root.is_absolute()and '..'not in root.parts,'Noncanonical preflight root')
resultpath=root/'run/preflight/result.json';pipelinepath=root/'control/pipeline.json'
require(sha(resultpath)==args.result_sha256 and sha(pipelinepath)==args.pipeline_sha256,'Terminal pins changed')
result=json.loads(resultpath.read_bytes());pipeline=json.loads(pipelinepath.read_bytes());plan=json.loads(Path(result['plan']['path']).read_bytes());execution=json.loads(Path(plan['execution']['path']).read_bytes())
require(result['status']=='prepared_complete_build'and result['schema']=='orbit-poc-native-complete-build-v1','Preflight not successful')
require(pipeline['returncode']==0 and pipeline['final_cleanup']['verified']is True and pipeline['final_cleanup']['errors']==[],'Controller not cleanly successful')
require(plan['phase']=='prepare'and result['inputs']==plan['inputs'],'Preflight inputs/phase differ')
require(all(result[k]==0 for k in ('compiled_object_count','preprocessing_count','reused_object_count','fit_attempts'))and result['release_evidence']is False,'Unexpected preflight scope')
checked_files={}
def resolved(path):
 path=Path(path)
 for row in sorted(execution['read_only_bindings'],key=lambda r:-len(r['target'])):
  target=Path(row['target'])
  if path==target or target in path.parents:return Path(row['source'])/path.relative_to(target)
 return path
def checked(record):
 require(set(record)=={'path','sha256'},'Nonexact artifact pin')
 path=resolved(record['path']);require(path.is_file()and sha(path)==record['sha256'],'Changed artifact '+record['path']);checked_files[record['path']]=record['sha256']
 return path
def load(record):return json.loads(checked(record).read_bytes())
checked(result['plan']);checked(plan['execution']);checked({'path':args.verifier,'sha256':args.verifier_sha256})
spec=importlib.util.spec_from_file_location('approved_validation07_verifier',args.verifier);v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
base=load(plan['inputs']['baseline_result']);delta=load(plan['inputs']['source_delta']);relink=load(result['baseline_relink']);install=load(result['installation_equivalence']);request=load(plan['inputs']['installation_request']);inventory=load(request['repository_inventory']);repo=inventory['files']
receipt={'build_base_result':plan['inputs']['baseline_result'],'native_source_delta':plan['inputs']['source_delta']}
require(receipt['build_base_result']['sha256']==v.BUILD_BASE_RESULT and base['native']['sha256']==v.BUILD_BASE_NATIVE,'Wrong build baseline')
require(result['source_before']==base['source_after'],'Baseline source inventory differs')
v.verify_baseline_relink(relink,receipt,base,checked)
v.verify_installation(install,receipt,result,repo,checked)
require(install['request']==plan['inputs']['installation_request']and {k:install['helper'][k]for k in ('path','sha256')}==plan['inputs']['installation_helper'],'Installer actual input/helper differs')
expected=dict(base['source_after']);changes=delta['changes'];require(len(changes)==7 and len({x['relative']for x in changes})==7,'Wrong native overlay count')
counts={'add':0,'replace':0}
for row in changes:
 counts[row['action']]+=1;path=checked(row['new_file']);name=v.relative(row['relative'])
 if row['action']=='replace':require(expected[name]==row['old_sha256'],'Wrong replaced source')
 else:require(name not in expected and row['old_sha256']is None,'Wrong added source')
 rel=str(Path(row['new_file']['path']).relative_to(inventory['root']));require(repo[rel]==row['new_file']['sha256'],'Overlay not frozen repository payload')
 expected[name]=row['new_file']['sha256']
require(counts=={'add':3,'replace':4}and expected==result['source_after'],'Complete source delta differs')
def tree(path):
 out={}
 for p in sorted(Path(path).rglob('*')):
  require(not p.is_symlink(),'Source symlink '+str(p))
  if p.is_file():out[str(p.relative_to(path))]=sha(p)
 return out
installed_root=Path(install['installed_checkout'])/'source';require(tree(installed_root)==expected,'Actual full installed tree differs')
base_root=Path(plan['inputs']['baseline_result']['path']).parents[2];require(tree(base_root/'native_source/source')==base['source_after'],'Original native source changed')
for name,h in repo.items():checked({'path':str(Path(inventory['root'])/name),'sha256':h})
fixture_inventory=load(plan['inputs']['fixture_inventory']);fixtures=load(result['supplemental_fixtures']);tool=load(plan['inputs']['toolchain'])
require(set(fixtures)=={'interpolation','serializer','roundtrip'}and set(fixture_inventory)=={'schema','interpolation','serializer','decoder'},'Wrong supplemental fixture inventory')
labels=['baseline-link','installer-equivalence','fixture-interpolation-compile','fixture-interpolation','fixture-serializer-compile','fixture-serializer']
require([x['label']for x in result['stages']]==labels,'Supplemental stage sequence differs')
for stage in result['stages']:
 require(stage['returncode']==0,'Preflight command failed');checked(stage['stdout']);checked(stage['stderr'])
require(result['stages'][0]==relink['stage'],'Baseline stage record differs')
require(result['stages'][1]['argv']==[tool['python']['path'],plan['inputs']['installation_helper']['path'],'--request',plan['inputs']['installation_request']['path'],'--sha256',plan['inputs']['installation_request']['sha256']],'Actual installer invocation differs')
inc=Path(inventory['root'])/'groops/extension'
for index,name in ((2,'interpolation'),(4,'serializer')):
 checked(fixture_inventory[name]);checked(fixtures[name]['binary']);binary=str(root/'run/preflight'/('fixture-'+name))
 require(fixtures[name]['binary']['path']==binary,'Supplemental binary path differs')
 require(result['stages'][index]['argv']==[tool['cxx']['path'],'-O3','-DNDEBUG','-std=gnu++17','-I'+str(inc/'wide_tangent/proposed/misc/orbitPoc'),'-I'+str(inc),fixture_inventory[name]['path'],'-o',binary],'Supplemental compilation changed')
 stage=result['stages'][index+1];require(stage['argv']==[binary]and Path(stage['stdout']['path']).read_text()==fixtures[name]['stdout'],'Supplemental execution attribution differs')
require(fixtures['interpolation']['stdout']=='','Unexpected interpolation fixture stdout')
checked(fixture_inventory['decoder']);decoderpath=checked(fixture_inventory['decoder']);spec=importlib.util.spec_from_file_location('actual_typed_decoder',decoderpath);decoder=importlib.util.module_from_spec(spec)
import sys
sys.modules[spec.name]=decoder;spec.loader.exec_module(decoder)
rows=[json.loads(x)for x in fixtures['serializer']['stdout'].splitlines()if x.strip()];require(len(rows)==2,'Wrong serializer record count')
exact,anchored=[decoder.decode_stencil(x,decoder.V2,5)for x in rows]
require(exact.mode=='exact'and exact.indices==(3,)and exact.coefficients()==((3,Fraction(1)),),'Exact stencil roundtrip differs')
require(anchored.mode=='anchored_twofold'and anchored.indices==(4,1)and anchored.anchor==1 and anchored.high==(Fraction(1,2),Fraction(1,2))and anchored.low==(Fraction(1,2**70),Fraction(0)),'Anchored stencil representation differs')
require(anchored.evaluate(list(map(Fraction,range(5))))==Fraction(5,2)+Fraction(3,2**70),'Exact dyadic roundtrip differs')
require(fixtures['roundtrip']['passed']is True and fixtures['roundtrip']['records']==rows and fixtures['roundtrip']['decoder']==fixture_inventory['decoder'],'Recorded roundtrip differs')
require(not any(Path(execution['paths']['build']).iterdir())and not any(Path(execution['paths']['binaries']).iterdir()),'Candidate build outputs present during preflight')
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();require(boot==pipeline['admission']['boot_id'],'Host rebooted since actual preflight')
identities={}
for identity in [pipeline['admission']['driver_identity']]+pipeline['cleanup']['identities']:identities[(identity['pid'],identity['start_ticks'])]=identity
absence=[]
for(pid,start),identity in identities.items():
 proc=Path('/proc')/str(pid)/'stat'
 if not proc.exists():absence.append({'pid':pid,'start_ticks':start,'absent':True,'live':False});continue
 raw=proc.read_text();words=raw[raw.rfind(')')+2:].split();actual_start=int(words[19]);state=words[0];live=actual_start==start and state!='Z';require(not live,'Owned process remains live')
 absence.append({'pid':pid,'start_ticks':start,'actual_start_ticks':actual_start,'state':state,'live':False})
require(sha(resultpath)==args.result_sha256 and sha(pipelinepath)==args.pipeline_sha256,'Terminal changed during audit')
output={'schema':'orbit-poc-native-complete-preflight-independent-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'preflight_result':pin(resultpath),'pipeline':pin(pipelinepath),'baseline_relink':result['baseline_relink'],'installation_equivalence':result['installation_equivalence'],'supplemental_fixtures':result['supplemental_fixtures'],'plan':result['plan'],'execution':plan['execution'],'verifier':{'path':args.verifier,'sha256':args.verifier_sha256},'source':{'original_files':len(base['source_after']),'installed_files':len(expected),'installed_sha256':v.digest(expected),'repository_files':len(repo),'additions':3,'replacements':4,'full_actual_tree_hashed':True,'original_preserved':True},'baseline':{'native_sha256':v.BUILD_BASE_NATIVE,'copied_objects_hashed':611,'original_objects_hashed':611,'distinct_inodes':True,'executable_rehashed':True},'supplemental':{'interpolation':True,'serializer':True,'exact_fraction_roundtrip':True,'flags':['-O3','-DNDEBUG','-std=gnu++17']},'owned_processes':absence,'boot_id':boot,'checked_artifact_count':len(checked_files),'scope':{'candidate_groops_objects_compiled':0,'propagations':0,'fits':0,'scientific_gates':0,'release_ready':False}}
print(json.dumps(output,indent=2,sort_keys=True))
