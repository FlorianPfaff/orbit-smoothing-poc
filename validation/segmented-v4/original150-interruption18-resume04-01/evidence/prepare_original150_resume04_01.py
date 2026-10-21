from pathlib import Path
import json,hashlib,datetime,copy,os,fcntl,shutil,importlib.util
C=Path('/mnt/d/orbit-segmented-v4/control');BASE=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume');OLD=BASE/'recovery-20261016-01';NEW=BASE/'recovery-20261016-02';B=BASE/'benchmark-01'
def read(p):return json.loads(Path(p).read_bytes())
def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb')as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def save(p,v):
 with p.open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
def load(path,name):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
assert sha(OLD/'resume-plan03.json')=='68b2ea578af4700165688c04e5b043da330755051006a9718257533bbee7bf80'
post=read(C/'original150-eighteen-prefix-postappend01.json');assert post['passed']and post['terminal_attempts']==18
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip();assert boot=='e0523d0a-e0c2-404b-88d2-57ba4367a15b'
NEW.mkdir(exist_ok=False)
ret_old=read(OLD/'retention-recovery-plan03.json');ret=copy.deepcopy(ret_old);ret['boot_id']=boot;ret['campaign_adapter_receipt']=str(NEW/'campaign-adapter04.json')
prior=read(C/'original150-tenth-terminal-independent-review01.json');ret['stopped_processes']=[{k:x[k]for k in ['pid','start_ticks']}for x in prior['live_control_chain']]
for x in ret['stopped_processes']:assert not Path('/proc',str(x['pid'])).exists()
ret_path=NEW/'retention-recovery-plan04.json';save(ret_path,ret)
helper=C/'original150_retention_recovery02.py';assert sha(helper)=='bb23360e9cd9af6219e6771fca90c834288f9467e3f1f55b38eca8552fd49c61'
load(helper,'frozen_metadata_check').check_plan(ret_path,sha(ret_path))
changed=[k for k in ret if ret[k]!=ret_old[k]];assert sorted(changed)==['boot_id','campaign_adapter_receipt','stopped_processes']
sixth_fields=['config','existing_checkpoints','failure','manifest','prepared_at','source_sha256']
for k in sixth_fields:assert ret[k]==ret_old[k]
six=read(C/'original150-retention-plan03-independent-review01.json')['actual_sixth_exactly_matches_approved_proposal']
for x in six:assert pin(x['path'])==x
save(NEW/'retention-plan-delta04.json',{'schema':'orbit-poc-original150-retention-plan-delta-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'old_plan':pin(OLD/'retention-recovery-plan03.json'),'new_plan':pin(ret_path),'changed_fields':changed,'sixth_derivation_fields_unchanged':sixth_fields,'sixth_actual_bytes_unchanged':six,'helper':pin(helper),'new_eighteenth_postappend':pin(C/'original150-eighteen-prefix-postappend01.json'),'no_campaign_launch':True})
config=read('/mnt/d/orbit-numerics-v3.1/deployment-final/benchmark-01/config.json');res=config['resources'];mem={x.split(':')[0]:int(x.split(':')[1].split()[0])*1024 for x in Path('/proc/meminfo').read_text().splitlines()if x.startswith(('MemAvailable:','MemTotal:'))};free=shutil.disk_usage(B).free;back=shutil.disk_usage(res['physical_backing_path']).free
assert mem['MemAvailable']>=res['minimum_available_bytes']and free>=res['minimum_free_output_bytes']and back>=res['minimum_free_backing_bytes']and 30 in os.sched_getaffinity(0)
conflicts=[];errors=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  raw=(p/'cmdline').read_bytes();argv=[x.decode(errors='replace')for x in raw.split(b'\0')if x];comm=(p/'comm').read_text().strip()
  if comm.startswith('groops')or any(Path(x).name in {'launch_original150_resume.py','original150_retention_recovery02.py','run_numerics_campaign.py','run_numerics_worker.py'}for x in argv):conflicts.append({'pid':int(p.name),'comm':comm,'argv':argv})
 except (FileNotFoundError,ProcessLookupError):pass
 except PermissionError as e:errors.append({'pid':int(p.name),'error':str(e)})
assert not conflicts and not errors
locks=[]
for q in [B/'numerics.lock',B/'controller/numerics.lock']:
 assert q.is_file()and not q.is_symlink();fd=os.open(q,os.O_RDONLY);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);s=os.fstat(fd);locks.append({'path':str(q),'device':s.st_dev,'inode':s.st_ino,'unlocked_at_check':True});os.close(fd)
admission={'schema':'orbit-poc-original150-current-host-admission-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'boot_id':boot,'memory':mem,'free_output_bytes':free,'free_backing_bytes':back,'cpu':30,'available_cpus':sorted(os.sched_getaffinity(0)),'known_native_conflicts':conflicts,'process_visibility_errors':errors,'locks':locks,'limits_unchanged':res,'postappend':pin(C/'original150-eighteen-prefix-postappend01.json'),'full_input_runtime_startup_still_required':True,'no_launch':True}
save(NEW/'continuation-prelaunch04.json',admission)
old=read(OLD/'resume-plan03.json');plan=copy.deepcopy(old);plan['root']=str(NEW);plan['boot_id']=boot
replace={str(OLD/'startup-resume-03.json'):str(NEW/'startup-resume-04.json'),str(OLD/'retention-recovery-plan03.json'):str(ret_path),sha(OLD/'retention-recovery-plan03.json'):sha(ret_path)}
plan['command']=[replace.get(x,x)for x in plan['command']]
extra=[C/'original150-interruption18-root-review01.json',C/'original150-interruption18-alias-root-review01.json',C/'original150-interrupted-attempt18-proposal01/proposal.json',C/'original150-interrupted-attempt18-plan01.json',C/'original150-interrupted-attempt18-apply01.json',C/'original150-eighteen-prefix-postappend01.json',C/'original150-boot-interruption-20261016-02/observation.json',C/'original150-boot-interruption-20261016-02/input-aliases.json',C/'apply_original150_interrupted_append03.py',C/'prepare_original150_resume04_01.py',ret_path,NEW/'retention-plan-delta04.json',NEW/'continuation-prelaunch04.json']
for x in post['terminal_prefix']:
 for key in ['result','index']:extra.append(Path(x[key]['path']))
art={x['path']:x for x in old['artifacts']}
for q in extra:
 r=pin(q)
 if r['path']in art:assert art[r['path']]==r
 art[r['path']]=r
plan['artifacts']=list(art.values())
for x in plan['artifacts']:assert pin(x['path'])==x
for name in ['launch.json','supervision.json','campaign.log','startup-resume-04.json','campaign-adapter04.json']:assert not(NEW/name).exists()
plan_path=NEW/'resume-plan04.json';save(plan_path,plan)
launch=C/'launch_original150_resume.py';load(launch,'unchanged_launcher').checked_plan(plan_path,sha(plan_path))
receipt={'schema':'orbit-poc-original150-resume04-preparation-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'plan':pin(plan_path),'retention_plan':pin(ret_path),'retention_delta':pin(NEW/'retention-plan-delta04.json'),'admission':pin(NEW/'continuation-prelaunch04.json'),'launcher':pin(launch),'helper':pin(helper),'artifact_count':len(plan['artifacts']),'all_artifacts_reverified':True,'old_command':old['command'],'new_command':plan['command'],'frozen_config_source_native_unchanged':True,'launch_argv':['/usr/bin/python3',str(launch),'--plan',str(plan_path),'--sha256',sha(plan_path)],'launched':False,'scope':'Fresh boot/output metadata only. Existing original numerical workers/configuration/seeds and control helper are unchanged. Both metadata validators passed; complete frozen startup remains mandatory after reviewed launch. Continue after18 terminal checkpoints, without retry/replacement.'}
save(C/'original150-resume04-preparation01.json',receipt);print(json.dumps({'receipt':pin(C/'original150-resume04-preparation01.json'),'plan':pin(plan_path),'artifact_count':len(plan['artifacts'])},indent=2))
