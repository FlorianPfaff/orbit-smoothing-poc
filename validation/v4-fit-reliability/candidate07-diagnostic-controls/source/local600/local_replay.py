"""One local fixed-physical nuisance profile; no optimizer or covariance action."""
from pathlib import Path
import argparse
import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import time
import traceback
import unittest

HERE=Path(__file__).absolute().parent
BASE=Path('/mnt/d/orbit-v41-recovery02')
ROOT=BASE/'candidate07-density04-local-fixed-replay-run01'
SCRATCH=Path('/home/emper/orbit-density04-local-fixed-replay01')
OLD=BASE/'density-trial-cold-controls04'
OLD_LEDGER='2bef971aaa46668bff5a09aa025e3b2ff2970a0b0e1e0c51540a8239789fa457'
PLAN=BASE/'candidate07-cold-density04/plan.json'
PLAN_SHA='530221cae291e0689cdd5dce62deca1b18f27ad0682553c8e9d5ced11504cafb'
REUSED_SHA='a4f36ee0e0ce263e232554fb19d50b5d8e810729d87d861fe47cb5af10acd193'
SUPERVISOR_SHA='060bc208a5d36631689905563c9e969ae4615299e39e87637f71393b62eed267'
BOOT='8e0af59f-3dd0-4063-b345-59e9ba9a2bab'
SCHEMA='candidate07-local-fixed-profile-plan-v1'
ARM='A-original'
LIMITS={'native_seconds':600,'rss_bytes':8*1024**3,'cpu':4,'threads':1}

def need(value,message):
 if not value:raise ValueError(message)
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for block in iter(lambda:f.read(1048576),b''):h.update(block)
 return h.hexdigest()
def read(path):return json.loads(Path(path).read_text())
def pin(path):
 p=Path(path);need(p.is_file() and not p.is_symlink(),'regular file required: '+str(p))
 return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def verify(row):
 need(pin(row['path'])==row,'pinned file changed: '+row['path']);return Path(row['path'])
def save(path,value):
 with Path(path).open('x') as f:json.dump(value,f,sort_keys=True,indent=2,allow_nan=False);f.write('\n');f.flush();os.fsync(f.fileno())
 return pin(path)
def ledger(root,name,expected):
 path=root/name;need(sha(path)==expected,'source ledger changed');rows={}
 for line in path.read_text().splitlines():
  digest,relative=line.split('  ',1);p=Path(relative)
  need(len(digest)==64 and all(c in '0123456789abcdef' for c in digest) and not p.is_absolute() and '..' not in p.parts and p.as_posix()==relative and relative not in rows,'invalid ledger')
  row=pin(root/p);need(row['sha256']==digest,'source member changed');rows[relative]=row
 need({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() or p.is_symlink()}==set(rows)|{name},'source membership changed')
 return rows
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
def helpers(source_sha,*,inside=False):
 sources=ledger(HERE,'inputs.sha256',source_sha)
 ledger(HERE/'reused','inputs.sha256',REUSED_SHA)
 if not inside:ledger(OLD,'source.sha256',OLD_LEDGER)
 for name,digest in {'one_hour_controls.py':'a968d8b3f312ccd0f4f62965a30dafb0cd76564cdd72bf678af73ec4bf02fc1d','contracts.py':'3695978cfc22078df08e1dd7f8cb50e04b72dd4516986d13a5067f46dfb7b61d','archived_reference.py':'4739b1bf52b0fb74587b01df5ee23d48a3f86ec5cada54874cb610a6a844a4fe'}.items():need(sha(OLD/name)==digest,'local helper changed')
 sys.path.insert(0,str(OLD));h=load(OLD/'one_hour_controls.py','local_profile_cold_helpers')
 a=load(HERE/'reused/replay_inputs.py','replay_inputs')
 return h,a,sources
def original():
 need(sha(PLAN)==PLAN_SHA,'original plan changed');p=read(PLAN)
 need(p['runtime']['native']['sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d' and len(p['native_loader_dependencies'])==14,'wrong native runtime')
 return p
def parent_environment(old):
 return {k:v for k,v in old['jobs'][0]['environment'].items() if k not in {'ORBIT_POC_GNSS_DESIGN_SCRATCH','ORBIT_POC_NUMERICS_SPOOL_DIRECTORY','TMPDIR','TMP','TEMP'}}
def runtime_check(h,p,*,inside=False):
 h.verify_files(p['bindings'],inside=inside);h.verify_directory_membership(p,inside=inside)
 for row in p['native_loader_dependencies']:h.c.verify(row)
 need(sha(h.c.SOURCE/'src/orbit_poc/segmented/supervisor.py')==SUPERVISOR_SHA,'supervisor changed')
def authority(path,digest,action,source_sha,plan_sha=None):
 need(sha(path)==digest,'action review changed');r=read(path)
 need(r.get('schema')=='candidate07-local-fixed-profile-action-review-v1' and r.get('approved_actions')==[action] and r.get('source_ledger_sha256')==source_sha,'wrong action scope')
 need(r.get('native_seconds')==600 and r.get('boot_id')==BOOT,'review limit/boot changed')
 need(r.get('plan_sha256')==plan_sha,'review plan differs')
 for row in r.get('evidence',[]):verify(row)
 return r
def binding(h,rows,host,target,role,digest=None):h.add_binding(rows,host,target,role,digest)

def prepare(source_sha,review_path,review_sha):
 h,a,sources=helpers(source_sha);old=original();authority(review_path,review_sha,'prepare',source_sha)
 need(dict(os.environ)==parent_environment(old),'parent environment changed')
 h.admission();lock,_=h.shared_lock()
 try:
  runtime_check(h,old);need(not ROOT.exists() and not ROOT.is_symlink() and not SCRATCH.exists() and not SCRATCH.is_symlink(),'preserve existing attempt')
  ROOT.mkdir();SCRATCH.mkdir(mode=0o700);_,legacy=h.helpers();filesystem=legacy.disk_filesystem(SCRATCH)
  for stage in ('prepared','cold-density'):
   (ROOT/stage).mkdir();(SCRATCH/stage).mkdir(mode=0o700)
   for leaf in ('tmp','scratch','row-spool','legacy-output'):(ROOT/stage/leaf).mkdir();(SCRATCH/stage/leaf).mkdir(mode=0o700)
   (ROOT/stage/'fit').mkdir()
  point=ROOT/'frozen/point';point.mkdir(parents=True);(ROOT/'frozen').chmod(0o700)
  armroot=ROOT/'cold-density/arms'/ARM
  for leaf in ('output/native/2024-04-24','scratch/design','scratch/rows','scratch/tmp'):(armroot/leaf).mkdir(parents=True,exist_ok=True)
  for leaf in ('design','rows','tmp'):(SCRATCH/'cold-density/scratch'/leaf).mkdir(mode=0o700)
  rows={r['target']:dict(r) for r in old['bindings']};original_rows=dict(rows);projection=[]
  # Same local readonly file-projection convention as cold04, with all133
  # private names explicitly attributed to their original pinned backings.
  for entry in a.aliases():
   need(entry['target'] in original_rows,'private backing absent from original plan');r=original_rows[entry['target']];h.verify_files([r])
   relative=Path(entry['path']).relative_to(a.POINT);destination=point/relative;destination.parent.mkdir(parents=True,exist_ok=True)
   with Path(r['host']).open('rb') as src,destination.open('xb') as dst:shutil.copyfileobj(src,dst)
   need(sha(destination)==r['sha256'],'private copy differs');binding(h,rows,destination,entry['path'],'fixed_profile_private_input',r['sha256'])
   projection.append({**entry,'original_binding':r,'projection':pin(destination)})
  for target,r in a.physical_inputs().items():
   relative=Path(target).relative_to(a.POINT);destination=point/relative;destination.parent.mkdir(parents=True,exist_ok=True)
   with Path(r['path']).open('rb') as src,destination.open('xb') as dst:shutil.copyfileobj(src,dst)
   need(sha(destination)==r['sha256'],'physical copy differs');binding(h,rows,destination,target,'fixed_profile_physical',r['sha256'])
  # Reuse the exact closed native input closure from the reviewed original A
  # composition, but project its bytes locally instead of its remote aliases.
  composition=read(HERE/'reused/provenance/original-A-composition.json');need(len(composition['records'])==197,'original native closure differs')
  old_pulse='/mnt/d/orbit-v41-recovery02/candidate06-cold02/cold-pulses/fit/point-019-final-covariance/'
  unused_pulse={target:r for target,r in composition['records'].items() if target.startswith(old_pulse)}
  need(len(unused_pulse)==8 and old_pulse.encode() not in (HERE/'reused/provenance/original-profile.xml').read_bytes(),'obsolete pulse closure selection changed')
  pool={r['sha256']:r for r in old['bindings']};native_targets=[]
  for target,r in composition['records'].items():
   if target in unused_pulse:continue
   need(r['sha256'] in pool,'native input unavailable locally');backing=pool[r['sha256']]
   binding(h,rows,backing['host'],target,'fixed_profile_native_closure',r['sha256']);native_targets.append(target)
  xml,changes=a.adapted_profile((HERE/'reused/provenance/original-profile.xml').read_bytes(),ROOT/'cold-density')
  profile=ROOT/'frozen/profile.xml'
  with profile.open('xb') as f:f.write(xml)
  env=a.environment(old['jobs'][0]['environment'],ROOT/'cold-density');environment=save(ROOT/'frozen/environment.json',env)
  for row in [*sources.values(),pin(HERE/'inputs.sha256'),*old['control_pins'],*old['helper_pins'],pin(profile),environment]:binding(h,rows,row['path'],row['path'],'fixed_profile_control',row['sha256'])
  g,_=h.helpers();directories=copy.deepcopy(old['directory_bindings']);directories.append({'host':str(point),'target':a.POINT,'role':'readonly_original_point_projection','inventory':g.runtime_api().tree(point)})
  with (ROOT/'python-runtime.json').open('xb') as f:f.write(verify(old['python_runtime']).read_bytes())
  p={'schema':SCHEMA,'output':str(ROOT),'scratch_root':str(SCRATCH),'runtime':old['runtime'],'python_runtime':pin(ROOT/'python-runtime.json'),'native_loader_dependencies':old['native_loader_dependencies'],'bindings':sorted(rows.values(),key=lambda r:r['target']),'directory_bindings':directories,'originals':{},'jobs':[],'prepared':{'output_dir':str(ROOT/'unused-original-output')},'forbidden_paths':h.FORBIDDEN+[a.POINT+'/qr.profile.json',a.POINT+'/qr.74.R.bin',a.POINT+'/profile.log'],'source_ledger_sha256':source_sha,'source_root':str(HERE),'source_members':sources,'original_plan':pin(PLAN),'profile':pin(profile),'environment':environment,'output_only_changes':changes,'private_projection':projection,'physical_inputs':a.physical_inputs(),'native_binding_targets':sorted(set(native_targets+[r['path'] for r in a.aliases()]+list(a.physical_inputs()))),'unconsumed_old_pulse_records_not_exposed':unused_pulse,'boot_id':BOOT,'limits':LIMITS,'scratch_filesystem':filesystem,'requested_cwd':a.POINT,'physical_optimization':False,'cold_nuisance':True,'covariance_authority':False,'release_authority':False,'representation':'qualified local readonly file projections; remote symlink topology is not reproduced'}
  p['owned_directories']=[h.c.directory_identity(q) for q in [ROOT,SCRATCH,ROOT/'frozen',ROOT/'prepared',ROOT/'cold-density',SCRATCH/'prepared',SCRATCH/'cold-density',*[(SCRATCH/s/leaf) for s in ('prepared','cold-density') for leaf in ('tmp','scratch','row-spool','legacy-output')]]]
  h.resource_admission(p);save(ROOT/'plan.json',p);runtime_check(h,old);ledger(HERE,'inputs.sha256',source_sha)
  return p
 finally:lock.close()

def checked(source_sha,plan_sha,*,inside=False,native_only=False):
 h,a,sources=helpers(source_sha,inside=inside);path=ROOT/'plan.json';need(sha(path)==plan_sha,'prepared plan changed');p=read(path)
 need(p['schema']==SCHEMA and p['source_ledger_sha256']==source_sha and p['source_root']==str(HERE) and p['output']==str(ROOT) and p['scratch_root']==str(SCRATCH) and p['limits']==LIMITS and p['boot_id']==BOOT,'plan scope differs')
 need(p['source_members']==sources and p['original_plan']['sha256']==PLAN_SHA and p['requested_cwd']==a.POINT,'source/point attribution changed')
 need(p['physical_optimization'] is False and p['cold_nuisance'] is True and p['covariance_authority'] is False and p['release_authority'] is False,'nonlinear/covariance action forbidden')
 for row in (p['profile'],p['environment'],p['python_runtime']):verify(row)
 expected,changes=a.adapted_profile((HERE/'reused/provenance/original-profile.xml').read_bytes(),ROOT/'cold-density')
 need(Path(p['profile']['path']).read_bytes()==expected and p['output_only_changes']==changes,'output rebase changed')
 old=read(HERE/'reused/provenance/original-density-plan.json');need(read(p['environment']['path'])==a.environment(old['jobs'][0]['environment'],ROOT/'cold-density'),'native environment changed')
 if native_only:
  rows={r['target']:r for r in p['bindings']};h.verify_files([rows[t] for t in p['native_binding_targets']],inside=True)
  for r in p['native_loader_dependencies']:h.c.verify(r)
 else:runtime_check(h,p,inside=inside)
 if not inside:
  need(Path('/proc/sys/kernel/random/boot_id').read_text().strip()==BOOT,'new boot requires fresh review')
  verify(p['original_plan'])
  for row in p['owned_directories']:h.c.verify_directory_identity(row)
  _,legacy=h.helpers();need(legacy.disk_filesystem(SCRATCH)==p['scratch_filesystem'],'scratch filesystem changed')
 need(sha(path)==plan_sha,'plan changed during verification');return h,a,p

def namespace(h,a,p,mode,argv):
 stage='cold-density' if mode=='native' else 'prepared';args=h.namespace(p,stage,argv)
 arm=ROOT/'cold-density/arms'/ARM
 # The existing local builder already creates all required ancestors. The
 # arm scratch is one additional owned ext4 mount; old point is readonly.
 index=args.index('--proc');extra=[]
 if mode!='native':extra=['--dir',str(ROOT/'cold-density'),'--dir',str(ROOT/'cold-density/arms'),'--dir',str(arm)]
 args[index:index]=extra+['--bind',str(SCRATCH/'cold-density/scratch'),str(arm/'scratch')]
 if mode=='native':
  start=args.index('--setenv');end=args.index('--chdir',start)
  args[start:end]=[v for pair in read(p['environment']['path']).items() for v in ('--setenv',*pair)]
  index=args.index('--chdir');need(args[index+1]==str(h.c.SOURCE),'original cwd builder changed');args[index+1]=a.POINT
 return args

def worker(mode,source_sha,plan_sha):
 need(sys.flags.isolated and sys.flags.no_site and sys.flags.no_user_site and sys.flags.dont_write_bytecode,'isolated stdlib worker required')
 h,a,p=checked(source_sha,plan_sha,inside=True,native_only=(mode=='native'))
 stage='cold-density' if mode=='native' else 'prepared';root=ROOT/stage
 expected=read(p['environment']['path']) if mode=='native' else h.environment(root)
 cwd=a.POINT if mode=='native' else str(h.c.SOURCE)
 need(dict(os.environ)=={**expected,'PWD':cwd} and os.getcwd()==cwd,'actual worker environment/cwd differs')
 # h.namespace_proof uses the old base environment; preserve its mount/file
 # checks in preflight. Native binds the same plan and exact context above.
 if mode=='preflight':
  proof=h.namespace_proof(p,stage);g,_=h.helpers()
  actual=[h.c.pin(path) for path in g.runtime_api().linked(h.c.BINARY,expected)]
  need({r['path']:(r['sha256'],r['bytes']) for r in actual}=={r['path']:(r['sha256'],r['bytes']) for r in p['native_loader_dependencies']},'actual namespace loader differs')
  save(root/'preflight-result.json',{'status':'passed','proof':proof,'actual_environment':dict(os.environ),'actual_cwd':os.getcwd(),'loader_dependencies':actual,'native_runs':0});return 0
 need(mode=='native','unknown worker action')
 need(os.statvfs(cwd).f_flag & os.ST_RDONLY,'native original point directory is not readonly')
 for forbidden in p['forbidden_paths']:need(not Path(forbidden).exists(),'forbidden archive visible')
 arm=root/'arms'/ARM;need(set(q.relative_to(arm/'output').as_posix() for q in (arm/'output').rglob('*'))=={'native','native/2024-04-24'} and all(q.is_dir() and not q.is_symlink() for q in (arm/'output').rglob('*')),'native output not fresh')
 argv=[p['runtime']['native']['path'],p['profile']['path']]
 save(root/'native-exec-request.json',{'status':'verified_before_exec','argv':argv,'environment':expected,'actual_wrapper_environment':dict(os.environ),'cwd':cwd,'read_only_cwd_verified':True,'native':p['runtime']['native'],'source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'native_run_completed':False,'covariance_authority':False})
 os.execve(argv[0],argv,{**expected,'PWD':cwd})

def qualification_worker(source_sha):
 need(sys.flags.isolated and sys.flags.no_site and sys.flags.no_user_site and sys.flags.dont_write_bytecode,'isolated fixture worker required')
 h,a,_=helpers(source_sha);old=original();need(dict(os.environ)==parent_environment(old),'fixture environment differs')
 sys.path.insert(0,str(HERE/'reused/tests'));sys.path.insert(0,str(HERE/'reused'))
 forbidden=[]
 def guard(event,args):
  if event.startswith(('subprocess.','os.exec','os.spawn','os.posix_spawn','ctypes.')) or event in ('os.system','os.fork','os.forkpty','os.kill','os.killpg'):
   forbidden.append(event);raise RuntimeError('fixture process/FFI/signal blocked')
 sys.addaudithook(guard)
 suite=unittest.defaultTestLoader.discover(str(HERE/'reused/tests'),pattern='test_replay_inputs.py')
 def flatten(value):
  for test in value:
   if isinstance(test,unittest.TestSuite):yield from flatten(test)
   else:yield test.id()
 ids=sorted(flatten(suite));need(ids==(HERE/'reused/expected-test-ids.txt').read_text().splitlines() and len(ids)==3,'exact three fixtures required')
 result=unittest.TextTestRunner(verbosity=2).run(suite)
 passed=result.wasSuccessful() and not result.skipped and not result.expectedFailures and not result.unexpectedSuccesses and not forbidden
 save(ROOT/'qualification/result.json',{'status':'passed' if passed else 'failed','test_ids':ids,'tests':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skips':len(result.skipped),'forbidden_events':forbidden,'source_ledger_sha256':source_sha,'native_runs':0})
 return 0 if passed else 1

def previous_phase(h,review,action,source_sha,plan_sha):
 folder=ROOT/('qualification' if action=='qualify' else 'preflight-control')
 controller=review.get(action+'_controller');supervisor=review.get(action+'_supervisor')
 need(controller is not None and supervisor is not None,'actual previous controller/supervisor required')
 need(controller['path']==str(folder/'controller-result.json') and supervisor['path']==str(folder/'supervisor.json'),'previous phase belongs to foreign output')
 c=read(verify(controller));s=read(verify(supervisor));g,_=h.helpers()
 need(c['status']=='passed' and c['action']==action and c['source_ledger_sha256']==source_sha and c['plan_sha256']==plan_sha and c['source_input_runtime_posthash_verified'] is True and c['cleanup_verified'] is True,'previous phase incomplete')
 need(c['supervisor']==supervisor and s['status']=='complete' and s['returncode']==0 and g.cleanup_verified(s),'previous owned cleanup incomplete')

def run_phase(action,source_sha,plan_sha,review_path,review_sha):
 need(action in ('qualify','preflight','native'),'unknown admitted action')
 h,a,_=helpers(source_sha);old=original();need(dict(os.environ)==parent_environment(old),'parent environment differs')
 review=authority(review_path,review_sha,action,source_sha,plan_sha)
 need(plan_sha is not None,'actual prepared plan required');h,a,p=checked(source_sha,plan_sha)
 if action!='qualify':
  previous_phase(h,review,'qualify',source_sha,plan_sha)
  row=review.get('qualification_result');need(row is not None and row['path']==str(ROOT/'qualification/result.json'),'actual three-fixture result required');q=read(verify(row));need(q['status']=='passed' and q['tests']==3 and q['test_ids']==(HERE/'reused/expected-test-ids.txt').read_text().splitlines() and q['source_ledger_sha256']==source_sha and q['errors']==q['failures']==q['skips']==0 and q['forbidden_events']==[],'fixture result ineligible')
 if action=='native':
  previous_phase(h,review,'preflight',source_sha,plan_sha)
  row=review.get('preflight_freeze');need(row is not None and row['path']==str(ROOT/'preflight-freeze.json'),'actual preflight required');freeze=read(verify(row));need(freeze['plan_sha256']==plan_sha and freeze['source_ledger_sha256']==source_sha,'preflight belongs to different plan')
  for r in freeze['evidence']:verify(r)
  need(read(freeze['evidence'][0]['path'])['status']=='passed' and freeze['native_runs']==0,'preflight failed')
 h.admission();h.resource_admission(p);lock,lock_identity=h.shared_lock()
 stage={'qualify':'qualification','preflight':'preflight-control','native':'native-control'}[action];folder=ROOT/stage;folder.mkdir(exist_ok=False)
 receipt={'schema':'candidate07-local-fixed-profile-controller-v1','action':action,'status':'failed','source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'review':pin(review_path),'cooperative_lock':lock_identity,'covariance_authority':False,'release_authority':False};started=time.monotonic()
 try:
  checked(source_sha,plan_sha)
  python=p['runtime']['python']['path'];command=[python,'-I','-S','-B',str(HERE/'local_replay.py'),'_'+action,'--source-sha256',source_sha,'--plan-sha256',plan_sha]
  argv=command if action=='qualify' else namespace(h,a,p,'native' if action=='native' else 'preflight',command)
  argv=['/usr/bin/taskset','-c','4',*argv]
  save(folder/'command.json',{'argv':argv,'environment':parent_environment(old),'cwd':str(h.c.SOURCE),'source_ledger_sha256':source_sha,'plan_sha256':plan_sha})
  sys.path.insert(0,str(h.c.SOURCE/'src'));from orbit_poc.segmented.supervisor import run_owned
  seconds=600 if action=='native' else 300 if action=='qualify' else 1800
  result=run_owned(argv,python_executable=python,cwd=h.c.SOURCE,env=parent_environment(old),log_path=folder/'worker.log',receipt_path=folder/'supervisor.json',timeout_seconds=seconds,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=SCRATCH)
  receipt['supervisor']=pin(folder/'supervisor.json');receipt['supervisor_status']=result['status'];receipt['worker_returncode']=result['returncode'];receipt['worker_limit_seconds']=seconds
  g,_=h.helpers();receipt['cleanup_verified']=g.cleanup_verified(result)
  need(result['status']=='complete' and result['returncode']==0 and receipt['cleanup_verified'],'owned phase incomplete; preserve failure')
  if action=='qualify':need(read(ROOT/'qualification/result.json')['status']=='passed','fixture qualification failed')
  if action=='preflight':
   proof=ROOT/'prepared/preflight-result.json';need(read(proof)['status']=='passed','preflight proof missing')
   receipt['freeze']=save(ROOT/'preflight-freeze.json',{'plan_sha256':plan_sha,'source_ledger_sha256':source_sha,'native_runs':0,'evidence':[pin(proof),pin(folder/'supervisor.json'),pin(folder/'command.json')]})
  receipt['status']='native_completed_pending_independent_factor_audit' if action=='native' else 'passed'
 except BaseException as error:receipt.update(status='failed',error=repr(error),traceback=traceback.format_exc())
 finally:
  try:checked(source_sha,plan_sha);receipt['source_input_runtime_posthash_verified']=True
  except BaseException as error:receipt.update(status='failed',posthash_error=repr(error),source_input_runtime_posthash_verified=False)
  receipt['elapsed_seconds']=time.monotonic()-started
  if action=='native':receipt['all_output_files']=[pin(q) for q in sorted((ROOT/'cold-density/arms'/ARM/'output').rglob('*')) if q.is_file()]
  save(folder/'controller-result.json',receipt);lock.close()
 return 0 if receipt['status'] in ('passed','native_completed_pending_independent_factor_audit') else 1

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','qualify','preflight','native','_qualify','_preflight','_native'));p.add_argument('--source-sha256',required=True);p.add_argument('--plan-sha256');p.add_argument('--review');p.add_argument('--review-sha256');args=p.parse_args()
 if args.action=='_qualify':return qualification_worker(args.source_sha256)
 if args.action.startswith('_'):return worker(args.action[1:],args.source_sha256,args.plan_sha256)
 need(args.review and args.review_sha256,'actual independent action review required')
 if args.action=='prepare':prepare(args.source_sha256,Path(args.review),args.review_sha256);return 0
 return run_phase(args.action,args.source_sha256,args.plan_sha256,Path(args.review),args.review_sha256)

if __name__=='__main__':raise SystemExit(main())
