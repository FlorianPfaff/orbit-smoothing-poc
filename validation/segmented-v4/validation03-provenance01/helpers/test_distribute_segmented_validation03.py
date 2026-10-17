from pathlib import Path
import importlib.util,json,gzip,pytest
HERE=Path(__file__).parent
s=importlib.util.spec_from_file_location('distribution',HERE/'distribute_segmented_validation03.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(json.dumps(v).encode() if not isinstance(v,bytes) else v);return m.pin(p)
def fixture(t):
 root=t/'external';records=[];arrays=[]
 def add(prefix,name,raw,encoding='identity'):
  source={'path':'/remote/'+prefix+'/'+name,'sha256':__import__('hashlib').sha256(raw).hexdigest(),'bytes':len(raw)};stored=write(root/prefix/(name+('.gz' if encoding=='gzip' else '')),gzip.compress(raw,mtime=0) if encoding=='gzip' else raw);stored['path']=str(Path(stored['path']).relative_to(root/prefix));return {'source':source,'stored':stored,**({'encoding':encoding} if prefix=='raw-capture' else {})}
 records.append(add('raw-capture','diagnostics.json',json.dumps({'rank':'full','count':23}).encode()))
 records.append(add('raw-capture','graph.json',json.dumps({'epoch_conditionals':[{'R':[[1]],'S':[[2]]}]}).encode(),'gzip'))
 records.append(add('raw-capture','solve.json',json.dumps({'conditionals':[{'matrix':[[3]]}],'maximum_error':1e-14}).encode()))
 for i in range(8):arrays.append(add('raw-linearization-arrays',str(i)+'.npz',b'fixture binary archive'+str(i).encode()))
 write(root/'raw-capture/manifest.json',{'records':records});write(root/'raw-linearization-arrays/manifest.json',{'records':arrays});write(root/'index.html',b'<h1>Segmented v4: terminal validation</h1><p>0 of68; no release.</p>');write(root/'summary.json',{'scientific_status':'passed_scoped_checks','benchmark_attempts_executed':0,'release_ready':False})
 return seal(root)
def seal(root):
 files=[]
 for p in sorted(root.rglob('*')):
  if p.is_file() and p!=root/'manifest.json':files.append({**m.pin(p),'path':str(p.relative_to(root))})
 return write(root/'manifest.json',{'schema':'orbit-poc-segmented-validation-publication-v1','files':files,'scientific_status':'passed_scoped_checks','benchmark_attempts_executed':0,'release_ready':False})
def test_all_arrays_and_conditionals_stay_external_with_exact_inventory(tmp_path):
 p=fixture(tmp_path);root=Path(p['path']).parent;before={str(x):x.read_bytes() for x in root.rglob('*') if x.is_file()};out=tmp_path/'git';v=m.distribute(p,out)
 assert len(v['external_not_distributed'])==10 and not list(out.rglob('*.npz')) and not (out/'raw-capture/graph.json.gz').exists() and not (out/'raw-capture/solve.json').exists()
 assert (out/'raw-capture/diagnostics.json').read_bytes()==(root/'raw-capture/diagnostics.json').read_bytes()
 assert json.loads((out/'external-evidence.json').read_text())['files']==v['external_not_distributed']
 assert (out/'external-full-publication-manifest.json').read_bytes()==Path(p['path']).read_bytes()
 assert all(Path(k).read_bytes()==b for k,b in before.items()) and v['release_ready'] is False
 assert 'validation02 deployment failure' in (out/'index.html').read_text()
@pytest.mark.parametrize('kind',['input_hash','member_hash','extra','missing','unknown_suffix','disguised_binary','duplicate','missing_array','missing_origin','unsafe','promoted'])
def test_source_integrity_and_classification_fail_closed(tmp_path,kind):
 p=fixture(tmp_path);root=Path(p['path']).parent;v=json.loads(Path(p['path']).read_text())
 if kind=='input_hash':p['sha256']='0'*64
 elif kind=='member_hash':(root/'summary.json').write_text('{}')
 elif kind=='extra':write(root/'unlisted.json',{})
 elif kind=='missing':(root/'summary.json').unlink()
 elif kind=='unknown_suffix':write(root/'unknown.dat',b'unknown');p=seal(root)
 elif kind=='disguised_binary':write(root/'binary.json',b'\x00\xff');p=seal(root)
 elif kind=='duplicate':v['files'].append(v['files'][0]);p=write(root/'manifest.json',v)
 elif kind=='missing_array':(root/'raw-linearization-arrays/0.npz').unlink();p=seal(root)
 elif kind=='missing_origin':write(root/'unattributed.json',{'conditionals':[[1]]});p=seal(root)
 elif kind=='unsafe':v['files'][0]['path']='../escape';p=write(root/'manifest.json',v)
 elif kind=='promoted':v['release_ready']=True;p=write(root/'manifest.json',v)
 with pytest.raises((ValueError,OSError,UnicodeError)):m.distribute(p,tmp_path/'git')
 assert not (tmp_path/'git').exists()
def test_omitted_external_payload_mutation_during_copy_is_not_silently_repinned(tmp_path,monkeypatch):
 p=fixture(tmp_path);root=Path(p['path']).parent;old=m.shutil.copyfile;changed=[]
 def copy(a,b):
  v=old(a,b)
  if not changed:(root/'raw-linearization-arrays/0.npz').write_bytes(b'changed');changed.append(True)
  return v
 monkeypatch.setattr(m.shutil,'copyfile',copy)
 with pytest.raises(ValueError,match='Pinned bytes'):m.distribute(p,tmp_path/'git')
 assert (tmp_path/'git').exists() and not (tmp_path/'git/manifest.json').exists()
def test_included_text_mutation_during_copy_rejects(tmp_path,monkeypatch):
 p=fixture(tmp_path);old=m.shutil.copyfile
 def copy(a,b):v=old(a,b);Path(b).write_text('changed');return v
 monkeypatch.setattr(m.shutil,'copyfile',copy)
 with pytest.raises(ValueError,match='Copied text'):m.distribute(p,tmp_path/'git')
def test_existing_distribution_never_overwritten(tmp_path):
 p=fixture(tmp_path);out=tmp_path/'git';out.mkdir();write(out/'retained.txt',b'old')
 with pytest.raises(ValueError,match='fresh'):m.distribute(p,out)
 assert (out/'retained.txt').read_bytes()==b'old'
