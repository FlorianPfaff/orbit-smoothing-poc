"""Publish exact existing source/fixture preflight evidence; no execution or inferred readiness."""
from pathlib import Path
import base64,hashlib,json,sys,html
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=C.parent
AUDITS={'01':'8a77005ca063a9dd19e823944bd48471dbff7e07dab73c634cf06e167f041667','02':'be2bdae00a50ace30ef0bb8a8bcfb537f54fa5612b397c63f3dcff0a21b0cab8','03':'bf5903c98b8fc54a02fb81520ed787fdceaf97b4b67fd6c1a3fc107313da8ffa'}
CAPTURES={'01':'a8f79fb416fe032e16bf67c14508fca4e1d167e152c72c6f4d34d74585c94154','02':'dc882cdd511ac942a12ca90c9497ef6dfaee7ae4649b92bfaa945c94808a36c6','03':'673eddb0abf596ebaaf4a6387e6c3a946ee548afd285ea095aa45aa18b38b8af'}
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def require(v,m):
 if not v:raise ValueError(m)
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str)and len(v['sha256'])==64:yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
def run(spec):
 require(set(spec)=={'schema','output','records'},'Unknown option');require(spec['schema']=='orbit-poc-native-complete-preflight-publication-spec-v1','Wrong schema')
 data={};docs={}
 for r in spec['records']:
  p=Path(r['path']);require(p.parent==C and p.is_file()and not p.is_symlink(),'Only regular immediate control evidence');b=p.read_bytes();require(pin(p)==r,'Changed pinned record');data[p.name]=(p,b)
  if p.suffix=='.json':
   try:docs[p.name]=json.loads(b)
   except json.JSONDecodeError:pass # Preserved failed empty readback, not a result.
 audits={};raw={}
 for number in ['01','02','03']:
  a=f'native-complete-preflight{number}-independent-'+('terminal-review01.json'if number=='03'else'failure-review01.json');c=f'native-complete-preflight{number}-terminal-capture01.json'
  require(sha(data[a][1])==AUDITS[number]and sha(data[c][1])==CAPTURES[number],'Wrong exact audit/capture');audits[number]=docs[a];require(audits[number]['passed']is True,'Actual audit failed')
  capture=docs[c];require(len(capture['files'])=={'01':19,'02':22,'03':44}[number],'Changed raw membership')
  for r in capture['files']:
   b=base64.b64decode(r['base64'],validate=True);require(len(b)==r['bytes']and sha(b)==r['sha256'],'Original bytes differ');key=(r['path'],r['sha256']);require(key not in raw,'Duplicate original');raw[key]=(number,r,b)
 a=audits['03'];require(a['scope']=={'candidate_groops_objects_compiled':0,'fits':0,'propagations':0,'release_ready':False,'scientific_gates':0},'Wrong scope')
 require(a['source']['installed_files']==1134 and a['source']['original_files']==1131 and a['source']['replacements']==4 and a['source']['additions']==3 and a['source']['full_actual_tree_hashed']and a['source']['original_preserved'],'Source equivalence absent')
 require(a['baseline']['native_sha256']=='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'and a['baseline']['executable_rehashed'],'Baseline not certified')
 require(a['supplemental']['interpolation']and a['supplemental']['serializer']and a['supplemental']['exact_fraction_roundtrip'],'Supplemental fixture incomplete')
 for k in ['preflight_result','installation_equivalence','supplemental_fixtures','baseline_relink','plan','execution','pipeline']:
  require((a[k]['path'],a[k]['sha256'])in raw,'Actual audited original missing: '+k)
 out=Path(spec['output']);require(out.parent==BASE and out.name=='publication-native-complete-preflight01'and not out.exists(),'Fresh exact publication required');out.mkdir()
 rows=[];copies={};documents=[]
 def put(rel,b,origin=None,attribution=None):
  p=out/rel;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb')as f:f.write(b)
  row={'path':rel,'sha256':sha(b),'bytes':len(b)}
  if origin:row['original']=origin;copies[(origin['path'],origin['sha256'])]=rel
  if attribution:row['attribution']=attribution
  rows.append(row)
 for n,(p,b)in sorted(data.items()):
  put('evidence/'+n,b,pin(p),'Exact local evidence; original remote bytes are separately decoded and attributed.')
  if n in docs:documents.append((str(p),docs[n]))
 for (path,digest),(number,r,b)in sorted(raw.items()):
  root=docs[f'native-complete-preflight{number}-terminal-capture01.json']['root'];relative=Path(path).relative_to(root);require('..'not in relative.parts,'Invalid original path')
  put('original/preflight'+number+'/'+str(relative),b,{k:r[k]for k in ['path','sha256','bytes']},'Exact original remote bytes decoded from the pinned terminal capture.')
  if path.endswith('.json'):
   try:documents.append((path,json.loads(b)))
   except json.JSONDecodeError:pass
 refs={}
 for recorded,doc in documents:
  for r in walk(doc):
   if not r['path'].startswith('/'):continue
   key=(r['path'],r['sha256']);v=refs.setdefault(key,{'path':r['path'],'sha256':r['sha256'],'recorded_in':[]})
   if 'bytes'in r:v['bytes']=r['bytes']
   if recorded not in v['recorded_in']:v['recorded_in'].append(recorded)
   if key in copies:v.update(availability='copied_exact_bytes',copy=copies[key])
   else:v['availability']='external_not_copied_or_read_by_this_publication'
 summary={'schema':'orbit-poc-native-complete-preflight-publication-v1','status':'preflight03_source_and_supplemental_fixtures_passed','observed_at':a['observed_at'],'independent_audit':pin(data['native-complete-preflight03-independent-terminal-review01.json'][0]),'preflight_result':a['preflight_result'],'source':a['source'],'baseline':a['baseline'],'supplemental':a['supplemental'],'retained_attempts':[{'attempt':'01','status':'failed','scope':'Resolved-path metadata mismatch before command stages; no source or numerical execution.','audit_sha256':AUDITS['01']},{'attempt':'02','status':'failed','scope':'Exact baseline relink recorded; installer rejected a Python symlink before patchers. No candidate compilation or fit.','audit_sha256':AUDITS['02']},{'attempt':'03','status':'passed','scope':'Exact baseline relink independently rehashed, complete source-only installation equality, two compiled supplemental fixtures and exact decoder roundtrip.','audit_sha256':AUDITS['03']}],'scope':{'native_candidate_full_build_completed':False,'candidate_groops_objects_compiled':0,'full_validation_suite_completed_for_this_candidate':False,'native_trajectory_closure_claimed':False,'physical_propagations':0,'v4_fit_attempts':0,'v4_planned_fits':68,'release_ready':False},'original_remote_records':len(raw),'tooling_history':'Prior namespace, interpreter-path, author launch-argument and independent readback/auditor invocation mistakes are retained in their original records. These are not numerical estimator outcomes.','external_scope':'Full source checkouts, objects, binaries, runtime trees and archive payloads remain external. Original byte identities and full source maps are retained in the captured receipts. No external payload is newly read by this publication.'}
 put('summary.json',(json.dumps(summary,indent=2)+'\n').encode());put('external-evidence.json',(json.dumps({'schema':'orbit-poc-explicit-copy-attribution-v1','records':list(refs.values())},indent=2)+'\n').encode())
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Native source and fixture preflight</title><style>body{font:16px system-ui;line-height:1.55;max-width:960px;margin:3rem auto}td,th{padding:.6rem;border-bottom:1px solid #ccc;text-align:left}code{word-break:break-all}</style><h1>Native source and fixture preflight</h1><p><strong>Attempt03 passed its independent source/fixture audit. The v4 benchmark remains at 0/68 fits.</strong> This evidence does not establish a successful full native build, physical trajectory closure, a complete validation suite or release readiness.</p><p>The original <code>25661fd8…</code> executable was reproduced and independently rehashed. A fresh pristine-source installation reproduced all 1,134 expected files: the 1,131-file baseline, four replacements and three additions. Both supplemental C++ fixtures compiled and passed with the pinned compiler flags; the exact-fraction decoder roundtrip passed. No candidate GROOPS translation unit was compiled in this preflight.</p><table><tr><th>Attempt</th><th>Actual outcome</th></tr><tr><td>01</td><td>Stopped before command stages on six resolved-path metadata aliases. Original payload identities were unchanged.</td></tr><tr><td>02</td><td>Baseline relink completed; source installer rejected the declared Python symlink before patchers. The next attempt used the regular executable path with identical bytes.</td></tr><tr><td>03</td><td>Baseline reproduction, complete installed-source equality and supplemental fixtures passed. The independent audit observed all twelve owned identities non-live at 21:32:52 UTC on October 16, 2026.</td></tr></table><p>All 85 exact original compact records and the earlier failure reviews are retained. Compiler objects, checkouts, runtime payloads and binaries remain external with explicit pins. Historical scientific validation and the original 150-attempt v3.1 campaign remain separate.</p><p><a href="summary.json">Scoped results</a> · <a href="evidence/native-complete-preflight03-independent-terminal-review01.json">Independent audit</a> · <a href="external-evidence.json">Copy attribution and external pins</a> · <a href="manifest.json">Exact byte manifest</a></p></html>'''
 put('index.html',page.encode());manifest={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(r['bytes']for r in rows),'scope':'Source installation and supplemental fixture preflight only; no full candidate native build, physical trajectory, complete suite or benchmark fit is inferred.'};(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');return {'output':str(out),'manifest':pin(out/'manifest.json'),'files':len(rows),'bytes':manifest['total_bytes'],'original_records':len(raw),'references':len(refs)}
if __name__=='__main__':
 p=Path(sys.argv[1]);require(sha(p.read_bytes())==sys.argv[2],'Specification changed');print(json.dumps(run(json.loads(p.read_bytes())),indent=2))
