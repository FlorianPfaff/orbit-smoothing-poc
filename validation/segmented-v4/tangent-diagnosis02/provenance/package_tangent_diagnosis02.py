"""Append-only publication of already sealed diagnostics; no scientific execution."""
from pathlib import Path
import collections, datetime, hashlib, html, json
R=Path('/mnt/d/orbit-segmented-v4');C=R/'control';O=R/'publication-tangent-diagnosis02'
I=C/'tangent-diagnosis01-source-inventory.json'
AUDITS={
 'nominal-tangent-replay01-terminal-independent-review01.json':'8e165fb71b7b609f9096006798ef16fdbf3e94d535510c53aa4f1057c9131463',
 'tangent-capture-build03-terminal-independent-review01.json':'4b6fb9f4c5954a741b6a818f994d118a1cf34aa60b610cb50db1887a1c9c0490',
 'nominal-tangent-capture02-terminal-independent-review01.json':'849ea378c1d9954536d16bc87e9fe8edfac51ef272097d76be57dc2f487053ea',
 'captured-tangent01-terminal-independent-review01.json':'d7e665e9c15cbd33fbf1dd72efc1401a878778470ce15c981b430ba54267ae33',
 'captured-tangent02-terminal-independent-review01.json':'80a2c846cd8b335ad0b519fd8e6b00525eddbda589e3a757a9dbdb3fca0a027c',
 'tangent72-quad-reader03-independent-review01.json':'714fe279347f8e3fd584b6657f60a611257a224754fde20438b48ec25fb84c25',
 'tangent72-wide-update05-independent-review01.json':'d0375e8463d71d614358ef7c041306d9f5cd4b903a03e55fd8488bfab2a40986'}
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink(),p;b=p.read_bytes()
 return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):return json.loads(Path(p).read_text())
def put(rel,b):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
def jput(rel,v):put(rel,(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
assert pin(I)['sha256']=='93ee00df123eaadcd0c6f63b1219f3fc80de3b073651f7b4beeb72c7881447bd'
inventory=read(I);assert inventory['files']==244 and inventory['bytes']==2217365
audits={n:read(C/n) for n in AUDITS}
for n,h in AUDITS.items():assert pin(C/n)['sha256']==h and audits[n]['passed']
A=audits['nominal-tangent-replay01-terminal-independent-review01.json']
B=audits['tangent-capture-build03-terminal-independent-review01.json']
T=audits['nominal-tangent-capture02-terminal-independent-review01.json']
Q=audits['captured-tangent01-terminal-independent-review01.json']
W=audits['captured-tangent02-terminal-independent-review01.json']
traces={
 'original':('tangent72-diagnostic01/actual-standalone-trace01.jsonl',T['standalone_trace']),
 'quad_original':('tangent72-diagnostic03/actual-trace01.jsonl',Q['trace']),
 'wide_update':('tangent72-diagnostic05/actual-trace01.jsonl',W['trace'])}
rows={}
for name,(rel,art) in traces.items():
 assert pin(C/rel)['sha256']==art['sha256']
 rows[name]=[json.loads(x) for x in (C/rel).read_text().splitlines()]
base,quad,wide=rows['original'],rows['quad_original'],rows['wide_update']
assert (len(base),len(quad),len(wide))==(198,200,15)
assert [x for x in quad if x['kind']!='quad_residual']==base
assert wide[:7]==base[:7]
assert base[-1]==Q['terminal']==T['terminal']
assert wide[-1]==W['terminal']=={'kind':'terminal','status':'passed','iterations':7,'relative_residual':1.7564764459600119e-12}
assert [x for x in quad if x['kind']=='quad_residual']==Q['quad_records']
assert [x for x in wide if x['kind'] in ['quad_residual','accepted_quad_residual']]==W['quad_records']
assert all(x['relative_residual_native_velocity_conversion']>2e-12 for x in Q['quad_records'])
accepted=W['quad_records'][-1]
assert accepted['kind']=='accepted_quad_residual' and accepted['relative_residual_native_velocity_conversion']<2e-12
assert A['native_evaluations']==T['native_evaluations']==1 and Q['groops_propagations']==W['groops_propagations']==0
assert A['native']['sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert T['capture']==dict(Q['capture'],bytes=27786112)==dict(W['capture'],bytes=27786112)
true=[x for x in base if x['kind']=='true_residual'];projected=[x for x in base if x['kind']=='projected_residual']
assert (len(true),len(projected))==(76,120)
best=min(true,key=lambda x:x['native_relative_residual'])
assert best['iteration']==6 and best['native_relative_residual']==2.0546669696740676e-12
cycles=[b['iteration']-a['iteration'] for a,b in zip(true,true[1:])]
assert collections.Counter(cycles)=={1:33,2:41,5:1}
assert not O.exists();O.mkdir()
source_map={}
for item in inventory['entries']:
 ident=pin(item['path']);assert ident['sha256']==item['sha256'] and ident['bytes']==item['bytes'],item
 put(item['relative'],Path(item['path']).read_bytes());source_map[item['path']]=item['relative']
put('source-inventory.json',I.read_bytes());put('provenance/package_tangent_diagnosis02.py',Path(__file__).read_bytes())
for name in ['manifest.json','external-evidence.json']:
 put('preserved-publication01/'+name,(R/'publication-tangent-diagnosis01'/name).read_bytes())
put('preserved-publication01/package_tangent_diagnosis01.py',(C/'package_tangent_diagnosis01.py').read_bytes())
def ev(name):
 p=str(C/name);assert p in source_map,name;return source_map[p]
def ledger(id,classification,description,refs,**extra):
 return dict(id=id,classification=classification,description=description,evidence=[ev(x) for x in refs],**extra)
failures=[
 ledger('original-native-replay','numerical_failure_reproduced','The unchanged original executable reproduces every field of the original inner true-residual failure; evidence-attribution audit passed, native evaluation failed.', ['nominal-tangent-replay01-terminal.json','nominal-tangent-replay01-terminal-independent-review01.json']),
 ledger('build01','precompile_control_failure','Source inventory keys retained a source/ prefix while the comparison used paths below source/. No compilation occurred.', ['tangent-capture-build01-failure.json','tangent-capture-build02-control-independent-review01.json']),
 ledger('build02','precompile_control_failure','The expected base was the repository extension; the installed native header includes the existing segmented export hook. The guard rejected the mismatch before compilation.', ['tangent-capture-build02-failure.json','tangent-capture-build03-control-independent-review01.json']),
 ledger('telemetry01','pre_native_control_failure','The read-only capture-build namespace binding was missing. No native evaluation or worker output occurred. Local capture03 names refer to remote telemetry01.', ['nominal-tangent-capture03-terminal.json','nominal-tangent-capture03-worker-failure.log','nominal-tangent-capture02-terminal-independent-review01.json']),
 ledger('telemetry02','numerical_failure_reproduced','The separately compiled capture binary and reader reproduce the exact original failure. Local capture04 names refer to remote telemetry02.', ['nominal-tangent-capture04-terminal.json','nominal-tangent-capture02-terminal-independent-review01.json','tangent72-diagnostic01/actual-standalone-trace01.jsonl']),
 ledger('quad-reader03','numerical_failure_confirmed','A 113-bit residual evaluation of the unchanged double iterates at six and 120 iterations still fails the 2e-12 criterion; all 198 original records are preserved.', ['captured-tangent01-terminal.json','captured-tangent01-terminal-independent-review01.json','tangent72-diagnostic03/actual-trace01.jsonl']),
 ledger('writer-fixture01','author_fixture_failure','Unsigned loop-index subtraction wrapped in fixture data before conversion. The version02 signed-index fixture passes with writer code unchanged.', ['tangent-capture-writer01-author-tests.log','test_tangent_capture_writer01.py','test_tangent_capture_writer02.py','tangent-capture-writer01-independent-review01.json']),
 ledger('build03-author-insertion','author_script_failure','The initial author script used a wrong insertion literal and stopped on its assertion; the versioned script corrects that literal. The exception was observed in tool output but has no separately saved raw stderr artifact. Both scripts are retained; no invented stderr or native failure is claimed.', ['author_tangent_capture_build03.py','author_tangent_capture_build03_02.py'],raw_stderr_preserved=False),
 ledger('build03-author-collection','author_test_collection_failure','The first test invocation could not find the not-yet-created test file; zero tests ran. A separately named second result and independent run preserve the completed checks.', ['tangent-capture-build03-author-tests.log','tangent-capture-build03-author-tests.xml','tangent-capture-build03-author-tests02.log','tangent-capture-build03-independent-tests.log']),
 ledger('replay-packet-review01','reviewer_invocation_failure','The read-only reviewer used CPU32; current-host admission rejected affinity outside the reserved controller CPUs. The same helper subsequently passed with the prescribed affinity.', ['nominal-tangent-replay01-packet-independent-readback01.stderr.log','nominal-tangent-replay01-packet-independent-review01.json']),
 ledger('capture-review01','reviewer_assertion_failure','The reviewer capture-magic assertion had one excess zero byte; its failed readback and helper are retained.', ['audit_nominal_tangent_capture02_terminal.py','nominal-tangent-capture02-terminal-independent-readback01.stderr.log','nominal-tangent-capture02-terminal-independent-review01.json']),
 ledger('capture-review02','reviewer_lookup_failure','The reviewer expected worker.log instead of native-replay.log. The versioned final review uses the actual recorded filename.', ['audit_nominal_tangent_capture02_terminal02.py','nominal-tangent-capture02-terminal-independent-readback02.stderr.log','nominal-tangent-capture02-terminal-independent-review01.json']),
 ledger('quad-fixture-review01','reviewer_output_bound_failure','The first Decimal comparison bound was smaller than documented long-double output rounding. A versioned reviewer fixture corrects that output bound; the diagnostic evaluator and 2e-12 scientific limit are unchanged.', ['tangent72-quad-independent01.stderr.log','test_tangent72_quad_independent01.py','test_tangent72_quad_independent02.py','tangent72-quad-reader03-independent-review01.json'])]
jput('failure-ledger.json',{'schema':'orbit-poc-tangent-diagnosis-failures-v1','entries':failures,'scope':'Scientific failures, pre-native/precompile control failures and author/reviewer mistakes are distinct. No unsuccessful record was replaced; intermediate unexecuted reader variants02/04 are retained as source, not reported as scientific runs.'})
# Pin every high-level external artifact named by the seven final audits. Exact
# trace bytes are copied; other originals remain external even when readback JSON
# embeds their parsed contents. The large capture is never opened here.
refs={}
def external_refs(x,audit):
 if isinstance(x,dict):
  if isinstance(x.get('path'),str) and x['path'].startswith('/mnt/seagate10tb/') and isinstance(x.get('sha256'),str):
   key=(x['path'],x['sha256']);record=refs.setdefault(key,{'original':{k:x[k] for k in ['path','sha256','bytes'] if k in x},'cited_by':[],'disposition':'original_external_compact_audit_and_readback_copied'})
   if audit not in record['cited_by']:record['cited_by'].append(audit)
  for v in x.values():external_refs(v,audit)
 elif isinstance(x,list):
  for v in x:external_refs(v,audit)
for n,a in audits.items():external_refs(a,ev(n))
for _,(rel,art) in traces.items():
 record=refs[(art['path'],art['sha256'])];record['disposition']='exact_bytes_copied';record['publication_relative']=ev(rel)
# Correct explicit copy/source attribution; never infer acquisition from a
# coincidental empty digest or from matching source bytes alone.
for artifact, local in [
 (B['result'], 'tangent-capture-build03-result.json'),
 (T['standalone_stderr'], 'tangent72-diagnostic01/actual-standalone-stderr01.log'),
 (T['preserved_attempt01']['log'], 'nominal-tangent-capture03-worker-failure.log')]:
 assert pin(C/local)['sha256']==artifact['sha256']
 record=refs[(artifact['path'],artifact['sha256'])]
 record['disposition']='exact_original_bytes_copied_from_recorded_local_capture'
 record['publication_relative']=ev(local)
for audit,local in [(Q,'tangent72-diagnostic03/replay.cpp'),(W,'tangent72-diagnostic05/replay.cpp')]:
 artifact=audit['source'];assert pin(C/local)['sha256']==artifact['sha256']
 record=refs[(artifact['path'],artifact['sha256'])]
 record['disposition']='identical_reviewed_local_source_bytes_copied_not_remote_acquisition'
 record['publication_relative']=ev(local)
record=refs[(Q['stderr']['path'],Q['stderr']['sha256'])]
assert Q['stderr']['sha256']==T['standalone_stderr']['sha256']
record['disposition']='identical_bytes_retained_from_earlier_telemetry_stderr_not_separate_remote_copy'
record['publication_relative']=ev('tangent72-diagnostic01/actual-standalone-stderr01.log')
capture=refs[(T['capture']['path'],T['capture']['sha256'])]
capture['disposition']='bulky_captured_system_external_not_read_by_publication'
jput('external-evidence.json',{'schema':'orbit-poc-tangent-diagnosis-external-v1','entries':list(refs.values()),'capture':T['capture'],'capture_read_by_publication':False,'native_binaries_copied':False,'scope':'This ledger indexes high-level originals from final audits. Complete build/runtime/input inventories remain in the copied exact readbacks and build result. Parsed embedded JSON is not represented as an exact-byte copy of its external original. No new remote scans were performed.'})
summary={
 'schema':'orbit-poc-tangent-diagnosis-publication-v1','packaged_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'evidence_observations_through':W['reviewed_at'],
 'v4_benchmark_fit_attempts':0,'v4_benchmark_planned_attempts':68,'release_ready':False,'full_native_closure_verified':False,'covariance_authorized':False,'production_fix_verified':False,
 'case':'leo500-disturbed-blackout-groops_pulses-72h','tolerance':2e-12,'maximum_iterations':120,'restart':20,
 'original_native':A['native'],'capture_native':T['native'],'capture':T['capture'],'capture_dimensions':T['capture_dimensions'],
 'original_replay':{'finished_at':A['finished_at'],'native_status':A['native_status'],'exact_failure_reproduced':A['exact_failure_reproduced'],'native_evaluations':1,'owned_identities_non_live':A['owned_identities_non_live']},
 'original_trace':{'records':198,'projected_records':120,'true_records':76,'terminal':base[-1],'best_true_record':best,'cycle_lengths':dict(sorted(collections.Counter(cycles).items())),'maximum_cycle_length':max(cycles),'restart_limit_reached':False,'iteration5_projected':projected[4]['relative_residual'],'iteration5_true':true[1]['native_relative_residual']},
 'original_iterates_quad_check':{'preserved_baseline_rows':198,'records':Q['quad_records'],'terminal':Q['terminal'],'groops_propagations':0},
 'wide_update_experiment':{'preserved_initial_rows':7,'terminal':W['terminal'],'quad_records':W['quad_records'],'groops_propagations':0,'numerical_delta':audits['tangent72-wide-update05-independent-review01.json']['numerical_delta'],'source_review':ev('tangent72-wide-update05-independent-review01.json'),'terminal_review':ev('captured-tangent02-terminal-independent-review01.json')},
 'diagnostic_total_groops_evaluations':2,'publication_native_runs':0,'publication_remote_scans':0,
 'interpretation':['A large gap separates the projected Krylov residual from the recomputed true residual; the unchanged guard correctly rejects the original iterates.','The independent 113-bit calculation also rejects the original iterations six and120. It does not justify accepting a numerical floor.','Wide cycle-update accumulation passes this one captured system, including the independent accepted-state residual. It does not establish a unique cause, full trajectory closure, fit convergence, covariance or release readiness.','The update changes product/accumulation precision and subsequent iterates. No claim isolates a single rounding mechanism.'],
 'original150':'Separate frozen campaign. No new observation or result imported in this report; see the dated prior ten-terminal snapshot.',
 'prior_reports':{'preparation_failure':'../preparation03-failure01/index.html','full14':'../validation04/index.html','shifted02':'../shifted02/index.html','original150_historical':'../status-preparation-original150-05/index.html'},
 'primary_audits':[{**pin(C/n),'publication_relative':ev(n)} for n in AUDITS],
 'publication_revision':{'previous_manifest':pin(R/'publication-tangent-diagnosis01/manifest.json'),'change':'Correct external artifact copy/source attribution only; scientific data, results, traces and scope unchanged.'},
 'preservation':{'source_text_files':244,'source_text_bytes':2217365,'failed_records':len(failures),'capture_bytes_external':27786112,'empty_failed_json_preserved_as_raw_text':[x['relative'] for x in inventory['entries'] if x['json_document_valid'] is False]}}
jput('summary.json',summary)
e=html.escape
audit_links=''.join('<li><a href="'+e(ev(n))+'">'+e(n)+'</a></li>' for n in AUDITS)
failure_rows=''.join('<tr><td>'+e(x['id'])+'</td><td>'+e(x['classification'].replace('_',' '))+'</td><td>'+e(x['description'])+' <a href="'+e(x['evidence'][0])+'">Evidence</a></td></tr>' for x in failures)
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>72-hour tangent diagnosis: captured-system precision experiment</title><style>body{font:16px/1.6 system-ui;max-width:1120px;margin:3rem auto;padding:0 1.3rem;color:#172737}table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{padding:.65rem;border-bottom:1px solid #ccd4df;text-align:left;vertical-align:top}.scope{background:#fff1e4;border-left:4px solid #a45d21;padding:1rem}a{color:#164e89}code{overflow-wrap:anywhere}small{color:#506273}</style><h1>72-hour tangent diagnosis</h1><p class="scope"><strong>The precision experiment passed one captured linear system. Full native trajectory closure remains unverified; 0/68 V4 benchmark fits have started.</strong> This package ends with the independently audited candidate05 captured-system result at 07:39:33 UTC on 16 October 2026. It does not establish a production fix, covariance or release readiness.</p><p>The <a href="../preparation03-failure01/index.html">preserved 72-hour disturbed/blackout preparation failure</a> occurred inside the coupled six-state tangent solve. The unchanged original executable reproduced its exact failure signature. A separate capture build first relinked the original objects to the original executable bytes, then added capture-only instrumentation. The native call and same-compiler reader reproduced the failure again on the same coefficients, fixed state and unchanged tolerances.</p><h2>Measured results</h2><table><thead><tr><th>Evaluation</th><th>Iteration</th><th>Native true relative residual</th><th>Independent 113-bit residual</th><th>Unchanged 2e-12 criterion</th></tr></thead><tbody><tr><td>Original best recomputed iterate</td><td>6</td><td>2.0546669696740676e-12</td><td>2.1655994428095743e-12</td><td>Fail</td></tr><tr><td>Original terminal iterate</td><td>120</td><td>1.503709478355439e-11</td><td>1.49884622244851e-11</td><td>Fail</td></tr><tr><td>Candidate05 captured-system update</td><td>7</td><td>1.7564764459600119e-12</td><td>1.6558481483345173e-12</td><td>Pass for this captured system</td></tr></tbody></table><p>At iteration five, the projected Krylov residual was 1.712331304520431e-14 while the recomputed native residual was 1.0349379487509937e-11. The original 75 cycles had lengths one, two or five; the restart limit of 20 was never reached. The native true-residual check correctly rejected the small projected residual. The 113-bit evaluator acts on the same original double iterate and coefficient data; its native-velocity-conversion results are shown above. Separately recorded exact-conversion values give the same pass/fail classifications.</p><p>Candidate05 replaces sequential double updates at the end of each Krylov cycle with a long-double affine sum, then casts once to the original double coordinate. The operator, preconditioner, Arnoldi orthogonalization, small triangular solve, restart limit, 120-iteration cap and true-residual threshold remain unchanged. The first seven trace records agree exactly; later iterates differ. The accepted double iterate also passes the independent 113-bit check. This supports the effectiveness of the update in this captured case; it does not isolate a unique rounding mechanism or establish full nonlinear closure. No numerical-floor acceptance or threshold relaxation is justified.</p><h2>Exact traces and attribution</h2><ul><li><a href="evidence/tangent72-diagnostic01/actual-standalone-trace01.jsonl">Original trace: 198 records</a></li><li><a href="evidence/tangent72-diagnostic03/actual-trace01.jsonl">Unchanged original trace plus two 113-bit evaluations</a></li><li><a href="evidence/tangent72-diagnostic05/actual-trace01.jsonl">Candidate05 trace and accepted-state 113-bit evaluation</a></li><li><a href="summary.json">Machine-readable result and scope</a></li><li><a href="external-evidence.json">External capture, binaries and original artifact identities</a></li><li><a href="source-inventory.json">Exact selected local source/evidence inventory</a></li><li><a href="manifest.json">Publication byte manifest</a></li></ul><p>The 27,786,112-byte captured system remains external, pinned by SHA-256 <code>b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2</code>. It contains 51,840 epochs, 51,839 intervals and 414,712 quadrature terms at a five-second step. No captured array or binary was copied or re-read by this publication. Exact local readbacks preserve compiler, link-input, source and input attribution; parsed embedded JSON is distinguished from exact-byte copies of external originals.</p><h2>Independent audits</h2><ul>'''+audit_links+'''</ul><p>The two native evaluations failed their numerical guards; their attribution and cleanup audits passed. Both later standalone experiments performed zero GROOPS propagations and zero fits. The source-review and actual-result reviews are separate records. All audited owned processes were non-live at their recorded terminal checks; no current process state is inferred.</p><h2>Preserved failures and control mistakes</h2><p>Scientific outcomes, precompile/pre-native control failures and author/reviewer mistakes have separate classifications. The <a href="failure-ledger.json">machine-readable ledger</a> links their original evidence. Empty failed JSON readbacks retain their exact bytes under <code>.raw.txt</code> names. The author insertion-script exception was observed in tool output but has no independently saved raw stderr file; its two source versions are retained without inventing a raw log.</p><table><thead><tr><th>Record</th><th>Classification</th><th>Preserved finding</th></tr></thead><tbody>'''+failure_rows+'''</tbody></table><h2>Release boundary</h2><p>The earlier <a href="../validation04/index.html">14-stage validation</a> and <a href="../shifted02/index.html">shifted-cut tests</a> retain their tested scope. This diagnosis neither replaces the failed preparation nor completes the 68-fit campaign. Full native closure, the unchanged correctness suite and subsequent preparation remain required. The original 150-attempt benchmark remains a separate frozen campaign; its <a href="../status-preparation-original150-05/index.html">dated ten-terminal observation</a> is not a current-running claim. Later native-candidate build or trajectory outcomes belong in separate evidence.</p></html>'''
put('index.html',page.encode())
# Recheck all copied sources after generation; no mutable external state is read.
for item in inventory['entries']:
 ident=pin(item['path']);assert ident['sha256']==item['sha256'] and ident['bytes']==item['bytes']
entries=[{'relative':str(p.relative_to(O)),'sha256':pin(p)['sha256'],'bytes':p.stat().st_size} for p in sorted(O.rglob('*')) if p.is_file()]
jput('manifest.json',{'schema':'orbit-poc-tangent-diagnosis-publication-manifest-v1','entries':entries,'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'source_inventory':pin(I),'builder':pin(Path(__file__)),'primary_audits':[{**pin(C/n)} for n in AUDITS],'external_capture':T['capture'],'native_runs_by_publication':0,'release_ready':False})
print(json.dumps({'root':str(O),'manifest':pin(O/'manifest.json'),'files':len(entries),'bytes':sum(x['bytes'] for x in entries)}))
