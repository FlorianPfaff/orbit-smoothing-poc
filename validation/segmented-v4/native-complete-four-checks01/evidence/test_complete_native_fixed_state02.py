from pathlib import Path
import hashlib,importlib.util,json,sys,types,xml.etree.ElementTree as ET
import numpy as np
import pytest
C=Path(__file__).parent
@pytest.mark.parametrize('shifted',[False,True])
def test_actual_closure_path_requires_original_initial_state(tmp_path,monkeypatch,shifted):
 s=importlib.util.spec_from_file_location('closure',C/'replay_nominal_complete_closure02.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 def put(name,text):
  p=tmp_path/name;p.write_text(text);return {'path':str(p),'sha256':m.sha(p)}
 placeholder=put('placeholder','{}');inputs={k:placeholder for k in m.INPUTS};inputs['initial_orbit']=put('orbit.dat','archived');inputs['initial_state']=put('state.txt','fixed');inputs['initial_text']=put('orbit.txt','archived')
 tree=ET.parse(C/'failed72h-iteration01.xml');tree.find('./program/PreprocessingVariationalEquation/inputfileOrbit').text=inputs['initial_orbit']['path'];tree.find('./program/OrbitPocEvaluateVariational/inputfileInitialState').text=inputs['initial_state']['path'];inputs['template']=put('template.xml',ET.tostring(tree.getroot(),encoding='unicode'))
 target=np.zeros(6);inputs['initialization']=put('initialization.json',json.dumps({'fixed_initial_state_si':target.tolist(),'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}));inputs['original_log']=put('original.log','six-state tangent did not meet its true residual tolerance: original')
 epochs=np.array([0.,5.]);states=np.zeros((2,6));returned=states.copy()
 if shifted:returned[0,0]=1e-7
 calls=[]
 def save_xml(t,p):ET.ElementTree(t).write(p);return p
 backend=types.SimpleNamespace(_orbit=lambda p:(epochs,states if str(p)==inputs['initial_text']['path']else returned),_save_xml=save_xml,run_native=lambda *a,**k:calls.append(a)or{'returncode':0},NativeExecutionError=type('NativeExecutionError',(Exception,),{}))
 comparison=types.ModuleType('orbit_poc.comparison');comparison.backend=backend;parent=types.ModuleType('orbit_poc');parent.comparison=comparison;protocol=types.ModuleType('orbit_poc.comparison.protocol');protocol.write_json=lambda p,v:Path(p).write_text(json.dumps(v))
 attr=types.ModuleType('complete_native_replay_attribution02');attr.verify=lambda *a:({},{});attr.verify_supplemental=lambda *a:{}
 for name,obj in [('orbit_poc',parent),('orbit_poc.comparison',comparison),('orbit_poc.comparison.protocol',protocol),(attr.__name__,attr)]:monkeypatch.setitem(sys.modules,name,obj)
 plan={k:placeholder for k in('execution','driver','worker','controller','native','source_freeze')};plan.update(schema=m.SCHEMA,inputs=inputs,output=str(tmp_path/'out'),global_lock=str(tmp_path/'lock'));p=put('plan.json',json.dumps(plan))
 if shifted:
  with pytest.raises(ValueError,match='Fixed initial state changed'):m.main(['--plan',p['path'],'--sha256',p['sha256']])
 else:assert m.main(['--plan',p['path'],'--sha256',p['sha256']])==0
 result=json.loads((tmp_path/'out/result.json').read_text());assert len(calls)==1
 assert result['status']==('controller_failed'if shifted else'closed') and result['converged']is(not shifted)
