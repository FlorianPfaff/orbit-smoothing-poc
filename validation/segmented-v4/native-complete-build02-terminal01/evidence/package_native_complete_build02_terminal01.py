"""Compact actual full-build publication; blocked until the independent audit passes."""
from pathlib import Path
import base64,hashlib,json,re,sys
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=C.parent
RESULT='0513e768a7e85fbc75cef08ccedde923563980b3e2ff4dc03d48d986526615f2'
CAPTURE='0faae52c6b349fef10f5d63aef3bbea3d393962e2a1f66e4aba36debea4b6243'
COMPACT='69ee4dc6c9831043bb1f1cb29d1e0a4d8160b8be66fe2b8875de86404610ce59'
NATIVE='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def need(v,m):
 if not v:raise ValueError(m)
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str)and len(v['sha256'])==64:yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
def run(spec):
 need(set(spec)=={'schema','output','sources','independent_audit'},'Unknown publication options');need(spec['schema']=='orbit-poc-complete-build02-terminal-publication-spec-v1','Wrong schema');files={};docs={}
 for r in spec['sources']:
  p=Path(r['path']);need(p.parent==C and p.is_file()and not p.is_symlink()and pin(p)==r,'Changed exact local record: '+str(p));files[p.name]=(p,p.read_bytes())
  if p.suffix=='.json':
   try:docs[p.name]=json.loads(p.read_bytes())
   except json.JSONDecodeError:pass # Retain empty failed audit/readback bytes without treating them as evidence.
 auditpath=Path(spec['independent_audit']['path']);need(pin(auditpath)==spec['independent_audit']and auditpath.name in docs,'Audit absent or changed');audit=docs[auditpath.name]
 need(audit.get('passed')is True and audit['actual_build_result']['sha256']==RESULT and audit['native']['sha256']==NATIVE,'Actual independent build audit not passed')
 need(audit['compiled_objects']==611 and audit['cpp_objects']==591 and audit['fortran_objects']==20 and audit['fortran_preprocessing']==20 and audit['complete_commands']==633 and audit['reused_objects']==0 and audit['full_source_files']==1134,'Full fresh build not certified')
 need(audit['scope']=={'propagations':0,'fits':0,'scientific_gates':0,'release_ready':False},'Unsupported scientific scope')
 raw={};documents=[]
 for name,digest,count in [('native-complete-build02-terminal-capture01.json',CAPTURE,32),('native-complete-build02-compile-records01.json',COMPACT,5)]:
  need(sha(files[name][1])==digest and len(docs[name]['files'])==count,'Capture identity/membership differs')
  for r in docs[name]['files']:
   b=base64.b64decode(r['base64'],validate=True);need(sha(b)==r['sha256']and len(b)==r['bytes'],'Raw original changed');key=(r['path'],r['sha256']);need(key not in raw,'Duplicate original');raw[key]=(r,b)
 def original(r):need((r['path'],r['sha256'])in raw,'Required exact original absent');return raw[(r['path'],r['sha256'])][1]
 result=json.loads(original(audit['actual_build_result']));evidence=json.loads(original(result['complete_compile_evidence']));normalized=json.loads(original(result['normalized_configuration']));pipeline=json.loads(original(audit['pipeline']))
 need(result['schema']=='orbit-poc-native-complete-build-v1'and result['status']=='built_complete_candidate'and result['compiled_object_count']==611 and result['preprocessing_count']==20 and result['reused_object_count']==0,'Wrong completed build')
 need(result['native']==audit['native']and result['candidate_source_sha256']==audit['candidate_source_sha256']and len(result['source_before'])==1131 and len(result['source_after'])==1134,'Source/native attribution differs')
 need(pipeline['status']=='passed_diagnostic'and pipeline['final_cleanup']['verified'],'Terminal controller/cleanup not passed')
 need(len(evidence['cpp'])==591 and len(evidence['fortran'])==20 and len(evidence['preprocess'])==20 and len(evidence['linked_objects'])==611 and evidence['reused_object_count']==0,'Missing per-object evidence')
 commands=json.loads(original(evidence['candidate_commands']))['commands'];verbose=original(evidence['verbose_stdout']).decode();invocations=[m.group(1)for x in verbose.splitlines()if(m:=re.match(r'^\[\d+/633\] (.*)$',x))]
 from collections import Counter
 need(len(commands)==len(invocations)==633 and Counter(commands)==Counter(invocations),'Actual complete command multiset differs')
 need(normalized['serial_jobs']==1 and len(normalized['normalized_commands'])==633,'Serial normalized recipe absent')
 out=Path(spec['output']);need(out==BASE/'publication-native-complete-build02-terminal01'and not out.exists(),'Fresh publication required');out.mkdir();rows=[];copies={}
 def put(rel,b,source=None,attr=None):
  p=out/rel;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb')as f:f.write(b)
  r={'path':rel,'sha256':sha(b),'bytes':len(b)}
  if source:r['original']=source;copies[(source['path'],source['sha256'])]=rel
  if attr:r['attribution']=attr
  rows.append(r)
 for n,(p,b)in sorted(files.items()):
  put('evidence/'+n,b,pin(p),'Exact local evidence/control source; remote originals are attributed separately.')
  if n in docs:documents.append((str(p),docs[n]))
 remote_root=docs['native-complete-build02-terminal-capture01.json']['root']
 for key,(r,b)in sorted(raw.items()):
  rel=Path(r['path']).relative_to(remote_root);need('..'not in rel.parts,'Unsafe original path');put('original/'+str(rel),b,{k:r[k]for k in ['path','sha256','bytes']},'Exact existing remote bytes from one terminal capture or the explicitly pinned five-record supplement.')
  if r['path'].endswith('.json'):
   try:documents.append((r['path'],json.loads(b)))
   except json.JSONDecodeError:pass
 refs={}
 for source,doc in documents:
  for r in walk(doc):
   if not r['path'].startswith('/'):continue
   key=(r['path'],r['sha256']);e=refs.setdefault(key,{'path':r['path'],'sha256':r['sha256'],'recorded_in':[]})
   if 'bytes'in r:e['bytes']=r['bytes']
   if source not in e['recorded_in']:e['recorded_in'].append(source)
   if key in copies:e.update(availability='copied_exact_bytes',copy=copies[key])
   else:e['availability']='external_payload_not_read_or_copied_by_this_publication'
 summary={'schema':'orbit-poc-native-complete-build02-terminal-publication-v1','status':'fresh_complete_native_build_independently_audited','build_finished_at':pipeline['finished_at'],'audit_observed_at':audit['observed_at'],'independent_audit':pin(auditpath),'actual_result':audit['actual_build_result'],'native':result['native'],'source':{'before_files':1131,'after_files':1134,'candidate_source_sha256':result['candidate_source_sha256'],'source_delta':result['source_delta'],'installation_equivalence':result['installation_equivalence']},'compilation':{'cpp_objects':591,'fortran_objects':20,'compiled_objects':611,'preprocessing_commands':20,'dynamic_dependency_commands':1,'link_commands':1,'total_commands':633,'reused_objects':0,'serial_jobs':1,'complete_compile_evidence':result['complete_compile_evidence'],'normalized_configuration':result['normalized_configuration'],'native_help_passed':next(x for x in result['stages']if x['label']=='native-help')['returncode']==0},'scope':{'propagations':0,'native_full_closure_passed':False,'new_complete_scientific_suite_passed':False,'v4_fit_attempts':0,'v4_planned_fits':68,'release_ready':False},'original_compact_records':37,'external_scope':'All source checkouts, object files and native binaries remain external. Exact compiled-object hashes/inodes and full source hashes are copied as receipts. The 28MB raw dependency listing remains external with its original pin. No external payload is re-audited by this publication.','preserved_history':'Earlier retained preflight/build-control failures are linked separately. This package retains both failed terminal-audit invocations and the separately versioned strict schema/alias corrections; neither changed or repeated the native build.'}
 put('summary.json',(json.dumps(summary,indent=2)+'\n').encode());put('external-evidence.json',(json.dumps({'schema':'orbit-poc-explicit-copy-attribution-v1','records':list(refs.values())},indent=2)+'\n').encode())
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Complete native build02: actual audited result</title><style>body{font:16px system-ui;line-height:1.55;max-width:960px;margin:3rem auto}code{word-break:break-all}</style><h1>Complete native build02 passed its build audit</h1><p><strong>The fresh full build finished at22:02:15 UTC on October16,2026 and produced executable <code>643a1b6d…</code>. Native trajectory closure, the new complete scientific correctness suite and all68 benchmark fits remain pending.</strong></p><p>All611 linked objects were freshly compiled:591 C++ and20 Fortran. The exact633-command inventory includes20 Fortran preprocessing steps, one dynamic-dependency step and one final link. No old object was reused. Actual verbose commands, Ninja success records, object hashes/inodes and normalized recipe equivalence are retained, together with the real CMake cache and public build-script invocation.</p><p>The complete1,134-file installed tree matches the pinned source delta and independently verified pristine installation. The baseline source and dependencies remain preserved. Native help ran successfully; this is a build smoke check, not a propagation or estimator test.</p><p>Two independent audit invocations failed on an incorrect expected recipe schema and a host-only alias lookup. Their exact stderr and prior verifier/auditor versions remain preserved alongside the corrected strict audit. The corrected resolver uses the already pinned namespace mapping; no interpreter, numerical tolerance or build was substituted. Earlier control failures and source/fixture preflights remain in their separate immutable reports.</p><p>The raw dependency listing, native executable, source trees and objects remain external with explicit pins. This report copies37 exact compact original records, including the complete per-object compile evidence and command logs. V4 remains at0/68 fits and is not release-ready.</p><p><a href="summary.json">Actual result and audit</a> · <a href="original/run/build-result/complete-compile-evidence.json">Fresh per-object evidence</a> · <a href="original/run/build-result/normalized-configuration.json">Normalized recipe</a> · <a href="original/build/CMakeCache.txt">Actual cache</a> · <a href="external-evidence.json">External/copy attribution</a> · <a href="manifest.json">Exact byte manifest</a></p></html>'''
 for a,b in [('at22','at 22'),('October16,2026','October 16, 2026'),('all68','all 68'),('All611','All 611'),(':591',': 591'),('and20','and 20'),('exact633','exact 633'),('includes20','includes 20'),('complete1,134','complete 1,134'),('copies37','copies 37'),('at0/68','at 0/68')]:page=page.replace(a,b)
 put('index.html',page.encode());m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(r['bytes']for r in rows),'scope':'Audited fresh complete native build only; native closure, new full scientific suite and 68 orbit-fit campaign remain pending.'};(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');return {'output':str(out),'manifest':pin(out/'manifest.json'),'files':len(rows),'bytes':m['total_bytes'],'raw_originals':len(raw),'references':len(refs)}
if __name__=='__main__':
 p=Path(sys.argv[1]);need(sha(p.read_bytes())==sys.argv[2],'Changed specification');print(json.dumps(run(json.loads(p.read_bytes())),indent=2))
