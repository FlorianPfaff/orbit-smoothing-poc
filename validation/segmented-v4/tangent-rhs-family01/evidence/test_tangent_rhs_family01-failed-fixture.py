from pathlib import Path
import copy,importlib.util,json,struct,subprocess
import pytest
C=Path(__file__).parent
spec=importlib.util.spec_from_file_location('rhs',C/'replay_tangent_rhs_family01.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
def capture(path):
 path.write_bytes(b'OPCTANGENT001\n\0\0'+struct.pack('<5Q2d',1,2,1,0,12,1.,1.)+struct.pack('<72d',*([0.]*72))+struct.pack('<Q',0)+struct.pack('<12d',*([1.]*12)))
 return path
@pytest.fixture
def family(tmp_path,monkeypatch):
 raw=capture(tmp_path/'anchor');h=m.sha(raw);monkeypatch.setattr(m,'ANCHORS',{k:h for k in m.ANCHORS});anchors=[];cases=[];order=[]
 for a in m.ANCHORS:
  anchors.append(dict(id=a,path=str(raw),sha256=h,epochs=2,dt=1.,duration=1.))
  variants=[(None,0,0.)]+[(d,s,z)for d in('smooth','alternating')for z in(1e-12,1e-9)for s in(-1,1)]
  for j,(d,s,z)in enumerate(variants):cases.append(dict(id=a+str(j),path=str(raw),sha256=h,bytes=raw.stat().st_size,anchor=a,direction=d,sign=s,relative_scale=z,changed_entries=0 if d is None else 1,actual_relative_balanced_norm=z))
 for i,c in enumerate(cases):
  for mode in(('baseline','wide')if i%2==0 else('wide','baseline')):order.append(dict(attempt_id=f"{len(order)+1:02d}-{c['id']}-{mode}",case_id=c['id'],profile=mode))
 return dict(schema_version=1,kind='bounded-captured-tangent-rhs-sensitivity',case_count=27,attempt_count=54,acceptance=dict(relative_residual=2e-12,maximum_iterations=120,restart=20),anchors=anchors,cases=cases,execution_order=order)
def test_family_valid(family):assert len(m.validate_family(family)[1])==54
@pytest.mark.parametrize('change',[lambda f:f['cases'].pop(),lambda f:f['execution_order'].pop(),lambda f:f['cases'][1].update(direction='unknown'),lambda f:f['cases'][1].update(sign=0),lambda f:f['cases'][1].update(relative_scale=1e-6),lambda f:f['cases'][1].update(direction=None,sign=0,relative_scale=0),lambda f:f['execution_order'].reverse(),lambda f:f['cases'][1].update(changed_entries=0),lambda f:f['cases'][1].update(actual_relative_balanced_norm=1.),lambda f:f['acceptance'].update(relative_residual=1e-10),lambda f:f['acceptance'].update(maximum_iterations=121),lambda f:f['acceptance'].update(restart=21),lambda f:f['anchors'][0].update(sha256='0'*64),lambda f:f['cases'][1].update(bytes=0)])
def test_family_rejects(family,change):
 change(family)
 with pytest.raises((ValueError,KeyError)):m.validate_family(family)
def trace(path,last=None,first=None):
 a=dict(kind='input',profile='wide',epochs=2,dt=1.,duration=1.,tolerance=2e-12,maximum_iterations=120,restart=20,extended_digits=64)
 b=dict(kind='terminal',status='passed',kernel_status='passed',iterations=4,relative_residual=1e-13,physical_double_quad_relative_residual=1e-13)
 if first:a.update(first)
 if last:b.update(last)
 path.write_text(json.dumps(a)+'\n'+json.dumps(b)+'\n');return path
META=dict(epochs=2,dt=1.,duration=1.)
def test_trace_success(tmp_path):assert m.parse_trace(trace(tmp_path/'t'),0,'wide',META)[-1]['status']=='passed'
@pytest.mark.parametrize('last,first,rc',[({'physical_double_quad_relative_residual':None},{},0),({'physical_double_quad_relative_residual':3e-12},{},0),({'kernel_status':'failed'},{},0),({'status':'failed'},{},0),({},dict(profile='baseline'),0),({},dict(epochs=3),0),({},dict(tolerance=3e-12),0),({},dict(maximum_iterations=121),0),({},dict(restart=21),0),({},dict(extended_digits=53),0),({}, {},2),({'iterations':121},{},0),({'relative_residual':None},{},0),({'status':'failed'},{},1)])
def test_trace_protocol_rejects(tmp_path,last,first,rc):
 with pytest.raises(ValueError):m.parse_trace(trace(tmp_path/'t',last,first),rc,'wide',META)
def test_kernel_failure_null_allowed(tmp_path):
 p=trace(tmp_path/'t',dict(status='failed',kernel_status='failed',relative_residual=None,physical_double_quad_relative_residual=None));assert m.parse_trace(p,1,'wide',META)[-1]['kernel_status']=='failed'
def test_oracle_failure_preserved(tmp_path):
 p=trace(tmp_path/'t',dict(status='failed',physical_double_quad_relative_residual=3e-12));assert m.parse_trace(p,1,'wide',META)[-1]['status']=='failed'
def test_decimal_oracle_not_rounded_to_pass(tmp_path):
 p=trace(tmp_path/'t');p.write_text(p.read_text().replace('"physical_double_quad_relative_residual": 1e-13','"physical_double_quad_relative_residual": 2.00000000000000000000001e-12'))
 with pytest.raises(ValueError):m.parse_trace(p,0,'wide',META)
def test_duplicate_terminal_rejected(tmp_path):
 p=trace(tmp_path/'t');p.write_text(p.read_text()+p.read_text().splitlines()[-1]+'\n')
 with pytest.raises(ValueError):m.parse_trace(p,0,'wide',META)
def test_timeout_retains_raw(tmp_path,monkeypatch):
 p=capture(tmp_path/'c');binary=tmp_path/'binary';binary.write_text('dummy');root=tmp_path/'out';root.mkdir()
 def expired(*args,**kw):kw['stdout'].write(b'partial');kw['stderr'].write(b'timeout');raise subprocess.TimeoutExpired(args[0],1)
 monkeypatch.setattr(m.subprocess,'run',expired)
 r=m.execute_attempt(m.pin(binary),dict(id='c',path=str(p),sha256=m.sha(p)),dict(attempt_id='a',profile='wide'),root,1)
 assert r['status']=='timeout'and m.check(r['trace']).read_bytes()==b'partial'and m.check(r['stderr']).read_bytes()==b'timeout'
def test_source_bundle_real_shape():
 root=C/'tangent-wide-candidate01';b=dict(schema='orbit-poc-tangent-rhs-source-bundle-v1',source_manifest=m.pin(root/'generation.json'),files={n:m.pin(root/n)for n in m.SOURCE_FILES});m.validate_source_bundle(b)
 b['files'].pop('test_wide.cpp')
 with pytest.raises(ValueError):m.validate_source_bundle(b)
@pytest.mark.parametrize('phase',['prepare','run'])
def test_phase_plan(phase):
 p=dict(schema=m.SCHEMA,phase=phase,execution={},driver={},worker={},controller={},native={},source_freeze={},inputs={k:{}for k in m.INPUTS[phase]},output='/fresh/result',global_lock='/shared/lock');m.validate_plan(p)
 p['inputs']['unknown']={}
 with pytest.raises(ValueError):m.validate_plan(p)
def test_existing_output_no_overwrite(tmp_path):
 p=tmp_path/'log';p.write_text('preserved')
 with pytest.raises(FileExistsError):m.logged(['/usr/bin/true'],tmp_path,'log')
