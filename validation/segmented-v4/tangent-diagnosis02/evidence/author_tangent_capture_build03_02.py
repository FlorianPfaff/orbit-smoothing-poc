from pathlib import Path
import hashlib
c=Path('/mnt/d/orbit-segmented-v4/control');base=(c/'stagedVariationalBody-installed-a669.h').read_bytes();assert hashlib.sha256(base).hexdigest()=='1cace042d5deffac657cc68b9be08de4dc607fba2f8028ac1440e4446fb5d500';block=(c/'tangent_capture_block01.txt').read_bytes();needle=b'      try {result=OrbitPoc::solveSixStateTangent'
assert base.count(needle)==1
new=base.replace(needle,block+needle);assert new.replace(block,b'')==base
(c/'stagedVariationalBody-tangent-capture02.h').write_bytes(new)
s=(c/'build_tangent_capture02.py').read_text();s=s.replace("'capture_header','reader_source'","'capture_header','capture_block','reader_source'")
pos=s.index('def save(')
s=s[:pos]+'''def validate_capture_delta(original,candidate,block):
 if not block or candidate.count(block)!=1 or candidate.replace(block,b'')!=original:raise ValueError('Capture must preserve exact installed header bytes')
def validate_reader_headers(manifest,original_root,reader_root):
 if manifest.get('schema')!='tangent-telemetry-only-v1' or set(manifest.get('files',{}))!={'sixStateTangent.h','syntheticForceDerivatives.h','eventQuadrature.h'}:raise ValueError('Unexpected reader header manifest')
 for name,value in manifest['files'].items():
  if set(value)!={'original_sha256','telemetry_sha256'} or sha(original_root/name)!=value['original_sha256'] or sha(reader_root/name)!=value['telemetry_sha256']:raise ValueError('Reader header does not match installed native source')
''' +s[pos:]
s=s.replace("assert sha(target_header)=='39ec6589cc2b7d1b36d7712760169a030682f957ba286743248517f4c71ebb0d'", "assert sha(target_header)==before[installed]\n validate_capture_delta(target_header.read_bytes(),capture.read_bytes(),check(p['inputs']['capture_block']).read_bytes())\n validate_reader_headers(json.loads(check(p['inputs']['reader_manifest']).read_text()),original_source/'source/misc/orbitPoc',check(p['inputs']['reader_source']).parent/'include')")
(c/'build_tangent_capture03.py').write_text(s)
s=(c/'run_tangent_capture_build02.py').read_text().replace("'capture_header','reader_source'","'capture_header','capture_block','reader_source'");(c/'run_tangent_capture_build03.py').write_text(s)
s=(c/'stage_tangent_capture_build02.py').read_text().replace("D=B/'tangent-capture-02'","D=B/'tangent-capture-03'").replace('build_tangent_capture02.py','build_tangent_capture03.py').replace('run_tangent_capture_build02.py','run_tangent_capture_build03.py').replace("('capture_header',str(C/'stagedVariationalBody-tangent-capture01.h'))","('capture_header',str(C/'stagedVariationalBody-tangent-capture02.h')),('capture_block',str(C/'tangent_capture_block01.txt'))")
(c/'stage_tangent_capture_build03.py').write_text(s)
s=(c/'test_tangent_capture_build02.py').read_text().replace('build_tangent_capture02.py','build_tangent_capture03.py');s+='''
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
''';(c/'test_tangent_capture_build03.py').write_text(s)
s=(c/'test_tangent_capture_writer02.py').read_text().replace("Path('/mnt/d/orbit-segmented-v4/validation-04-packet/source/groops/extension/stagedVariationalBody.h')","(C/'stagedVariationalBody-installed-a669.h')").replace('stagedVariationalBody-tangent-capture01.h','stagedVariationalBody-tangent-capture02.h');(c/'test_tangent_capture_writer03.py').write_text(s)
s=(c/'stage_nominal_tangent_capture02.py').read_text().replace("B/'tangent-capture-02/run/build-result/result.json'","B/'tangent-capture-03/run/build-result/result.json'");(c/'stage_nominal_tangent_capture03.py').write_text(s)
print(hashlib.sha256(new).hexdigest())
