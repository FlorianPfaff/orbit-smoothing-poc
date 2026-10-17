"""Publish exact already-audited native single outcomes; never execute scientific code."""
from pathlib import Path
import base64, collections, hashlib, html, json
B=Path('/mnt/d/orbit-segmented-v4'); C=B/'control'; O=B/'publication-native-compensation-singles01'
def sha(b): return hashlib.sha256(b).hexdigest()
def pin(p):
 b=p.read_bytes(); return dict(path=str(p),sha256=sha(b),bytes=len(b))
def read(n): return json.loads((C/n).read_bytes())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str) and isinstance(v.get('sha256'),str): yield v
  for x in v.values(): yield from walk(x)
 elif isinstance(v,list):
  for x in v: yield from walk(x)
def verified_local(r):
 p=Path(r['path']); assert p.is_relative_to(C) and p.is_file() and not p.is_symlink(),str(p)
 b=p.read_bytes(); assert sha(b)==r['sha256'],str(p)
 if 'bytes' in r: assert len(b)==r['bytes'],str(p)
 assert b'\0' not in b; b.decode('utf-8'); return p
A=C/'nominal-compensation-singles-independent-terminal-review01.json'
assert pin(A)['sha256']=='ca7ce3bfc4e177d288fc92e013424fcdeac9955d95d944bed51150ad56b16cd7'
a=read(A.name); assert a['passed'] and a['fit_attempts']==0 and not a['numerical_fix_verified'] and not a['candidate_release_approved']
assert [x['status']for x in a['outcomes']]==['native_failed','native_completed']
N='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
assert all(x['native']['sha256']==N and x['compact_records_verified']==14 and x['current_owned_nonlive']==7 for x in a['outcomes'])
names=[A.name,Path(__file__).name,'nominal-compensation-native-control-history01.json','validation06-preparation-paused01.json','precision02-source-identity01.json','tangent-compensation-candidate01-independent-review01.json','captured-tangent06-07-independent-terminal-review01.json','nominal-compensation-native-controls-independent-review02.json','nominal-compensation-four-independent-packet-review01.json','tangent-precision-build02-terminal-independent-review01.json','stage_nominal_compensation_checks01.py']
files={C/n for n in names}
# Exact selected audit/control closure. Historical build/source trees remain in their separate publications.
for r in [a['audit_script'],*sum(([x['compact_capture'],x['current_readback']]for x in a['outcomes']),[])]: files.add(verified_local(r))
controls=read('nominal-compensation-native-controls-independent-review02.json')
for r in controls['scripts']+[controls['sealed_controls'],controls['prior_review_preserved'],controls['fixture_tests']['junit'],controls['fixture_tests']['log']]: files.add(verified_local(r))
packet=read('nominal-compensation-four-independent-packet-review01.json')
for r in [packet['audit_script'],packet['readback']]: files.add(verified_local(r))
history=read('nominal-compensation-native-control-history01.json')
for key in ['preserved_failed_collection','corrected_stager','successful_author_tests']: files.add(verified_local(history[key]))
for x in read('precision02-source-identity01.json')['files']: files.add(verified_local(x['source_copy']))
for p in files:
 assert p.is_file() and not p.is_symlink(),str(p)
 b=p.read_bytes(); assert b'\0'not in b; b.decode('utf-8')
O.mkdir(exist_ok=False); rows=[]; values={}; copies={}; remote_copies={}
def put(rel,b,original=None,attribution=None):
 assert not Path(rel).is_absolute() and '..'not in Path(rel).parts
 p=O/rel; p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
 row=dict(path=rel,sha256=sha(b),bytes=len(b))
 if original: row['original']=original
 if attribution: row['attribution']=attribution
 rows.append(row)
 if original: copies[(original['path'],original['sha256'])]=rel
 return rel
def js(rel,v): put(rel,(json.dumps(v,indent=2)+'\n').encode())
for p in sorted(files):
 rel='evidence/'+str(p.relative_to(C)); b=p.read_bytes()
 put(rel,b,pin(p),'Exact local evidence/source bytes. Matching deployed source is not inferred remote acquisition.')
 if p.suffix=='.json': values[rel]=json.loads(b)
rawresults={}; output_arrays=[]; original_count=0
for k in ['01','02']:
 cap=read(f'nominal-compensation-single{k}-terminal-capture01.json'); assert len(cap['files'])==14 and cap['fit_attempts']==0 and not cap['release_evidence']
 output_arrays.extend(cap['external_arrays_and_binaries'])
 for i,r in enumerate(cap['files'],1):
  b=base64.b64decode(r['base64'],validate=True); assert len(b)==r['bytes'] and sha(b)==r['sha256']
  b.decode('utf-8'); assert b'\0'not in b
  orig={x:r[x]for x in ['path','sha256','bytes']}; rel=f'original/single{k}/{i:02d}-{Path(r["path"]).name}'
  put(rel,b,orig,'Exact original remote bytes decoded from audited base64, preserving CR/LF.'); remote_copies[(r['path'],r['sha256'])]=rel; original_count+=1
  if r['path'].endswith('.json'): values[rel]=json.loads(b)
  if r['path'].endswith('/replay/result.json'): rawresults[k]=json.loads(b)
for k,outcome in zip(['01','02'],a['outcomes']):
 r=rawresults[k]
 assert r['status']==outcome['status'] and r['native_evaluations']==1 and r['fit_attempts']==0
 assert r['execution']==outcome['native_execution'] and r['fixed_initial_state_si']==outcome['initial_state']
 assert r['state_epochs']==51840 and r['native']['sha256']==N
 assert r['supplemental_regression']['status']=='passed' and not r['supplemental_regression']['frozen_suite_counts_changed']
 assert r['initialization_criteria']==dict(maximum_iterations=10,position_tolerance_m=2e-6,velocity_tolerance_m_s=3e-9)
assert rawresults['01']['replay_failure_signature']==a['outcomes'][0]['failure']['actual_signature']
assert rawresults['02']['initial_state_error_si']==[0]*6
assert 'relative_residual=1.2851453361637898e-11, tolerance=2e-12, iterations=120' in rawresults['01']['replay_failure_signature']
refs={}
for src,v in values.items():
 for r in walk(v):
  path,h=r['path'],r['sha256']
  if not path.startswith('/') or len(h)!=64: continue
  key=(path,h);e=refs.setdefault(key,dict(path=path,sha256=h,recorded_in=[]))
  if 'bytes'in r:e['bytes']=r['bytes']
  if src not in e['recorded_in']:e['recorded_in'].append(src)
  if key in remote_copies:e.update(availability='copied_exact_remote_record',copy=remote_copies[key])
  elif key in copies:e.update(availability='copied_exact_local_record_or_source',copy=copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
local_sources=collections.defaultdict(list)
for r in rows:
 if r['path'].startswith('evidence/') and Path(r['path']).suffix in {'.py','.h','.cpp'} and r['bytes']:local_sources[r['sha256']].append(r['path'])
for e in refs.values():
 if e['availability'].startswith('external') and e['sha256']in local_sources:e['identical_local_source_bytes']=local_sources[e['sha256']]
summary=dict(schema='orbit-poc-native-compensation-single-outcomes-publication-v1',observed_at=a['observed_at'],status='candidate_not_verified_fixed',native_sha256=N,source_commit=read('precision02-source-identity01.json')['source_commit'],independent_audit=pin(A),outcomes=a['outcomes'],raw_native_results=rawresults,benchmark_attempts=0,full_closures_executed=0,covariance_authorized=False,release_ready=False,validation06='unexecuted_drafts_preserved',original_compact_records=original_count,scope=[
 'The joint audit passed attribution checks; the preparation03 native propagation failed. Audit pass must not be read as numerical success.',
 'Preparation03 fails the unchanged 2e-12 true-residual guard after 120 iterations. Preparation04 succeeds for exactly one preserved iteration03 propagation with the fixed initial state and all 51840 epochs.',
 'Both supplemental analytical fixtures passed under the actual compiler flags. They are separate from the unchanged 106/51 prescribed test counts.',
 'Compensated integration is called for both the mean-force integral and the tangent operator. The observed native RHS norm changes slightly; frozen-capture passes do not establish native closure. This observation does not establish the complete cause of nonconvergence.',
 'Both full-closure attempts remain unexecuted at this audit. Validation06 drafts were not assembled, relocated, staged or launched. These control-state records are not validation outcomes.',
 'No source changes, native execution, Git mutation, PR mutation or new data capture were performed to make this publication.' ])
js('summary.json',summary)
js('external-evidence.json',dict(schema='orbit-poc-explicit-publication-reference-inventory-v1',records=list(refs.values()),scope='Exact original copies, exact local copies and external payloads are distinguished. Native arrays, binaries and packet archives remain outside this package. Identical local source does not imply remote acquisition.'))
js('external-native-outputs.json',dict(schema='orbit-poc-native-single-external-output-inventory-v1',records=output_arrays,scope='The three successful P4 trajectory/tangent arrays and both compiled supplemental fixture binaries remain external, with their original recorded hashes. Input and runtime pins are in external-evidence.json.'))
js('preserved-control-history.json',dict(original_history=pin(C/'nominal-compensation-native-control-history01.json'),failed_collection=history['preserved_failed_collection'],cause=history['cause'],successful_control_tests=49,scope='Collection typo was corrected before any metadata staging or native execution; original failed log and stager01 are copied. Both unused/final packet archives remain external. Earlier incomplete reviewer scope is explicitly preserved and corrected by review02. Validation06 notice is only unexecuted draft state.',validation06_notice=pin(C/'validation06-preparation-paused01.json')))
put('index.html',b'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Native compensation candidate remains unverified</title><style>body{font:16px system-ui;max-width:1000px;margin:3rem auto;line-height:1.55}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.6rem;text-align:left}code{overflow-wrap:anywhere}</style><h1>The native compensation candidate is not a verified fix</h1><p>The actual executable <code>25661fd8...</code> was built from the reviewed compensated-quadrature source. Independent audit at 16:29:32 UTC on October 16, 2026 verified the two outcomes below. <strong>V4 remains at 0/68 benchmark fits; neither full closure was run.</strong></p><table><tr><th>Preserved physical input</th><th>Actual native result</th><th>Bound</th></tr><tr><td>Preparation03 original 72-hour input</td><td>Failed: true residual 1.2851453361637898e-11 after 120 iterations</td><td>Unchanged limit 2e-12; no timeout</td></tr><tr><td>Preparation04 exact iteration03 input</td><td>One propagation completed; fixed initial state unchanged and all 51,840 epochs retained</td><td>No full-closure result</td></tr></table><p>The earlier preparation03 input regresses relative to the preceding wide-affine executable, which had closed that case. The new candidate cannot be considered a correctness resolution. The successful preparation04 propagation does not override the failed retained case.</p><p>The native preparation03 right-hand-side norm is 3747.3316555805213, versus 3747.3316555822867 in the original failure. Compensated integration is used for both mean-force integration and the tangent operator, so it can change the newly generated floating-point system as well as its solution. The earlier two fixed-capture passes remain valid within their recorded scope; they do not certify this native system or full trajectory closure. This observation does not establish the complete cause of nonconvergence.</p><p>Each run passed the separate analytical supplemental fixture under the actual compiler flags. These fixtures do not change the prescribed 106 native and 51 correction test counts. Both full-closure packets remain unexecuted at the audit. Validation06 preparation consists of preserved unexecuted drafts; no new full-suite pass, covariance authorization, speedup or release readiness is claimed.</p><p>The prior stager collection typo and incomplete earlier review scope are preserved alongside the corrected 49-test control review. All 28 compact original records retain exact byte content, including CR/LF and empty logs. The native executable, three successful trajectory/tangent arrays, fixture binaries and packet archives remain external with their hashes.</p><ul><li><a href="summary.json">Machine-readable outcomes and exact native results</a></li><li><a href="evidence/nominal-compensation-singles-independent-terminal-review01.json">Independent outcome audit</a></li><li><a href="original/single01/08-result.json">Failed native replay result</a></li><li><a href="original/single01/10-propagate.log">Exact failure log</a></li><li><a href="original/single02/08-result.json">Successful single-propagation result</a></li><li><a href="evidence/precision02-source-identity01.json">Committed source and supplemental test identity</a></li><li><a href="preserved-control-history.json">Preserved control failures and unexecuted drafts</a></li><li><a href="external-native-outputs.json">External native outputs</a></li><li><a href="external-evidence.json">Complete explicit source/runtime/reference inventory</a></li><li><a href="manifest.json">Publication manifest</a></li></ul></html>''')
m=dict(schema='orbit-poc-compact-publication-manifest-v1',files=rows,file_count=len(rows),total_bytes=sum(r['bytes']for r in rows),scope='Actual native P3 failure and P4 single-propagation pass; neither full closure nor verified fix or release.')
(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
# Verify only this new publication's exact bytes and internal links; no scientific rerun.
import re
assert {str(p.relative_to(O))for p in O.rglob('*')if p.is_file()}=={r['path']for r in rows}|{'manifest.json'}
for r in rows:
 p=O/r['path'];assert pin(p)['sha256']==r['sha256']and p.stat().st_size==r['bytes'];p.read_bytes().decode('utf-8')
for href in re.findall('href="([^"]+)"',(O/'index.html').read_text()):assert (O/href).is_file(),href
print(json.dumps(dict(output=str(O),manifest=pin(O/'manifest.json'),file_count=len(rows),total_bytes=m['total_bytes'],original_records=original_count,reference_count=len(refs)),indent=2))
