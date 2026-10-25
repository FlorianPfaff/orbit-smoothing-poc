"""Prepare, independently approve and run two isolated original cold full fits.

No native computation occurs in prepare/preflight. Only an explicit reviewed
launch invokes the unchanged candidate04 full nonlinear backend.
"""
from __future__ import annotations
import argparse, copy, datetime, fcntl, hashlib, importlib.util, json, os, signal, subprocess, sys, time, traceback, shutil, stat
from pathlib import Path
import contracts as c

HERE=Path(__file__).absolute().parent
GATES=c.BASE/'validation-controls07/reference_gates09.py'
GATES_SHA='c60a79be9e4fb048035b448c6edfc1e58ea4ceff9c40087bd7927f97d3c4ddd7'
LEGACY=c.SOURCE/'scripts/run_v41_wholefit_regressions.py'
LEGACY_SHA='92343a79f27212464a59f30006e6f09ec0a3b7366367a4566a3a2c31c26a1ef4'
SCHEMA='orbit-poc-one-hour-cold-plan-v1'
PINNED_NATIVE=c.NATIVE_SHA
FORBIDDEN=[
 '/mnt/d/orbit-numerics-v3.1/engineering-archive/development-fits-07',
 '/mnt/d/orbit-numerics-v3.1-artifacts/engineering/objective-validation-near-03',
 '/mnt/d/orbit-segmented-v4', '/mnt/d/orbit-nuisance-warmstarts',
 '/mnt/d/orbit-v41-recovery02/reference-gates14-run01',
 '/mnt/seagate10tb/orbit-segmented-v4-florianpfaff',
 '/mnt/c/users/emper/documents/codex/2026-10-13/i-x20/work/v3/synthetic-tudat-smoke/truth.npz',
 '/mnt/c/Users/emper/Codex/2026-10-13/i-x20/work/v3/synthetic-tudat-smoke/truth.npz']

def load(path,digest,name):
 c.verify({'path':str(path),'sha256':digest});sp=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(sp);sys.modules[name]=m;exec(compile(Path(path).read_bytes(),str(path),'exec'),m.__dict__);return m

def helpers():return load(GATES,GATES_SHA,'_one_hour_reference'),load(LEGACY,LEGACY_SHA,'_one_hour_legacy')
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def pins():return [c.pin(p) for p in sorted(HERE.glob('*.py'))]
def source_identity():return c.canonical(c.read(c.SOURCE.parent/'source-snapshot.json')['files'])
def environment(stage):
 g,_=helpers();d=g.base_env();d.pop('PYTHONPATH',None)
 d.update(PYTHONPATH=str(c.SOURCE/'src'),TMPDIR=str(Path(stage)/'tmp'),TMP=str(Path(stage)/'tmp'),TEMP=str(Path(stage)/'tmp'),ORBIT_POC_GNSS_DESIGN_SCRATCH=str(Path(stage)/'scratch'),ORBIT_POC_NUMERICS_SPOOL_DIRECTORY=str(Path(stage)/'fit/row-spool'))
 return d

def validate_environment(expected,actual):
 c.require(all(actual.get(k)==v for k,v in expected.items()),'Whitelisted environment changed')
 c.require(not any(k.startswith(('ORBIT_POC_','LD_','PYTHON')) and k not in expected for k in actual),'Unexpected numerical/runtime environment')

def add_binding(rows,host,target,role,digest=None):
 host=Path(host);target=Path(target)
 c.require(host.is_file() and target.is_absolute() and '..' not in target.parts,'Invalid file binding')
 row={'host':str(host),'target':str(target),'sha256':digest or c.sha(host),'bytes':host.stat().st_size,'role':role}
 c.require(c.sha(host)==row['sha256'],'Binding bytes differ: '+str(host))
 if str(target) in rows:c.require(rows[str(target)]['sha256']==row['sha256'],'Conflicting binding')
 else:rows[str(target)]=row

def build_bindings(base,originals):
 rows={};pool={}
 for row in base['pins']+[x['source'] for x in base['aliases']]:pool.setdefault(row['sha256'],row['path'])
 for ov in base['directory_overlays']:
  for row in c.read(ov['inventory']['path'])['entries']:
   if row['kind']=='file':pool.setdefault(row['sha256'],str(Path(ov['source'])/row['relative']))
 prepareds=[]
 for request in originals.values():
  for row in request['estimation_inputs']:
   host=row['path'] if Path(row['path']).is_file() else pool.get(row['sha256'])
   c.require(host,'No verified input backing: '+row['path']);add_binding(rows,host,row['path'],'estimation:'+row['role'],row['sha256'])
   if row.get('metadata',{}).get('kind')=='native_preparation':prepareds.append(c.read(host))
 c.require(prepareds and all(x==prepareds[0] for x in prepareds),'The two methods no longer share preprocessing')
 prep=prepareds[0]
 c.require(prep['metadata']['reference_inputs_used'] is False and prep['metadata']['bootstrap_provenance']=='gnss_only','Preparation is not GNSS-only')
 for row in prep['native_artifacts']:
  host=row['path'] if Path(row['path']).is_file() else pool.get(row['sha256'])
  c.require(host,'No verified native input backing: '+row['path']);add_binding(rows,host,row['path'],'native:'+row['role'],row['sha256'])
 # Reconstructed frozen data is bound at its original logical target using files.
 wanted=str(Path(prep['output_dir'])/'data');ov=next(x for x in base['directory_overlays'] if x['target']==wanted)
 for row in c.read(ov['inventory']['path'])['entries']:
  if row['kind']=='file':add_binding(rows,Path(ov['source'])/row['relative'],Path(wanted)/row['relative'],'prepared_data',row['sha256'])
 for key,expected in [('orbit',c.NOMINAL_SHA)]:
  c.require(rows[prep['native_paths'][key]]['sha256']==expected,'Original nominal initialization chain changed')
 c.require(any(x['sha256']==c.INITIAL_SHA for x in rows.values()),'Original fixed initial state absent')
 return sorted(rows.values(),key=lambda x:x['target']),prep

def runtime_bindings(base):
 rt=c.read(base['python_runtime']['path']);rows={};directories=[]
 for tree in rt['trees']:
  if str(tree['root']).startswith(str(c.SOURCE)) and Path(tree['root']).name=='scripts':continue
  directories.append({'host':tree['root'],'target':tree['root'],'role':'pinned_runtime_tree','inventory':tree})
  for row in tree['entries']:
   if row['kind']=='file':rows[row['path']]={'host':row['path'],'target':row['path'],'sha256':row['sha256'],'bytes':row['bytes'],'role':'runtime_member'}
 for row in rt['files']:
  rows[row['path']]={'host':row['path'],'target':row['path'],'sha256':row['sha256'],'bytes':row['bytes'],'role':'runtime_file'}
 for part in ['configs','groops/templates']:
  directory=c.SOURCE/part;g,_=helpers();directories.append({'host':str(directory),'target':str(directory),'role':'native_configuration_source','inventory':g.runtime_api().tree(directory)})
  for f in sorted(directory.rglob('*')):
   if f.is_file():
    expected={r['relative_path']:r['sha256'] for r in c.read(c.SOURCE.parent/'source-snapshot.json')['files']}[str(f.relative_to(c.SOURCE))]
    add_binding(rows,f,f,'source_configuration',expected)
 # Native loader libraries are among the verified reference plan pins.
 for row in base['pins']:
  if '/lib/' in row['path'] or row['path'].endswith(('.so.0','.so.1','.so.5','.so.6','.so.2')):
   add_binding(rows,row['path'],row['path'],'native_library',row['sha256'])
 add_binding(rows,c.BINARY,c.BINARY,'native_binary',PINNED_NATIVE)
 add_binding(rows,str(c.BINARY)+'.build-manifest.json',str(c.BINARY)+'.build-manifest.json','native_build_manifest')
 return rows,directories

def verify_files(rows,*,inside=False):
 for row in rows:
  path=Path(row['target'] if inside else row['host'])
  c.require(path.is_file() and path.stat().st_size==row['bytes'] and c.sha(path)==row['sha256'],'Bound bytes changed: '+str(path))


def normalized_tree(tree):
 return {'excluded':tree['excluded'],'entries':[{k:v for k,v in row.items() if k not in ('path','resolved')} for row in tree['entries']]}

def verify_directory_membership(plan,*,inside=False):
 g,_=helpers();api=g.runtime_api()
 for row in plan['directory_bindings']:
  target=row['target'] if inside else row['host'];actual=api.tree(target,row['inventory']['excluded'])
  c.require(normalized_tree(actual)==normalized_tree(row['inventory']),'Readonly runtime/source tree membership or bytes changed: '+target)
 return True

def prepare(output,scratch_root):
 output=Path(output).absolute();scratch_root=Path(scratch_root).absolute()
 c.require(output.parent==c.BASE and not output.exists() and not output.is_symlink(),'Output must be a fresh direct recovery child')
 c.require(scratch_root.parent==Path('/home/emper') and not scratch_root.exists() and scratch_root.resolve()==scratch_root,'Scratch must be a fresh /home/emper child')
 g,legacy=helpers();base=g.checked_plan(c.REFERENCE_PLAN,c.REFERENCE_PLAN_SHA)
 originals={s:c.original_request(s,Path(c.REQUESTS[s]['path']).read_bytes()) for s in c.CASES}
 bindings,prep=build_bindings(base,originals);rt,dirs=runtime_bindings(base)
 loader=[];known={r['sha256'] for r in [*base['pins'],*rt.values()]}
 for path in g.runtime_api().linked(c.BINARY,g.base_env()):
  item=c.pin(path);c.require(item['sha256'] in known,'Native loader selected an unpinned dependency: '+path);loader.append(item);add_binding(rt,path,path,'native_loader_dependency',item['sha256'])
 for row in bindings:
  if row['target'] in rt:c.require(rt[row['target']]['sha256']==row['sha256'],'Input/runtime conflict')
  rt[row['target']]=row
 output.mkdir();scratch_root.mkdir(mode=0o700)
 filesystem=legacy.disk_filesystem(scratch_root)
 sourcehash=source_identity();jobs=[]
 for stage in ('prepared',*c.CASES):
  root=output/stage;root.mkdir();backing=scratch_root/stage;backing.mkdir(mode=0o700)
  for leaf in ['tmp','scratch','row-spool','legacy-output']:(root/leaf).mkdir();(backing/leaf).mkdir(mode=0o700)
  if stage=='prepared':continue
  raw=Path(c.REQUESTS[stage]['path']).read_bytes();req,journal=c.rebind(stage,raw,sourcehash)
  c.save(root/'request.json',req);c.save(root/'rebinding.json',{'stage':stage,'original':c.pin(c.REQUESTS[stage]['path']),'journal':journal,'scientific_settings_unchanged':True,'initial_override':False,'nuisance_donor':False})
  jobs.append({'stage':stage,'directory':str(root),'scratch':str(backing),'request':c.pin(root/'request.json'),'rebinding':c.pin(root/'rebinding.json'),'environment':environment(root),'original_request':c.pin(c.REQUESTS[stage]['path'])})
 # Original case requests are copied to a readonly, non-estimator control location.
 (output/'originals').mkdir()
 for stage in c.CASES:(output/'originals'/f'{stage}.json').write_bytes(Path(c.REQUESTS[stage]['path']).read_bytes())
 originals_pins={stage:c.pin(output/'originals'/f'{stage}.json') for stage in c.CASES}
 helper_pins=[c.pin(GATES),c.pin(LEGACY),*[dict(row) for row in base['pins'] if '/validation-controls07/' in row['path'] and row['path'].endswith('.py')]]
 for row in [*pins(),*helper_pins]:add_binding(rt,row['path'],row['path'],'new_control' if Path(row['path']).parent==HERE else 'pinned_control_helper',row['sha256'])
 c.save(output/'python-runtime.json',c.read(base['python_runtime']['path']))
 plan={'schema':SCHEMA,'created_at':now(),'output':str(output),'scratch_root':str(scratch_root),'scratch_filesystem':filesystem,'scratch_identities':{s:{'device':(scratch_root/s).stat().st_dev,'inode':(scratch_root/s).stat().st_ino,'uid':(scratch_root/s).stat().st_uid} for s in ('prepared',*c.CASES)},'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'stages':list(c.CASES),'limits':c.LIMITS,'jobs':jobs,'runtime':base['runtime'],'native_loader_dependencies':loader,'source_identity':sourcehash,'source_snapshot':c.pin(c.SOURCE.parent/'source-snapshot.json'),'reference_plan':c.pin(c.REFERENCE_PLAN),'control_pins':pins(),'helper_pins':helper_pins,'originals':originals_pins,'bindings':sorted(rt.values(),key=lambda x:x['target']),'directory_bindings':dirs,'python_runtime':c.pin(output/'python-runtime.json'),'prepared':{'output_dir':prep['output_dir'],'native_paths':prep['native_paths'],'nominal_initialization':prep['nominal_initialization']},'forbidden_paths':FORBIDDEN,'scratch_leaf_identities':{str(q):{'device':q.stat().st_dev,'inode':q.stat().st_ino,'uid':q.stat().st_uid} for s in ('prepared',*c.CASES) for q in [scratch_root/s/leaf for leaf in ['tmp','scratch','row-spool','legacy-output']]},'cold_start':True,'initialization':'Unchanged NativeModel.initial_state: GNSS-only prepared nominal orbit; zero pulse/density coordinates; no imported nuisance state','previous_results_reused':False,'native_runs':0,'owned_directory_identities':[c.directory_identity(q) for q in [output,scratch_root,*[output/s for s in ('prepared',*c.CASES)],*[output/s/leaf for s in ('prepared',*c.CASES) for leaf in ['tmp','scratch','row-spool','legacy-output']]]],'namespace_scope':'Minimal mount allowlist; no host /, /mnt, /home or archived results are exposed. System /usr /etc /lib runtime directories remain readonly.'}
 c.save(output/'plan.json',plan);return c.pin(output/'plan.json')

def checked_plan(path,digest,*,inside=False):
 c.verify({'path':str(path),'sha256':digest});p=c.read(path)
 c.require(p['schema']==SCHEMA and p['stages']==list(c.CASES) and p['limits']==c.LIMITS,'Unknown plan or changed limits')
 c.require(p['cold_start'] is True and p['previous_results_reused'] is False and p['forbidden_paths']==FORBIDDEN,'Cold/isolation contract changed')
 c.require(p['runtime']['native']['sha256']==PINNED_NATIVE and p['runtime']['source_root']==str(c.SOURCE),'Native/source identity changed')
 for row in [*p['control_pins'],*p['helper_pins']]:c.verify(row)
 if not inside:
  for row in p['owned_directory_identities']:c.verify_directory_identity(row)
  c.verify(p['source_snapshot']);c.verify(p['reference_plan']);c.verify(p['python_runtime'])
  c.require(source_identity()==p['source_identity'],'Frozen source snapshot identity changed')
  _,legacy=helpers();c.require(legacy.disk_filesystem(p['scratch_root'])==p['scratch_filesystem'],'Scratch filesystem changed')
  c.require(p['boot_id']==Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'Previous boot; preserve interrupted attempt')
  for s,row in p['scratch_identities'].items():
   q=Path(p['scratch_root'])/s;z=q.stat();c.require(row=={'device':z.st_dev,'inode':z.st_ino,'uid':z.st_uid},'Scratch identity changed')
 if not inside:
  for raw,row in p['scratch_leaf_identities'].items():
   q=Path(raw);z=q.stat();c.require(not q.is_symlink() and q.resolve()==q and row=={'device':z.st_dev,'inode':z.st_ino,'uid':z.st_uid},'Scratch leaf identity changed')
 verify_files(p['bindings'],inside=inside)
 verify_directory_membership(p,inside=inside)
 c.require([j['stage'] for j in p['jobs']]==list(c.CASES),'Two exact case order differs')
 for job in p['jobs']:
  s=job['stage'];c.require(s in c.CASES and Path(job['directory'])==Path(p['output'])/s,'Stage ownership changed')
  for key in ['request','rebinding']:c.verify(job[key])
  original=Path(p['originals'][s]['path']);c.verify(p['originals'][s]);journal=c.read(job['rebinding']['path'])
  c.verify_rebinding(s,original.read_bytes(),c.read(job['request']['path']),journal['journal'],p['source_identity'])
  c.require(job['environment']==environment(job['directory']),'Unknown environment/settings')
 c.require(c.sha(path)==digest,'Plan changed during verification');return p

def namespace(plan,stage,argv):
 root=Path(plan['output'])/stage;backing=Path(plan['scratch_root'])/stage
 c.require(stage in ('prepared',*c.CASES),'Unknown namespace stage')
 binds=[]
 for x in plan['directory_bindings']:binds.append(('ro',x['host'],x['target']))
 for x in plan['bindings']:
  # Parent directory bindings already retain exact scientific runtime content.
  if not any(Path(x['target']).is_relative_to(Path(d['target'])) for d in plan['directory_bindings']):binds.append(('ro',x['host'],x['target']))
 for f in ['plan.json','python-runtime.json']:
  binds.append(('ro',str(Path(plan['output'])/f),str(Path(plan['output'])/f)))
 for item in plan['originals'].values():binds.append(('ro',item['path'],item['path']))
 # Preparation can read both frozen requests; it never runs the native program.
 for job in plan['jobs']:
  for key in ['request','rebinding']:binds.append(('ro',job[key]['path'],job[key]['path']))
 binds.append(('rw',str(root),str(root)))
 for leaf in ['tmp','scratch','row-spool']:binds.append(('rw',str(backing/leaf),str(root/leaf)))
 binds += [('rw',str(backing/'tmp'),'/tmp'),('rw',str(root/'legacy-output'),str(Path(plan['prepared']['output_dir'])/'output'))]
 if stage!='prepared':
  # The backend sets its own spool path under fit/, so put that leaf on ext4.
  binds.append(('rw',str(backing/'row-spool'),str(root/'fit/row-spool')))
  for key in ['request','rebinding']:item=next(x for x in plan['jobs'] if x['stage']==stage)[key];binds.append(('ro',item['path'],item['path']))
 parents={'/home','/mnt','/run'}
 for _,_,target in binds:
  t=Path(target).parent
  while str(t) not in ('/','.'):
   if not any(t.is_relative_to(Path(x)) for x in ['/usr','/lib','/lib64','/bin','/sbin','/etc']):parents.add(str(t))
   t=t.parent
 args=['/usr/bin/bwrap','--die-with-parent','--unshare-all','--new-session','--clearenv']
 for d in sorted(parents,key=lambda x:(len(Path(x).parts),x)):args += ['--dir',d]
 for d in ['/usr','/bin','/sbin','/lib','/lib64','/etc']:
  if Path(d).exists():args+=['--ro-bind',d,d]
 for mode,host,target in binds:args+=['--bind' if mode=='rw' else '--ro-bind',host,target]
 args+=['--proc','/proc','--dev','/dev']
 for k,v in environment(root).items():args+=['--setenv',k,v]
 return args+['--chdir',str(c.SOURCE),'--']+list(argv)

def namespace_proof(plan,stage):
 root=Path(plan['output'])/stage;env=environment(root);validate_environment(env,os.environ)
 absent=[]
 for f in plan['forbidden_paths']:
  c.require(not Path(f).exists(),'Forbidden archive/truth visible: '+f);absent.append(f)
 mounts=[]
 for line in Path('/proc/self/mountinfo').read_text().splitlines():
  a=line.split();mounts.append({'path':a[4].replace('\\040',' '),'options':a[5].split(','),'filesystem':a[a.index('-')+1]})
 def containing(path):
  pp=Path(path).resolve();matches=[m for m in mounts if pp.is_relative_to(Path(m['path']))];return max(matches,key=lambda m:len(Path(m['path']).parts))
 for row in plan['bindings']:c.require('ro'in containing(row['target'])['options'],'Input/runtime is writable')
 for path in [root/'tmp',root/'scratch',root/'row-spool',*([root/'fit/row-spool'] if stage!='prepared' else [])]:
  m=containing(path);c.require('rw'in m['options'] and m['filesystem'] in ['ext4','xfs','btrfs','zfs'],'Scratch is not disk-backed writable')
 return {'minimal_namespace':True,'forbidden_paths_absent':absent,'read_only_files':len(plan['bindings']),'disk_backed_scratch':True,'environment_whitelisted':True}

def preflight_worker(path,digest):
 p=checked_plan(path,digest,inside=True);proof=namespace_proof(p,'prepared');sys.path.insert(0,str(c.SOURCE/'src'))
 from orbit_poc.comparison import backend as native
 from orbit_poc.comparison.groops_config import build_fit_configs
 import numpy,scipy,psutil
 g,_=helpers();native_loader=[]
 for path in g.runtime_api().linked(c.BINARY,environment(Path(p['output'])/'prepared')):native_loader.append(c.pin(path))
 c.require({Path(x['path']).name:x['sha256'] for x in native_loader}=={Path(x['path']).name:x['sha256'] for x in p['native_loader_dependencies']},'Actual namespace native loader differs from pinned dependencies')
 rows=[]
 for job in p['jobs']:
  j=c.read(job['request']['path']);prep=native._preparation(j);target=Path(p['output'])/'prepared'/job['stage']/'native';native._private_data(prep,target);config=build_fit_configs(prep,target,j['method'],j['parameters'])
  import xml.etree.ElementTree as ET
  for f in config['result_paths'].values():c.require(Path(f).is_relative_to(target),'Actual config output escapes fresh preflight')
  xml_outputs=[]
  for f in config['configs'].values():
   for node in ET.parse(f).iter():
    if node.tag.lower().startswith('outputfile') and node.text:
     # Placeholders are allowed only below the already verified private root.
     # A variable at the path root, or '..', cannot evade this prefix check.
     c.require(Path(node.text).is_relative_to(target) and '..' not in Path(node.text).parts,'XML output escapes fresh preflight: '+node.text);xml_outputs.append(node.text)
  rows.append({'stage':job['stage'],'native_preparation_verified':True,'original_nominal_orbit_sha256':c.sha(prep['native_paths']['orbit']),'native_config_outputs':xml_outputs,'output_paths_private':True})
 c.save(Path(p['output'])/'prepared/preflight-result.json',{'status':'passed','proof':proof,'cases':rows,'native_loader_dependencies':native_loader,'native_loader_verified':True,'python':sys.executable,'numpy':numpy.__version__,'scipy':scipy.__version__,'native_runs':0});return 0

def preflight(path,digest):
 p=checked_plan(path,digest);g,_=helpers();admission();resource_admission(p)
 root=Path(p['output'])/'prepared';argv=namespace(p,'prepared',[p['runtime']['python']['path'],'-s','-B',str(HERE/'one_hour_controls.py'),'_preflight','--plan',str(path),'--sha256',digest])
 c.save(root/'command.json',{'argv':argv,'scope':'No native computation; actual input parser and private config construction'})
 sys.path.insert(0,str(c.SOURCE/'src'));from orbit_poc.segmented.supervisor import run_owned
 result=run_owned(['/usr/bin/taskset','-c','4',*argv],python_executable=p['runtime']['python']['path'],cwd=c.SOURCE,env=environment(root),log_path=root/'preflight.log',receipt_path=root/'supervisor.json',timeout_seconds=1800,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=Path(p['scratch_root'])/'prepared')
 c.save(root/'execution.json',{'status':result['status'],'returncode':result['returncode'],'native_runs':0,'cleanup_verified':g.cleanup_verified(result)})
 c.require(result['status']=='complete' and result['returncode']==0 and g.cleanup_verified(result),'Namespace preflight failed; preserve attempt')
 checked_plan(path,digest);c.require(c.read(root/'preflight-result.json')['status']=='passed','No preflight receipt')
 freeze={'schema':'orbit-poc-one-hour-freeze-v1','plan':c.pin(path),'preflight':c.pin(root/'preflight-result.json'),'preflight_execution':c.pin(root/'execution.json'),'preflight_supervisor':c.pin(root/'supervisor.json'),'launch_authority':False,'native_runs':0}
 c.save(Path(p['output'])/'freeze.json',freeze);return c.pin(Path(p['output'])/'freeze.json')

def assessment(result,job,fit):
 import numpy as np
 from orbit_poc.numerics import backend,protocol,optimizer
 protocol.validate_complete_result(result,job)
 for key in ['source_hash','preprocessing_hash','mask_hash']:
  c.require(result.get(key)==job.get(key) and key in job,'Complete result differs from frozen '+key)
 c.require(result.get('runtime',{}).get('source_hash')==job['source_hash'],'Runtime source identity differs')
 for item in result['artifacts']:
  c.require(Path(item['path']).is_relative_to(fit),'Result artifact escapes fresh fit');c.verify(item)
 def artifact(role):
  xs=[x for x in result['artifacts'] if x['role']==role];c.require(len(xs)==1,'Missing unique artifact '+role);return Path(xs[0]['path'])
 profile_path=artifact('native_nuisance_profile');folder=profile_path.parent
 c.require(folder.name.endswith('-final-covariance'),'Accepted covariance is not from fresh final point')
 profile=c.read(profile_path);factor=artifact('native_qr_factor');coords=c.read(artifact('native_qr_coordinates'));diag=c.read(artifact('native_qr_diagnostics'));cost=c.read(artifact('native_objective'))
 backend.require_full_native_factor(coords,diag)
 c.require(diag.get('lambda')==0,'Final factor diagnostics are not undamped')
 point=optimizer.Linearization(backend.read_factor(factor),backend.read_factor(artifact('native_qr_rhs')).ravel(),np.asarray(coords['scales']),np.asarray(coords['dynamic'],dtype=bool),int(diag['reduced_rows']),float(cost['direct_cost']),float(coords['orthogonal_energy']),'postfit-check',None).validate()
 rank=optimizer.certify_rank(point);_,_,gradient=optimizer.proposal(point)
 proposal=c.read(folder/'proposal-000/proposal-retention.json');c.require(proposal['status']=='complete','Final proposal retention incomplete')
 fresh={'stationary':True,'raw_correction':proposal['metrics'],'normalized_gradient':gradient,'nuisance_floor_limited':False}
 c.strict_summary(result,profile,fresh)
 c.require(result.get('confirmation_checks') and result['confirmation_checks'][-1]['stationary'] is True,'Optimizer confirmation missing')
 return {'final_profile':c.pin(profile_path),'final_factor':c.pin(factor),'fresh_final_correction':fresh,'rank':rank,'final_covariance_nuisance_marginalized':True}


def cold_start_evidence(job,fit,nominal):
 import numpy as np
 from orbit_poc.comparison import backend as native
 c.require(c.sha(nominal)==c.NOMINAL_SHA,'Initial nominal orbit differs from original GNSS-only chain')
 fit=Path(fit);point=fit/'point-001-initial';converted=fit/'initial-input/orbit.txt';physical=point/'physical_initial.txt'
 _,states=native._orbit(converted);values=native.read_native_table(physical).ravel()
 c.require(values.shape==(6,) and np.array_equal(states[0],values),'First physical state differs from original prepared orbit conversion')
 density=job['method']=='groops_log_drag_ou';count=61 if density else 6
 force=point/'native/log_density.txt' if density else point/'full_pulses_um_s.txt'
 values=np.asarray([float(row.split()[-1]) for row in force.read_text().splitlines() if row.strip()])
 c.require(len(values)==count and np.array_equal(values,np.zeros(count)),'Initial density/pulses are not exactly zero')
 fixed=native.read_native_table(point/'fixed_force.txt').ravel()
 c.require(len(fixed)==count+6 and np.array_equal(fixed,np.zeros(count+6)),'Initial propagation force correction differs')
 return {'initialization':'original GNSS-only bootstrap and unchanged nominal closure','nominal_orbit_sha256':c.NOMINAL_SHA,'converted':c.pin(converted),'physical_initial':c.pin(physical),'initial_state_exact':True,'force':c.pin(force),'zero_force_count':count,'fixed_force':c.pin(point/'fixed_force.txt'),'no_physical_override':True,'no_nuisance_donor':True}

def worker(path,digest,stage):
 p=checked_plan(path,digest,inside=True);proof=namespace_proof(p,stage);job=next(x for x in p['jobs'] if x['stage']==stage);root=Path(job['directory']);fit=root/'fit';result=None;error=None;started=time.monotonic()
 try:
  # bwrap creates the fit/spool mountpoint. No other existing fit contents allowed.
  c.require(set(x.name for x in fit.iterdir())=={'row-spool'} and not any((fit/'row-spool').iterdir()),'Cold fit directory already used')
  sys.path.insert(0,str(c.SOURCE/'src'));from orbit_poc.numerics.backend import fit_job
  result=fit_job(c.read(job['request']['path']),fit)
  c.save(root/'backend-result.json',result)
  evidence=assessment(result,c.read(job['request']['path']),fit)
  evidence['cold_start']=cold_start_evidence(c.read(job['request']['path']),fit,p['prepared']['native_paths']['orbit'])
  verify_files(p['bindings'],inside=True)
  record={'status':'passed','stage':stage,'whole_fit_verified':True,'accepted_covariance':True,'evidence':evidence}
 except Exception as exc:
  error=type(exc).__name__+': '+str(exc);record={'status':'failed','stage':stage,'whole_fit_verified':False,'accepted_covariance':False,'error':error,'traceback':traceback.format_exc()}
 if result is not None:record['backend_outcome']={k:result.get(k) for k in ['status','numerical_status','error','elapsed_seconds','converged','covariance_valid']}
 try:
  if (fit/'initial-input/orbit.txt').exists() and (fit/'point-001-initial/physical_initial.txt').exists():record['cold_start_evidence']=cold_start_evidence(c.read(job['request']['path']),fit,p['prepared']['native_paths']['orbit'])
 except Exception as exc:record.update(status='failed',whole_fit_verified=False,accepted_covariance=False,cold_start_error=repr(exc))
 record.update(namespace=proof,worker_elapsed_seconds=time.monotonic()-started,release_authority=False,cold_start=True,initial_state_override=False,nuisance_donor=False)
 c.save(root/'strict-result.json',record);return 0 if record['status']=='passed' else 1

def checked_freeze(path,digest):
 c.verify({'path':str(path),'sha256':digest});f=c.read(path);c.require(f['schema']=='orbit-poc-one-hour-freeze-v1','Wrong freeze schema')
 for key in ['plan','preflight','preflight_execution','preflight_supervisor']:c.verify(f[key])
 c.require(c.read(f['preflight']['path'])['status']=='passed' and c.read(f['preflight_execution']['path'])['returncode']==0 and c.read(f['preflight_execution']['path'])['cleanup_verified'] is True,'Preflight not complete')
 return f,checked_plan(f['plan']['path'],f['plan']['sha256'])

def audit_authority(a,freeze_hash,plan):
 c.require(a.get('schema')=='orbit-poc-one-hour-launch-review-v1' and a.get('approved') is True and a.get('freeze_sha256')==freeze_hash and a.get('runner_sha256')==c.sha(__file__) and a.get('two_original_cold_fullfits') is True and a.get('thresholds_unchanged') is True and a.get('namespace_preflight_passed') is True,'No exact independent launch approval')

def admission():
 g,_=helpers();info=g.recovery_api().admission(cpu=4)
 c.require(info['available_memory_bytes']>=c.LIMITS['minimum_available_memory_bytes'],'At least 16 GiB available memory required')
 for row in g.recovery_api().process_snapshot():
  if row['pid']==os.getpid() or row.get('state')=='Z':continue
  if any('one_hour_controls' in x for x in row['argv'][1:]):
   # Existing ancestor launcher is ours; any unrelated controller blocks admission.
   parents={os.getpid()};by={x['pid']:x for x in g.recovery_api().process_snapshot()};cur=os.getpid()
   while cur in by and by[cur]['parent'] not in parents:cur=by[cur]['parent'];parents.add(cur)
   c.require(row['pid'] in parents,'Competing one-hour controller: '+str(row['pid']))
 return info


def resource_admission(plan):
 rows=[]
 for label,path in [('output',plan['output']),('scratch',plan['scratch_root'])]:
  free=shutil.disk_usage(path).free;c.require(free>=32*1024**3,'32 GiB free disk required on '+label);rows.append({'role':label,'path':path,'available_bytes':free,'required_bytes':32*1024**3})
 return rows

def shared_lock():
 path=c.BASE/'validation-controls07/cooperative-admission.lock'
 flags=os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW
 fd=os.open(path,flags,0o600);stream=os.fdopen(fd,'r+')
 try:
  z=os.fstat(fd);ls=path.lstat()
  c.require(stat.S_ISREG(z.st_mode) and z.st_uid==os.getuid() and (z.st_dev,z.st_ino)==(ls.st_dev,ls.st_ino),'Shared lock ownership/identity invalid')
  fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
  return stream,{'path':str(path),'device':z.st_dev,'inode':z.st_ino,'uid':z.st_uid,'scope':'Existing shared cooperative lock; opened without following links, no lock-file content changes'}
 except BaseException:stream.close();raise

def run(freeze,sha,audit,audit_sha):
 c.verify({'path':str(audit),'sha256':audit_sha});f,p=checked_freeze(freeze,sha);audit_authority(c.read(audit),sha,p);out=Path(p['output']);results=[];error=None
 lock,lock_identity=shared_lock()
 for job in p['jobs']:c.fresh_stage(job['directory']);c.fresh_backing(job['scratch'])
 resource_admission(p)
 c.save(out/'run-started.json',{'at':now(),'pid':os.getpid(),'admission':admission(),'shared_lock':lock_identity,'freeze_sha256':sha,'audit_sha256':audit_sha})
 sys.path.insert(0,str(c.SOURCE/'src'));from orbit_poc.segmented.supervisor import run_owned
 try:
  for job in p['jobs']:
   checked_freeze(freeze,sha);c.fresh_backing(job['scratch']);resource=resource_admission(p);c.save(Path(job['directory'])/'admission.json',{**admission(),'resource':resource})
   args=namespace(p,job['stage'],[p['runtime']['python']['path'],'-s','-B',str(HERE/'one_hour_controls.py'),'_worker','--plan',f['plan']['path'],'--sha256',f['plan']['sha256'],'--stage',job['stage']])
   sup=run_owned(['/usr/bin/taskset','-c','4',*args],python_executable=p['runtime']['python']['path'],cwd=c.SOURCE,env=environment(job['directory']),log_path=Path(job['directory'])/'stage.log',receipt_path=Path(job['directory'])/'supervisor.json',timeout_seconds=7200,max_process_tree_rss_bytes=8*1024**3,min_free_disk_bytes=32*1024**3,working_directory=Path(job['scratch']))
   valid=True
   try:checked_freeze(freeze,sha)
   except Exception as e:valid=False;error=repr(e)
   strict=Path(job['directory'])/'strict-result.json';receipt=c.read(strict) if strict.exists() else None;classification=c.terminal_classification(sup,receipt,valid)
   results.append({'stage':job['stage'],**classification,'supervisor':c.pin(Path(job['directory'])/'supervisor.json'),'strict_result':c.pin(strict) if strict.exists() else None})
   if not classification['continue']:break
 except BaseException as exc:error=repr(exc)
 finally:
  done={r['stage']:r for r in results}
  for job in p['jobs']:
   if job['stage'] not in done and (Path(job['directory'])/'supervisor.json').exists():done[job['stage']]={'stage':job['stage'],'status':'attempted_without_verified_terminal_assessment','supervisor':c.pin(Path(job['directory'])/'supervisor.json')}
  passed=error is None and len(results)==2 and all(r['status']=='passed' for r in results)
  c.save(out/'result.json',{'status':'passed' if passed else 'interrupted' if any(r['status']=='interrupted' for r in results) else 'failed','planned_stages':list(c.CASES),'stages':[done.get(s,{'stage':s,'status':'not_executed_or_interrupted_without_receipt'}) for s in c.CASES],'error':error,'freeze_sha256':sha,'old_results_reused':False,'release_authority':False});lock.close()
 return 0 if passed else 1

def launch(freeze,digest,audit,audit_sha):
 c.verify({'path':str(audit),'sha256':audit_sha});f,p=checked_freeze(freeze,digest);audit_authority(c.read(audit),digest,p);info=admission();out=Path(p['output'])
 c.require(not any((out/n).exists() for n in ['launch.json','run-started.json','result.json']),'Preserve previous launch')
 for j in p['jobs']:c.fresh_stage(j['directory']);c.fresh_backing(j['scratch'])
 resource_admission(p)
 argv=[p['runtime']['python']['path'],'-s','-B',str(HERE/'one_hour_controls.py'),'_run','--freeze',str(freeze),'--sha256',digest,'--audit',str(audit),'--audit-sha256',audit_sha]
 with (out/'detached.log').open('x') as log:child=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,env=environment(out/'prepared'),cwd=HERE,start_new_session=True)
 fields=Path(f'/proc/{child.pid}/stat').read_text().rsplit(')',1)[1].split()
 result={'pid':child.pid,'start_ticks':int(fields[19]),'boot_id':p['boot_id'],'argv':argv,'admission':info,'at':now(),'freeze_sha256':digest,'audit_sha256':audit_sha};c.save(out/'launch.json',result);return result


def execute(freeze,digest,audit,audit_sha):
 out=Path(freeze).parent
 c.require(out.parent==c.BASE and out.is_dir() and out.resolve()==out,'Detached output ownership differs')
 c.require(not (out/'detached-result.json').exists(),'Preserve detached terminal result')
 started=time.monotonic();signals=[];handlers={};code=1;error=None
 def interrupted(number,frame):signals.append(number);raise KeyboardInterrupt('Owned controller interrupted')
 for number in (signal.SIGTERM,signal.SIGINT,signal.SIGHUP):handlers[number]=signal.signal(number,interrupted)
 try:
  c.save(out/'detached-started.json',{'at':now(),'pid':os.getpid(),'freeze_sha256':digest,'audit_sha256':audit_sha})
  code=run(freeze,digest,audit,audit_sha)
 except BaseException as exc:error=repr(exc)
 finally:
  for number,handler in handlers.items():signal.signal(number,handler)
  c.save(out/'detached-result.json',{'status':'interrupted' if signals or ((out/'result.json').exists() and c.read(out/'result.json')['status']=='interrupted') else 'complete' if code==0 else 'failed','returncode':code,'error':error,'signals_received':signals,'elapsed_seconds':time.monotonic()-started,'freeze_sha256':digest,'audit_sha256':audit_sha,'old_results_reused':False,'release_authority':False,'cleanup_authority':'Original pidfd/subreaper supervisor receipts only; no inferred cleanup certificate'})
 return code

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('operation',choices=['prepare','preflight','launch','_preflight','_worker','_run']);parser.add_argument('--output',type=Path);parser.add_argument('--scratch-root',type=Path,default=Path('/home/emper/orbit-one-hour-scratch01'));parser.add_argument('--plan',type=Path);parser.add_argument('--freeze',type=Path);parser.add_argument('--sha256');parser.add_argument('--audit',type=Path);parser.add_argument('--audit-sha256');parser.add_argument('--stage',choices=c.CASES);a=parser.parse_args()
 if a.operation=='prepare':c.require(a.output is not None,'--output required');print(json.dumps(prepare(a.output,a.scratch_root)));return 0
 if a.operation in ['preflight','_preflight','_worker']:
  c.require(a.plan is not None and a.sha256,'--plan and --sha256 required')
  if a.operation=='preflight':print(json.dumps(preflight(a.plan,a.sha256)));return 0
  if a.operation=='_preflight':return preflight_worker(a.plan,a.sha256)
  c.require(a.stage is not None,'--stage required');return worker(a.plan,a.sha256,a.stage)
 c.require(a.freeze and a.sha256 and a.audit and a.audit_sha256,'--freeze --sha256 --audit --audit-sha256 required')
 if a.operation=='launch':print(json.dumps(launch(a.freeze,a.sha256,a.audit,a.audit_sha256)));return 0
 return execute(a.freeze,a.sha256,a.audit,a.audit_sha256)
if __name__=='__main__':raise SystemExit(main())
