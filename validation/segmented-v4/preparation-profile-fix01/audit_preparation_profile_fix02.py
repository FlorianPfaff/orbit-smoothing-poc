from pathlib import Path
from copy import deepcopy
import ast, datetime, hashlib, json, xml.etree.ElementTree as ET
C=Path('/mnt/d/orbit-segmented-v4/control');D=C/'preparation-profile-fix01';S=Path('/mnt/d/orbit-segmented-v4/source')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_bytes())
def dump(n):return ast.dump(n,include_attributes=False)
candidate=D/'candidate-files02.json'
assert sha(candidate)=='4e966eea96c426e78dd1d1f3370f2f271f6eeade8f20865f46319127844f939b'
rows=read(candidate);files={x['relative']:{'path':x['path'],'sha256':x['sha256']} for x in rows}
expected={'src/orbit_poc/segmented/multiday.py':'5a9f34a41ad6e301a82f347127669ceb1ce21c6f76a73747b239552438e889d8',
 'tests/test_segmented_multiday.py':'99c51178099be8ad5a8e0d36a41c3c9a14a551f4b15c38dc001a8a724f69bab4',
 'tests/test_comparison_initialization.py':'4edf979ecc7789ca0b65b0a86bcdbee9e4fc81b015b68626c334ab581e83256f'}
assert set(files)==set(expected)
old=read(Path('/mnt/d/orbit-segmented-v4/validation-02-packet/control/source-freeze.json'))
for row in rows:
    assert row['path']==str(S/row['relative']) and sha(row['path'])==row['sha256']==expected[row['relative']]
    assert Path(row['path']).stat().st_size==row['bytes']
    assert sha(D/'before'/row['relative'])==old['source']['files'][row['relative']]
before=ast.parse((D/'before/src/orbit_poc/segmented/multiday.py').read_text())
after=ast.parse((S/'src/orbit_poc/segmented/multiday.py').read_text())
oldfn=next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_one')
newfn=next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_one')
def config_if(n):
    return isinstance(n,ast.If) and n.body and isinstance(n.body[0],ast.Assign) and isinstance(n.body[0].value,ast.Call) and isinstance(n.body[0].value.func,ast.Name) and n.body[0].value.func.id=='configure_synthetic_forces'
orig=next(n for n in oldfn.body if config_if(n));changed=next(n for n in newfn.body if config_if(n))
assert dump(orig.test)==dump(changed.test) and not orig.orelse and not changed.orelse
assert len(orig.body)==1 and len(changed.body)==7
assert dump(changed.body[0])==dump(orig.body[0])
assert any(isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='_field' and [ast.literal_eval(x) for x in n.value.args[1:]]==['orbitPocDerivativeProfile','synthetic_complete_v1'] for n in changed.body)
imports=[n for n in newfn.body if isinstance(n,ast.ImportFrom) and n.module=='comparison.initialization']
assert len(imports)==1 and imports[0].level==2 and [(x.name,x.asname) for x in imports[0].names]==[('_field',None)]
newfn.body.remove(imports[0]);newfn.body[newfn.body.index(changed)]=deepcopy(orig)
assert dump(after)==dump(before)
for name,newname in [('tests/test_segmented_multiday.py','test_prepare_one_selects_corrected_profile_through_shared_closure'),('tests/test_comparison_initialization.py','test_shared_closure_preserves_legacy_profile_selection')]:
    b=ast.parse((D/'before'/name).read_text());a=ast.parse((S/name).read_text())
    added=[n for n in a.body if isinstance(n,ast.FunctionDef) and n.name==newname]
    assert len(added)==1;a.body.remove(added[0]);assert dump(a)==dump(b)
author=read(D/'author-validation02.json');assert author['passed'] is True
unchanged=[]
for row in author['unchanged_source_checks']:
    assert sha(row['path'])==row['sha256'];unchanged.append(row)
native={name:digest for name,digest in old['source']['files'].items() if name.startswith('groops/') or name=='scripts/build_groops.py'}
assert len(native)==70
for name,digest in native.items():assert sha(S/name)==digest
root=ET.parse(D/'independent-tests03.xml').getroot();suite=root if root.tag=='testsuite' else root.find('testsuite')
assert [int(suite.get(k,'0')) for k in ('tests','failures','errors','skipped')]==[31,0,0,0]
assert '31 passed, 2 deselected' in (D/'independent-tests03.log').read_text()
out=D/'independent-review02.json'
v={'schema':'orbit-poc-v4-preparation-profile-fix-independent-review-v1','passed':True,
 'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'candidate_files':pin(candidate),'patched_files':files,
 'helper':pin(Path(__file__)),'author_validation':pin(D/'author-validation02.json'),
 'independent_tests':{'passed':31,'failures':0,'errors':0,'skips':0,'deselected':2,
 'explicit_exclusion':'test_native_closure_loop_boundaries_use_offset_once: two native-environment parametrizations deferred to prescribed native validation',
 'junit':pin(D/'independent-tests03.xml'),'log':pin(D/'independent-tests03.log'),'cpu_affinity':[1],'native_runs':0},
 'preserved_prior_independent_run':{'junit':pin(D/'independent-tests02.xml'),'log':pin(D/'independent-tests02.log'),'scope':'31 passed; two unavailable native tests skipped because reviewer initially used the wrong exclusion expression. No native binary was configured or launched. Corrected explicit exclusion rerun passed31 with zero skips.'},
 'exact_ast_checks':{'only_production_change_is_synthetic_prepare_one_profile_wiring':True,'all_old_test_functions_unchanged':True,'one_new_two_parameter_test_in_each_test_module':True},
 'unchanged_source_checks':unchanged,'native_compilation_inputs_unchanged':{'count':70,'files':native},
 'same_input_native_diagnostic':pin(C/'nominal-profile-diagnostic01-terminal-independent-review/review.json'),
 'decision':'Approve these three exact files for a fresh source/config freeze and complete prescribed validation; no old gate outcome is inherited.',
 'scope':'V4 synthetic-only profile wiring selects the existing corrected native path before shared nominal closure. Physical forces, priors, weights, masks, hyperparameters, closure thresholds, shared defaults, flight branch and native implementation remain unchanged. Pure regressions and the exact48h diagnostic do not establish full validation or benchmark completion.'}
with out.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
