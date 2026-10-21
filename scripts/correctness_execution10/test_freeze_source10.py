import copy,importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('freeze_source09',Path(__file__).with_name('freeze_source10.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
OLD={'tests/test_original.py':'a','tests/test_regression.py':'b','scripts/validate_numerics_one.py':'c','src/orbit_poc/numerics/backend.py':'d','groops/extension/example.h':'e'}
def fixture():
    previous={'source':{'files':copy.deepcopy(OLD)},'regression_suite':{'files':['tests/test_regression.py'],'expected_count':40}}
    files={**OLD,'groops/extension/example.h':'changed','tests/test_new.py':'new'}
    return previous,files

def test_new_regressions_preserve_previous_suite():
    previous,files=fixture();assert m.check_inventory(previous,files,['tests/test_new.py'],41)=={'files':['tests/test_regression.py','tests/test_new.py'],'expected_count':41}

@pytest.mark.parametrize('name',[x for x in OLD if x!='groops/extension/example.h'])
def test_protected_gate_and_existing_test_changes_rejected(name):
    previous,files=fixture();files[name]='modified'
    with pytest.raises(RuntimeError,match='changed'):m.check_inventory(previous,files,['tests/test_new.py'],41)

def test_deleted_existing_file_rejected():
    previous,files=fixture();del files['groops/extension/example.h']
    with pytest.raises(RuntimeError,match='delete'):m.check_inventory(previous,files,['tests/test_new.py'],41)

@pytest.mark.parametrize('regressions,count',[([],41),(['tests/test_new.py']*2,41),(['tests/test_regression.py'],41),(['tests/../test_new.py'],41),(['missing.py'],41),(['tests/test_new.py'],40),(['tests/test_new.py'],True)])
def test_invalid_regression_declarations_rejected(regressions,count):
    previous,files=fixture()
    with pytest.raises(RuntimeError):m.check_inventory(previous,files,regressions,count)

def test_previous_count_cannot_be_relabelled():
    previous,files=fixture();previous['regression_suite']['expected_count']=39
    with pytest.raises(RuntimeError,match='Previous40'):m.check_inventory(previous,files,['tests/test_new.py'],41)


def transition(tmp_path,monkeypatch,change=None,review_flag=True,pin_ok=True,regression_change=None):
    import ast,json
    base=tmp_path/'base';control=base/'control';control.mkdir(parents=True)
    old={'groops/extension/positionRemainder.py':'old','tests/test_original.py':'same','tests/test_new.py':'same-new'}
    prior={'commit':'prior09','source':{'files':old},'regression_suite':{'files':['tests/test_original.py','tests/test_new.py'],'expected_count':51}}
    (control/'candidate09-source-freeze.json').write_text(json.dumps(prior))
    files={**old,'groops/extension/positionRemainder.py':'corrected'}
    if change:change(files)
    regression=copy.deepcopy(prior['regression_suite'])
    if regression_change:regression_change(regression)
    tree=ast.parse(Path(m.__file__).read_text());function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='freeze')
    def assigns(n,name):return isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id==name for t in n.targets)
    start=next(i for i,n in enumerate(function.body) if assigns(n,'prior09_path'))
    end=next(i for i,n in enumerate(function.body) if assigns(n,'fp'))
    body=ast.Module(body=function.body[start:end],type_ignores=[]);ast.fix_missing_locations(body)
    namespace=dict(m.__dict__,BASE=base,files=files,review={'generated_tree_byte_equivalence':review_flag},freeze={},regression=regression)
    namespace['sha']=lambda path:'149f55da9ae92ee0d6c6c529125b1268c327f6ba0904b09898ddcc0cd57a4f1b' if pin_ok else 'wrong'
    exec(compile(body,'actual_installer_transition_guards','exec'),namespace)
    return namespace


def test_installer_only_transition_preserves_equal_inventory_and_test_count(tmp_path,monkeypatch):
    result=transition(tmp_path,monkeypatch)
    assert set(result['incremental'])=={'groops/extension/positionRemainder.py'}
    assert result['freeze']['execution_attempt']=='10' and result['freeze']['control_version']=='09'
    assert result['freeze']['immediate_previous_source_commit']=='prior09'
    assert result['freeze']['immediate_previous_source_freeze']['sha256']=='149f55da9ae92ee0d6c6c529125b1268c327f6ba0904b09898ddcc0cd57a4f1b'


@pytest.mark.parametrize('change',[
    lambda f:f.update({'unexpected.h':'new'}),
    lambda f:f.pop('tests/test_original.py'),
    lambda f:f.update({'tests/test_original.py':'changed'}),
    lambda f:f.update({'groops/extension/positionRemainder.py':'old'}),
])
def test_any_other_incremental_source_change_is_rejected(tmp_path,monkeypatch,change):
    with pytest.raises(RuntimeError,match='only the measured installer'):transition(tmp_path,monkeypatch,change=change)


@pytest.mark.parametrize('value',[False,None,'true'])
def test_generated_native_equivalence_requires_literal_independent_true(tmp_path,monkeypatch,value):
    with pytest.raises(RuntimeError,match='equivalence'):transition(tmp_path,monkeypatch,review_flag=value)


def test_changed_executed09_freeze_is_rejected(tmp_path,monkeypatch):
    with pytest.raises(RuntimeError,match='source freeze changed'):transition(tmp_path,monkeypatch,pin_ok=False)


@pytest.mark.parametrize('change',[lambda r:r.update(expected_count=52),lambda r:r['files'].reverse()])
def test_installer_correction_cannot_change_prior51_suite(tmp_path,monkeypatch,change):
    with pytest.raises(RuntimeError):transition(tmp_path,monkeypatch,regression_change=change)


def test_original_cumulative_inventory_guard_is_ast_identical():
    import ast
    root=Path(__file__).parent
    def tree(path):return next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='check_inventory')
    assert ast.dump(tree(root/'freeze_source09.py'),include_attributes=False)==ast.dump(tree(root/'freeze_source10.py'),include_attributes=False)


def test_supplementary_history_and_no_overwrite_guards_are_present():
    text=Path(m.__file__).read_text()
    for name in ('installer-correction10.json','immediate_previous_source_freeze','previous_pins','failed_pipeline','postprocess_pipeline','supplementary_correction'):
        assert name in text
    assert "'separate_regression_count':51" in text
    assert "not (C/name).exists() and not (C/name).is_symlink()" in text
