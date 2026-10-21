"""Read-only independent audit of the actual, terminal bounded D03 experiment."""
from pathlib import Path
import hashlib,importlib.util,json,datetime,sys
D=Path('@REMOTE_DATA_ROOT@/orbit-v31-diagnostic-row-trace-03-PRIVATE_USER')
PLAN_SHA='0846eeaddca404116ecc8ee1d8de404aa1e46e00df5517e207d06e55d53b21bd'
EXEC_SHA='1377e293a906394392c8dbd6b9d12c492b80eb8256396788a495cbd402c43428'
NATIVE_SHA='3a113ae1a88954a33f81f6e251ecffb98a757058821568965aae11658be8e251'
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def artifact(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def require(ok,why):
    if not ok:raise RuntimeError(why)
def checked(pin):require(sha(pin['path'])==pin['sha256'],'Changed pinned artifact: '+pin['path'])
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def audit():
    pp=D/'control/plan.json';ep=D/'control/diagnostic-execution.json';jp=D/'diagnostic/pipeline.json'
    require(sha(pp)==PLAN_SHA and sha(ep)==EXEC_SHA,'Actual plan/execution identity differs')
    plan=json.loads(pp.read_text());e=json.loads(ep.read_text());journal=json.loads(jp.read_text());initial_journal=sha(jp)
    require(journal['schema']=='orbit-poc-diagnostic-row-trace-run-v2' and journal['status']=='completed' and journal.get('finished_at'),'Diagnostic is not terminal/completed')
    require(journal.get('scientific_correctness_resolved') is False and journal['final_cleanup']['verified'] is True and not journal['final_cleanup']['errors'],'Diagnostic cleanup/scope differs')
    require(journal['plan']=={'path':str(pp),'sha256':PLAN_SHA},'Journal belongs to another plan')
    for key in ('runner','execution','driver','source_freeze','prior_pipeline','prior_postprocess'):checked(plan[key])
    for pin in (*plan['helpers'].values(),*plan['inputs'].values()):checked(pin)
    d=load('d03_terminal_owned_driver',plan['driver']['path']);require(d.load_execution(ep)==e,'Execution validation differs')
    frozen=json.loads(Path(plan['source_freeze']['path']).read_text())['source'];require(d.source_receipt(D/'source')==frozen and len(frozen['files'])==771,'Frozen771-file source changed')
    for pin in e['runtime_artifacts'].values():require(sha(d.resolved_host_path(pin['path'],e))==pin['sha256'],'Runtime artifact changed')
    prepare=load('d03_terminal_input_identity',plan['helpers']['prepare']['path'])
    inputs,links,identity=prepare.collect_inputs(Path(plan['inputs']['profile']['path']),e,d)
    require(inputs==plan['inputs'] and links==plan['input_links'],'Original XML input closure changed')
    require(identity==json.loads(Path(plan['helpers']['input_identity']['path']).read_text()),'Original expanded input identity changed')
    launchp=D/'control/diagnostic-launch.json';launch=json.loads(launchp.read_text());pid=launch['driver_process']
    require(pid=={'pid':1876829,'start_ticks':104623282,'boot_id':e['host']['boot_id']},'Launched driver identity differs')
    require(launch['plan_sha256']==PLAN_SHA and launch['execution_sha256']==EXEC_SHA and launch['launch_committed'] is True,'Launch attribution differs')
    driverid=journal['admission']['driver_identity'];require(driverid['pid']==pid['pid'] and driverid['start_ticks']==pid['start_ticks'],'Journal driver differs from detached launch')
    require(journal['native']['sha256']==NATIVE_SHA and sha(journal['native']['path'])==NATIVE_SHA,'Diagnostic native binary differs')
    expected=['clone','checkout','build','trace-off','trace-on','equivalence'];steps=journal['steps'];require([s['name'] for s in steps]==expected,'Diagnostic step inventory differs')
    cleanup=journal['final_cleanup']['commands'];require(len(cleanup)==len(steps) and all(c.get('verified') is True and not c.get('live_owned_processes') for c in cleanup),'Final owned cleanup is incomplete')
    for n,step in enumerate(steps):
        require(step['status']=='completed' and step['returncode']==(1 if step['name'].startswith('trace-') else 0),'Unexpected diagnostic step result')
        require(step.get('cleanup_verified') is True and step.get('cleanup',{}).get('verified') is True,'Step cleanup is unverified')
        require(step.get('started_at') and step.get('finished_at'),'Missing step timing')
        if n:require(steps[n-1]['finished_at']<=step['started_at'],'Native steps overlap')
    comparator=load('d03_terminal_exact_comparator',plan['helpers']['compare']['path'])
    dirs=[Path(plan['inputs']['profile']['path']).parent,D/'diagnostic/trace-off',D/'diagnostic/trace-on']
    eqp=D/'diagnostic/equivalence.json';eq=json.loads(eqp.read_text());recomputed=comparator.verify(dirs,4)
    require(eq==recomputed and eq['passed'] is True and len(eq['checks'])==52,'Exact52-check equivalence does not reproduce')
    receipts={};sentinels={}
    for name in ('trace-off','trace-on'):
        folder=D/'diagnostic'/name;rp=folder/'receipt.json';r=json.loads(rp.read_text())
        require(r['schema']=='orbit-poc-native-nuisance-validation-v1' and r['passed'] is False and r['returncode']==1 and r['timed_out'] is False and r['profile'] is None,'Diagnostic replay wrongly marked successful or timed out')
        require(r['native_unchanged'] is True and r['native_sha256']==NATIVE_SHA,'Replay binary differs')
        require(r['source_profile']==plan['inputs']['profile']['path'] and r['source_profile_sha256']==plan['inputs']['profile']['sha256'],'Replay source input differs')
        require(r['replay_profile_sha256']==sha(folder/'profile.xml'),'Replay XML changed')
        require(r['strict_nuisance_converged'] is False and r['progress_only_floor_validated'] is False,'Incomplete diagnostic cannot establish nuisance convergence')
        require([s['generation'] for s in r['searches']]==[1,2,3,4],'Replay receipt has wrong generation support')
        require(not (folder/'qr.profile.json').exists(),'Diagnostic unexpectedly contains completed final profile')
        require('D03 diagnostic generation limit reached; scientific validation incomplete' in (folder/'profile.log').read_text(),'Explicit stop reason missing from native log')
        receipts[name]=artifact(rp);sentinels[name]=artifact(folder/'qr.diagnostic-incomplete.json')
    values=d.table();identities={(pid['pid'],pid['start_ticks'])};namespaces=set()
    for c in cleanup:
        identities.update((i['pid'],i['start_ticks']) for i in c['identities']);namespaces.update(c['pid_namespaces'])
    active=[v for v in values.values() if v['state']!='Z' and ((v['pid'],v['start_ticks']) in identities or v['pid_namespace'] in namespaces)]
    require(not active,'An exact owned process/namespace is still executing')
    admission=d.admission(e)
    traces=sorted((D/'diagnostic/trace').glob('nuisance-trace-*.tsv'));require(traces and all(p.is_file() and not p.is_symlink() for p in traces),'Trace files are absent or linked')
    # Full trace parsing is intentionally left to a subsequent, independently
    # attributed support audit after the separately owned Decimal analysis.
    trace_inventory=[{'path':str(p),'bytes':p.stat().st_size} for p in traces]
    require(sha(jp)==initial_journal and sha(pp)==PLAN_SHA and sha(ep)==EXEC_SHA,'Terminal evidence changed during audit')
    return {'schema':'orbit-poc-d03-terminal-independent-audit-v1','status':'passed','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer':'recovery04_controls','artifacts':{'plan':artifact(pp),'execution':artifact(ep),'pipeline':artifact(jp),'launch':artifact(launchp),'native':artifact(journal['native']['path']),'equivalence':artifact(eqp)},'source_sha256':frozen['sha256'],'source_files':len(frozen['files']),'inputs_verified':len(inputs),'steps':[{k:s[k] for k in ('name','status','returncode','elapsed_seconds','started_at','finished_at')} for s in steps],'exact_equivalence_checks':len(eq['checks']),'replay_receipts':receipts,'incomplete_sentinels':sentinels,'cleanup':{'verified':True,'owned_process_identities_checked':len(identities),'owned_namespaces_checked':len(namespaces),'live_owned_processes':[]},'admission':admission,'trace_inventory_without_content_scan':trace_inventory,'trace_support_audit_pending':True,'scientific_validation_complete':False,'covariance_authorized':False,'scope':'Bounded diagnostic provenance, exact arithmetic equivalence and cleanup only. The failed original08 correctness gates remain failed.'}
if __name__=='__main__':
    try:result=audit()
    except Exception as error:result={'schema':'orbit-poc-d03-terminal-independent-audit-v1','status':'failed_closed','error':repr(error),'scientific_validation_complete':False,'covariance_authorized':False}
    print(json.dumps(result,sort_keys=True,indent=2));raise SystemExit(0 if result['status']=='passed' else 1)
