"""Read-only diagnosis of four original native-suite failures; no native launch."""
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE = Path('/mnt/d/orbit-v41-recovery02')
SOURCE = Path('/mnt/d/orbit-v41-density-trial-candidate06/source')
PARENT = Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
NATIVE = Path('/mnt/d/orbit-v41-recovery01/candidate04/native-source-04/source')
RUN = BASE / 'candidate06-correctness01/native-tests'
OUT = Path(__file__).parent
evidence = {}
checks = {}

def pin(path):
    path = Path(path); data = path.read_bytes()
    v = {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    evidence[str(path)] = v
    return v

def read(path):
    pin(path)
    return json.loads(Path(path).read_text())

def check(name, value):
    assert name not in checks
    checks[name] = bool(value)

def reference(path, needle):
    pin(path)
    return {'file': str(path), 'line': next(i for i,line in enumerate(Path(path).read_text().splitlines(),1) if needle in line), 'anchor': needle}

plan = read(BASE / 'candidate06-correctness01/plan.json')
freeze = read(BASE / 'candidate06-correctness01/freeze.json')
junit = RUN / 'tests.xml'; pin(junit)
tree = ET.parse(junit).getroot(); cases = list(tree.iter('testcase'))
failed = [c for c in cases if c.find('failure') is not None]
check('exact106inventory_102pass4fail_noerror_skip', len(cases) == 106 and len(failed) == 4 and not any(c.find('error') is not None or c.find('skipped') is not None for c in cases))
check('frozen_failed_stage_flag_is1', plan['jobs'][0]['stage'] == 'native-tests' and plan['jobs'][0]['environment']['ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY'] == '1')
check('candidate06_plan_identity_preserved', pin(BASE / 'candidate06-correctness01/plan.json')['sha256'] == freeze['plan']['sha256'] == 'aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95')
strict = read(RUN / 'strict-result.json')
supervisor = read(RUN / 'supervisor.json')
check('strict_failure_retained', strict['status'] == 'failed' and strict['returncode'] == 1 and strict['stage'] == 'native-tests')
check('owned_failed_stage_cleaned', supervisor['status'] == 'failed' and supervisor['returncode'] == 1 and supervisor['cleanup']['verified'] is True and supervisor['cleanup']['empty_tree_certificate'] == 'kernel_ECHILD' and supervisor['cleanup']['remaining'] == [] and supervisor['cleanup']['hard_kill'] is False)

source_files = ['tests/test_numerics_native_qr.py', 'groops/extension/orbitPocQrSolve.cpp', 'groops/extension/nuisanceLineSearch.h', 'tests/test_native_nuisance_fail_fast.py']
for name in source_files:
    a,b=SOURCE/name,PARENT/name
    check('unchanged_from_candidate04:' + name, pin(a)['sha256'] == pin(b)['sha256'])
compiled_fixture = NATIVE / 'programs/simulation/orbitPocQrSolve.cpp'
check('compiled_fixture_matches_source', pin(compiled_fixture)['sha256'] == pin(SOURCE / 'groops/extension/orbitPocQrSolve.cpp')['sha256'])
header = SOURCE / 'groops/extension/nuisanceLineSearch.h'
compiled_header = NATIVE / 'misc/orbitPoc/nuisanceLineSearch.h'
pin(compiled_header)
a,b=header.read_text(),compiled_header.read_text()
for start, end, name in [
    ('inline Bool nuisanceFailFastReplay()', 'inline Bool validNuisanceTrial', 'flag_parser'),
    ('inline NuisanceSearch searchNuisance(', 'inline std::string nuisanceJsonNumber', 'search_control_flow')]:
    check('compiled_controller_matches:' + name, a[a.index(start):a.index(end)] == b[b.index(start):b.index(end)])

mapping = [
 ('reject','test_native_nuisance_search_is1','Zero-update callback unconditionally forces reduction=-1, so identity replay fails before any alpha>0 trial.'),
 ('support','test_native_nuisance_search_is3','Zero-update callback unconditionally sets support321 instead of123. JSON does not export support itself; the source and floor_rejection establish the path.'),
 ('exception','test_native_nuisance_search_is4','Zero-update callback unconditionally throws injected child failure; the error is retained.'),
 ('floor_zero_replay','test_native_empirical_nuisance14','At alpha0 the fixture deliberately sets reduction1e-10; the immutable identity replay must reject.')]
results=[]
for mode, directory, explanation in mapping:
    folder=RUN/'pytest-temp'/directory
    report=read(folder/'search.json');pin(folder/'run.xml');pin(folder/'qr.parent.txt')
    check('invalid_replay_rejected_without_update:' + mode, report['accepted'] is False and report['stationary_without_update'] is False and report['nuisance_floor_limited'] is False and report['alpha'] == 0 and report['floor_rejection'] == 'zero_update_replay_failed' and report['trials'] == [] and report['nuisance_floor_audit'] == [])
    check('parent_transaction_preserved:' + mode, (folder/'qr.parent.txt').read_text() == 'parent\npreserved\n')
    results.append({'mode':mode,'directory':str(folder),'report':pin(folder/'search.json'),'observed_zero_replay':report['zero_update_replay'],'trials':len(report['trials']),'source_explanation':explanation})
check('reject_actual_replay_nonzero', results[0]['observed_zero_replay']['actual_reduction'] == -1)
check('exception_actual_replay_error', results[2]['observed_zero_replay']['status'] == 1 and results[2]['observed_zero_replay']['error'] == 'injected child failure')
check('floor_replay_nonzero', results[3]['observed_zero_replay']['actual_reduction'] == 1e-10)

tests=SOURCE/'tests/test_numerics_native_qr.py'
dedicated=SOURCE/'tests/test_native_nuisance_fail_fast.py'
controls=BASE/'density-trial-controls01/reference_gates09.py'
refs={
 'original17trial_assertions':[reference(tests,'assert len(report["trials"]) == 17')],
 'original_test_inherits_environment':reference(tests,'env=dict(os.environ, OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")'),
 'shared_flag':reference(controls,"'ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY': '1'"),
 'stage_environment':reference(controls,'def planned_stage_env(root):'),
 'base_environment':reference(controls,'def base_env():'),
 'default_flag_off':reference(header,'const std::string value=raw?raw:"0";'),
 'zero_replay_before_search':reference(header,'result.zeroUpdateReplay=isolatedNuisanceTrial(0.,evaluate);'),
 'failfast_guard':reference(header,'if(failFast&&(!validNuisanceTrial'),
 '17step_search_preserved':reference(header,'for(UInt attempt=0;attempt<17;attempt++)'),
 'fixture_unconditional_reject':reference(compiled_fixture,'if(nuisanceFixture=="reject")result.reduction=-1;'),
 'fixture_unconditional_support':reference(compiled_fixture,'if(nuisanceFixture=="support")result.support=321;'),
 'fixture_unconditional_exception':reference(compiled_fixture,'if(nuisanceFixture=="exception")throw'),
 'fixture_zero_replay_failure':reference(compiled_fixture,'if(nuisanceFixture=="floor_zero_replay"&&alpha==0)'),
 'dedicated_environment_sanitization':reference(dedicated,'def _environment('),
 'dedicated_invalid_replay_matrix':reference(dedicated,'def test_native_invalid_replay_keeps_legacy_work_unless_opted_in('),
 'dedicated_valid_replay_matrix':reference(dedicated,'def test_native_valid_replay_preserves_acceptance_and_stationarity('),
 'dedicated_valid_zero_replay_full17':reference(dedicated,'def test_valid_zero_replay_does_not_shortcut_rejected_proposals('),
 'dedicated_invalid_flag_before_fork':reference(dedicated,'def test_invalid_flag_is_rejected_before_any_child_callback('),
}
pin(BASE/'density-trial-sequence01/sequence.py')
pin(BASE/'density-trial-sequence01/plan.json')
pin(BASE/'density-trial-controls01/controls-manifest01.json')
pin(Path('/mnt/d/orbit-v41-density-review06/controls-review01.json'))
pin(Path('/mnt/d/orbit-v41-density-review06/correctness-launch-review02.json'))
result={
 'schema':'candidate06-independent-native-suite-failure-audit-v1','created_at':datetime.now(timezone.utc).isoformat(),
 'diagnosis_supported':all(checks.values()),'checks':checks,'check_count':len(checks),
 'current_suite_status':'failed;106tests,102passed,4failed,0errors,0skips. No reclassification or waiver.',
 'classification':'Validation-control environment versus unchanged original fixture contract mismatch. The four observed failures are the existing opt-in fail-fast behavior, not evidence of a candidate06 Python trial-domain change regressing production native acceptance.',
 'causal_chain':[
  'Controls derived from the eight production checks put ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY=1 in base_env; newly added native-tests inherited it without an explicit legacy-fixture environment.',
  'The original test subprocesses copy os.environ; original assertions intentionally demand17searchtrials for these rejection modes.',
  'Each of the four affected fixtures invalidates alpha0 itself. The already present fail-fast option correctly returns immediately with zero_update_replay_failed, preserving parent state, accepting no update and granting no floor/covariance authority.',
  'Original testsource, fixture source and search-controller logic are unchanged from candidate04. The actual candidate04 native source has only performance instrumentation around child evaluation relative to the extension header; the flag parser and search function are exact.',
  'The stage correctly failed and was cleaned. Subsequent correctness stages may continue to provide diagnostics, but this failed aggregate must not open the cold-fit gate.'
 ],
 'failed_cases':results,'references':refs,
 'meaningful_minimum_repair':{
  'scope':'A separately versioned validation-control repair; no current freeze/result/source mutation and no mathematical/native algorithm change justified by this evidence.',
  'original106':'Run the unchanged exact106 inventory with explicit ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY=0 for this compatibility test stage. This restores the original17trial test contract rather than reducing assertions. Pin the stage environment and retain all other reviewed limits/options.',
  'production':'Keep ORBIT_POC_NUISANCE_FAIL_FAST_REPLAY=1 in the eight physical/refinement/objective/replay stages and two full-fit regressions. Do not disable production fail-fast just to green the suite.',
  'supplementary37':'Require the unchanged existing test_native_nuisance_fail_fast.py as a separate additional native gate:12invalid-replay modes across unset/0/1,6valid-replay equivalence cases,8invalidnativeflag cases,3valid-zero/full17callback cases,8invalidflag-before-callback cases. Its helper explicitly sanitizes then sets the option.',
  'coverage_extension_if_needed':'If testing reject/support/exception after a valid zero replay under production flag1 is desired, add distinct fixture modes which alter only alpha>0 and retain the full17trial/rollback assertion. Do not repurpose the existing historical fixtures or count them as the original106.',
  'controls_tests':'Add pure stage-environment separation tests and freeze/argv/environment mismatch negatives. Check the actual namespace environment in preparation. A new sequence must require every original gate plus the separate supplementary opt-in gate before cold fitting.',
  'publication':'Publish the current failed106attempt and this diagnosis. Any passing replacement is a distinct attempt/control identity. Current failed sequence cannot be retroactively passed.'
 },
 'review_accountability':'Earlier independent controls/launch reviews verified exact source, argv, inventory, runtime and stage flags but missed that propagating the production fail-fast flag into the newly added unchanged106fixtures changed their intended execution path. Those approvals and their evidence remain preserved; this diagnosis corrects that semantic oversight.',
 'uncertainty':'This read-only trace does not prove future reruns pass or certify unrelated production behavior. The option equivalence and invalid-replay path already have meaningful dedicated tests, but their fresh execution remains required.',
 'preservation':{'native_runs':0,'tests_run':0,'controls_modified':False,'source_modified':False,'thresholds_changed':False,'current_attempt_modified':False,'cold_gate_must_remain_closed':True},
 'audit_source':pin(__file__),'evidence':list(evidence.values())
}
destination=OUT/'findings.json'
with destination.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
print(json.dumps({'path':str(destination),'sha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'diagnosis_supported':result['diagnosis_supported'],'checks':len(checks),'failures':[k for k,v in checks.items() if not v]}))
