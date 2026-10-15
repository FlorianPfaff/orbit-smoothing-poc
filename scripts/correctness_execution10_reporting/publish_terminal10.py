"""Publish a separate execution10 index; never changes scientific classifications."""
from pathlib import Path
import argparse,gzip,hashlib,html,importlib.util,io,json,sys
sys.dont_write_bytecode=True
MAX_FILE=16*1024*1024
MAX_EXPANDED=64*1024*1024
MAX_TOTAL=64*1024*1024
STEPS=('clone','checkout','build','native-tests','correction-regression-tests',
 'synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement',
 'eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay',
 'nuisance-replay-candidate1-point012')
def require(ok,message):
 if not ok:raise ValueError(message)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(d):return (json.dumps(d,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
def safe(name):
 p=Path(name);require(not p.is_absolute() and '..' not in p.parts and str(p)==name,'Unsafe publication path');return p
def file(path):
 p=Path(path);require(p.is_file() and not p.is_symlink() and p.stat().st_size<=MAX_EXPANDED,'Missing, symlinked or oversized file');return p.read_bytes()
def pin(p):
 raw=file(p['path']);require(sha(raw)==p['sha256'],'Pinned file changed');return raw
def expand(raw,encoding):
 require(encoding in ('identity','gzip'),'Unknown encoding')
 if encoding=='identity':return raw
 with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:v=f.read(MAX_EXPANDED+1)
 require(len(v)<=MAX_EXPANDED,'Expanded file exceeds limit');return v

def inspect(plan):
 require(plan.get('schema')=='orbit-poc-terminal10-publication-plan-v1','Unknown publication plan')
 transfer=json.loads(pin(plan['transfer_manifest']));root=Path(transfer['local_root'])
 require(transfer.get('schema')=='orbit-poc-terminal10-bounded-transfer-v1'
  and transfer.get('execution_attempt')=='10' and transfer.get('candidate_control_version')=='09'
  and transfer.get('local_match_verified') is True,'Transfer is not verified execution10')
 require(all(transfer.get(k)==plan[k] for k in ('source_commit','source_sha256','journals','execution_sha256','pins_sha256')),'Transfer attribution differs')
 immediate=transfer.get('immediate_predecessor',{})
 require(immediate.get('execution_attempt')=='09' and immediate.get('status')=='failed'
  and immediate.get('source_commit')==plan['previous_source_commit']
  and immediate.get('validation_sha256')==plan['previous_validation_sha256']
  and immediate.get('installer_correction_sha256')==plan['installer_correction_sha256']
  and immediate.get('supplementary_verification_sha256')==plan['supplementary_verification_sha256'], 'Immediate failed09 lineage differs')
 rows={};original={};stored_total=0
 for r in transfer['files']:
  p=safe(r['relative']);raw=file(root/p)
  require(len(raw)==r['bytes']<=MAX_FILE and sha(raw)==r['sha256'],'Transferred stored bytes changed')
  expanded=expand(raw,r['encoding'])
  require(len(expanded)==r['original_bytes']<=MAX_EXPANDED and sha(expanded)==r['original_sha256'],'Transferred expanded bytes changed')
  source=Path(r['source']);remote=Path(transfer['remote_root']);require(source.is_relative_to(remote),'Transferred source outside execution')
  name=str(source.relative_to(remote));require(name not in rows,'Duplicate transferred source')
  require(name+('.gz' if r['encoding']=='gzip' else '')==r['relative'],'Transferred source/storage attribution differs')
  rows[name]=(r,raw);original[name]=expanded;stored_total+=len(raw)
 require(stored_total==transfer['transfer_bytes']<=MAX_TOTAL,'Transfer total differs')
 for name,digest in plan['journals'].items():require(sha(original[name])==digest,'Terminal journal changed')
 pipeline=json.loads(original['validation-09/pipeline.json']);post=json.loads(original['postprocess-09-01/pipeline.json'])
 require(pipeline.get('status') in ('passed','failed') and pipeline.get('finished_at') and pipeline.get('final_cleanup',{}).get('verified') is True,'Native suite is not terminal and clean')
 require(post.get('status') in ('completed','failed') and post.get('finished_at')
  and all(s.get('cleanup_verified') is True for s in post.get('steps',[])),'Postprocessor is not terminal and clean')
 require(post.get('validation_pipeline',{}).get('sha256')==plan['journals']['validation-09/pipeline.json'],'Postprocessor validation attribution differs')
 observed=pipeline.get('steps',[]);names=[s['name'] for s in observed]
 require(len(set(names))==len(names) and all(n in STEPS for n in names),'Unknown or duplicate native stage')
 require(names==[n for n in STEPS if n in names],'Native stage order differs')
 stages=[next((s for s in observed if s['name']==n),{'name':n,'status':'not_run'}) for n in STEPS]
 audit_raw=pin(plan['independent_audit']);audit=json.loads(audit_raw)
 require(audit.get('execution_attempt')=='10' and audit.get('control_version')=='09'
  and audit.get('consistency_audit_passed') is True and audit.get('cleanup_verified') is True
  and audit.get('source_commit')==plan['source_commit'] and audit.get('source_sha256')==plan['source_sha256']
  and audit.get('pipeline_status')==pipeline['status'],'Independent audit attribution/consistency differs')
 require(audit.get('identity',{}).get('execution_sha256')==plan['execution_sha256']
  and audit['identity'].get('pins_sha256')==plan['pins_sha256'],'Independent execution pins differ')
 for name,digest in plan['journals'].items():require(audit.get('artifacts',{}).get(name,{}).get('sha256')==digest,'Independent terminal journal differs')
 report=None;report_step=next((s for s in post['steps'] if s['name']=='report'),None)
 if 'postprocess-09-01/report/summary.json' in original:
  raw=original['postprocess-09-01/report/summary.json'];result=report_step.get('result',{}) if report_step else {}
  require(result.get('path')==transfer['remote_root']+'/postprocess-09-01/report/summary.json'
   and result.get('sha256')==sha(raw) and result.get('bytes')==len(raw),'Reported summary is not original postprocess result')
  report=json.loads(raw)
 # Successful native collection is copied byte-for-byte, including its unchanged historical terminology.
 prefix='postprocess-09-01/publication/';bundle={}
 if transfer.get('collector_publication_complete'):
  for name,(r,raw) in rows.items():
   if name.startswith(prefix):bundle[name[len(prefix):]]=original[name]
  require('manifest.json' in bundle and 'index.html' in bundle,'Successful collector bundle is incomplete')
  collect=next(s for s in post['steps'] if s['name']=='collect');require(collect.get('returncode')==0 and collect.get('result',{}).get('sha256')==sha(bundle['manifest.json']),'Collector manifest attribution differs')
  inventory=json.loads(bundle['manifest.json']);declared=set()
  for r in inventory['files']:
   name=r['destination'];safe(name);require(name not in declared,'Duplicate collector file');declared.add(name)
   raw=bundle[name];require(len(raw)==r['published_bytes']<=MAX_FILE and sha(raw)==r['published_sha256'],'Collector file changed')
   expanded=expand(raw,r.get('encoding','identity'))
   require(len(expanded)==r['published_expanded_bytes'] and sha(expanded)==r['published_expanded_sha256'],'Collector expanded file changed')
  require(set(bundle)==declared|{'manifest.json','README.md'},'Collector undeclared or missing files')
 scrub_path=Path(plan['scrubber']['path']);pin(plan['scrubber'])
 spec=importlib.util.spec_from_file_location('terminal10_scrubber',scrub_path);scrubber=importlib.util.module_from_spec(spec);spec.loader.exec_module(scrubber)
 return transfer,pipeline,post,stages,audit,audit_raw,report,original,bundle,scrubber.scrub

def render(summary,has_raw):
 esc=lambda x:html.escape(str(x))
 rows=''.join('<tr><td>'+esc(s['name'])+'</td><td>'+esc(s['status'])+'</td><td>'+esc(s.get('returncode','—'))+'</td></tr>' for s in summary['planned_steps'])
 tables=''
 for heading,values in summary['reported_metrics'].items():
  tables+='<h2>'+esc(heading)+'</h2><pre>'+esc(json.dumps(values,indent=2,sort_keys=True))+'</pre>'
 raw='<a href="raw-report/index.html">Original control09 report</a> · ' if has_raw else ''
 return ('<!doctype html><meta charset="utf-8"><title>Execution10 terminal evidence</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:0 20px}td,th{padding:6px 15px;text-align:left;border-bottom:1px solid #ccc}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}</style>'
  '<h1>Execution10: '+esc(summary['validation_status'])+'</h1><p>Source <code>'+esc(summary['source_commit'])+'</code>; unchanged control version09. The actual immediate predecessor is failed execution09/source05. Cumulative execution08/source04 fields and any “immediate previous07” wording in the archived control09 report describe its compatibility basis, not this execution’s immediate predecessor.</p>'
  '<p>'+raw+'<a href="summary.json">Derived summary</a> · <a href="evidence/terminal-independent-audit.json.gz">Independent terminal audit</a> · <a href="manifest.json">Publication hashes</a></p>'
  '<p>Scientific gate classifications are copied from the original report and independent audit. Presentation does not authorize covariance or establish v3.1 release readiness. The original 150-fit benchmark remains separate.</p>'
  '<h2>All planned stages</h2><table><tr><th>Stage</th><th>Status</th><th>Exit</th></tr>'+rows+'</table>'+tables+
  '<h2>Preserved full evidence</h2><p><a href="evidence/report-summary.json.gz">Full original report summary (paths tokenized)</a>. Missing report artifacts remain explicit in the manifest. Floor-limited progress is distinct from strict nuisance convergence.</p>').encode()

def publish(plan):
 out=Path(plan['output']);require(not out.exists(),'Publication output must be new')
 transfer,pipeline,post,stages,audit,audit_raw,report,original,bundle,scrub=inspect(plan)
 metrics={}
 if report:
  for key in ('native_tests','correction_regression_tests'):
   metrics[key]={k:report.get(key,{}).get(k) for k in ('status','counts')}
  selections={'objectives':('status','reported_passed','prior_status','accepted_derivative_scales','directional_scales','profile_resolution_counts','error'),
   'nuisance_replays':('status','resolution_status','strict_nuisance_converged','progress_only_floor_validated','passed','error'),
   'synthetic_refinement':('status','metrics','error'),'additional_refinement':('status','metrics','error')}
  for key,fields in selections.items():metrics[key]={n:{k:v[k] for k in fields if k in v} for n,v in report.get(key,{}).items()}
 summary={'schema':'orbit-poc-terminal10-presentation-v1','execution_attempt':'10','control_version':'09',
  'source_commit':plan['source_commit'],'source_sha256':plan['source_sha256'],'validation_status':pipeline['status'],
  'postprocess_status':post['status'],'postprocess_steps':[{k:s.get(k) for k in ('name','returncode','cleanup_verified','error')} for s in post['steps']],
  'immediate_predecessor':transfer['immediate_predecessor'],'planned_steps':[{k:s.get(k) for k in ('name','status','returncode','elapsed_seconds')} for s in stages],
  'candidate_evidence_status':report.get('candidate_evidence_status') if report else 'unavailable',
  'independent_consistency_audit_passed':audit['consistency_audit_passed'],'scientific_correctness_gate_passed':audit.get('scientific_correctness_gate_passed'),
  'reported_metrics':metrics,'missing_report':report is None,'covariance_authorized':False,'release_acceptance':'not_assessed','frozen_benchmark_reclassified':False,
  'raw_collector_available':bool(bundle),'collector_publication_inventory':transfer['collector_publication_inventory']}
 pending={};records=[]
 def add(name,raw,source=None,compressed=False,transformation='identity'):
  safe(name);require(name not in pending,'Duplicate publication output')
  expanded=raw;raw=gzip.compress(raw,mtime=0) if compressed else raw
  require(len(raw)<=MAX_FILE and len(expanded)<=MAX_EXPANDED,'Publication file exceeds bounds')
  pending[name]=raw;records.append({'path':name,'sha256':sha(raw),'bytes':len(raw),'encoding':'gzip' if compressed else 'identity',
   'expanded_sha256':sha(expanded),'expanded_bytes':len(expanded),'source_sha256':source,'transformation':transformation})
 for name,raw in bundle.items():add('raw-report/'+name,raw,sha(raw))
 add('evidence/terminal-independent-audit.json.gz',encoded(scrub(audit)),sha(audit_raw),True,'canonical JSON; absolute paths tokenized')
 for rel,name in (('validation-09/pipeline.json','validation-pipeline'),('postprocess-09-01/pipeline.json','postprocess-pipeline'),('postprocess-09-01/report/summary.json','report-summary'),('postprocess-09-01/independent-audit.json','native-independent-audit')):
  if rel in original:add('evidence/'+name+'.json.gz',encoded(scrub(json.loads(original[rel]))),sha(original[rel]),True,'canonical JSON; absolute paths tokenized')
 add('summary.json',encoded(scrub(summary)))
 add('index.html',render(scrub(summary),bool(bundle)))
 require(sum(len(x) for x in pending.values())<=MAX_TOTAL,'Publication total exceeds64MiB')
 manifest={'schema':'orbit-poc-terminal10-presentation-manifest-v1','execution_attempt':'10','control_version':'09',
  'transfer_manifest_sha256':plan['transfer_manifest']['sha256'],'independent_audit_sha256':plan['independent_audit']['sha256'],
  'files':records,'bytes':sum(len(x) for x in pending.values()),'raw_collector_copied_verbatim':bool(bundle),
  'collector_publication_complete':transfer['collector_publication_complete'],'missing_report':report is None,
  'covariance_authorized':False,'release_acceptance':'not_assessed','scientific_gate_policy_changed':False}
 pending['manifest.json']=encoded(manifest);out.mkdir(parents=True)
 for name,raw in pending.items():p=out/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
 return {'output':str(out),'files':len(pending),'manifest_sha256':sha(pending['manifest.json']),'validation_status':pipeline['status']}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True,type=Path);p.add_argument('--plan-sha256',required=True);a=p.parse_args()
 raw=pin({'path':a.plan,'sha256':a.plan_sha256});print(json.dumps(publish(json.loads(raw))))
if __name__=='__main__':main()
