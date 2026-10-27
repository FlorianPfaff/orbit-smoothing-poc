from pathlib import Path
import datetime,hashlib,json,os,re,shutil,socket,subprocess,sys,time
B=Path('/home/emper/orbit-v4-failure-investigation');R=B/'source';S=B/'native-source-02';BUILD=B/'build-02'
PREFIX=Path('/home/emper/orbit-nuisance-warmstarts/toolchain-01')
PY=Path('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/numerics-v3.1/python/bin/python')
sys.path.insert(0,str(R/'src'))
from orbit_poc.segmented.supervisor import run_owned
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def pin(p):return {'path':str(p),'sha256':sha(p),'bytes':Path(p).stat().st_size}
def inventory(root):return {str(p.relative_to(root)):sha(p) for p in sorted((root/'source').rglob('*')) if p.is_file()}
for p in Path('/proc').glob('[0-9]*'):
 try:
  n=(p/'comm').read_text().strip()
  if n.startswith('groops') or n in ['cc1plus','f951','ninja','segmented_qr']:raise RuntimeError('Competing workload: '+str(p)+' '+n)
 except FileNotFoundError:pass
assert not S.exists() and not BUILD.exists()
old=Path('/home/emper/orbit-nuisance-warmstarts/native-source-01')
protected=[pin(p) for p in [Path('/home/emper/orbit-nuisance-performance/build-01/groops'),Path('/home/emper/orbit-nuisance-warmstarts/build-06/groops'),B/'evidence/campaign-before.json']]
previous=json.loads((B/'control/build-result01.json').read_text())
protected += [pin(previous['native']['path']),pin(previous['build_manifest']['path']),pin(B/'control/build-result01.json')]
patches=[pin(p) for p in sorted((R/'groops/extension').rglob('*')) if p.is_file() and '__pycache__' not in p.parts]+[pin(R/'scripts/build_groops.py')]
subprocess.run(['git','clone','--shared','--no-checkout',str(old),str(S)],check=True)
subprocess.run(['git','-C',str(S),'checkout','--detach','7e1bd6dc8bf2fb1c9180f2f9366efa7e7b4477ee'],check=True)
assert not subprocess.check_output(['git','-C',str(S),'status','--porcelain'],text=True).strip()
base=inventory(S)
command=['/usr/bin/taskset','-c','0-3',str(PY),'-s','-B',str(R/'scripts/build_groops.py'),'--source-dir',str(S),'--build-dir',str(BUILD),'--prefix',str(PREFIX),'--jobs','4','--numerics','--segmented','--wide-tangent-candidate','--nuisance-performance','--variational-memory-candidate','--cmake-executable',str(PY.parent.parent/'lib/python3.11/site-packages/cmake/data/bin/cmake')]
env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ['PYTHONPATH','PYTHONHOME']};env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',LD_LIBRARY_PATH=str(PREFIX/'lib'))
start=datetime.datetime.now(datetime.timezone.utc).isoformat();mono=time.monotonic();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
save(B/'control/build-plan02.json',{'schema':'orbit-poc-v4-failure-candidate-build-plan-v1','started_at':start,'host':socket.gethostname(),'boot_id':boot,'command':command,'python':pin(PY),'runner':pin(__file__),'clean_upstream_source':base,'patches':patches,'protected_originals':protected,'limits':{'numerical_thread':1,'compiler_jobs':4,'cpus':[0,1,2,3],'timeout_seconds':7200,'process_tree_rss_bytes':8*1024**3},'admission':'local current-host check; no exclusive CPU reservation claim'})
r=run_owned(command,python_executable=str(PY),cwd=B,env=env,log_path=B/'control/build02.log',receipt_path=B/'control/build-supervisor02.json',timeout_seconds=7200,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=16*1024**3,working_directory=B)
unchanged=all(sha(x['path'])==x['sha256'] for x in protected+patches)
record={'schema':'orbit-poc-v4-failure-candidate-build-result-v1','started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_monotonic_seconds':time.monotonic()-mono,'boot_unchanged':Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot,'execution':r,'inputs_and_originals_unchanged':unchanged,'build_plan':pin(B/'control/build-plan02.json')}
if r['status']=='complete' and unchanged:
 exe=BUILD/'groops';h=sha(exe);dest=B/'binaries'/('groops-fit-reliability-'+h[:16]);assert not dest.exists();shutil.copyfile(exe,dest);dest.chmod(0o555);shutil.copyfile(BUILD/'build-manifest.json',str(dest)+'.build-manifest.json')
 record['native']=pin(dest);record['build_manifest']=pin(BUILD/'build-manifest.json');record['source_root']=str(S)
 raw=subprocess.check_output(['ldd',str(dest)],env=env,text=True);assert 'not found' not in raw;record['ldd']=raw
 record['libraries']=[pin(p) for p in sorted(set(re.findall(r'(?:=>\s+)?(/[^\s]+)\s+\(',raw)))];record['runtime_environment']={'LD_LIBRARY_PATH':str(PREFIX/'lib')};record['patched_source']=inventory(S)
save(B/'control/build-result02.json',record)
print(json.dumps({'status':r['status'],'originals_unchanged':unchanged,'elapsed':record['elapsed_monotonic_seconds'],'native':record.get('native')}),flush=True)
if r['status']!='complete' or not unchanged:raise SystemExit(1)
