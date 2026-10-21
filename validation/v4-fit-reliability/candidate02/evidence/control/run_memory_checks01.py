from pathlib import Path
import hashlib,json,os,sys,xml.etree.ElementTree as ET,copy,subprocess
B=Path('/home/emper/orbit-v4-failure-investigation');R=B/'source';OUT=B/'memory-checks01';IN=B/'inputs/memory-replay02'
sys.path.insert(0,str(R/'src'))
from orbit_poc.segmented.supervisor import run_owned
from orbit_poc.numerics.backend import read_native_table
import numpy as np
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with Path(p).open('x') as f:json.dump(v,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def admission():
 for p in Path('/proc').glob('[0-9]*'):
  try:
   n=(p/'comm').read_text().strip()
   if n.startswith('groops') or n in ('ninja','cc1plus','f951'):raise RuntimeError('Competing workload: '+n)
  except FileNotFoundError:pass
build=json.loads((B/'control/build-result01.json').read_text());assert build['execution']['status']=='complete' and build['inputs_and_originals_unchanged']
native=build['native']['path'];OUT.mkdir();admission()
env={k:v for k,v in os.environ.items() if not k.startswith('ORBIT_POC_') and k not in ('PYTHONPATH','PYTHONHOME')};env.update(OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',NUMEXPR_NUM_THREADS='1',PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYTHONPATH=str(R/'src'),LD_LIBRARY_PATH='/home/emper/orbit-nuisance-warmstarts/toolchain-01/lib',ORBIT_POC_VARIATIONAL_MEMORY_GROOPS=native,ORBIT_POC_VARIATIONAL_NATIVE_SOURCE=build['source_root'])
jobs=[]
original=ET.parse(IN/'propagate.xml').getroot()
for block in (0,64,256):
 d=OUT/f'replay72h-block{block}';d.mkdir();tree=copy.deepcopy(original)
 for p in list(tree.findall('program')):
  if p.find('PreprocessingVariationalEquation') is not None:tree.remove(p)
 for node in tree.iter():
  if not node.text:continue
  if node.tag=='inputfileVariational':node.text=str(IN/'variational.dat')
  elif node.tag=='inputfileParameters':node.text=str(IN/'fixed_force.txt')
  elif node.tag=='inputfileInitialState':node.text=str(IN/'physical_initial.txt')
  elif node.tag=='inputfileLogDensity':node.text=str(IN/'log_density.txt')
  elif node.tag=='inputfileEphemerides':node.text=str(IN/'ephemerides.dat')
  elif node.tag in ('outputfileOrbit','inputfile'):node.text=str(d/'orbit.dat')
  elif node.tag=='outputfile':node.text=str(d/'orbit.txt')
  elif node.tag=='outputfileParameters':node.text=str(d/'reference.txt')
  elif node.tag=='outputfileInitialStateDesign':node.text=str(d/'initial_design.txt')
 ET.ElementTree(tree).write(d/'replay.xml',encoding='utf-8',xml_declaration=True)
 jobs.append({'block_epochs':block,'xml':pin(d/'replay.xml')})
inputs=[pin(p) for p in IN.iterdir() if p.is_file()];runtime=[build['native'],build['build_manifest'],*build['libraries'],pin(__file__),pin(R/'src/orbit_poc/segmented/supervisor.py')]
freeze={'schema':'orbit-poc-memory-component-freeze-v1','input_pins':inputs,'runtime_pins':runtime,'native_test':pin(R/'tests/test_native_variational_memory.py'),'jobs':jobs,'one_numerical_thread':True,'cpu':0,'limits':{'timeout_seconds':7200,'process_tree_rss_bytes':8*1024**3},'scope':'failed fixed-parameter evaluator only; propagation archive reused exactly; not whole-fit or covariance validation'}
save(OUT/'freeze.json',freeze)
def verify():
 for x in inputs+runtime+[freeze['native_test']]+[j['xml'] for j in jobs]:assert sha(x['path'])==x['sha256'],x
verify();d=OUT/'native-pairs';d.mkdir();argv=['/usr/bin/taskset','-c','0',sys.executable,'-B','-m','pytest','-q','-p','no:cacheprovider','--basetemp='+str(d/'temp'),'--junitxml='+str(d/'tests.xml'),'tests/test_native_variational_memory.py']
r=run_owned(argv,python_executable=sys.executable,cwd=R,env=env,log_path=d/'pytest.log',receipt_path=d/'supervisor.json',timeout_seconds=3600,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=16*1024**3,working_directory=d);verify()
counts=list(ET.parse(d/'tests.xml').getroot().iter('testcase')) if (d/'tests.xml').exists() else []
record={'execution':r,'counts':{'tests':len(counts),**{t:sum(c.find(t) is not None for c in counts) for t in ('failure','error','skipped')}}};save(d/'result.json',record);print(json.dumps(record['counts']),flush=True)
assert r['owned_process_group_cleaned'] and r['cleanup']['verified']
if r['status']!='complete' or any(record['counts'][t] for t in ('failure','error','skipped')):raise SystemExit('Native block checks failed; no large replay launched')
results=[]
for job in jobs:
 admission();verify();d=Path(job['xml']['path']).parent;env['ORBIT_POC_VARIATIONAL_BLOCK_EPOCHS']=str(job['block_epochs']);argv=['/usr/bin/taskset','-c','0',native,job['xml']['path']]
 r=run_owned(argv,python_executable=sys.executable,cwd=d,env=env,log_path=d/'native.log',receipt_path=d/'supervisor.json',timeout_seconds=7200,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=16*1024**3,working_directory=d);verify()
 record={'block_epochs':job['block_epochs'],'execution':r,'freeze_sha256':sha(OUT/'freeze.json'),'whole_fit_verified':False};save(d/'result.json',record);results.append(record)
 print(json.dumps({'block_epochs':job['block_epochs'],'status':r['status'],'seconds':r['elapsed_seconds'],'rss_bytes':r['peak_process_tree_rss_bytes']}),flush=True)
 assert r['owned_process_group_cleaned'] and r['cleanup']['verified']
checks={}
if all(x['execution']['status']=='complete' for x in results[1:]):
 a=read_native_table(OUT/'replay72h-block64/orbit.txt',10);b=read_native_table(OUT/'replay72h-block256/orbit.txt',10)
 pos=float(np.max(np.linalg.norm(a[:,1:4]-b[:,1:4],axis=1)));vel=float(np.max(np.linalg.norm(a[:,4:7]-b[:,4:7],axis=1)))
 checks={'epochs':len(a),'epoch_identity':bool(np.array_equal(a[:,0],b[:,0])),'maximum_position_difference_m':pos,'maximum_velocity_difference_m_s':vel,'passed':bool(np.array_equal(a[:,0],b[:,0]) and pos<2e-6 and vel<3e-9),'position_limit_m':2e-6,'velocity_limit_m_s':3e-9}
save(OUT/'result.json',{'native_pairs':record if False else str(OUT/'native-pairs/result.json'),'replays':results,'blocked_pair':checks,'whole_fit_verified':False})
