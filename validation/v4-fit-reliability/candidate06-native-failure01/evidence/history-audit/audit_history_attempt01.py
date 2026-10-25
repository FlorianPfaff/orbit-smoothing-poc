"""Read-only archived native test/environment attribution. Never executes native code."""
from pathlib import Path
import datetime,hashlib,json,xml.etree.ElementTree as ET
OUT=Path(__file__).resolve().parent
OLD=Path('/mnt/d/orbit-v41-recovery01')
C4=OLD/'candidate04'
C6=Path('/mnt/d/orbit-v41-density-trial-candidate06')
CUR=Path('/mnt/d/orbit-v41-recovery02/candidate06-correctness01')
REMOTE=OLD/'remote-native338-transfer04/full-attempt01/remote-evidence/validation-results04/native338-attempt04'
FLAG='ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY'
PINS=[]
def read(p):
 p=Path(p);b=p.read_bytes();PINS.append({'path':str(p),'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()});return b
def js(p):return json.loads(read(p))
def xml(p):
 root=ET.fromstring(read(p));cases={(x.attrib['classname'],x.attrib['name']):{'status':'failed' if x.find('failure') is not None else 'error' if x.find('error') is not None else 'skipped' if x.find('skipped') is not None else 'passed','failure':x.find('failure').attrib.get('message') if x.find('failure') is not None else None} for x in root.iter('testcase')}
 return {'counts':{'tests':len(cases),'failures':len(list(root.iter('failure'))),'errors':len(list(root.iter('error'))),'skipped':len(list(root.iter('skipped')))},'suite_metadata':[x.attrib for x in root.iter('testsuite')],'cases':cases}
def env_from_bwrap(args):return {args[i+1]:args[i+2] for i,x in enumerate(args) if x=='--setenv'}
def extract(names,cases):return [{'classname':a,'name':b,**cases[(a,b)]} for a,b in names]

def main():
 now=xml(CUR/'native-tests/tests.xml');remote=xml(REMOTE/'native/tests.xml');local=xml(C4/'native-tests04/native/tests.xml');ff=xml(REMOTE/'fail_fast/tests.xml')
 names=[key for key,value in now['cases'].items() if value['status']=='failed']
 assert len(names)==4 and now['counts']=={'tests':106,'failures':4,'errors':0,'skipped':0}
 assert set(now['cases'])==set(remote['cases'])==set(local['cases'])
 assert all(remote['cases'][x]['status']==local['cases'][x]['status']=='passed' for x in names)
 assert remote['counts']==local['counts']=={'tests':106,'failures':0,'errors':0,'skipped':0}
 assert ff['counts']=={'tests':37,'failures':0,'errors':0,'skipped':0}
 ff_cases=[{'classname':a,'name':b,**v} for (a,b),v in ff['cases'].items() if 'invalid_replay_keeps_legacy' in b]
 assert len(ff_cases)==12 and all(x['status']=='passed' for x in ff_cases)
 oldplan=js(REMOTE/'plan.json');oldsuper=js(REMOTE/'native/supervisor.plan.json');oldenv=env_from_bwrap(oldsuper['argv'])
 oldresult=js(REMOTE/'native/result.json');oldrequest=js(REMOTE/'native/request.json');oldstartup=js(REMOTE/'native/startup.json')
 aggregate=js(REMOTE/'result.json');prioraudit=js(OLD/'remote-native338-review03/audit_full354.json')
 localfreeze=js(C4/'native-tests04/freeze.json');localresult=js(C4/'native-tests04/native/result.json')
 currentplan=js(CUR/'plan.json');currentresult=js(CUR/'native-tests/strict-result.json');job=next(x for x in currentplan['jobs'] if x['stage']=='native-tests')
 assert '--clearenv' in oldsuper['argv'] and FLAG not in oldenv and FLAG not in localfreeze['environment']
 assert job['environment'][FLAG]=='1'
 binary=js(C4/'build-result04.json')['native'];actualbin=hashlib.sha256(read(binary['path'])).hexdigest()
 assert actualbin==binary['sha256']==oldplan['candidate_native_sha256']==oldrequest['native_sha256']==oldstartup['native_sha256']==prioraudit['candidate_native_sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
 assert any(x.get('path')==binary['path'] and x.get('sha256')==actualbin for x in currentplan['pins'])
 snap4=js(C4/'source-snapshot.json');snap6=js(C6/'source-snapshot.json');map4={x['relative_path']:x['sha256'] for x in snap4['files']};map6={x['relative_path']:x['sha256'] for x in snap6['files']}
 checked=[]
 for rel in ['tests/test_numerics_native_qr.py','tests/test_native_nuisance_fail_fast.py','groops/extension/nuisanceLineSearch.h','groops/extension/orbitPocQrSolve.cpp']:
  h4=hashlib.sha256(read(C4/'source'/rel)).hexdigest();h6=hashlib.sha256(read(C6/'source'/rel)).hexdigest();assert h4==h6==map4[rel]==map6[rel]
  checked.append({'relative_path':rel,'sha256':h4,'candidate04_candidate06_and_snapshots_match':True})
 for rel,installed in [('groops/extension/nuisanceLineSearch.h','source/misc/orbitPoc/nuisanceLineSearch.h'),('groops/extension/orbitPocQrSolve.cpp','source/programs/simulation/orbitPocQrSolve.cpp')]:
  assert hashlib.sha256(read(C4/'native-source-04'/installed)).hexdigest()==map4[rel]
 pub=js(Path('/mnt/d/orbit-v41-recovery02/publication14-01/packet/report.json'))
 assert pub['counts']=={'planned':8,'passed':8,'failed':0} and len(pub['stages'])==8 and all(x['stage'] not in ['native-tests','correction-tests'] for x in pub['stages'])
 diagnoses=[]
 for dirname,mode in [('test_native_nuisance_search_is1','reject'),('test_native_nuisance_search_is3','support'),('test_native_nuisance_search_is4','exception'),('test_native_empirical_nuisance14','floor_zero_replay')]:
  p=CUR/'native-tests/pytest-temp'/dirname/'search.json';d=js(p)
  diagnoses.append({'fixture_mode':mode,'receipt':str(p),'ordinary_trial_count':len(d['trials']),'accepted':d['accepted'],'stationary_without_update':d['stationary_without_update'],'nuisance_floor_limited':d['nuisance_floor_limited'],'floor_rejection':d['floor_rejection'],'zero_update_replay':d['zero_update_replay']})
  assert len(d['trials'])==0 and d['floor_rejection']=='zero_update_replay_failed' and d['accepted'] is False and d['stationary_without_update'] is False and d['nuisance_floor_limited'] is False
 report={
  'schema':'candidate06-native-failure-history-audit-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'passed_history_consistency_checks':True,
  'conclusion':'The same four tests previously passed with the same executable and identical test/native source. Their original106-test compatibility contract was exercised with fail-fast replay unset(default0). The new correctness control runs that unchanged suite with fail-fast replay1. The four observed zero-trial rejections exactly follow the existing opt-in branch and were separately expected/tested in the archived37-case fail-fast suite. This evidence identifies a validation-environment compatibility mismatch; it does not establish a new candidate06 production-code regression.',
  'current_gate_remains_failed':True,'current_outcome':{k:v for k,v in now.items() if k!='cases'},'current_terminal':{k:currentresult.get(k) for k in ['stage','status','returncode','error','scientific_command_seconds']},
  'failing_cases':extract(names,now['cases']),
  'prior_remote106':{'root':str(REMOTE/'native'),'counts':remote['counts'],'suite_metadata':remote['suite_metadata'],'same_four':extract(names,remote['cases']),'same_all106_testcase_identities':True,'native_binary_sha256':actualbin,'source_snapshot_sha256':oldplan['source_snapshot_sha256'],'cleared_environment':True,'fail_fast_replay':'unset; compiled default0','ORBIT_flags':{k:v for k,v in oldenv.items() if k.startswith('ORBIT_POC_')},'independent_354_audit_passed':prioraudit['passed']},
  'prior_local106':{'root':str(C4/'native-tests04/native'),'counts':local['counts'],'suite_metadata':local['suite_metadata'],'same_four':extract(names,local['cases']),'fail_fast_replay':'unset in frozen environment; default0','source_test_hash':localfreeze['source_snapshot']['tests/test_numerics_native_qr.py'],'native_build':binary},
  'prior_explicit_fail_fast37':{'root':str(REMOTE/'fail_fast'),'counts':ff['counts'],'relevant12_cases':ff_cases,'test_contract':'test_native_nuisance_fail_fast.py74–94: four invalid replay modes × default/legacy0/early1;17 trials unless flag1, then0. Accepted/stationary/floor-limited must remain false.'},
  'current_environment':{'plan_sha256':hashlib.sha256((CUR/'plan.json').read_bytes()).hexdigest(),'stage':job['stage'],'fail_fast_replay':job['environment'][FLAG],'ORBIT_flags':{k:v for k,v in job['environment'].items() if k.startswith('ORBIT_POC_')},'execution_binding':'reference_gates09.py654–657 verifies environment then subprocess.run(job.argv,env=job.environment); supervised current worker used frozen plan hash.'},
  'source_identity':checked,'actual_native_binary_sha256':actualbin,'compiled_native_overlay_matches':True,
  'causal_source_locations':[{'file':str(C4/'source/groops/extension/nuisanceLineSearch.h'),'lines':[135,141],'meaning':'Flag absent defaults0; only0/1 accepted.'},{'file':str(C4/'source/groops/extension/nuisanceLineSearch.h'),'lines':[235,255],'meaning':'With flag1 an invalid/nonidentity zero replay returns before pushing any ordinary trial.'},{'file':str(C4/'source/groops/extension/orbitPocQrSolve.cpp'),'lines':[346,346],'meaning':'floor_zero_replay injects nonzero reduction at alpha0.'},{'file':str(C4/'source/groops/extension/orbitPocQrSolve.cpp'),'lines':[381,384],'meaning':'reject/support/exception deliberately invalidate zero replay too.'},{'file':str(C6/'source/tests/test_numerics_native_qr.py'),'lines':[364,638],'meaning':'Unchanged legacy fixtures require17 ordinary trials.'}],
  'current_failed_native_receipts':diagnoses,
  'publication14_scope':{'path':'/mnt/d/orbit-v41-recovery02/publication14-01/packet/report.json','counts':pub['counts'],'stages':[x['stage'] for x in pub['stages']],'interpretation':'Eight reference-preservation checks only; it did not rerun106/51 and cannot support a106-pass claim under current flag1 environment.'},
  'limits':['No native replay or environment-toggle experiment was performed in this audit. Source branch and archived explicit flag tests explain the observed behavior.','Other historical runtime/system-library differences exist; exact executable/test identity is not full runtime identity.','Current four failures must remain failed in the frozen attempt. Any corrected stage-environment adapter requires separate controls, audit and validation; no in-place test or threshold changes.','Do not infer whole-fit convergence, covariance or release readiness from this compatibility diagnosis.'],
  'preservation':{'native_runs':0,'current_runs_changed':False,'source_or_tests_changed':False,'assertions_or_thresholds_relaxed':False},'evidence_pins':PINS}
 with (OUT/'history-audit.json').open('x') as f:json.dump(report,f,indent=2);f.write('\n')
 print(json.dumps({'history_audit':str(OUT/'history-audit.json'),'sha256':hashlib.sha256((OUT/'history-audit.json').read_bytes()).hexdigest(),'same106_cases':True,'same_binary_and_relevant_sources':True,'previous_flag':'unset/default0','current_flag':'1','prior_explicit_mode_tests':12,'new_native_runs':0},indent=2))
if __name__=='__main__':main()
