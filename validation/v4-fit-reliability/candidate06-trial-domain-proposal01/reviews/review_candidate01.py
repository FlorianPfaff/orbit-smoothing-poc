"""Independent source-invariance and focused-test audit; no native execution."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

HERE=Path(__file__).parent
CANDIDATE=Path('/mnt/d/orbit-v41-density-trial-candidate06')
PARENT=Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
SOURCE=CANDIDATE/'source'
checks={}
evidence=[]

def data(path):
    value=path.read_bytes()
    evidence.append({'path':str(path),'sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)})
    return value

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def tree(path):
    return ast.parse(data(path).decode())

def defs(node):
    result={}
    for child in node.body:
        if isinstance(child,(ast.FunctionDef,ast.ClassDef)):
            result[child.name]=child
    return result

def dump(node):
    return ast.dump(node,include_attributes=False)

snapshot=json.loads(data(CANDIDATE/'source-snapshot.json'))
parent=json.loads(data(CANDIDATE/'parent-copy.json'))
old_files={p['relative_path']:p for p in parent['files']}
new_files={p['relative_path']:p for p in snapshot['files']}
actual_changes=[]
for rel,entry in new_files.items():
    checks['candidate_file:'+rel]=sha(SOURCE/rel)==entry['sha256'] and (SOURCE/rel).stat().st_size==entry['bytes']
    if rel not in old_files or entry['sha256']!=old_files[rel]['sha256']:
        actual_changes.append(rel)
for rel,entry in old_files.items():
    checks['preserved_parent:'+rel]=sha(PARENT/rel)==entry['sha256']
checks['no_parent_files_deleted']=set(old_files)<=set(new_files)
checks['only_two_existing_files_changed']=sorted(set(actual_changes)&set(old_files))==[
    'src/orbit_poc/numerics/backend.py','src/orbit_poc/numerics/optimizer.py']
checks['manifest_changes_exact']=sorted(actual_changes)==sorted(p['relative_path'] for p in snapshot['changes'])
checks['native_binary_identity']=sha(Path(snapshot['native_binary']['path']))==snapshot['native_binary']['sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
checks['no_native_source_or_rebuild']=snapshot['native_source_changed'] is False and snapshot['native_rebuild_required'] is False

old_backend=defs(tree(PARENT/'src/orbit_poc/numerics/backend.py'))
new_backend=defs(tree(SOURCE/'src/orbit_poc/numerics/backend.py'))
for name,node in old_backend.items():
    if name!='NativeModel':
        checks['backend_original_definition_unchanged:'+name]=dump(node)==dump(new_backend[name])
old_methods=defs(old_backend['NativeModel'])
new_methods=defs(new_backend['NativeModel'])
for name,node in old_methods.items():
    if name!='_close':
        checks['native_model_method_unchanged:'+name]=dump(node)==dump(new_methods[name])
close=copy.deepcopy(new_methods['_close'])
class RemoveClosureWrapper(ast.NodeTransformer):
    removed=0
    def visit_Try(self,node):
        if (len(node.body)==1 and isinstance(node.body[0],ast.Expr)
                and isinstance(node.body[0].value,ast.Call)
                and isinstance(node.body[0].value.func,ast.Attribute)
                and node.body[0].value.func.attr=='execute'):
            self.removed+=1
            return node.body
        return self.generic_visit(node)
rewriter=RemoveClosureWrapper(); close=rewriter.visit(close)
checks['closure_math_unchanged_except_execute_error_wrapper']=rewriter.removed==1 and dump(close)==dump(old_methods['_close'])

old_optimizer=defs(tree(PARENT/'src/orbit_poc/numerics/optimizer.py'))
new_optimizer=defs(tree(SOURCE/'src/orbit_poc/numerics/optimizer.py'))
for name,node in old_optimizer.items():
    if name!='minimize':
        checks['optimizer_original_definition_unchanged:'+name]=dump(node)==dump(new_optimizer[name])
minimize=copy.deepcopy(new_optimizer['minimize'])
class RemoveTypedTrialHandling(ast.NodeTransformer):
    classifiers=0
    records=0
    def visit_If(self,node):
        # Only reverse the two reviewed additions, never remove any original branch.
        if isinstance(node.test,ast.BoolOp) and len(node.test.values)==2:
            first=node.test.values[0]
            if (isinstance(first,ast.UnaryOp) and isinstance(first.operand,ast.Call)
                    and dump(first.operand)==dump(ast.parse('isinstance(error, PhysicalTrialDomainFailure)',mode='eval').body)):
                self.classifiers+=1;node.test=node.test.values[1]
        if dump(node.test)==dump(ast.parse('isinstance(error, PhysicalTrialDomainFailure)',mode='eval').body):
            expected=ast.parse('record["trial_domain_evidence"] = error.evidence').body
            if len(node.body)==1 and dump(node.body[0])==dump(expected[0]) and not node.orelse:
                self.records+=1;return None
        return self.generic_visit(node)
rewriter=RemoveTypedTrialHandling();minimize=rewriter.visit(minimize)
checks['optimizer_math_unchanged_except_typed_trial_rejection']=rewriter.classifiers==rewriter.records==1 and dump(minimize)==dump(old_optimizer['minimize'])

xml_path=HERE/'unit01/junit.xml'
xml=ET.fromstring(data(xml_path))
suites=[xml] if xml.tag=='testsuite' else list(xml.iter('testsuite'))
counts={name:sum(int(s.get(name,0)) for s in suites) for name in ['tests','failures','errors','skipped']}
checks['independent_67_tests_without_failures_or_skips']=counts=={'tests':67,'failures':0,'errors':0,'skipped':0}
for name in ['proposal-audit01.json','reference-replay-review01.json']:
    result=json.loads(data(HERE/name));checks['independent:'+name]=result['approved'] is True and all(result['checks'].values())
for name in ['tests/unit01/result.json','tests/unit02/result.json']:
    result=json.loads(data(CANDIDATE/name));checks['preserved_authored_receipt:'+name]=isinstance(result,dict)
data(HERE/'unit01/pytest.log')
data(SOURCE/'tests/test_numerics_trial_domain.py')
data(CANDIDATE/'tests/unit02/junit.xml')
data(Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python'))
result={'schema':'independent-candidate06-scientific-review-v1','approved':all(checks.values()),
    'check_count':len(checks),'checks':checks,'focused_tests':counts,
    'candidate_source_snapshot_sha256':sha(CANDIDATE/'source-snapshot.json'),
    'production_changes':actual_changes,'evidence':evidence,
    'scope':'Approve the minimal source correction for prescribed validation; not authorization to bypass validation or a completed full-fit/release claim.',
    'scientific_invariance':'AST comparison preserves all existing method bodies, objective, priors, force models, closure/covariance/rank tolerances and LM arithmetic except the evidenced typed trial error wrapper and its rejection recording.',
    'remaining_gates':['Prescribed correctness validation under fresh candidate source identity','Exact two cold full fits under unchanged scientific inputs and controls','Independent terminal-result and provenance audit'],
    'limitations':['Native reference replay was inspected independently, not rerun by reviewer.','No new nonlinear fit, native gate, source/control or archived output mutation by reviewer.']}
(HERE/'candidate-review01.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'approved':result['approved'],'check_count':len(checks),'failed':[k for k,v in checks.items() if not v],'focused_tests':counts},indent=2))
