"""Pure two-case cold full-fit contracts; no estimator or launcher import."""
from pathlib import Path
import copy, hashlib, json, math, os

SOURCE=Path('/mnt/d/orbit-v41-recovery01/candidate04/source')
BINARY=SOURCE.parent/'binaries/groops-v41-28c725765201e470'
NATIVE_SHA='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d'
BASE=Path('/mnt/d/orbit-v41-recovery02')
REFERENCE_PLAN=BASE/'reference-gates14-run01/plan.json'
REFERENCE_PLAN_SHA='83224b4e5284e5b7d4c6ac0e8d99f0f7845a0c1aedbd7f6d1f1a45831212967a'
CASES=('cold-pulses','cold-density')
REQUESTS={
 'cold-pulses':{'method':'groops_pulses','path':'/mnt/d/orbit-numerics-v3.1-artifacts/engineering/objective-validation-near-03/pulses-staged/request.json','sha256':'9de707ae51e5031a5b13f1d02ab5ec5a67e996195840de6c5c7e81457a74c9f5'},
 'cold-density':{'method':'groops_log_drag_ou','path':'/mnt/d/orbit-numerics-v3.1-artifacts/engineering/objective-validation-near-03/log_drag_ou-staged/request.json','sha256':'2189944cfb519b5ca0730e6e02ee9cb809145a0845f66846931a8fb199694dfd'}}
CONTROLS={'initial_damping':.001,'maximum_accepted_iterations':32,'maximum_density_update':.0001,'maximum_position_change_m':.00003,'maximum_pulse_update_m_s':1e-8,'maximum_trial_evaluations':96,'minimum_gain_ratio':.0001,'normalized_gradient_tolerance':1e-8,'wall_time_seconds':7200.}
PARAMETERS={'cold-pulses':{'interval_seconds':1200.,'sigma_velocity_m_s':.0001},'cold-density':{'empirical_acceleration':False,'initial_prior':'stationary_ou','interpolation':'linear_log_density','knot_seconds':60.,'sigma_log_density':.3,'tau_seconds':7200.}}
LIMITS={'timeout_seconds':7200,'process_tree_rss_bytes':8*1024**3,'min_free_disk_bytes':32*1024**3,'minimum_available_memory_bytes':16*1024**3,'numerical_threads':1,'cpu':4}
BOOTSTRAP_SHA='24e3870fbdedeb31d53edd56e93a0067c12b1444afa44dbc8bda40e70c312226'
INITIAL_SHA='ed50841f7928ecaf5284028edacde0db9c878461d621a47d04686c66007eb690'
NOMINAL_SHA='16bb3d709b50d6918c0ee2dbb6d419f17f17e934c04f39d607c77abcf73f3db1'
FORBIDDEN_KEYS={'evaluation_inputs','calibration_inputs','truth','reference_orbit','initial_state_from','nuisance_donor','warm_start'}

def require(v,message):
 if not v:raise ValueError(message)
def canonical(d):return hashlib.sha256(json.dumps(d,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(path):
 def pairs(items):
  d={}
  for k,v in items:
   require(k not in d,'Duplicate JSON key');d[k]=v
  return d
 def bad(v):raise ValueError('Nonfinite JSON')
 return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=bad)
def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for x in iter(lambda:f.read(1048576),b''):h.update(x)
 return h.hexdigest()
def pin(path):
 p=Path(path).absolute();return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def verify(row):
 require(set(row)>={'path','sha256'},'Invalid artifact pin');p=Path(row['path']);require(p.is_file() and sha(p)==row['sha256'],'Pinned bytes changed: '+str(p))
 if 'bytes'in row:require(p.stat().st_size==row['bytes'],'Pinned size changed')
 return p
def save(path,d):
 with Path(path).open('x') as f:
  json.dump(d,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n');f.flush()
  import os;os.fsync(f.fileno())
def original_request(stage,raw):
 require(stage in CASES,'Unknown case')
 require(hashlib.sha256(raw).hexdigest()==REQUESTS[stage]['sha256'],'Original case hash differs')
 d=json.loads(raw);require(d['method']==REQUESTS[stage]['method'] and d['stage']=='synthetic' and d['kind']=='fit','Original case classification differs')
 require(d['numerics_profile']=='qr_lm_staged_jacobian' and d['case']['duration_hours']==1.,'Original numerical profile/duration differs')
 require(d['parameters']==PARAMETERS[stage] and d['numerical_controls']==CONTROLS,'Original parameters/thresholds differ')
 require(not (set(d)&FORBIDDEN_KEYS),'Donor/reference/initial override forbidden')
 init=[x for x in d['estimation_inputs'] if x['role']=='bootstrap_orbit']
 require(len(init)==1 and init[0]['sha256']==BOOTSTRAP_SHA and init[0]['provenance']=='gnss_only','Original GNSS-only bootstrap missing')
 require(all(x['role'] not in ['truth','reference_orbit','evaluation'] for x in d['estimation_inputs']),'Forbidden estimation input role')
 return d

def rebind(stage,raw,source_identity):
 original=original_request(stage,raw);d=copy.deepcopy(original);journal=[]
 for path,value in [(('backend','groops_executable'),str(BINARY)),(('expected_native_binary_sha256',),NATIVE_SHA),(('source_hash',),source_identity)]:
  cursor=d
  for k in path[:-1]:cursor=cursor[k]
  before=cursor[path[-1]];cursor[path[-1]]=value;journal.append({'path':list(path),'before':before,'after':value,'reason':'Separate corrected runtime attribution; scientific settings unchanged'})
 return d,journal

def verify_rebinding(stage,raw,rebound,journal,source_identity):
 expected,edits=rebind(stage,raw,source_identity);require(rebound==expected and journal==edits,'Runtime rebinding differs or scientific settings changed')
 return True

def fresh_stage(root):
 root=Path(root);require(root.is_dir() and not root.is_symlink() and root.resolve()==root,'Stage output must be ordinary directory')
 expected={'request.json','rebinding.json','tmp','scratch','row-spool','legacy-output'}
 require(set(x.name for x in root.iterdir())==expected,'Preserve prior attempt: stage is not fresh')
 for leaf in expected-{'request.json','rebinding.json'}:
  p=root/leaf
  require(p.is_dir() and not p.is_symlink() and p.resolve()==p and p.stat().st_uid==os.getuid(),'Cold leaf is not an ordinary owned stage directory')
  require(not any(p.iterdir()),'Cold stage scratch already used')
 return True

def terminal_classification(supervisor,worker,identity_ok):
 status=supervisor.get('status');cleanup=supervisor.get('cleanup',{})
 clean=supervisor.get('owned_process_group_cleaned') is True and cleanup.get('verified') is True and cleanup.get('empty_tree_certificate')=='kernel_ECHILD' and cleanup.get('remaining')==[]
 if not identity_ok:return {'status':'failed','reason':'identity_changed','continue':False}
 if not clean:return {'status':'failed','reason':'cleanup_unverified','continue':False}
 if status=='interrupted':return {'status':'interrupted','reason':'owned_supervisor_interrupted','continue':False}
 if status!='complete':return {'status':status or 'failed','reason':'supervisor_did_not_complete','continue':True}
 if supervisor.get('returncode')!=0:
  outcome=(worker or {}).get('backend_outcome',{})
  if outcome.get('status')=='timeout' or outcome.get('numerical_status')=='timeout':return {'status':'timeout','reason':'backend_timeout','backend_outcome':outcome,'continue':True}
  return {'status':'failed','reason':'worker_exit_nonzero','backend_outcome':outcome,'continue':True}
 if not worker or worker.get('status')!='passed' or worker.get('whole_fit_verified') is not True or worker.get('accepted_covariance') is not True:return {'status':'failed','reason':'missing_strict_complete_fit_receipt','continue':True}
 return {'status':'passed','reason':'strict_complete_fullfit','continue':True}

def strict_summary(result,profile,confirmation):
 require(result.get('status')=='complete' and result.get('converged') is True and result.get('covariance_valid') is True,'No complete converged covariance-valid fit')
 require(result.get('native_binary_sha256')==NATIVE_SHA,'Wrong native result identity')
 require(profile.get('nuisance_converged') is True and profile.get('nuisance_floor_limited') is False,'Final nuisance is not strictly converged')
 require(profile.get('threshold_m')==1e-8 and profile.get('required_consecutive_small_updates')==2 and profile.get('fresh_full_nuisance_confirmed') is True,'Final strict nuisance controls differ')
 require(0<=profile.get('fresh_full_nuisance_update_m',float('inf'))<1e-8,'Fresh full nuisance update is not small')
 hist=profile.get('history',[]);require(len(hist)>=2 and all(0<=r.get('maximum_update_m',float('inf'))<1e-8 for r in hist[-2:]),'Two strict nuisance updates absent')
 require(confirmation.get('stationary') is True and not confirmation.get('nuisance_floor_limited',False),'Strict physical confirmation missing')
 metrics=confirmation['raw_correction']
 require(metrics['position_change_m']<3e-5 and metrics['density_update']<1e-4 and metrics['pulse_update_m_s']<1e-8 and confirmation['normalized_gradient']<1e-8,'Physical convergence threshold not met')
 require(all(math.isfinite(float(v)) and float(v)>=0 for v in [*metrics.values(),confirmation['normalized_gradient']]),'Nonfinite/negative physical metrics')
 return True


def directory_identity(path):
 p=Path(path);require(p.is_dir() and not p.is_symlink() and p.resolve()==p and p.stat().st_uid==os.getuid(),'Directory is not ordinary, canonical and owned: '+str(p));s=p.stat()
 return {'path':str(p),'device':s.st_dev,'inode':s.st_ino,'uid':s.st_uid}

def verify_directory_identity(row):
 require(directory_identity(row['path'])==row,'Owned directory identity changed: '+row['path']);return True

def fresh_backing(path):
 p=Path(path);directory_identity(p)
 require(set(x.name for x in p.iterdir())=={'tmp','scratch','row-spool','legacy-output'},'Backing leaf membership differs')
 for leaf in p.iterdir():directory_identity(leaf);require(not any(leaf.iterdir()),'Actual ext4 cold scratch already used: '+str(leaf))
 return True
