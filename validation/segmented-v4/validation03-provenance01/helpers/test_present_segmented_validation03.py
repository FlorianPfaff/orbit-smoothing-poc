from pathlib import Path
import importlib.util,json,pytest
HERE=Path(__file__).parent
def module(n):
 s=importlib.util.spec_from_file_location(n,HERE/(n+'.py'));v=importlib.util.module_from_spec(s);s.loader.exec_module(v);return v
m=module('present_segmented_validation03');old=module('test_present_segmented_validation02_v2')
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return m.artifact(p)
def read(pin):return json.loads(Path(pin['path']).read_bytes())
def fixture(tmp,failed=False):
 p=old.fixture(tmp,failed);p['schema']='orbit-poc-segmented-validation-presentation-plan-v2';capture=read(p['capture']);records=[];base=tmp/'arrays'
 audit=read(p['independent_audit'])
 for method in ('log_drag_ou','pulses'):
  stage=next(x for x in audit['stages'] if x['name']=='linearization-'+method)
  for tail in ('dense-reference.npz','gtsam-original-rows.npz','segments-3600/covariance.npz','segments-14400/covariance.npz'):
   target=base/method/tail;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(b'fixture arrays '+(method+'/'+tail).encode());sp=m.artifact(target);source={**sp,'path':str(Path(capture['pipeline']['path']).parent/('linearization-'+method)/'result/comparison'/tail)};records.append({'source':source,'stored':{**sp,'path':method+'/'+tail}});stage['raw_artifacts'].append(source)
 arrays={'schema':'orbit-poc-segmented-linearization-array-capture-v1','main_capture':p['capture'],'pipeline':capture['pipeline'],'records':records};p['array_capture']=save(base/'manifest.json',arrays);audit['array_capture']=p['array_capture'];p['independent_audit']=save(Path(p['independent_audit']['path']),audit);return p

def repin_array(p,a):
 p['array_capture']=save(Path(p['array_capture']['path']),a);audit=read(p['independent_audit']);audit['array_capture']=p['array_capture'];p['independent_audit']=save(Path(p['independent_audit']['path']),audit)

@pytest.mark.parametrize('failed',[False,True])
def test_preserve_exact_capture_and_eight_arrays_without_promotion(tmp_path,failed):
 p=fixture(tmp_path,failed);out=tmp_path/'out';before=Path(p['capture']['path']).read_bytes();v=m.publish(p,out);s=json.loads((out/'summary.json').read_text())
 assert (out/'raw-capture/manifest.json').read_bytes()==before and len(s['attempts'])==68 and s['benchmark_attempts_executed']==0 and not s['release_ready']
 assert s['scientific_status']==('failed' if failed else 'passed_scoped_checks')
 for r in read(p['array_capture'])['records']:assert m.artifact(out/'raw-linearization-arrays'/r['stored']['path'])['sha256']==r['stored']['sha256']
 assert all(m.artifact(out/x['path'])['sha256']==x['sha256'] for x in v['files'])

@pytest.mark.parametrize('kind',['main_hash','main_bytes','pipeline','audit_pin','schema','missing','duplicate','unexpected','source_path','source_hash','stored_hash','encoding','extra_file','unsafe_path','file_changed'])
def test_array_attribution_and_membership_reject(tmp_path,kind):
 p=fixture(tmp_path);a=read(p['array_capture']);base=Path(p['array_capture']['path']).parent
 if kind=='main_hash':a['main_capture']['sha256']='0'*64
 elif kind=='main_bytes':a['main_capture']['bytes']+=1
 elif kind=='pipeline':a['pipeline']['sha256']='0'*64
 elif kind=='schema':a['schema']='other'
 elif kind=='missing':a['records'].pop()
 elif kind=='duplicate':a['records'][1]=a['records'][0]
 elif kind=='unexpected':a['records'][0]['stored']['path']='wrong/x.npz'
 elif kind=='source_path':a['records'][0]['source']['path']='/other/array.npz'
 elif kind=='source_hash':a['records'][0]['source']['sha256']='0'*64
 elif kind=='stored_hash':a['records'][0]['stored']['sha256']='0'*64
 elif kind=='encoding':a['records'][0]['encoding']='gzip'
 elif kind=='extra_file':(base/'extra.npz').write_bytes(b'extra')
 elif kind=='unsafe_path':a['records'][0]['stored']['path']='../escape.npz'
 elif kind=='file_changed':(base/a['records'][0]['stored']['path']).write_bytes(b'changed')
 if kind=='audit_pin':
  audit=read(p['independent_audit']);audit['array_capture']['sha256']='0'*64;p['independent_audit']=save(Path(p['independent_audit']['path']),audit)
 else:repin_array(p,a)
 with pytest.raises((ValueError,KeyError,OSError)):m.publish(p,tmp_path/'out')
 assert not (tmp_path/'out').exists()

def test_changed_array_during_copy_preserves_failed_partial_output(tmp_path,monkeypatch):
 p=fixture(tmp_path);copy=m.shutil.copytree;root=Path(p['array_capture']['path']).parent;name=read(p['array_capture'])['records'][0]['stored']['path']
 def changed(src,dst,*args,**kwargs):
  v=copy(src,dst,*args,**kwargs)
  if Path(src)==root:(Path(dst)/name).write_bytes(b'post-inspect mutation')
  return v
 monkeypatch.setattr(m.shutil,'copytree',changed)
 with pytest.raises(ValueError,match='Captured stored bytes'):m.publish(p,tmp_path/'out')
 assert (tmp_path/'out').exists() and not (tmp_path/'out/manifest.json').exists()
