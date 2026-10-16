from pathlib import Path
import ast,hashlib,importlib.util
import pytest
C=Path(__file__).parent
DRIVER=C.parent/'validation-04-packet/control/owned_driver09.py'

def context(tmp_path):
 assert hashlib.sha256(DRIVER.read_bytes()).hexdigest()=='72ac591a4c0b1d18b67b2739d694be40e271ec09d7b0f9b3dcad4287cb88fdcd'
 spec=importlib.util.spec_from_file_location('exact_owned_alias',DRIVER);driver=importlib.util.module_from_spec(spec);spec.loader.exec_module(driver)
 a=tmp_path/'readonly-a';b=tmp_path/'readonly-b';a.mkdir();b.mkdir()
 e={'read_only_bindings':[{'target':'/canonical/a','source':str(a)},{'target':'/canonical/b','source':str(b)}]}
 def require(ok,msg):
  if not ok:raise RuntimeError(msg)
 env={'Path':Path,'execution':e,'resolver':driver,'original_host_path':driver.host_path,'require':require,'sha':lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest(),'checked_files':{}}
 t=ast.parse((C/'audit_native_complete_build_remote04.py').read_text());names={'mapped_readonly','guarded_alias_host_path','resolved','checked'}
 nodes=[n for n in t.body if isinstance(n,ast.FunctionDef)and n.name in names];assert len(nodes)==4
 exec(compile(ast.Module(body=nodes,type_ignores=[]),'<actual-resolver>','exec'),env)
 driver.host_path=env['guarded_alias_host_path']
 return env,a,b

def test_absolute_then_relative_alias_across_bindings(tmp_path):
 e,a,b=context(tmp_path);(b/'python3.11').write_bytes(b'exact interpreter');(b/'python').symlink_to('python3.11');(a/'python').symlink_to('/canonical/b/python')
 p=e['resolved']('/canonical/a/python');assert p==b/'python3.11'
 pin={'path':'/canonical/a/python','sha256':hashlib.sha256(b'exact interpreter').hexdigest()};assert e['checked'](pin)==p

@pytest.mark.parametrize('data',[b'changed',b''])
def test_wrong_alias_target_bytes_rejected(tmp_path,data):
 e,a,b=context(tmp_path);(b/'file').write_bytes(data);(a/'file').symlink_to('/canonical/b/file')
 with pytest.raises(RuntimeError,match='Changed artifact'):e['checked']({'path':'/canonical/a/file','sha256':hashlib.sha256(b'original').hexdigest()})

def test_loop_rejected(tmp_path):
 e,a,b=context(tmp_path);(a/'first').symlink_to('/canonical/b/second');(b/'second').symlink_to('/canonical/a/first')
 with pytest.raises(RuntimeError,match='cycle'):e['resolved']('/canonical/a/first')

@pytest.mark.parametrize('relative',[False,True])
def test_unbound_existing_host_target_rejected(tmp_path,relative):
 e,a,b=context(tmp_path);outside=tmp_path/'outside';outside.write_bytes(b'host must not substitute');(a/'link').symlink_to('../outside'if relative else str(outside))
 with pytest.raises(RuntimeError,match='Unbound read-only alias target'):e['resolved']('/canonical/a/link')

def test_missing_bound_target_rejected(tmp_path):
 e,a,b=context(tmp_path);(a/'link').symlink_to('/canonical/b/missing')
 with pytest.raises(RuntimeError,match='missing'):e['resolved']('/canonical/a/link')

def test_longest_declared_binding_wins(tmp_path):
 e,a,b=context(tmp_path);(b/'value').write_bytes(b'bound');e['execution']['read_only_bindings'].append({'target':'/canonical/a/nested','source':str(b)})
 assert e['resolved']('/canonical/a/nested/value')==b/'value'

def test_unmapped_direct_regular_artifact_preserved(tmp_path):
 e,a,b=context(tmp_path);p=tmp_path/'direct';p.write_bytes(b'direct');assert e['resolved'](p)==p

def test_verifier04_remains_exact():
 assert hashlib.sha256((C/'validation07_provenance04.py').read_bytes()).hexdigest()=='23e8a0e54de29250a31aeb65f0bb2001614f0e70cd043d54469d9c0e6d5f6bfa'
