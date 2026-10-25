#!/usr/bin/env python3
"""Assemble14 compact originals into a new archive; no tests, fits or publication."""
import argparse, hashlib, html, json, re
from datetime import datetime, timezone
from pathlib import Path
import verify_packet as v

ROOT=Path(__file__).resolve().parent
def pin(path):
 p=Path(path);return {'path':str(p),'bytes':p.stat().st_size,'sha256':v.sha(p)}
def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as f:json.dump(value,f,indent=2,sort_keys=True,allow_nan=False);f.write('\n')
def write(path,text):
 path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as f:f.write(text)
def require(value,message):
 if not value:raise ValueError(message)

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();output=args.output
 require(output.is_absolute() and output.parent==ROOT and output.resolve()==output and re.fullmatch(r'assembly[0-9]+',output.name),'New ordinary assemblyNN directory under this draft root required')
 plan=v.load(ROOT/'publication-plan.json');require([(x['original'],x['destination']) for x in plan['compact_copy_selection']]==list(v.SELECTION),'Changed compact copy selection')
 audit_path=Path(plan['terminal_audit']['path']);require(v.sha(audit_path)==v.AUDIT_SHA==plan['terminal_audit']['sha256'],'Changed independent terminal audit')
 audit=v.load(audit_path);require(audit['approved_terminal_attribution'] is True and audit['check_count']==len(audit['checks'])==133 and all(x['passed'] is True for x in audit['checks']) and audit['failed_checks']==[] and audit['failure_separation']['aggregate_qualified'] is False,'Incomplete terminal attribution or waived failure')
 sources={p['path']:p for p in audit['evidence']};sources[audit['audit_source']['path']]=audit['audit_source'];sources[str(audit_path)]=pin(audit_path)
 require(plan['existing_publication_reused']['commit']==v.PRIOR_COMMIT and plan['existing_publication_reused']['manifest_sha256']==v.PRIOR_MANIFEST,'Prior publication identity changed')
 for original,dest in v.SELECTION:
  require(original in sources,'Selected source lacks independent audit identity')
  require(pin(original)==sources[original],'Changed selected original '+original)
 output.mkdir();packet=output/'packet';packet.mkdir();provenance=[]
 save(output/'intent.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'builder':pin(ROOT/'build_packet.py'),'verifier':pin(ROOT/'verify_packet.py'),'plan':pin(ROOT/'publication-plan.json'),'terminal_audit':pin(audit_path),'native_runs':0,'publication_performed':False})
 try:
  for original,dest in v.SELECTION:
   source=Path(original);target=packet/dest;target.parent.mkdir(parents=True,exist_ok=True)
   with target.open('xb') as f:f.write(source.read_bytes())
   require(v.sha(target)==sources[original]['sha256'] and target.stat().st_size==sources[original]['bytes'],'Copy differs '+dest)
   provenance.append({'path':dest,'original_path':original,'bytes':target.stat().st_size,'sha256':v.sha(target)})
  save(packet/'provenance.json',{'schema':'exact-copied-originals-v1','files':provenance})
  copied={p for p,d in v.SELECTION}
  prior={'commit':v.PRIOR_COMMIT,'prefix':'validation/v4-fit-reliability/candidate06-native-failure01/','manifest_sha256':v.PRIOR_MANIFEST}
  save(packet/'external-artifacts.json',{'schema':'audited-external-originals-v1','files':[sources[k] for k in sorted(sources) if k not in copied],'prior_publication':prior,'scope':'Exact remaining inputs to the included independent audit. No bulk dataset, runtime tree, row spool or already published native-failure packet is duplicated.'})
  gate=v.load(packet/'evidence/correctness/result.json');seq=v.load(packet/'evidence/sequence/result.json');report=v.expected_report(audit,gate,seq);save(packet/'report.json',report)
  readme=(ROOT/'README.template.md').read_text();old='This is a draft packet template. No new packet verification, publication audit, commit, push or PR update has occurred through this draft.'
  require(readme.count(old)==1,'README template boundary changed')
  readme=readme.replace(old,'This static evidence packet grants no scientific acceptance or release authority. Publication verification and review receipts, when completed, are recorded separately.')
  write(packet/'README.md',readme)
  rows=''.join('<tr><td>'+html.escape(r['stage'])+'</td><td>'+html.escape(r['status'] if r['status']!=v.NO_LAUNCH else 'not launched')+'</td></tr>' for r in gate['stages'])
  links=['README.md','report.json','artifact-manifest.json','provenance.json','external-artifacts.json','evidence/terminal-audit/audit01.json','evidence/terminal-audit/audit.py','evidence/correctness/result.json','evidence/overlapping-review/result.json']
  page='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Candidate06 terminal admission stop</title><style>body{font:17px/1.55 system-ui;max-width:1000px;margin:3em auto;padding:0 1em;color:#17222e}table{border-collapse:collapse;width:100%}td,th{padding:.6em;border-bottom:1px solid #ccd4dc;text-align:left}.failed{border-left:5px solid #ad293c;padding:1em;background:#fff0f1}code{font-size:.9em}</style><h1>Candidate06 first validation sequence: failed aggregate</h1><p class="failed"><strong>4 completed stages; 6 numerical stages and both cold fits not launched.</strong><br>Original native tests:102 passed,4 failed. Correction tests:51 passed. Both synthetic refinements passed. All four completed stages have verified owned cleanup.</p><table><thead><tr><th>Prescribed stage</th><th>Terminal outcome</th></tr></thead><tbody>'''+rows+'''</tbody></table><p>The independently pinned terminal audit passed133 checks of attribution, outcomes and cleanup. It does not qualify the failed aggregate or authorize cold fits, covariance or release. The four original native failures remain preserved.</p><h2>Admission stop and responsibility</h2><p>The parent agent allowed a separate mocked-controls pytest review to overlap the primary sequence. This scheduling mistake caused the unchanged admission guard to refuse flight refinement. Observed PID72934, start tick1506771, matches the exact command and unique output path of the174-test review. This was not a native-fit failure. No unrelated process was signaled by the audited cleanup receipts.</p><p>The review's JUnit start was21:34:00 UTC, the primary terminal receipts were written at21:34:15 UTC, and the review receipt followed at21:34:45 UTC. These receipt timestamps are not a separately instrumented admission-event clock.</p><p><strong>The validation timings are not uncontended benchmark measurements.</strong> Overlapping review work prevents a speedup interpretation.</p><p>Both cold fits remained prepared-only. The separate eleven-stage recovery is outside this attempt; no new preflight, numerical pass or cold-fit result is claimed. Existing models, thresholds, benchmarks and published packets remain unchanged.</p><h2>Evidence</h2><ul>'''+''.join('<li><a href="'+p+'">'+html.escape(p)+'</a></li>' for p in links)+'''</ul><p><a href="https://github.com/FlorianPfaff/orbit-smoothing-poc/blob/'''+v.PRIOR_COMMIT+'''/validation/v4-fit-reliability/candidate06-native-failure01/README.md">Previously published native-failure evidence</a> remains immutable. <a href="https://github.com/FlorianPfaff/orbit-smoothing-poc/pull/9">Draft PR #9</a>. Publication checks confirm evidence integrity, not scientific qualification.</p></html>'''
  for old,new in [('tests:102 passed,4 failed','tests: 102 passed, 4 failed'),('tests:51 passed','tests: 51 passed'),('passed133 checks','passed 133 checks'),('PID72934','PID 72934'),('tick1506771','tick 1506771'),('the174-test','the 174-test'),('was21:34','was 21:34'),('at21:34','at 21:34')]:page=page.replace(old,new)
  write(packet/'index.html',page)
  for name in ('build_packet.py','verify_packet.py','publication-plan.json'):write(packet/name,(ROOT/name).read_text())
  for original,dest in v.SELECTION:require(pin(original)==sources[original],'Original changed during collection '+original)
  files=[{'path':str(p.relative_to(packet)),'bytes':p.stat().st_size,'sha256':v.sha(p)} for p in sorted(packet.rglob('*')) if p.is_file()]
  require({p['path'] for p in files}=={d for s,d in v.SELECTION}|v.GENERATED,'Unexpected packet membership')
  save(packet/'artifact-manifest.json',{'schema':'immutable-publication-manifest-v1','scope':'Failed candidate06 sequence; no release authority','files':files,'file_count':len(files),'total_bytes':sum(p['bytes'] for p in files)})
  receipt={'status':'assembled_not_yet_verified','created_utc':datetime.now(timezone.utc).isoformat(),'manifest':pin(packet/'artifact-manifest.json'),'files_excluding_manifest':len(files),'bytes_excluding_manifest':sum(p['bytes'] for p in files),'native_runs':0,'scientific_code_executed':False,'previous_packets_modified':False,'publication_performed':False}
  save(output/'build-result.json',receipt);print(json.dumps(receipt));return 0
 except BaseException as exc:
  save(output/'build-failure.json',{'status':'failed','error':repr(exc),'partial_packet_preserved':True,'publication_performed':False});raise
if __name__=='__main__':raise SystemExit(main())
