from pathlib import Path
import hashlib,json,datetime,collections
B=Path('/home/emper/orbit-nuisance-performance');W=B/'wholefit01';A=B/'control/wholefit-outcome-audit01';R=Path('/mnt/d/orbit-nuisance-performance/publication/wholefit01-results')
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):p=Path(p);return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def save(n,v):p=A/n;p.open('x').write(json.dumps(v,indent=2,sort_keys=True)+'\n');return pin(p)
new=read(A/'checker.json');old=read(R/'checker.json');freeze=read(W/'freeze.json');repro=read(A/'reproduction-execution.json');terminal=read(W/'execution-complete.json');auto=read(R/'summary.json')
assert [k for k in set(new)|set(old) if new.get(k)!=old.get(k)]==['created_at']
assert new['analysis_status']=='valid' and new['issues']==[] and new['scientific_equivalence']=={'status':'not_evaluable'} and not new['whole_fit_complete_pair'] and not new['release_authority']
assert repro['returncode']==0 and repro['protected_unchanged'] and repro['tool_pins_unchanged']
assert terminal['all_attempts_executed'] and terminal['freeze_sha256']==sha(W/'freeze.json')
verified={(x['path'],x['uncompressed']):x for x in new['evidence']}
for p in freeze['pinned_files']:
 e=verified[(str(Path(p['path']).resolve()),False)];assert e['sha256']==p['sha256']
 if 'bytes'in p:assert e['bytes']==p['bytes']
assert len(freeze['pinned_files'])==1059
outcomes=[];owned={}
for idx,name in enumerate(('cache1','cache0')):
 run=next(r for r in new['runs'] if r['name']==name);res=read(W/name/'result.json');sup=read(W/name/'supervisor.json');env=read(W/name/'effective-environment.json');post=read(W/name/'post-input-check.json')
 assert terminal['outcomes'][idx]['name']==name and terminal['outcomes'][idx]['result_sha256']==sha(W/name/'result.json') and terminal['outcomes'][idx]['status']=='timeout'
 assert res['status']==sup['status']==run['outcome']=='timeout' and not res['converged'] and not res['covariance_valid'] and not run['accepted_covariance'] and not run['scientific_complete']
 assert sup['returncode']==-15 and sup['owned_process_group_cleaned'] and sup['cleanup']['verified'] and sup['cleanup']['remaining']==[] and sup['cleanup']['empty_tree_certificate']=='kernel_ECHILD'
 assert sup['elapsed_seconds']>=7200 and sup['peak_process_tree_rss_bytes']<8*1024**3 and sup['signals_received']==[]
 assert post['verified'] and post['freeze_sha256']==sha(W/'freeze.json') and post['pinned_file_count']==1059
 assert env['cpu_affinity']==[0] and env['environment']['ORBIT_POC_NUISANCE_INTERPOLATION_CACHE']==name[-1] and env['environment']['ORBIT_POC_NUISANCE_PERFORMANCE']=='1'
 assert all(env['environment'][k]=='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS'))
 assert run['cache_treatment_verified'] and run['issues']==[]
 for p in sup['tracked_owned_processes']+[sup['supervisor'],sup['worker']]:owned[(sup['boot_id'],p['pid'],p['start_ticks'])]=p
 pointrows=[]
 for pointname,p in run['points'].items():
  complete=p['profile_complete'];profile=p.get('profile',{})
  if complete:assert p['classification']=='strict_nuisance_convergence' and profile['nuisance_converged'] and not profile['nuisance_floor_limited'] and profile['fixed_weights'] and not profile['dynamic_updates']
  assert p['issues']==[]
  pointrows.append({'name':pointname,'strict_nuisance_profile_complete':complete,'nuisance_iterations':profile.get('iterations'),'sidecar_count':p.get('sidecar_count'),'profile_command_wall_seconds':p.get('profile_elapsed_seconds'),'covariance_authorized':False})
 checkpoint=W/name/'iterations.json'
 opt=None
 if checkpoint.exists():
  v=read(checkpoint);assert v['status']=='running' and v['accepted_iterations']==2 and v['trial_evaluations']==2 and v['confirmation_checks']==[]
  assert [x['trial'] for x in v['history']]==[1,2] and all(x['accepted'] for x in v['history'])
  for k,row in enumerate(v['history'],1):
   pp=W/name/f'point-{k+3:03d}-trial-{k:03d}';profile=read(pp/'qr.profile.json');cost=read(pp/f"qr.{profile['iterations']+1}.profile.json")['direct_cost'];assert cost==row['objective_trial'] and row['actual_reduction']>0 and row['gain_ratio']>1e-4
  assert v['history'][0]['objective_trial']==v['history'][1]['objective_before']
  opt={'checkpoint':pin(checkpoint),'status':'running','accepted_steps_recorded':2,'completed_trial_decisions_recorded':2,'next_trial_started':3,'final_confirmation_checks':0,'scope':'Progress checkpoint only; no whole-fit convergence.'}
 else:opt={'checkpoint':None,'accepted_steps_recorded':0,'completed_trial_decisions_recorded':0,'next_trial_started':1,'scope':'No optimizer decision checkpoint was written. These are recorded-decision counts, not inferred unrecorded decisions.'}
 outcomes.append({'name':name,'cache':int(name[-1]),'outcome':'timeout','monotonic_supervisor_seconds':sup['elapsed_seconds'],'peak_process_tree_rss_bytes':sup['peak_process_tree_rss_bytes'],'cleanup_verified':True,'post_input_identity_verified':True,'effective_environment':pin(W/name/'effective-environment.json'),'completed_nuisance_profiles':sum(p['strict_nuisance_profile_complete'] for p in pointrows),'points':pointrows,'recorded_parent_cache_hits':run['recorded_parent_cache_hits'],'optimizer_progress':opt,'result':pin(W/name/'result.json'),'supervisor':pin(W/name/'supervisor.json'),'accepted_covariance':False,'whole_fit_converged':False})
assert [x['completed_nuisance_profiles'] for x in outcomes]==[5,3]
assert outcomes[0]['recorded_parent_cache_hits']>0 and outcomes[1]['recorded_parent_cache_hits']==0
comparisons=new['partial_point_comparisons'];counts=[]
for c in comparisons:
 rows=c['scientific_comparisons'];counts.append({'name':c['name'],'status':c['status'],'comparisons':len(rows),'equal':sum(x['equal'] for x in rows),'comparison_scopes':dict(collections.Counter(x['scope'] for x in rows))});assert not c['issues'] and all(x['equal'] for x in rows)
assert [c['comparisons'] for c in counts]==[159,159,159,47,0,0]
assert [c['status'] for c in counts]==['equal_completed_point']*3+['equal_available_prefix','unmatched_progress','unmatched_progress']
prefix=save('prefix-equality.json',{'schema':'orbit-poc-wholefit-independent-prefix-equality-v1','checker':pin(A/'checker.json'),'summary':counts,'comparisons':comparisons,'scope':'Matching physical initial state/fixed force/full pulses verified. Retained uncompressed bytes or canonical scientific values use declared CPU/RSS/output-path normalization only. Deleted factor identities are separately attributed to exact retention receipts. No full-fit or covariance acceptance.','direct_comparisons':422,'pre_release_identity_comparisons':102,'scientific_equivalence':'not_evaluable','release_authority':False})
assert sum(c['comparison_scopes'].get('direct bytes/values',0) for c in counts)==422 and sum(c['comparison_scopes'].get('recorded pre-release identity',0) for c in counts)==102
clock=read(B/'control/wholefit-clock-observation01/observation.json');assert abs(clock['utc_since_controller_launch_seconds']-clock['supervisor_elapsed_seconds']-clock['difference_seconds'])<1e-9
for key,file in [('observation','annotation-0-observation.json'),('supervisor_snapshot','annotation-0-supervisor_snapshot.json')]:assert sha(R/file)==auto['annotations'][0][key]['sha256']
assert auto['timing_comparison']=='compromised' and auto['speedup_claim'] is None and auto['utc_two_hour_budget_compliance']=='not_established' and auto['independent_outcome_audit']=='pending'
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();live=[];states=[]
for (recordedboot,pid,start),oldstate in sorted(owned.items()):
 p=Path('/proc')/str(pid)/'stat';state={'recorded_boot_id':recordedboot,'pid':pid,'start_ticks':start}
 if recordedboot!=boot:state['current_status']='different_boot'
 elif not p.exists():state['current_status']='absent'
 else:
  raw=p.read_text();fields=raw[raw.rfind(')')+2:].split();state.update(current_start_ticks=int(fields[19]),state=fields[0]);state['current_status']='reused_pid' if int(fields[19])!=start else 'zombie' if fields[0]=='Z' else 'live_owned_identity'
  if state['current_status']=='live_owned_identity':live.append(state)
 states.append(state)
assert live==[]
cleanup=save('owned-identities-observation.json',{'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'current_boot_id':boot,'identities':states,'live_owned_identities':live,'scope':'Read-only named proc identities; historical kernel_ECHILD cleanup receipts retained independently.'})
audit={'schema':'orbit-poc-wholefit-actual-outcomes-independent-audit-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'accepted_preserved_timeout_outcomes_and_partial_prefix_evidence','source_head':'301722c6238925a1c5a9521f960254ca4dffbc1d','freeze':pin(W/'freeze.json'),'frozen_files_verified':1059,'frozen_source_files_verified':318,'actual_evidence_files_or_uncompressed_views':len(new['evidence']),'checker':pin(B/'source/scripts/analyze_nuisance_wholefit.py'),'checker_review':pin(B/'control/wholefit-checker-review03/independent-review03.json'),'reproduction':{'plan':pin(A/'reproduction-plan.json'),'execution':pin(A/'reproduction-execution.json'),'stdout':pin(A/'stdout.log'),'stderr':pin(A/'stderr.log'),'result':pin(A/'checker.json'),'result_differs_from_original_only_in':['created_at'],'native_runs':0},'original_automatic_report':{'checker':pin(R/'checker.json'),'summary':pin(R/'summary.json'),'preserved_unchanged':True,'pending_audit_field_left_unchanged':True},'execution_complete':pin(W/'execution-complete.json'),'outcomes':outcomes,'prefix_equality':prefix,'owned_cleanup':cleanup,'scientific_equivalence':{'status':'not_evaluable'},'accepted_covariance':False,'whole_fit_complete_pair':False,'timing_comparison':'compromised','speedup_claim':None,'utc_two_hour_budget_compliance':'not_established','clock_discrepancy':{'observation':pin(B/'control/wholefit-clock-observation01/observation.json'),'difference_seconds':clock['difference_seconds'],'cause':'unverified'},'limitations':['Both attempts are censored by the original monotonic7200-second limit; neither completes the prescribed full nonlinear solve.','Cache-enabled progress exceeds the disabled run in these retained records, but timing/host-clock discrepancy and one pair prevent a clean timing or speedup conclusion.','Prefix equality covers matching recorded numerical states and shared scientific artifacts only.524 matches comprise422 retained-byte/canonical-value comparisons plus102 recorded pre-release factor identities.','Only the original declared resource fields and output/spool paths are normalized; no objective/prior/weight/threshold/scientific value relaxed.','Local candidate/exporter runtime is identical across arms but includes six system-library differences from the original remote timeout; no historical-runtime equivalence claim.','Strict nuisance convergence at individual fixed physical points is not strict whole-orbit convergence or accepted covariance.','Recorded optimizer decisions are distinct from an incomplete trial and from a final result.','Original reports, frozen1059-file protocol, inputs, native binary, attempts and frozen remote campaign remain unchanged.'],'changes_to_science_or_execution':False,'native_runs':0,'release_authority':False}
receipt=save('independent-audit01.json',audit);print(json.dumps({'audit':receipt,'prefix':prefix,'cleanup':cleanup,'outcomes':[{'name':x['name'],'outcome':x['outcome'],'strict_profiles':x['completed_nuisance_profiles']} for x in outcomes]},indent=2))
