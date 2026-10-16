from pathlib import Path
import importlib.util,xml.etree.ElementTree as ET
import pytest
C=Path(__file__).parent;s=importlib.util.spec_from_file_location('r',C/'replay_nominal_complete_single02.py');r=importlib.util.module_from_spec(s);s.loader.exec_module(r)
def original():return ET.parse(C/'failed72h-iteration01.xml').getroot()
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
