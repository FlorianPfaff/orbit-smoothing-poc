from pathlib import Path
import importlib.util,json,sys,types,pytest,subprocess
s=importlib.util.spec_from_file_location('probe',Path(__file__).with_name('validation04_startup_probe.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
@pytest.fixture
def fixture(tmp_path,monkeypatch):
 monkeypatch.syspath_prepend(str(Path(__file__).parent.parent/'source/src'))
 from orbit_poc.segmented import protocol as p,config as cfg,validation as v
 root=tmp_path/'root';source=root/'source';source.mkdir(parents=True);native=root/'native';native.write_text('same native');sidecar=Path(str(native)+'.build-manifest.json');sidecar.write_text(json.dumps({'executable_sha256':m.sha(native)}));solver=root/'solver';solver.write_text('solver')
 def file(name,content):
  path=root/name;path.write_text(content);return {'path':str(path),'sha256':m.sha(path)}
 inputs={'input_artifacts':{'old_nuisance_replay':file('old.xml','<first/>'),'candidate1_nuisance_replay':file('candidate.xml','<second/>'),'density_request':file('density.json','{"estimation_inputs":[]}'),'pulse_request':file('pulse.json','{"estimation_inputs":[]}'),'initial_state':file('initial.txt','initial')},'dependencies':[],'data_directories':[]}
 for i in range(9):inputs['input_artifacts']['other'+str(i)]=file('other'+str(i),'other')
 runtime={'source_root':str(source),'source_sha256':'source','native':{'path':str(native),'sha256':m.sha(native)},'segmented_solver':{'path':str(solver),'sha256':m.sha(solver)},'python':{'path':sys.executable,'sha256':'python'}}
 configuration=types.SimpleNamespace(segmented_runtime=types.SimpleNamespace(build_manifest=types.SimpleNamespace(sha256=m.sha(sidecar))),dense_runtime=object())
 monkeypatch.setattr(cfg,'load_config',lambda _:configuration);monkeypatch.setattr(p,'verify_runtime',lambda *_:runtime);monkeypatch.setattr(v,'verify_inputs',lambda *_:inputs);monkeypatch.setattr(p,'source_snapshot',lambda *_:{'sha256':'source'});monkeypatch.setattr(m.os,'access',lambda *_:False);monkeypatch.setattr(m.importlib.metadata,'version',lambda _:'4.2');monkeypatch.setitem(sys.modules,'gtsam',types.SimpleNamespace(JacobianFactor=types.SimpleNamespace(eliminate=lambda:None)))
 calls=[]
 def run(command,**kw):
  calls.append(command);out='3 tests collected' if any('test_segmented_native_tangent.py' in x for x in command) else '303 tests collected' if '--collect-only' in command else 'usage'
  return types.SimpleNamespace(returncode=0,stdout=out,stderr='')
 monkeypatch.setattr(m.subprocess,'run',run);return root,source,native,sidecar,inputs,calls,configuration,run

def test_all_six_dependencies_without_executing_gates(fixture):
 root,source,native,sidecar,inputs,calls,_,_=fixture;out=root/'output';assert m.main(['--root',str(root),'--output',str(out)])==0
 v=json.loads((out/'result.json').read_text());assert len(v['last_six_stage_startup'])==6 and not v['fit_or_numerical_gate_executed'];assert all('--help' in c or '--collect-only' in c for c in calls);assert len(calls)==7;assert v['last_six_stage_startup'][0]['source_profile']!=v['last_six_stage_startup'][1]['source_profile']
@pytest.mark.parametrize('mode',['missing_sidecar','wrong_sidecar','wrong_sidecar_hash','same_replays','incomplete_collection','stale_structural_collection','startup_failure','native_startup_failure','wrong_gtsam','writable_source','existing_output'])
def test_startup_failures_preserved(fixture,monkeypatch,mode):
 root,source,native,sidecar,inputs,calls,cfg,run=fixture;out=root/'output'
 if mode=='missing_sidecar':sidecar.unlink()
 elif mode=='wrong_sidecar':sidecar.write_text('{"executable_sha256":"wrong"}')
 elif mode=='wrong_sidecar_hash':cfg.segmented_runtime.build_manifest.sha256='wrong'
 elif mode=='same_replays':inputs['input_artifacts']['candidate1_nuisance_replay']=inputs['input_artifacts']['old_nuisance_replay']
 elif mode=='wrong_gtsam':monkeypatch.setattr(m.importlib.metadata,'version',lambda _:'4.3')
 elif mode=='writable_source':monkeypatch.setattr(m.os,'access',lambda *_:True)
 elif mode=='existing_output':out.mkdir()
 else:
  def altered(command,**kw):
   result=run(command,**kw)
   if mode=='incomplete_collection' and '--collect-only' in command:result.stdout='2 tests collected'
   if mode=='stale_structural_collection' and '--collect-only' in command and not any('test_segmented_native_tangent.py' in x for x in command):result.stdout='301 tests collected'
   if mode=='startup_failure' or mode=='native_startup_failure' and command[0]==str(native):result.returncode=1
   return result
  monkeypatch.setattr(m.subprocess,'run',altered)
 with pytest.raises((ValueError,FileNotFoundError)):m.main(['--root',str(root),'--output',str(out)])
 assert not (out/'result.json').exists()
