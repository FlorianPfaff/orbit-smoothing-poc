"""Independent read-only audit of the closed original-test early stop in execution09."""
from pathlib import Path
import datetime, hashlib, json, xml.etree.ElementTree as ET
ROOT=Path('@EXECUTION_09_ROOT@')
RUN=ROOT/'validation-09'
ARTIFACTS={}
EXPECTED_PINS='bef26212c810f13ac9a1050034c61e99d5a4d944a4b4edd768a31f7de5a7fb81'
EXPECTED_NATIVE='beaf1afc41c5102477fdcd27b81a146aac9916b487ffb235eb4d15a37241d774'
EXPECTED_SOURCE='029864cfbb2140007d0767505e0f4a655912a9ff053e135fd2bc0f434415b498'
EXPECTED_PIPELINE='c66d830ce7c8ca98e916706e6d30a0724b54efeb7d65f678702193fbeb30731e'
EXPECTED_POST='726e3d744d921dfe7ababd849cc78b824c4b1e0f53e789bdb578dad6867e01e2'
PLANNED=['clone','checkout','build','native-tests','correction-regression-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012']
def require(value, message):
    if not value:
        raise AssertionError(message)

def read(path, kind='json'):
    path = Path(path)
    raw = path.read_bytes()
    key=str(path.relative_to(ROOT)) if ROOT in path.parents else str(path)
    ARTIFACTS[key]={'path':str(path), 'sha256':hashlib.sha256(raw).hexdigest(), 'bytes':len(raw)}
    if kind == 'json':
        return json.loads(raw)
    if kind == 'xml':
        return ET.fromstring(raw)
    return raw

def host_path(path,execution):
    path=Path(path)
    for binding in sorted(execution['read_only_bindings'],key=lambda b:len(Path(b['target']).parts),reverse=True):
        target=Path(binding['target'])
        if path==target or target in path.parents:return Path(binding['source'])/path.relative_to(target)
    return path

def verify_identity(pipeline):
    pins_path=ROOT/'control/candidate09-pins.json';pins=read(pins_path)
    require(ARTIFACTS[str(pins_path.relative_to(ROOT))]['sha256']==EXPECTED_PINS,'Wrong09 pins')
    execution=read(ROOT/'control/candidate09-execution.json')
    require(ARTIFACTS['control/candidate09-execution.json']['sha256']==pins['execution_sha256'],'Execution changed')
    original_path=host_path(pins['candidate03_pins']['path'],execution);original=read(original_path)
    require(hashlib.sha256(original_path.read_bytes()).hexdigest()==pins['candidate03_pins']['sha256'],'Original03 pins changed')
    require(pins['input_artifacts']==original['input_artifacts'] and len(pins['input_artifacts'])==14,'Original14 inputs changed')
    hashes={}
    for name,item in pins['input_artifacts'].items():
        raw=read(host_path(item['path'],execution),'bytes');hashes[name]=hashlib.sha256(raw).hexdigest();require(hashes[name]==item['sha256'],'Input changed: '+name)
    frozen=read(pins['new_source_freeze']['path']);require(hashlib.sha256(Path(pins['new_source_freeze']['path']).read_bytes()).hexdigest()==pins['new_source_freeze']['sha256'],'Source freeze changed')
    require(frozen['commit']=='7e232423566a9d608ada0bcc88af8a86dd914db3' and frozen['source']==pipeline['source'],'Wrong frozen candidate')
    files=frozen['source']['files'];require(len(files)==772,'Wrong source count')
    for name,digest in files.items():require(hashlib.sha256((ROOT/'source'/name).read_bytes()).hexdigest()==digest,'Source changed: '+name)
    require(pins['expected_native_test_count']==106 and pins['regression_suite']['expected_count']==51,'Test inventory changed')
    for name,key in [('validate_candidate_09.py','driver_sha256'),('with_correctness_namespace_09.py','wrapper_sha256'),('recovery_evidence_09.py','recovery_verifier_sha256')]:
        require(hashlib.sha256(read(ROOT/'control'/name,'bytes')).hexdigest()==pins[key],'Control changed: '+name)
    return {'original14_preserved':True,'input_hashes':hashes,'source_files_verified':len(files),'source_freeze_sha256':pins['new_source_freeze']['sha256'],'execution_sha256':pins['execution_sha256'],'pins_sha256':ARTIFACTS['control/candidate09-pins.json']['sha256']}

def processes(pipeline):
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();identities=[]
    for name,key in [('candidate09-launch.json','driver_process'),('candidate09-postprocess-launch.json','postprocess_process')]:
        receipt=read(ROOT/'control'/name);identities.append(receipt[key])
    observations=[]
    for item in identities:
        require(item['boot_id']==boot,'Execution host rebooted before audit')
        observation=dict(item,observed_boot_id=boot);path=Path('/proc')/str(item['pid'])/'stat'
        try:
            fields=path.read_text().rsplit(')',1)[1].split();observation.update(observed_state=fields[0],observed_start_ticks=int(fields[19]),exact_identity_live=int(fields[19])==item['start_ticks'] and fields[0]!='Z')
        except (FileNotFoundError,ProcessLookupError):observation.update(proc_exists=False,exact_identity_live=False)
        require(not observation['exact_identity_live'],'Exact driver/postprocessor still live');observations.append(observation)
    return observations

def junit(tree):
    cases=list(tree.iter('testcase'))
    identities=[(c.get('classname'),c.get('name')) for c in cases]
    require(len(cases)==106 and len(set(identities))==106,'Wrong or duplicate original test inventory')
    counts={k:sum(c.find(k) is not None for c in cases) for k in ('failure','error','skipped')}
    require(counts=={'failure':2,'error':0,'skipped':0},'Unexpected original test outcome')
    failures=[{'classname':c.get('classname'),'name':c.get('name'),'message':c.find('failure').get('message'),'details':c.find('failure').text} for c in cases if c.find('failure') is not None]
    require({f['name'] for f in failures}=={'test_installer_is_idempotent_and_preserves_compatibility_output','test_piecewise_exact_legacy_batch_and_both_receiver_caches'},'Unexpected failed tests')
    require(all(f['classname']=='tests.test_numerics_geometry_precision' and f['message']=='ValueError: Relative query patch anchor mismatch: twofold light-time duration' for f in failures),'Unexpected failure attribution')
    suites=list(tree.iter('testsuite'))
    require(sum(int(s.get('tests','0')) for s in suites)==106 and sum(int(s.get('failures','0')) for s in suites)==2,'JUnit totals differ')
    return {'tests':106,'passed':104,'failures':2,'errors':0,'skipped':0,'failure_details':failures}


def absent_process(identity):
    p=Path('/proc')/str(identity['pid'])
    try:
        stat=(p/'stat').read_text().rsplit(')',1)[1].split();namespace=str((p/'ns/pid').readlink())
    except (FileNotFoundError,ProcessLookupError):return True
    return not(int(stat[19])==identity['start_ticks'] and namespace==identity['pid_namespace'] and stat[0]!='Z')


def main():
    pipeline=read(RUN/'pipeline.json');post=read(ROOT/'postprocess-09-01/pipeline.json')
    require(ARTIFACTS['validation-09/pipeline.json']['sha256']==EXPECTED_PIPELINE and ARTIFACTS['postprocess-09-01/pipeline.json']['sha256']==EXPECTED_POST,'Closed journal changed')
    require(pipeline['status']=='failed' and [s['name'] for s in pipeline['steps']]==PLANNED[:4],'Not the expected early-stop journal')
    require([(s['status'],s['returncode']) for s in pipeline['steps']]==[('passed',0)]*3+[('failed',1)],'Early-stop status mismatch')
    require(pipeline['error']=='RuntimeError: native-tests failed; inspect the preserved log','Wrong driver stop reason')
    identity=verify_identity(pipeline)
    require(pipeline['native']['sha256']==EXPECTED_NATIVE and pipeline['source']['sha256']==EXPECTED_SOURCE,'Candidate identity differs')
    require(hashlib.sha256(read(pipeline['native']['path'],'bytes')).hexdigest()==EXPECTED_NATIVE,'Native bytes changed')
    build=Path(pipeline['native']['path']+'.build-manifest.json')
    require(hashlib.sha256(read(build,'bytes')).hexdigest()==pipeline['native']['build_manifest_sha256'],'Build manifest differs')
    tests=junit(read(RUN/'native-tests.xml','xml'))
    missing=[]
    for name in PLANNED[4:]:
        paths=[RUN/name,RUN/(name+'.xml'),RUN/(name+'.log')]
        require(not any(p.exists() for p in paths),'Later-stage output exists: '+name)
        missing.append({'name':name,'status':'not_run','reason':'driver stopped after original106 test failures'})
    require(pipeline['final_cleanup']['verified'] is True,'Native cleanup unverified')
    owned=[]
    for command in pipeline['final_cleanup']['commands']:
        require(command['verified'] is True and not command['live_owned_processes'],'Native child cleanup unverified')
        for item in command['identities']:
            require(absent_process(item),'Exact native owned process remains live');owned.append(item)
    require(post['status']=='completed' and post['scientific_status']=='failed' and post['validation_status']=='failed','Postprocessor outcome relabelled')
    require(post['validation_pipeline']['sha256']==EXPECTED_PIPELINE,'Postprocessor attribution differs')
    require([(s['name'],s['returncode']) for s in post['steps']]==[('audit',1),('report',0),('collect',0)],'Postprocess statuses differ')
    for s in post['steps']:
        require(s['status']=='exited' and s['cleanup_verified'] is True,'Postprocess cleanup incomplete')
        raw=read(s['result']['path'],'bytes');require(len(raw)==s['result']['bytes'] and hashlib.sha256(raw).hexdigest()==s['result']['sha256'],'Postprocess result changed')
    process_observations=processes(pipeline)
    print(json.dumps({'schema':'orbit-poc-terminal09-independent-partial-audit-v1','reviewer':'@AGENT_ROOT@/v31_recovery_review','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'consistency_audit_passed':True,'status':'required_gate_suite_failed','pipeline_status':'failed','source_commit':'7e232423566a9d608ada0bcc88af8a86dd914db3','source_sha256':EXPECTED_SOURCE,'source_files':772,'native_sha256':EXPECTED_NATIVE,'identity':identity,'artifacts':ARTIFACTS,'native-tests':tests,'planned_steps':[{'name':s['name'],'status':s['status'],'returncode':s['returncode']} for s in pipeline['steps']]+missing,'postprocessing':{'status':'completed','scientific_status':'failed','steps':[{'name':s['name'],'returncode':s['returncode'],'cleanup_verified':True} for s in post['steps']]},'cleanup_verified':True,'native_owned_process_identities_checked':len(owned),'live_exact_owned_processes':[],'independent_process_observations':process_observations,'scientific_correctness_gate_passed':False,'strict_nuisance_convergence_everywhere':None,'covariance_authorized':False,'release':'not_assessed','bounded_benchmark_complete':False,'scope':'Independent early-stop receipt/source/input/current-process audit; no native build or fit executed by reviewer. Both objectives, four refinements, both original replays and51 regressions were not run.','limitations':['This attempt gives no new objective, derivative, nuisance convergence or covariance result.','A successful report and collector preserve failed scientific status.','The complete150-fit benchmark and v3.1 release remain incomplete.']},sort_keys=True,indent=2))

if __name__=='__main__':main()
