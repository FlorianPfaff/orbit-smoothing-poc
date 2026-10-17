#!/usr/bin/env python3
"""Two explicit phases: prepare/freeze external RHS diagnostics, then 54 calls."""
from pathlib import Path
from decimal import Decimal
import argparse,hashlib,json,math,os,shutil,struct,subprocess,sys,time
SCHEMA='orbit-poc-tangent-rhs-family-plan-v1'
PROFILES={'baseline','wide'}
ANCHORS={'historical_large':'b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2','current_small':'f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044','current_large':'b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3'}
SOURCE_FILES={'include/eventQuadrature.h','include/syntheticForceDerivatives.h','include/sixStateTangent.h','include/wideSixStateTangent.h','replay.cpp','test_wide.cpp','test_reader.py','generate_family.py','test_family.py'}
TOLERANCE=2e-12
INPUTS={'prepare':{'source_bundle',*('anchor_'+a for a in ANCHORS)},'run':{'source_bundle','family_manifest','preflight_plan','preflight_result','family_audit'}}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def check(value):
 if set(value)!={'path','sha256'}:raise ValueError('Exact file pin required')
 p=Path(value['path'])
 if not p.is_absolute()or '..'in p.parts or not p.is_file()or p.is_symlink()or sha(p)!=value['sha256']:raise ValueError('Pinned regular file differs')
 return p
def save(p,value):
 with Path(p).open('w')as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def validate_plan(p):
 if set(p)!={'schema','phase','execution','driver','worker','controller','native','source_freeze','inputs','output','global_lock'}or p['schema']!=SCHEMA or p['phase']not in INPUTS or set(p['inputs'])!=INPUTS[p['phase']]:raise ValueError('Unknown family diagnostic plan')
 for k in('output','global_lock'):
  q=Path(p[k])
  if not q.is_absolute()or '..'in q.parts:raise ValueError('Absolute canonical path required')
def validate_source_bundle(bundle):
 if set(bundle)!={'schema','source_manifest','files'}or bundle['schema']!='orbit-poc-tangent-rhs-source-bundle-v1'or set(bundle['files'])!=SOURCE_FILES:raise ValueError('Unknown source bundle')
 manifest=json.loads(check(bundle['source_manifest']).read_text())
 if manifest['schema']!='orbit-poc-external-wide-candidate-v1'or manifest['original_tolerance']!=TOLERANCE or manifest['maximum_iterations']!=120 or manifest['restart']!=20:raise ValueError('Source protocol changed')
 rows=manifest['source_files']
 if len(rows)!=9 or {r['path']for r in rows}!=SOURCE_FILES:raise ValueError('Exact nine-file manifest required')
 for r in rows:
  p=check(bundle['files'][r['path']])
  if sha(p)!=r['sha256']or p.stat().st_size!=r['bytes']:raise ValueError('Source manifest binding differs')
 return manifest
def capture_metadata(p):
 with Path(p).open('rb')as f:header=f.read(72)
 if len(header)!=72 or header[:16]!=b'OPCTANGENT001\n\0\0':raise ValueError('Invalid captured-system header')
 schema,n,intervals,terms,rhscount=struct.unpack_from('<5Q',header,16);dt,duration=struct.unpack_from('<2d',header,56)
 if schema!=1 or intervals!=n-1 or rhscount!=6*n or n<2 or not all(math.isfinite(x)and x>0 for x in(dt,duration)):raise ValueError('Invalid captured-system dimensions')
 return {'epochs':n,'dt':dt,'duration':duration}
def validate_family(manifest):
 if manifest.get('schema_version')!=1 or manifest.get('kind')!='bounded-captured-tangent-rhs-sensitivity'or manifest.get('case_count')!=27 or manifest.get('attempt_count')!=54:raise ValueError('Unknown RHS family schema')
 acceptance=manifest.get('acceptance',{})
 if acceptance.get('relative_residual')!=TOLERANCE or acceptance.get('maximum_iterations')!=120 or acceptance.get('restart')!=20:raise ValueError('Family criteria changed')
 anchors=manifest.get('anchors');cases=manifest.get('cases');order=manifest.get('execution_order')
 if not isinstance(anchors,list)or len(anchors)!=3 or not isinstance(cases,list)or len(cases)!=27 or not isinstance(order,list)or len(order)!=54:raise ValueError('Exact three-anchor/27-case/54-call family required')
 if {a['id']:a['sha256']for a in anchors}!=ANCHORS:raise ValueError('Exact original anchor identities required')
 ids=[x['id']for x in cases]
 if len(set(ids))!=27 or any(not isinstance(x,str)or not x or '/'in x or '..'in x for x in ids):raise ValueError('Invalid family case identities')
 variants={(None,0,0.)}|{(d,s,z)for d in('smooth','alternating')for s in(-1,1)for z in(1e-12,1e-9)}
 for a in ANCHORS:
  group=[c for c in cases if c['anchor']==a]
  if len(group)!=9 or {(c['direction'],c['sign'],c['relative_scale'])for c in group}!=variants:raise ValueError('Exact original and eight prescribed perturbations required')
 for a in anchors:
  p=check({'path':a['path'],'sha256':a['sha256']})
  if capture_metadata(p)!={k:a[k]for k in('epochs','dt','duration')}:raise ValueError('Anchor dimensions differ')
 for c in cases:
  if c['anchor']not in ANCHORS:raise ValueError('Unknown anchor')
  p=check({'path':c['path'],'sha256':c['sha256']})
  if p.stat().st_size!=c['bytes']:raise ValueError('Frozen case size differs')
  if c['direction']is None and c['sha256']!=ANCHORS[c['anchor']]:raise ValueError('Original case bytes differ')
  if c['direction']is not None and (c['changed_entries']<=0 or not math.isfinite(c['actual_relative_balanced_norm'])or abs(c['actual_relative_balanced_norm']/c['relative_scale']-1)>.01):raise ValueError('Perturbation magnitude differs')
 expected=[]
 for i,c in enumerate(cases):
  for mode in(('baseline','wide')if i%2==0 else('wide','baseline')):
   expected.append({'attempt_id':f"{len(expected)+1:02d}-{c['id']}-{mode}",'case_id':c['id'],'profile':mode})
 if order!=expected:raise ValueError('Balanced frozen execution order differs')
 return {x['id']:x for x in cases},order

def parse_trace(path,returncode,profile,metadata):
 def reject(value):raise ValueError('Non-finite JSON diagnostic '+value)
 lines=Path(path).read_text().splitlines();rows=[json.loads(x,parse_constant=reject)for x in lines]
 if not rows or rows[0].get('kind')!='input'or rows[-1].get('kind')!='terminal'or sum(r.get('kind')=='input'for r in rows)!=1 or sum(r.get('kind')=='terminal'for r in rows)!=1:raise ValueError('Reader lacks unique input/terminal attribution')
 first=rows[0];last=rows[-1]
 if any(first.get(k)!=v for k,v in {'profile':profile,**metadata,'tolerance':TOLERANCE,'maximum_iterations':120,'restart':20,'extended_digits':64}.items()):raise ValueError('Reader input/protocol differs')
 if returncode not in(0,1)or last.get('kernel_status')not in('passed','failed')or type(last.get('iterations'))is not int or not 0<=last['iterations']<=120:raise ValueError('Reader protocol or execution failed')
 decimal_last=json.loads(lines[-1],parse_float=Decimal,parse_constant=reject);oracle=decimal_last.get('physical_double_quad_relative_residual')
 certified=isinstance(oracle,(int,Decimal))and not isinstance(oracle,bool)and Decimal(oracle).is_finite()and Decimal(0)<=Decimal(oracle)<=Decimal.from_float(TOLERANCE)
 if returncode==0:
  if last.get('status')!='passed'or last['kernel_status']!='passed'or not certified:raise ValueError('Uncertified success')
 elif last.get('status')!='failed'or(last['kernel_status']=='passed'and certified):raise ValueError('Inconsistent failure attribution')
 if last['kernel_status']=='passed':
  r=decimal_last.get('relative_residual')
  if not isinstance(r,(int,Decimal))or isinstance(r,bool)or not Decimal(r).is_finite()or not Decimal(0)<=Decimal(r)<=Decimal.from_float(TOLERANCE):raise ValueError('Invalid successful kernel residual')
  certificates=[json.loads(line,parse_float=Decimal,parse_constant=reject)for line in lines if json.loads(line).get('kind')=='physical_double_quad_residual'and json.loads(line).get('selection')=='returned']
  if len(certificates)!=1 or certificates[0].get('binary_digits')!=113 or certificates[0].get('iteration')!=last['iterations']or certificates[0].get('relative_residual')!=oracle:raise ValueError('Returned physical-state certificate attribution differs')
 return rows

def execute_attempt(binary,case,item,root,timeout=600):
 folder=root/item['attempt_id'];folder.mkdir();capture={'path':case['path'],'sha256':case['sha256']};check(capture);check(binary)
 argv=[binary['path'],item['profile'],capture['path']];started=time.monotonic();record={'attempt_id':item['attempt_id'],'case_id':case['id'],'profile':item['profile'],'capture':capture,'binary':binary,'argv':argv,'status':'running','fit_attempts':0}
 save(folder/'result.json',record)
 try:
  with(folder/'trace.jsonl').open('xb')as out,(folder/'stderr.log').open('xb')as err:
   try:r=subprocess.run(argv,stdout=out,stderr=err,timeout=timeout,check=False)
   except subprocess.TimeoutExpired:record.update(status='timeout',returncode=None);return record
  rows=parse_trace(folder/'trace.jsonl',r.returncode,item['profile'],capture_metadata(capture['path']))
  record.update(status='reader_certified'if r.returncode==0 else'numerical_failure',returncode=r.returncode,terminal=rows[-1],input=rows[0],record_count=len(rows))
  return record
 except BaseException as error:record.update(status='execution_or_protocol_failed',error=repr(error));raise
 finally:
  record['elapsed_seconds']=time.monotonic()-started
  for key,name in [('trace','trace.jsonl'),('stderr','stderr.log')]:
   if(folder/name).is_file():record[key]=pin(folder/name)
  try:check(capture);check(binary)
  except BaseException as error:record.update(status='identity_failed',error=repr(error));save(folder/'result.json',record);raise
  save(folder/'result.json',record)

def logged(argv,root,name,expected_stdout=None):
 with(root/(name+'.stdout')).open('xb')as out,(root/(name+'.stderr')).open('xb')as err:r=subprocess.run(argv,stdout=out,stderr=err,timeout=600,check=False)
 value={'argv':argv,'returncode':r.returncode,'stdout':pin(root/(name+'.stdout')),'stderr':pin(root/(name+'.stderr'))}
 save(root/(name+'.json'),value)
 if r.returncode!=0 or(expected_stdout is not None and(root/(name+'.stdout')).read_text()!=expected_stdout):raise RuntimeError('Fixture/compilation failed: '+name)
 return value

def prepare(p,e,bundle,root,result):
 work=root/'compiled-source';work.mkdir()
 for name,value in bundle['files'].items():
  dest=work/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(check(value),dest)
 compiler=check(e['runtime_artifacts']['cxx_compiler']);result['steps']=[]
 for name,source in [('replay','replay.cpp'),('test_wide','test_wide.cpp')]:
  result['steps'].append(logged([str(compiler),'-O3','-DNDEBUG','-std=gnu++17','-I'+str(work/'include'),str(work/source),'-o',str(work/name)],root,'compile-'+name));save(root/'result.json',result)
 result['binary']=pin(work/'replay');result['compiler']=e['runtime_artifacts']['cxx_compiler'];result['compiler_version']=subprocess.check_output([str(compiler),'--version'],text=True)
 result['loader']=logged(['/usr/bin/ldd',str(work/'replay')],root,'reader-loader')
 for name,argv,expected in [('wide-fixtures',[str(work/'test_wide')],'wide diagnostic focused regressions passed\n'),('reader-fixtures',[sys.executable,str(work/'test_reader.py'),str(work/'replay')],'2 valid profile cases,12 invalid capture cases,3 invalid invocations passed\n'),('family-fixtures',[sys.executable,str(work/'test_family.py')],None)]:
  result['steps'].append(logged(argv,root,name,expected));save(root/'result.json',result)
 if 'Ran 4 tests'in(root/'family-fixtures.stderr').read_text()and(root/'family-fixtures.stderr').read_text().rstrip().endswith('OK'):pass
 else:raise ValueError('Exactly four family fixtures must pass')
 for a,h in ANCHORS.items():
  if p['inputs']['anchor_'+a]['sha256']!=h:raise ValueError('Anchor identity differs')
  check(p['inputs']['anchor_'+a])
 base=Path(p['inputs']['anchor_historical_large']['path']).parents[3]
 result['steps'].append(logged([sys.executable,str(work/'generate_family.py'),'--base',str(base),'--output',str(root/'family')],root,'generate-family'))
 family=root/'family/manifest.json';result['family_manifest']=pin(family);validate_family(json.loads(family.read_text()));validate_source_bundle(bundle)
 result['status']='prepared_family_no_planned_solves';result['planned_family_calls_executed']=0

def run_family(p,bundle,root,result):
 preflight=json.loads(check(p['inputs']['preflight_result']).read_text());previous=json.loads(check(p['inputs']['preflight_plan']).read_text());validate_plan(previous)
 if previous['phase']!='prepare'or preflight.get('status')!='prepared_family_no_planned_solves'or preflight.get('plan_sha256')!=p['inputs']['preflight_plan']['sha256']or preflight['source_bundle']!=p['inputs']['source_bundle']or preflight['family_manifest']!=p['inputs']['family_manifest']:raise ValueError('Exact successful preflight required')
 audit=json.loads(check(p['inputs']['family_audit']).read_text())
 if audit.get('passed')is not True or audit.get('family_manifest')!=p['inputs']['family_manifest']:raise ValueError('Independent exact family audit required')
 binary=preflight['binary'];check(binary);family_path=check(p['inputs']['family_manifest']);family=json.loads(family_path.read_text());cases,order=validate_family(family)
 result.update(binary=binary,planned_attempts=order,attempts=[]);attempt_root=root/'attempts';attempt_root.mkdir();save(root/'result.json',result)
 for item in order:
  check(p['inputs']['family_manifest']);validate_source_bundle(bundle)
  try:record=execute_attempt(binary,cases[item['case_id']],item,attempt_root)
  except BaseException as error:
   receipt=attempt_root/item['attempt_id']/'result.json'
   result['attempts'].append(json.loads(receipt.read_text())if receipt.is_file()else dict(item,status='not_started_control_failure',error=repr(error)))
   raise
  result['attempts'].append(record);save(root/'result.json',result)
 validate_family(family);validate_source_bundle(bundle);result['status']='completed_all_planned_calls'

def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv)
 if sha(a.plan)!=a.sha256:raise ValueError('Plan changed')
 p=json.loads(a.plan.read_text());validate_plan(p);e=json.loads(check(p['execution']).read_text());bundle=json.loads(check(p['inputs']['source_bundle']).read_text());validate_source_bundle(bundle)
 root=Path(p['output'])
 if root.exists():raise ValueError('Preserve previous experiment')
 root.mkdir();result={'schema':'orbit-poc-tangent-rhs-family-result-v1','status':'running','phase':p['phase'],'plan_sha256':a.sha256,'source_bundle':p['inputs']['source_bundle'],'fit_attempts':0,'groops_propagations':0,'release_evidence':False,'reference_native_not_executed':p['native']};save(root/'result.json',result)
 try:
  if p['phase']=='prepare':prepare(p,e,bundle,root,result)
  else:run_family(p,bundle,root,result)
 except BaseException as error:result.update(status='stopped_on_control_or_runtime_failure',error=repr(error));raise
 finally:save(root/'result.json',result)
 return 0
if __name__=='__main__':raise SystemExit(main())
