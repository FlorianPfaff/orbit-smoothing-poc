#!/usr/bin/env python3
"""Read-only bounded remote capture; all writes remain in this isolated local tree."""
from pathlib import Path
import hashlib,json,subprocess,tarfile,time,sys
B=Path('/home/emper/orbit-nuisance-performance/wholefit01')
plan=json.loads((B/'capture-inputs-plan01.json').read_text())
code="""from pathlib import Path
import gzip,hashlib,io,json,os,stat,sys,tarfile,time
PLAN=__PLAN__
total=0; receipts=[]
with gzip.GzipFile(fileobj=sys.stdout.buffer,mode='wb',compresslevel=1) as compressed, tarfile.open(fileobj=compressed,mode='w|') as archive:
 for i,e in enumerate(PLAN['entries']):
  p=Path(e['path']); before=p.stat()
  if not stat.S_ISREG(before.st_mode) or before.st_size>PLAN['maximum_file_bytes']:raise ValueError('unexpected immutable file: '+str(p))
  total+=before.st_size
  if total>PLAN['maximum_total_bytes']:raise ValueError('capture byte cap')
  data=p.read_bytes(); h=hashlib.sha256(data).hexdigest()
  if h!=e['sha256']:raise ValueError('source input changed: '+str(p))
  if e['bytes'] is not None and len(data)!=e['bytes']:raise ValueError('source size changed: '+str(p))
  after_hash=hashlib.sha256(p.read_bytes()).hexdigest(); after=p.stat()
  identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns)
  if identity(before)!=identity(after) or after_hash!=h:raise ValueError('input mutated during capture: '+str(p))
  name='payload/'+str(i).zfill(4);info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o444
  archive.addfile(info,io.BytesIO(data))
  receipts.append(dict(source=e,archive_member=name,bytes=len(data),sha256_before=h,sha256_after=after_hash,
                       device=before.st_dev,inode=before.st_ino,mtime_ns=before.st_mtime_ns,resolved_path=str(p.resolve()),is_symlink=p.is_symlink()))
 receipt=dict(schema='orbit-poc-wholefit-input-capture-v1',host=os.uname().nodename,cpu_affinity=sorted(os.sched_getaffinity(0)),
              captured_unix=time.time(),entries=receipts,total_bytes=total,remote_mutations=False,native_executions=0)
 data=json.dumps(receipt,sort_keys=True).encode();info=tarfile.TarInfo('capture-receipt.json');info.size=len(data);info.mode=0o444;archive.addfile(info,io.BytesIO(data))
""".replace('__PLAN__',repr(plan))
remote=B/'capture-inputs02.remote.py'
with remote.open('x') as f:f.write(code)
argv=['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090','/usr/bin/taskset -c 32 /usr/bin/python3 -B -']
archive=B/'capture-inputs02.tar.gz'; stderr=B/'capture-inputs02.stderr'
start=time.monotonic()
with archive.open('xb') as output,stderr.open('xb') as errors:
 r=subprocess.run(argv,input=code.encode(),stdout=output,stderr=errors)
receipt=dict(argv=argv,returncode=r.returncode,elapsed_seconds=time.monotonic()-start,archive=str(archive),
             archive_bytes=archive.stat().st_size,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
             script_sha256=hashlib.sha256(remote.read_bytes()).hexdigest())
with (B/'capture-inputs02.execution.json').open('x') as f:json.dump(receipt,f,indent=2,sort_keys=True);f.write('\n')
if r.returncode:raise RuntimeError('Remote capture failed; all partial records retained')
with tarfile.open(archive,'r:gz') as a:
 members={m.name:m for m in a.getmembers()}
 cr=json.load(a.extractfile('capture-receipt.json'))
 expected={'capture-receipt.json',*(e['archive_member'] for e in cr['entries'])}
 if set(members)!=expected or any(not m.isfile() for m in members.values()):raise ValueError('Unexpected archive members')
 for e in cr['entries']:
  data=a.extractfile(e['archive_member']).read()
  if hashlib.sha256(data).hexdigest()!=e['source']['sha256'] or len(data)!=e['bytes']:raise ValueError('Captured bytes differ')
  target=B/'inputs/mirror'/e['source']['path'].lstrip('/')
  target.parent.mkdir(parents=True,exist_ok=True)
  with target.open('xb') as f:f.write(data)
  target.chmod(0o555 if 'original_diagnostic_exporter' in e['source']['scopes'] else 0o444)
  e['local_path']=str(target);e['local_sha256']=hashlib.sha256(target.read_bytes()).hexdigest()
with (B/'capture-inputs02.receipt.json').open('x') as f:json.dump(cr,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(dict(status='captured_verified',files=len(cr['entries']),uncompressed_bytes=cr['total_bytes'],**receipt)),flush=True)
