from pathlib import Path
import hashlib,json,os,sys,subprocess,datetime
B=Path('/home/emper/orbit-v4-failure-investigation');R=B/'source';OUT=B/'cost-pairs01'
sys.path.insert(0,str(R/'src'))
from orbit_poc.segmented.supervisor import run_owned
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def admission():
 for p in Path('/proc').glob('[0-9]*'):
  try:
   name=(p/'comm').read_text().strip()
   if name.startswith('groops') or name in ('cc1plus','f951','ninja'):raise RuntimeError('Other workload: '+name)
  except FileNotFoundError:pass
 return {'host':os.uname().nodename,'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'cpu':0,'scope':'cooperative current-host check, not exclusive CPU reservation'}
def verify(pins):
 for x in pins:
  if sha(x['path'])!=x['sha256']:raise RuntimeError('Changed input: '+x['path'])
source=Path('/home/emper/orbit-nuisance-performance/paired01/preparation.json');plan=json.loads(source.read_text())
build=json.loads((B/'control/build-result01.json').read_text());assert build['execution']['status']=='complete' and build['inputs_and_originals_unchanged']
native=build['native']['path'];OUT.mkdir();jobs=[]
# Balanced fixed order chosen before any new native outcome.
for method,accumulate,order in [('pulses',0,(0,1)),('pulses',1,(1,0)),('log_drag_ou',0,(1,0)),('log_drag_ou',1,(0,1))]:
 old=next(j for j in plan['jobs'] if j['method']==method and j['accumulate']==accumulate and j['cache']==1)
 verify([{'path':old['profile'],'sha256':old['profile_sha256']},old['source_profile'],*old['input_files']])
 for flag in order:
  name=f'{method}-accumulate{accumulate}-cost{flag}';d=OUT/name;d.mkdir()
  content=Path(old['profile']).read_text();text=content.replace(str(Path(old['profile']).parent),str(d))
  assert text!=content
  profile=d/'profile.xml';profile.write_text(text)
  jobs.append({'name':name,'method':method,'accumulate':accumulate,'cost_only_design':flag,'cache':1,'profile':str(profile),'profile_sha256':sha(profile),'input_files':[{'path':x['path'],'sha256':x['sha256']} for x in old['input_files']],'source_profile':pin(old['profile'])})
fixed={'OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','NUMEXPR_NUM_THREADS':'1','BLIS_NUM_THREADS':'1','GOTO_NUM_THREADS':'1','PYTHONDONTWRITEBYTECODE':'1','PYTHONNOUSERSITE':'1','ORBIT_POC_NUISANCE_PERFORMANCE':'1','ORBIT_POC_NUISANCE_INTERPOLATION_CACHE':'1','ORBIT_POC_NUMERICS_KEEP_INTERMEDIATE_FACTORS':'1','ORBIT_POC_NUMERICS_COMPRESS_ROW_PROVENANCE':'0','LD_LIBRARY_PATH':'/home/emper/orbit-nuisance-warmstarts/toolchain-01/lib'}
freeze={'schema':'orbit-poc-cost-only-pair-freeze-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'native':build['native'],'build_manifest':build['build_manifest'],'libraries':build['libraries'],'source_preparation':pin(source),'jobs':jobs,'environment_fixed':fixed,'runner':pin(__file__),'supervisor':pin(R/'src/orbit_poc/segmented/supervisor.py'),'admission':admission(),'limits':{'timeout_seconds':7200,'process_tree_rss_bytes':8*1024**3},'whole_fit_verified':False,'cpu':0,'one_numerical_thread':True}
save(OUT/'freeze.json',freeze)
results=[]
for job in jobs:
 verify([freeze['native'],freeze['build_manifest'],freeze['runner'],freeze['supervisor'],*freeze['libraries'],job['source_profile'],*job['input_files']]);assert sha(job['profile'])==job['profile_sha256']
 d=Path(job['profile']).parent;save(d/'admission.json',admission())
 env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH','PYTHONHOME')};env.update(fixed);env['ORBIT_POC_NUISANCE_COST_ONLY_DESIGN']=str(job['cost_only_design']);env['ORBIT_POC_NUMERICS_QR_PREFIX']=str(d/'qr')
 argv=['/usr/bin/taskset','-c','0',native,job['profile']]
 result=run_owned(argv,python_executable=sys.executable,cwd=d,env=env,log_path=d/'profile.log',receipt_path=d/'supervisor.json',timeout_seconds=7200,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=16*1024**3,working_directory=d)
 verify([*job['input_files'],job['source_profile']]);assert sha(job['profile'])==job['profile_sha256']
 record={'environment':{k:env[k] for k in [*fixed,'ORBIT_POC_NUISANCE_COST_ONLY_DESIGN','ORBIT_POC_NUMERICS_QR_PREFIX']},'command':argv,'config_sha256':job['profile_sha256'],'native_binary_sha256':freeze['native']['sha256'],'elapsed_seconds':result['elapsed_seconds'],'returncode':result['returncode'],'timed_out':result['status']=='timeout','status':result['status'],'peak_rss_bytes':result['peak_process_tree_rss_bytes'],'blas_openmp_threads':1,'cache':1,'cost_only_design':job['cost_only_design'],'accumulate_epoch_observations':job['accumulate'],'owned_process_group_cleaned':result['owned_process_group_cleaned'],'supervisor_sha256':sha(d/'supervisor.json'),'input_identity_after':'verified','freeze_sha256':sha(OUT/'freeze.json')}
 save(d/'profile.execution.json',record);results.append({'job':job['name'],**record});print(json.dumps({'job':job['name'],'status':result['status'],'seconds':result['elapsed_seconds']}),flush=True)
 assert result['owned_process_group_cleaned'] and result['cleanup']['verified']
save(OUT/'result.json',{'all_planned_attempts_executed':len(results)==8,'results':results,'whole_fit_verified':False,'cpu':0,'one_numerical_thread':True})
