from pathlib import Path
import importlib.util,json,sys,types
import pytest
C=Path(__file__).parent
def load(name):
 s=importlib.util.spec_from_file_location(name,C/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
@pytest.mark.parametrize('case,mode,template,reference',[('preparation03','single','iteration-01/propagate.xml','initial'),('preparation03','closure','iteration-01/propagate.xml','initial'),('preparation04','single','iteration-03/propagate.xml','iteration-02'),('preparation04','closure','iteration-01/propagate.xml','initial')])
def test_distinct_archived_cases(case,mode,template,reference):
 m=load('stage_nominal_complete_checks02');r=m.selection(case,mode);assert r['template']==template and r['reference']==reference
 assert r['validation']==('validation-04'if case=='preparation03'else'validation-05')
def test_four_fresh_roots():
 m=load('stage_nominal_complete_checks02');roots={m.selection(c,s)['root']for c in('preparation03','preparation04')for s in('single','closure')};assert len(roots)==4 and all(x.startswith('tangent-complete-')for x in roots)
@pytest.mark.parametrize('mode',['single','closure'])
def test_failed_build_attribution_prevents_native_call(tmp_path,monkeypatch,mode):
 worker=load('replay_nominal_complete_'+mode+'02');calls=[]
 backend=types.SimpleNamespace(run_native=lambda *a,**k:calls.append(a));comparison=types.ModuleType('orbit_poc.comparison');comparison.backend=backend;protocol=types.ModuleType('orbit_poc.comparison.protocol');protocol.write_json=lambda *a:None
 parent=types.ModuleType('orbit_poc');parent.comparison=comparison
 for key,value in [('orbit_poc',parent),('orbit_poc.comparison',comparison),('orbit_poc.comparison.protocol',protocol)]:monkeypatch.setitem(sys.modules,key,value)
 fake=types.ModuleType('complete_native_replay_attribution02')
 def reject(*args):raise ValueError('Rejected actual build attribution')
 fake.verify=reject;monkeypatch.setitem(sys.modules,fake.__name__,fake)
 item=tmp_path/'item';item.write_text('{}');pin={'path':str(item),'sha256':worker.sha(item)}
 plan={k:pin for k in('execution','driver','worker','controller','native','source_freeze')};plan.update(schema=worker.SCHEMA,inputs={k:pin for k in worker.INPUTS},output=str(tmp_path/'out'),global_lock=str(tmp_path/'lock'))
 p=tmp_path/'plan.json';p.write_text(json.dumps(plan))
 with pytest.raises(ValueError,match='Rejected actual build attribution'):worker.main(['--plan',str(p),'--sha256',worker.sha(p)])
 assert not calls and not(tmp_path/'out').exists()
