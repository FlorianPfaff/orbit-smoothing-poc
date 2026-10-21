from pathlib import Path
import importlib.util,xml.etree.ElementTree as ET,json,subprocess
import pytest
C=Path(__file__).parent;s=importlib.util.spec_from_file_location('r',C/'replay_nominal_tangent_capture02.py');r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
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
 source=tmp_path/'source';source.mkdir();names=['replay.cpp','probe.cpp','test_quad.py','test_telemetry_identity.py','include/manifest.json','include/sixStateTangent.h','include/syntheticForceDerivatives.h','include/eventQuadrature.h','base_test_replay.py'];files={}
 for name in names:
  p=source/name;p.parent.mkdir(exist_ok=True);p.write_bytes(name.encode());files[name]={'path':str(p),'sha256':r.sha(p)}
 p=tmp_path/'pins.json';p.write_text(json.dumps({'schema':'orbit-poc-tangent06-fixture-pins-v1','files':files}));native=tmp_path/'reader';native.write_bytes(b'binary');root=tmp_path/'output';root.mkdir();built={'reader_compile_command':['c++','-O3','-DNDEBUG','-std=gnu++17','-I'+str(source/'include'),str(source/'replay.cpp'),'-o',str(native)],'reader':{'path':str(native),'sha256':r.sha(native)}}
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
