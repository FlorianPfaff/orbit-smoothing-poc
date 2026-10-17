from pathlib import Path
import importlib.util,json,copy
import pytest
C=Path(__file__).parent;s=importlib.util.spec_from_file_location('b',C/'build_tangent_capture03.py');b=importlib.util.module_from_spec(s);s.loader.exec_module(b)
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

def test_real_manifest_key_shape():
 raw=json.loads((C/'tangent-capture-build01-failure.json').read_text());assert raw['source_prefix_only_equal']is True;assert raw['raw_membership_equal']is False
 for name in raw['manifest_key_sample']:assert name.startswith('source/')
 value={'source/base/a.h':'a'*64,'source/programs/b.cpp':'b'*64};assert b.normalized_source_files(value)=={'base/a.h':'a'*64,'programs/b.cpp':'b'*64}
@pytest.mark.parametrize('value',[{}, {'base/a.h':'a'*64},{'source/':'a'*64},{'source/../a':'a'*64},{'source/base//a':'a'*64},{'source/base/a':'x'*64}])
def test_bad_source_receipt_rejected(value):
 with pytest.raises(ValueError):b.normalized_source_files(value)

def test_capture_preserves_installed_export_hook():
 original=(C/'stagedVariationalBody-installed-a669.h').read_bytes();candidate=(C/'stagedVariationalBody-tangent-capture02.h').read_bytes();block=(C/'tangent_capture_block01.txt').read_bytes();b.validate_capture_delta(original,candidate,block);assert b'ORBIT_POC_SEGMENTED_TANGENT_EXPORT_V4'in candidate
@pytest.mark.parametrize('kind',['missing_hook','missing_block','duplicate_block'])
def test_other_installed_header_mutation_rejected(kind):
 original=(C/'stagedVariationalBody-installed-a669.h').read_bytes();candidate=(C/'stagedVariationalBody-tangent-capture02.h').read_bytes();block=(C/'tangent_capture_block01.txt').read_bytes()
 if kind=='missing_hook':candidate=candidate.replace(b'ORBIT_POC_SEGMENTED_TANGENT_EXPORT_V4',b'changed')
 if kind=='missing_block':candidate=candidate.replace(block,b'')
 if kind=='duplicate_block':candidate+=block
 with pytest.raises(ValueError):b.validate_capture_delta(original,candidate,block)
def test_reader_installed_header_binding(tmp_path):
 original=tmp_path/'original';reader=tmp_path/'reader';original.mkdir();reader.mkdir();names=('sixStateTangent.h','syntheticForceDerivatives.h','eventQuadrature.h');m={'schema':'tangent-telemetry-only-v1','files':{}}
 for name in names:
  (original/name).write_bytes(b'old');(reader/name).write_bytes(b'new');m['files'][name]={'original_sha256':b.sha(original/name),'telemetry_sha256':b.sha(reader/name)}
 b.validate_reader_headers(m,original,reader);(original/names[0]).write_bytes(b'changed')
 with pytest.raises(ValueError):b.validate_reader_headers(m,original,reader)
