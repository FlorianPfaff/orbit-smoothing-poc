from pathlib import Path
import importlib.util,copy,pytest
s=importlib.util.spec_from_file_location('smoke',Path(__file__).with_name('smoke_shifted_runtime01.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def test_only_five_writable_paths_are_changed():
 e={'paths':{k:'/original/'+k for k in ('native_source','build','binaries','run','temporary','source','control','wrapper','root','python')},'read_only_bindings':[{'source':'/old','target':'/canonical'}],'runtime_artifacts':{'pinned':'unchanged'}};before=copy.deepcopy(e);new=m.derive(e,Path('/original/staging/smoke'))
 assert e==before and new['read_only_bindings']==e['read_only_bindings'] and new['runtime_artifacts']==e['runtime_artifacts']
 assert {k for k in e['paths'] if e['paths'][k]!=new['paths'][k]}=={'native_source','build','binaries','run','temporary'}
 assert all(str(Path(x)).startswith('/original/staging/smoke/') for k,x in new['paths'].items() if k in {'native_source','build','binaries','run','temporary'})
@pytest.mark.parametrize('bad',['helper','plan'])
def test_changed_control_identity_rejected_before_loading(tmp_path,bad):
 p=tmp_path/'plan.json';p.write_text('{}')
 with pytest.raises(RuntimeError,match='changed'):m.main(['--plan',str(p),'--sha256','0'*64 if bad=='plan' else m.sha(p),'--helper-sha256','0'*64 if bad=='helper' else m.sha(m.__file__)])
