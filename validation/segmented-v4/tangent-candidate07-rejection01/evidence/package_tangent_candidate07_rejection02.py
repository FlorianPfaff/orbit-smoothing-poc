from pathlib import Path
import json,hashlib,base64,collections
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-tangent-candidate07-rejection02'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def load(n):return json.loads((C/n).read_text())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
joint=load('captured-tangent03-04-independent-terminal-review01.json');baseline=load('captured-tangent05-independent-terminal-review01.json')
assert joint['passed']and baseline['passed']and not joint['promotion_approved']and not baseline['production_promotion_approved']
assert pin(C/'captured-tangent03-04-independent-terminal-review01.json')['sha256'].startswith('fa816036')
assert pin(C/'captured-tangent05-independent-terminal-review01.json')['sha256'].startswith('17f51269')
names=['captured-tangent03-04-independent-terminal-review01.json','captured-tangent05-independent-terminal-review01.json','tangent72-diagnostic07-independent-review01.json','captured-tangent02-independent-code-review01.json','tangent72-diagnostic06-independent-review01.json','captured-tangent03-author-tests01.log',Path(__file__).name]
for k in ['03','04','05']:
 for suffix in ['terminal-capture01.json','result.json','trace.jsonl','staging01.json','install01.json','launch-readiness01.json','launch01.json']:
  names.append(f'captured-tangent{k}-{suffix}')
 names.append(f'captured-tangent{k}-packet/packet-files.json')
files={C/n for n in names};pending=list(files)
while pending:
 p=pending.pop();assert p.is_file()and not p.is_symlink(),str(p)
 if p.suffix!='.json':continue
 try:v=json.loads(p.read_bytes())
 except json.JSONDecodeError:continue
 for r in walk(v):
  q=Path(r['path'])
  if q.is_relative_to(C)and q.is_file()and not q.is_symlink()and q.suffix not in {'.gz','.bin','.so','.pyc'}and q.stat().st_size<1500000:
   b=q.read_bytes();assert sha(b)==r['sha256'],str(q)
   if 'bytes'in r:assert len(b)==r['bytes'],str(q)
   assert 'tangent72-diagnostic08'not in str(q)
   if q not in files:files.add(q);pending.append(q)
for sub in ['tangent72-diagnostic07','tangent72-diagnostic06','captured-tangent03-packet/control','captured-tangent04-packet/control','captured-tangent05-packet/control']:
 for p in (C/sub).rglob('*'):
  if p.is_file()and '__pycache__'not in p.parts and p.suffix in {'.py','.cpp','.h','.json','.txt'}:files.add(p)
O.mkdir(exist_ok=False);rows=[];values={};remote_copies={}
def put(rel,b,original=None,attribution=None):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
 r={'path':rel,'sha256':sha(b),'bytes':len(b)}
 if original:r['original']=original
 if attribution:r['attribution']=attribution
 rows.append(r)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
for p in sorted(files):
 rel='evidence/'+str(p.relative_to(C));b=p.read_bytes();put(rel,b,pin(p),'Exact local evidence or source bytes; identical deployed source is not inferred remote acquisition.')
 if p.suffix=='.json':
  try:values[str(p)]=json.loads(b)
  except json.JSONDecodeError:pass
original_count=0
for k,expected in [('03',14),('04',14),('05',11)]:
 capture=load(f'captured-tangent{k}-terminal-capture01.json');assert len(capture['files'])==expected
 for i,f in enumerate(capture['files'],1):
  b=base64.b64decode(f['base64'],validate=True);assert len(b)==f['bytes']and sha(b)==f['sha256']
  orig={x:f[x]for x in ['path','sha256','bytes']};rel=f'original/attempt{k}/{i:02d}-{Path(f["path"]).name}'
  put(rel,b,orig,'Exact original remote bytes decoded from audited base64 capture, preserving CR/LF.');remote_copies[(f['path'],f['sha256'])]=rel;original_count+=1
external={}
for source,v in values.items():
 for r in walk(v):
  p=r['path'];h=r['sha256']
  if not p.startswith('/')or p.startswith(str(C)+'/')or len(h)!=64:continue
  key=(p,h);e=external.setdefault(key,{'path':p,'sha256':h,'recorded_in':[]})
  if 'bytes'in r:e['bytes']=r['bytes']
  if source not in e['recorded_in']:e['recorded_in'].append(source)
  if key in remote_copies:e.update(availability='copied_exact_remote_record',copy=remote_copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
byhash=collections.defaultdict(list)
for r in rows:
 if r['path'].startswith('evidence/')and Path(r['path']).suffix in {'.py','.cpp','.h','.txt'}and r['bytes']:byhash[r['sha256']].append(r['path'])
for e in external.values():
 if e['availability'].startswith('external')and e['sha256']in byhash:e['identical_local_source_bytes']=byhash[e['sha256']]
results={k:load(f'captured-tangent{k}-result.json')for k in ['03','04','05']}
assert [results[k]['terminal']['status']for k in results]==['passed','failed','passed']
for k,r in results.items():
 trace=[json.loads(x)for x in (C/f'captured-tangent{k}-trace.jsonl').read_text().splitlines()]
 assert len(trace)==r['record_count']and [x for x in trace if x['kind']=='terminal']==[r['terminal']]
 assert pin(C/f'captured-tangent{k}-trace.jsonl')['sha256']==r['trace']['sha256']
 assert r['input']['tolerance']==2e-12 and r['input']['maximum_iterations']==120 and r['input']['restart']==20
 assert r['groops_propagations']==r['fit_attempts']==0
assert results['03']['reader']['sha256']==results['04']['reader']['sha256']=='e41517890067357108cb77c99661e48ddd192863c4b6c6fbf5d5b1f5a14e9e7a'
assert results['05']['reader']['sha256']=='6dd7c97dc0825ffb815266ea478c038208a4fe883dce872653904e0a57dd5b34'
assert results['04']['inputs']['capture']==results['05']['inputs']['capture']
outcomes=[]
for k,label in [('03','candidate07_new_system'),('04','candidate07_old_system'),('05','fresh_diagnostic06_old_system_baseline')]:
 r=results[k];q=next(x for x in [json.loads(s)for s in (C/f'captured-tangent{k}-trace.jsonl').read_text().splitlines()]if x['kind']in ('accepted_quad_residual','quad_residual'))
 outcomes.append({'attempt':k,'label':label,'terminal':r['terminal'],'accepted_or_final_quad':q,'capture':r['inputs']['capture'],'reader':r['reader'],'compiler_command':r['compiler_command'],'compiler_version':r['compiler_version'],'runtime_libraries':r['reader_libraries'],'result':pin(C/f'captured-tangent{k}-result.json'),'trace':pin(C/f'captured-tangent{k}-trace.jsonl')})
summary={'schema':'orbit-poc-candidate07-rejection-publication-v1','status':'candidate07_rejected_due_to_retained_case_regression','outcomes':outcomes,'conclusion':baseline['conclusion'],'candidate07_old_best_observed_quad':joint['outcomes'][1]['best_native_quad'],'threshold':2e-12,'max_iterations':120,'restart_capacity':20,'production_code_changed_by_experiment':False,'production_promotion_approved':False,'benchmark_attempts':0,'release_ready':False,'pending_candidate08_outcomes_included':False,'audits':{'candidate07_joint':pin(C/'captured-tangent03-04-independent-terminal-review01.json'),'fresh_diagnostic06_baseline':pin(C/'captured-tangent05-independent-terminal-review01.json')},'scope':['Candidate07 retains the Arnoldi basis after a projected threshold crossing whose rounded candidate fails the actual true-residual test. The physical/statistical model, operator, quadrature, preconditioner and 120/20/2e-12 limits stay unchanged.','It passes the new small-RHS capture but regresses the old large-RHS capture, which freshly passes with diagnostic06 under the same compiler and runtime. Candidate07 is rejected for production.','These are isolated captured-system solves. They do not establish native trajectory closure, covariance validity, a fitted orbit or release readiness.','Both compact fixture suites for 07 passed 3 tests with 8 nested original checks; the source review records limitations of branch coverage. Fresh 05 was a baseline execution, not a new fixture-suite claim.','The joint reviewer records an earlier inline Python syntax error before execution; no raw artifact was created, and no numerical run or evidence mutation resulted.','Both bulky captured-system arrays remain external with exact hashes; pending compensated-summation candidate08 outcomes are excluded.'],'original_compact_records':original_count}
js('summary.json',summary);js('external-evidence.json',{'schema':'orbit-poc-experiment-source-output-inventory-v1','records':list(external.values()),'scope':'Explicit remote copies are distinguished from external payloads and identical local source bytes. No new capture or numerical execution was performed to publish this snapshot.'})
put('index.html',('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Candidate07 rejected after retained-system regression</title><style>body{font:16px system-ui;max-width:980px;margin:3rem auto;line-height:1.5}table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #bbb;text-align:left}code{word-break:break-all}</style><h1>Candidate07 is rejected after a retained-system regression</h1><p>Candidate07 keeps the current Arnoldi basis after a projected threshold crossing fails a fresh true-residual check. It passes the new captured system but fails the earlier captured system. A fresh diagnostic06 baseline passes that earlier system under the same compiler and runtime.</p><table><tr><th>Captured-system experiment</th><th>Outcome / steps</th><th>Native final residual</th><th>113-bit accepted/final residual</th></tr><tr><td>Candidate07, new system f172…</td><td>Pass / 7</td><td>1.2183859441480567e-12</td><td>1.170533711634619e-12</td></tr><tr><td>Candidate07, earlier system b1fd…</td><td>Fail / 120</td><td>8.89024170922695e-12</td><td>8.980836588702807e-12</td></tr><tr><td>Fresh diagnostic06 baseline, earlier b1fd…</td><td>Pass / 7</td><td>1.7564764459600119e-12</td><td>1.6558481483345173e-12</td></tr></table><p>The original threshold is 2e-12, with 120 steps and restart capacity 20. The best observed native iterate from candidate07 on the earlier system also fails under 113-bit re-evaluation (2.039978489460305e-12). Higher-precision values shown use the native velocity conversion; exact-conversion values are retained separately.</p><p>The fresh diagnostic06 baseline is a new measured execution. Its reader matches the reader used to diagnose the new system. Both 07 traces match their prior baseline through the first failed true-residual crossing; the later divergence is the intended experimental control-flow change. Independent audits verified source/runtime attribution and owned cleanup.</p><p><strong>Candidate07 must not be promoted. Production remains unchanged by this experiment; 0/68 benchmark fits.</strong> No full native trajectory closure, covariance, orbit-fit or release claim follows from these isolated solves. Pending candidate08 outcomes are excluded.</p><ul><li><a href="evidence/captured-tangent03-04-independent-terminal-review01.json">Joint actual 07 outcome audit</a></li><li><a href="evidence/captured-tangent05-independent-terminal-review01.json">Fresh diagnostic06 baseline audit</a></li><li><a href="evidence/tangent72-diagnostic07-independent-review01.json">Candidate source review and test-coverage limitations</a></li><li><a href="evidence/captured-tangent03-result.json">New-system result, compiler flags, runtime and fixture tests</a></li><li><a href="evidence/captured-tangent04-result.json">Retained-system failure, compiler flags, runtime and fixture tests</a></li><li><a href="evidence/captured-tangent05-result.json">Fresh retained-system baseline result</a></li><li><a href="summary.json">Machine-readable comparison</a></li><li><a href="external-evidence.json">Both external captures and source/control/runtime provenance</a></li><li><a href="manifest.json">Exact publication manifest</a></li></ul><p>Thirty-nine original compact records preserve exact bytes, including failed-experiment output. Both captured-system arrays remain outside Git. No native run, Git mutation or PR mutation was performed to prepare this publication.</p></html>''').encode())
m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Rejected external candidate07 and fresh diagnostic06 retained-system baseline; no production promotion or readiness.'};(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps({'output':str(O),'manifest':pin(O/'manifest.json'),'file_count':len(rows),'total_bytes':m['total_bytes'],'original_records':original_count,'external_references':len(external)},indent=2))
