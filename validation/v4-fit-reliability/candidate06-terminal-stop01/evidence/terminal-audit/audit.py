"""Archive-only terminal audit. Execute only in the parent's serial stdlib slot."""
from pathlib import Path
import ast, datetime, hashlib, json, sys, xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
SEQUENCE=ROOT/'density-trial-sequence01'
CORRECTNESS=ROOT/'candidate06-correctness01'
COLD=ROOT/'candidate06-cold01'
REVIEW=Path('/mnt/d/orbit-scientific-adapter01/execution-revision03/tests02')
SCIENTIFIC_SOURCE=Path('/mnt/d/orbit-scientific-adapter01/source')
checks=[];evidence={}
def check(name,value,detail=None):checks.append({'name':name,'passed':bool(value),'detail':detail})
def pin(path):
    path=Path(path);data=path.read_bytes()
    value={'path':str(path),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()};evidence[str(path)]=value
    return value
def read(path):pin(path);return json.loads(Path(path).read_text())
def verify(row):
    actual=pin(row['path'])
    return actual['sha256']==row['sha256'] and ('bytes' not in row or actual['bytes']==row['bytes'])
def junit(path):
    pin(path);tree=ET.parse(path).getroot();cases=tree.findall('.//testcase')
    failed=[{'classname':t.get('classname'),'name':t.get('name'),'message':(t.find('failure') if t.find('failure') is not None else t.find('error')).get('message')} for t in cases if t.find('failure') is not None or t.find('error') is not None]
    skipped=[t for t in cases if t.find('skipped') is not None]
    return {'tests':len(cases),'failed':failed,'failures':len(failed),'skips':len(skipped),'passed':len(cases)-len(failed)-len(skipped),'inventory':[{'classname':t.get('classname'),'name':t.get('name')} for t in cases],'suites':[s.attrib for s in tree.findall('.//testsuite')]}
def mtime(path):return datetime.datetime.fromtimestamp(Path(path).stat().st_mtime,datetime.timezone.utc)
def function(path,name):
    tree=ast.parse(Path(path).read_text())
    return next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)

def main():
    check('system Python only',Path(sys.executable).resolve()==Path('/usr/bin/python3').resolve())
    plan=read(SEQUENCE/'plan.json');seq=read(SEQUENCE/'result.json');launch=read(SEQUENCE/'launch.json');started=read(SEQUENCE/'started.json')
    gate_plan=read(CORRECTNESS/'plan.json');gate=read(CORRECTNESS/'result.json');detached=read(CORRECTNESS/'detached-result.json');run_started=read(CORRECTNESS/'run-started.json')
    check('terminal sequence failure in correctness phase',seq['status']=='failed' and seq['returncode']==1 and seq['phase']=='correctness' and 'cold fits not launched' in seq['error'])
    check('exact frozen sequence identity',pin(SEQUENCE/'plan.json')['sha256']==seq['plan_sha256']==started['plan_sha256']==launch['plan_sha256']=='40343c898a8ccf26d6f57575c520fe1abeab4e96bb3c79973952df6c845b06e2')
    check('same sequence launch audit',seq['audit_sha256']==started['audit_sha256']==launch['audit_sha256'])
    for key in ['driver','gate_controller','gate_runner','gate_freeze','gate_review','cold_contracts','cold_controller','cold_freeze','cold_review','candidate_snapshot','source_review']:
        check('sequence pin '+key,verify(plan[key]))
    for row in plan['helper_pins']:check('sequence helper pin '+Path(row['path']).name,verify(row))
    freeze=read(plan['gate_freeze']['path'])
    check('exact frozen correctness plan',verify(gate['plan']) and freeze['plan']['sha256']==gate['plan']['sha256']==pin(CORRECTNESS/'plan.json')['sha256']=='aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95')
    check('exact frozen correctness freeze',verify(gate['freeze']) and detached['freeze_sha256']==plan['gate_freeze']['sha256'])
    check('same boot through launch and terminal stages',launch['boot_id']==plan['boot_id']==run_started['admission']['boot_id']=='cb2d0b40-9b17-45f8-9e5c-716efb8e6aa5')
    check('correctness detached failed without user signal',detached['status']=='failed' and detached['returncode']==1 and detached['signals_received']==[] and seq['signals_received']==[])
    check('all qualification authority withheld',gate['all_ten_strict_passed'] is False and gate['accepted_covariance'] is False and gate['whole_fit_verified'] is False and gate['release_authority'] is False and seq['release_authority'] is False)
    check('no old result substitution',seq['old_results_reused'] is False and plan['prior_results_reused'] is False and detached['old_results_reused'] is False)
    check('unchanged ten-stage order',gate['planned_stages']==plan['gate_stages']==gate_plan['stages'] and [r['stage'] for r in gate['stages']]==plan['gate_stages'])
    completed=gate['stages'][:4];remaining=gate['stages'][4:]
    check('four terminal stages in original order',[r['stage'] for r in completed]==['native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses'])
    check('terminal outcome vector preserved',[r['status'] for r in completed]==['failed','passed','passed','passed'])
    summaries=[];all_cleanup=[]
    snapshot=read(gate_plan['candidate_source']['path']);source=Path('/mnt/d/orbit-v41-density-trial-candidate06/source')
    check('candidate snapshot identity',verify(gate_plan['candidate_source']))
    source_by_path={row['relative_path']:row for row in snapshot['files']}
    for row in completed:
        stage=row['stage'];folder=CORRECTNESS/stage;job=next(j for j in gate_plan['jobs'] if j['stage']==stage)
        check(stage+' result pins',verify(row['execution']) and verify(row['strict_result']) and verify(row['plan']) and verify(row['freeze']))
        strict=read(folder/'strict-result.json');supervisor=read(folder/'supervisor.json');superplan=read(folder/'supervisor.plan.json')
        check(stage+' exact scientific argv',strict['stage']==stage and strict['argv']==job['argv'])
        check(stage+' supervision plan hash',pin(folder/'supervisor.plan.json')['sha256']==supervisor['plan_sha256'])
        check(stage+' same boot',supervisor['boot_id']==plan['boot_id'])
        check(stage+' terminal and strict agree',strict['status']==row['status'] and strict['returncode']==supervisor['returncode'] and supervisor['status']==('failed' if row['status']=='failed' else 'complete'))
        cleanup=supervisor['cleanup']
        check(stage+' terminal owned cleanup',row['cleanup_verified'] is True and supervisor['owned_process_group_cleaned'] is True and cleanup['verified'] is True and cleanup['remaining']==[] and cleanup['empty_tree_certificate']=='kernel_ECHILD')
        owned={(p['pid'],p['start_ticks']) for p in supervisor['tracked_owned_processes']}
        signaled={(p['pid'],p['start_ticks']) for p in cleanup['signals']}
        check(stage+' every cleanup target belongs to tracked owned identity',signaled<=owned)
        check(stage+' no competitor cleanup',all(pid not in (72934,72933) for pid,ticks in signaled))
        all_cleanup.extend(cleanup['signals'])
        check(stage+' input identity reverified',row['input_identity_after']=='verified')
        check(stage+' original deadlines and memory',superplan['timeout_seconds']==job['timeout_seconds'] and superplan['max_process_tree_rss_bytes']==8589934592)
        for argument in job['argv']:
            path=Path(argument)
            if argument.endswith('.py') and path.is_relative_to(source):
                rel=str(path.relative_to(source));expected=source_by_path[rel]
                check(stage+' source '+rel,pin(path)['sha256']==expected['sha256'])
        summary={'stage':stage,'status':row['status'],'returncode':supervisor['returncode'],'cleanup':cleanup,'timings_are_not_uncontended_benchmark_measurements':True}
        if stage.endswith('tests'):
            tests=junit(folder/'tests.xml');summary['tests']=tests
            expected=(106,102,4,0) if stage=='native-tests' else (51,51,0,0)
            check(stage+' exact terminal counts',(tests['tests'],tests['passed'],tests['failures'],tests['skips'])==expected)
            if stage=='correction-tests':
                check('correction strict JUnit identity',verify(strict['evidence']['junit']))
                check('correction exact strict inventory',tests['inventory']==strict['evidence']['inventory'])
        else:
            result=read(folder/'result/result.json');summary['metric_evidence']={'metrics':result['metrics'],'native_signals':result['native_signals'],'method':result['method'],'request_sha256':result['request_sha256']}
            check(stage+' exact scientific result pin',verify(strict['evidence']['result']))
            check(stage+' original refinement gates',result['status']=='complete' and result['passed'] is True and result['native_signals']['passed'] is True and all(v<3e-5 for v in result['metrics'].values()) and all(s['maximum_fraction_of_sigma']<.01 and s['passed'] is True for s in result['native_signals']['signals']))
            request=Path(job['argv'][job['argv'].index('--request')+1]);check(stage+' original request pin',pin(request)['sha256']==result['request_sha256'])
        summaries.append(summary)
    check('six remaining stages not launched',len(remaining)==6 and all(x['status']=='not_executed_or_interrupted_without_receipt' for x in remaining))
    for row in remaining:
        folder=CORRECTNESS/row['stage'];files=[str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()]
        check(row['stage']+' only prepared empty placeholders',files==[],files)
    # The exception is data: parse its literal argument without importing/running controllers.
    call=ast.parse(gate['error'],mode='eval').body
    message=ast.literal_eval(call.args[0]);prefix='Competing native/numerical workload; preserve it: '
    check('admission stop type and precise source',isinstance(call.func,ast.Name) and call.func.id=='RuntimeError' and message.startswith(prefix))
    competitors=json.loads(message[len(prefix):]);check('exact single competing PID observation',len(competitors)==1 and competitors[0]['pid']==72934 and competitors[0]['parent']==72933 and competitors[0]['start_ticks']==1506771 and competitors[0]['reason']=='numerical Python controller')
    test_result=read(REVIEW/'result.json');test_manifest=read(REVIEW/'source-manifest.json');test_junit=junit(REVIEW/'tests.xml')
    check('competing command exactly attributed to preserved test receipt',competitors[0]['argv']==test_result['command'])
    check('unique review output path in observed argv','--junitxml='+str(REVIEW/'tests.xml') in competitors[0]['argv'])
    check('review tests terminal successful',(test_junit['tests'],test_junit['failures'],test_junit['skips'],test_result['returncode'])==(174,0,0,0))
    for row in test_manifest['files']:
        path=SCIENTIFIC_SOURCE/row['path'];check('review source pin '+row['path'],pin(path)['sha256']==row['sha256'])
    for row in test_manifest['independent_tests']:
        prefix='execution-review01-' if '/execution-review01/' in row['path'] else 'execution-review02-'
        copy=REVIEW/(prefix+Path(row['path']).name)
        check('preserved independent test copy '+copy.name,pin(copy)['sha256']==row['sha256'])
    testcase_source=SCIENTIFIC_SOURCE/'tests/test_scientific_execution.py'
    test_ast=ast.parse(testcase_source.read_text())
    mock=next(n for n in test_ast.body if isinstance(n,ast.ClassDef) and n.name=='MockSupervisor')
    mock_calls=[n for n in ast.walk(mock) if isinstance(n,ast.Call)]
    forbidden={'Popen','run','run_owned','exec_command','fit_job_native'}
    check('review receipt identifies mocked control tests',test_manifest['scope']=='Pure mocked execution tests; no native fits or processes')
    check('mock supervisor implementation contains no process launcher',not any((isinstance(n.func,ast.Attribute) and n.func.attr in forbidden) or (isinstance(n.func,ast.Name) and n.func.id in forbidden) for n in mock_calls))
    test_start=datetime.datetime.fromisoformat(test_junit['suites'][0]['timestamp']).astimezone(datetime.timezone.utc)
    stop_time=mtime(CORRECTNESS/'result.json');test_end=mtime(REVIEW/'result.json')
    check('review interval brackets admission stop receipt',test_start<=stop_time<=test_end)
    check('sequence and correctness terminal receipts same second',abs((mtime(SEQUENCE/'result.json')-stop_time).total_seconds())<1)
    recovery=Path(plan['gate_controller']['path']);admission=function(recovery,'admission_from_snapshot')
    check('admission rejects without kill calls',not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('kill','killpg','terminate') for n in ast.walk(admission)))
    for stage in plan['cold_stages']:
        folder=COLD/stage;files=sorted(str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file())
        check(stage+' contains only frozen preparation request and rebinding',files==['rebinding.json','request.json'],files)
        journal=read(folder/'rebinding.json');pin(folder/'request.json')
        check(stage+' no warm/physical override',journal['initial_override'] is False and journal['nuisance_donor'] is False and journal['scientific_settings_unchanged'] is True)
    check('cold controller never started',all(not (COLD/name).exists() for name in ['result.json','run-started.json','detached-started.json','detached-result.json','launch.json']))
    check('cold phase gate explicitly prohibited',gate['all_ten_strict_passed'] is False and seq['phase']=='correctness' and seq['phase_receipt_errors']==[])
    check('stdlib audit has no numerical imports',not any(x.startswith(('numpy','scipy','jax','gtsam','orbit_poc')) for x in sys.modules))
    record={'schema':'candidate06-terminal-admission-stop-independent-audit-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'approved_terminal_attribution':all(x['passed'] for x in checks),'checks':checks,'check_count':len(checks),'failed_checks':[x for x in checks if not x['passed']],'stage_results':summaries,'remaining_stage_status':'Six stages never entered supervised execution; placeholder directories are preparation only.','cold_status':'Both exact cold fits were prepared but never launched.','stop':{'reason':'Primary host admission detected an overlapping separate mocked-controls pytest process.','observed_process':competitors[0],'receipt_attribution':'Exact argv and unique JUnit output path match the preserved successful source-only review; its JUnit interval brackets the primary failure receipt. PID/start ticks come from the primary admission observation, not a second independent process-start receipt.','test_start_utc':test_start.isoformat(),'correctness_result_mtime_utc':stop_time.isoformat(),'sequence_result_mtime_utc':mtime(SEQUENCE/'result.json').isoformat(),'review_result_mtime_utc':test_end.isoformat(),'timestamp_scope':'JUnit start plus file modification times of preserved terminal receipts; not a separately instrumented admission-event timestamp.','scheduling_responsibility':'The parent agent acknowledged authorizing overlapping review tests while the primary sequence was active. This coordination mistake triggered the unchanged admission guard; it was not an unexpected native-fit numerical failure.','admission_changed':False,'unrelated_workload_signaled_by_audited_receipts':False},'failure_separation':{'native_stage':'102 passed and 4 failed; all failures remain retained.','controller_stop':'Distinct pre-flight admission failure after both synthetic refinement stages, caused by overlapping review execution.','aggregate_qualified':False,'accepted_covariance':False,'release_authority':False,'old_failure_erasure':False},'timing_caveat':'Overlapping pure review jobs mean this campaign\'s stage and end-to-end timings are not uncontended benchmark measurements. Preserve them as observed validation timings only.','cleanup_scope':'All four stage terminal receipts certify kernel_ECHILD and empty owned trees; every recorded cleanup signal targets a tracked PID+start identity, not the detected competitor. This is not a claim about arbitrary host processes outside the audited receipts.','recovery_boundary':'No stopped-run repair, resume, admission-rule change, source edit or result substitution was performed. Fresh controls02/all-eleven validation is a separate future attempt.','evidence':list(evidence.values()),'audit_source':pin(__file__)}
    output=HERE/'audit01.json'
    with output.open('x') as f:json.dump(record,f,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'checks':len(checks),'passed':len(checks)-len(record['failed_checks']),'failed':record['failed_checks'],'audit':pin(output),'aggregate_qualified':False},indent=2))
    return 0 if record['approved_terminal_attribution'] else 1

if __name__=='__main__':raise SystemExit(main())
