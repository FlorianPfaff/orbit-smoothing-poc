"""Package immutable one-hour cold-fit evidence; never starts estimation or edits original evidence."""
from pathlib import Path
from zoneinfo import ZoneInfo
import collections,csv,datetime,hashlib,json,math,shutil
B=Path('/mnt/d/orbit-v41-recovery02');R=B/'one-hour-run01';O=Path(__file__).parent;P=O/'packet'
COPIES=[];EXTERNAL=[]
def read(p):return json.loads(Path(p).read_text())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def pin(p):
 p=Path(p);return {'source':str(p),'bytes':p.stat().st_size,'sha256':sha(p)}
def save(p,d):p.write_text(json.dumps(d,indent=2)+'\n')
def copy(p,dest=None):
 p=Path(p);dest=dest or 'evidence/'+str(p.relative_to(B));q=P/dest
 if q.exists():assert sha(q)==sha(p);return dest
 assert p.is_file() and p.stat().st_size<5_000_000,str(p)
 q.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,q);COPIES.append({**pin(p),'path':dest});return dest
def external(p,reason,digest=None):
 p=Path(p)
 if any(x['source']==str(p) for x in EXTERNAL):return
 e=({'source':str(p),'sha256':digest,'bytes':p.stat().st_size if p.exists() else None,'hash_authority':'original completed backend receipt; not rehashed for publication'} if digest else {**pin(p),'hash_authority':'publication collector rehashed bytes'})
 EXTERNAL.append({**e,'reason':reason})
P.mkdir(exist_ok=False)
terminal=read(R/'result.json');assert terminal['planned_stages']==['cold-pulses','cold-density']
assert [x['status'] for x in terminal['stages']]==['passed','failed'] and terminal['status']=='failed'
plan=read(R/'plan.json');freeze=read(R/'freeze.json');assert freeze['plan']['sha256']==sha(R/'plan.json')
assert plan['cold_start'] and not plan['previous_results_reused']
for name in ['freeze.json','launch.json','detached-started.json','run-started.json','result.json','detached-result.json','prepared/preflight-result.json','prepared/execution.json','prepared/supervisor.json']:copy(R/name)
for name in ['plan.json','python-runtime.json']:external(R/name,'Full exact runtime/input inventory retained externally; compact plan and scientific binding extract are packaged.')
for stage in terminal['planned_stages']:
 copy(R/'originals'/f'{stage}.json')
 for n in ['request.json','rebinding.json','admission.json','supervisor.json','supervisor.plan.json','strict-result.json','backend-result.json','stage.log','fit/iterations.json','fit/native_runtime.json','fit/factor-retention.json']:copy(R/stage/n)
 for label in ['point-001-initial','point-002-repeat','point-003-closure-refinement']:
  for n in ['qr.profile.json','closure.json','closure-retention.json','profile.execution.json']:
   p=R/stage/'fit'/label/n
   if p.exists():copy(p)
 for item in read(R/stage/'strict-result.json')['cold_start_evidence'].values():
  if isinstance(item,dict) and 'path' in item:assert sha(item['path'])==item['sha256'];copy(item['path'])
 include_roles={'physical_parameters','native_nuisance_profile','native_qr_factor','native_qr_rhs','native_qr_coordinates','native_qr_diagnostics','native_objective','native_qr_parameters','native_qr_row_compression_receipt','native_parameter_covariance','native_parameters','native_preprocessing_audit','full_native_solution','native_parameter_names','online_factor_retention','online_closure_retention','online_proposal_retention','native_runtime'}
 for item in read(R/stage/'backend-result.json')['artifacts']:
  p=Path(item['path'])
  if item['role'] in include_roles and p.exists() and p.stat().st_size<5_000_000:
   if item.get('sha256'):assert sha(p)==item['sha256']
   copy(p)
  else:external(p,'Backend artifact kept outside this compact publication packet.',item.get('sha256'))
density=R/'cold-density/fit'
for n in ['point-004-trial-001/physical_initial.txt','point-004-trial-001/fixed_force.txt','point-004-trial-001/native/log_density.txt','point-004-trial-001/closure-01/propagate.log','point-004-trial-001/closure-01/propagate.execution.json','point-004-trial-001/closure-01/propagate.xml','point-004-trial-001/closure-02/propagate.log','point-004-trial-001/closure-02/propagate.execution.json','point-004-trial-001/closure-02/propagate.xml','point-004-trial-001/closure-retention.json']:copy(density/n)
for name in ['README.md','contracts.py','one_hour_controls.py','test_behavior.py','test_contracts.py','controls-manifest01.json','development-test-history.json','tests01.log','tests02.log','tests03.log','tests04.log','tests05.log','tests05-result.json','test-created-bytecode01/receipt.json']:
 p=B/'one-hour-controls01'/name
 if p.exists():copy(p)
for p in sorted((B/'one-hour-controls01/tests05-source').glob('*.py')):copy(p)
for name in ['scientific-contract01.json','native-contract/contract.json','controls-tests01/result.json','controls-tests01/tests.log','controls-review01.json','prepared-plan-review01.json','launch-review01.json']:
 p=B/'one-hour-review01'/name
 if p.exists():copy(p)
for name in ['recommendation.json','lifecycle-review01.json','lifecycle-review02.json','lifecycle-review03.json','launch-lifecycle01.json']:
 p=B/'one-hour-host-review01'/name
 if p.exists():copy(p)
for p in sorted((B/'one-hour-preparation01').glob('*')):
 if p.is_file() and p.suffix in {'.json','.log'}:copy(p)
C=Path('/mnt/d/orbit-v41-recovery01/candidate04')
for n in ['build-result04.json','candidate04-source-patch.json','binaries/groops-v41-28c725765201e470.build-manifest.json']:copy(C/n,'evidence/candidate04/'+Path(n).name)
external(C/'source-snapshot.json','Complete candidate04 snapshot archived with recovery14; exact identity remains required.')
external(C/'binaries/groops-v41-28c725765201e470','Native executable retained outside Git.',plan['runtime']['native']['sha256'])
compact={k:plan[k] for k in ['schema','created_at','stages','limits','boot_id','cold_start','initialization','previous_results_reused','source_identity','source_snapshot','reference_plan','control_pins','helper_pins','originals','namespace_scope']}
compact.update(original_plan=pin(R/'plan.json'),runtime=plan['runtime'],jobs=plan['jobs'],binding_role_counts=dict(collections.Counter(x['role'] for x in plan['bindings'])),directory_tree_count=len(plan['directory_bindings']),extraction_scope='Derived compact view; the exact full external plan is bound by freeze SHA256.')
save(P/'plan-summary.json',compact)
science=[x for x in plan['bindings'] if x['role'].startswith(('estimation:','native:')) or x['role']=='prepared_data']
save(P/'scientific-input-bindings.json',{'original_plan':pin(R/'plan.json'),'scope':'Unchanged rows from the original full plan. Runtime tree inventories remain external; source datasets are not packaged.','binding_count':len(science),'bindings':science})
rows=[]
for stage in terminal['planned_stages']:
 d=R/stage;q=read(d/'strict-result.json');sup=read(d/'supervisor.json');result=read(d/'backend-result.json');it=read(d/'fit/iterations.json')
 assert sup['owned_process_group_cleaned'] and not sup['signals_received']
 rows.append({'stage':stage,'method':result['method'],'status':q['status'],'numerical_status':result['numerical_status'],'whole_fit_verified':q['whole_fit_verified'],'accepted_covariance':q['accepted_covariance'],'backend_fit_seconds':result['elapsed_seconds'],'supervised_seconds':sup['elapsed_seconds'],'peak_process_tree_rss_bytes':sup['peak_process_tree_rss_bytes'],'accepted_iterations':it['accepted_iterations'],'trial_evaluations':it['trial_evaluations'],'propagation_count':read(d/'fit/native_runtime.json')['propagation_count'],'cleanup_verified':sup['owned_process_group_cleaned'],'native_binary_sha256':result['native_binary_sha256'],'source_hash':result['source_hash'],'strict_result':'evidence/one-hour-run01/'+stage+'/strict-result.json','error':result.get('error')})
pulse=read(R/'cold-pulses/strict-result.json');last=[x for x in read(R/'cold-pulses/fit/iterations.json')['history'] if 'trial' in x][-1]
assert rows[0]['accepted_iterations']==10 and rows[0]['trial_evaluations']==10
assert pulse['evidence']['fresh_final_correction']['stationary'] and not pulse['evidence']['fresh_final_correction']['nuisance_floor_limited']
assert rows[1]['accepted_iterations']==0 and rows[1]['trial_evaluations']==1 and not rows[1]['accepted_covariance']
assert 'Nonfinite equinoctial reference input' in (density/'point-004-trial-001/closure-02/propagate.log').read_text()
values=[float(x.split()[-1]) for x in (density/'point-004-trial-001/native/log_density.txt').read_text().splitlines() if x.strip()]
report={'schema':'orbit-poc-cold-one-hour-publication-v1','scope':'Two bounded synthetic cold full-fit attempts: one strict pass and one preserved native failure.','created_at':datetime.datetime.now(ZoneInfo('Europe/Berlin')).isoformat(),'run':str(R),'native_binary_sha256':rows[0]['native_binary_sha256'],'source_hash':rows[0]['source_hash'],'freeze_sha256':sha(R/'freeze.json'),'counts':{'planned':2,'passed':1,'failed':1},'execution_order':terminal['planned_stages'],'stages':rows,'pulse_final':pulse['evidence'],'pulse_last_accepted_trial':{k:last[k] for k in ['trial','actual_reduction','objective_floor','objective_reduction_numerically_resolved']},'pulse_convergence_basis':'Fresh undamped final correction, full-rank factor and strict fresh nuisance confirmation. The last accepted reduction is below the measured objective floor and is not convergence authority.','density_failure':{'native_message':'Nonfinite equinoctial reference input','point':'point-004-trial-001','closure':'closure-02','trial_log_density_min':min(values),'trial_log_density_max':max(values),'maximum_trial_density_multiplier':math.exp(max(values)),'diagnosis_scope':'Observed native guard failure and extreme proposal only. Exact failing element/root cause and a corrective candidate are not established by this publication.','timeout':False,'memory_limit':False,'accepted_covariance':False},'independent_prelaunch_review':{'path':'evidence/one-hour-review01/launch-review01.json','check_count':read(B/'one-hour-review01/launch-review01.json')['check_count'],'approved':True},'control_tests':{'path':'evidence/one-hour-controls01/tests05-result.json','tests':50,'passed':True},'terminal_review_scope':'Original strict receipts substantiate the outcomes. Prelaunch reviews are not terminal numerical audits. Independent publication approval is recorded separately.','no_new_native_runs_for_publication':True,'frozen_benchmarks_changed':False,'release_authority':False,'scientific_accuracy_superiority_claim':False,'covariance_calibration_verified':False,'timing_scope':'Backend fitting and supervised elapsed time are separate. Supervision includes substantial identity I/O; these different methods are not a speedup comparison.'}
save(P/'report.json',report)
with (P/'summary.csv').open('w',newline='') as f:
 fields=['stage','status','numerical_status','accepted_iterations','trial_evaluations','propagation_count','backend_fit_seconds','supervised_seconds','peak_process_tree_rss_bytes','whole_fit_verified','accepted_covariance','cleanup_verified'];w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
copy(Path(__file__),'build_packet.py')
save(P/'external-evidence.json',{'scope':'Omitted original artifacts retain exact identities and original receipt authority. Large input/runtime inventories remain in the external frozen plan. No original file was removed for publication.','files':EXTERNAL})
save(P/'source-map.json',{'scope':'Copies retain original bytes. Absolute evidence locators are historical; use these portable packet paths.','files':COPIES})
print(json.dumps({'packet':str(P),'copied_files':len(COPIES),'copied_bytes':sum(x['bytes'] for x in COPIES),'external_artifacts':len(EXTERNAL),'counts':report['counts']}))
