from pathlib import Path
import hashlib,json,os,time
B=Path('/home/emper/orbit-nuisance-performance/wholefit01')
request=json.loads((B/'original/request.json').read_text())
aux=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/v3/groops-data')
rows=[]
def copy_checked(source,target,expected):
 before=source.stat(); h=hashlib.sha256();target.parent.mkdir(parents=True,exist_ok=True)
 with source.open('rb') as inp,target.open('xb') as out:
  for block in iter(lambda:inp.read(1024*1024),b''):h.update(block);out.write(block)
 after=source.stat()
 if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or h.hexdigest()!=expected:raise ValueError('local input differs: '+str(source))
 target.chmod(0o444)
 return dict(source=str(source),target=str(target),bytes=before.st_size,sha256=h.hexdigest(),device=before.st_dev,inode=before.st_ino,mtime_ns=before.st_mtime_ns)
for a in request['estimation_inputs']:
 if '/inputs/auxiliary/' not in a['path']:continue
 source=aux/a['path'].split('/inputs/auxiliary/',1)[1]
 target=B/'inputs/mirror'/a['path'].lstrip('/')
 rows.append(dict(original_path=a['path'],**copy_checked(source,target,a['sha256'])))
m=json.loads(Path('/mnt/d/orbit-segmented-v4/control/preparation07-terminal01/run/manifest.json').read_text())
deps=m['runtimes']['segmented']['libraries']['executables']['native']['dependencies']
runtime=[]
for a in deps:
 source=Path(a['path']);actual=hashlib.sha256(source.read_bytes()).hexdigest()
 target=B/'inputs/exporter-runtime'/source.name
 row=copy_checked(source,target,actual)
 runtime.append(dict(historical_sha256=a['sha256'],matches_historical=actual==a['sha256'],**row))
v=dict(schema='orbit-poc-wholefit-local-input-copies-v1',auxiliary=rows,auxiliary_bytes=sum(r['bytes'] for r in rows),
       exporter_dependencies=runtime,system_runtime_differences=[r['source'] for r in runtime if not r['matches_historical']],
       scope='Byte-identical auxiliary copies; exact historical exporter with frozen current local dependencies for both arms. Historical system runtime differences disclosed.')
with (B/'local-input-copies01.json').open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(dict(auxiliary_files=len(rows),auxiliary_bytes=v['auxiliary_bytes'],dependencies=len(runtime),historical_runtime_mismatches=len(v['system_runtime_differences']))),flush=True)
