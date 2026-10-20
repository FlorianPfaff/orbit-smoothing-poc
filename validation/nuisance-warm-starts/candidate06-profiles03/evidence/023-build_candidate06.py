"""Build separately copied warm candidate; never touch prior build/campaign."""
from pathlib import Path
import datetime,hashlib,json,os,re,shutil,socket,subprocess,sys,time
B=Path('/home/emper/orbit-nuisance-warmstarts');OLD=Path('/home/emper/orbit-nuisance-performance');R=B/'source-candidate06';S=B/'native-source-06';BUILD=B/'build-06';PREFIX=B/'toolchain-01'
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
copy=json.loads((B/'control/toolchain-copy01.json').read_text());assert copy['target']==str(PREFIX)
assert json.loads((B/'control/toolchain-relocation01.json').read_text())['located_within_copy']
assert all(sha(PREFIX/x['path'])==x['sha256'] for x in copy['files'])
assert json.loads((B/'control/bootstrap-result01.json').read_text())['execution']['owned_process_group_cleaned']
assert not S.exists() and not BUILD.exists()
base=inventory(B/'native-source-01');shutil.copytree(B/'native-source-01',S,symlinks=True);assert inventory(S)==base
protected=[pin(p) for p in [OLD/'build-01/groops',OLD/'build-01/build-manifest.json',B/'control/bootstrap-result01.json',B/'control/candidate-build-result05.json',B/'build-05/groops',B/'build-05/build-manifest.json',B/'profiles02/freeze.json',B/'profiles02/run-result.json']]
patches=[pin(p) for p in sorted((R/'groops/extension').rglob('*')) if p.is_file()]+[pin(R/'scripts/build_groops.py')]
command=['/usr/bin/taskset','-c','0-3',str(PY),'-s','-B',str(R/'scripts/build_groops.py'),'--source-dir',str(S),'--build-dir',str(BUILD),'--prefix',str(PREFIX),'--jobs','4','--numerics','--segmented','--wide-tangent-candidate','--nuisance-performance','--nuisance-warm-starts','--cmake-executable',str(PY.parent.parent/'lib/python3.11/site-packages/cmake/data/bin/cmake')]
env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ['PYTHONPATH','PYTHONHOME']};env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',LD_LIBRARY_PATH=str(PREFIX/'lib'))
start=datetime.datetime.now(datetime.timezone.utc).isoformat();mono=time.monotonic();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
save(B/'control/candidate-build-plan06.json',{'schema':'orbit-poc-warm-candidate-build-plan-v1','started_at':start,'host':socket.gethostname(),'boot_id':boot,'command':command,'python':pin(PY),'runner':pin(__file__),'base_source':base,'patches':patches,'protected_originals':protected,'toolchain_copy':pin(B/'control/toolchain-copy01.json'),'limits':{'numerical_thread':1,'compiler_jobs':4,'cpus':[0,1,2,3],'timeout_seconds':7200,'process_tree_rss_bytes':8*1024**3}})
r=run_owned(command,python_executable=str(PY),cwd=B,env=env,log_path=B/'control/candidate-build06.log',receipt_path=B/'control/candidate-build-supervisor06.json',timeout_seconds=7200,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=16*1024**3,working_directory=B)
unchanged=all(sha(x['path'])==x['sha256'] for x in protected+patches) and inventory(B/'native-source-01')==base
record={'schema':'orbit-poc-warm-candidate-build-result-v1','started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'elapsed_monotonic_seconds':time.monotonic()-mono,'boot_unchanged':Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot,'execution':r,'inputs_and_originals_unchanged':unchanged,'build_plan':pin(B/'control/candidate-build-plan06.json')}
if r['status']=='complete' and unchanged:
 bins=B/'binaries';bins.mkdir(exist_ok=True);exe=BUILD/'groops';h=sha(exe);dest=bins/('groops-nuisance-warm-'+h[:16]);assert not dest.exists();shutil.copyfile(exe,dest);dest.chmod(0o555);shutil.copyfile(BUILD/'build-manifest.json',str(dest)+'.build-manifest.json')
 record['native']=pin(dest);record['build_manifest']=pin(BUILD/'build-manifest.json');record['source_root']=str(S)
 raw=subprocess.check_output(['ldd',str(dest)],env=env,text=True);assert 'not found' not in raw;record['ldd']=raw
 record['libraries']=[pin(p) for p in sorted(set(re.findall(r'(?:=>\s+)?(/[^\s]+)\s+\(',raw)))];record['runtime_environment']={'LD_LIBRARY_PATH':str(PREFIX/'lib')}
 record['patched_source']=inventory(S)
save(B/'control/candidate-build-result06.json',record)
print(json.dumps({'status':r['status'],'originals_unchanged':unchanged,'elapsed':record['elapsed_monotonic_seconds'],'native':record.get('native')}),flush=True)
if r['status']!='complete' or not unchanged:raise SystemExit(1)
