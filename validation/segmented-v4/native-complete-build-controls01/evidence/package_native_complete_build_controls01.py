"""Exact retained build-control failure, passed preflight04 and dated compiler observation."""
from pathlib import Path
import base64,hashlib,json,sys
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=C.parent
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
 need(set(spec)=={'schema','output','sources'},'Unknown fields');need(spec['schema']=='orbit-poc-complete-build-controls-publication-spec-v1','Wrong schema');files={};docs={};originals={}
 for r in spec['sources']:
  p=Path(r['path']);need(p.parent==C and p.is_file()and not p.is_symlink()and pin(p)==r,'Changed exact source');files[p.name]=(p,p.read_bytes())
  if p.suffix=='.json':
   try:docs[p.name]=json.loads(p.read_bytes())
   except json.JSONDecodeError:pass
 failure=docs['native-complete-build01-independent-failure-review01.json'];audit=docs['native-complete-preflight04-independent-terminal-review01.json'];live=docs['native-complete-build02-live01.json']
 need(failure['passed']and failure['failure']['candidate_groops_objects']==0 and failure['failure']['error']=="ValueError('Configured toolchain differs: CMAKE_MAKE_PROGRAM')",'Wrong retained failure')
 need(audit['passed']and audit['original_ninja_identity_verified']and audit['source']['installed_files']==1134 and audit['supplemental']['exact_fraction_roundtrip'],'Missing actual preflight04')
 need(live['pipeline']['status']=='running'and live['pipeline']['fit_attempts']==0 and live['launch']['launch_committed']and live['driver']['pid']==live['launch']['driver_process']['pid']and live['driver']['start_ticks']==live['launch']['driver_process']['start_ticks'],'Missing actual build ownership')
 need(live['observed_at']=='2026-10-16T21:50:52.960784+00:00'and live['locks']and any('[45/633]'in line for r in live['logs']for line in r['last_lines']),'Wrong dated compiler observation')
 need(any('cc1plus'in' '.join(p.get('argv',[]))and p['affinity']==['Cpus_allowed_list:\t24']for p in live['processes']),'Actual compiler/CPU24 absent')
 for name,expected,tag in [('native-complete-build01-terminal-capture01.json','9ba0978ac144a6edda911dc74901ca720e3befedb8734ceec6122b3f7bd4682f','failed-build01'),('native-complete-preflight04-terminal-capture01.json','da0baa2ba2e3e1717127f92c6a30c7a553074ba31e840995344a8d3052ae298a','preflight04')]:
  need(sha(files[name][1])==expected,'Wrong raw capture');d=docs[name];need(len(d['files'])=={'failed-build01':26,'preflight04':44}[tag],'Wrong original count')
  for r in d['files']:
   b=base64.b64decode(r['base64'],validate=True);need(sha(b)==r['sha256']and len(b)==r['bytes'],'Raw bytes differ');rel=Path(r['path']).relative_to(d['root']);need('..'not in rel.parts,'Unsafe recorded path');key=(r['path'],r['sha256']);need(key not in originals,'Duplicate original');originals[key]=(f'original/{tag}/{rel}',r,b)
 out=Path(spec['output']);need(out==BASE/'publication-native-complete-build-controls01'and not out.exists(),'Fresh output required');out.mkdir();rows=[];copies={};documents=[]
 def put(rel,b,source=None,attr=None):
  p=out/rel;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb')as f:f.write(b)
  r={'path':rel,'sha256':sha(b),'bytes':len(b)}
  if source:r['original']=source;copies[(source['path'],source['sha256'])]=rel
  if attr:r['attribution']=attr
  rows.append(r)
 for n,(p,b)in sorted(files.items()):
  put('evidence/'+n,b,pin(p),'Exact local source or recorded evidence. Remote acquisition is identified separately.')
  if n in docs:documents.append((str(p),docs[n]))
 for key,(rel,r,b)in sorted(originals.items()):
  put(rel,b,{k:r[k]for k in ['path','sha256','bytes']},'Exact original remote bytes decoded from the pinned base64 capture.')
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
 summary={'schema':'orbit-poc-native-complete-build-controls-publication-v1','observed_at':live['observed_at'],'status':'build02_actual_compiler_observed_no_terminal_result','failed_build01':{'audit':pin(files['native-complete-build01-independent-failure-review01.json'][0]),'error':failure['failure'],'measured_causes':failure['measured_causes'],'cleanup':failure['cleanup']},'passed_preflight04':{'audit':pin(files['native-complete-preflight04-independent-terminal-review01.json'][0]),'source':audit['source'],'supplemental':audit['supplemental'],'original_ninja_identity_verified':True,'scope':audit['scope']},'actual_build02':{'launch_created_at':live['launch']['created_at'],'driver':live['launch']['driver_process'],'plan_sha256':live['pipeline']['plan']['sha256'],'execution_sha256':live['launch']['execution_sha256'],'observed_build_step':45,'planned_ninja_steps':633,'candidate_translation_units_expected':611,'compiler_cpu':24,'pinned_toolchain':'GCC 15.3','completion_claimed':False},'scope':{'candidate_executable_available':False,'full_native_closure_passed':False,'new_complete_correctness_suite_passed':False,'v4_fit_attempts':0,'v4_planned_fits':68,'release_ready':False},'raw_original_records':70,'preservation':'Retain the original Ninja/cache metadata failure, its failed live-probe observation, original namespace/Python path failures referenced by recovery index, exact corrected preflight04 and all control versions. No numerical model or tolerance change is inferred.','dated_observation_limit':'Current build liveness and later progress are not inferred from this historical observation.'}
 put('summary.json',(json.dumps(summary,indent=2)+'\n').encode());put('external-evidence.json',(json.dumps({'schema':'orbit-poc-explicit-copy-attribution-v1','records':list(refs.values())},indent=2)+'\n').encode())
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Complete native build: control recovery and launch</title><style>body{font:16px system-ui;line-height:1.55;max-width:950px;margin:3rem auto}code{word-break:break-all}</style><h1>Complete native build: retained failure and actual compilation</h1><p><strong>The new full build was actually compiling at 21:50:52 UTC on October 16, 2026. No new executable, native closure, complete correctness suite or v4 fit result is claimed.</strong> The benchmark remains at 0/68 fits.</p><p>Build01 completed the public source installers and CMake configuration, then stopped before candidate GROOPS compilation because its guard pinned the wrong Ninja identity. The configured Ninja1.13.2 was the original cached tool; the erroneous control pin named Ninja1.10.1. The original project enables CXX and Fortran, with no C compiler cache entry. These measured metadata facts and every failed record remain preserved; CMake's own compiler probes are not mislabeled as zero compilation of any kind.</p><p>Fresh preflight04 independently passed full 1,134-file source equivalence, exact baseline relink, original Ninja identity, both compiled supplemental fixtures and exact fraction decoding. All thirteen owned identities were non-live in its independent terminal observation. This remains a source/fixture check, separate from the full candidate build.</p><p>Build02 launched at 21:50:21 UTC. Its dated observation records the admitted driver, shared lock, successful configure, pinned GCC15.3 compiler on CPU24, empty compiler stderr and build step45/633. The build is configured to compile all611 translation units in a fresh tree; neither completion nor later liveness is inferred. Numerical source and limits were preserved through the control correction.</p><p><a href="summary.json">Scoped results and observation</a> · <a href="evidence/native-complete-build01-independent-failure-review01.json">Failure audit</a> · <a href="evidence/native-complete-preflight04-independent-terminal-review01.json">Preflight04 audit</a> · <a href="external-evidence.json">External/copy attribution</a> · <a href="manifest.json">Exact byte manifest</a></p></html>'''
 for a,b in [('Ninja1.','Ninja 1.'),('GCC15.3','GCC 15.3'),('CPU24','CPU24'),('step45/633','step 45/633'),('all611','all 611')]:page=page.replace(a,b)
 put('index.html',page.encode());m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Exact build-control failure, audited source preflight and dated actual compiler observation only; no completed build or scientific outcomes.'};(out/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');return {'output':str(out),'manifest':pin(out/'manifest.json'),'payloads':len(rows),'bytes':m['total_bytes'],'raw_originals':len(originals),'references':len(refs)}
if __name__=='__main__':
 p=Path(sys.argv[1]);need(sha(p.read_bytes())==sys.argv[2],'Changed specification');print(json.dumps(run(json.loads(p.read_bytes())),indent=2))
