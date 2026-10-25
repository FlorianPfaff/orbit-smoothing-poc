#!/usr/bin/env python3
"""Read-only independent terminal audit; writes only this new audit directory.

No estimator imports, native execution, data generation or numerical refits.
Larger arrays are read to recompute diagnostics and hash-located in the evidence
inventory. Prior prelaunch closure receipts supply the already audited full
input/runtime inventory; this audit does not repeat that bulk scan.
"""
from pathlib import Path
import hashlib, json, math, sys, datetime, xml.etree.ElementTree as ET
import numpy as np

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
RUN=BASE/'reference-gates14-run01'
SOURCE=Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
NATIVE=Path('/mnt/d/orbit-v41-recovery01/candidate04/binaries/groops-v41-28c725765201e470')
NATIVE_SHA='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
STAGES=['synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012']
checks=[]; evidence={}; findings={}
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()
def record(p,role='supporting evidence'):
    p=Path(p); key=str(p)
    if key not in evidence:
        n=p.stat().st_size
        evidence[key]={'path':key,'sha256':sha(p),'bytes':n,'role':role,'copy_recommended':n<=1048576 and p.suffix not in ('.dat','.so'),'publication_policy':'exact bytes; retain absolute original path in mapping' if n<=1048576 else 'hash-located large raw artifact; do not copy by default'}
    return evidence[key]
def read(p,role='supporting evidence'):
    record(p,role);return json.loads(Path(p).read_text())
def check(name,ok,detail=None):
    checks.append({'name':name,'passed':bool(ok),'detail':detail})
def pin(p,expected=None,role='pinned evidence'):
    v=record(p,role)
    if expected is not None:check('sha256:'+str(p),v['sha256']==expected,{'expected':expected,'actual':v['sha256']})
    return v
def close(a,b):return math.isclose(float(a),float(b),rel_tol=2e-13,abs_tol=1e-18)
def table(p,width):
    record(p,'raw numerical diagnostic; read independently')
    rows=[]
    with Path(p).open() as f:
        for line in f:
            bits=line.split()
            if len(bits)!=width:continue
            try:rows.append([float(x) for x in bits])
            except ValueError:continue
    a=np.asarray(rows)
    check('finite table:'+str(p),bool(a.size) and np.isfinite(a).all())
    return a
def xml_signature(e):
    return (e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(xml_signature(c) for c in e))

plan=read(RUN/'plan.json','frozen complete eight-stage plan')
freeze=read(RUN/'freeze.json','immutable run14 freeze')
terminal=read(RUN/'result.json','terminal aggregate; independently checked below')
detached=read(RUN/'detached-result.json','durable controller terminal receipt')
started=read(RUN/'detached-started.json','durable controller admission and identity')
pin(RUN/'freeze.json','11d21c440b6eee1df54372f2f524c03799ac3c5b2d2e854fb9cf68330361608d')
pin(RUN/'plan.json','83224b4e5284e5b7d4c6ac0e8d99f0f7845a0c1aedbd7f6d1f1a45831212967a')
launchreview=read(BASE/'validation-review04/recovery14-launch-review01.json','independent exact prelaunch closure review')
pin(BASE/'validation-review04/recovery14-launch-review01.json','ae1161667fb5291a8625e2a45abb7e122a6d22e67aa68683e64b1b502dbcc48d')
for rel in ['validation-review04/recovery14-dependency-identity01.json','validation-review04/controls07-review01.json','preparation05/result.json','validation-controls07/controls-freeze01.json','validation-review04/runtime13-loader-metadata-review01.json','validation-review04/runtime13-groops-loader-review01.json']:
    record(BASE/rel,'pre-existing independently reviewed provenance closure; no bulk re-scan')
for key in ['plan','preflight','validation_inputs']:
    pin(freeze[key]['path'],freeze[key]['sha256'])
pin(NATIVE,NATIVE_SHA,'actual native executable; single 24 MB identity check')
native_manifest=read(str(NATIVE)+'.build-manifest.json','pinned native build manifest')
snapshot_path=SOURCE.parent/'source-snapshot.json'
snapshot=read(snapshot_path,'immutable candidate04 source snapshot')
pin(snapshot_path,next(p['sha256'] for p in plan['pins'] if p['path']==str(snapshot_path)))
source_pins={p['relative_path']:p['sha256'] for p in snapshot['files']}
check('all eight planned in exact order',plan['stages']==STAGES and [j['stage'] for j in plan['jobs']]==STAGES and terminal['planned_stages']==STAGES)
check('fresh complete suite without old reuse',plan['recovery']['fresh_complete_stage_inventory'] is True and plan['recovery']['previous_results_reused'] is False and detached['old_results_reused'] is False)
check('terminal scope excludes covariance full-fit release',all(terminal[x] is False for x in ['accepted_covariance','whole_fit_verified','release_authority']) and detached['release_authority'] is False)
check('successful terminal controller',detached['status']=='complete' and detached['returncode']==0 and detached['error'] is None and detached['signals_received']==[])
check('controller exact approved identities',detached['freeze_sha256']==record(RUN/'freeze.json')['sha256'] and detached['review_sha256']==record(BASE/'validation-review04/recovery14-launch-review01.json')['sha256'])
check('original process-tree memory limit',plan['limits']['process_tree_rss_bytes']==8*1024**3)
timing=[]; previous_start=None
for job,summary in zip(plan['jobs'],terminal['stages']):
    name=job['stage']; folder=RUN/name
    strict=read(folder/'strict-result.json','strict worker result and actual namespace proof')
    supervisor=read(folder/'supervisor.json','owned process-tree supervision and cleanup')
    supervision=read(folder/'supervisor.plan.json','stage supervision plan')
    admission=read(folder/'admission.json','current-host per-stage admission')
    for field in ['execution','freeze','plan','strict_result']:
        pin(summary[field]['path'],summary[field]['sha256'])
    pin(folder/'supervisor.plan.json',supervisor['plan_sha256'])
    check(name+': exact argv and fresh directory',strict['argv']==job['argv'] and job['directory']==str(folder) and strict['stage']==name and str(folder/'result') in job['argv'])
    check(name+': strict successful stage',strict['status']=='passed' and strict['returncode']==0 and summary['status']=='passed' and summary['input_identity_after']=='verified')
    check(name+': supervisor completion',supervisor['status']=='complete' and supervisor['returncode']==0 and supervisor['signals_received']==[])
    clean=supervisor['cleanup']
    check(name+': owned-tree cleanup',clean['verified'] and clean['empty_tree_certificate']=='kernel_ECHILD' and clean['remaining']==[] and supervisor['owned_process_group_cleaned'] and summary['cleanup_verified'])
    check(name+': original limits',supervision['timeout_seconds']==job['timeout_seconds']==(7500 if name.startswith('nuisance-replay') else 7200) and supervision['max_process_tree_rss_bytes']==8*1024**3 and supervision['min_free_disk_bytes']==16*1024**3)
    check(name+': within resources',supervisor['peak_process_tree_rss_bytes']<8*1024**3 and supervisor['elapsed_seconds']<job['timeout_seconds'])
    check(name+': same historical boot, ownership and admission',supervisor['boot_id']==supervision['boot_id']==admission['boot_id']==started['admission']['boot_id'] and supervisor['supervisor']['parent']==started['pid'] and admission['competing_workloads']==[] and admission['cpu']==4)
    ticks=supervisor['supervisor']['start_ticks']
    if previous_start is not None:check(name+': serial process start order',ticks>previous_start)
    previous_start=ticks
    check(name+': one numerical thread',all(job['environment'][v]=='1' for v in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','BLIS_NUM_THREADS','NUMEXPR_NUM_THREADS','GOTO_NUM_THREADS']))
    check(name+': no authority upgrade',all(strict[k] is False for k in ['covariance_authority','full_fit_verified','release_authority']))
    ev=strict['evidence']
    for v in ev.values():
        if isinstance(v,dict) and 'path' in v and 'sha256' in v:pin(v['path'],v['sha256'])
    source_path=Path(job['argv'][1]);pin(source_path,source_pins[str(source_path.relative_to(SOURCE))],'unchanged scientific validation source')
    ledger=strict['mount_proof']
    # Objective stages add one read-only copied-parent view over the common
    # 374 distinct mounts; all stages verify the same 978 protected paths.
    check(name+': protected originals actually read-only',ledger['checked_original_paths']==978 and len(ledger['readonly_mounts'])==(375 if name.startswith('objective-') else 374) and all('ro' in x['options'] for x in ledger['readonly_mounts']))
    if name.startswith('objective-'):
        private=ledger['private_objective_output']
        check(name+': fresh private legacy-output role',private['active'] is True and private['same_backing_identity'] is True and private['host_original_written'] is False and private['backing']==str(folder/'legacy-output') and 'ro' in private['parent_mount']['options'] and 'rw' in private['output_mount']['options'])
    # The timer calls themselves leave a separately measurable, positive microsecond gap.
    timer_remainder=strict['worker_total_seconds']-sum(strict[k] for k in ['controller_before_scientific_seconds','scientific_command_seconds','controller_after_scientific_seconds'])
    check(name+': controller costs included',strict['controller_inventory_included_in_stage_limit'] and 0<=timer_remainder<.001,{'unassigned_timer_call_seconds':timer_remainder,'interpretation':'Accounting granularity only; no scientific threshold changed.'})
    timing.append({'stage':name,'scientific_command_seconds':strict['scientific_command_seconds'],'worker_total_seconds':strict['worker_total_seconds'],'stage_end_to_end_seconds':summary['end_to_end_stage_seconds'],'peak_process_tree_rss_bytes':supervisor['peak_process_tree_rss_bytes'],'cleanup_verified':clean['verified'],'cleanup_signals_count':len(clean['signals'])})
findings['timing']={'stages':timing,'scientific_command_seconds':sum(x['scientific_command_seconds'] for x in timing),'end_to_end_run_seconds':terminal['end_to_end_run_seconds'],'detached_controller_seconds':detached['elapsed_seconds'],'peak_process_tree_rss_bytes':max(x['peak_process_tree_rss_bytes'] for x in timing),'interpretation':'Runtime inventories and supervision are included in stage and end-to-end totals. Cleanup SIGTERM records are owned-descendant cleanup, not scientific timeouts; no received interrupt signals or timeouts occurred.'}

refinements=[]
for stage in STAGES[:4]:
    folder=RUN/stage/'result'; result=read(folder/'result.json','scientific refinement result')
    check(stage+': complete source and binary identity',result['status']=='complete' and result['binary_sha256']==NATIVE_SHA and result['diagnostic_source_sha256']==record(plan['jobs'][STAGES.index(stage)]['argv'][1])['sha256'])
    pin(SOURCE/'scripts/numerics_refinement_helpers.py',result['signal_diagnostic_source_sha256'])
    arrays=[]; off=[]; orb=[]
    for label in ['coarse','fine']:
        p=folder/label
        arrays.append(table(p/'predictions/signals.txt',8))
        record(p/'predictions/signal_support.txt','complete signal identity/support')
        mode=read(p/'predictions/prediction_mode.json','fixed nuisance and estimator interpolation branch')
        check(stage+': '+label+' fixed nuisance mode',mode['nuisance_fitting'] is False and mode['environment']['ORBIT_POC_NUMERICS_SOLVER']=='scaled_qr_v1')
        off.append(table(p/'offgrid_orbit.txt',10));orb.append(table(p/'fixed_orbit.txt',10))
        read(p/'closure.json','physical closure before prediction')
    a,b=arrays
    check(stage+': identical signal identities and nuisance',a.shape==b.shape and np.array_equal(a[:,:4],b[:,:4]) and np.array_equal(a[:,6:],b[:,6:]) and sha(folder/'coarse/predictions/signal_support.txt')==sha(folder/'fine/predictions/signal_support.txt'))
    check(stage+': original six clock offsets',np.array_equal(np.unique(a[:,6]),[-2e-5,-5e-6,-5e-8,5e-8,5e-6,2e-5]))
    check(stage+': identical offgrid times',np.array_equal(off[0][:,0],off[1][:,0]))
    t,ia,ib=np.intersect1d(orb[0][:,0],orb[1][:,0],return_indices=True)
    check(stage+': all coarse epochs present',len(t)==len(orb[0]))
    metrics={'aligned_position_maximum_m':float(np.max(np.linalg.norm(orb[0][ia,1:4]-orb[1][ib,1:4],axis=1))),'offgrid_position_maximum_m':float(np.max(np.linalg.norm(off[0][:,1:4]-off[1][:,1:4],axis=1)))}
    for k,v in metrics.items():
        check(stage+': recomputed '+k,close(v,result['metrics'][k]),{'recomputed':v,'recorded':result['metrics'][k]})
        check(stage+': original 30 micrometre '+k,v<3e-5)
    diff=np.abs(a[:,4]-b[:,4]); groups=[]
    for phase,label,sigma in [(0,'code',.3),(1,'carrier',.003)]:
        for freq in [1575420000.,1227600000.]:
            select=(a[:,3]==phase)&(a[:,2]==freq);den=np.minimum(a[select,5],sigma)
            calc={'observable':label,'frequency_hz':freq,'rows':int(select.sum()),'maximum_difference_m':float(np.max(diff[select])),'maximum_fraction_of_sigma':float(np.max(diff[select]/den))}
            old=next(v for v in result['native_signals']['signals'] if v['observable']==label and v['frequency_hz']==freq)
            check(stage+': recomputed '+label+' '+str(freq),all(close(calc[k],old[k]) for k in ['rows','maximum_difference_m','maximum_fraction_of_sigma']))
            check(stage+': one percent '+label+' '+str(freq),bool(np.all(diff[select]<.01*den)))
            groups.append(calc)
    check(stage+': frozen weights interpretation',result['native_signals']['comparison_weights_frozen'] and result['native_signals']['comparison_weight_source']=='coarse native sigma shared by both predictions')
    if stage!='flight-refinement':
        values=np.asarray(result['fixed_force'])
        expected=.1*np.sin(np.arange(len(values))*.27) if result['method']=='groops_log_drag_ou' else np.resize([40.,-30.,20.],len(values))
        check(stage+': nonzero prescribed disturbances',np.array_equal(values,expected) and np.any(values!=0))
        check(stage+': original coarse fine sampling',result['state_grid_seconds']==[5.,2.5])
    else:
        check(stage+': bounded flight scope',result['gnss_fit_performed'] is False and result['reference_orbit_used'] is False and result['duration_seconds']==1800 and result['profile']=='flight_gravity_drag_v1')
        check(stage+': joint refinement unchanged',result['controls']=={'coarse':{'atmosphere_seconds':1.,'state_seconds':5.,'thermal_seconds':[1.]},'fine':{'atmosphere_seconds':.5,'state_seconds':2.5,'thermal_seconds':[.5]}})
    refinements.append({'stage':stage,'metrics':metrics,'signals':groups,'maximum_fraction_of_sigma':max(g['maximum_fraction_of_sigma'] for g in groups),'noise_fraction_threshold':.01})
findings['refinements']=refinements

artifacts=plan['historical_inputs']['input_artifacts']; replay_results=[]
for stage,key,prefix in [('nuisance-replay','old_nuisance_replay','old_replay'),('nuisance-replay-candidate1-point012','candidate1_nuisance_replay','new_replay')]:
    folder=RUN/stage/'result';receipt=read(folder/'receipt.json','exact nuisance failure replay receipt')
    profile=read(folder/'qr.profile.json','actual final native nuisance convergence state')
    original=Path(artifacts[key]['path']);pin(original,artifacts[key]['sha256'],'distinct original nuisance XML')
    pin(folder/'profile.xml',receipt['replay_profile_sha256'],'actual replay XML')
    check(stage+': frozen source profile identity',receipt['source_profile']==str(original) and receipt['source_profile_sha256']==artifacts[key]['sha256'])
    old=ET.parse(original).getroot()
    changed=0
    for node in old.iter():
        if node.text and (node.tag.startswith('outputfile') or node.tag=='filename' and node.attrib.get('label')=='tmpDir'):
            check(stage+': original output rooted in original parent '+str(changed),str(original.parent) in node.text)
            node.text=node.text.replace(str(original.parent),str(folder));changed+=1
    check(stage+': XML changes only output destinations',changed>0 and xml_signature(old)==xml_signature(ET.parse(folder/'profile.xml').getroot()))
    for suffix in ['density','reference','variational']:
        p=artifacts[prefix+'_'+suffix];pin(p['path'],p['sha256'],'distinct frozen replay physical '+suffix)
        check(stage+': preserved physical input '+suffix,p['path'] in original.read_text() and p['path'] in (folder/'profile.xml').read_text())
    check(stage+': actual strict not floor convergence',profile['nuisance_converged'] is True and profile['nuisance_floor_limited'] is False and profile['fresh_full_nuisance_confirmed'] is True and profile['nuisance_floor_audit']==[] and profile['threshold_m']==1e-8 and profile['required_consecutive_small_updates']==2 and profile['maximum_update_m']<1e-8 and profile['fresh_full_nuisance_update_m']<1e-8)
    check(stage+': two consecutive undamped small updates',len(profile['history'])>=2 and all(x['maximum_update_m']<1e-8 for x in profile['history'][-2:]))
    check(stage+': fixed physical dynamics and weights',profile['fixed_weights'] is True and profile['dynamic_updates'] is False)
    searches=[read(p,'actual nuisance trial and exact zero replay') for p in sorted(folder.glob('qr.*.nuisance_line_search.json'),key=lambda p:int(p.name.split('.')[1]))]
    normalized=[{k:v for k,v in s.items() if k not in ('generation','sha256')} for s in receipt['searches']]
    check(stage+': receipt equals raw searches',searches==normalized)
    for item in receipt['searches']:pin(folder/('qr.'+str(item['generation'])+'.nuisance_line_search.json'),item['sha256'])
    confirmations=[read(p,'fresh full-system nuisance confirmation') for p in folder.glob('qr.*.nuisance_confirmation.json')]
    check(stage+': one fresh full-system confirmation',len(confirmations)==1)
    allsearch=searches+confirmations; trials=[v for s in allsearch for v in s['trials'] if v['status']==0]
    signatures={v['observation_signature'] for v in trials}
    crossings=sum(v['ambiguity_half_integer_crossings'] for v in trials)
    check(stage+': fixed nonempty support and weights every trial',len(signatures)==1 and None not in signatures and '0' not in signatures and bool(trials))
    check(stage+': ambiguity half-integer crossings actually tested',crossings>0)
    check(stage+': every zero replay exact',all(s['zero_update_replay']['status']==0 and s['zero_update_replay']['actual_reduction']==0 and s['zero_update_replay']['maximum_update_m']==0 for s in allsearch))
    check(stage+': no floor evidence substituted',all(s['nuisance_floor_limited'] is False for s in allsearch) and receipt['strict_nuisance_converged'] is True and receipt['progress_only_floor_validated'] is False and receipt['returncode']==0 and receipt['timed_out'] is False)
    confirm=confirmations[0]
    check(stage+': final raw confirmation update',confirm['stationary_without_update'] and close(confirm['undamped_maximum_update_m'],profile['fresh_full_nuisance_update_m']))
    replay_results.append({'stage':stage,'source_profile':artifacts[key],'strict':True,'floor_limited':False,'maximum_update_m':profile['maximum_update_m'],'fresh_full_nuisance_update_m':profile['fresh_full_nuisance_update_m'],'threshold_m':1e-8,'observation_signature':next(iter(signatures)),'half_integer_crossings':crossings,'zero_replay_checks':len(allsearch),'iterations':profile['iterations']})
check('two distinct original failure profiles',replay_results[0]['source_profile']['sha256']!=replay_results[1]['source_profile']['sha256'])
for suffix in ['density','reference','variational']:check('distinct frozen physical '+suffix,artifacts['old_replay_'+suffix]['sha256']!=artifacts['new_replay_'+suffix]['sha256'])
findings['replays']=replay_results

child_path=HERE/'objective-math/audit-result.json'
if child_path.exists():
    child=read(child_path,'separate independent objective mathematics audit')
    findings['objective_math']=child
    check('independent objective mathematics audit passes',child['passed'] is True and child['failed_checks']==[] and all(c['passed'] for c in child['checks']))
    check('all 32 objective nuisance profiles strictly converge',sum(m['profile_count'] for m in child['methods'])==32 and sum(m['strict_nuisance_count'] for m in child['methods'])==32 and sum(m['floor_limited_count'] for m in child['methods'])==0)
    for item in child['evidence']:
        evidence.setdefault(item['path'],{**item,'role':'independent objective-math audit evidence','copy_recommended':item.get('copy_eligible',False)})
    pin(child['audit_script']['path'],child['audit_script']['sha256'],'separate independently written objective math audit source')
else:
    findings['objective_math']={'pending':True,'expected_path':str(child_path)}
    check('independent objective mathematics audit present',False,'Pending independent child result; terminal audit cannot yet be approved.')

# Every accessed artifact is rehashed after the calculations. This is a
# selected evidence stability check, not a redundant scan of all frozen data.
changed=[p for p,item in evidence.items() if sha(p)!=item['sha256']]
check('all accessed audit evidence unchanged',not changed,{'changed_paths':changed})

out={'schema':'orbit-poc-independent-run14-terminal-audit-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'audit_source':record(Path(__file__),'this independently written read-only audit'),'python':sys.executable,'numpy':np.__version__,'approved':all(c['passed'] for c in checks),'checks_count':len(checks),'checks':checks,'findings':findings,'scope':{'read_only_original_evidence':True,'native_runs':0,'nonlinear_refits':0,'full_input_rescan':False,'prior_closure_basis':'116-check exact launch review plus per-stage pre/post identity receipts; selected terminal artifacts independently rehashed','accepted_covariance':False,'whole_fit_verified':False,'release_authority':False,'claims_excluded':['full nonlinear dynamic-fit convergence','scientific accuracy superiority','complete flight derivatives','v4 release readiness','rerun of 106 native tests or 51 historical correction tests'],'remaining_flight_derivative_approximations':['thermal-history sensitivities','other force gradients','atmospheric event-time derivatives']}}
(HERE/'audit-result.json').write_text(json.dumps(out,indent=2,allow_nan=False)+'\n')
(HERE/'evidence-inventory.json').write_text(json.dumps({'schema':'orbit-poc-terminal-audit-evidence-inventory-v1','entries':list(evidence.values()),'large_artifact_policy':'Large arrays were independently read and hashed but may remain outside Git. Copy exact small evidence with source->package mapping; never mutate originals.','limitations':'Selected raw signal rows and orbital exports support recomputation; giant row spools, full input trees and binaries are hash-located.'},indent=2)+'\n')
print(json.dumps({'approved':out['approved'],'checks':len(checks),'failures':[c for c in checks if not c['passed']],'timing':findings['timing']},indent=2))
