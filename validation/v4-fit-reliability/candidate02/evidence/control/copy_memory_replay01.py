from pathlib import Path
import hashlib,json,tarfile,io,sys,datetime
r=Path('/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/validation-07/run')
b=(r/'manifest.json').read_bytes();assert hashlib.sha256(b).hexdigest()=='4877f929be8a9eda5d58ff6b4eb0e0fc8b84ea16934a6fbe63fa5a18418fa5c6'
p=r/'attempts/leo500-quiet-normal-groops_log_drag_ou-72h--dense_corrected/point-001-initial'
files={'propagate.xml':p/'closure-01/propagate.xml','variational.dat':p/'closure-01/variational.dat','fixed_force.txt':p/'fixed_force.txt','physical_initial.txt':p/'physical_initial.txt','log_density.txt':p/'native/log_density.txt','ephemerides.dat':Path('/home/florianpfaff/codex-runs/orbit-comparison-v3-20261013/inputs/auxiliary/tides/ephemerides_JPL_DE432.dat')}
records=[]
with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as out:
 for name,f in files.items():
  assert f.is_file() and not f.is_symlink()
  data=f.read_bytes();assert len(data)<128*1024**2
  records.append({'source':str(f),'name':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
  t=tarfile.TarInfo(name);t.size=len(data);out.addfile(t,io.BytesIO(data))
 for rec in records:assert hashlib.sha256(Path(rec['source']).read_bytes()).hexdigest()==rec['sha256']
 data=json.dumps({'copied_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_manifest_sha256':hashlib.sha256(b).hexdigest(),'files':records},indent=2).encode();t=tarfile.TarInfo('provenance.json');t.size=len(data);out.addfile(t,io.BytesIO(data))
