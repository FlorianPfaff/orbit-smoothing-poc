from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict,make_dataclass
import ast,hashlib,json,datetime,os,stat
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume');B=BASE/'benchmark-01';R=BASE/'recovery-20261016-01'
O=C/'original150-boot-interruption-20261016-02';P=C/'original150-interrupted-attempt18-proposal01'
S=Path('/mnt/d/orbit-numerics-v3.1/source-snapshots/runtime-553ad084a7165b045f8f/src/orbit_poc/numerics/protocol.py');CONFIG=Path('/mnt/d/orbit-numerics-v3.1/deployment-final/benchmark-01/config.json')
def enc(x):return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(x):return sha(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pin(p):
 p=Path(p);before=p.stat();h=hashlib.sha256()
 with p.open('rb')as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 after=p.stat();assert(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),str(p)
 return {'path':str(p),'sha256':h.hexdigest(),'bytes':before.st_size}
def read(p):return json.loads(Path(p).read_bytes())
def save(p,v):
 with p.open('xb')as f:f.write(enc(v))
O.mkdir();P.mkdir();(O/'original').mkdir()
m=read(B/'manifest.json');cfg=read(CONFIG);a=m['attempts'][17];d=B/'attempts'/a['attempt_id'];case=next(x for x in m['cases']if x['case_id']==a['case_id']);boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();launch=read(R/'launch.json')
assert boot=='e0523d0a-e0c2-404b-88d2-57ba4367a15b'and launch['boot_id']=='04656a53-958c-4419-8605-c7088e036b9f'and not Path('/proc/9877').exists()
assert pin(S)['sha256']=='1435ad9cf8b4fecc81c688ec5fed9182ed630365d9db75e22846dc4badd36769'
node=next(n for n in ast.parse(S.read_text()).body if isinstance(n,ast.FunctionDef)and n.name=='attempt_job');ns={'asdict':asdict};exec(compile(ast.Module(body=[node],type_ignores=[]),str(S),'exec'),ns)
Control=make_dataclass('FrozenControls',[(k,object)for k in cfg['controls']]);job=ns['attempt_job'](SimpleNamespace(controls=Control(**cfg['controls'])),m,case,a)
assert job==read(d/'request.json')==read(d/'worker-request.json');rh=canonical(job)
prefix=[]
for i,at in enumerate(m['attempts'][:17]):
 td=B/'attempts'/at['attempt_id'];v=read(td/'result.json');ix=read(td/'result-record.json');rp=pin(td/'result.json');assert ix['result']=={k:rp[k]for k in ('path','sha256')}
 prefix.append({'attempt_id':at['attempt_id'],'order':i,'status':v['status'],'result':rp,'index':pin(td/'result-record.json')})
for at in m['attempts'][18:]:
 q=B/'attempts'/at['attempt_id'];assert not q.exists()or(q.is_dir()and not any(q.iterdir()))
for n in ['result.json','result-record.json','controller-boot-interruption.json','worker-result.json']:assert not(d/n).exists()
partial=[];aliases=[]
for path,dirs,files in os.walk(d,followlinks=False):
 for name in list(dirs):
  q=Path(path)/name
  if q.is_symlink():files.append(name);dirs.remove(name)
 for name in files:
  q=Path(path)/name;s=q.lstat();rel=str(q.relative_to(d))
  if stat.S_ISLNK(s.st_mode):aliases.append({'relative':rel,'target':os.readlink(q),'lstat_size':s.st_size,'lstat_mtime_ns':s.st_mtime_ns,'device':s.st_dev,'inode':s.st_ino})
  else:
   assert stat.S_ISREG(s.st_mode),str(q);v=pin(q);partial.append({'relative':rel,'bytes':v['bytes'],'sha256':v['sha256'],'mtime_ns':s.st_mtime_ns})
partial.sort(key=lambda x:x['relative']);aliases.sort(key=lambda x:x['relative'])
assert len(partial)==224 and len(aliases)==9
rt=m['new_runtime'];assert pin(rt['native']['path'])['sha256']==rt['native']['sha256']=='3aad854b51102dce1fa7a8622177b33075d928d060cb10d740f1b137a00c33e9'
copies=[]
source_files=[R/'launch.json',R/'supervision.json',R/'campaign.log',B/'controller/20261016T035411Z-859946a79d9841f1a0d299507b99cc7e.json',d/'request.json',d/'worker-request.json',d/'resource-guard.json',d/'worker.log',d/'point-001-initial/profile.log',C/'original150-current-status-20261016T211347Z.json',C/'original150-current-host-attribution-20261016-01.json',C/'original150-current-host-namespace-20261016-01.json']
for i,q in enumerate(source_files):
 target=O/'original'/f'{i:02d}-{q.name}';target.write_bytes(q.read_bytes());copies.append({'source':pin(q),'copy':pin(target)})
observation={'schema':'orbit-poc-original150-interruption-observation-v2','observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'interrupted_attempt':a,'terminal_checkpoints':17,'interrupted_without_checkpoint':1,'expected_attempts':150,'not_started':132,'previous_boot_id':launch['boot_id'],'current_boot_id':boot,'boot_changed':True,'partial_request_hash':rh,'partial_request_matches_frozen_job':True,'partial_files':partial,'partial_regular_file_count':len(partial),'partial_regular_bytes':sum(x['bytes']for x in partial),'existing_input_alias_count':len(aliases),'terminal_prefix':prefix,'copies':copies,'inputs':{'configuration':pin(CONFIG),'manifest':pin(B/'manifest.json'),'plan':pin(B/'plan.json'),'archived_protocol':pin(S)},'partial_native_runtime':rt,'parent_wall_time_seconds':None,'parent_peak_memory_bytes':None,'parent_returncode':None,'process_cleanup_verified':False,'old_journals_preserved':True,'converged':False,'covariance_authorized':False,'numerical_rerun':False,'scope':'Changed actual local WSL boot and absent campaign identities; all224 partial regular files hashed without input-alias traversal. Parent metrics and terminal cleanup are unavailable. No existing campaign file or terminal checkpoint was changed.'}
save(O/'observation.json',observation)
alias={'schema':'orbit-poc-original150-existing-input-alias-inventory-v1','attempt_directory':str(d),'request':pin(d/'request.json'),'alias_count':len(aliases),'entries':aliases,'native_preparation':next(x for x in job['estimation_inputs']if x.get('metadata',{}).get('kind')=='native_preparation'),'accuracy':next(x for x in job['estimation_inputs']if x.get('kind')=='synthetic_gnss_accuracy'),'scope':'Literal existing readlink/lstat identity only; targets not traversed. Independent audit must bind targets to the exact frozen native preparation.'}
save(O/'input-aliases.json',alias)
receipt_path=d/'controller-boot-interruption.json';result_path=d/'result.json';index_path=d/'result-record.json'
receipt={'schema':'orbit-poc-original150-boot-interruption-recovery-v1','prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attempt_id':a['attempt_id'],'outcome':'interrupted','failure_scope':'host_boot_changed_before_terminal_checkpoint','request_hash':rh,'manifest_hash':m['manifest_hash'],'configuration':pin(CONFIG),'manifest':pin(B/'manifest.json'),'source_sha256':rt['source_sha256'],'native':rt['native'],'dependency_runtime_identity':rt,'archived_protocol':pin(S),'helper':pin(__file__),'interruption_observation':pin(O/'observation.json'),'previous_boot_id':launch['boot_id'],'observed_boot_id':boot,'numerical_rerun':False,'covariance_authorized':False,'old_journals_preserved':True,'process_cleanup_verified':False,'parent_harness_metrics_available':False,'measurements':'Parent harness wall time, peak RSS, return code and worker PID were not checkpointed and remain null. No filesystem-time reconstruction.','preservation':'All17 prior checkpoints and all224 regular partial outputs remain unchanged, with9 literal input aliases preserved. No retry, binary substitution, source/input/model change or compaction.'}
receipt_bytes=enc(receipt)
artifacts=[{'path':str(receipt_path),'sha256':sha(receipt_bytes),'role':'controller_boot_interruption_recovery'},{'path':str(O/'observation.json'),'sha256':pin(O/'observation.json')['sha256'],'role':'boot_interruption_observation'},{'path':str(O/'input-aliases.json'),'sha256':pin(O/'input-aliases.json')['sha256'],'role':'preserved_input_alias_inventory'}]
for name,role in [('resource-guard.json','pre_attempt_resource_guard'),('worker.log','partial_worker_log'),('point-001-initial/profile.log','partial_native_profile_log')]:
 q=d/name;artifacts.append({'path':str(q),'sha256':pin(q)['sha256'],'role':role})
result={'status':'interrupted','converged':False,'covariance_valid':False,'error':'Local WSL host boot changed before terminal worker result and parent checkpoint were saved. Raw partial outputs are preserved; this frozen attempt is not retried.','elapsed_seconds':None,'final_objective':None,'request_hash':rh,'numerics_profile':a['profile'],'numerics_manifest_hash':m['manifest_hash'],'input_manifest_hash':case['input_manifest_hash'],'artifacts':artifacts,'harness_execution':{'elapsed_seconds':None,'peak_process_tree_rss_bytes':None,'returncode':None,'pid':None,'minimum_free_output_bytes':None,'minimum_free_physical_backing_bytes':None,'resource_limit_status':None,'process_group_isolated':None,'runtime':rt,'log':{'path':str(d/'worker.log'),'sha256':pin(d/'worker.log')['sha256']},'measurement':'Unavailable after host interruption. No reconstructed timing or memory metrics.'},'recovery':{'outcome':'interrupted','numerical_rerun':False,'accepted_covariance':False,'observation':pin(O/'observation.json'),'receipt':{'path':str(receipt_path),'sha256':sha(receipt_bytes)}}}
result_bytes=enc(result);index={'attempt_id':a['attempt_id'],'case_id':a['case_id'],'profile':a['profile'],'status':'interrupted','request_hash':rh,'result':{'path':str(result_path),'sha256':sha(result_bytes)}}
append=[]
for dest,raw in [(receipt_path,receipt_bytes),(result_path,result_bytes),(index_path,enc(index))]:
 q=P/dest.name;q.write_bytes(raw);append.append({'destination':str(dest),'candidate':pin(q),'destination_absent_at_proposal':True})
proposal={'schema':'orbit-poc-original150-reviewed-interrupted-append-proposal-v2','status':'proposed_not_applied','attempt':a,'observation':pin(O/'observation.json'),'archived_protocol':pin(S),'configuration':pin(CONFIG),'manifest':pin(B/'manifest.json'),'request':pin(d/'request.json'),'request_hash':rh,'expected_checkpoint_prefix':prefix,'append_files':append,'input_alias_inventory':pin(O/'input-aliases.json'),'covariance_authorized':False,'native_substitution':False,'numeric_rerun':False,'parent_metrics_null':True,'continuation_allowed_by_this_proposal':False,'precedent':pin(C/'original150-interrupted-append-proposal01/proposal.json'),'scope':'Propose exactly three data files. Preserve all older bytes. Requires independent proposal/alias review and separately reviewed append helper before mutation; fresh verified admission/startup before continuation.'}
save(P/'proposal.json',proposal)
print(json.dumps({'proposal':pin(P/'proposal.json'),'observation':pin(O/'observation.json'),'aliases':pin(O/'input-aliases.json'),'partial_files':len(partial),'partial_bytes':sum(x['bytes']for x in partial),'campaign_files_written':0},indent=2))
