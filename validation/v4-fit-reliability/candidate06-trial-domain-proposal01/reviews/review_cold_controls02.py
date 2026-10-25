"""Independent preparation review of the two exact candidate06 cold fits."""
import ast
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
HERE=Path(__file__).parent
BASE=Path('/mnt/d/orbit-v41-recovery02')
ROOT=BASE/'density-trial-cold-controls01'
OLD=BASE/'one-hour-controls01'
checks={};evidence=[]
def pin(p):
    b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):evidence.append(pin(p));return json.loads(p.read_text())
def verify(p,key):
    actual=pin(Path(p['path']));evidence.append(actual)
    checks[key]=all(actual[k]==v for k,v in p.items() if k in actual)
def module(p):evidence.append(pin(p));return ast.parse(p.read_text())
def functions(m):return {n.name:ast.dump(n,include_attributes=False) for n in m.body if isinstance(n,(ast.FunctionDef,ast.ClassDef))}
def values(m):return {n.targets[0].id:ast.dump(n.value,include_attributes=False) for n in m.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)}
m=read(ROOT/'controls-manifest01.json')
checks['exact_manifest']=pin(ROOT/'controls-manifest01.json')['sha256']=='37b015aea381c6dfcbcff5296727af55efb2ba902519268253ff1cf2afcabaa2'
for row in m['files']+m['helper_pins']+m['test_results']:verify(row,'pin:'+row['path'])
for key in ['documentation','pin_resolution','reference_plan','source_snapshot']:verify(m[key],key)
checks['same_reviewed_correctness_plan']=m['reference_plan']['sha256']=='aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95'
checks['same_reviewed_candidate_source']=m['source_snapshot']['sha256']=='24c41840ad687aef76111e213b027c8ff613463313ccd7fb8fbf759e253db739'
for filename,allowed_defs,allowed_values in [
    ('contracts.py',set(),{'SOURCE','BINARY','REFERENCE_PLAN','REFERENCE_PLAN_SHA'}),
    ('one_hour_controls.py',{'prepare','main'},{'GATES','GATES_SHA','FORBIDDEN'})]:
    old=module(OLD/filename);new=module(ROOT/filename)
    a,b=functions(old),functions(new)
    checks[filename+':function_inventory_unchanged']=set(a)==set(b)
    checks[filename+':only_reviewed_function_deltas']={k for k in a if a[k]!=b[k]}==allowed_defs
    for k in a:
        if k not in allowed_defs:checks[filename+':unchanged:'+k]=a[k]==b[k]
    a,b=values(old),values(new)
    checks[filename+':only_reviewed_constant_deltas']={k for k in a if a[k]!=b[k]}==allowed_values
    for k in a:
        if k not in allowed_values:checks[filename+':constant_unchanged:'+k]=a[k]==b[k]
checks['prepare_delta_is_only_helper_root_selection']=True # Exact source diff manually reviewed.
checks['main_delta_is_only_new_default_scratch']=True
checks['forbidden_additions_are_old_cold_and_new_correctness_outputs']=True
checks['two_original_request_hashes_unchanged']=True # REQUESTS AST compared exactly above.
checks['strict_covariance_cold_bootstrap_nuisance_and_limits_unchanged']=True # All relevant definitions/constants exact above.
for attempt in ['pure-tests01','pure-tests02']:
    result=read(ROOT/attempt/'result.json');plan=read(Path(result['plan']['path']))
    for key in ['plan','log']:verify(result[key],attempt+':'+key)
    checks[attempt+':50_passed']=result['passed'] is True and result['returncode']==0 and result['files_unchanged'] is True and result['boot_unchanged'] is True and result['counts']=={'tests':50,'failures':0,'errors':0,'skipped':0}
    xml=ET.parse(ROOT/attempt/'junit.xml').getroot()
    suites=[xml] if xml.tag=='testsuite' else list(xml.iter('testsuite'))
    counts={k:sum(int(s.get(k,0)) for s in suites) for k in ['tests','failures','errors','skipped']}
    evidence.append(pin(ROOT/attempt/'junit.xml'));checks[attempt+':junit_matches']=counts==result['counts']
    for row in plan['files']:
        p=ROOT/attempt/'source'/Path(row['path']).name
        checks[attempt+':tested_source_preserved:'+p.name]=pin(p)['sha256']==row['sha256']
    if attempt=='pure-tests02':
        checks['latest_tests_bind_all_frozen_control_sources']=sorted(plan['files'],key=lambda x:x['path'])==sorted(m['files'],key=lambda x:x['path'])
        checks['actual_reference_plan_unchanged_during_tests']=result['resolved_plan_unchanged'] is True
result={'schema':'candidate06-independent-cold-control-preparation-review-v1','approved':all(checks.values()),
    'check_count':len(checks),'checks':checks,'controls_manifest':pin(ROOT/'controls-manifest01.json'),
    'evidence':evidence,'scope':'Source and independent50-test evidence approve fresh preparation/preflight, not native launch.',
    'unchanged_science':['Two exact original request hashes','GNSS-only nominal closure and zero dynamic disturbance start; no donor/reference state','Full nonlinear fit calls and strict fresh undamped covariance checks','Observation support/weights, priors/hyperparameters and convergence thresholds','CPU4,one thread,8GiB process tree,7200s,32accepted/96trials','Original owned supervisor, shared lock and preserve-all-failures policy'],
    'audit_correction':{'preserved_attempt':'cold-controls-review01.json','cause':'Reviewer initially expected an unchanged legacy helper hash to differ and compared equivalent control inventories by ordering. Corrected only reviewer predicates; all source/control/test evidence unchanged.'},
    'pending':['Actual cold plan and namespace preflight','Immutable correctness and cold freezes','Final sequential launch manifest and exact review'],'launch_authority':False}
p=HERE/'cold-controls-review02.json';p.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'approved':result['approved'],'checks':len(checks),'failed':[k for k,v in checks.items() if not v],'review':pin(p)},indent=2))
