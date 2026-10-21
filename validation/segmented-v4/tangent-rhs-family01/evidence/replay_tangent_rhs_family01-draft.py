#!/usr/bin/env python3
"""Frozen captured-system experiment: 27 right-hand sides, two modes, no fits."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys,time,xml.etree.ElementTree as ET
SCHEMA='orbit-poc-tangent-rhs-family-plan-v1'
INPUTS={'source_bundle','family_manifest'}
PROFILES={'baseline','wide'}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def check(value):
 if set(value)!={'path','sha256'}:raise ValueError('Exact file pin required')
 p=Path(value['path'])
 if not p.is_absolute()or '..'in p.parts or str(p)!=str(p.resolve())or not p.is_file()or p.is_symlink()or sha(p)!=value['sha256']:raise ValueError('Pinned canonical file differs')
 return p
def save(p,value):
 with Path(p).open('w')as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
def validate_plan(p):
 if set(p)!={'schema','execution','driver','worker','controller','native','source_freeze','inputs','output','global_lock'}or p['schema']!=SCHEMA or set(p['inputs'])!=INPUTS:raise ValueError('Unknown family diagnostic plan')
 for k in('output','global_lock'):
  q=Path(p[k])
  if not q.is_absolute()or '..'in q.parts:raise ValueError('Absolute canonical path required')
def validate_family(manifest):
 if manifest.get('schema_version')!=1:raise ValueError('Unknown RHS family schema')
 anchors=manifest.get('anchors');cases=manifest.get('cases');order=manifest.get('execution_order')
 if not isinstance(anchors,list)or len(anchors)!=3 or not isinstance(cases,list)or len(cases)!=27 or not isinstance(order,list)or len(order)!=54:raise ValueError('Exact three-anchor/27-case/54-call family required')
 ids=[x['id']for x in cases]
 if len(set(ids))!=27 or any(not isinstance(x,str)or not x or '/'in x or '..'in x for x in ids):raise ValueError('Invalid family case identities')
 anchor_ids={x['id']for x in anchors}
 if len(anchor_ids)!=3 or any(sum(c['anchor']==a for c in cases)!=9 for a in anchor_ids):raise ValueError('Exactly nine cases per anchor required')
 for c in cases:
  if not {'id','path','sha256','anchor','direction','sign','relative_scale'}.issubset(c):raise ValueError('Missing frozen perturbation attribution')
  if c['anchor']not in anchor_ids:raise ValueError('Unknown anchor')
  check({'path':c['path'],'sha256':c['sha256']})
 for a in anchors:check({'path':a['path'],'sha256':a['sha256']})
 pairs=[];attempts=[]
 for item in order:
  if set(item)!={'attempt_id','case_id','profile'}or item['case_id']not in ids or item['profile']not in PROFILES:raise ValueError('Invalid frozen execution order')
  if not isinstance(item['attempt_id'],str)or not item['attempt_id']or '/'in item['attempt_id']or '..'in item['attempt_id']:raise ValueError('Invalid attempt identity')
  pairs.append((item['case_id'],item['profile']));attempts.append(item['attempt_id'])
 if len(set(attempts))!=54 or set(pairs)!={(i,p)for i in ids for p in PROFILES}or len(set(pairs))!=54:raise ValueError('Each case/profile must occur exactly once')
 return {x['id']:x for x in cases},order
def validate_source_bundle(bundle):
 if set(bundle)!={'schema','source_manifest','files','compile_units','test_files','expected_test_count'}or bundle['schema']!='orbit-poc-tangent-rhs-source-bundle-v1':raise ValueError('Unknown source bundle')
 check(bundle['source_manifest'])
 if not isinstance(bundle['files'],dict)or not bundle['files']:raise ValueError('Empty source closure')
 for name,value in bundle['files'].items():
  p=Path(name)
  if p.is_absolute()or '..'in p.parts or str(p)!=name:raise ValueError('Unsafe relative source member')
  check(value)
 units=bundle['compile_units']
 if not isinstance(units,dict)or units.get('replay')!='replay.cpp'or not 1<=len(units)<=3:raise ValueError('Common replay binary required')
 for name,source in units.items():
  if '/'in name or '..'in name or not name or source not in bundle['files']or not source.endswith('.cpp'):raise ValueError('Invalid native fixture unit')
 if not bundle['test_files']or any(n not in bundle['files']or not n.endswith('.py')for n in bundle['test_files'])or not isinstance(bundle['expected_test_count'],int)or bundle['expected_test_count']<=0:raise ValueError('Exact fixture inventory required')
def parse_trace(path,returncode):
 def reject(value):raise ValueError('Non-finite JSON diagnostic '+value)
 rows=[json.loads(x,parse_constant=reject)for x in Path(path).read_text().splitlines()]
 if not rows or rows[0].get('kind')!='input'or rows[-1].get('kind')!='terminal':raise ValueError('Reader lacks input/terminal attribution')
 if returncode not in(0,1):raise ValueError('Reader protocol or execution failed')
 return rows
def execute_attempt(binary,case,item,root,timeout=600):
 folder=root/item['attempt_id'];folder.mkdir();capture={'path':case['path'],'sha256':case['sha256']};check(capture);check(binary)
 argv=[binary['path'],item['profile'],capture['path']];started=time.monotonic();record={'attempt_id':item['attempt_id'],'case_id':case['id'],'profile':item['profile'],'capture':capture,'binary':binary,'argv':argv,'status':'running','fit_attempts':0}
 save(folder/'result.json',record)
 try:
  with(folder/'trace.jsonl').open('xb')as out,(folder/'stderr.log').open('xb')as err:
   try:r=subprocess.run(argv,stdout=out,stderr=err,timeout=timeout,check=False)
   except subprocess.TimeoutExpired:record.update(status='timeout',returncode=None);return record
  rows=parse_trace(folder/'trace.jsonl',r.returncode)
  record.update(status='reader_certified'if r.returncode==0 else'numerical_failure',returncode=r.returncode,terminal=rows[-1],input=rows[0],record_count=len(rows),trace=pin(folder/'trace.jsonl'),stderr=pin(folder/'stderr.log'))
  return record
 except BaseException as error:record.update(status='execution_or_protocol_failed',error=repr(error));raise
 finally:
  record['elapsed_seconds']=time.monotonic()-started
  try:check(capture);check(binary)
  except BaseException as error:record.update(status='identity_failed',error=repr(error));save(folder/'result.json',record);raise
  save(folder/'result.json',record)
def main(argv=None):
 ap=argparse.ArgumentParser();ap.add_argument('--plan',type=Path,required=True);ap.add_argument('--sha256',required=True);a=ap.parse_args(argv)
 if sha(a.plan)!=a.sha256:raise ValueError('Plan changed')
 p=json.loads(a.plan.read_text());validate_plan(p)
 e=json.loads(check(p['execution']).read_text());family_path=check(p['inputs']['family_manifest']);family=json.loads(family_path.read_text());cases,order=validate_family(family)
 bundle=json.loads(check(p['inputs']['source_bundle']).read_text());validate_source_bundle(bundle)
 root=Path(p['output'])
 if root.exists():raise ValueError('Preserve previous experiment')
 root.mkdir();work=root/'compiled-source';work.mkdir();result={'schema':'orbit-poc-tangent-rhs-family-result-v1','status':'running','plan_sha256':a.sha256,'family_manifest':p['inputs']['family_manifest'],'source_bundle':p['inputs']['source_bundle'],'planned_attempts':order,'attempts':[],'fit_attempts':0,'groops_propagations':0,'release_evidence':False,'reference_native_not_executed':p['native']}
 save(root/'result.json',result)
 try:
  for name,value in bundle['files'].items():
   dest=work/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(check(value),dest)
  compiler=check(e['runtime_artifacts']['cxx_compiler']);commands={}
  for name,source in bundle['compile_units'].items():
   command=[str(compiler),'-O3','-DNDEBUG','-std=gnu++17','-I'+str(work/'include'),str(work/source),'-o',str(work/name)];commands[name]=command
   with(root/('compile-'+name+'.log')).open('xb')as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=600)
  result['compile_commands']=commands;result['binary']=pin(work/'replay');result['compiler_version']=subprocess.check_output([str(compiler),'--version'],text=True)
  fixture_command=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider',*[str(work/n)for n in bundle['test_files']],'--junitxml='+str(root/'fixtures.xml')]
  with(root/'fixtures.log').open('xb')as f:subprocess.run(fixture_command,stdout=f,stderr=subprocess.STDOUT,check=True,timeout=600)
  suites=list(ET.parse(root/'fixtures.xml').getroot().iter('testsuite'))
  if len(suites)!=1 or any(int(suites[0].get(k,'0'))!=v for k,v in [('tests',bundle['expected_test_count']),('errors',0),('failures',0),('skipped',0)]):raise ValueError('Fixture inventory did not pass exactly')
  result['fixture_command']=fixture_command;result['fixtures']=pin(root/'fixtures.xml');result['family_reverified_before_first_call']=pin(check(p['inputs']['family_manifest']));validate_family(family);save(root/'result.json',result)
  attempt_root=root/'attempts';attempt_root.mkdir()
  for item in order:
   check(p['inputs']['family_manifest']);validate_source_bundle(bundle)
   result['attempts'].append(execute_attempt(result['binary'],cases[item['case_id']],item,attempt_root));save(root/'result.json',result)
  validate_family(family);validate_source_bundle(bundle);result['status']='completed_all_planned_calls'
 except BaseException as error:result.update(status='stopped_on_control_or_runtime_failure',error=repr(error));raise
 finally:save(root/'result.json',result)
 return 0
if __name__=='__main__':raise SystemExit(main())
