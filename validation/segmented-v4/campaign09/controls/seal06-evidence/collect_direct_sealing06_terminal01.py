from pathlib import Path
import hashlib,json,subprocess,tarfile
C=Path('/mnt/d/orbit-segmented-v4/control');B='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff';ssh=['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090'];helper=C/'capture_direct_sealing06_terminal01.py';output=C/'direct-sealing06-terminal01';archive=C/'direct-sealing06-terminal01.tar.gz'
if output.exists() or archive.exists():raise ValueError('Fresh terminal capture required')
r=subprocess.run(ssh+['env PYTHONDONTWRITEBYTECODE=1 /usr/bin/taskset -c 32 /usr/bin/python3 -B -'],input=helper.read_text(),text=True,capture_output=True)
(C/'direct-sealing06-terminal-capture01.stdout.json').write_text(r.stdout);(C/'direct-sealing06-terminal-capture01.stderr.log').write_text(r.stderr)
if r.returncode:raise RuntimeError(r.stderr)
v=json.loads(r.stdout)
if v['archive']!=B+'/direct-sealing06-terminal-01/terminal.tar.gz':raise ValueError('Capture path changed')
with archive.open('xb') as f:
 r=subprocess.run(ssh+['/usr/bin/taskset -c 32 /bin/cat '+v['archive']],stdout=f,stderr=subprocess.PIPE)
if r.returncode:raise RuntimeError(r.stderr.decode())
if hashlib.sha256(archive.read_bytes()).hexdigest()!=v['archive_sha256']:raise ValueError('Archive transfer changed')
output.mkdir()
with tarfile.open(archive,'r:gz') as t:
 for m in t.getmembers():
  if not m.isfile() or Path(m.name).is_absolute() or '..' in Path(m.name).parts:raise ValueError('Unsafe capture archive')
  p=output/m.name;p.parent.mkdir(parents=True,exist_ok=True)
  with p.open('xb') as f:f.write(t.extractfile(m).read())
manifest=output/'manifest.json'
if hashlib.sha256(manifest.read_bytes()).hexdigest()!=v['manifest_sha256']:raise ValueError('Capture manifest changed')
cap=json.loads(manifest.read_text())
for row in cap['files']:
 p=output/row['relative_path']
 if p.stat().st_size!=row['bytes'] or hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Captured file changed')
print(json.dumps({'capture':str(output),'manifest_sha256':v['manifest_sha256'],'files':v['files'],'bytes':v['bytes'],'status':cap['status']}))
