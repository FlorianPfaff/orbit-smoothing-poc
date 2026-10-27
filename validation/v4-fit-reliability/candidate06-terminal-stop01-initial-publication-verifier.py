#!/usr/bin/env python3
"""Portable terminal-archive checks. Never execute archived code or commands."""
import argparse, ast, hashlib, json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ET

AUDIT_SHA='0a5921d6097ddb170dc2e2e2192e1f7e6f0d6e8510e09e66bb097dc2e28b6315'
SEQUENCE_SHA='40343c898a8ccf26d6f57575c520fe1abeab4e96bb3c79973952df6c845b06e2'
GATE_SHA='aca653aae8ae8c712defdc74b550e43be013552e26aebf9cc454f30757df8e95'
PRIOR_COMMIT='1a82ecb6b5cba43bd6795adca7bf6acbbcfca90d'
PRIOR_MANIFEST='ea58aee86610dd917a3c44901bad53a7082665efd756cb43f783503c55ce9b4b'
BASE='/mnt/d/orbit-v41-recovery02/'
REVIEW='/mnt/d/orbit-scientific-adapter01/execution-revision03/tests02/'
SELECTION=(
 (BASE+'density-trial-sequence01/plan.json','evidence/sequence/plan.json'),
 (BASE+'density-trial-sequence01/launch.json','evidence/sequence/launch.json'),
 (BASE+'density-trial-sequence01/started.json','evidence/sequence/started.json'),
 (BASE+'density-trial-sequence01/result.json','evidence/sequence/result.json'),
 (BASE+'candidate06-correctness01/result.json','evidence/correctness/result.json'),
 (BASE+'candidate06-correctness01/detached-result.json','evidence/correctness/detached-result.json'),
 (BASE+'candidate06-correctness01/correction-tests/tests.xml','evidence/correction-tests/tests.xml'),
 (BASE+'candidate06-correctness01/synthetic-refinement-log_drag_ou/result/result.json','evidence/refinements/density.json'),
 (BASE+'candidate06-correctness01/synthetic-refinement-pulses/result/result.json','evidence/refinements/pulses.json'),
 (BASE+'candidate06-terminal-admission-audit01/audit01.json','evidence/terminal-audit/audit01.json'),
 (BASE+'candidate06-terminal-admission-audit01/audit.py','evidence/terminal-audit/audit.py'),
 (REVIEW+'result.json','evidence/overlapping-review/result.json'),
 (REVIEW+'tests.xml','evidence/overlapping-review/tests.xml'),
 (REVIEW+'source-manifest.json','evidence/overlapping-review/source-manifest.json'))
GENERATED={'README.md','index.html','report.json','provenance.json','external-artifacts.json','publication-plan.json','build_packet.py','verify_packet.py'}
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012')
FAILURES={
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[reject]',
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[support]',
 'tests.test_numerics_native_qr::test_native_nuisance_search_is_transactional[exception]',
 'tests.test_numerics_native_qr::test_native_empirical_nuisance_floor_requires_independent_audits[floor_zero_replay-zero_update_replay_failed]'}
NO_LAUNCH='not_executed_or_interrupted_without_receipt'

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):
 def pairs(items):
  result={}
  for k,v in items:
   if k in result:raise ValueError('Duplicate JSON key')
   result[k]=v
  return result
 return json.loads(Path(p).read_text(),object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
def junit(p):
 root=ET.parse(p).getroot();cases=list(root.iter('testcase'));names=[c.get('classname','')+'::'+c.get('name','') for c in cases]
 if len(names)!=len(set(names)):raise ValueError('Duplicate JUnit identity')
 counts={'tests':len(cases),'failures':sum(c.find('failure') is not None for c in cases),'errors':sum(c.find('error') is not None for c in cases),'skips':sum(c.find('skipped') is not None for c in cases)}
 return counts,names
def expected_report(audit,gate,sequence):
 return {'schema':'candidate06-terminal-stop-report-v1','status':'failed','aggregate_qualified':False,'accepted_covariance':False,'release_authority':False,'cold_fits_launched':0,'completed_stages':4,'unlaunched_stages':6,'sequence_plan_sha256':SEQUENCE_SHA,'correctness_plan_sha256':GATE_SHA,'terminal_audit_sha256':AUDIT_SHA,'terminal_audit_checks':133,'outcomes':[{'stage':r['stage'],'status':r['status']} for r in gate['stages']],'completed_evidence':audit['stage_results'],'stop':audit['stop'],'timing_caveat':audit['timing_caveat'],'native_failure_explanation':'Preserved control-environment mismatch: original fixtures expected 17 ordinary trials but observed 0 with production fail-fast enabled. No failure waived.','sequence_error':sequence['error'],'recovery_scope':'The separately prepared eleven-stage controls02 recovery is outside this stopped attempt. This packet claims no new preflight, scientific pass, cold-fit result or release readiness.','prior_publication':{'commit':PRIOR_COMMIT,'prefix':'validation/v4-fit-reliability/candidate06-native-failure01/','manifest_sha256':PRIOR_MANIFEST},'preservation':{'source_changed':False,'thresholds_changed':False,'frozen_benchmarks_changed':False,'old_packets_changed':False,'native_runs_by_packager':0},'portable_verification_scope':'Checks included terminal receipts, audit summaries and compact metric records. Full original supervisor/strict receipts remain pinned external inputs; their detailed ownership was checked by the included independently pinned audit.'}

class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,tag,attrs):
  self.links.extend(v for k,v in attrs if k in ('href','src') and v)

def verify(packet,originals=False):
 checks=[];packet=Path(packet)
 def check(name,value):
  checks.append({'name':name,'passed':bool(value)})
  if not value:raise ValueError(name)
 def read(rel):return load(packet/rel)
 def filecheck(row,path):
  p=Path(path);check('regular file '+str(path),p.is_file() and not p.is_symlink());check('size '+str(path),p.stat().st_size==row['bytes']);check('hash '+str(path),sha(p)==row['sha256'])
 try:
  manifest=read('artifact-manifest.json');names=[r['path'] for r in manifest['files']]
  expected={d for s,d in SELECTION}|GENERATED
  check('manifest exact planned paths',len(names)==len(set(names)) and set(names)==expected)
  check('manifest totals',manifest['schema']=='immutable-publication-manifest-v1' and manifest['file_count']==len(names) and manifest['total_bytes']==sum(r['bytes'] for r in manifest['files']))
  allpaths=list(packet.rglob('*'));check('no symlinks anywhere',not any(p.is_symlink() for p in allpaths))
  check('exact packet inventory',{str(p.relative_to(packet)) for p in allpaths if p.is_file()}==expected|{'artifact-manifest.json'})
  for row in manifest['files']:
   q=PurePosixPath(row['path']);check('safe path '+str(q),not q.is_absolute() and '..' not in q.parts and str(q)==row['path']);check('within packet '+str(q),(packet/str(q)).resolve().is_relative_to(packet.resolve()));filecheck(row,packet/str(q))
  audit_path=packet/'evidence/terminal-audit/audit01.json';check('exact independent audit trust anchor',sha(audit_path)==AUDIT_SHA)
  audit=read('evidence/terminal-audit/audit01.json');check('all133 terminal audit checks retained',audit['check_count']==len(audit['checks'])==133 and all(c['passed'] is True for c in audit['checks']) and audit['failed_checks']==[] and audit['approved_terminal_attribution'] is True)
  sourcepins={p['path']:p for p in audit['evidence']};sourcepins[audit['audit_source']['path']]=audit['audit_source'];sourcepins[SELECTION[9][0]]={'path':SELECTION[9][0],'bytes':74701,'sha256':AUDIT_SHA}
  provenance=read('provenance.json')['files'];check('exact14 original copy mapping',[(p['original_path'],p['path']) for p in provenance]==list(SELECTION))
  for row in provenance:
   expectedpin=sourcepins[row['original_path']];check('copy matches audited identity '+row['path'],row['bytes']==expectedpin['bytes'] and row['sha256']==expectedpin['sha256']);filecheck(row,packet/row['path'])
   if originals:filecheck(row,row['original_path'])
  publication=read('publication-plan.json');check('copied publication plan exact selection and audit',[(r['original'],r['destination']) for r in publication['compact_copy_selection']]==list(SELECTION) and publication['terminal_audit']['sha256']==AUDIT_SHA and publication['publication_authority'] is False)
  external=read('external-artifacts.json');copied={s for s,d in SELECTION}
  wanted={k:v for k,v in sourcepins.items() if k not in copied}
  check('exact external audited pin closure',{r['path']:r for r in external['files']}==wanted and len(external['files'])==len(wanted))
  check('prior publication reused without rewriting',external['prior_publication']=={'commit':PRIOR_COMMIT,'prefix':'validation/v4-fit-reliability/candidate06-native-failure01/','manifest_sha256':PRIOR_MANIFEST})
  if originals:
   for row in external['files']:filecheck(row,row['path'])
  plan=read('evidence/sequence/plan.json');seq=read('evidence/sequence/result.json');gate=read('evidence/correctness/result.json');launch=read('evidence/sequence/launch.json');started=read('evidence/sequence/started.json');detached=read('evidence/correctness/detached-result.json')
  check('exact sequence plan',sha(packet/'evidence/sequence/plan.json')==SEQUENCE_SHA==seq['plan_sha256']==started['plan_sha256']==launch['plan_sha256'])
  check('exact correctness plan attribution',gate['plan']['sha256']==GATE_SHA)
  check('terminal sequence failure',seq['status']=='failed' and seq['returncode']==1 and seq['phase']=='correctness' and 'cold fits not launched' in seq['error'] and seq['signals_received']==[])
  check('detached failure agrees',detached['status']=='failed' and detached['returncode']==1 and detached['signals_received']==[])
  check('same boot attribution',launch['boot_id']==plan['boot_id']=='cb2d0b40-9b17-45f8-9e5c-716efb8e6aa5')
  check('all authority remains withheld',all(gate[k] is False for k in ('all_ten_strict_passed','accepted_covariance','whole_fit_verified','release_authority')) and seq['release_authority'] is False and audit['failure_separation']['aggregate_qualified'] is False)
  check('exact ten-stage order',gate['planned_stages']==plan['gate_stages']==list(STAGES)==[r['stage'] for r in gate['stages']])
  check('four completed six unlaunched',[r['status'] for r in gate['stages']]==['failed','passed','passed','passed']+[NO_LAUNCH]*6)
  stage_audits=audit['stage_results'];check('four audited stages in order',[r['stage'] for r in stage_audits]==list(STAGES[:4]))
  for row,summary in zip(gate['stages'][:4],stage_audits):
   check(row['stage']+' exact audited outcome',row['status']==summary['status'] and row['cleanup_verified'] is True and row['input_identity_after']=='verified')
   for field in ('execution','strict_result','freeze','plan'):
    p=row[field];check(row['stage']+' audited '+field,p['path'] in sourcepins and all(p[k]==sourcepins[p['path']][k] for k in ('bytes','sha256')))
   cleanup=summary['cleanup'];check(row['stage']+' terminal empty-tree summary',cleanup['verified'] is True and cleanup['remaining']==[] and cleanup['empty_tree_certificate']=='kernel_ECHILD' and not any(p['pid'] in (72933,72934) for p in cleanup['signals']))
   if originals:
    raw=load(row['execution']['path']);strict=load(row['strict_result']['path']);owned={(p['pid'],p['start_ticks']) for p in raw['tracked_owned_processes']}
    check(row['stage']+' original cleanup matches included audit',raw['cleanup']==cleanup and raw['owned_process_group_cleaned'] is True and {(p['pid'],p['start_ticks']) for p in cleanup['signals']}<=owned)
    check(row['stage']+' original strict and supervisor agree',strict['stage']==row['stage'] and strict['status']==row['status'] and strict['returncode']==raw['returncode'])
  native=stage_audits[0]['tests'];check('native102/4 retained',native['tests']==len(native['inventory'])==106 and native['passed']==102 and native['failures']==len(native['failed'])==4 and native['skips']==0)
  check('exact four native failures',{r['classname']+'::'+r['name'] for r in native['failed']}==FAILURES)
  if originals:
   rawcounts,rawnames=junit(Path(gate['stages'][0]['execution']['path']).parent/'tests.xml')
   check('original native106 JUnit confirms102/4 with no errors/skips',rawcounts=={'tests':106,'failures':4,'errors':0,'skips':0} and rawnames==[r['classname']+'::'+r['name'] for r in native['inventory']])
  counts,names=junit(packet/'evidence/correction-tests/tests.xml');check('raw correction51 all passed',counts=={'tests':51,'failures':0,'errors':0,'skips':0})
  check('correction raw inventory agrees with audit',names==[r['classname']+'::'+r['name'] for r in stage_audits[1]['tests']['inventory']])
  for label,method,index in [('density','groops_log_drag_ou',2),('pulses','groops_pulses',3)]:
   r=read('evidence/refinements/'+label+'.json');check(label+' correct completed method',r['method']==method and r['status']=='complete' and r['passed'] is True)
   check(label+' original position limits',set(r['metrics'])=={'aligned_position_maximum_m','offgrid_position_maximum_m'} and all(0<=v<3e-5 for v in r['metrics'].values()))
   signals=r['native_signals']['signals'];check(label+' original dual-frequency signal limits',len(signals)==4 and {(s['observable'],s['frequency_hz']) for s in signals}=={(s,f) for s in ('code','carrier') for f in (1575420000.,1227600000.)} and all(0<=s['maximum_fraction_of_sigma']<.01 and s['passed'] is True and s['rows']>0 for s in signals))
   check(label+' fixed-nuisance refinement only',r['native_signals']['fixed_nuisance_values_identical'] is True and r['native_signals']['comparison_weights_frozen'] is True)
   check(label+' exact audited metrics',r['metrics']==stage_audits[index]['metric_evidence']['metrics'] and r['native_signals']==stage_audits[index]['metric_evidence']['native_signals'])
  bycheck={r['name']:r for r in audit['checks']}
  for stage in STAGES[4:]:check(stage+' audited non-launch inventory',bycheck[stage+' only prepared empty placeholders']['detail']==[])
  for stage in ('cold-pulses','cold-density'):check(stage+' audited prepared-only inventory',bycheck[stage+' contains only frozen preparation request and rebinding']['detail']==['rebinding.json','request.json'])
  call=ast.parse(gate['error'],mode='eval').body;message=ast.literal_eval(call.args[0]);prefix='Competing native/numerical workload; preserve it: '
  check('admission stop exact error type',isinstance(call.func,ast.Name) and call.func.id=='RuntimeError' and message.startswith(prefix));observed=json.loads(message[len(prefix):])
  review=read('evidence/overlapping-review/result.json');check('exact observed competitor attribution',len(observed)==1 and observed[0]==audit['stop']['observed_process'] and observed[0]['pid']==72934 and observed[0]['start_ticks']==1506771 and observed[0]['argv']==review['command'] and observed[0]['reason']=='numerical Python controller')
  check('unique overlapping review output','--junitxml='+REVIEW+'tests.xml' in review['command'])
  counts,names=junit(packet/'evidence/overlapping-review/tests.xml');check('raw overlapping174 review all passed',counts=={'tests':174,'failures':0,'errors':0,'skips':0} and review['returncode']==0)
  check('review identified as mocked controls',read('evidence/overlapping-review/source-manifest.json')['scope']=='Pure mocked execution tests; no native fits or processes')
  stop=audit['stop'];check('recorded review interval brackets terminal receipt',datetime.fromisoformat(stop['test_start_utc'])<=datetime.fromisoformat(stop['correctness_result_mtime_utc'])<=datetime.fromisoformat(stop['review_result_mtime_utc']))
  check('no unrelated cleanup or admission relaxation',stop['unrelated_workload_signaled_by_audited_receipts'] is False and stop['admission_changed'] is False)
  check('scheduling responsibility retained','parent agent acknowledged' in stop['scheduling_responsibility'] and 'coordination mistake' in stop['scheduling_responsibility'])
  check('timing limitation retained','not uncontended benchmark measurements' in audit['timing_caveat'])
  check('report exact recomputation from evidence',read('report.json')==expected_report(audit,gate,seq))
  for rel in ('README.md','index.html'):
   text=(packet/rel).read_text();check(rel+' essential disclosure',all(x in text for x in ('scheduling mistake','not uncontended benchmark measurements','133','51','102','failed','not launched')))
  links=Links();links.feed((packet/'index.html').read_text())
  for link in links.links:
   url=urlsplit(link)
   if url.scheme or url.netloc:check('intended external link '+link,link=='https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9' or link.startswith('https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/'+PRIOR_COMMIT+'/validation/v4-fit-reliability/candidate06-native-failure01/'))
   elif url.path:
    p=packet/unquote(url.path);check('safe existing local link '+link,p.resolve().is_relative_to(packet.resolve()) and p.is_file())
  return {'passed':True,'check_count':len(checks),'checks':checks,'manifest_sha256':sha(packet/'artifact-manifest.json'),'verify_originals':originals,'scientific_gate_status':'failed; unchanged','scientific_code_executed':False}
 except Exception as exc:return {'passed':False,'check_count':len(checks),'checks':checks,'error':repr(exc),'verify_originals':originals,'scientific_code_executed':False}

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--packet',type=Path,default=Path(__file__).resolve().parent);parser.add_argument('--verify-originals',action='store_true');parser.add_argument('--output',type=Path);args=parser.parse_args()
 result=verify(args.packet,args.verify_originals);result['created_utc']=datetime.now(timezone.utc).isoformat()
 if args.output:
  with args.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
 print(json.dumps({k:v for k,v in result.items() if k!='checks'}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
