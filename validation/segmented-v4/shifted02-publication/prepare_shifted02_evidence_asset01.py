"""Preserve and verify the complete shifted02 compact capture outside Git."""
from pathlib import Path,PurePosixPath
import datetime,hashlib,json,shutil,tarfile
R=Path('/mnt/d/orbit-segmented-v4');C=R/'control';source=R/'shifted-diagnostic-02-results/terminal-transfer-01.tar.gz';capture=R/'shifted-diagnostic-02-results/terminal-capture-01/manifest.json';out=R/'publication-shifted02-assets-01'
def pin(p):
 b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
original=pin(source);assert original['sha256']=='17c16d8ee9c628f33346e61bbbc065eba6830afb10c54a686b5c8ac3eeb85c5c'
cp=pin(capture);assert cp['sha256']=='2fcbbeb40d456fb852eda01aac0098ef748938de16eae8bfe12aaf90d4c14f79';cap=json.loads(capture.read_text())
expected={v['stored']['path']:v['stored'] for v in cap['records']};expected['manifest.json']={'path':'manifest.json','sha256':cp['sha256'],'bytes':cp['bytes']};assert len(expected)==110
assert not out.exists();out.mkdir();asset=out/'segmented-v4-shifted02-full-capture.tar.gz'
with source.open('rb') as src,asset.open('xb') as dst:shutil.copyfileobj(src,dst)
assert pin(asset)['sha256']==original['sha256'] and pin(asset)['bytes']==original['bytes']
seen=set();directories=[]
with tarfile.open(asset,'r:gz') as archive:
 for entry in archive:
  path=PurePosixPath(entry.name);assert not path.is_absolute() and '..' not in path.parts and path.parts[0]=='terminal-capture-01'
  if entry.isdir():directories.append(entry.name);continue
  assert entry.isfile() and len(path.parts)>1
  name=str(PurePosixPath(*path.parts[1:]));assert name in expected and name not in seen;seen.add(name);raw=archive.extractfile(entry).read();v=expected[name]
  assert len(raw)==entry.size==v['bytes'] and hashlib.sha256(raw).hexdigest()==v['sha256']
assert seen==set(expected) and pin(source)==original and pin(capture)==cp
result={'schema':'orbit-poc-shifted-diagnostic-external-capture-asset-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'asset':pin(asset),'source_archive':original,'capture_manifest':cp,'verified_regular_members':len(seen),'directory_headers':len(directories),'exact_captured_numerical_payloads':48,'remote_shifted_row_files':cap['external_not_copied'],'remote_original_row_files':cap['original_unshifted_rows'],'benchmark_attempts_executed':0,'fit_covariance_authorized':False,'release_ready':False,'builder':pin(Path(__file__)),'scope':'Exact original109-file compact capture plus its manifest, including arrays/graphs/conditionals, retained outside Git. The32 shifted and4 original weighted-row files remain at their separately hashed external paths; this archive does not contain them. Diagnostic only;0of68 benchmark fits and no release/covariance authorization.'}
p=out/'manifest.json'
with p.open('x') as f:json.dump(result,f,sort_keys=True,indent=2);f.write('\n')
print(json.dumps({'manifest':pin(p),'asset':pin(asset),'regular_members':len(seen)}))
