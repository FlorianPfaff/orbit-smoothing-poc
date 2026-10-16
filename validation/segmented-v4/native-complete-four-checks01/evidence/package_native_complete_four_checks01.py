"""Package only existing pinned audited native checks; never run numerical work."""
from pathlib import Path
import base64,collections,hashlib,html,json,re
B=Path('/mnt/d/orbit-segmented-v4');C=B/'control';O=B/'publication-native-complete-four-checks01'
N='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):
 b=p.read_bytes();return dict(path=str(p),sha256=sha(b),bytes=len(b))
def read(p):return json.loads(p.read_bytes())
def walk(v):
 if isinstance(v,dict):
  if isinstance(v.get('path'),str) and isinstance(v.get('sha256'),str):yield v
  for x in v.values():yield from walk(x)
 elif isinstance(v,list):
  for x in v:yield from walk(x)
def checkpin(r):
 p=Path(r['path']);assert p.is_relative_to(C) and p.is_file() and not p.is_symlink(),str(p)
 b=p.read_bytes();assert sha(b)==r['sha256'],str(p)
 if 'bytes'in r:assert len(b)==r['bytes'],str(p)
 assert b'\0'not in b;b.decode('utf-8');return p
S=C/'native-complete-four-checks-publication-spec01.json';spec=read(S)
files={checkpin(r)for r in spec['files']};files|={S,Path(__file__)}
audits={k:read(checkpin(v))for k,v in spec['audits'].items()}
assert set(audits)=={'single01','single02','closure01','closure02','supplemental'}
for k,a in audits.items():
 assert a['passed'] and a['native']['sha256']==N,k
 assert checkpin(a['raw_capture'])in files,k
 if k!='supplemental':
  assert a['physical_inputs_verified']==13 and a['explicit_build_and_supplemental_inputs_verified']==3 and a['fit_attempts']==0,k
  assert a['initialization_criteria']==dict(maximum_iterations=10,position_tolerance_m=2e-6,velocity_tolerance_m_s=3e-9),k
  assert a['full_scientific_suite_verified'] is False,k
  assert all(not p['live']for p in a['owned_identities']),k
 else:
  assert a['regression']['status']=='passed' and not a['regression']['frozen_suite_counts_changed']
  assert all(not p['live']for p in a['owned_processes'])
controls=read(C/'nominal-complete-native-independent-code-review02.json');assert controls['passed'] and controls['tests']['passed']==77 and controls['tests']['failed']==0 and controls['tests']['skipped']==0
packet=read(C/'nominal-complete-four-independent-packet-review01.json');assert packet['passed']and len(packet['packets'])==4
# Validate all decoded original records before creating any output.
raw=[];rawvalues={};external=[];results={};rawmap={}
for k,a in audits.items():
 cap=read(Path(a['raw_capture']['path']));assert len(cap['files'])==a['raw_records_verified'],k
 assert cap['fit_attempts']==0 and not cap['release_evidence'],k
 external.extend({'check':k,**r}for r in cap['external_arrays_and_binaries'])
 for i,r in enumerate(cap['files'],1):
  b=base64.b64decode(r['base64'],validate=True);assert sha(b)==r['sha256']and len(b)==r['bytes'];b.decode('utf-8');assert b'\0'not in b
  orig={x:r[x]for x in ['path','sha256','bytes']};rel=f'original/{k}/{i:02d}-{Path(r["path"]).name}'
  raw.append((rel,b,orig));rawmap[(r['path'],r['sha256'])]=rel
  if r['path'].endswith('.json'):rawvalues[rel]=json.loads(b)
  if r['path'].endswith('/replay/result.json'):
   assert r['sha256']==a['result']['sha256'];results[k]=json.loads(b)
  if r['path']==a['pipeline']['path']:assert r['sha256']==a['pipeline']['sha256']
for k in ['single01','single02','closure01','closure02']:
 a=audits[k];r=results[k];assert r['native']['sha256']==N and r['fit_attempts']==0 and r['state_epochs']==51840
 assert r['fixed_initial_state_si']==a['fixed_initial_state_si']
 assert r['initialization_criteria']==a['initialization_criteria']
 assert r['status']==a['status']
 assert r['analytical_supplemental']['receipt']['sha256']==audits['supplemental']['result']['sha256']
 if k.startswith('single'):assert r['native_evaluations']==1 and r['status']=='native_completed' and r['initial_state_error_si']==[0]*6
 else:
  assert r['status']=='closed'and r['converged']and r['native_evaluations']==len(r['iterations'])<=10
  assert all(x['initial_state_error_si']==[0]*6 for x in r['iterations'])
  last=r['iterations'][-1];assert last['closed'] and last['maximum_position_change_m']<2e-6 and last['maximum_velocity_change_m_s']<3e-9
# The original target differs between preparations; closure04 starts from its original initial orbit,
# whereas its single replay uses the saved iteration02 orbit. Every one of the13 physical pins is retained.
phys=[]
for p in packet['packets']:
 assert len(p['physical_inputs'])==13
 k=('single'if p['mode']=='single'else'closure')+('01'if p['case']=='preparation03'else'02')
 assert p['plan']['sha256']==audits[k]['plan']['sha256'] and p['fixed_initial_state_si']==audits[k]['fixed_initial_state_si']
 phys.append(dict(check=k,case=p['case'],mode=p['mode'],inputs=p['physical_inputs'],fixed_initial_state_si=p['fixed_initial_state_si']))
assert audits['single01']['fixed_initial_state_si']!=audits['single02']['fixed_initial_state_si']
assert next(x for x in phys if x['check']=='single02')['inputs']['initial_orbit']!=next(x for x in phys if x['check']=='closure02')['inputs']['initial_orbit']
O.mkdir(exist_ok=False);rows=[];copies={};values={}
def put(rel,b,original=None,attribution=None):
 assert not Path(rel).is_absolute()and'..'not in Path(rel).parts
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb')as f:f.write(b)
 row=dict(path=rel,sha256=sha(b),bytes=len(b))
 if original:row['original']=original;copies[(original['path'],original['sha256'])]=rel
 if attribution:row['attribution']=attribution
 rows.append(row)
 if rel.endswith('.json')and b.strip():values[rel]=json.loads(b)
def js(rel,v):put(rel,(json.dumps(v,indent=2)+'\n').encode())
for p in sorted(files):put('evidence/'+str(p.relative_to(C)),p.read_bytes(),pin(p),'Exact local evidence or source bytes; not inferred remote acquisition.')
for rel,b,orig in raw:put(rel,b,orig,'Exact original remote bytes decoded from audited base64; CR/LF retained.')
summary=dict(schema='orbit-poc-complete-native-four-checks-publication-v1',status='four_bounded_native_checks_passed',native_sha256=N,latest_independent_audit_at=max(a['observed_at']for a in audits.values()),audits=spec['audits'],checks=[dict(check=k,case=audits[k]['case'],status=results[k]['status'],state_epochs=results[k]['state_epochs'],native_propagations=results[k]['native_evaluations'],fixed_initial_state_si=results[k]['fixed_initial_state_si'],final_closure=results[k]['iterations'][-1]if k.startswith('closure')else None,raw_result=audits[k]['result'])for k in ['single01','single02','closure01','closure02']],analytical_supplemental=audits['supplemental']['regression'],control_tests=77,original_compact_records=len(raw),benchmark_attempts=0,planned_benchmark_attempts=68,full_scientific_suite_verified=False,covariance_authorized=False,release_ready=False,scope=[
 'Two exact originally failed native propagations and two complete fixed-initial-state closures are independently audited. Each preparation keeps its distinct13 original physical input pins; supplemental/build receipts add three attribution pins.',
 'Every successful native output retains all51840 epochs and the exact physical initial state. The closure caps remain10 iterations,2 micrometres position and3 nanometres/second velocity; the inner tangent residual limit remains2e-12.',
 'The analytical fixture ran once separately against the installed header and compiler; each replay requires its passed receipt. The77 pure control tests and this fixture do not add to or replace106 native/51 correction tests.',
 'This is bounded native replay/closure evidence. No new complete scientific suite, benchmark fit, covariance authorization, accuracy superiority, speedup or release readiness is claimed.',
 'The package performs only local byte/provenance checks on existing captures and audits; it does not execute native work or rewrite historical outcomes.' ])
js('summary.json',summary);js('physical-inputs.json',dict(schema='orbit-poc-exact-native-check-input-inventory-v1',checks=phys,scope='Exact original13 input pins per check, plus original target; shared content does not collapse distinct source-path attribution.'))
js('external-native-outputs.json',dict(schema='orbit-poc-native-check-external-output-inventory-v1',records=external,scope='Bulky native trajectory/tangent arrays and binaries remain external with original audit hashes.'))
js('preserved-control-history.json',dict(schema='orbit-poc-native-check-control-history-v1',records=spec['history'],scope='Control-review and read-only inspection issues remain distinct from scientific outcomes. No failed native check is omitted or reclassified.'))
refs={}
for src,v in values.items():
 for r in walk(v):
  path,h=r['path'],r['sha256']
  if not path.startswith('/')or len(h)!=64:continue
  key=(path,h);e=refs.setdefault(key,dict(path=path,sha256=h,recorded_in=[]))
  if 'bytes'in r:e['bytes']=r['bytes']
  if src not in e['recorded_in']:e['recorded_in'].append(src)
  if key in rawmap:e.update(availability='copied_exact_remote_record',copy=rawmap[key])
  elif key in copies:e.update(availability='copied_exact_local_record_or_source',copy=copies[key])
  else:e['availability']='external_payload_not_copied_by_this_publication'
local_sources=collections.defaultdict(list)
for row in rows:
 if row['path'].startswith('evidence/')and Path(row['path']).suffix in {'.py','.cpp','.h'}and row['bytes']:local_sources[row['sha256']].append(row['path'])
for e in refs.values():
 if e['availability'].startswith('external')and e['sha256']in local_sources:e['identical_local_source_bytes']=local_sources[e['sha256']]
js('external-evidence.json',dict(schema='orbit-poc-explicit-publication-reference-inventory-v1',records=list(refs.values()),scope='Exact per-path/hash acquisition attribution. Identical local source is distinguished from original remote copies; empty stderr files are never inferred to be copies by hash alone.'))
table=[]
for x in summary['checks']:
 k=x['check'];r=results[k]
 if k.startswith('single'):detail=f'One propagation; {r["execution"]["elapsed_seconds"]:.4f}s recorded wall time'
 else:
  v=x['final_closure'];detail=f'{x["native_propagations"]} iterations; final change {v["maximum_position_change_m"]:.12g}m / {v["maximum_velocity_change_m_s"]:.12g}m/s'
 table.append(f'<tr><td>{html.escape(k)}</td><td>{html.escape(x["case"])}</td><td>{html.escape(x["status"])}</td><td>{html.escape(detail)}</td></tr>')
links=[]
for k,a in audits.items():links.append(f'<li><a href="evidence/{Path(spec["audits"][k]["path"]).name}">{k} independent audit</a></li>')
doc='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Four bounded native checks passed</title><style>body{font:16px system-ui;max-width:1100px;margin:3rem auto;line-height:1.55}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:.6rem;text-align:left}code{overflow-wrap:anywhere}</style><h1>Both retained failures now pass native replay and fixed-state closure</h1><p>The complete rebuilt executable <code>643a1b6d...</code> passed both single propagations and both complete fixed-initial-state closures under independent audit. <strong>V4 remains at0/68 benchmark fits. The fresh complete scientific suite and release gates remain outstanding.</strong></p><table><tr><th>Check</th><th>Original case</th><th>Outcome</th><th>Bounded result</th></tr>'''+''.join(table)+'''</table><p>All51,840 saved epochs and each exact initial state were retained. The13 original physical input pins are preserved separately for every check. The preparation04 single replay starts from its archived iteration02 orbit; its full closure starts from the original initial orbit. These are different checks, not interchangeable substitutes.</p><p>The closure criteria remain10 iterations maximum,2µm position change and3nm/s velocity change, with the unchanged2e-12 inner tangent true-residual guard. No threshold was relaxed. Reported propagation times are individual observed diagnostics, not a speedup or benchmark result.</p><p>The original analytical compensated-quadrature fixture passed separately against the installed header with the build compiler and flags. Its receipt is required by all four checks. The77 pure control tests passed independently; neither those tests nor the supplemental fixture replace or increase the prescribed106 native and51 correction test counts.</p><p>The earlier control draft lacked rejection of a changed initial state; its review finding and corrected exact-state tests are retained. A read-only live inspector initially used the wrong receipt name; its failure and corrected inspector are retained, without duplicate native execution. The earlier unused terminal auditor is preserved separately from the actual auditor. Historical failed native candidates remain published unchanged.</p><p>This evidence does not establish the full estimator's convergence, covariance validity, multi-day campaign completion, accuracy superiority or release readiness. Bulky output arrays and the executable remain outside Git with explicit source/hash attribution.</p><ul><li><a href="summary.json">Machine-readable outcomes</a></li><li><a href="physical-inputs.json">Distinct original inputs and targets</a></li>'''+''.join(links)+'''<li><a href="preserved-control-history.json">Preserved control history</a></li><li><a href="external-native-outputs.json">External output inventory</a></li><li><a href="external-evidence.json">All explicit provenance references</a></li><li><a href="manifest.json">Exact publication bytes</a></li></ul></html>'''
# Improve spacing without changing any numerical content.
for a,b in [('at0/68','at 0/68'),('All51,840','All 51,840'),('The13','The 13'),('remain10','remain 10'),('maximum,2µm','maximum, 2µm'),('and3nm/s','and 3nm/s'),('unchanged2e-12','unchanged 2e-12'),('The77','The 77'),('prescribed106','prescribed 106'),('and51','and 51')]:doc=doc.replace(a,b)
put('index.html',doc.encode())
m=dict(schema='orbit-poc-compact-publication-manifest-v1',files=rows,file_count=len(rows),total_bytes=sum(x['bytes']for x in rows),scope='Four exact bounded native checks and separate analytical fixture; full scientific suite and0/68 benchmark outstanding.')
(O/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
assert {str(p.relative_to(O))for p in O.rglob('*')if p.is_file()}=={r['path']for r in rows}|{'manifest.json'}
for r in rows:assert pin(O/r['path'])['sha256']==r['sha256']and(O/r['path']).stat().st_size==r['bytes']
for href in re.findall('href="([^"]+)"',(O/'index.html').read_text()):assert(O/href).is_file(),href
print(json.dumps(dict(output=str(O),manifest=pin(O/'manifest.json'),file_count=len(rows),total_bytes=m['total_bytes'],original_records=len(raw),reference_count=len(refs)),indent=2))
