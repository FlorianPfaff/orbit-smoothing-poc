#!/usr/bin/env python3
"""Propose exact append bytes; never write campaign outputs or run a fit."""
from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict,make_dataclass
import ast,hashlib,json,datetime
BASE=Path('/mnt/d/orbit-numerics-v3.1/benchmark-d-volume'); ROOT=BASE/'benchmark-01'
CONTROL=Path('/mnt/d/orbit-segmented-v4/control')
OBS=CONTROL/'original150-boot-interruption-20261016-01/observation.json'
OUT=CONTROL/'original150-interrupted-append-proposal01'
SOURCE=Path('/mnt/d/orbit-numerics-v3.1/source-snapshots/runtime-553ad084a7165b045f8f/src/orbit_poc/numerics/protocol.py')
CONFIG=Path('/mnt/d/orbit-numerics-v3.1/deployment-final/benchmark-01/config.json')
def enc(x): return (json.dumps(x,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def read(p): return json.loads(Path(p).read_text())
def sha(b): return hashlib.sha256(b).hexdigest()
def canonical(x): return sha(json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def pin(p):
 p=Path(p); b=p.read_bytes(); return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
assert not OUT.exists(); OUT.mkdir()
o=read(OBS); assert o['terminal_checkpoints']==6 and o['interrupted_without_checkpoint']==1 and o['boot_changed']
assert Path('/proc/sys/kernel/random/boot_id').read_text().strip()==o['current_boot_id']
manifest=read(ROOT/'manifest.json'); config=read(CONFIG); attempt=manifest['attempts'][6]; case=next(c for c in manifest['cases'] if c['case_id']==attempt['case_id'])
assert attempt==o['new_attempt_after_sixth']
assert pin(SOURCE)['sha256']=='1435ad9cf8b4fecc81c688ec5fed9182ed630365d9db75e22846dc4badd36769'
tree=ast.parse(SOURCE.read_text()); function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='attempt_job')
mod=ast.Module(body=[function],type_ignores=[]); ast.fix_missing_locations(mod); ns={'asdict':asdict}; exec(compile(mod,str(SOURCE),'exec'),ns)
Controls=make_dataclass('FrozenControls',[(k,object) for k in config['controls']])
job=ns['attempt_job'](SimpleNamespace(controls=Controls(**config['controls'])),manifest,case,attempt)
d=ROOT/'attempts'/attempt['attempt_id']; assert read(d/'request.json')==job==read(d/'worker-request.json')
request_hash=canonical(job); assert request_hash==o['partial_request_hash']
for item in o['attempts'][:6]:
 assert pin(item['result']['path'])==item['result']; assert pin(item['index']['path'])==item['index']
for p in [ROOT/'manifest.json',ROOT/'plan.json']:
 expected=o['inputs']['manifest' if p.name=='manifest.json' else 'plan']; assert pin(p)==expected
for copied in o['copies']: assert pin(copied['source']['path'])==copied['source']
for f in o['partial_files']:
 p=d/f['relative']; s=p.stat(); assert s.st_size==f['bytes'] and s.st_mtime_ns==f['mtime_ns']
assert pin(manifest['new_runtime']['native']['path'])['sha256']==manifest['new_runtime']['native']['sha256']
receipt_path=d/'controller-boot-interruption.json'; result_path=d/'result.json'; index_path=d/'result-record.json'
for p in [receipt_path,result_path,index_path,d/'worker-result.json']: assert not p.exists()
receipt={'schema':'orbit-poc-original150-boot-interruption-recovery-v1','prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'attempt_id':attempt['attempt_id'],'outcome':'interrupted','failure_scope':'host_boot_changed_before_terminal_checkpoint','request_hash':request_hash,'manifest_hash':manifest['manifest_hash'],'configuration':pin(CONFIG),'manifest':pin(ROOT/'manifest.json'),'source_sha256':manifest['new_runtime']['source_sha256'],'native':manifest['new_runtime']['native'],'dependency_runtime_identity':manifest['new_runtime'],'archived_protocol':pin(SOURCE),'helper':pin(__file__),'interruption_observation':pin(OBS),'previous_boot_id':o['previous_boot_id'],'observed_boot_id':o['current_boot_id'],'numerical_rerun':False,'covariance_authorized':False,'old_journals_preserved':True,'process_cleanup_verified':False,'parent_harness_metrics_available':False,'measurements':'Parent harness wall time, peak process-tree RSS, return code, worker PID and minima were not checkpointed. They remain null. Filesystem timestamps and partial native profile values are not substituted.','preservation':'Every existing checkpoint, request, raw partial output and old running journal remains unchanged. No compaction, rerun, binary substitution or numerical change.','verification_scope':'Exact archived attempt_job function, pinned plan/manifest/config and native binary bytes, six checkpoint identities, compact raw evidence bytes and partial-file stat inventory. The complete frozen dependency/input trees are not rehashed by this data-only proposal; unchanged startup verification is required before any continuation.'}
receipt_bytes=enc(receipt)
artifacts=[{'path':str(receipt_path),'sha256':sha(receipt_bytes),'role':'controller_boot_interruption_recovery'}, {'path':str(OBS),'sha256':pin(OBS)['sha256'],'role':'boot_interruption_observation'}]
for name,role in [('resource-guard.json','pre_attempt_resource_guard'),('worker.log','partial_worker_log'),('point-001-initial/profile.log','partial_native_profile_log'),('point-001-initial/qr.7.profile.json','partial_nuisance_profile_diagnostic'),('point-001-initial/qr.7.diagnostics.json','partial_rank_diagnostic')]:
 p=d/name; artifacts.append({'path':str(p),'sha256':pin(p)['sha256'],'role':role})
result={'status':'interrupted','converged':False,'covariance_valid':False,'error':'Host boot changed before a terminal worker result and parent checkpoint were saved. Raw initial-point nuisance-profile outputs are retained; this attempt is not retried.','elapsed_seconds':None,'final_objective':None,'request_hash':request_hash,'numerics_profile':attempt['profile'],'numerics_manifest_hash':manifest['manifest_hash'],'input_manifest_hash':case['input_manifest_hash'],'artifacts':artifacts,'harness_execution':{'elapsed_seconds':None,'peak_process_tree_rss_bytes':None,'returncode':None,'pid':None,'minimum_free_output_bytes':None,'minimum_free_physical_backing_bytes':None,'resource_limit_status':None,'process_group_isolated':None,'runtime':manifest['new_runtime'],'log':{'path':str(d/'worker.log'),'sha256':pin(d/'worker.log')['sha256']},'measurement':'Unavailable after host interruption; no elapsed-time or memory estimate reconstructed from timestamps or partial native diagnostics.'},'recovery':{'outcome':'interrupted','numerical_rerun':False,'accepted_covariance':False,'observation':pin(OBS),'receipt':{'path':str(receipt_path),'sha256':sha(receipt_bytes)}}}
result_bytes=enc(result)
index={'attempt_id':attempt['attempt_id'],'case_id':attempt['case_id'],'profile':attempt['profile'],'status':'interrupted','request_hash':request_hash,'result':{'path':str(result_path),'sha256':sha(result_bytes)}}
proposals=[]
for destination,b in [(receipt_path,receipt_bytes),(result_path,result_bytes),(index_path,enc(index))]:
 p=OUT/destination.name
 with p.open('xb') as f:f.write(b)
 proposals.append({'destination':str(destination),'candidate':pin(p),'destination_absent_at_proposal':True})
proposal={'schema':'orbit-poc-original150-reviewed-interrupted-append-proposal-v1','status':'proposed_not_applied','attempt':attempt,'proposal_scope':'Three data files only, with receipt/result/index order. Do not overwrite any existing file, mutate previous outputs or restart an attempt. An explicit independent audit must precede application.','observation':pin(OBS),'source_function':'Exact archived attempt_job AST loaded from pinned protocol source; no native or campaign function executed.','archived_protocol':pin(SOURCE),'configuration':pin(CONFIG),'manifest':pin(ROOT/'manifest.json'),'request':pin(d/'request.json'),'request_hash':request_hash,'expected_six_checkpoint_prefix':[{'attempt_id':x['attempt_id'],'result':x['result'],'index':x['index']} for x in o['attempts'][:6]],'append_files':proposals,'covariance_authorized':False,'native_substitution':False,'numeric_rerun':False,'parent_metrics_null':True,'prior_whole_runtime_audit_attribution':pin(BASE/'recovery-20261015-02/startup-resume-02.json'),'continuation_allowed_by_this_proposal':False}
with (OUT/'proposal.json').open('xb') as f:f.write(enc(proposal))
print(json.dumps({'proposal':pin(OUT/'proposal.json'),'append_files':proposals,'written_campaign_outputs':False}))
