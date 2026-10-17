from pathlib import Path
import importlib.util,json,copy
import pytest
C=Path(__file__).parent;s=importlib.util.spec_from_file_location('b',C/'build_tangent_capture01.py');b=importlib.util.module_from_spec(s);s.loader.exec_module(b)
OLD=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/engineering-02/groops-source');NEW=Path('/fresh/native-source')
def record():return json.loads((C/'tangent-capture-build-inspection02.json').read_text())
def test_exact_original_commands():
 v=record();c,l,t=b.recipes(v,OLD,NEW);assert c[c.index('-c')+1]==str(NEW/'source/programs/preprocessing/preprocessingVariationalEquation.cpp');assert c[c.index('-o')+1]==t;assert l[0]==c[0];assert l[l.index('-o')+1]=='groops';assert '-O3'in c and '-DNDEBUG'in c and '-std=gnu++17'in c
@pytest.mark.parametrize('field,value',[('commands_count',632),('selected_commands',[]),('header_dependency_blocks',[])])
def test_changed_inventory_rejected(field,value):
 v=record();v[field]=value
 with pytest.raises(ValueError):b.recipes(v,OLD,NEW)
@pytest.mark.parametrize('idx,old,new',[(0,'-O3','-O3 ;'),(0,'preprocessingVariationalEquation.cpp.o','another.cpp.o'),(1,': &&','echo &&'),(1,'&& :','&& echo'),(1,' -o groops ',' -o other ')])
def test_changed_command_rejected(idx,old,new):
 v=record();assert old in v['selected_commands'][idx];v['selected_commands'][idx]=v['selected_commands'][idx].replace(old,new)
 with pytest.raises(ValueError):b.recipes(v,OLD,NEW)
def test_failed_pin_rejected(tmp_path):
 p=tmp_path/'x';p.write_text('before');pin={'path':str(p),'sha256':b.sha(p)};assert b.check(pin)==p;p.write_text('after')
 with pytest.raises(ValueError):b.check(pin)
