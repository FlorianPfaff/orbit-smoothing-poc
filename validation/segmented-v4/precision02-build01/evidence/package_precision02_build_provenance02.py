"""Append-only publication, blocked until actual precision02 build and audit pass."""
from pathlib import Path
import argparse,base64,collections,hashlib,json
BASE=Path('/mnt/d/orbit-segmented-v4');CONTROL=BASE/'control'
PLAN='09f659c3a5fb3719a4cb46e6b76194f9317e6f379653ec21e5828607ba088e53'
EXECUTION='89814a08b267b3a5c23bf5e188175095c7a4e86b4936de0b063513af6d13a7b8'
BASELINE='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
HEADER='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
SOURCE_ID='518a329e0e6522d12b2408cba1c35360279ccc5818baf0523146c1f529674a8f'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=Path(p).read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def require(v,message):
 if not v:raise ValueError(message)
def check(p):
 require(isinstance(p,dict)and set(p)=={'path','sha256','bytes'},'Exact file pin required')
 q=Path(p['path']);require(q.is_absolute()and '..'not in q.parts and q.is_file()and not q.is_symlink(),'Canonical regular evidence required')
 b=q.read_bytes();require(sha(b)==p['sha256']and len(b)==p['bytes'],'Changed evidence bytes');return q,b

def validate_documents(result,audit,source,result_pin):
 require(result.get('schema')=='orbit-poc-tangent-precision-candidate-build-v1'and result.get('status')=='built_precision_candidate','Actual completed precision build required')
 require(audit.get('schema')=='orbit-poc-independent-native-compensation-build-terminal-review-v1' and audit.get('passed')is True,'Passed independent actual-build audit required')
 require(audit.get('plan',{}).get('sha256')==PLAN and audit.get('execution',{}).get('sha256')==EXECUTION,'Wrong build plan or execution')
 remote=audit.get('actual_result',{});require(remote.get('sha256')==result_pin['sha256']and remote.get('bytes')==result_pin['bytes']and '/tangent-precision-02/run/'in remote.get('path',''),'Audit does not bind exact actual02 result')
 require(audit.get('native')==result.get('native')and result['native']['path'].startswith('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-precision-02/binaries/'),'Native identity differs')
 require(result.get('fit_attempts')==0 and result.get('release_evidence')is False,'Unsupported fitting/release scope')
 require(result.get('baseline_relinked_sha256')==BASELINE and result.get('original_native',{}).get('sha256')==BASELINE,'Original baseline reproduction missing')
 key='misc/orbitPoc/sixStateTangent.h';before=result['source_before'];after=result['source_after']
 require(set(before)==set(after)and len(before)==1131 and {k for k in before if before[k]!=after[k]}=={key}and after[key]==HEADER,'Source delta differs from reviewed header')
 commands=result['compile_commands'];rebuilt=result['rebuilt_objects'];original=result['original_object_sha256'];changed=result['changed_objects']
 require(len(commands)==len(rebuilt)==len(set(rebuilt))==27 and set(rebuilt)==set(commands),'All27 dependency translation units must be rebuilt')
 require(len(original)==611 and set(rebuilt).issubset(original)and result.get('reused_object_count')==584,'Object reuse inventory differs')
 require(set(changed).issubset(rebuilt)and 'CMakeFiles/groopscore.dir/programs/preprocessing/preprocessingVariationalEquation.cpp.o'in changed,'Changed object inventory differs')
 require(len(result['all_original_link_inputs'])==637,'Full link-input attribution required')
 require(source.get('source_commit')=='8aab780ec5807347c0a45aca94d042457bf77ad8','Wrong committed source')
 expected={'groops/extension/sixStateTangent.h':HEADER,'tests/fixtures/tangent_compensated_quadrature.cpp':'1e11c286ceeec33bc5f75fc9a2287dbcf76e4bca565a693228eefe32b2037627','tests/test_numerics_compensated_quadrature.py':'1638627325eb31a6dd25a46b30f8dff242c091e13c61ae0e5d0eeea5582383b7'}
 require({x['repository_path']:x['committed_sha256']for x in source['files']}==expected,'Committed header or supplemental identity changed')
 return {'native':result['native'],'baseline_relinked_sha256':BASELINE,'source_commit':source['source_commit'],'candidate_header_sha256':HEADER,'recompiled_translation_units':27,'changed_objects':len(changed),'reused_objects':584,'original_objects':611,'original_link_inputs':637,'fit_attempts':0,'release_ready':False,'native_closure_claimed':False}

def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)

def run(spec):
 require(set(spec)=={'schema','output','actual_result','independent_audit','records'},'Unknown publication option')
 require(spec['schema']=='orbit-poc-precision02-build-publication-spec-v1','Wrong specification schema')
 result_path,result_bytes=check(spec['actual_result']);audit_path,audit_bytes=check(spec['independent_audit'])
 source_path=CONTROL/'precision02-source-identity01.json';require(pin(source_path)['sha256']==SOURCE_ID,'Source receipt changed');source=json.loads(source_path.read_bytes())
 result=json.loads(result_bytes);audit=json.loads(audit_bytes);summary=validate_documents(result,audit,source,spec['actual_result'])
 files={result_path,audit_path,source_path,Path(__file__).resolve()}
 for r in spec['records']:q,_=check(r);files.add(q)
 pending=list(files)
 while pending:
  q=pending.pop()
  if q.suffix!='.json':continue
  try:doc=json.loads(q.read_bytes())
  except json.JSONDecodeError:continue
  for r in walk(doc):
   p=Path(r['path'])
   if p.is_relative_to(CONTROL)and p.is_file()and not p.is_symlink()and p.suffix not in {'.gz','.bin','.so','.pyc'}and p.stat().st_size<1500000:
    b=p.read_bytes();require(sha(b)==r['sha256'],'Changed referenced local evidence: '+str(p))
    if 'bytes'in r:require(len(b)==r['bytes'],'Referenced byte count changed')
    if p not in files:files.add(p);pending.append(p)
 output=Path(spec['output']);require(output.parent==BASE and output.name.startswith('publication-precision02-build-'),'Output outside dedicated publication root')
 require(not output.exists()and not output.is_symlink(),'Preserve previous publication');output.mkdir()
 rows=[];documents={};copies={}
 def put(rel,b,original=None,attribution=None):
  p=output/rel;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb')as f:f.write(b)
  r={'path':rel,'sha256':sha(b),'bytes':len(b)}
  if original:r['original']=original
  if attribution:r['attribution']=attribution
  rows.append(r)
 for p in sorted(files):
  require(p.is_relative_to(CONTROL),'Publication sources must be local control evidence')
  rel='evidence/'+str(p.relative_to(CONTROL));b=p.read_bytes();put(rel,b,pin(p),'Exact local evidence or source bytes; remote acquisition is identified separately.')
  if p.suffix=='.json':
   try:documents[str(p)]=json.loads(b)
   except json.JSONDecodeError:pass
 copies[(audit['actual_result']['path'],audit['actual_result']['sha256'])]='evidence/'+str(result_path.relative_to(CONTROL))
 original_index=0
 for name,doc in documents.items():
  for r in walk(doc):
   if 'base64'not in r:continue
   b=base64.b64decode(r['base64'],validate=True);require(sha(b)==r['sha256']and len(b)==r['bytes'],'Raw capture differs')
   key=(r['path'],r['sha256'])
   if key in copies:continue
   original_index+=1;rel=f'original/{original_index:03d}-{Path(r["path"]).name}';put(rel,b,{k:r[k]for k in ['path','sha256','bytes']},'Exact original remote bytes decoded from pinned base64 capture.');copies[key]=rel
 external={}
 for name,doc in documents.items():
  for r in walk(doc):
   if not r['path'].startswith('/')or r['path'].startswith(str(CONTROL)+'/')or len(r['sha256'])!=64:continue
   key=(r['path'],r['sha256']);e=external.setdefault(key,{'path':r['path'],'sha256':r['sha256'],'recorded_in':[]})
   if 'bytes'in r:e['bytes']=r['bytes']
   if name not in e['recorded_in']:e['recorded_in'].append(name)
   if key in copies:e.update(availability='copied_exact_remote_record',copy=copies[key])
   else:e['availability']='external_payload_not_copied_by_this_publication'
 summary.update(schema='orbit-poc-precision02-build-publication-v1',status='actual_build_and_attribution_verified',independent_audit=pin(audit_path),actual_result=pin(result_path),scope=['Native candidate build attribution only. No propagated closure, complete-suite pass, benchmark fit, covariance or release readiness is inferred.','The new supplemental fixture and Python runner are explicitly pinned to the source commit; their existence is not a compiled-test outcome and does not modify frozen106/51 test inventories.','All455 staged runtime declarations and original27-translation-unit worker are historical control provenance; actual terminal audit and exact result authorize the build statement.','Original a669 baseline and native inputs remain separate; previous failures and diagnostic candidates are retained.'])
 put('summary.json',(json.dumps(summary,indent=2)+'\n').encode());put('external-evidence.json',(json.dumps({'records':list(external.values()),'scope':'Exact recorded input/output pins; external native binaries/build payloads remain outside Git.'},indent=2)+'\n').encode())
 text='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Precision02 native build provenance</title><style>body{font:16px system-ui;max-width:900px;margin:3rem auto;line-height:1.5}code{word-break:break-all}</style><h1>Precision02 native candidate build</h1><p>The actual completed build and its independent attribution audit passed. The original a669 baseline was reproduced exactly, all27 dependent translation units were rebuilt, and584 of611 original objects were reused. The full637 link-input inventory and one-header source delta are recorded.</p><p>Candidate header <code>9a46f045…</code> and the supplemental cancellation fixture/runner are pinned to commit <code>8aab780</code>. Supplemental source identity does not imply a compiled fixture pass or change the frozen106/51 required test counts.</p><p><strong>Build provenance only: no native trajectory closure, complete validation-suite pass, benchmark fit, covariance or release readiness is claimed.</strong></p><p><a href="summary.json">Actual native identity and audit</a> · <a href="external-evidence.json">External source/build/runtime pins</a> · <a href="manifest.json">Exact byte manifest</a></p></html>'''
 for a,b in [('all27','all 27'),('and584','and 584'),('of611','of 611'),('full637','full 637'),('frozen106/51','frozen 106/51')]:text=text.replace(a,b)
 put('index.html',text.encode());manifest={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Actual precision02 native build only; downstream numerical validation remains separate.'};(output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return {'output':str(output),'manifest':pin(output/'manifest.json'),'files':len(rows)}
def main():
 p=argparse.ArgumentParser();p.add_argument('--spec',required=True);p.add_argument('--sha256',required=True);a=p.parse_args();s=Path(a.spec);require(sha(s.read_bytes())==a.sha256,'Specification changed');print(json.dumps(run(json.loads(s.read_bytes())),indent=2))
if __name__=='__main__':main()
