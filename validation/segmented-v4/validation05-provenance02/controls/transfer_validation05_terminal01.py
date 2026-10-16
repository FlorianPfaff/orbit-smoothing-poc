from pathlib import Path
import datetime,hashlib,json,subprocess,tarfile
C=Path('/mnt/d/orbit-segmented-v4/control');R=C.parent/'validation-05-results'/'terminal-01'
assert not R.exists();R.mkdir(parents=True)
B='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff'
parts=['validation-05/terminal-capture-01','validation-05/terminal-linearization-arrays-01','validation-05/staging/continuation-audit-01/run/independent-review.json','validation05-continuation-01/cleanup/result.json']
archive=R/'frozen-evidence-transfer01.tar.gz';log=C/'validation05-terminal-transfer01.stderr.log'
command='tar -czf - -C '+B+' '+' '.join(parts)
start=datetime.datetime.now(datetime.timezone.utc).isoformat()
with archive.open('xb') as out,log.open('xb') as err:
 r=subprocess.run(['/mnt/c/Windows/System32/OpenSSH/ssh.exe','-o','BatchMode=yes','gpuserver4090',command],stdin=subprocess.DEVNULL,stdout=out,stderr=err,check=False)
assert r.returncode==0,r.returncode
members=[]
with tarfile.open(archive,'r:gz') as tar:
 for member in tar:
  path=Path(member.name);assert not path.is_absolute() and '..' not in path.parts
  if member.isdir():continue
  assert member.isfile(),member.name
  if member.name.startswith(parts[0]+'/'):relative=Path('terminal-capture-01')/path.relative_to(parts[0])
  elif member.name.startswith(parts[1]+'/'):relative=Path('terminal-linearization-arrays-01')/path.relative_to(parts[1])
  elif member.name==parts[2]:relative=Path('audit/independent-review.json')
  elif member.name==parts[3]:relative=Path('cleanup/result.json')
  else:raise AssertionError(member.name)
  p=R/relative;assert not p.exists();p.parent.mkdir(parents=True,exist_ok=True);h=hashlib.sha256();count=0
  with tar.extractfile(member) as src,p.open('xb') as dst:
   while chunk:=src.read(4*1024*1024):h.update(chunk);dst.write(chunk);count+=len(chunk)
  assert count==member.size
  members.append({'remote_path':B+'/'+member.name,'path':str(p),'sha256':h.hexdigest(),'bytes':count})
assert len({x['path'] for x in members})==len(members)
def pin(p):b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
assert pin(R/'audit/independent-review.json')['sha256']=='159b9e6298265ef2db60abc4954c79efc301455c66743372eb80aae202e7d4ac'
assert pin(R/'terminal-capture-01/manifest.json')['sha256'].startswith('e4f5b2b8')
assert pin(R/'terminal-linearization-arrays-01/manifest.json')['sha256'].startswith('8d3a73e6')
assert pin(R/'cleanup/result.json')['sha256'].startswith('7c747bc1')
receipt={'schema':'orbit-poc-frozen-terminal-evidence-transfer-v1','started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'helper':pin(Path(__file__)),'remote_command':command,'returncode':r.returncode,'archive':pin(archive),'stderr':pin(log),'members':members,'scope':'Read-only tar stream of already frozen capture/array/audit/cleanup evidence. No new capture, independent numerical audit, scientific run, remote write or preparation mutation.'}
p=C/'validation05-terminal-transfer01.json';p.write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n');print(json.dumps({'receipt':pin(p),'archive':receipt['archive'],'members':len(members),'capture':pin(R/'terminal-capture-01/manifest.json'),'arrays':pin(R/'terminal-linearization-arrays-01/manifest.json')}))
