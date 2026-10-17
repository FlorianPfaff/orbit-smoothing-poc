from pathlib import Path
import hashlib,json,os,datetime
C=Path('/mnt/d/orbit-segmented-v4/control');IP=C/'original150-input-aliases01.json'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def read(p):return json.loads(Path(p).read_text())
def checked(x):
 p=Path(x['path']);assert p.is_file() and not p.is_symlink() and sha(p)==x['sha256'];assert 'bytes' not in x or p.stat().st_size==x['bytes'];return p
assert sha(IP)=='1e4871520c61608ebb1624574fca63969d6e62af3e1baba61e1dc7504e18d6b3';a=read(IP)
assert a['schema']=='orbit-poc-original150-existing-input-alias-inventory-v1' and a['alias_count']==len(a['entries'])==9
job=read(checked(a['request']));assert a['request']['sha256']=='77d9788b371c7f94944c4f934aa4398d8d1db4a778b22275a03cfffd94f8fb6f'
d=Path(a['attempt_directory']);assert d==Path(a['request']['path']).parent and d.name==job['id']=='retained-pulse-weak-300001--qr_lm_staged_jacobian'
for x in [d,*d.parents]:assert not x.is_symlink()
p=a['native_preparation'];inputs={x['path']:x for x in job['estimation_inputs']};assert p['canonical_path'] in inputs and inputs[p['canonical_path']]['sha256']==p['expected_sha256']==p['backing']['sha256']=='7c03d1a2b1ecf603e802ca26130b116d83a21fa17a3dcc386b2ca90db1fcfc92'
assert Path(p['backing']['path'])==Path('/mnt/d/orbit-numerics-v3.1-mirror/remote-root')/p['canonical_path'].lstrip('/')
prep=read(checked(p['backing']));assert prep['date']==job['case']['epoch'][:10]=='2024-05-10'
expected={};native={x['path']:x for x in prep['native_artifacts']};base='point-001-initial/native/data/'
for kind in ('attitude','clock','orbit','signalBias'):
 prefix='/data/'+prep['date']+'/'+kind+'/'
 members=[Path(path) for path in native if prefix in path];assert len(members)==32
 parents={str(x.parent) for x in members};assert len(parents)==1
 expected[base+prep['date']+'/'+kind]=(parents.pop(),32)
for key in ('receiver','receiver_orbit','receiver_attitude','attitude'):
 target=prep['native_paths'][key];assert target in native
 expected[base+prep['date']+'/gracefo/'+Path(target).name]=(target,1)
accuracy=[x for x in job['estimation_inputs'] if x['path'].endswith('/data/synthetic_accuracy.xml')];assert len(accuracy)==1
expected[base+'synthetic_accuracy.xml']=(accuracy[0]['path'],1)
assert {x['relative']:(x['target'],x['original_artifact_count']) for x in a['entries']}==expected
actual={str(x.relative_to(d)):os.readlink(x) for x in d.rglob('*') if x.is_symlink()};assert actual=={k:v[0] for k,v in expected.items()}
previous=read(checked(a['prior_failure']));assert a['prior_failure']['sha256']=='6f364c39a5e38d6bcb6a8747af169d3bc3bed2e77266f4b4557b7c9ff7a7977e'
previous_rows={x['relative']:x for x in previous['observed_extra_input_aliases']}
for x in a['entries']:
 path=d/x['relative'];assert Path(x['relative']).is_absolute() is False and '..' not in Path(x['relative']).parts
 for parent in path.parents:
  assert not parent.is_symlink()
  if parent==d:break
 st=path.lstat();old=previous_rows[x['relative']];assert os.readlink(path)==x['target']==old['readlink'];assert st.st_size==x['lstat_size']==old['symlink_bytes'];assert st.st_mtime_ns==x['lstat_mtime_ns']==old['mtime_ns'];assert st.st_ctime_ns==old['ctime_ns']
for name in ('controller-boot-interruption.json','result.json','result-record.json'):assert not (d/name).exists() and not (d/name).is_symlink()
assert sha(IP)=='1e4871520c61608ebb1624574fca63969d6e62af3e1baba61e1dc7504e18d6b3'
v={'schema':'orbit-poc-original150-input-alias-independent-review-v1','passed':True,'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer':'/root/v4_independent_review','alias_inventory':pin(IP),'helper':pin(Path(__file__)),'original_request':a['request'],'native_preparation_backing':p['backing'],'verified_aliases':9,'transmitter_files_referenced':128,'receiver_files_referenced':4,'accuracy_xml_referenced':1,'matches_prior_failed_inspection_identity':True,'append_targets_absent_and_symlink_free':True,'scope':'Exact nine pre-existing native-input readlinks independently derived from pinned original request/preparation metadata. Links were not followed and payload byte checks are not claimed; ordinary partial outputs and new receipt/result/index retain strict symlink rejection. No campaign write, native process or continuation approval.'}
out=C/'original150-input-aliases-independent-review01.json'
with out.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(out)))
