from pathlib import Path
import importlib.util,xml.etree.ElementTree as ET,json,subprocess
import pytest
C=Path(__file__).parent;s=importlib.util.spec_from_file_location('r',C/'replay_nominal_tangent_capture03.py');r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
def original():return ET.parse(C/'failed72h-precision-iteration03.xml').getroot()
def nodes(t):return [list(p)[0] for p in t.findall('program')]
def test_only_output_fields_change():
 t=original();before=ET.tostring(t);n=r.tree_for(t,Path('/fresh/run'));assert ET.tostring(t)==before
 for a,b,keys in zip(nodes(t),nodes(n),(('outputfileVariational',),('inputfileVariational','outputfileOrbit'),('inputfile','outputfile'))):
  for key in keys:assert b.findtext(key).startswith('/fresh/run/');b.find(key).text=a.findtext(key)
 assert ET.tostring(n)==before
@pytest.mark.parametrize('profile',[None,'legacy_v3','flight_gravity_drag_v1'])
def test_reject_profile(profile):
 t=original();p=nodes(t)[0];q=p.find('orbitPocDerivativeProfile')
 if profile is None:p.remove(q)
 else:q.text=profile
 with pytest.raises(ValueError):r.tree_for(t,Path('/o'))
def test_reject_existing_telemetry():
 t=original();ET.SubElement(nodes(t)[0],'orbitPocDerivativeDiagnostics').text='/old'
 with pytest.raises(ValueError):r.tree_for(t,Path('/o'))
@pytest.mark.parametrize('idx,key',[(0,'inputfileOrbit'),(1,'inputfileInitialState'),(0,'outputfileVariational'),(1,'inputfileVariational'),(1,'outputfileOrbit'),(2,'inputfile'),(2,'outputfile')])
def test_reject_missing_path(idx,key):
 t=original();p=nodes(t)[idx];p.remove(p.find(key))
 with pytest.raises(ValueError):r.tree_for(t,Path('/o'))
@pytest.mark.parametrize('idx',[0,1,2])
def test_reject_programs(idx):
 t=original();t.remove(t.findall('program')[idx])
 with pytest.raises(ValueError):r.tree_for(t,Path('/o'))
def test_signature_strips_only_ansi():
 msg='six-state tangent did not meet its true residual tolerance: relative_residual=1.5e-11'
 assert r.failure_signature('\x1b[1;31m'+msg+'\x1b[0m')==msg
@pytest.mark.parametrize('value',['', 'six-state tangent did not meet its true residual tolerance:a\nsix-state tangent did not meet its true residual tolerance:b'])
def test_signature_rejects_inventory(value):
 with pytest.raises(ValueError):r.failure_signature(value)
def test_changed_pin_rejected(tmp_path):
 p=tmp_path/'a';p.write_text('old');pin={'path':str(p),'sha256':r.sha(p)};assert r.check(pin)==p;p.write_text('new')
 with pytest.raises(ValueError):r.check(pin)

def fixtures(tmp_path):
 source=tmp_path/'source';source.mkdir();names=['replay.cpp','probe.cpp','test_quad.py','test_compensation.py','include/manifest.json','include/sixStateTangent.h','include/syntheticForceDerivatives.h','include/eventQuadrature.h','base_test_replay.py'];files={}
 for name in names:
  p=source/name;p.parent.mkdir(exist_ok=True);p.write_bytes(name.encode());files[name]={'path':str(p),'sha256':r.sha(p)}
 p=tmp_path/'pins.json';p.write_text(json.dumps({'schema':'orbit-poc-tangent09-fixture-pins-v1','files':files}));native=tmp_path/'reader';native.write_bytes(b'binary');root=tmp_path/'output';root.mkdir();built={'reader_compile_command':['c++','-O3','-DNDEBUG','-std=gnu++17','-I'+str(source/'include'),str(source/'replay.cpp'),'-o',str(native)],'reader':{'path':str(native),'sha256':r.sha(native)}}
 return {'path':str(p),'sha256':r.sha(p)},built,root
def test_reader_preflight_runs_pinned_exact_tests(tmp_path,monkeypatch):
 pin,built,root=fixtures(tmp_path);calls=[]
 def run(argv,**kwargs):
  calls.append(argv)
  if '-m'in argv:
   junit=next(x.split('=',1)[1]for x in argv if x.startswith('--junitxml='));Path(junit).write_text('<testsuites><testsuite tests="3" errors="0" failures="0" skipped="0"/></testsuites>')
 monkeypatch.setattr(r.subprocess,'run',run);result=r.run_reader_fixtures(pin,built,root);assert result['status']=='passed' and result['nested_original_reader_checks']==8 and len(calls)==2;assert calls[0][1:4]==['-O3','-DNDEBUG','-std=gnu++17'];assert (root/'reader-fixtures/tangent72-diagnostic01/test_replay.py').read_bytes()==b'base_test_replay.py'
@pytest.mark.parametrize('field',['schema','files','source'])
def test_reader_preflight_rejects_bad_identity(tmp_path,field):
 pin,built,root=fixtures(tmp_path);p=Path(pin['path']);m=json.loads(p.read_text())
 if field=='schema':m['schema']='wrong'
 elif field=='files':m['files'].pop('probe.cpp')
 else:built['reader_compile_command'][-3]='/wrong/source'
 p.write_text(json.dumps(m));pin['sha256']=r.sha(p)
 with pytest.raises(ValueError):r.run_reader_fixtures(pin,built,root)
def test_reader_preflight_failure_is_not_pass(tmp_path,monkeypatch):
 pin,built,root=fixtures(tmp_path)
 def run(argv,**kwargs):raise subprocess.CalledProcessError(1,argv)
 monkeypatch.setattr(r.subprocess,'run',run)
 with pytest.raises(subprocess.CalledProcessError):r.run_reader_fixtures(pin,built,root)
@pytest.mark.parametrize('attribute',['tests="2"','failures="1"','skipped="1"'])
def test_reader_preflight_rejects_partial_or_skipped_tests(tmp_path,monkeypatch,attribute):
 pin,built,root=fixtures(tmp_path)
 def run(argv,**kwargs):
  if '-m'in argv:
   junit=next(x.split('=',1)[1]for x in argv if x.startswith('--junitxml='));attrs={'tests':'3','errors':'0','failures':'0','skipped':'0'};key,value=attribute.split('=');attrs[key]=value.strip('"');Path(junit).write_text('<testsuites><testsuite '+ ' '.join(k+'="'+v+'"' for k,v in attrs.items()) +'/></testsuites>')
 monkeypatch.setattr(r.subprocess,'run',run)
 with pytest.raises(ValueError):r.run_reader_fixtures(pin,built,root)

def current_failure(tmp_path):
 def pin(name,value):
  path=tmp_path/name;path.write_text(json.dumps(value)if not isinstance(value,str)else value);return {'path':str(path),'sha256':r.sha(path)}
 names={'template','initial_orbit','initial_text','initial_state','bootstrap','initialization','request','attitude','satellite_model','eop','ephemerides','gravityfield'}
 inputs={k:pin(k,k)for k in names};native={'path':'/current/native','sha256':'c'*64};capture={'path':'/capture/native','sha256':'d'*64};reader={'path':'/reader','sha256':'e'*64}
 recorded={'native_binary_sha256':'a'*64,'fixed_initial_state_si':[1,2,3,4,5,6],'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}
 plan={'native':native,'inputs':dict(inputs)};inputs['baseline_plan']=pin('baseline-plan',plan)
 signature='six-state tangent did not meet its true residual tolerance: relative_residual=1.285e-11'
 baseline={'status':'native_failed','plan_sha256':inputs['baseline_plan']['sha256'],'native':native,'fixed_initial_state_si':recorded['fixed_initial_state_si'],'initialization_criteria':{k:recorded[k]for k in('maximum_iterations','position_tolerance_m','velocity_tolerance_m_s')},'replay_failure_signature':signature}
 inputs['baseline_replay']=pin('baseline-replay',baseline);inputs['original_log']=pin('original-log',signature);inputs['reader']=reader
 build={'status':'built_diagnostic_only','native':capture,'reader':reader,'original_native':native,'baseline_relinked_sha256':native['sha256']}
 return {'inputs':inputs,'native':capture},build,recorded
def test_current_native_attribution_preserves_historical_initialization(tmp_path):
 p,b,recorded=current_failure(tmp_path);assert r.validate_current_baseline(p,b,recorded)['native']['sha256']=='c'*64;assert recorded['native_binary_sha256']=='a'*64
@pytest.mark.parametrize('wrong',['plan','native','state','criteria','physical','build','signature'])
def test_current_attribution_rejects_mismatch(tmp_path,wrong):
 p,b,recorded=current_failure(tmp_path);path=Path(p['inputs']['baseline_replay']['path']);baseline=json.loads(path.read_text())
 if wrong=='plan':baseline['plan_sha256']='0'*64
 if wrong=='native':baseline['native']['sha256']='0'*64
 if wrong=='state':baseline['fixed_initial_state_si'][0]=99
 if wrong=='criteria':baseline['initialization_criteria']['maximum_iterations']=11
 if wrong=='physical':p['inputs']['initial_orbit']['sha256']='0'*64
 if wrong=='build':b['baseline_relinked_sha256']='0'*64
 if wrong=='signature':baseline['replay_failure_signature']='different'
 path.write_text(json.dumps(baseline));p['inputs']['baseline_replay']['sha256']=r.sha(path)
 with pytest.raises(ValueError):r.validate_current_baseline(p,b,recorded)
