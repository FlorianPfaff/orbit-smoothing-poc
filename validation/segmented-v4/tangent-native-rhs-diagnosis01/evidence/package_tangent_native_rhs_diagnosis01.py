"""Exact existing telemetry04/capture06 evidence; publication only, no numerical runs."""
from pathlib import Path
import base64,collections,hashlib,json,re
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-tangent-native-rhs-diagnosis01'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return dict(path=str(p),sha256=sha(b),bytes=len(b))
def load(n):return json.loads((C/n).read_bytes())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
def check(r):
 p=Path(r['path']);b=p.read_bytes();assert not p.is_symlink() and p.is_relative_to(C) and sha(b)==r['sha256'],str(p)
 if 'bytes'in r:assert len(b)==r['bytes']
 b.decode();assert b'\0'not in b;return p
A=C/'nominal-tangent-capture04-independent-terminal-review01.json'
assert pin(A)['sha256']=='916466d68b82f80980978488ce46b280867f86540b775a2008eff119c1a7fa91'
a=load(A.name);assert a['passed'] and not a['candidate_verified_fixed'] and a['fit_attempts']==0
names=[A.name,Path(__file__).name,'audit_nominal_tangent_capture04_terminal01.py','nominal-tangent-capture04-result.json','nominal-tangent-capture04-standalone-trace.jsonl','compare_tangent_captures01.py','compare-tangent-captures01-result.json','compare-tangent-captures01.stderr.log','nominal-tangent-current-capture03-author-control-note.json','nominal-compensation-native-control-history01.json','nominal-compensation-native-author-tests02.log','nominal-compensation-native-author-tests03.log','nominal-compensation-singles-independent-terminal-review01.json','tangent-capture-build06-result.json','tangent-capture-build06-staging01.json','tangent-capture-build06-launch01.json','tangent-capture-build06-independent-packet-review01.json','tangent-capture-build04-independent-code-review01.json']
files={C/n for n in names}
for key in ['raw_capture','readback','build_audit','control_audit','source_audit']:files.add(check(a[key]))
build=load(a['build_audit']['path'].split('/')[-1]);files.add(check(build['readback']))
controls=load(a['control_audit']['path'].split('/')[-1])
for r in controls['scripts']+[controls['fixtures']['junit'],controls['fixtures']['log'],controls['sealed_controls']]:files.add(check(r))
packet=load('tangent-capture-build06-independent-packet-review01.json')
for r in [packet['readback'],packet['stager']]:files.add(check(r))
for sub in ['tangent72-diagnostic09','tangent-capture-build06-packet/control']:
 for p in(C/sub).rglob('*'):
  if p.is_file()and'__pycache__'not in p.parts and p.suffix in {'.py','.cpp','.h','.json','.txt'}:files.add(p)
for p in files:
 assert p.is_file()and not p.is_symlink();b=p.read_bytes();b.decode();assert b'\0'not in b
O.mkdir(exist_ok=False);rows=[];values={};copies={};remote_copies={}
def put(rel,b,original=None,attribution=None):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
 r=dict(path=rel,sha256=sha(b),bytes=len(b))
 if original:r['original']=original;copies[(original['path'],original['sha256'])]=rel
 if attribution:r['attribution']=attribution
 rows.append(r)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
for p in sorted(files):
 rel='evidence/'+str(p.relative_to(C));b=p.read_bytes();put(rel,b,pin(p),'Exact local evidence/source bytes; equivalent deployed source is not inferred remote acquisition.')
 if p.suffix=='.json':values[rel]=json.loads(b)
cap=load(a['raw_capture']['path'].split('/')[-1]);assert len(cap['files'])==16
for i,r in enumerate(cap['files'],1):
 b=base64.b64decode(r['base64'],validate=True);assert len(b)==r['bytes']and sha(b)==r['sha256'];b.decode()
 rel=f'original/telemetry04/{i:02d}-{Path(r["path"]).name}';orig={x:r[x]for x in ['path','sha256','bytes']}
 put(rel,b,orig,'Exact original remote bytes decoded from audited base64, preserving CR/LF.');remote_copies[(r['path'],r['sha256'])]=rel
 if r['path'].endswith('.json'):values[rel]=json.loads(b)
# This previously transferred build result is an explicitly identified remote copy, not a hash-only inference.
br=build['build_result'];local=C/'tangent-capture-build06-result.json'
assert pin(local)['sha256']==br['sha256']and pin(local)['bytes']==br['bytes'];remote_copies[(br['path'],br['sha256'])]='evidence/tangent-capture-build06-result.json'
result=load('nominal-tangent-capture04-result.json');trace=[json.loads(x)for x in(C/'nominal-tangent-capture04-standalone-trace.jsonl').read_text().splitlines()];compare=load('compare-tangent-captures01-result.json')
assert result['status']=='native_failed'and result['exact_failure_reproduced']and result['algorithm_delta']is None and result['fit_attempts']==0 and result['native_evaluations']==1
assert result['original_failure_signature']==result['replay_failure_signature']
assert result['execution']['returncode']==1 and not result['execution']['timed_out']
assert len(trace)==a['trace_rows']==result['standalone']['record_count']==209
assert sha((C/'nominal-tangent-capture04-standalone-trace.jsonl').read_bytes())==result['standalone']['trace']['sha256']
assert [x for x in trace if x['kind']=='terminal']==[result['standalone']['terminal']]
assert [x for x in trace if x['kind']=='best_native_iterate_quad_residual']==[a['best_observed_native_iterate']]
assert [x for x in trace if x['kind']=='quad_residual']==[a['final_113bit']]
assert result['standalone']['input']['tolerance']==2e-12 and result['standalone']['input']['maximum_iterations']==120 and result['standalone']['input']['restart']==20
assert a['best_observed_native_iterate']['relative_residual_native_velocity_conversion']>2e-12 and a['final_113bit']['relative_residual_native_velocity_conversion']>2e-12
assert compare['operator_prefix_byte_identical']and compare['operator_prefix_bytes']==a['operator_prefix_comparison']['identical_operator_bytes']==25297792
assert compare['header_jacobians_quadrature_old_sha256']==compare['header_jacobians_quadrature_new_sha256']
assert [x['sha256']for x in compare['inputs']]==[a['operator_prefix_comparison']['old_sha256'],a['operator_prefix_comparison']['new_sha256']]
assert compare['position_rhs']['changed_values']>0 and compare['scaled_velocity_rhs']['changed_values']>0 and compare['scientific_runs']==0
projected=[x for x in trace if x['kind']=='projected_residual'];true=[x for x in trace if x['kind']=='true_residual'and not x['final']and x['iteration']>0]
assert len(projected)==120
prev=0;cycles=[]
for x in true:cycles.append(x['iteration']-prev);prev=x['iteration']
assert {str(k):v for k,v in collections.Counter(cycles).items()}==a['cycle_counts']
refs={}
for src,v in values.items():
 for r in walk(v):
  path,h=r['path'],r['sha256']
  if not path.startswith('/')or len(h)!=64:continue
  key=(path,h);e=refs.setdefault(key,dict(path=path,sha256=h,recorded_in=[]))
  if 'bytes'in r:e['bytes']=r['bytes']
  if src not in e['recorded_in']:e['recorded_in'].append(src)
  if key in remote_copies:e.update(availability='copied_exact_remote_record',copy=remote_copies[key])
  elif key in copies:e.update(availability='copied_exact_local_record_or_source',copy=copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
local_sources=collections.defaultdict(list)
for r in rows:
 if r['path'].startswith('evidence/')and Path(r['path']).suffix in {'.py','.cpp','.h'}and r['bytes']:local_sources[r['sha256']].append(r['path'])
for e in refs.values():
 if e['availability'].startswith('external')and e['sha256']in local_sources:e['identical_local_source_bytes']=local_sources[e['sha256']]
summary=dict(schema='orbit-poc-native-rhs-diagnosis-publication-v1',status='native_failure_reproduced_rhs_only_capture_difference',audit=pin(A),build_audit=pin(Path(a['build_audit']['path'])),baseline_native_sha256=build['baseline_native_sha256'],capture_native=build['capture_native'],reader=build['reader'],outcome=result,trace_rows=len(trace),cycles=a['cycle_counts'],best_observed_native_iterate=a['best_observed_native_iterate'],final_113bit=a['final_113bit'],capture_comparison=compare,guard=a['unchanged_guard'],fit_attempts=0,native_correction_verified=False,full_closure_claimed=False,covariance_authorized=False,release_ready=False,scope=[
 'Capture06 is a telemetry-only build from actual candidate25661. Its capture insertion changes only the diagnostic hook; the standalone reader is separately instrumented. The reproduced native failure is distinct from the read-only captured-data comparison.',
 'The original and new captures have identical stored header, Jacobian and quadrature prefix bytes. Only their RHS data differs. This comparison does not claim identical floating-point integration algorithms across historical executables.',
 'The best observed iterate is selected by the native true residual, then checked independently at 113 bits. It is not a claim of the globally best solution or every possible higher-precision iterate.',
 'Both the best observed native iterate and final iterate exceed the unchanged2e-12 guard in the independent113-bit check. No numerical-floor waiver or covariance authorization follows.',
 'The exact source/control failures and original raw records are retained. This package performs no new propagation, fit, remote capture, source change, Git write or PR mutation.',
 'Later RHS-variant experiments are excluded; their outcomes are not part of this frozen diagnosis.' ])
js('summary.json',summary)
js('external-evidence.json',dict(schema='orbit-poc-explicit-publication-reference-inventory-v1',records=list(refs.values()),scope='Exact remote copies are explicit; identical local source bytes do not imply acquisition. The two large captured systems, native/reader binaries, original source datasets and packet archives remain external.'))
js('external-captures.json',dict(schema='orbit-poc-external-captured-systems-v1',records=[dict(**x,bytes=27786112)for x in compare['inputs']],scope='Both 27,786,112-byte captured systems remain outside Git. Their exact pins and the read-only comparison source/result preserve attribution.'))
js('preserved-control-history.json',dict(current_authoring_note=pin(C/'nominal-tangent-current-capture03-author-control-note.json'),note_scope='Local filename lookup error recorded in the original note; not represented as a separately captured raw traceback or remote failure.',prior_collection_history=pin(C/'nominal-compensation-native-control-history01.json'),prior_failed_log=pin(C/'nominal-compensation-native-author-tests02.log'),prior_corrected_log=pin(C/'nominal-compensation-native-author-tests03.log'),scope='Both authoring failures preceded remote staging/native execution and remain separate from actual native numerical failures.'))
put('index.html',b'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Native failure and changed right-hand side</title><style>body{font:16px system-ui;max-width:1000px;margin:3rem auto;line-height:1.55}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.6rem;text-align:left}code{overflow-wrap:anywhere}</style><h1>Native failure reproduced; captured RHS changed</h1><p>The telemetry-only build reproduces the actual <code>25661fd8...</code> candidate failure on the preserved preparation03 input. Its separately instrumented reader reproduces the same final true residual. <strong>The candidate is not verified fixed. V4 remains at 0/68 benchmark fits.</strong></p><table><tr><th>Observed iterate</th><th>Native true residual</th><th>Independent 113-bit residual</th></tr><tr><td>Best observed native residual, step 5</td><td>2.0663992186504604e-12</td><td>2.064444255359571e-12</td></tr><tr><td>Final, step 120</td><td>1.2851453361637898e-11</td><td>1.284955101674569e-11</td></tr></table><p>Both independent checks still exceed the unchanged 2e-12 limit. The best iterate was selected using the observed native true residual; this does not claim a global optimum or test every possible higher-precision iterate. The 209-row trace contains 120 projected steps and 84 update cycles: one five-step cycle, 32 two-step cycles and 51 one-step cycles. Restart capacity remains 20. No numerical-floor exception is claimed.</p><h2>Exact captured-data comparison</h2><p>The old <code>b1fd97fe...</code> and new <code>b1020102...</code> captures contain exactly the same 25,297,792-byte prefix: stored header, Jacobians and quadrature. Their right-hand-side arrays differ. This is an identity statement about the stored data, not a claim that historical executable arithmetic is identical.</p><table><tr><th>RHS component</th><th>Changed values</th><th>Maximum absolute difference</th><th>Difference norm</th></tr><tr><td>Position</td><td>34,090</td><td>1.862645149230957e-9</td><td>9.46872678551124e-8</td></tr><tr><td>Scaled velocity</td><td>53,228</td><td>1.1368683772161603e-10</td><td>1.4047108215248954e-9</td></tr></table><p>Compensated integration also participates in generating the physical RHS. Thus the earlier success on a fixed capture did not certify the newly generated native system. The comparison identifies the changed input data; it does not establish the complete mechanism of residual stagnation or a robust correction.</p><h2>Attribution and limits</h2><p>Capture06 baseline-relinked to the exact candidate25661 and reused 610 objects; its only modified native header adds capture telemetry. The reader binary matches the reviewed compensated reader. Three reader fixtures and eight nested checks passed before the actual failed propagation. Nine owned telemetry identities were verified non-live. No timeout, full trajectory closure, new full-suite pass, covariance approval or release readiness is claimed.</p><p>The 16 original compact telemetry records are preserved byte-for-byte, including logs and CR/LF. The actual build result, source, flags, controls and local authoring failures are included. Both 27,786,112-byte captures and compiled binaries remain external. Later RHS-variant experiments are deliberately outside this frozen report.</p><ul><li><a href="summary.json">Machine-readable native and diagnostic outcomes</a></li><li><a href="evidence/nominal-tangent-capture04-independent-terminal-review01.json">Independent terminal audit</a></li><li><a href="evidence/tangent-capture-build06-independent-terminal-review01.json">Telemetry build audit</a></li><li><a href="original/telemetry04/09-result.json">Exact native/reader result</a></li><li><a href="original/telemetry04/10-standalone-trace.jsonl">Complete exact trace</a></li><li><a href="original/telemetry04/13-propagate.log">Exact native failure log</a></li><li><a href="evidence/compare-tangent-captures01-result.json">Read-only capture comparison</a></li><li><a href="evidence/compare_tangent_captures01.py">Comparison source</a></li><li><a href="external-captures.json">External capture pins</a></li><li><a href="external-evidence.json">Source/runtime/reference inventory</a></li><li><a href="preserved-control-history.json">Preserved authoring failures</a></li><li><a href="manifest.json">Publication manifest</a></li></ul></html>''')
m=dict(schema='orbit-poc-compact-publication-manifest-v1',files=rows,file_count=len(rows),total_bytes=sum(x['bytes']for x in rows),scope='Actual telemetry04 native failure, capture06 provenance and read-only RHS-only captured-data comparison; no correction/closure/fit/release claim.')
(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
assert {str(p.relative_to(O))for p in O.rglob('*')if p.is_file()}=={r['path']for r in rows}|{'manifest.json'}
for r in rows:
 b=(O/r['path']).read_bytes();assert len(b)==r['bytes']and sha(b)==r['sha256'];b.decode()
for href in re.findall('href="([^"]+)"',(O/'index.html').read_text()):assert(O/href).is_file(),href
print(json.dumps(dict(output=str(O),manifest=pin(O/'manifest.json'),file_count=len(rows),total_bytes=m['total_bytes'],original_records=16,reference_count=len(refs)),indent=2))
