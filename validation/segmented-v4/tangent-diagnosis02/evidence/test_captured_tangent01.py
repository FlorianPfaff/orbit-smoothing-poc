from pathlib import Path
import importlib.util,json,copy
import pytest
C=Path(__file__).parent
def load(name):
 s=importlib.util.spec_from_file_location(name,C/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
w=load('replay_captured_tangent01');d=load('run_captured_tangent01')
def built():return json.loads((C/'tangent-capture-build03-result.json').read_text())
def test_exact_native_compile_recipe():
 r=built();command=w.compile_command(r,Path('/fresh/reader/replay.cpp'),Path('/fresh/binary'));assert command==[r['reader_compile_command'][0],'-O3','-DNDEBUG','-std=gnu++17','-I/fresh/reader/include','/fresh/reader/replay.cpp','-o','/fresh/binary']
@pytest.mark.parametrize('index,value',[(1,'-O2'),(2,'-ffast-math'),(3,'-std=gnu++20'),(4,'-I/other'),(6,'-shared')])
def test_changed_recipe_rejected(index,value):
 r=built();r['reader_compile_command'][index]=value
 with pytest.raises(ValueError):w.compile_command(r,Path('/fresh/reader.cpp'),Path('/fresh/binary'))
def test_changed_input_rejected(tmp_path):
 p=tmp_path/'x';p.write_bytes(b'preserved');pin={'path':str(p),'sha256':w.sha(p)};w.check(pin);p.write_bytes(b'changed')
 with pytest.raises(ValueError):w.check(pin)
def rows():return [{'kind':'input','tolerance':2e-12,'maximum_iterations':120,'restart':20},{'kind':'terminal','status':'failed'}]
def test_failure_trace_retained(tmp_path):
 p=tmp_path/'trace';p.write_text('\n'.join(map(json.dumps,rows())));assert w.trace_records(p)[-1]['status']=='failed'
@pytest.mark.parametrize('key,value',[('tolerance',3e-12),('maximum_iterations',121),('restart',21)])
def test_changed_limits_rejected(tmp_path,key,value):
 p=tmp_path/'trace';r=rows();r[0][key]=value;p.write_text('\n'.join(map(json.dumps,r)))
 with pytest.raises(ValueError):w.trace_records(p)
@pytest.mark.parametrize('value',[[],[{'kind':'terminal'}],[{'kind':'input'}]])
def test_incomplete_trace_rejected(tmp_path,value):
 p=tmp_path/'trace';p.write_text('\n'.join(map(json.dumps,value)))
 with pytest.raises(ValueError):w.trace_records(p)
def test_controller_strict_input_inventory():
 p={'schema':'orbit-poc-captured-tangent-plan-v1','execution':{},'driver':{},'worker':{},'controller':{},'native':{},'source_freeze':{},'inputs':{x:{}for x in w.INPUTS},'output':'/fresh/run','global_lock':'/shared/lock'};d.validate_plan(p);p['inputs']['unrecognized']={}
 with pytest.raises(ValueError):d.validate_plan(p)
