from pathlib import Path
import importlib.util,json,pytest
s=importlib.util.spec_from_file_location('arrays',Path(__file__).with_name('capture_segmented_linearization_arrays01.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v));return m.pin(p)
@pytest.fixture
def fixture(tmp_path):
 root=tmp_path/'run/validation/attempt-0001';steps=[]
 for method in m.METHODS:
  d=root/('linearization-'+method);steps.append({'name':'linearization-'+method,'directory':str(d),'status':'passed'})
  for name in m.NAMES:
   p=d/'result/comparison'/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(('exact fixture '+str(p)).encode())
 pipeline=write(root/'pipeline.json',{'steps':steps});controller=write(tmp_path/'controller.json',{'status':'passed'})
 manifest=write(tmp_path/'capture/manifest.json',{'schema':'orbit-poc-v4-terminal-validation-capture-v1','final_owned_cleanup_verified':True,'pipeline':pipeline,'controller':controller})
 return tmp_path,manifest,steps
def test_exact_eight_arrays_and_originals_unchanged(fixture):
 tmp,manifest,steps=fixture;v=m.capture(manifest,tmp/'arrays');out=json.loads(Path(v['path']).read_text());assert len(out['records'])==8
 for r in out['records']:
  assert m.pin(r['source']['path'])==r['source'];actual=m.pin(tmp/'arrays'/r['stored']['path']);assert actual['sha256']==r['source']['sha256'] and actual['bytes']==r['source']['bytes']
@pytest.mark.parametrize('change',['missing','extra','symlink','changed_pipeline','reused_output','changed_main','no_cleanup','failed_step'])
def test_failclosed(fixture,change):
 tmp,manifest,steps=fixture;source=Path(steps[0]['directory'])/'result/comparison'/m.NAMES[0]
 if change=='missing':source.unlink()
 if change=='extra':source.with_name('unexpected.npz').write_bytes(b'new')
 if change=='symlink':source.unlink();source.symlink_to(tmp/'unknown')
 if change=='changed_pipeline':Path(json.loads(Path(manifest['path']).read_text())['pipeline']['path']).write_text('{}')
 if change=='reused_output':(tmp/'arrays').mkdir()
 if change=='changed_main':Path(manifest['path']).write_text('{}')
 if change=='no_cleanup':v=json.loads(Path(manifest['path']).read_text());v['final_owned_cleanup_verified']=False;manifest=write(Path(manifest['path']),v)
 if change=='failed_step':
  v=json.loads(Path(manifest['path']).read_text());steps[0]['status']='failed';v['pipeline']=write(Path(v['pipeline']['path']),{'steps':steps});manifest=write(Path(manifest['path']),v)
 with pytest.raises(ValueError):m.capture(manifest,tmp/'arrays')
