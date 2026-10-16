from pathlib import Path
import importlib.util,copy,xml.etree.ElementTree as ET
import pytest
S=Path(__file__).with_name('replay_nominal_profile01.py');spec=importlib.util.spec_from_file_location('replay',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
T=Path(__file__).with_name('failed48h-iteration01.xml')
def nodes(t):return [list(p)[0] for p in t.findall('program')]
def test_only_declared_xml_changes():
 t=ET.parse(T).getroot();before=ET.tostring(t);n=m.tree_for(t,Path('/fresh/previous.dat'),Path('/fixed/state.txt'),Path('/fresh/iteration-01'));assert ET.tostring(t)==before
 p,e,c=nodes(n);assert p.findtext('orbitPocDerivativeProfile')=='synthetic_complete_v1';assert p.findtext('orbitPocDerivativeDiagnostics')=='/fresh/iteration-01/derivatives.json'
 for key in ('orbitPocDerivativeProfile','orbitPocDerivativeDiagnostics'):p.remove(p.find(key))
 for original,actual,keys in zip(nodes(t),(p,e,c),(('inputfileOrbit','outputfileVariational'),('inputfileVariational','outputfileOrbit','inputfileInitialState'),('inputfile','outputfile'))):
  for key in keys:actual.find(key).text=original.findtext(key)
 assert ET.tostring(n)==before
@pytest.mark.parametrize('tag',['orbitPocDerivativeProfile','orbitPocDerivativeDiagnostics'])
def test_reject_preconfigured_profile(tag):
 t=ET.parse(T).getroot();ET.SubElement(nodes(t)[0],tag).text='existing'
 with pytest.raises(ValueError):m.tree_for(t,Path('/r'),Path('/s'),Path('/o'))
@pytest.mark.parametrize('idx',[0,1,2])
def test_reject_program_inventory(idx):
 t=ET.parse(T).getroot();t.remove(t.findall('program')[idx])
 with pytest.raises(ValueError):m.tree_for(t,Path('/r'),Path('/s'),Path('/o'))
@pytest.mark.parametrize('idx,key',[(0,'inputfileOrbit'),(0,'outputfileVariational'),(1,'inputfileInitialState'),(2,'outputfile')])
def test_reject_missing_path(idx,key):
 t=ET.parse(T).getroot();p=nodes(t)[idx];p.remove(p.find(key))
 with pytest.raises(ValueError):m.tree_for(t,Path('/r'),Path('/s'),Path('/o'))
def test_pin_mutation(tmp_path):
 p=tmp_path/'f';p.write_text('original');pin={'path':str(p),'sha256':m.sha(p)};assert m.check(pin)==p;p.write_text('changed')
 with pytest.raises(ValueError):m.check(pin)
