#!/usr/bin/env python3
"""Read-only, compact capture of the stopped original150 campaign after boot change."""
from pathlib import Path
import datetime,hashlib,json,os
BASE=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume')
ROOT=BASE/'benchmark-01'; REC=BASE/'recovery-20261015-02'
OUT=Path('/mnt/d/orbit-segmented-v4/control/original150-boot-interruption-20261016-01')
def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(x): return sha(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def read(p): return json.loads(Path(p).read_text())
def pin(p):
 p=Path(p); b=p.read_bytes(); return {'path':str(p),'bytes':len(b),'sha256':sha(b)}
def save(name,data):
 p=OUT/name; p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('xb') as f: f.write(data)
 return {'path':str(p),'bytes':len(data),'sha256':sha(data)}
def copy(p,name):
 p=Path(p); before=p.stat(); b=p.read_bytes(); after=p.stat()
 assert (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns)
 return {'source':{'path':str(p),'bytes':len(b),'sha256':sha(b)},'copy':save(name,b)}
def proc(pid):
 p=Path('/proc')/str(pid)
 try:
  raw=(p/'stat').read_text(); fields=raw[raw.rfind(')')+2:].split()
  return {'pid':pid,'present':True,'state':fields[0],'parent':int(fields[1]),'start_ticks':int(fields[19])}
 except FileNotFoundError: return {'pid':pid,'present':False}
assert not OUT.exists(); OUT.mkdir()
boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(); observed=datetime.datetime.now(datetime.timezone.utc).isoformat()
launch=read(REC/'launch.json'); supervision=read(REC/'supervision.json')
assert boot != launch['boot_id']
processes=[{'expected':launch['process'],'observed':proc(launch['process']['pid'])},{'expected':supervision['wrapper_process'],'observed':proc(supervision['wrapper_process']['pid'])}]
assert all(not x['observed']['present'] for x in processes)
manifest=read(ROOT/'manifest.json'); plan=read(ROOT/'plan.json'); config=read('/mnt/d/orbit-numerics-v3.1/deployment-final/benchmark-01/config.json')
assert len(manifest['attempts'])==150 and manifest['attempts']==plan['attempts']
prior=read('/mnt/d/orbit-segmented-v4/control/original150-retention-record-independent-review-02.json')
rows=[]; copies=[]; partial=[]; cases={x['case_id']:x for x in manifest['cases']}
for a in manifest['attempts']:
 d=ROOT/'attempts'/a['attempt_id']; row={**a,'directory_exists':d.exists()}
 if (d/'result-record.json').exists():
  idx=read(d/'result-record.json'); result=read(d/'result.json'); assert idx['result']['sha256']==pin(d/'result.json')['sha256']
  assert idx['attempt_id']==a['attempt_id'] and idx['status']==result['status']
  row.update(state='terminal_checkpoint_present',status=result['status'],result=pin(d/'result.json'),index=pin(d/'result-record.json'))
  for n in ['result.json','result-record.json']: copies.append(copy(d/n,'original150/checkpoints/'+a['attempt_id']+'/'+n))
 elif d.exists() and any(d.iterdir()):
  row['state']='interrupted_without_terminal_checkpoint'; partial.append(a)
 else: row['state']='not_started'
 rows.append(row)
assert [r['state'] for r in rows[:7]]==['terminal_checkpoint_present']*6+['interrupted_without_terminal_checkpoint']
assert all(r['state']=='not_started' for r in rows[7:]); assert len(partial)==1
for old,row in zip(prior['first_five_unchanged'],rows[:5]):
 assert old['attempt_id']==row['attempt_id'] and old['result']['sha256']==row['result']['sha256'] and old['record']['sha256']==row['index']['sha256']
assert rows[5]['result']['sha256']=='e2dcd71f4338abaaa1a86086d482cf4588559e8ce6d7b51ddee657df456e6c44'
a=partial[0]; d=ROOT/'attempts'/a['attempt_id']; case=cases[a['case_id']]; runtime=manifest['new_runtime']
job={**case['fit_request'],'id':a['attempt_id'],'kind':'fit','split':'numerics','numerics_profile':a['profile'],'numerics_manifest_hash':manifest['manifest_hash'],'input_manifest_hash':case['input_manifest_hash'],'source_hash':runtime['source_sha256'],'protocol_hash':manifest['manifest_hash'],'backend':{'groops_executable':runtime['native']['path'],'command_timeout_seconds':7200.,'retain_native_diagnostics':True},'expected_native_binary_sha256':runtime['native']['sha256'],'numerical_controls':config['controls']}
assert read(d/'request.json')==job==read(d/'worker-request.json')
for n in ['result.json','result-record.json','worker-result.json','native_runtime.json','outer_iterations.json']: assert not (d/n).exists()
files=[]
for p in sorted(d.rglob('*')):
 if p.is_file():
  s=p.stat(); files.append({'relative':str(p.relative_to(d)),'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'mtime_utc':datetime.datetime.fromtimestamp(s.st_mtime,datetime.timezone.utc).isoformat()})
last=sorted(files,key=lambda x:x['mtime_ns'])[-20:]
selected=['request.json','worker-request.json','resource-guard.json','worker.log','point-001-initial/profile.log','point-001-initial/qr.7.profile.json','point-001-initial/qr.7.diagnostics.json','point-001-initial/qr.7.nuisance_line_search.json']
for n in selected: copies.append(copy(d/n,'original150/partial-attempt/'+n))
controller=ROOT/'controller/20261016T003956Z-5b688772d4974b0284af846c67d28cce.json'; c=read(controller)
assert c['status']=='running' and c['phase']=='run' and c['initial_report']['terminal_attempts']==6
for p in [REC/'launch.json',REC/'supervision.json',REC/'startup-resume-02.json',REC/'campaign-adapter02.json',REC/'continuation-prelaunch02.json',REC/'campaign.log',controller,Path('/mnt/d/orbit-segmented-v4/control/original150-retention-record-independent-review-02.json'),Path('/mnt/d/orbit-segmented-v4/control/original150-continuation-independent-review-02.json')]: copies.append(copy(p,'original150/controls/'+p.name))
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==boot
report={'schema':'orbit-poc-original150-boot-interruption-observation-v1','observed_at':observed,'previous_boot_id':launch['boot_id'],'current_boot_id':boot,'boot_changed':True,'recorded_processes':processes,'old_journals_preserved':True,'old_journals_running_status_is_stale':True,'process_cleanup_verified':False,'cleanup_note':'The old boot and recorded processes ended. No terminal owned-cleanup receipt was produced; this observation is not a fabricated cleanup receipt.','expected_attempts':150,'terminal_checkpoints':6,'interrupted_without_checkpoint':1,'not_started':143,'attempts':rows,'new_attempt_after_sixth':a,'partial_request_matches_frozen_job':True,'partial_request_hash':canonical(job),'partial_native_runtime':runtime['native'],'partial_stage':'Initial-point native nuisance profiling; iteration 7 saved diagnostic output, iteration 8 row output present; no terminal objective, convergence or covariance result.','partial_files':files,'last_saved_files_by_filesystem_mtime':last,'mtime_caveat':'Filesystem modification timestamps identify saved artifacts; they are not elapsed runtime, boot-end time or a measured process-tree peak.','parent_wall_time_seconds':None,'parent_peak_memory_bytes':None,'parent_returncode':None,'final_objective':None,'converged':False,'covariance_authorized':False,'retry_authorized':False,'native_substitution':False,'controller_phase':c['phase'],'controller_status_recorded':c['status'],'controller_started_at':c['started_at'],'resource_guard_checked_at':read(d/'resource-guard.json')['checked_at'],'inputs':{'plan':pin(ROOT/'plan.json'),'manifest':pin(ROOT/'manifest.json'),'source':pin(__file__)},'copies':copies,'scope':'Compact read-only interruption audit. No original file, result, checkpoint, source, binary or data input was modified. Large row/factor payloads remain outside this packet; their stat inventory is included without claiming byte verification. No whole input tree was rehashed and no process was launched or stopped.'}
save('observation.json',(json.dumps(report,indent=2,sort_keys=True)+'\n').encode())
print(json.dumps({'observation':pin(OUT/'observation.json'),'terminal_checkpoints':6,'partial_attempt':a['attempt_id'],'last_saved':last[-1]}))
