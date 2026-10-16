from pathlib import Path
import json,hashlib,base64,collections,argparse
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-tangent-candidate08-captures01'
p=argparse.ArgumentParser();p.add_argument('--audit',required=True);p.add_argument('--sha256',required=True);args=p.parse_args()
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def load(n):return json.loads((C/n).read_text())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str)and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
auditpath=Path(args.audit);assert auditpath.parent==C and pin(auditpath)['sha256']==args.sha256
joint=json.loads(auditpath.read_text());assert joint['passed']
names=[auditpath.name,'tangent72-diagnostic08-independent-review01.json','captured-tangent03-independent-control-review01.json',Path(__file__).name]
for k in ['06','07']:
 for suffix in ['terminal-capture01.json','result.json','trace.jsonl','staging01.json','install01.json','launch-readiness01.json','launch01.json']:
  names.append(f'captured-tangent{k}-{suffix}')
 names.append(f'captured-tangent{k}-packet/packet-files.json')
files={C/n for n in names};pending=list(files)
while pending:
 q=pending.pop();assert q.is_file()and not q.is_symlink(),str(q)
 if q.suffix!='.json':continue
 try:v=json.loads(q.read_bytes())
 except json.JSONDecodeError:continue
 for r in walk(v):
  x=Path(r['path'])
  if x.is_relative_to(C)and x.is_file()and not x.is_symlink()and x.suffix not in {'.gz','.bin','.so','.pyc'}and x.stat().st_size<1500000:
   b=x.read_bytes();assert sha(b)==r['sha256'],str(x)
   if 'bytes'in r:assert len(b)==r['bytes'],str(x)
   if x not in files:files.add(x);pending.append(x)
for sub in ['tangent72-diagnostic08','captured-tangent06-packet/control','captured-tangent07-packet/control']:
 for x in (C/sub).rglob('*'):
  if x.is_file()and '__pycache__'not in x.parts and x.suffix in {'.py','.cpp','.h','.json','.txt'}:files.add(x)
O.mkdir(exist_ok=False);rows=[];values={};remote_copies={}
def put(rel,b,original=None,attribution=None):
 q=O/rel;q.parent.mkdir(parents=True,exist_ok=True)
 with q.open('xb')as f:f.write(b)
 r={'path':rel,'sha256':sha(b),'bytes':len(b)}
 if original:r['original']=original
 if attribution:r['attribution']=attribution
 rows.append(r)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
for q in sorted(files):
 rel='evidence/'+str(q.relative_to(C));b=q.read_bytes();put(rel,b,pin(q),'Exact local evidence or source bytes; identical deployed source bytes are not inferred remote acquisition.')
 if q.suffix=='.json':
  try:values[str(q)]=json.loads(b)
  except json.JSONDecodeError:pass
original_count=0
for k in ['06','07']:
 cap=load(f'captured-tangent{k}-terminal-capture01.json');assert len(cap['files'])==14
 for i,f in enumerate(cap['files'],1):
  b=base64.b64decode(f['base64'],validate=True);assert len(b)==f['bytes']and sha(b)==f['sha256'];orig={x:f[x]for x in ['path','sha256','bytes']};rel=f'original/attempt{k}/{i:02d}-{Path(f["path"]).name}'
  put(rel,b,orig,'Exact original remote bytes decoded from audited base64 capture, preserving CR/LF.');remote_copies[(f['path'],f['sha256'])]=rel;original_count+=1
external={}
for source,v in values.items():
 for r in walk(v):
  path=r['path'];h=r['sha256']
  if not path.startswith('/')or path.startswith(str(C)+'/')or len(h)!=64:continue
  key=(path,h);e=external.setdefault(key,{'path':path,'sha256':h,'recorded_in':[]})
  if 'bytes'in r:e['bytes']=r['bytes']
  if source not in e['recorded_in']:e['recorded_in'].append(source)
  if key in remote_copies:e.update(availability='copied_exact_remote_record',copy=remote_copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
byhash=collections.defaultdict(list)
for r in rows:
 if r['path'].startswith('evidence/')and Path(r['path']).suffix in {'.py','.cpp','.h','.txt'}and r['bytes']:byhash[r['sha256']].append(r['path'])
for e in external.values():
 if e['availability'].startswith('external')and e['sha256']in byhash:e['identical_local_source_bytes']=byhash[e['sha256']]
results={k:load(f'captured-tangent{k}-result.json')for k in ['06','07']};outcomes=[]
for k,label in [('06','candidate08_new_system'),('07','candidate08_old_system')]:
 r=results[k];trace=[json.loads(x)for x in (C/f'captured-tangent{k}-trace.jsonl').read_text().splitlines()]
 assert len(trace)==r['record_count']and [x for x in trace if x['kind']=='terminal']==[r['terminal']]
 assert pin(C/f'captured-tangent{k}-trace.jsonl')['sha256']==r['trace']['sha256']
 assert r['input']['tolerance']==2e-12 and r['input']['maximum_iterations']==120 and r['input']['restart']==20
 assert r['groops_propagations']==r['fit_attempts']==0 and r['returncode']==0
 q=next(x for x in trace if x['kind']=='accepted_quad_residual');assert q['relative_residual_native_velocity_conversion']<2e-12 and q['relative_residual_exact_velocity_conversion']<2e-12
 assert r['terminal']['status']=='passed'and r['terminal']['relative_residual']<2e-12
 outcomes.append({'attempt':k,'label':label,'terminal':r['terminal'],'accepted_quad':q,'capture':r['inputs']['capture'],'reader':r['reader'],'compiler_command':r['compiler_command'],'compiler_version':r['compiler_version'],'runtime_libraries':r['reader_libraries'],'fixture_preflight':r['fixture_preflight'],'result':pin(C/f'captured-tangent{k}-result.json'),'trace':pin(C/f'captured-tangent{k}-trace.jsonl')})
assert [r['terminal']['iterations']for r in results.values()]==[5,46]
assert results['06']['reader']['sha256']==results['07']['reader']['sha256']=='4f127662f76b0da5058446dec79ce04caed174f30c8606ecf5123d85c313891f'
summary={'schema':'orbit-poc-candidate08-captured-system-publication-v1','status':'both_captured_systems_passed_scoped_checks','outcomes':outcomes,'candidate':'diagnostic08 compensated quadrature accumulation with unchanged diagnostic06 GMRES/restart','threshold':2e-12,'max_iterations':120,'restart_capacity':20,'production_modification_or_build_launch_claimed':False,'native_trajectory_closure_claimed':False,'benchmark_attempts':0,'covariance_authorized':False,'release_ready':False,'audit':pin(auditpath),'code_audit':pin(C/'tangent72-diagnostic08-independent-review01.json'),'scope':['Local and chronological sums use compensation with the same stored quadrature weights and dependencies; the velocity low part is carried into the position sum. Floating-point ordering changes, not the physical/statistical model.','Baseline06 preconditioner, GMRES, restart and stopping criteria are unchanged; rejected candidate07 basis-continuation behavior is not used.','Both observed accepted double iterates pass the original threshold under the independent 113-bit residual evaluation. This is limited to the two pinned captured systems.','Each execution passed three small fixture tests with eight nested original reader checks, including an analytic cancellation fixture; these do not establish a general robustness guarantee.','The earlier system takes46 steps here versus7 for the fresh diagnostic06 baseline. No speedup is claimed; all failures and preceding rejected07 remain preserved separately.','These are external captured-system experiments. Full native propagation/closure, a production build, the complete correctness suite and the68-fit benchmark are not results of this package.'],'original_compact_records':original_count}
js('summary.json',summary);js('external-evidence.json',{'schema':'orbit-poc-experiment-source-output-inventory-v1','records':list(external.values()),'scope':'Explicit remote copies are distinguished from external payloads and identical local source bytes. No new capture or numerical execution was performed to publish this snapshot.'})
put('index.html',('''<!doctype html><html lang="en"><meta charset="utf-8"><title>Candidate08 captured-system experiments</title><style>body{font:16px system-ui;max-width:980px;margin:3rem auto;line-height:1.5}table{border-collapse:collapse}td,th{padding:.5rem;border:1px solid #bbb;text-align:left}code{word-break:break-all}</style><h1>Candidate08 passes both captured-system checks</h1><p>The external candidate adds compensated local and chronological quadrature sums while retaining the stored weights, dependencies and baseline06 GMRES/restart behavior. It carries the velocity low part into the position sum. Floating-point ordering changes; no physical model, prior, constraint or interpolation coefficient changes.</p><table><tr><th>Captured system</th><th>Accepted step</th><th>Native true residual</th><th>Independent 113-bit residual</th></tr><tr><td>New small-RHS system f172…</td><td>5</td><td>1.321764983063378e-12</td><td>1.3176918808001025e-12</td></tr><tr><td>Earlier large-RHS system b1fd…</td><td>46</td><td>1.7745943440717721e-12</td><td>1.7706735103637685e-12</td></tr></table><p>The unchanged threshold is 2e-12, with 120 steps and restart capacity 20. Both accepted double iterates pass under the independent higher-precision calculation; exact velocity-conversion variants are retained in the raw records. Each experiment also passed three small fixture tests with eight nested reader checks.</p><p>The earlier system requires 46 steps here, compared with 7 for the fresh diagnostic06 baseline. <strong>No speedup or general robustness claim is made.</strong> Rejected candidate07 and its retained-case regression remain separately preserved; its basis-continuation change is absent from this candidate.</p><p><strong>These are two external captured-system results, not full native trajectory closure or a production rollout. V4 remains at 0/68 benchmark fits.</strong> No production build launch, accepted covariance or release readiness is claimed by this snapshot. The production-scale validation work remains separate.</p><ul><li><a href="summary.json">Machine-readable outcomes and audit identity</a></li><li><a href="evidence/tangent72-diagnostic08-independent-review01.json">Candidate source review, analytic fixture and limitations</a></li><li><a href="evidence/captured-tangent06-result.json">New-system result, compiler flags, runtime and fixtures</a></li><li><a href="evidence/captured-tangent07-result.json">Earlier-system result, compiler flags, runtime and fixtures</a></li><li><a href="evidence/captured-tangent06-trace.jsonl">New-system trace</a></li><li><a href="evidence/captured-tangent07-trace.jsonl">Earlier-system trace</a></li><li><a href="external-evidence.json">External capture and source/control/runtime pins</a></li><li><a href="manifest.json">Exact publication manifest</a></li></ul><p>Twenty-eight original compact records preserve exact raw bytes. Both captured-system arrays remain outside Git. No native run, Git mutation or PR mutation was performed to prepare this publication.</p></html>''').encode())
m={'schema':'orbit-poc-compact-publication-manifest-v1','files':rows,'file_count':len(rows),'total_bytes':sum(x['bytes']for x in rows),'scope':'Two actual external candidate08 captured-system passes; no native closure, build-launch or release claim.'};(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n');print(json.dumps({'output':str(O),'manifest':pin(O/'manifest.json'),'file_count':len(rows),'total_bytes':m['total_bytes'],'original_records':original_count,'external_references':len(external)},indent=2))
