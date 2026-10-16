"""Publish the independently audited fixed-state native closure supplement."""
from pathlib import Path
import datetime,hashlib,html,json,subprocess
R=Path('/mnt/d/orbit-segmented-v4');C=R/'control';O=R/'publication-candidate-native-closure02'
def pin(p):
 p=Path(p);assert p.is_file() and not p.is_symlink(),p;b=p.read_bytes()
 return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):return json.loads(Path(p).read_text())
def put(rel,b):
 p=O/rel;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f:f.write(b)
def jput(rel,v):put(rel,(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
audits={
 'tangent-precision-build01-terminal-independent-review01.json':'0fcbe2817d023b20fc99edd47486309b785c88ca980022316c71b00d4e86eea7',
 'nominal-precision-closure01-terminal-independent-review01.json':'00f8cfc962ba71cb9d118dbb0daac0b92322adcf10ba73d769b7e04381ae8eb5'}
for n,h in audits.items():assert pin(C/n)['sha256']==h and read(C/n)['passed']
B=read(C/'tangent-precision-build01-terminal-independent-review01.json');A=read(C/'nominal-precision-closure01-terminal-independent-review01.json')
D=read(C/'nominal-precision-closure01-terminal-independent-readback01.json')
T=read(C/'nominal-precision-closure01-terminal.json');V=T['run/replay/result.json']['value'];P=T['control/pipeline.json']['value']
assert pin(B['readback']['path'])==B['readback'] and pin(A['readback']['path'])==A['readback']
assert pin(C/'tangent-precision-build01-result.json')['sha256']==B['result']['sha256']
assert A['native']==B['native'] and A['native_propagations']==4 and A['fit_attempts']==0 and A['release_ready'] is False
assert P['status']=='passed_diagnostic' and P['final_cleanup']['verified'] and V['converged']
assert V['initialization_criteria']=={'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}
assert [x['closed'] for x in V['iterations']]==[False,False,False,True]
assert len(A['iteration_metrics'])==len(D['independently_recomputed_iterations'])==len(V['iterations'])==4
for x,y,z in zip(A['iteration_metrics'],D['independently_recomputed_iterations'],V['iterations']):
 assert x=={k:y[k] for k in x}
 assert all(x[k]==z[k] for k in ['iteration','maximum_position_change_m','maximum_velocity_change_m_s','closed'])
 assert x['fixed_initial_state_exact'] and x['epoch_support_exact'] and z['initial_state_error_si']==[0]*6
 assert z['execution']['returncode']==0 and z['execution']['timed_out'] is False and z['execution']['native_binary_sha256']==A['native']['sha256']
assert A['iteration_metrics'][-1]['maximum_position_change_m']==2.4870890451505247e-7
assert A['iteration_metrics'][-1]['maximum_velocity_change_m_s']==2.755874001513291e-10
assert B['candidate_header_sha256']=='1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28'
assert pin(C/'sixStateTangent-precision-native01.h')['sha256']==B['candidate_header_sha256']
commit='677c68cc851234b9ad89d45de4dd6fdc43fd2dec'
def git(*args):return subprocess.check_output(['git','-C',str(R/'source'),*args])
assert git('rev-parse',commit).decode().strip()==commit
assert git('diff-tree','--no-commit-id','--name-only','-r',commit).decode().splitlines()==['groops/extension/sixStateTangent.h']
assert hashlib.sha256(git('show',commit+':groops/extension/sixStateTangent.h')).hexdigest()==B['candidate_header_sha256']
S={p for p in C.iterdir() if p.is_file() and p.name.startswith(('nominal-precision-closure01-','tangent-precision-build01-')) and p.suffix in {'.json','.log','.xml','.stdout','.stderr'}}
for n in ['audit_nominal_precision_closure01_terminal.py','audit_tangent_precision_build01_terminal.py','author_tangent_precision_build01.py','build_tangent_precision01.py','check_nominal_precision_closure01_mapping.py','replay_nominal_precision_closure01.py','run_nominal_precision_closure01.py','run_tangent_precision_build01.py','stage_nominal_precision_closure01.py','stage_tangent_precision_build01.py','test_replay_nominal_precision_closure01.py','test_tangent_precision_build01.py','sixStateTangent-precision-native01.h']:
 S.add(C/n)
for n in ['result.json','pytest01.log']:S.add(C/'tangent-production-kernel01'/n)
F=read(C/'tangent-affine-regression01/summary.json')
assert pin(C/'tangent-affine-regression01/summary.json')['sha256']=='c234906eb4fc4980f4dc32e7d184e1922a15cb74555d0b1a5752c58c77ac4b88'
assert F['final_search_stronger_margin_found'] is False
assert [x['paired_settings'] for x in F['searches']]==[1650,1650,1200]
assert [x['pass_status_counts'].get("('1', '0')",0) for x in F['searches']]==[102,4,1]
assert pin(C/'tangent-affine-pinned01/result.json')==F['pinned_compiler_author_record']
for name in ['summary.json','fixture.cpp','fixture02.cpp','coefficients01.h','fixed-outcomes01.json','fixed-outcomes02.json','search.cpp','search02.cpp','search03.cpp']:
 S.add(C/'tangent-affine-regression01'/name)
S.add(C/'tangent-affine-pinned01/result.json')
sources=[]
for p in sorted(S):
 b=p.read_bytes();b.decode();rel='evidence/'+str(p.relative_to(C));sources.append({'relative':rel,'source':pin(p)})
assert not O.exists();O.mkdir()
for x in sources:put(x['relative'],Path(x['source']['path']).read_bytes())
put('provenance/package_candidate_native_closure02.py',Path(__file__).read_bytes())
for name in ['manifest.json','summary.json']:
 put('preserved-publication01/'+name,(R/'publication-candidate-native-closure01'/name).read_bytes())
jput('source-inventory.json',{'schema':'orbit-poc-native-closure-supplement-sources-v1','entries':sources,'files':len(sources),'bytes':sum(x['source']['bytes'] for x in sources)})
jput('provenance/source-commit.json',{'schema':'orbit-poc-native-precision-source-commit-v1','commit':commit,'changed_paths':['groops/extension/sixStateTangent.h'],'header_sha256':B['candidate_header_sha256'],'commit_metadata':git('show','--format=fuller','--no-patch',commit).decode(),'source_read_only_verification':True,'published_state_not_checked_by_this_builder':True})
refs={}
def refs_in(x,source):
 if isinstance(x,dict):
  if isinstance(x.get('path'),str) and x['path'].startswith('/mnt/seagate10tb/') and isinstance(x.get('sha256'),str):
   key=(x['path'],x['sha256']);r=refs.setdefault(key,{'original':{k:x[k] for k in ['path','sha256','bytes'] if k in x},'cited_by':[],'disposition':'external_original_compact_audit_readback_copied'})
   if source not in r['cited_by']:r['cited_by'].append(source)
  for v in x.values():refs_in(v,source)
 elif isinstance(x,list):
  for v in x:refs_in(v,source)
refs_in(B,'evidence/tangent-precision-build01-terminal-independent-review01.json')
refs_in(A,'evidence/nominal-precision-closure01-terminal-independent-review01.json')
refs_in(D,'evidence/nominal-precision-closure01-terminal-independent-readback01.json')
r=refs[(B['result']['path'],B['result']['sha256'])];r['disposition']='exact_original_bytes_copied';r['publication_relative']='evidence/tangent-precision-build01-result.json'
trajectory=[x for row in D['independently_recomputed_iterations'] for x in row['artifacts'] if Path(x['path']).name in {'nominal.txt','nominal.dat','variational.dat'}]
assert len(trajectory)==12
for x in trajectory:refs[(x['path'],x['sha256'])]['disposition']='large_trajectory_external_not_read_by_publication'
jput('external-evidence.json',{'schema':'orbit-poc-native-closure-supplement-external-v1','entries':list(refs.values()),'large_trajectory_files':12,'large_trajectory_bytes':sum(x['bytes'] for x in trajectory),'scope':'The independent audit read/recomputed all four trajectories. This publication copies compact records only and performs no trajectory or remote rescan. Original propagation XML/logs and execution records remain external with exact pins. Parsed result JSON is not claimed to be an exact-byte copy of the original result; the build result is copied exactly.'})
summary={'schema':'orbit-poc-native-closure-supplement-v1','packaged_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'finished_at':A['finished_at'],'audit_completed_at':A['reviewed_at'],'case':'leo500-disturbed-blackout-groops_pulses-72h','fixed_state_native_closure_passed':True,'fit_attempts':0,'v4_benchmark_fits_started':0,'v4_benchmark_fits_planned':68,'release_ready':False,'complete_validation_passed_for_candidate':False,'covariance_authorized':False,'prepared_benchmark_complete':False,'candidate_commit':commit,'candidate_header_sha256':B['candidate_header_sha256'],'native':A['native'],'original_native_sha256':B['baseline_relinked_sha256'],'original_source_files_verified':A['source_files_verified'],'original_inputs_verified':A['original_inputs_verified'],'initialization_criteria':V['initialization_criteria'],'fixed_initial_state_si':V['fixed_initial_state_si'],'iteration_metrics':A['iteration_metrics'],'native_propagations':4,'elapsed_controller_seconds':P['elapsed_seconds'],'peak_owned_rss_bytes':P['peak_owned_rss_bytes'],'owned_identities_non_live':A['owned_identities_non_live'],'native_build':{'recompiled_objects':B['recompiled_objects'],'changed_objects':B['changed_objects'],'reused_objects':B['reused_objects'],'pinned_link_inputs_verified':B['pinned_link_inputs_verified'],'owned_identities_non_live':B['owned_identities_non_live']},'interpretation':'The original failed fixed-state72h inputs now close under the separately versioned precision candidate. This proves that bounded native diagnostic only, not estimation convergence, a completed preparation or the full correctness/benchmark requirements. Earlier failed preparation and diagnostic attempts remain unchanged.','prior_reports':{'captured_system_diagnosis':'../tangent-diagnosis02/index.html','original_failed_preparation':'../preparation03-failure01/index.html','original150_historical':'../status-preparation-original150-05/index.html'},'author_kernel_tests':read(C/'tangent-production-kernel01/result.json'),'publication_native_runs':0,'publication_remote_scans':0,'primary_audits':[pin(C/n) for n in audits]}
summary['bounded_external_fixture']={
 'summary':pin(C/'tangent-affine-regression01/summary.json'),
 'pinned_compiler_repetition':pin(C/'tangent-affine-pinned01/result.json'),
 'classification':F['classification'],'selected_result':{'original':F['original_result'],'candidate':F['candidate_result']},
 'search_setting_counts':[x['paired_settings'] for x in F['searches']],
 'old_passes_candidate_fails_by_search':[x['pass_status_counts'].get("('1', '0')",0) for x in F['searches']],
 'final_search_stronger_margin_found':False,'limitations':F['limitations'],
 'portable_acceptance_gate':False,'production_or_validation_freeze_changed':False,
 'preserved_reporting_correction':F['preserved_initial_reporting']}
summary['publication_revision']={'prior_manifest':pin(R/'publication-candidate-native-closure01/manifest.json'),'reason':'Append separately completed bounded fixture evidence and its limitations; native closure metrics and scope unchanged.'}
jput('bounded-fixture-external.json',{'schema':'orbit-poc-bounded-fixture-external-v1','raw_search_results':[{'original':x[k],'disposition':'external_csv_not_copied_or_recomputed_by_publication'} for x in F['searches'] for k in ['old_results','new_results']],'classification':'Exploratory outcome-selected literal linear systems, not an orbital force model or a portable automated gate. Counts are transcribed from the independently produced sealed summary, not recomputed here.'})
jput('summary.json',summary)
e=html.escape
table=''.join('<tr><td>'+str(x['iteration'])+'</td><td>'+format(x['maximum_position_change_m'],'.16g')+'</td><td>'+format(x['maximum_velocity_change_m_s'],'.16g')+'</td><td>'+str(x['closed']).lower()+'</td></tr>' for x in A['iteration_metrics'])
page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Native precision candidate: exact 72-hour closure</title><style>body{font:16px/1.6 system-ui;max-width:1080px;margin:3rem auto;padding:0 1.3rem;color:#172737}table{border-collapse:collapse;width:100%;font-size:.9rem}td,th{padding:.7rem;border-bottom:1px solid #ccd4df;text-align:left}.scope{background:#eaf1fb;border-left:4px solid #3164a0;padding:1rem}a{color:#164e89}code{overflow-wrap:anywhere}</style><h1>Native precision candidate closes the exact 72-hour case</h1><p class="scope"><strong>The fixed-state native diagnostic passed in four propagations. V4 still has 0/68 benchmark fits and is not ready for release.</strong> The terminal result at 07:52:35 UTC on 16 October 2026 passed independent audit at 07:55:45 UTC. This is a separate supplement to the <a href="../tangent-diagnosis02/index.html">captured-system experiment</a>; it preserves the earlier failed attempts.</p><p>The candidate accumulates each end-of-cycle tangent update in long double before storing the original double state. The operator, preconditioner, Arnoldi arithmetic, small triangular solve, native residual guard and iteration limits remain unchanged. Only <code>sixStateTangent.h</code> changed in source commit <a href="https://github.com/FlorianPfaff/orbit-smoothing-poc/commit/677c68cc851234b9ad89d45de4dd6fdc43fd2dec">677c68c</a>. This is a numerical precision change, with physical models, priors, weights and hyperparameters preserved.</p><h2>Exact original inputs and closure</h2><p>The diagnostic reuses all 13 original failure inputs, the original fixed initial state, original profile and epoch support. It does not rerun GNSS preprocessing or initialization. Each propagation recomputes the full trajectory; later iterations use the preceding orbit. The independent audit loaded all four saved 51,840-epoch trajectories and recomputed every change below.</p><table><thead><tr><th>Propagation</th><th>Maximum position change (m)</th><th>Maximum velocity change (m/s)</th><th>Closed</th></tr></thead><tbody>'''+table+'''</tbody></table><p>The final changes are <strong>0.2487089045 µm</strong> and <strong>0.2755874002 nm/s</strong>, below the unchanged <strong>2 µm</strong> and <strong>3 nm/s</strong> closure limits. The cap remains ten iterations. The original initial state and epoch support match exactly at every iteration. This is trajectory closure at a fixed state, not nonlinear estimator convergence.</p><h2>Pinned build and verification</h2><p>The build recompiled all 27 dependency-derived translation units; 26 object hashes changed and 584 uncompiled objects retained their original bytes. All 637 original link inputs were verified. A baseline relink reproduced the original executable exactly. The existing segmented export hook was retained. Candidate executable SHA-256 is <code>eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133</code>; header SHA-256 is <code>1590e13ff3f69cb6841af8341737b8d52c4d618592070b61b4ae6516f2ea4c28</code>.</p><p>The separately recorded author kernel run passed five existing checks with four environment-dependent integration parametrizations explicitly deselected. Its first invocation had a missing-PYTHONPATH collection error and ran zero tests; that fact remains in the author result. Neither this small test run nor this closure replay substitutes for the full prescribed correctness suite.</p><p>All eight recorded closure-process identities and 65 build-process identities were non-live at their audited terminal checks. The closure controller took 9.945840873988345 seconds with 392,024,064-byte sampled peak process-tree RSS. Each propagation took about 1.9 seconds; the 600-second diagnostic call cap was not reached. These are diagnostic measurements, not comparative performance claims.</p><ul><li><a href="summary.json">Machine-readable scope, metrics and source identity</a></li><li><a href="evidence/nominal-precision-closure01-terminal-independent-review01.json">Independent native closure audit</a></li><li><a href="evidence/nominal-precision-closure01-terminal-independent-readback01.json">Independent recomputation and all trajectory pins</a></li><li><a href="evidence/tangent-precision-build01-terminal-independent-review01.json">Independent build attribution audit</a></li><li><a href="evidence/tangent-precision-build01-result.json">Exact native build result</a></li><li><a href="evidence/nominal-precision-closure01-terminal.json">Recorded controller/result snapshot</a></li><li><a href="external-evidence.json">External native, trajectory and propagation-control identities</a></li><li><a href="source-inventory.json">Copied local evidence inventory</a></li><li><a href="manifest.json">Publication byte manifest</a></li></ul><h2>Remaining boundary</h2><p>The full unchanged validation suite, fresh input preparation and all 68 planned fits remain required. This diagnostic does not authorize covariance, claim accuracy improvements or establish release readiness. The <a href="../preparation03-failure01/index.html">original preparation failure</a> and the failed captured-system iterations remain preserved. The original 150-attempt benchmark is separate; its <a href="../status-preparation-original150-05/index.html">dated snapshot</a> is not a new observation. Later validation outcomes belong in separate evidence.</p><p>Twelve large trajectory files and the native executable remain external. Their exact identities are preserved in the copied audit readback. This publication performed no native execution, trajectory rescan, remote scan or source change.</p></html>'''
page=page.replace('<h2>Remaining boundary</h2>', '<h2>Bounded small-system experiment</h2><p>A separate exploratory search used literal small linear systems and preserved all outcomes, including settings where the original update passed and the candidate failed: 102 of 1,650 in the first search, 4 of 1,650 in the second and 1 of 1,200 in the final search. The final 1,200 settings found no stronger-margin candidate success. These outcome-selected searches do not establish general robustness or independent scientific trials.</p><p>The selected three-epoch fixture repeats under local GCC15.2 O2/O3 and three pinned GCC15.3 O3 runs. Its candidate native residual, 1.9860811696140564e-12, has only about 0.7% margin below the unchanged guard; its independent 113-bit residual is 1.221177268479969e-12. The original native iterate fails its guard at 2.4710902817179282e-12 while the independent residual is 1.962114417858921e-12, showing that residual-evaluation rounding also contributes. This fixture is not a portable automatic acceptance gate. The exact 72-hour native replay remains the primary regression evidence.</p><p>The <a href="evidence/tangent-affine-regression01/summary.json">sealed fixture summary</a>, <a href="evidence/tangent-affine-pinned01/result.json">pinned compiler repetitions</a> and <a href="bounded-fixture-external.json">all six external raw-search result identities</a> preserve this limitation. Both initial and corrected fixture reports are included: the initial report displayed zero in its residual field after an exception while retaining the correct exception text; the corrected version parses that value without changing coefficients or the solver. No production file or validation freeze was changed by this experiment.</p><h2>Remaining boundary</h2>')
put('index.html',page.encode())
for x in sources:assert pin(x['source']['path'])==x['source']
entries=[{'relative':str(p.relative_to(O)),'sha256':pin(p)['sha256'],'bytes':p.stat().st_size} for p in sorted(O.rglob('*')) if p.is_file()]
jput('manifest.json',{'schema':'orbit-poc-native-closure-supplement-manifest-v1','entries':entries,'files':len(entries),'bytes':sum(x['bytes'] for x in entries),'primary_audits':[pin(C/n) for n in audits],'builder':pin(Path(__file__)),'native_runs_by_publication':0,'release_ready':False})
print(json.dumps({'root':str(O),'manifest':pin(O/'manifest.json'),'files':len(entries),'bytes':sum(x['bytes'] for x in entries)}))
