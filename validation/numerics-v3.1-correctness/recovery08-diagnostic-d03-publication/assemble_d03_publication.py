"""Stage bounded path-tokenized D03 evidence; final reviewed prose is separate."""
from pathlib import Path
import json,gzip,hashlib,importlib.util
BASE=Path('@LOCAL_DATA_ROOT@/orbit-numerics-v3.1/correctness');CONTROL=BASE/'control';OUT=BASE/'staging-d03-publication'
ADAPTER=CONTROL/'publish_bounded_retry.py';assert hashlib.sha256(ADAPTER.read_bytes()).hexdigest()=='0a2a33dde1906981dae09fce1dae1683e1c60783adad8c3d38d9af3545ccebf5'
s=importlib.util.spec_from_file_location('bounded_scrub',ADAPTER);M=importlib.util.module_from_spec(s);s.loader.exec_module(M)
SOURCES=[('preserved-row-trace-d03-01','b9b704563f7962d7f3135b2384a846d8a26218be26ace64c173622df9cb18e1c',''),('preserved-row-trace-d03-analysis02-failed','37a86bafa9fd0303fb01bf883e1b0a21e27f053d7829886545a3de7fe75973d0','analysis-attempt02-failed'),('preserved-row-trace-d03-analysis03','80cd074a1b70af7c1070350a302ef4090e90d1d37a2a5a2150ae0a9335fc3943','analysis-attempt03')]
def stage():
 assert not OUT.exists();files={};source_manifests={};payload={}
 def add(name,raw):
  assert name not in payload and len(raw)<=16*1024*1024
  text=M.scrub(raw.decode());assert '@REMOTE_DATA_ROOT@/' not in text and '@REMOTE_HOME@/' not in text
  data=text.encode();compressed=Path(name).suffix in ('.json','.xml','.log');target=name+'.gz' if compressed else name;stored=gzip.compress(data,mtime=0) if compressed else data
  assert target not in files;payload[target]=stored;files[target]={'sha256':M.digest(stored),'bytes':len(stored),'original_sha256':M.digest(raw),'original_bytes':len(raw),'published_expanded_sha256':M.digest(data),'published_expanded_bytes':len(data),'encoding':'gzip' if compressed else 'identity','transformation':'private path/username tokenization; gzip for receipts/logs'}
 for directory,pin,prefix in SOURCES:
  root=BASE/directory;raw=(root/'manifest.json').read_bytes();assert M.digest(raw)==pin;manifest=json.loads(raw);source_manifests[directory]=pin
  for name,record in manifest['files'].items():
   path=Path(name);assert not path.is_absolute() and '..' not in path.parts;raw=(root/path).read_bytes();assert M.digest(raw)==record['sha256'] and len(raw)==record['bytes'];add(str(Path(prefix)/path),raw)
  add('preservation/'+directory+'-manifest.json',(root/'manifest.json').read_bytes())
 for name in ('d03-analysis-invocation-01.json','d03-analysis-invocation-02.json','d03-analysis-invocation-03.json','launch_d03_independent_analysis01.py','launch_d03_independent_analysis02.py','launch_d03_independent_analysis03.py','row-trace-d03-analyzer-independent-review-02.json'):
  add('analysis-reviews/'+name,(CONTROL/name).read_bytes())
 for p in sorted((CONTROL/'row-trace-d03-analysis-02').rglob('*')):
  if p.is_file() and '__pycache__' not in p.parts:add('analysis-version02-controls/'+str(p.relative_to(CONTROL/'row-trace-d03-analysis-02')),p.read_bytes())
 assert sum(map(len,payload.values()))<=64*1024*1024;OUT.mkdir()
 for name,raw in payload.items():p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 record={'schema':'orbit-poc-d03-publication-staging-v1','files':files,'source_manifests':source_manifests,'bytes':sum(map(len,payload.values())),'final_independent_review_pending':True,'scientific_gate_substitution':False};(OUT/'staging-manifest.json').write_bytes(M.encoded(record));return record
if __name__=='__main__':
 r=stage();print(json.dumps({'files':len(r['files']),'bytes':r['bytes'],'staging_manifest_sha256':M.digest((OUT/'staging-manifest.json').read_bytes())}))
