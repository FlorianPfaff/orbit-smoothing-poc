
from pathlib import Path
import ctypes,hashlib,json,os,sys,platform,importlib.util
import numpy,scipy,gtsam
c=json.loads(Path(sys.argv[1]).read_bytes());f=json.loads(Path(sys.argv[2]).read_bytes())['source'];source=Path(c['paths']['source'])
assert os.statvfs(source).f_flag & os.ST_RDONLY
files={str(p.relative_to(source)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source.rglob('*')) if p.is_file()}
assert files==f['files'] and len(files)==771
libraries={}
for name,item in c['runtime_artifacts'].items():
 if name.startswith('glibc239_'):
  actual=hashlib.sha256(Path(item['path']).read_bytes()).hexdigest();assert actual==item['sha256'];libraries[name]=actual
assert libraries
libc=ctypes.CDLL(None);libc.gnu_get_libc_version.restype=ctypes.c_char_p;version=libc.gnu_get_libc_version().decode();assert version=='2.39'
for key in ('native_source','build','binaries','run','temporary'):
 path=Path(c['paths'][key]);assert not (os.statvfs(path).f_flag & os.ST_RDONLY)
 (path/'namespace-writable-probe.txt').write_text('Only this staging path is intentionally writable.\n')
helper=Path(sys.argv[3]);reference=Path(sys.argv[4])
assert hashlib.sha256(helper.read_bytes()).hexdigest()==sys.argv[5]
assert hashlib.sha256(reference.read_bytes()).hexdigest()==sys.argv[6]
spec=importlib.util.spec_from_file_location('upstream_check',helper);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
upstream=module.check(c['paths']['upstream_repository'],json.loads(reference.read_bytes()))
assert os.statvfs(c['paths']['upstream_repository']).f_flag & os.ST_RDONLY
print(json.dumps({'upstream':upstream,'source_read_only':True,'upstream_read_only':True,'source_files':len(files),'source_sha256':f['sha256'],'glibc':version,'canonical_library_hashes':libraries,'scientific_imports':['numpy','scipy','gtsam'],'python':platform.python_version(),'numpy':numpy.__version__,'scipy':scipy.__version__,'writable_outputs':'five staging-only paths','pid_namespace':os.readlink('/proc/self/ns/pid')}))
