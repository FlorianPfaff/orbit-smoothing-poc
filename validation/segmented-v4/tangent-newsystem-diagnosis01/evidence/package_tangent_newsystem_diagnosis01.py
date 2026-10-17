from pathlib import Path
import json,hashlib,base64,collections,html
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-tangent-newsystem-diagnosis01'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def load(n):return json.loads((C/n).read_text())
AUDITS={'tangent-capture-build05-independent-terminal-review01.json':'dc549c1013d8810f9068b6d3f65a6b104e4f738d2317b6fbd9978d5b9657d435','nominal-tangent-capture03-independent-terminal-review01.json':'59634cafaaf9979e3cf45eb8413dfd41113211a31134e0677a9a5f76cafd556d'}
for n,h in AUDITS.items():assert pin(C/n)['sha256']==h and load(n)['passed']
actual=load('nominal-tangent-capture03-independent-terminal-review01.json');build=load('tangent-capture-build05-independent-terminal-review01.json');capture=load('nominal-tangent-capture03-terminal-capture01.json')
assert pin(C/'nominal-tangent-capture03-terminal-capture01.json')['sha256']==actual['capture_readback']['sha256']
names=list(AUDITS)+[
 'tangent-capture-build04-independent-code-review01.json','tangent-capture-build05-independent-packet-review01.json','nominal-tangent-capture06-independent-packet-review01.json','tangent72-diagnostic06-independent-review01.json',
 'tangent-capture05-control-attempt-ledger01.json','tangent-capture-build04-staging01.json','tangent-capture-build04-staging01.stderr.log',
 'tangent-capture-build05-staging01.json','tangent-capture-build05-launch-readiness01.json','tangent-capture-build05-launch01.json','tangent-capture-build05-result.json',
 'nominal-tangent-capture06-staging01.json','nominal-tangent-capture03-launch-readiness01.json','nominal-tangent-capture03-launch01.json',
 'nominal-tangent-capture03-terminal-capture01.json','nominal-tangent-capture03-terminal-capture01.stderr.log','nominal-tangent-capture03-standalone-trace.jsonl','nominal-tangent-capture03-trace-summary01.json',
 'build_tangent_capture04.py','run_tangent_capture_build04.py','test_tangent_capture_build04.py','stage_tangent_capture_build04.py','stage_tangent_capture_build05.py',
 'install_tangent_capture_build04_packet.py','install_tangent_capture_build05_packet.py','tangent-capture-build04-install01.json','tangent-capture-build04-install01.stderr.log','tangent-capture-build05-install01.json',
 'tangent-capture-build04-packet/packet-files.json','tangent-capture-build05-packet/packet-files.json',Path(__file__).name]
# Include only pinned compact local dependencies of current audits and the explicit failure ledger.
files={C/n for n in names};pending=list(files)
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str) and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
while pending:
 p=pending.pop()
 assert p.is_file() and not p.is_symlink(),str(p)
 if p.suffix!='.json':continue
 try:d=json.loads(p.read_text())
 except json.JSONDecodeError:continue
 for r in walk(d):
  q=Path(r['path'])
  if q.is_relative_to(C) and q.is_file() and not q.is_symlink() and q.suffix not in {'.gz','.bin','.so','.pyc'}:
   if q.stat().st_size>1500000:continue
   b=q.read_bytes();assert sha(b)==r['sha256'],str(q)
   if 'bytes'in r:assert len(b)==r['bytes'],str(q)
   if q not in files:files.add(q);pending.append(q)
for sub in ['tangent72-diagnostic06','tangent-capture-build05-packet/control']:
 for p in (C/sub).rglob('*'):
  if p.is_file() and '__pycache__'not in p.parts and p.suffix in {'.py','.cpp','.h','.json','.txt'}:files.add(p)
O.mkdir(exist_ok=False);rows=[];source_data={};remote_copies={}
def put(rel,b,original=None,attribution=None):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
 r={'path':rel,'sha256':sha(b),'bytes':len(b)}
 if original:r['original']=original
 if attribution:r['attribution']=attribution
 rows.append(r)
def js(rel,d):put(rel,(json.dumps(d,indent=2)+'\n').encode())
for p in sorted(files):
 rel='evidence/'+str(p.relative_to(C));b=p.read_bytes();put(rel,b,pin(p),'Exact local evidence/source bytes. Matching deployed source bytes alone do not imply remote acquisition.')
 if p.suffix in {'.json','.jsonl'}:
  try:source_data[str(p)]=json.loads(b)
  except json.JSONDecodeError:pass
for i,f in enumerate(capture['files'],1):
 b=base64.b64decode(f['base64'],validate=True);assert len(b)==f['bytes']and sha(b)==f['sha256'];orig={k:f[k]for k in ('path','sha256','bytes')};rel=f'original/{i:02d}-{Path(f["path"]).name}'
 put(rel,b,orig,'Exact remote bytes decoded from the independently audited base64 capture, including original CR/LF.');remote_copies[(f['path'],f['sha256'])]=rel
# The separately transferred actual build result is also an explicitly attributed remote copy.
result=build['result'];assert pin(C/'tangent-capture-build05-result.json')['sha256']==result['sha256']
remote_copies[(result['path'],result['sha256'])]='evidence/tangent-capture-build05-result.json'
# Preserve recorded remote input/output pins without claiming unavailable payload copies.
external={}
for source,v in source_data.items():
 for r in walk(v):
  path=r['path'];h=r['sha256']
  if not path.startswith('/')or path.startswith(str(C)+'/')or len(h)!=64:continue
  key=(path,h);e=external.setdefault(key,{'path':path,'sha256':h,'recorded_in':[]})
  if 'bytes'in r:e['bytes']=r['bytes']
  if source not in e['recorded_in']:e['recorded_in'].append(source)
  if key in remote_copies:e.update(availability='copied_exact_remote_record',copy=remote_copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
# Some diagnostic source files are available as local identical bytes; label explicitly, never as remote captures.
byhash=collections.defaultdict(list)
for r in rows:
 if r['path'].startswith('evidence/')and Path(r['path']).suffix in {'.py','.cpp','.h','.txt'}and r['bytes']:
  byhash[r['sha256']].append(r['path'])
for e in external.values():
 if e['availability'].startswith('external')and e['sha256']in byhash:e['identical_local_source_bytes']=byhash[e['sha256']]
trace=[json.loads(x)for x in (C/'nominal-tangent-capture03-standalone-trace.jsonl').read_text().splitlines()]
assert len(trace)==219;counts=dict(collections.Counter(x['kind']for x in trace));assert counts==actual['trace_summary']['counts']
truth=[x for x in trace if x['kind']=='true_residual'];best=min(truth,key=lambda x:x['native_relative_residual']);assert best==actual['trace_summary']['best_native']
cycles=dict(collections.Counter(str(b['iteration']-a['iteration'])for a,b in zip(truth,truth[1:])));assert cycles==actual['trace_summary']['cycle_lengths']
quad=actual['trace_summary']['best_native_quad'];assert quad['relative_residual_native_velocity_conversion']>2e-12
summary={'schema':'orbit-poc-v4-new-system-tangent-diagnosis-publication-v1','status':'diagnosis_verified_solver_still_failed','observed_at':actual['observed_at'],'original_failure':actual['exact_original_failure_signature'],'build':{'baseline_relinked_sha256':load('tangent-capture-build05-result.json')['baseline_relinked_sha256'],'capture_native':build['native'],'reader':build['reader'],'reused_objects':610,'original_objects':611,'original_link_input_pins':637,'scope':build['scope']},'trace_summary':actual['trace_summary'],'trace_rows':219,'update_cycles':94,'original_residual_threshold':2e-12,'actual_capture':actual['actual_capture'],'benchmark_attempts':0,'covariance_authorized':False,'release_ready':False,'pending_candidate_outcomes_included':False,'scope':['The exact new failed third nominal propagation was reproduced; standalone final residual agrees with the native failure.','The best observed native true-residual iterate and final iterate both fail the original threshold under the independent 113-bit residual computation. Best means lowest observed native true residual, not a search over all states.','Ninety-four short update cycles were observed: 71 one-step, 22 two-step and one five-step. This motivates further diagnostics; it does not establish a cause or correction.','Capture instrumentation and telemetry preserve the production tangent algorithm and thresholds. The unmodified baseline relinks exactly to eb41 before the diagnostic hook is applied.','Metadata staging04 and author/reviewer tooling failures are retained separately from actual build05 and telemetry03 outcomes.','No full trajectory closure, accepted covariance, benchmark result, production correction or release claim. Pending candidate07 outcomes are excluded.'],'audits':{n:pin(C/n)for n in AUDITS},'external_reference_count':len(external)}
js('summary.json',summary);js('external-evidence.json',{'schema':'orbit-poc-diagnosis-source-output-inventory-v1','records':list(external.values()),'scope':'Original paths and hashes retained; explicit copies are distinguished from external payloads and identical local source bytes. No new remote or numerical read was performed by this publication.'})
put('index.html',('''<!doctype html><html lang="en"><meta charset="utf-8"><title>New 72-hour tangent failure diagnosis</title><style>body{font:16px system-ui;max-width:980px;margin:3rem auto;line-height:1.5}code{word-break:break-all}table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #bbb;text-align:left}</style><h1>The new 72-hour tangent failure is reproduced</h1><p>The failed third nominal propagation from preparation04 was reproduced with diagnostic instrumentation. The standalone captured-system solve returned the exact native final residual <strong>5.2053902058798312e-12</strong> after 120 iterations. The original acceptance threshold remains <strong>2e-12</strong>.</p><table><tr><th>Saved original double iterate</th><th>Native true residual</th><th>Independent 113-bit residual</th></tr><tr><td>Best observed native true residual, iteration91</td><td>2.458626682382519e-12</td><td>2.417945997329731e-12</td></tr><tr><td>Final, iteration120</td><td>5.2053902058798312e-12</td><td>5.436097612732665e-12</td></tr></table><p>Both saved iterates still fail under the higher-precision residual calculation. These values use the original native velocity conversion; the alternative exact conversion is recorded separately. The projected residual remains distinct from the true residual and does not certify acceptance.</p><p>The 219-row trace contains 94 update cycles: 71 one-step, 22 two-step and one five-step. These observations motivate further diagnostic experiments; they do not establish a production correction or the cause of stagnation.</p><p>The diagnostic build first reproduced the corrected <code>eb41fabb…</code> executable exactly, retaining610 of611 original objects and verifying637 link-input pins. Only the capture hook was then compiled. The production tangent arithmetic and stopping threshold were unchanged. Owned cleanup and exact replay attribution passed independent audit.</p><p><strong>0/68 benchmark fits. No full native trajectory closure, covariance authorization, production fix or release readiness is claimed.</strong> Pending candidate07 outcomes are excluded from this frozen diagnosis snapshot.</p><ul><li><a href="evidence/nominal-tangent-capture03-independent-terminal-review01.json">Actual replay/113-bit independent audit</a></li><li><a href="evidence/tangent-capture-build05-independent-terminal-review01.json">Actual diagnostic build audit</a></li><li><a href="evidence/tangent72-diagnostic06-independent-review01.json">Telemetry-only source review</a></li><li><a href="evidence/nominal-tangent-capture03-standalone-trace.jsonl">Exact219-row trace</a></li><li><a href="evidence/tangent-capture05-control-attempt-ledger01.json">Preserved control and metadata-staging failures</a></li><li><a href="summary.json">Machine-readable scope and results</a></li><li><a href="external-evidence.json">Source/input/output pins and explicit copy attribution</a></li><li><a href="manifest.json">Publication byte manifest</a></li></ul><p>The27,786,112-byte captured system remains outside Git with its exact hash. Sixteen compact original records are copied as exact base64-decoded bytes; source, control and build evidence retain their original provenance.</p></html>''').encode())
m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Actual new-system diagnostic replay still fails unchanged threshold; no correction or readiness claim.'};(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps({'output':str(O),'manifest':pin(O/'manifest.json'),'file_count':len(rows),'total_bytes':m['total_bytes'],'original_records':len(remote_copies),'external_references':len(external)},indent=2))
