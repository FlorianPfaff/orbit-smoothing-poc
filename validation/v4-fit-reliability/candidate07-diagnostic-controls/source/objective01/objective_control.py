"""One ordinary archived physical proposal evaluation; no optimizer or retry."""
from pathlib import Path
import argparse, copy, hashlib, importlib.util, json, os, shutil, sys, time

HERE=Path(__file__).absolute().parent
BASE=Path('/mnt/d/orbit-v41-recovery02')
ROOT=BASE/'candidate07-density04-undamped-objective-probe-run01'
SCRATCH=Path('/home/emper/orbit-density04-undamped-objective-probe01')
SOURCE=BASE/'candidate07-density04-undamped-objective-probe01/preparation01'
SOURCE_SHA='754967b72939e921f0eafcb98766c1daa514bf8ae1e512c49dbe9f77518a3cef'
OLD=BASE/'density-trial-cold-controls04'
OLD_SHA='2bef971aaa46668bff5a09aa025e3b2ff2970a0b0e1e0c51540a8239789fa457'
ORIGINAL=BASE/'candidate07-cold-density04/plan.json'
ORIGINAL_SHA='530221cae291e0689cdd5dce62deca1b18f27ad0682553c8e9d5ced11504cafb'
REPLAY=BASE/'candidate07-density04-local-fixed-replay-run01'
REPLAY_PLAN_SHA='8ca6a619781418ad2ee44577ec4001fa3f6c2b4240d77b1c280ce51425bc79a3'
FIXTURES=BASE/'candidate07-density04-undamped-probe-fixtures01'
FIXTURE_SOURCE=BASE/'candidate07-density04-undamped-probe-fixture-controls01/preparation01'
FIXTURE_SHA='96a3b683a5c1d90cfa10d35818f8718a0388933bf57159a8f82960cf1277c660'
SUPERVISOR_SHA='060bc208a5d36631689905563c9e969ae4615299e39e87637f71393b62eed267'
SCHEMA='candidate07-undamped-objective-plan-v1'
LIMITS={'objective_seconds':900,'preflight_seconds':1800,'rss_bytes':8*1024**3,'cpu':4,'threads':1}

def need(value,message):
 if not value:raise ValueError(message)
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1048576),b''):h.update(b)
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
def helpers(source_sha,inside=False):
 own=ledger(HERE,'inputs.sha256',source_sha);probe=ledger(SOURCE,'inputs.sha256',SOURCE_SHA)
 if not inside:ledger(OLD,'source.sha256',OLD_SHA)
 for name,digest in {'one_hour_controls.py':'a968d8b3f312ccd0f4f62965a30dafb0cd76564cdd72bf678af73ec4bf02fc1d','contracts.py':'3695978cfc22078df08e1dd7f8cb50e04b72dd4516986d13a5067f46dfb7b61d','archived_reference.py':'4739b1bf52b0fb74587b01df5ee23d48a3f86ec5cada54874cb610a6a844a4fe'}.items():need(sha(OLD/name)==digest,'local helper changed')
 sys.path.insert(0,str(OLD));h=load(OLD/'one_hour_controls.py','objective_cold_helpers')
 return h,load(SOURCE/'probe.py','archived_undamped_probe'),own,probe
def original():
 need(sha(ORIGINAL)==ORIGINAL_SHA,'original plan changed');p=read(ORIGINAL)
 need(p['runtime']['native']['sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d' and len(p['native_loader_dependencies'])==14,'wrong native runtime')
 return p
def parent_environment(old):
 return {k:v for k,v in old['jobs'][0]['environment'].items() if k not in {'ORBIT_POC_GNSS_DESIGN_SCRATCH','ORBIT_POC_NUMERICS_SPOOL_DIRECTORY','TMPDIR','TMP','TEMP'}}
def runtime_check(h,p,inside=False):
 h.verify_files(p['bindings'],inside=inside);h.verify_directory_membership(p,inside=inside)
 for row in p['native_loader_dependencies']:h.c.verify(row)
 need(sha(h.c.SOURCE/'src/orbit_poc/segmented/supervisor.py')==SUPERVISOR_SHA,'supervisor changed')
def clean(h,s):
 g,_=h.helpers();return g.cleanup_verified(s) and s['cleanup']['empty_tree_certificate']=='kernel_ECHILD' and s['cleanup']['remaining']==[]
def prerequisites(h,r):
 # Actual terminal attribution may be success or failure; neither is invented.
 x=r['local600_terminal'];c=read(verify(x['controller']));s=read(verify(x['supervisor']));a=read(verify(x['audit']))
 need(x['controller']['path']==str(REPLAY/'native-control/controller-result.json') and x['supervisor']['path']==str(REPLAY/'native-control/supervisor.json'),'wrong replay attempt')
 need(c['action']=='native' and c['plan_sha256']==REPLAY_PLAN_SHA and c['source_ledger_sha256']=='e781713a5c2e3556cfac4d9bb7682656527411a66a9143ffa0a01f5703f9b092' and c['status'] in ('failed','native_completed_pending_independent_factor_audit') and c['source_input_runtime_posthash_verified'] is True and c['cleanup_verified'] is True and c['supervisor']==x['supervisor'] and clean(h,s),'local600 has no clean closed attribution')
 need(a['schema']=='undamped-probe-local600-terminal-review-v1' and a['controller']==x['controller'] and a['supervisor']==x['supervisor'] and a['terminal_attribution_verified'] is True and a['owned_processes_absent'] is True,'independent local600 terminal/absence audit required')
 need(sha(REPLAY/'plan.json')==REPLAY_PLAN_SHA,'replay plan changed')
 x=r['five_fixture_qualification'];c=read(verify(x['controller']));s=read(verify(x['supervisor']));f=read(verify(x['worker']))
 need(x['controller']['path']==str(FIXTURES/'result.json') and x['supervisor']['path']==str(FIXTURES/'supervisor.json') and x['worker']['path']=='/home/emper/orbit-density04-undamped-probe-fixtures01/fixture-result.json','wrong fixture attempt')
 ledger(FIXTURE_SOURCE,'inputs.sha256',FIXTURE_SHA)
 need(c['status']=='passed' and c['source_runtime_unchanged'] is True and c['cleanup_verified'] is True and c['supervisor']==x['supervisor'] and c['fixture_result']==x['worker'] and s['status']=='complete' and s['returncode']==0 and clean(h,s),'fixture control incomplete')
 ids=(SOURCE/'expected-test-ids.txt').read_text().splitlines()
 need(f['status']=='passed' and f['expected_ids']==ids and sorted(f['started_ids'])==sorted(ids) and sorted(f['success_ids'])==sorted(ids) and f['tests_run']==5 and all(f[k]==[] for k in ('failures','errors','skips','expected_failures','unexpected_successes','forbidden_events')) and f['source_control_bytes_unchanged'] is True,'exact five fixtures not passed')
 p=read(verify(c['plan']));need(p['control_ledger']['sha256']==FIXTURE_SHA and p['probe_ledger']['sha256']==SOURCE_SHA,'fixture source attribution differs')
 return {'local600_terminal':r['local600_terminal'],'five_fixture_qualification':r['five_fixture_qualification']}
def authority(h,path,digest,action,source_sha,plan_sha=None):
 need(sha(path)==digest,'action review changed');r=read(path)
 need(r['schema']=='candidate07-undamped-objective-action-review-v1' and r['approved_actions']==[action] and r['source_ledger_sha256']==source_sha and r['plan_sha256']==plan_sha and r['limits']==LIMITS and r['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'wrong action/source/plan/boot scope')
 prerequisites(h,r)
 for row in r.get('evidence',[]):verify(row)
 return r
def baseline(probe):
 need(sha(HERE/'baseline-inputs.json')=='11e32a478bc631a48b103f95c8f2ae3f9c83a67935d7bca711f49a62e6f5d019','baseline manifest changed')
 items=read(HERE/'baseline-inputs.json')['inputs'];need(len(items)==4,'baseline receipt count changed')
 rows={r['role']:{k:r[k] for k in ('path','sha256','bytes')} for r in items}
 for row in rows.values():verify(row)
 profile=read(rows['strict_nuisance_profile']['path']);confirmation=read(rows['fresh_full_nuisance_confirmation']['path']);probe.strict_profile(profile,confirmation)
 closure=read(rows['physical_closure']['path']);first=read(rows['initial_trial_objective_floor']['path'])['history'][0]
 b=probe.bind_archived_proposal()
 need(closure['converged'] is True and closure['tighter'] is True and first['objective_floor']==b['baseline_archived_floor'] and first['objective_before']==b['baseline_objective'] and confirmation['objective_before']==b['baseline_objective'],'archived baseline attribution differs')
 return rows,b

def prepare(source_sha,review_path,review_sha):
 h,probe,own,source=helpers(source_sha);old=original();r=authority(h,review_path,review_sha,'prepare',source_sha)
 need(dict(os.environ)==parent_environment(old),'parent environment changed');h.admission();lock,_=h.shared_lock()
 try:
  runtime_check(h,old);base,b=baseline(probe)
  need(not os.path.lexists(ROOT) and not os.path.lexists(SCRATCH),'preserve previous attempt')
  ROOT.mkdir();SCRATCH.mkdir(mode=0o700);_,legacy=h.helpers();filesystem=legacy.disk_filesystem(SCRATCH)
  for stage in ('prepared','cold-density'):
   (ROOT/stage).mkdir();(SCRATCH/stage).mkdir(mode=0o700)
   for leaf in ('tmp','scratch','row-spool','legacy-output','fit'):(ROOT/stage/leaf).mkdir();(SCRATCH/stage/leaf).mkdir(mode=0o700)
  (ROOT/'frozen').mkdir();request=ROOT/'frozen/request.json';request.write_bytes(probe.REQUEST.read_bytes())
  copied=save(ROOT/'frozen/request-copy.json',{'original':pin(probe.REQUEST),'copy':pin(request),'request_bytes_changed':False,'only_output_namespace_is_new':True})
  physical=save(ROOT/'frozen/physical-binding.json',b);rows={r['target']:dict(r) for r in old['bindings']}
  additions=[*own.values(),*source.values(),pin(HERE/'inputs.sha256'),pin(SOURCE/'inputs.sha256'),pin(request),copied,physical,pin(ORIGINAL),*base.values()]
  additions += [pin(row['path']) for row in b['archived_inputs']]
  for row in additions:h.add_binding(rows,row['path'],row['path'],'undamped_probe_input',row['sha256'])
  with (ROOT/'python-runtime.json').open('xb') as f:f.write(verify(old['python_runtime']).read_bytes())
  job={'stage':'cold-density','directory':str(ROOT/'cold-density'),'scratch':str(SCRATCH/'cold-density'),'request':pin(request),'rebinding':copied,'environment':h.environment(ROOT/'cold-density')}
  p={'schema':SCHEMA,'output':str(ROOT),'scratch_root':str(SCRATCH),'runtime':old['runtime'],'python_runtime':pin(ROOT/'python-runtime.json'),'native_loader_dependencies':old['native_loader_dependencies'],'bindings':sorted(rows.values(),key=lambda x:x['target']),'directory_bindings':copy.deepcopy(old['directory_bindings']),'originals':{},'jobs':[job],'prepared':old['prepared'],'forbidden_paths':h.FORBIDDEN+[str(probe.POINT/'qr.74.R.bin'),str(probe.POINT/'profile.log')],'source_ledger_sha256':source_sha,'source_members':own,'probe_members':source,'original_plan':pin(ORIGINAL),'physical_binding':physical,'baseline_receipts':base,'prerequisites':prerequisites(h,r),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'limits':LIMITS,'scratch_filesystem':filesystem,'physical_optimization':False,'physical_evaluations':1,'ordinary_tighter':False,'covariance_authority':False,'release_authority':False,'fit_projection':{'logical':str(ROOT/'cold-density/fit'),'backing':str(SCRATCH/'cold-density/fit')}}
  # All consumed input/control/native files plus the complete small scientific
  # source are repeated inside; the full Python envelope is checked separately.
  p['worker_binding_targets']=[x['target'] for x in p['bindings'] if x['role']!='runtime_member' or Path(x['target']).is_relative_to(h.c.SOURCE)]
  p['owned_directories']=[h.c.directory_identity(q) for q in [ROOT,SCRATCH,ROOT/'frozen',*(ROOT/s for s in ('prepared','cold-density')),*(SCRATCH/s for s in ('prepared','cold-density')),*(SCRATCH/s/leaf for s in ('prepared','cold-density') for leaf in ('tmp','scratch','row-spool','legacy-output','fit'))]]
  h.resource_admission(p);save(ROOT/'plan.json',p);runtime_check(h,old);ledger(HERE,'inputs.sha256',source_sha)
  return p
 finally:lock.close()

def checked(source_sha,plan_sha,inside=False,finite=False):
 h,probe,own,source=helpers(source_sha,inside);path=ROOT/'plan.json';need(sha(path)==plan_sha,'plan changed');p=read(path)
 need(p['schema']==SCHEMA and p['source_ledger_sha256']==source_sha and p['source_members']==own and p['probe_members']==source and p['output']==str(ROOT) and p['scratch_root']==str(SCRATCH) and p['limits']==LIMITS and p['physical_evaluations']==1 and p['physical_optimization'] is False and p['ordinary_tighter'] is False and p['covariance_authority'] is False and p['release_authority'] is False,'plan scope differs')
 need(p['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'new boot requires fresh review')
 verify(p['original_plan']);need(p['original_plan']['sha256']==ORIGINAL_SHA,'wrong original plan')
 base,b=baseline(probe);need(base==p['baseline_receipts'] and read(verify(p['physical_binding']))==b,'physical binding changed')
 verify(p['python_runtime']);job=p['jobs'][0];verify(job['request']);verify(job['rebinding'])
 need(len(p['jobs'])==1 and job['stage']=='cold-density' and read(job['request']['path'])==read(probe.REQUEST) and job['environment']==h.environment(ROOT/'cold-density'),'request/environment changed')
 if finite:
  expected=[x['target'] for x in p['bindings'] if x['role']!='runtime_member' or Path(x['target']).is_relative_to(h.c.SOURCE)]
  need(p['worker_binding_targets']==expected,'finite consumed-byte selection changed')
  selected=set(expected);h.verify_files([x for x in p['bindings'] if x['target'] in selected],inside=True)
  for row in p['native_loader_dependencies']:h.c.verify(row)
 else:runtime_check(h,p,inside)
 if not inside:
  need(prerequisites(h,p['prerequisites'])==p['prerequisites'],'prerequisite evidence changed')
  for row in p['owned_directories']:h.c.verify_directory_identity(row)
  _,legacy=h.helpers();need(legacy.disk_filesystem(SCRATCH)==p['scratch_filesystem'],'scratch filesystem changed')
 need(sha(path)==plan_sha,'plan changed during verification');return h,probe,p

def namespace(h,p,argv):
 args=h.namespace(p,'cold-density',argv)
 original=['--bind',str(SCRATCH/'cold-density/row-spool'),str(ROOT/'cold-density/fit/row-spool')]
 indexes=[i for i in range(len(args)-2) if args[i:i+3]==original];need(len(indexes)==1,'original spool mount differs')
 del args[indexes[0]:indexes[0]+3]
 i=args.index('--proc');args[i:i]=['--bind',str(SCRATCH/'cold-density/fit'),str(ROOT/'cold-density/fit')]
 return args

def worker(mode,source_sha,plan_sha):
 need(sys.flags.no_user_site and sys.flags.dont_write_bytecode,'qualified scientific bootstrap required')
 h,probe,p=checked(source_sha,plan_sha,inside=True,finite=(mode=='evaluate'));stage=ROOT/'cold-density'
 need(dict(os.environ)=={**h.environment(stage),'PWD':str(h.c.SOURCE)} and os.getcwd()==str(h.c.SOURCE) and os.sched_getaffinity(0)=={4},'actual worker context differs')
 selected=set(p['worker_binding_targets'])
 proof_plan=p if mode=='preflight' else {**p,'bindings':[x for x in p['bindings'] if x['target'] in selected]}
 proof=h.namespace_proof(proof_plan,'cold-density')
 proof['verification_scope']='full_preflight' if mode=='preflight' else 'finite_consumed_files_after_separate_full_preflight'
 sys.path.insert(0,str(h.c.SOURCE/'src'))
 if mode=='preflight':
  from orbit_poc.comparison import backend as native
  from orbit_poc.comparison.groops_config import build_fit_configs
  import numpy,scipy,psutil
  g,_=h.helpers();actual=[h.c.pin(path) for path in g.runtime_api().linked(h.c.BINARY,h.environment(stage))]
  need({r['path']:(r['sha256'],r['bytes']) for r in actual}=={r['path']:(r['sha256'],r['bytes']) for r in p['native_loader_dependencies']},'namespace loader differs')
  prep=native._preparation(read(p['jobs'][0]['request']['path']));target=stage/'preflight-native';native._private_data(prep,target);config=build_fit_configs(prep,target,'groops_log_drag_ou',read(probe.REQUEST)['parameters'])
  import xml.etree.ElementTree as ET
  outputs=list(config['result_paths'].values())
  outputs += [node.text for path in config['configs'].values() for node in ET.parse(path).iter() if node.tag.lower().startswith('outputfile') and node.text]
  need(all(Path(x).is_relative_to(target) and '..' not in Path(x).parts for x in outputs),'preflight output escapes private root')
  need(not any((stage/'fit').iterdir()),'preflight touched the future fit')
  save(stage/'preflight-result.json',{'status':'passed','proof':proof,'actual_environment':dict(os.environ),'actual_cwd':os.getcwd(),'loader_dependencies':actual,'private_outputs':outputs,'source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'native_runs':0});return 0
 need(mode=='evaluate','unknown worker action')
 from orbit_poc.numerics.backend import NativeModel
 need(not any((stage/'fit').iterdir()),'preserve previous objective output');report={'status':'failed','source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'covariance_authority':False,'release_authority':False}
 try:
  model=NativeModel(read(p['jobs'][0]['request']['path']),stage/'fit')
  result=probe.evaluate_bound_probe(model,read(p['physical_binding']['path']))
  report.update(objective_result=pin(stage/'fit/probe-result.json'),objective_status=result['status'],objective_qualified=result['objective_qualified'])
  need(result['objective_qualified'] is True and result['status']=='strict_fixed_point_evaluated' and model.sequence==1,'one strictly profiled ordinary objective not obtained')
  report['status']='evaluated_pending_independent_audit'
 except BaseException as error:report['error']=repr(error)
 finally:save(stage/'objective-worker-result.json',report)
 return 0 if report['status']=='evaluated_pending_independent_audit' else 1

def run_phase(action,source_sha,plan_sha,review_path,review_sha):
 need(action in ('preflight','evaluate'),'unsupported phase');h,probe,p=checked(source_sha,plan_sha);r=authority(h,review_path,review_sha,action,source_sha,plan_sha)
 need(p['prerequisites']==prerequisites(h,r),'prerequisite attribution changed')
 if action=='evaluate':
  freeze=read(verify(r['preflight_freeze']));c=read(verify(r['preflight_controller']));s=read(verify(r['preflight_supervisor']))
  need(r['preflight_freeze']['path']==str(ROOT/'preflight-freeze.json') and r['preflight_controller']['path']==str(ROOT/'preflight-control/controller-result.json') and r['preflight_supervisor']['path']==str(ROOT/'preflight-control/supervisor.json'),'wrong preflight')
  need(freeze['plan_sha256']==plan_sha and freeze['source_ledger_sha256']==source_sha and c['status']=='passed' and c['plan_sha256']==plan_sha and c['source_ledger_sha256']==source_sha and c['source_input_runtime_posthash_verified'] is True and c['cleanup_verified'] is True and c['supervisor']==r['preflight_supervisor'] and s['status']=='complete' and s['returncode']==0 and clean(h,s),'preflight incomplete')
  for row in freeze['evidence']:verify(row)
  need(read(freeze['evidence'][0]['path'])['status']=='passed','preflight worker failed')
 need(dict(os.environ)==parent_environment(original()),'parent environment changed');h.admission();lock,lock_identity=h.shared_lock();folder=ROOT/(action+'-control');folder.mkdir()
 receipt={'schema':'candidate07-undamped-objective-controller-v1','action':action,'status':'failed','source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'review':pin(review_path),'cooperative_lock':lock_identity,'covariance_authority':False,'release_authority':False};start=time.monotonic()
 try:
  h.resource_admission(p);h.admission();python=p['runtime']['python']['path']
  command=[python,'-s','-B',str(HERE/'objective_control.py'),'_'+action,'--source-sha256',source_sha,'--plan-sha256',plan_sha]
  argv=['/usr/bin/taskset','-c','4',*namespace(h,p,command)];save(folder/'command.json',{'argv':argv,'worker_limit_seconds':LIMITS['preflight_seconds' if action=='preflight' else 'objective_seconds'],'no_optimizer':True})
  sys.path.insert(0,str(h.c.SOURCE/'src'));from orbit_poc.segmented.supervisor import run_owned
  s=run_owned(argv,python_executable=python,cwd=h.c.SOURCE,env=parent_environment(original()),log_path=folder/'worker.log',receipt_path=folder/'supervisor.json',timeout_seconds=LIMITS['preflight_seconds' if action=='preflight' else 'objective_seconds'],max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=SCRATCH)
  receipt.update(supervisor=pin(folder/'supervisor.json'),supervisor_status=s['status'],worker_returncode=s['returncode'],cleanup_verified=clean(h,s))
  need(s['status']=='complete' and s['returncode']==0 and clean(h,s),'failed, interrupted or incomplete owned worker')
  if action=='preflight':
   proof=ROOT/'cold-density/preflight-result.json';need(read(proof)['status']=='passed','preflight evidence missing')
   receipt['freeze']=save(ROOT/'preflight-freeze.json',{'source_ledger_sha256':source_sha,'plan_sha256':plan_sha,'native_runs':0,'evidence':[pin(proof),pin(folder/'supervisor.json'),pin(folder/'command.json')]});receipt['status']='passed'
  else:
   out=ROOT/'cold-density/objective-worker-result.json';q=read(out);need(q['status']=='evaluated_pending_independent_audit' and q['objective_qualified'] is True,'objective ineligible')
   backing=SCRATCH/'cold-density/fit/probe-result.json';need(q['objective_result']['path']==str(ROOT/'cold-density/fit/probe-result.json') and q['objective_result']['sha256']==sha(backing),'logical/backing result attribution differs')
   receipt.update(status='evaluated_pending_independent_audit',worker=pin(out),objective_result_backing=pin(backing),fit_projection=p['fit_projection'])
 except BaseException as error:receipt['error']=repr(error)
 finally:
  try:checked(source_sha,plan_sha);receipt['source_input_runtime_posthash_verified']=True
  except BaseException as error:receipt.update(status='failed',posthash_error=repr(error),source_input_runtime_posthash_verified=False)
  receipt['elapsed_seconds']=time.monotonic()-start;save(folder/'controller-result.json',receipt);lock.close()
 return 0 if receipt['status'] in ('passed','evaluated_pending_independent_audit') else 1

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','preflight','evaluate','_preflight','_evaluate'));p.add_argument('--source-sha256',required=True);p.add_argument('--plan-sha256');p.add_argument('--review');p.add_argument('--review-sha256');a=p.parse_args()
 if a.action.startswith('_'):return worker(a.action[1:],a.source_sha256,a.plan_sha256)
 need(a.review and a.review_sha256,'actual action review required')
 if a.action=='prepare':prepare(a.source_sha256,Path(a.review),a.review_sha256);return 0
 return run_phase(a.action,a.source_sha256,a.plan_sha256,Path(a.review),a.review_sha256)
if __name__=='__main__':raise SystemExit(main())
