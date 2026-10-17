from pathlib import Path
import ast,copy,importlib.util,json,shutil
import pytest
C=Path(__file__).parent
spec=importlib.util.spec_from_file_location('auditor07',C/'audit_validation07_terminal01.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def records():
 readback=json.loads((C/'validation07-independent-packet-readback01.json').read_text());d={Path(r['path']).name:r['value']for r in readback['records']}
 startup=json.loads((C/'validation07-startup01-results/staging/namespace-smoke-01/run/probe-result/result.json').read_text())
 return [d['native-rebuild-provenance.json'],d['source-freeze.json'],d['segmented-v4.json'],{'runtimes':startup['runtimes']},d['launch-plan.json'],json.loads((C/'native-complete-build02-independent-terminal-review01.json').read_text())]

def test_actual_current_metadata_accepts():assert m.verify_complete_provenance(*records()) is True

MUTATIONS=[
 (0,('schema',),'orbit-poc-v4-native-rebuild-provenance-v1'),
 (0,('status',),'verified_actual_rebuild'),
 (5,('passed',),False),
 (5,('schema',),'unrelated'),
 *[(5,(k,),v)for k,v in [('compiled_objects',610),('cpp_objects',590),('fortran_objects',19),('fortran_preprocessing',19),('complete_commands',632),('reused_objects',1),('full_source_files',1133)]],
 *[(0,(k,'sha256'),'0'*64)for k in ('actual_build_result','original_recipe_inventory','normalized_configuration','complete_compile_evidence','baseline_relink','installation_equivalence','native_source_delta','build_base_result','previous_source','previous_config','runtime_provenance','repository_source_delta')],
 (0,('build_base_result','sha256'),'eb41fabb2117fd81c9d018793ad8e067f6ae65e86d71dae8e6ef8fcca4771133'),
 (1,('previous_source','sha256'),'0'*64),
 (1,('source','files','scripts/build_groops.py'),'0'*64),
 (1,('source','sha256'),'0'*64),
 (1,('allowed_changed_paths',),['groops/extension/sixStateTangent.h']),
 (1,('additional_paths',),[]),
 (0,('native_inputs','scripts/build_groops.py'),'0'*64),
 (0,('fixed_stage_names',),m.STAGES[::-1]),
 (0,('installed_source_mapping','base/polynomial.cpp'),'groops/extension/other.cpp'),
 (0,('candidate_native_source_root',),'/other/source'),
 (2,('dense_runtime','native','sha256'),'0'*64),
 (3,('runtimes','dense','native','sha256'),'0'*64),
 (2,('segmented_runtime','native','sha256'),'0'*64),
 (3,('runtimes','segmented','native','path'),'/different/native'),
 (5,('native','sha256'),'0'*64),
 (2,('segmented_runtime','build_manifest','sha256'),'0'*64),
 (5,('build_manifest','sha256'),'0'*64),
 (4,('native_equivalence','sha256'),'0'*64),
]
@pytest.mark.parametrize('record,path,value',MUTATIONS)
def test_reject_changed_binding(record,path,value):
 args=records();target=args[record]
 for key in path[:-1]:target=target[key]
 target[path[-1]]=value
 with pytest.raises(AssertionError):m.verify_complete_provenance(*args)

def test_missing_source_rejected():
 a=records();a[1]['source']['files'].pop('tests/test_wide_tangent_native.py')
 with pytest.raises(AssertionError):m.verify_complete_provenance(*a)

def tree(name):return ast.parse((C/name).read_text())
def func(t,name):return next(x for x in t.body if isinstance(x,ast.FunctionDef)and x.name==name)
def dump(x):return ast.dump(x,include_attributes=False)
def test_linearization_numerical_core_ast_unchanged():assert dump(func(tree('audit_validation05_terminal01.py'),'linearization_check'))==dump(func(tree('audit_validation07_terminal01.py'),'linearization_check'))
def test_replay_core_ast_only_sidecar_identity_changed():
 old=(C/'audit_validation05_terminal01.py').read_text().replace('5282b39135979ad51ab6065224e63174f7967d6599f5758231d47a74eea5dce8','f4209ee2011d7c566c1d51189745140155ebaf455db32d2999172f542ca15ec8').replace('actual precision-rebuild sidecar','actual complete-build sidecar')
 assert dump(func(ast.parse(old),'replay_check'))==dump(func(tree('audit_validation07_terminal01.py'),'replay_check'))
def test_all_fourteen_stage_acceptance_loop_ast_unchanged():
 loops=[]
 for name in ('audit_validation05_terminal01.py','audit_validation07_terminal01.py'):
  f=func(tree(name),'audit');loops.append(next(x for x in f.body if isinstance(x,ast.For)and isinstance(x.target,ast.Tuple)and [v.id for v in x.target.elts]==['index','step']))
 assert dump(loops[0])==dump(loops[1])
@pytest.mark.parametrize('name',['sha','canonical','pin','need','close'])
def test_unchanged_arithmetic_utilities(name):assert dump(func(tree('audit_validation05_terminal01.py'),name))==dump(func(tree('audit_validation07_terminal01.py'),name))
def test_support_records_are_exact_and_passed():assert len(m.supporting_reviews())==5
@pytest.mark.parametrize('which',list(m.SUPPORT))
def test_changed_support_record_rejected(tmp_path,monkeypatch,which):
 for name in m.SUPPORT:shutil.copyfile(C/name,tmp_path/name)
 (tmp_path/which).write_text('{}\n');monkeypatch.setattr(m,'C',tmp_path)
 with pytest.raises(AssertionError):m.supporting_reviews()
def test_current_identity_scope_does_not_claim_release_or_fits():
 source=(C/'audit_validation07_terminal01.py').read_text()
 assert "'release_ready':False"in source and "'fit_covariance_authorized':False"in source and "'benchmark_attempts_executed':0"in source
 assert m.NATIVE=='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
 assert len(m.STAGES)==14 and len(m.ADDITIONS)==21
