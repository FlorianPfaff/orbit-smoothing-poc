"""Independent preparation-scope audit of candidate06 validation controls."""
import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).parent
CONTROLS=Path('/mnt/d/orbit-v41-recovery02/density-trial-controls01')
OLD=CONTROLS.parent/'validation-controls07'
checks={};evidence=[]
def pin(path):
    value=path.read_bytes()
    return {'path':str(path),'sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)}
def read(path):
    evidence.append(pin(path));return json.loads(path.read_text())
def verify(record, label):
    actual=pin(Path(record['path']));evidence.append(actual)
    checks[label]=all(actual.get(k)==v for k,v in record.items() if k in ['path','sha256','bytes'])
def functions(path):
    evidence.append(pin(path));return {node.name:ast.dump(node,include_attributes=False)
        for node in ast.parse(path.read_text()).body if isinstance(node,ast.FunctionDef)}
def junit(path):
    evidence.append(pin(path));root=ET.parse(path).getroot()
    suites=[root] if root.tag=='testsuite' else list(root.iter('testsuite'))
    return {key:sum(int(s.get(key,0)) for s in suites) for key in ['tests','failures','errors','skipped']}

manifest=read(CONTROLS/'controls-manifest01.json')
checks['exact_reviewed_manifest']=pin(CONTROLS/'controls-manifest01.json')['sha256']=='43eb44f34a4c4f5a2b3e7e0fd9873f06fa9e7ae3ce932c4f165e08543b17ed93'
for row in manifest['files']:verify(row,'frozen_control:'+Path(row['path']).name)
for key in ['stdio_probe','documentation','candidate_source_snapshot']:verify(manifest[key],key)
for row in manifest['test_results']:verify(row,'authored_receipt:'+row['path'])
source=read(HERE/'candidate-review01.json')
checks['candidate_source_independently_approved']=source['approved'] is True and all(source['checks'].values())
checks['same_independently_approved_candidate']=source['candidate_source_snapshot_sha256']==manifest['candidate_source_snapshot']['sha256']

for name in ['reference_objective_output.py','reference_storage09.py']:
    checks['unchanged_composition_storage:'+name]=pin(CONTROLS/name)['sha256']==pin(OLD/name)['sha256']
before=functions(OLD/'reference_gates09.py');after=functions(CONTROLS/'reference_gates09.py')
allowed={'planned_stage_env','checked_plan','prepare','stage_worker','run'}
checks['existing_gate_control_change_set_exact']=set(k for k in before if before[k]!=after[k])==allowed
for name in before:
    if name not in allowed:checks['unchanged_gate_function:'+name]=before[name]==after[name]
oldrecovery=functions(OLD/'reference_recovery.py');newrecovery=functions(CONTROLS/'reference_recovery.py')
checks['existing_launcher_change_set_exact']=set(k for k in oldrecovery if oldrecovery[k]!=newrecovery[k])=={'inherited_environment','execute'}
for name in oldrecovery:
    if name not in {'inherited_environment','execute'}:checks['unchanged_launcher_function:'+name]=oldrecovery[name]==newrecovery[name]
probe=read(Path(manifest['stdio_probe']['path']))
checks['current_host_stdio_probe_passed']=probe['passed'] is True and probe['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip() and probe['source_unchanged'] is True and probe['scratch_empty_after_close'] is True and all(x['passed'] for x in probe['steps'])
verify(probe['probe'],'stdio_probe_script');verify(probe['source'],'stdio_native_source')
for attempt,count in [('pure-tests01',163),('pure-tests02',165)]:
    result=read(CONTROLS/attempt/'result.json');plan=read(Path(result['plan']['path']))
    verify(result['plan'],attempt+':plan');verify(result['log'],attempt+':log')
    checks[attempt+':passed']=result['passed'] is True and result['files_unchanged'] is True and result['boot_unchanged'] is True and result['returncode']==0 and result['counts']=={'tests':count,'failures':0,'errors':0,'skipped':0}
    checks[attempt+':junit_exact']=junit(CONTROLS/attempt/'junit.xml')==result['counts']
    for row in plan['files']:
        historical=CONTROLS/attempt/'source'/Path(row['path']).name
        checks[attempt+':preserved_tested_source:'+historical.name]=pin(historical)['sha256']==row['sha256']
    if attempt=='pure-tests02':checks['latest_authored_tests_bind_current_frozen_files']=plan['files']==manifest['files']

execution=read(HERE/'controls01/execution.json');plan=read(HERE/'controls01/plan.json')
checks['independent_execution_clean']=execution['returncode']==0 and execution['files_unchanged'] is True and execution['boot_unchanged'] is True
counts=junit(HERE/'controls01/junit.xml')
checks['independent165_no_failures_errors_skips']=counts=={'tests':165,'failures':0,'errors':0,'skipped':0}
checks['independent_exact_frozen_sources']=plan['files']==manifest['files']
checks['independent_frozen_manifest']=execution['source_control_manifest']==pin(CONTROLS/'controls-manifest01.json')
verify(execution['log'],'independent_log');verify(execution['plan'],'independent_plan')
result={'schema':'candidate06-independent-control-preparation-review-v1','approved':all(checks.values()),
    'check_count':len(checks),'checks':checks,'controls_manifest':pin(CONTROLS/'controls-manifest01.json'),
    'candidate_review':pin(HERE/'candidate-review01.json'),'focused_control_tests':counts,'evidence':evidence,
    'scope':'Controls approved for fresh preparation and complete readonly preflight; no native launch authority.',
    'scientific_invariance':'Original validation.command and check_result, 106/51 exact test inventories, four refinements, both objective/prior checks and both distinct replays preserved. All eight downstream stage settings and 8GiB limit unchanged. Added test-stage deadlines3600s and candidate06 source/current-boot binding; historical all_eight_fresh approval field retained with exact ten-stage plan enforcement.',
    'reviewed_operational_deltas':['Ten exact original GATE1 stages','Frozen candidate06 Python source; unchanged candidate04 native executable','Pytest import and exact compiler/helper pins for original test stages','Explicit test-native environment and disabled third-party plugin autoload','Current-host boot, exact source membership and unknown-stage rejection','Whitelist inherited controller environment and shared lock ownership checks'],
    'pending':['Actual prepared manifest semantic/runtime/input-identity review','Complete actual readonly namespace preflight and immutable freeze','Final cold-control pins and independent control tests/preflight','Final sequential-driver review and approved exact launch manifest'],
    'launch_authority':False,'native_gates_started_by_reviewer':False}
(HERE/'controls-review01.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'approved':result['approved'],'check_count':len(checks),'failed':[k for k,v in checks.items() if not v],'path':str(HERE/'controls-review01.json'),'sha256':pin(HERE/'controls-review01.json')['sha256']},indent=2))
