#!/usr/bin/env python3
"""Publish terminal validation beside an unchanged pre-prepare68-attempt report.

Presentation only: the independently audited native result remains distinct from
benchmark completion. All copied raw evidence is retained byte-for-byte.
"""
from pathlib import Path
import argparse,gzip,hashlib,html,json,shutil
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
AUDIT_KEYS={'controller','cli_pipeline','validation_context','validation_plan','run_plan','config','source_freeze','launch_plan','launch_pins'}
REPORT_ONLY={'release_evidence','original150_report','original150_manifest','original150_plan'}
MAX_STORED=16*1024*1024;MAX_EXPANDED=64*1024*1024;MAX_TOTAL=64*1024*1024

def need(ok,message):
 if not ok:raise ValueError(message)
def sha(b):return hashlib.sha256(b).hexdigest()
def canonical(v):return sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def artifact(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def checked(pin):
 p=Path(pin['path']);need(p.is_absolute() and p.is_file() and not p.is_symlink(),'Expected absolute regular pinned file')
 b=p.read_bytes();need(sha(b)==pin['sha256'] and len(b)==pin['bytes'],'Pinned file differs: '+str(p));return p,b
def safe_relative(path):
 p=Path(path);need(not p.is_absolute() and '..' not in p.parts and str(p) not in ('','.','manifest.json'),'Unsafe stored path');return p
def decode(record,base):
 p=base/safe_relative(record['stored']['path']);need(not p.is_symlink() and p.is_file(),'Missing captured regular file')
 b=p.read_bytes();need(len(b)<=MAX_STORED and len(b)==record['stored']['bytes'] and sha(b)==record['stored']['sha256'],'Captured stored bytes differ')
 need(record['encoding'] in ('identity','gzip'),'Unknown capture encoding')
 if record['encoding']=='gzip':
  import io
  with gzip.GzipFile(fileobj=io.BytesIO(b)) as f:r=f.read(MAX_EXPANDED+1)
 else:r=b
 need(len(r)<=MAX_EXPANDED and len(r)==record['source']['bytes'] and sha(r)==record['source']['sha256'],'Captured expanded bytes differ')
 return b,r

def inspect(plan):
 need(set(plan)=={'schema','capture','independent_audit','raw_report','raw_html','interface_review'},'Unknown presentation plan fields')
 need(plan['schema']=='orbit-poc-segmented-validation-presentation-plan-v1','Wrong presentation plan schema')
 cp,cb=checked(plan['capture']);capture=json.loads(cb);base=cp.parent
 need(capture['schema']=='orbit-poc-v4-terminal-validation-capture-v1' and capture.get('final_owned_cleanup_verified') is True,'Capture is not terminal and clean')
 bm=capture['benchmark_outputs'];need(bm.get('manifest_present') is False and bm.get('attempts_directory_present') is False and bm.get('attempt_entries')==[],'This presenter is only for a pre-prepare0-of68 snapshot')
 bysource={};storedpaths=set();total=0
 for rec in capture['records']:
  source=rec['source']['path'];stored=str(safe_relative(rec['stored']['path']))
  need(source not in bysource and stored not in storedpaths,'Duplicate captured identity');storedpaths.add(stored)
  b,r=decode(rec,base);total+=len(b);need(total<=MAX_TOTAL,'Capture exceeds publication storage budget');bysource[source]=(rec,r)
 actual={str(x.relative_to(base)) for x in base.rglob('*') if x.is_file() and x!=cp}
 need(actual==storedpaths,'Unlisted capture files or missing members')
 def raw(pin,as_json=True):
  need(pin['path'] in bysource,'Core audit artifact missing from capture: '+pin['path'])
  rec,b=bysource[pin['path']];need(all(rec['source'].get(k)==pin[k] for k in ('path','sha256')) and ('bytes' not in pin or rec['source']['bytes']==pin['bytes']),'Audit/capture artifact differs');return json.loads(b) if as_json else b
 ap,ab=checked(plan['independent_audit']);audit=json.loads(ab)
 need(audit.get('schema')=='orbit-poc-segmented-validation-terminal-independent-review-v1' and audit.get('consistency_passed') is True and audit.get('cleanup_verified') is True,'Independent consistency/cleanup audit did not pass')
 need(audit.get('scientific_status') in ('passed_scoped_checks','failed','incomplete'),'Unknown scientific status')
 need(audit.get('release_ready') is False and audit.get('fit_covariance_authorized') is False and audit.get('benchmark_attempts_executed')==0,'Audit scope exceeds prebenchmark validation')
 need(set(audit['artifacts'])==AUDIT_KEYS,'Independent audit artifact keys differ')
 v={k:raw(pin) for k,pin in audit['artifacts'].items()}
 controller,pipeline,context,vplan,runplan=v['controller'],v['cli_pipeline'],v['validation_context'],v['validation_plan'],v['run_plan']
 need(capture['controller']==audit['artifacts']['controller'] and capture['pipeline']==audit['artifacts']['cli_pipeline'],'Capture journal attribution differs')
 need(controller['status']==capture['controller_status'] and pipeline['status']==capture['pipeline_status'],'Capture status differs')
 need(controller.get('final_cleanup',{}).get('verified') is True and pipeline['status'] in ('passed','failed'),'Unclosed validation')
 need(runplan['plan_hash']==canonical({k:x for k,x in runplan.items() if k!='plan_hash'}),'Run plan hash differs')
 need(context['validation_context_hash']==canonical({k:x for k,x in context.items() if k!='validation_context_hash'}) and context['plan_hash']==runplan['plan_hash'],'Validation context attribution differs')
 need(vplan['plan_hash']==canonical({k:x for k,x in vplan.items() if k!='plan_hash'}) and vplan['validation_context_hash']==context['validation_context_hash'],'Validation plan attribution differs')
 need(pipeline.get('plan_hash')==vplan['plan_hash'] and pipeline.get('validation_context_hash')==context['validation_context_hash'],'CLI validation identity differs')
 need(runplan['config']=={k:x for k,x in v['config'].items() if k not in REPORT_ONLY},'Executed config/run plan differs')
 identity=audit['identity'];freeze=v['source_freeze']
 need(identity['full_source_sha256']==freeze['source']['sha256'] and identity['source_file_count']==len(freeze['source']['files']),'Full source identity differs')
 need(identity['comparison_source_sha256']==runplan['source']['sha256']==freeze['comparison_source']['sha256'],'Comparison source identity differs')
 runtime=context['runtimes']['segmented'];need(runtime['source_sha256']==identity['comparison_source_sha256'] and runtime['native']['sha256']==identity['native_sha256'] and runtime['segmented_solver']['sha256']==identity['solver_sha256'],'Runtime identity differs')
 need(tuple(s['name'] for s in pipeline['steps'])==STAGES and tuple(s['name'] for s in audit['stages'])==STAGES and tuple(vplan['stages'])==STAGES,'Exact14 gate inventory differs')
 need(capture['planned_gates']==[{'name':s['name'],'status':s['status']} for s in pipeline['steps']],'Capture gate statuses differ')
 stages=[]
 for s,a in zip(pipeline['steps'],audit['stages']):
  need(a['independently_consistent'] is True and a['status']==s['status'] and s['status'] in ('passed','failed','not_run','interrupted_or_failed'),'Audited gate status differs')
  for pin in a['raw_artifacts']:raw(pin,False)
  execution=None
  if 'execution' in s:
   execution=raw(s['execution']);need(execution.get('harness_execution',{}).get('owned_process_group_cleaned') is True,'Gate cleanup missing')
   if s['status']=='passed':need(execution.get('status')=='complete' and execution.get('returncode')==0,'Passed stage execution failed')
  else:need(s['status']!='passed','Passed gate lacks an execution')
  stages.append({'name':s['name'],'status':s['status'],'measurements':a['measurements'],'raw_artifacts':a['raw_artifacts'],'execution':s.get('execution'),'execution_summary':{k:execution.get(k) for k in ('status','returncode','elapsed_seconds')} if execution else None})
 if audit['scientific_status']=='passed_scoped_checks':need(pipeline['status']=='passed' and controller['status']=='passed' and all(s['status']=='passed' for s in stages),'False scoped pass')
 else:need(not all(s['status']=='passed' for s in stages),'Audit cannot downgrade an all-passed pipeline without an explicit corrected schema')
 rp,rb=checked(plan['raw_report']);report=json.loads(rb);checked(plan['raw_html']);_,ib=checked(plan['interface_review']);interface=json.loads(ib)
 need(interface['plan_hash']==runplan['plan_hash'] and interface['source_sha256']==identity['comparison_source_sha256'] and interface['config']['sha256']==audit['artifacts']['config']['sha256'] and interface['report_sha256']==plan['raw_report']['sha256'],'Original API report attribution differs')
 need(report['plan_hash']==runplan['plan_hash'] and report.get('manifest_hash') is None and report['expected_attempts']==68 and report['terminal_attempts']==0 and report['execution_complete'] is False and report['release_ready'] is False,'Raw report is not the same pending benchmark')
 need(len(runplan['attempts'])==len(report['attempts'])==68 and len({x['attempt_id'] for x in runplan['attempts']})==68,'Expected exact68 attempts')
 cases={c['case_id']:c for c in runplan['cases']};need(len(cases)==28,'Expected exact28 cases')
 for a,row in zip(runplan['attempts'],report['attempts']):
  need(all(row.get(k)==value for k,value in a.items()) and row['status']=='not_run' and row['strict_success'] is False,'Pending attempt identity/status differs')
  c=cases[a['case_id']];need(all(row.get(k)==c[k] for k in ('case','method','stage','family_id')),'Pending case physics differs')
 return {'plan':plan,'capture':capture,'capture_root':base,'audit':audit,'run_plan':runplan,'raw_report':report,'stages':stages,'identity':identity,'stored_paths':storedpaths,'total_stored':total}

def render(summary):
 esc=lambda x:html.escape(str(x))
 rows=''.join('<tr><td>'+esc(s['name'])+'</td><td>'+esc(s['status'])+'</td><td><pre>'+esc(json.dumps(s['measurements'],sort_keys=True,indent=2))+'</pre></td></tr>' for s in summary['stages'])
 attempts=''.join('<tr><td>'+str(a['order']+1)+'</td><td>'+esc(a['attempt_id'])+'</td><td>not_run</td></tr>' for a in summary['attempts'])
 return '''<!doctype html><meta charset="utf-8"><title>Segmented v4: terminal validation and pending benchmark</title><style>body{font:16px system-ui;max-width:1200px;margin:3em auto;padding:0 1em}table{border-collapse:collapse;width:100%}td,th{padding:.5em;border:1px solid #ccd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}code{overflow-wrap:anywhere}</style><h1>Segmented v4: terminal validation</h1><p>Scientific validation status: <strong>'''+esc(summary['scientific_status'])+'''</strong>. This is the 14-gate correctness validation of the pinned implementation. Benchmark fits: <strong>0 of 68</strong>; preparation has not completed. Full v4 release readiness and accepted-fit covariance are not established.</p><p>The original frozen report runs before preparation and therefore records its native-correctness gate as unavailable without an input manifest. That raw output is preserved; the separate validation table below comes from exact terminal journals and their independent audit. No scientific thresholds or classifications are changed by this presentation.</p><p><a href="summary.json">Presentation summary</a> · <a href="raw-benchmark/report.json">Original pending benchmark JSON</a> · <a href="raw-benchmark/index.html">Original HTML</a> · <a href="independent-audit.json">Independent terminal audit</a> · <a href="raw-capture/manifest.json">Exact raw evidence inventory</a></p><p>Earlier <a href="../preflight01/index.html">preflight fixtures</a> and <a href="../engineering02/index.html">engineering02</a> are separate records, not substitutes for this validation or the benchmark.</p><h2>Executed validation gates</h2><table><tr><th>Gate</th><th>Actual status</th><th>Independently audited measurements</th></tr>'''+rows+'''</table><h2>Frozen identity</h2><pre>'''+esc(json.dumps(summary['identity'],sort_keys=True,indent=2))+'''</pre><h2>Every planned benchmark attempt</h2><p>Missing attempts remain visible. Shared seeds, methods and prefixes are not independent trials. The original150 v3.1 campaign remains a separate required deliverable; this report does not certify its completion.</p><table><tr><th>Order</th><th>Attempt</th><th>Status</th></tr>'''+attempts+'''</table>'''

def publish(plan,output):
 state=inspect(plan);output=Path(output);need(output.is_absolute() and not output.exists() and not output.is_symlink(),'Use a new absolute publication directory')
 output.mkdir(parents=True)
 shutil.copytree(state['capture_root'],output/'raw-capture')
 for key,name in (('independent_audit','independent-audit.json'),('raw_report','raw-benchmark/report.json'),('raw_html','raw-benchmark/index.html'),('interface_review','raw-benchmark/interface-review.json')):
  source,_=checked(plan[key]);target=output/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
 summary={'schema':'orbit-poc-segmented-validation-presentation-v1','scope':'Terminal14 correctness gates before new benchmark preparation; no accepted-fit covariance/release claim','scientific_status':state['audit']['scientific_status'],'identity':state['identity'],'stages':state['stages'],'attempts':state['raw_report']['attempts'],'benchmark_attempts_executed':0,'expected_attempts':68,'release_ready':False,'fit_covariance_authorized':False,'execution_complete':False,'inputs':plan,'raw_report_gate_limitation':'Frozen create_report requires a prepared manifest before it reads native gates; this table separately preserves audited pre-prepare validation.'}
 (output/'summary.json').write_text(json.dumps(summary,sort_keys=True,indent=2)+'\n');(output/'index.html').write_text(render(summary));(output/'presentation-plan.json').write_text(json.dumps(plan,sort_keys=True,indent=2)+'\n')
 files=[]
 for p in sorted(output.rglob('*')):
  if p.is_file():files.append({'path':str(p.relative_to(output)),**{k:v for k,v in artifact(p).items() if k!='path'}})
 need(sum(x['bytes'] for x in files)<=MAX_TOTAL and all(x['bytes']<=MAX_STORED for x in files),'Final publication exceeds bounds')
 manifest={'schema':'orbit-poc-segmented-validation-publication-v1','files':files,'bytes':sum(x['bytes'] for x in files),'source_plan':plan,'helper':artifact(__file__),'scientific_status':summary['scientific_status'],'benchmark_attempts_executed':0,'release_ready':False}
 (output/'manifest.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');return manifest

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();b=a.plan.read_bytes();need(sha(b)==a.sha256,'Presentation plan changed');m=publish(json.loads(b),a.output);print(json.dumps({'manifest':artifact(a.output/'manifest.json'),'files':len(m['files']),'scientific_status':m['scientific_status']}))
if __name__=='__main__':main()
