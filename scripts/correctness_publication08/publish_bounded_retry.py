"""New presentation-only adapter for closed candidate07 execution attempts.

Preserve complete path-sanitized receipts as gzip and render bounded tables.
No estimator, mathematical audit, gate change, source edit or release promotion.
"""
import argparse,datetime,gzip,hashlib,html,io,json,re
from pathlib import Path

MAX_FILE=16*1024*1024
MAX_EXPANDED=64*1024*1024
REQUIRED={'execution','pins','source_freeze','pipeline','postprocess','postprocess_plan',
          'launch','postprocess_launch','audit','summary','html','independent_review','transfer_inventory'}
STEPS=('clone','checkout','build','native-tests','correction-regression-tests',
       'synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement',
       'eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay',
       'nuisance-replay-candidate1-point012')

def require(value,message):
    if not value:raise ValueError(message)
def digest(raw):return hashlib.sha256(raw).hexdigest()
def pairs(rows):
    result={}
    for key,value in rows:
        require(key not in result,'Duplicate JSON key');result[key]=value
    return result
def decode(raw):return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
def encoded(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
def artifact(pin):
    require(set(pin)=={'path','sha256','bytes','encoding','original_sha256','original_bytes'},'Unexpected artifact fields')
    path=Path(pin['path']);require(path.is_absolute() and path.is_file() and not path.is_symlink(),'Artifact must be a real absolute file')
    require(type(pin['bytes']) is int and 0<=pin['bytes']<=MAX_FILE and path.stat().st_size==pin['bytes'],'Stored artifact exceeds bound or changed size')
    raw=path.read_bytes();require(digest(raw)==pin['sha256'],'Artifact byte identity changed')
    require(pin['encoding'] in ('identity','gzip') and type(pin['original_bytes']) is int and 0<=pin['original_bytes']<=MAX_EXPANDED,'Invalid expanded artifact bound')
    if pin['encoding']=='gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:raw=stream.read(MAX_EXPANDED+1)
    require(len(raw)==pin['original_bytes'] and digest(raw)==pin['original_sha256'],'Expanded artifact identity changed')
    return raw

def scrub(text):
    # Tokens retain execution-attempt labels and source-relative paths.
    text=re.sub(r'/mnt/seagate10tb/orbit-v31-correctness-(\d+)-florianpfaff',lambda m:'@EXECUTION_'+m[1]+'_ROOT@',text)
    for old,new in [('/mnt/c/users/emper/documents/codex/2026-10-13/i-x20','@WORKSPACE_ROOT@'),
        ('/mnt/c/Users/emper/Documents/Codex/2026-10-13/i-x20','@WORKSPACE_ALIAS_ROOT@'),
        ('/home/florianpfaff','@REMOTE_HOME@'),('/mnt/seagate10tb','@REMOTE_DATA_ROOT@'),
        ('/mnt/d','@LOCAL_DATA_ROOT@'),('/mnt/c','@WINDOWS_MOUNT@'),('/tmp','@TEMP_ROOT@'),('/root','@AGENT_ROOT@')]:text=text.replace(old,new)
    return re.sub(r'\b(?:emper|florianpfaff)\b','PRIVATE_USER',text)

def inspect(plan):
    require(set(plan)=={'schema','execution_attempt','candidate_control_version','execution_root','output','artifacts','attachments'},'Unexpected plan fields')
    require(plan['schema']=='orbit-poc-bounded-retry-publication-plan-v1' and plan['candidate_control_version']=='07','Unknown candidate/report version')
    attempt=plan['execution_attempt'];require(attempt in ('07','08'),'Unknown execution attempt')
    remote=Path(plan['execution_root']);require(remote==Path('/mnt/seagate10tb/orbit-v31-correctness-'+attempt+'-florianpfaff'),'Execution attempt/root mismatch')
    require(set(plan['artifacts'])==REQUIRED,'Exact presentation inputs required')
    raw={key:artifact(pin) for key,pin in plan['artifacts'].items()}
    data={key:decode(value) for key,value in raw.items() if key!='html'}
    pipeline=data['pipeline'];post=data['postprocess'];execution=data['execution'];pins=data['pins'];frozen=data['source_freeze'];summary=data['summary'];audit=data['audit'];postplan=data['postprocess_plan']
    require(pipeline.get('schema')=='orbit-poc-correctness-validation07-run-v1'
            and post.get('schema')=='orbit-poc-correctness-postprocess07-run-v1'
            and pins.get('schema')=='orbit-poc-correctness-candidate07-pins-v1'
            and execution.get('schema')=='orbit-poc-correctness-execution-v1','Unexpected original control schemas')
    require(pipeline.get('status') in ('passed','failed') and pipeline.get('finished_at') and pipeline.get('final_cleanup',{}).get('verified') is True,'Validation must be terminal with owned cleanup')
    require(post.get('status') in ('completed','failed') and post.get('finished_at') and len(post.get('steps',[]))==3 and all(x.get('cleanup_verified') is True for x in post['steps']),'Postprocessing must be terminal with owned cleanup')
    require(Path(execution['paths']['root'])==remote and Path(execution['paths']['run'])==remote/'validation-07','Execution layout changed')
    def binding(record,key,relative):
        require(record.get('path')==str(remote/relative) and record.get('sha256')==digest(raw[key]),'Execution/source attribution differs: '+key)
        require('bytes' not in record or record['bytes']==len(raw[key]),'Recorded artifact size differs: '+key)
    binding(pipeline['execution'],'execution','control/candidate07-execution.json')
    binding(pipeline['required_pins'],'pins','control/candidate07-pins.json')
    binding(pins['new_source_freeze'],'source_freeze','control/candidate07-source-freeze.json')
    binding(post['validation_pipeline'],'pipeline','validation-07/pipeline.json')
    binding(post['plan'],'postprocess_plan','control/candidate07-postprocess-plan.json')
    binding(data['postprocess_launch']['plan'],'postprocess_plan','control/candidate07-postprocess-plan.json')
    binding(postplan['execution'],'execution','control/candidate07-execution.json')
    binding(postplan['candidate_pins'],'pins','control/candidate07-pins.json')
    require(frozen.get('schema')=='orbit-poc-candidate07-source-freeze-v1' and pipeline.get('source')==frozen['source']
            and pins.get('source_sha256')==frozen['source']['sha256'] and pins.get('source_file_count')==len(frozen['source']['files'])
            and post.get('source')=={'commit':frozen['commit'],'sha256':frozen['source']['sha256'],'file_count':len(frozen['source']['files'])},'Candidate source identity mismatch')
    require(pins.get('expected_native_test_count')==106 and len(pins.get('input_artifacts',{}))==14,'Original106/14 inventory differs')
    require(pipeline.get('resume')=={'status':'not_applicable','reason':'no_campaign_running'},'Unexpected campaign resume')
    review=data['independent_review']
    require(review.get('source_commit')==frozen['commit'] and review.get('source_sha256')==frozen['source']['sha256'],'Independent review source identity differs')
    for role,relative in [('pipeline','validation-07/pipeline.json'),('postprocess','postprocess-07-01/pipeline.json')]:
        reviewed=review.get('artifacts',{}).get(relative,{})
        require(reviewed.get('sha256')==digest(raw[role]) and reviewed.get('bytes')==len(raw[role]),'Independent review execution identity differs: '+role)
    identity=data['launch']['driver_process'];admission=pipeline['admission']
    require(identity==postplan['driver_process'] and identity['pid']==admission['driver_identity']['pid']
            and identity['start_ticks']==admission['driver_identity']['start_ticks'] and identity['boot_id']==admission['boot_id'], 'Driver execution identity differs')
    require(data['launch']['execution_sha256']==digest(raw['execution']) and data['launch']['pins_sha256']==digest(raw['pins']), 'Launch pins differ')
    require(audit.get('schema')=='orbit-poc-correctness-independent-audit07-v1' and type(audit.get('passed')) is bool,'Audit missing or wrong schema')
    require(summary.get('schema')=='orbit-correction-evidence-report07-v1'
            and summary.get('independent_audit',{}).get('record')==audit,'Summary does not contain the same actual audit')
    binding(summary['pipeline']['evidence'],'pipeline','validation-07/pipeline.json')
    require(summary['independent_audit']['evidence']['sha256']==digest(raw['audit']),'Summary/audit hash mismatch')
    require(summary.get('release_acceptance')=='not_assessed' and summary.get('frozen_campaign_reclassified') is False,'Presentation cannot promote release or campaign status')
    require(post['validation_status']==pipeline['status'] and post['scientific_status']==summary['candidate_evidence_status'],'Postprocess outcome differs from its reports')
    require([step.get('name') for step in post['steps']]==['audit','report','collect'],'Postprocess step identity differs')
    for step,key,relative in [(post['steps'][0],'audit','postprocess-07-01/independent-audit.json'),
                              (post['steps'][1],'summary','postprocess-07-01/report/summary.json')]:
        binding(step['result'],key,relative)
        require(step['result'].get('bytes')==len(raw[key]),'Original postprocess result size differs')
    require(post['steps'][0].get('reported_outcome')==audit['passed'] and post['steps'][1].get('reported_outcome')==summary['candidate_evidence_status'],'Original postprocess result status differs')
    inventory=data['transfer_inventory']
    require(inventory.get('remote_root')==str(remote) and inventory.get('local_match_verified') is True,'Original transfer attribution differs')
    for key,relative in [('pipeline','validation-07/pipeline.json'),('postprocess','postprocess-07-01/pipeline.json'),
                         ('audit','postprocess-07-01/independent-audit.json'),('summary','postprocess-07-01/report/summary.json'),
                         ('html','postprocess-07-01/report/index.html')]:
        matches=[row for row in inventory.get('files',[]) if row.get('source')==str(remote/relative)]
        require(len(matches)==1 and matches[0].get('original_sha256')==digest(raw[key]) and matches[0].get('original_bytes')==len(raw[key]),'Original transferred report identity differs: '+key)
    for key in ('pipeline','execution','candidate07_pins'):
        expected={'pipeline':'pipeline','execution':'execution','candidate07_pins':'pins'}[key]
        matches=[x for x in audit.get('input_artifacts',[]) if x.get('role')==key]
        require(len(matches)==1 and matches[0].get('sha256')==digest(raw[expected]),'Audit input identity differs: '+key)
    if attempt=='07':
        require(not pipeline.get('native') and len(pipeline.get('steps',[]))==1 and pipeline['steps'][0].get('name')=='clone'
                and pipeline['steps'][0].get('returncode')==128,'Failed execution07 cannot be reclassified')
    else:
        require(any(x.get('name')=='clone' and x.get('returncode')==0 for x in pipeline.get('steps',[])),'Retry08 did not establish its independent staged clone')
    require(isinstance(plan['attachments'],list) and len(plan['attachments'])<=60,'Invalid attachment inventory')
    extra={}
    for row in plan['attachments']:
        require(set(row)=={'name','artifact'},'Invalid attachment descriptor')
        name=Path(row['name']);require(not name.is_absolute() and '..' not in name.parts and str(name) not in extra,'Unsafe/duplicate attachment name')
        extra[str(name)]=artifact(row['artifact'])
    return raw,data,extra

def selected(value,keys):return {k:value[k] for k in keys if k in value}
def compact(plan,data):
    s=data['summary'];p=data['pipeline'];a=data['audit'];steps=[]
    for name in STEPS:
        matches=[x for x in p.get('steps',[]) if x.get('name')==name];require(len(matches)<=1,'Duplicate planned step')
        steps.append(selected(matches[0],('name','status','returncode','elapsed_seconds','timeout_seconds','error')) if matches else {'name':name,'status':'not_run'})
    for value in p.get('steps',[]):
        if value.get('name') not in STEPS:steps.append(selected(value,('name','status','returncode','elapsed_seconds','error')))
    result={'schema':'orbit-poc-bounded-execution-summary-v1','execution_attempt':plan['execution_attempt'],'candidate_control_version':'07',
        'candidate_commit':data['source_freeze']['commit'],'source_sha256':p['source']['sha256'],
        'native':p.get('native'),'validation_status':p['status'],'postprocess_status':data['postprocess']['status'],
        'reported_evidence_status':s['candidate_evidence_status'],'independent_receipt_audit_passed':a['passed'],
        'independent_audit_errors':a.get('errors',[]),'summary_integrity_errors':s.get('integrity_errors',[]),
        'steps':steps,'original_tests':selected(s['native_tests'],('status','counts','integrity_errors')),
        'additional_regressions':selected(s['correction_regression_tests'],('status','counts','integrity_errors')),
        'refinements':{},'objectives':{},'original_nuisance_replays':{},'release_acceptance':'not_assessed','covariance_authorized':False,
        'frozen_campaign_reclassified':False,'presentation_only':True,
        'scope':'Summary of existing unchanged numerical audits. Full original reports are retained separately as gzip; no gate is rerun, relaxed or replaced. Floor-limited progress is not strict convergence and cannot authorize covariance.'}
    for category in ('synthetic_refinement','additional_refinement'):
        for key,value in s.get(category,{}).items():result['refinements'][key]=selected(value,('status','passed','error','metrics','native_signals','integrity_errors'))
    for key,value in s.get('objectives',{}).items():result['objectives'][key]=selected(value,('status','reported_passed','error','prior','prior_status','directional_scales','accepted_derivative_scales','profile_resolution_counts','integrity_errors'))
    for key,value in s.get('nuisance_replays',{}).items():
        item=selected(value,('status','passed','error','resolution_status','strict_nuisance_converged','progress_only_floor_validated','elapsed_seconds','source_profile_sha256','replay_profile_sha256','integrity_errors'))
        item['profile']=selected(value.get('profile') or {},('nuisance_converged','nuisance_floor_limited','maximum_update_m','threshold_m','required_consecutive_small_updates','nuisance_gradient_scaled','nuisance_predicted_reduction','nuisance_objective_resolution'))
        item['final_search']=selected(value.get('final_search') or {},('nuisance_floor_limited','nuisance_objective_resolution','undamped_maximum_update_m','zero_update_replay_exact','support_preserved','floor_rejection'))
        result['original_nuisance_replays'][key]=item
    require(len(encoded(result))<=1024*1024,'Compact numerical summary exceeds1MiB; no truncation permitted')
    return result

def publish(plan,plan_sha256=None):
    out=Path(plan['output']);require(out.is_absolute() and not out.exists() and not out.is_symlink(),'Choose a new publication output')
    raw,data,extra=inspect(plan);summary=compact(plan,data);payload={}
    for name,value in raw.items():payload['full/'+name+('.html.gz' if name=='html' else '.json.gz')]=(value,'full original artifact, path-sanitized then gzip')
    for name,value in extra.items():payload['attachments/'+name+'.gz']=(value,'preserved attachment, path-sanitized then gzip')
    files={};packed={};total=0
    for name,(value,label) in payload.items():
        sanitized=scrub(value.decode()).encode();compressed=gzip.compress(sanitized,mtime=0)
        require(len(compressed)<=MAX_FILE,'Compressed artifact exceeds16MiB cap');total+=len(compressed);require(total<=64*1024*1024,'Publication exceeds64MiB')
        packed[name]=compressed;files[name]={'sha256':digest(compressed),'bytes':len(compressed),'original_sha256':digest(value),'original_bytes':len(value),'published_expanded_sha256':digest(sanitized),'published_expanded_bytes':len(sanitized),'transformation':label}
    public=decode(scrub(encoded(summary).decode()));summary_raw=encoded(public)
    rows=''.join('<tr><td>'+html.escape(str(x['name']))+'</td><td>'+html.escape(str(x['status']))+'</td><td>'+html.escape(str(x.get('returncode','')))+' </td></tr>' for x in public['steps'])
    report='<!doctype html><html lang="en"><meta charset="utf-8"><title>Execution '+plan['execution_attempt']+' evidence</title><style>body{font:16px system-ui;max-width:1050px;margin:2rem auto;padding:0 1rem}table{border-collapse:collapse}td,th{border:1px solid #ccd;padding:.4rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>Execution attempt '+plan['execution_attempt']+' — candidate07 controls</h1><p>Validation: <strong>'+html.escape(public['validation_status'])+'</strong>. Original postprocessing: <strong>'+html.escape(public['postprocess_status'])+'</strong>. Reported numerical evidence: <strong>'+html.escape(public['reported_evidence_status'])+'</strong>.</p><p>This bounded presentation preserves every planned step and the original reporting failure. It changes no numerical gate. Strict nuisance convergence and audited floor-limited progress remain distinct; floor status cannot authorize covariance. Release acceptance and the frozen150-attempt benchmark remain unassessed.</p><table><tr><th>Planned step</th><th>Actual status</th><th>Exit</th></tr>'+rows+'</table><h2>Compact reported metrics</h2><pre>'+html.escape(summary_raw.decode())+'</pre><h2>Complete preserved artifacts</h2><ul>'+''.join('<li><a href="'+html.escape(name,quote=True)+'">'+html.escape(name)+'</a></li>' for name in packed)+'</ul><p>Full files are gzip-compressed, with private paths sanitized. The manifest records both original and published hashes and sizes. This adapter does not modify or replace the original collector, its limit, or its failed journal.</p></html>'
    require(len(report.encode())<=1024*1024,'Compact HTML exceeds1MiB')
    packed.update({'summary.json':summary_raw,'index.html':report.encode()})
    for name in ('summary.json','index.html'):files[name]={'sha256':digest(packed[name]),'bytes':len(packed[name]),'transformation':'new bounded presentation only'}
    manifest={'schema':'orbit-poc-bounded-retry-publication-v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'execution_attempt':plan['execution_attempt'],'candidate_control_version':'07','source_commit':public['candidate_commit'],
        'source_sha256':public['source_sha256'],'files':files,'bytes':sum(x['bytes'] for x in files.values()),
        'plan_sha256':plan_sha256 or digest(encoded(plan)),'canonical_plan_sha256':digest(encoded(plan)),
        'adapter_sha256':digest(Path(__file__).read_bytes()),'scientific_gate_substitution':False}
    out.mkdir(parents=True)
    for name,value in packed.items():path=out/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(value)
    (out/'manifest.json').write_bytes(encoded(manifest))
    return manifest

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--plan',type=Path,required=True);parser.add_argument('--plan-sha256',required=True);args=parser.parse_args()
    raw=args.plan.read_bytes();require(digest(raw)==args.plan_sha256,'Frozen publication plan changed');result=publish(decode(raw),args.plan_sha256);print(json.dumps({'execution_attempt':result['execution_attempt'],'files':len(result['files']),'bytes':result['bytes']}))
if __name__=='__main__':main()
