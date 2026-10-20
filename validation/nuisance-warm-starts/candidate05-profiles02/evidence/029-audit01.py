from pathlib import Path
import collections,datetime,hashlib,importlib.util,json,math,os,re,socket,subprocess,sys,xml.etree.ElementTree as ET
B=Path('/home/emper/orbit-nuisance-warmstarts');R=B/'source-candidate05';RUN=B/'profiles02';OUT=B/'control/review02/profiles02-outcomes'
cache={}
def need(value,message):
 if not value:raise AssertionError(message)
def sha(path):
 p=Path(path);s=p.stat();identity=lambda a:(a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns,a.st_ctime_ns);key=(str(p),identity(s))
 if key in cache:return cache[key]
 h=hashlib.sha256()
 with p.open('rb')as stream:
  for part in iter(lambda:stream.read(1048576),b''):h.update(part)
 need(identity(s)==identity(p.stat()),'changed while hashing '+str(p));cache[key]=h.hexdigest();return cache[key]
def pin(path):return {'path':str(path),'sha256':sha(path),'bytes':Path(path).stat().st_size}
def verify(record):
 need(sha(record['path'])==record['sha256'],'changed pin '+record['path'])
 if 'bytes'in record:need(Path(record['path']).stat().st_size==record['bytes'],'changed size '+record['path'])
def read(path):
 def pairs(items):
  d={}
  for k,v in items:need(k not in d,'duplicate JSON key '+k);d[k]=v
  return d
 def bad(v):raise ValueError('nonfinite JSON '+v)
 return json.loads(Path(path).read_text(),object_pairs_hook=pairs,parse_constant=bad)
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def save(path,value):
 with Path(path).open('x')as stream:json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
need(sorted(os.sched_getaffinity(0))==[4],'offline review must use CPU4')
need(all(os.environ.get(k)=='1' for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','GOTO_NUM_THREADS')),'offline threads')
need(not (OUT/'independent-review.json').exists(),'review already sealed')
f=read(RUN/'freeze.json');fp=pin(RUN/'freeze.json')
need(fp['sha256']=='cb0a6ce75a68c91d3606b74ed3ec8df65d78b9f85d58c71e3b3d22b42666cc4a','wrong frozen campaign')
need(socket.gethostname()==f['admission']['host']and Path('/proc/sys/kernel/random/boot_id').read_text().strip()==f['admission']['boot_id'],'current host/boot differs')
launch_review_path=B/'control/review02/profiles02-launch/independent-review.json'
need(sha(launch_review_path)=='16dcd4fcb29b273c42398a65dba5b535437501dfbaa151f13e80f688e2e828e4','launch audit changed')
lr=read(launch_review_path);need(fp==lr['freeze'] and lr['status']=='accepted_exact_serial_27_job_launch_only','launch admission binding')
for key in ('preparation','build_record','native','runner','supervisor','checker','python','launch_guard'):verify(f[key])
for record in f['source_files']:verify(record)
prep=read(f['preparation']['path']);need(len(prep['copies'])==1131,'prepared copy count')
for record in prep['copies']:
 need(sha(record['copy'])==record['copy_sha256']==record['sha256']and Path(record['copy']).stat().st_size==record['bytes'],'prepared copy changed')
for group in prep['groups']:
 for point in group['points']:verify(point['profile_template'])
deployment=read(lr['deployment']['path']);verify(lr['deployment'])
need({str(p.relative_to(R)) for p in R.rglob('*')if p.is_file()}==set(deployment['source_inventory']),'candidate files added/removed')
for rel,digest in deployment['source_inventory'].items():need(sha(R/rel)==digest,'candidate file changed '+rel)
build=read(f['build_record']['path'])
for key in ('build_manifest','build_plan'):verify(build[key])
for record in build['libraries']:verify(record)
for rel,digest in build['patched_source'].items():need(sha(Path(build['source_root'])/rel)==digest,'compiled source drift '+rel)
runtime=read(lr['runtime_and_native157_review']['path']);verify(lr['runtime_and_native157_review'])
for key in ('build_result','build_plan','native','manifest','native_test_result','native_test_freeze'):verify(runtime[key])
for suite in runtime['suites']:
 for key in ('junit','result','log'):verify(suite[key])
 cases=list(ET.parse(suite['junit']['path']).getroot().iter('testcase'))
 need(len(cases)==suite['counts']['tests'] and all(c.find(t)is None for c in cases for t in ('failure','error','skipped')),'actual native test counts changed')
need([s['counts']['tests']for s in runtime['suites']]==[106,51]and read(runtime['native_test_result']['path'])['passed']is True,'actual157 gate')
verify(lr['postcheck_controller']);need(lr['postcheck_controller']['sha256']=='a917db49ecdc52187c18c54a9146c9ca16f06d99972333c0777d15998140b64e','postcheck control changed')
run_result=read(RUN/'run-result.json');run_pin=pin(RUN/'run-result.json')
need(run_result['freeze']==fp and run_result['planned']==run_result['completed']==27,'all27 terminal required')
need([x['job_id']for x in run_result['outcomes']]==f['execution_order'],'execution order differs')
index_path=B/'control/profiles02-check-execution-index.json';index=read(index_path);index_pin=pin(index_path)
need(index['freeze_sha256']==fp['sha256']and index['checker_sha256']==f['checker']['sha256']and index['runner_sha256']==lr['postcheck_controller']['sha256'],'postcheck identity')
need(len(index['checks'])==15,'all15 checks required')
guard=load('independent_outcome_guard',f['launch_guard']['path']);checker=load('independent_outcome_checker',f['checker']['path'])
jobs={j['id']:j for j in f['jobs']};attempts=[];prior_finish=None
for outcome in run_result['outcomes']:
 j=jobs[outcome['job_id']];d=Path(j['root']);e=read(d/'execution.json');s=read(d/'supervisor.json');a=read(d/'admission.json')
 need(e['schema']=='orbit-poc-nuisance-warm-profile-execution-v1'and e['job_id']==j['id']and e['status']==outcome['status'],'execution attribution')
 need(e['freeze']==fp and e['preparation']==f['preparation']and e['native_binary_sha256']==f['native']['sha256'],'execution frozen context')
 need(e['config_sha256']==j['profile_sha256']==sha(d/'config.xml')and e['supervisor_sha256']==sha(d/'supervisor.json'),'config/supervisor binding')
 need(e['input_inventory']==j['input_inventory'],'input attribution')
 for key in ('group','point','treatment','mode','context_sha256'):need(e[key]==j[key],'treatment attribution '+key)
 need(e['inputs_unchanged']is True and e['identity_error']is None,'input identity failure')
 need(e['native_launch_mode']==f['native_launch_mode']==guard.MODE,'launch mode attribution')
 for key in ('host','boot_id','cpu','threads'):need(a[key]==f['admission'][key],'launch admission drift '+key)
 need(a['native_processes']==[],'competing native process at admission')
 for record in e['input_inventory']:verify(record)
 names=[]
 for record in e['output_inventory']:
  rel=Path(record['path']);need(not rel.is_absolute()and '..'not in rel.parts,'output path escape');verify({**record,'path':str(d/rel)});names.append(record['path'])
 actual={str(p.relative_to(d))for p in d.rglob('*')if p.is_file()}
 need(len(names)==len(set(names))and set(names)|{'execution.json'}==actual,'complete unique output inventory')
 need(not any(p.is_symlink()for p in d.rglob('*')),'output alias')
 start=datetime.datetime.fromisoformat(e['started_at']);finish=datetime.datetime.fromisoformat(e['finished_at']);need(finish>=start,'negative wall interval')
 if prior_finish:need(start>=prior_finish,'overlapping attempts')
 prior_finish=finish
 expected_env=dict(j['environment'])
 if e['source_donor']:
  donor=e['source_donor'];need(j['treatment']=='warm'and donor['root']==jobs[j['source_donor_job_id']]['root'],'wrong donor')
  verify(donor['payload']);verify(donor['companion']);expected_env['ORBIT_POC_NUISANCE_WARM_INPUT_SHA256']=donor['payload']['sha256']
 need(e['effective_environment']==expected_env,'effective environment differs')
 item={'job_id':j['id'],'group':j['group'],'point':j['point'],'treatment':j['treatment'],'mode':j['mode'],'status':e['status'],'returncode':e['returncode'],'elapsed_seconds':e['elapsed_seconds'],'execution':pin(d/'execution.json'),'supervisor':pin(d/'supervisor.json'),'admission':pin(d/'admission.json'),'input_files_rehashed':len(j['input_inventory']),'output_files_rehashed':len(names),'timed_out':e['timed_out']}
 if e['status']=='blocked':
  need(j['treatment']=='warm'and j['source_donor_job_id']and e['source_donor']is None,'nonwarm/partlyimported block')
  need(e['command']is None and e['launch_binding']is None and e['returncode']is None and e['elapsed_seconds']==0 and e['timed_out']is False,'blocked execution must be unlaunched')
  need(set(names)=={'admission.json','config.xml','supervisor.json'},'blocked job native artifacts')
  need(s=={'elapsed_seconds':0.0,'owned_process_group_cleaned':True,'reason':e['blocked_reason'],'returncode':None,'status':'blocked'},'blocked supervisor')
  item.update(native_launched=False,blocked_reason=e['blocked_reason'],donor_execution=pin(Path(jobs[j['source_donor_job_id']]['root'])/'execution.json'),strict_profile_accepted=False)
 else:
  need(s['schema']=='orbit-poc-segmented-supervision-v1'and s['status']==e['status']and s['returncode']==e['returncode']and s['elapsed_seconds']==e['elapsed_seconds'],'supervisor classification')
  need(e['timed_out']==(s['status']=='timeout')and e['owned_process_group_cleaned']is True and s['owned_process_group_cleaned']is True,'timeout/cleanup classification')
  cleanup=s['cleanup'];need(cleanup['verified']is True and cleanup['remaining']==[]and cleanup['empty_tree_certificate']=='kernel_ECHILD','owned process tree not clean')
  for owned in [s['worker'],*s['tracked_owned_processes']]:
   try:current=Path('/proc')/str(owned['pid'])/'stat';fields=current.read_text().rsplit(')',1)[1].split()
   except FileNotFoundError:continue
   need(int(fields[19])!=owned['start_ticks'],'completed owned process identity remains present')
  need(s['boot_id']==f['admission']['boot_id']and s['helper_sha256']==f['supervisor']['sha256'],'supervisor host/source')
  plan=read(d/'supervisor.plan.json');need(sha(d/'supervisor.plan.json')==s['plan_sha256'],'supervisor plan hash')
  launch_receipt=read(d/'native-launch.json');binding=guard.checked_launch(e['launch_binding'],launch_receipt,expected_environment=expected_env)
  need(binding['freeze']==fp and binding['native']==f['native']and binding['guard']==f['launch_guard']and binding['job_id']==j['id']and binding['root']==str(d)and binding['config']==pin(d/'config.xml'),'launch binding attribution')
  cmd=guard.launch_command(f['python']['path'],f['launch_guard']['path'],e['launch_binding'])
  need(e['command']==s['argv']==plan['argv']==cmd and plan['cwd']==plan['working_directory']==str(d),'supervised command/cwd')
  need(launch_receipt['pid']==s['worker']['pid'],'actual native pid differs from supervised worker')
  need(plan['receipt_path']==str(d/'supervisor.json')and plan['log_path']==str(d/'profile.log')and plan['boot_id']==s['boot_id']and plan['helper_sha256']==s['helper_sha256'],'supervision attribution')
  for key in ('timeout_seconds','max_process_tree_rss_bytes','min_free_disk_bytes'):need(plan[key]==f['limits'][key],'supervision limit changed')
  log=(d/'profile.log').read_text();errors=[line for line in log.splitlines()if 'Error' in line or 'ERROR' in line or 'Nuisance warm state:' in line]
  item.update(native_launched=True,native_launch=pin(d/'native-launch.json'),launch_binding=e['launch_binding'],supervisor_plan=pin(d/'supervisor.plan.json'),profile_log=pin(d/'profile.log'),cleanup_verified=True,cleanup=cleanup,signals_received=s['signals_received'],peak_process_tree_rss_bytes=s['peak_process_tree_rss_bytes'],logged_error_lines=errors)
  item['native_failure_messages']=[re.sub(r'\x1b\[[0-9;]*m','',line).strip()for line in log.splitlines()if 'Nuisance warm state:'in line]
  try:
   datum=guard.datum_evidence(d);item['native_datum_evidence']=datum;item['datum_kinds']=dict(collections.Counter(x['kind']for x in datum))
  except Exception as error:item['native_datum_error']=type(error).__name__+': '+str(error)
  if e['status']=='complete':
   need(type(e['returncode'])is int and e['returncode']==0 and e['timed_out']is False and '=== Finished GROOPS ==='in log,'false completed native classification')
   need(cleanup['signals']==[]and cleanup['hard_kill']is False and s['signals_received']==[]and s['elapsed_seconds']<f['limits']['timeout_seconds']and s['peak_process_tree_rss_bytes']<f['limits']['max_process_tree_rss_bytes'],'completed attempt suffered signals/resource limit')
   try:
    inspected=checker.inspect(d)
    item.update(strict_profile_accepted=True,iterations=inspected['iterations'],last_two_maximum_updates_m=[x['maximum_update_m']for x in inspected['profile']['history'][-2:]],objective=inspected['objective'],prior_evidence=inspected['prior_evidence'],seed_companion=pin(d/'seed.bin.json')if inspected['companion']else None,seed=pin(d/'seed.bin')if inspected['companion']else None,donor=inspected.get('donor'),retained_rows=inspected['rows'])
   except Exception as error:item.update(strict_profile_accepted=False,strict_profile_error=type(error).__name__+': '+str(error))
  else:item['strict_profile_accepted']=False
 attempts.append(item)
 print(json.dumps({'audited':j['id'],'status':e['status'],'strict_profile_accepted':item['strict_profile_accepted']}),flush=True)
checks=[];ordinal=0
for group in ('pulses','density','pulses-bias-priors'):
 for name,roles,inert in [('inert-full',['disabled_source','cold_source_full'],True),('inert-clock',['disabled_source','cold_source_clock'],True),('warm-source-full',['cold_source_full','warm_source_full','cold_source_repeat_full'],False),('warm-target-full',['cold_target_full','warm_target_full','cold_target_repeat_full'],False),('warm-target-clock',['cold_target_full','warm_target_clock','cold_target_repeat_full'],False)]:
  label=group+'--'+name;roots=[str(RUN/(group+'--'+role))for role in roles];original=B/'profiles02-checks'/(label+'.json');auth=index['checks'][ordinal];ordinal+=1
  expected_cmd=['/usr/bin/taskset','-c','0',f['python']['path'],'-s','-B',f['checker']['path'],*roots,*(['--inert']if inert else []),'--output',str(original)]
  need(auth['name']==label and auth['output']==str(original)and auth['command']==expected_cmd and auth['sha256']==sha(original),'actual comparison invocation/index')
  result_path=OUT/(label+'.json');log_path=OUT/(label+'.log');argv=[f['python']['path'],'-s','-B',f['checker']['path'],*roots,*(['--inert']if inert else []),'--output',str(result_path)]
  need(not result_path.exists()and not log_path.exists(),'replay output already exists')
  env={k:v for k,v in os.environ.items()if not k.startswith(('ORBIT_POC_','LD_'))and k not in('PYTHONPATH','PYTHONHOME')};env['LD_LIBRARY_PATH']=str(B/'toolchain-01/lib')
  with log_path.open('x')as stream:proc=subprocess.run(argv,cwd=R,env=env,stdout=stream,stderr=subprocess.STDOUT,check=False)
  result=read(result_path);need(type(result['passed'])is bool and proc.returncode==(0 if result['passed']else 1),'independent checker returncode')
  need(auth['returncode']==proc.returncode and read(original)==result,'independent/author comparison differs')
  need(result['roots']==roots and result['checker_sha256']==f['checker']['sha256']and result['release_authority']is False and result['accepted_orbit_covariance']is False,'checker scientific scope/attribution')
  checks.append({'label':label,'passed':result['passed'],'error':result.get('error'),'author_result':pin(original),'author_log':pin(original.with_suffix('.log')),'independent_result':pin(result_path),'independent_log':pin(log_path),'command':argv,'returncode':proc.returncode,'metrics':{k:v for k,v in result.items()if k not in('execution_receipts','roots','checker_sha256','schema')}})
  print(json.dumps({'replayed':label,'passed':result['passed'],'error':result.get('error')}),flush=True)
for key in ('preparation','build_record','native','runner','supervisor','checker','python','launch_guard'):verify(f[key])
for record in f['source_files']:verify(record)
for rel,digest in deployment['source_inventory'].items():need(sha(R/rel)==digest,'source drift during audit')
need({str(p.relative_to(R))for p in R.rglob('*')if p.is_file()}==set(deployment['source_inventory']),'candidate inventory drift during audit')
for a in attempts:
 for key in ('execution','supervisor','admission'):verify(a[key])
 e=read(a['execution']['path']);d=Path(a['execution']['path']).parent
 for record in e['input_inventory']:verify(record)
 for record in e['output_inventory']:verify({**record,'path':str(d/record['path'])})
verify(run_pin);verify(index_pin)
counts=dict(collections.Counter(a['status']for a in attempts));passed=sum(c['passed']for c in checks);strict=sum(a['strict_profile_accepted']for a in attempts)
accepted=counts=={'complete':27}and strict==27 and passed==15
by_id={a['job_id']:a for a in attempts};timings=[]
for group in ('pulses','density','pulses-bias-priors'):
 for role,cold_role in [('warm_source_full','cold_source_full'),('warm_target_full','cold_target_full'),('warm_target_clock','cold_target_full')]:
  warm=by_id[group+'--'+role];cold=by_id[group+'--'+cold_role]
  entry={'group':group,'warm_job':warm['job_id'],'cold_job':cold['job_id'],'warm_mode':warm['mode'],'cold_mode':cold['mode'],'warm_status':warm['status'],'cold_status':cold['status']}
  if warm['strict_profile_accepted']and cold['strict_profile_accepted']:
   entry.update(cold_iterations=cold['iterations'],warm_iterations=warm['iterations'],iterations_saved=cold['iterations']-warm['iterations'],cold_elapsed_seconds=cold['elapsed_seconds'],warm_elapsed_seconds=warm['elapsed_seconds'],cold_to_warm_elapsed_ratio=cold['elapsed_seconds']/warm['elapsed_seconds'])
  timings.append(entry)
receipt={'schema':'independent-warm-profiles02-outcome-review-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'status':'accepted_27_completed_and_15_comparisons'if accepted else 'accepted_truthful_terminal_attribution_with_scientific_rejections','attribution_accepted':True,'scientific_accepted':accepted,'wholefit_admission':False,'fullfit_admission':False,'release_authority':False,'accepted_orbit_covariance':False,'freeze':fp,'launch_admission':pin(launch_review_path),'preparation':f['preparation'],'run_result':run_pin,'postcheck_execution_index':index_pin,'postcheck_controller':lr['postcheck_controller'],'native':f['native'],'native157_review':lr['runtime_and_native157_review'],'deployment':lr['deployment'],'thresholds':f['thresholds'],'limits':f['limits'],'outcomes':{'terminal_records':len(attempts),'status_counts':counts,'native_calls':sum(a['native_launched']for a in attempts),'strict_profiles':strict,'timeouts':sum(a['timed_out']for a in attempts),'blocked_unlaunched':sum(not a['native_launched']for a in attempts)},'checks':{'required':15,'independently_replayed':15,'passed':passed,'rejected':15-passed,'details':checks},'attempts':attempts,'protected_counts':{'candidate_files':len(deployment['source_inventory']),'frozen_source_files':len(f['source_files']),'built_source_files':len(build['patched_source']),'runtime_libraries':len(build['libraries']),'unchanged_native_cases':157},'blocking_issues':([]if accepted else ['The prescribed fixed-trajectory scientific prerequisites are not all accepted; see exact per-attempt and comparison rejections.']),'limitations':['The fixed-trajectory diagnostic covariance comparisons do not establish an accepted orbit covariance or full nonlinear convergence.','Whole-fit preparation and launch require separate independent admission against this exact actual-outcome receipt; this audit does not admit a native whole fit.','Elapsed times and iteration counts are measured single attempts in this frozen protocol, not general performance guarantees.'],'review_execution':{'cpu':sorted(os.sched_getaffinity(0)),'threads':1,'native_runs':0,'compiler_runs':0,'signals':0,'source_input_benchmark_changes':0},'audit_script':pin(__file__)}
receipt['matched_measurements']={'comparisons':timings,'timing_scope':'One measured attempt per frozen treatment; no statistical speedup claim. Clock warm targets use the prescribed full-mode cold target baseline. Correctness acceptance is distinct from useful performance.','general_speedup_established':False,'wholefit_launch_warranted_by_this_audit':False}
receipt['outcomes']['native_failure_messages']=dict(collections.Counter(message for a in attempts if a['status']!='complete'for message in a.get('native_failure_messages',[])))
identities=[]
for group in ('pulses','density','pulses-bias-priors'):
 source=by_id[group+'--cold_source_full'];target=by_id[group+'--cold_target_full']
 if source['strict_profile_accepted']and target['strict_profile_accepted']:
  a=read(source['seed_companion']['path']);b=read(target['seed_companion']['path'])
  identities.append({'group':group,'source_companion':source['seed_companion'],'target_companion':target['seed_companion'],'fields':{key:{'source':a[key],'target':b[key],'equal':a[key]==b[key]}for key in('mode','context_sha256','chart_sha256','cold_origin_sha256','counts')}})
receipt['cold_export_source_target_identity']={'full_mode_pairs':identities,'scope':'Direct comparison of separately completed cold full-mode exports. This does not identify an unlogged clock-mode target hash or establish a repair.'}
save(OUT/'independent-review.json',receipt)
print(json.dumps({'receipt':pin(OUT/'independent-review.json'),'scientific_accepted':accepted,'outcomes':receipt['outcomes'],'checks_passed':passed}),flush=True)
