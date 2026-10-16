from pathlib import Path
import importlib.util,json,copy,shutil,subprocess
import pytest
C=Path(__file__).parent
def load(name):
 s=importlib.util.spec_from_file_location(name,C/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
w=load('replay_captured_tangent02');d=load('run_captured_tangent02')
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

def experiment():return json.loads((C/'tangent72-diagnostic07/generation.json').read_text())
def test_explicit_actual_experiment_manifest():w.validate_experiment(experiment(),C/'tangent72-diagnostic07/replay.cpp')
@pytest.mark.parametrize('field,value',[('schema','tangent-telemetry-only-v1'),('production_header_sha256','0'*64),('files',{})])
def test_bad_experiment_manifest_rejected(field,value):
 m=experiment();m[field]=value
 with pytest.raises(ValueError):w.validate_experiment(m,C/'tangent72-diagnostic07/replay.cpp')
def test_changed_experiment_byte_rejected(tmp_path):
 source=tmp_path/'source';shutil.copytree(C/'tangent72-diagnostic07',source);(source/'replay.cpp').write_bytes(b'changed')
 with pytest.raises(ValueError):w.validate_experiment(experiment(),source/'replay.cpp')
def fixture_args(tmp_path):
 out=tmp_path/'out';out.mkdir();binary=tmp_path/'binary';binary.write_bytes(b'binary');return C/'tangent72-diagnostic07/replay.cpp',binary,['c++'],experiment(),C/'tangent72-diagnostic01/test_replay.py',out,{}
def fake_test_runner(calls,tests=3,failures=0,skipped=0):
 def run(argv,**kwargs):
  calls.append(argv)
  if '-m'in argv:
   p=Path(next(x.split('=',1)[1]for x in argv if x.startswith('--junitxml=')));p.write_text(f'<testsuites><testsuite tests="{tests}" errors="0" failures="{failures}" skipped="{skipped}"/></testsuites>')
 return run
def test_fixtures_use_exact_compiler_flags_and_checks(tmp_path,monkeypatch):
 calls=[];monkeypatch.setattr(w.subprocess,'run',fake_test_runner(calls));result=w.fixtures(*fixture_args(tmp_path));assert result['tests']==3 and result['nested_original_reader_checks']==8;assert calls[0][1:4]==['-O3','-DNDEBUG','-std=gnu++17'];assert calls[1][1:3]==['-m','pytest']
@pytest.mark.parametrize('kw',[{'tests':2},{'failures':1},{'skipped':1}])
def test_partial_or_failed_fixture_not_accepted(tmp_path,monkeypatch,kw):
 monkeypatch.setattr(w.subprocess,'run',fake_test_runner([],**kw))
 with pytest.raises(ValueError):w.fixtures(*fixture_args(tmp_path))
def test_fixture_compile_failure_stops_before_replay(tmp_path,monkeypatch):
 def run(argv,**kwargs):raise subprocess.CalledProcessError(1,argv)
 monkeypatch.setattr(w.subprocess,'run',run)
 with pytest.raises(subprocess.CalledProcessError):w.fixtures(*fixture_args(tmp_path))
