from pathlib import Path
import importlib.util,json,subprocess
import pytest
C=Path(__file__).parent
def load(name):
 s=importlib.util.spec_from_file_location(name,C/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
r=load('compensation_native_regression01');s=load('stage_nominal_compensation_checks02')
def built(tmp_path,monkeypatch):
 root=tmp_path/'native';header=root/'native_source/source/misc/orbitPoc/sixStateTangent.h';header.parent.mkdir(parents=True);header.write_text('candidate')
 monkeypatch.setattr(r,'EXPECTED_HEADER',r.sha(header));compiler=tmp_path/'compiler';compiler.write_text('compiler')
 return {'native':{'path':str(root/'binaries/groops'),'sha256':'a'*64},'source_after':{'misc/orbitPoc/sixStateTangent.h':r.sha(header)},'compile_commands':{str(i):[str(compiler),'-O3','-DNDEBUG','-std=gnu++17']for i in range(27)}}
def test_exact_compile_recipe(tmp_path,monkeypatch):
 b=built(tmp_path,monkeypatch);argv,h=r.recipe(b,tmp_path/'fixture',tmp_path/'output');assert argv[1:4]==['-O3','-DNDEBUG','-std=gnu++17'];assert argv[4:6]==['-I',str(h.parent)]
@pytest.mark.parametrize('failure',['header','count','compiler','flag'])
def test_reject_mismatched_build(tmp_path,monkeypatch,failure):
 b=built(tmp_path,monkeypatch)
 if failure=='header':b['source_after']['misc/orbitPoc/sixStateTangent.h']='0'*64
 if failure=='count':b['compile_commands'].pop('0')
 if failure=='compiler':b['compile_commands']['0'][0]='other'
 if failure=='flag':b['compile_commands']['0'].remove('-DNDEBUG')
 with pytest.raises(ValueError):r.recipe(b,tmp_path/'fixture',tmp_path/'output')
def test_run_records_explicit_fixture_success(tmp_path,monkeypatch):
 b=built(tmp_path,monkeypatch);fixture=tmp_path/'fixture';fixture.write_text('fixture');calls=[]
 def run(argv,**kw):
  calls.append((argv,kw['timeout']))
  if len(calls)==1:Path(argv[-1]).write_text('binary')
  else:kw['stdout'].write(b'compensated quadrature regression passed\n')
 monkeypatch.setattr(r.subprocess,'run',run);out=r.run(tmp_path/'out',b,fixture)
 assert out['status']=='passed'and[c[1]for c in calls]==[90,30]and not out['frozen_suite_counts_changed']
def test_failure_preserved_without_propagation(tmp_path,monkeypatch):
 b=built(tmp_path,monkeypatch);fixture=tmp_path/'fixture';fixture.write_text('fixture')
 def run(*args,**kw):raise subprocess.CalledProcessError(1,args[0])
 monkeypatch.setattr(r.subprocess,'run',run)
 with pytest.raises(subprocess.CalledProcessError):r.run(tmp_path/'out',b,fixture)
 assert json.loads((tmp_path/'out/result.json').read_text())['status']=='failed'
def test_four_distinct_archived_cases():
 cases={(case,mode):s.selection(case,mode)for case in('preparation03','preparation04')for mode in('single','closure')}
 assert len({v['root']for v in cases.values()})==4
 assert cases['preparation03','single']['reference']=='initial'
 assert cases['preparation04','single']['reference']=='iteration-02'
 assert cases['preparation04','single']['template']=='iteration-03/propagate.xml'
 for case in('preparation03','preparation04'):
  assert cases[case,'closure']['reference']=='initial'and cases[case,'closure']['template']=='iteration-01/propagate.xml'
 assert cases['preparation03','closure']['validation']!=cases['preparation04','closure']['validation']
@pytest.mark.parametrize('case,mode',[('other','single'),('preparation04','other')])
def test_unknown_check_rejected(case,mode):
 with pytest.raises(ValueError):s.selection(case,mode)
def test_ro_mapping_exact_reuse_only():
 e={'read_only_bindings':[{'source':'/old','target':'/old'}]};s.add_ro(e,Path('/old'));assert len(e['read_only_bindings'])==1
 e['read_only_bindings'][0]['source']='/different'
 with pytest.raises(ValueError):s.add_ro(e,Path('/old'))
