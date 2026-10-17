#!/usr/bin/env python3
"""Compact exact-byte publication of an independently accepted validation07.
Presentation only; no numerical audit, native invocation or remote operations.
"""
from pathlib import Path
import base64,gzip,hashlib,html,json,shutil,datetime,argparse,xml.etree.ElementTree as ET
C=Path('/mnt/d/orbit-segmented-v4/control')
LOCAL=Path('/mnt/d/orbit-segmented-v4/validation-07-results/terminal-01')
STAGES=('native-tests','correction-tests','synthetic-refinement-log_drag_ou','synthetic-refinement-pulses','flight-refinement','eccentric-24h-refinement','objective-log_drag_ou','objective-pulses','nuisance-replay','nuisance-replay-candidate1-point012','segmented-native-tangent','segmented-structural','linearization-log_drag_ou','linearization-pulses')
NATIVE='643a1b6d523a363eae88902f2a2d4807452ea3edbd504bceaad23a94d65fb2f6'
CAPTURE='c800b241b00fedd4a22a081442a998e503e699880a7e76a6731a90f1a923dbc9'
ARRAYS='db424b64e3d1583f2caf9f1ced8cc495ac63b1681953af7bc484b65436452694'

def need(x,message):
 if not x:raise ValueError(message)
def sha(b):return hashlib.sha256(b).hexdigest()
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def match(b,p):need(sha(b)==p['sha256'] and ('bytes'not in p or len(b)==p['bytes']),'Exact bytes differ: '+p['path'])
def checked(p):
 q=Path(p['path']);need(q.is_file() and not q.is_symlink(),'Missing regular pinned source');b=q.read_bytes();match(b,p);return b
def canonical(v):return sha(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def relative(s):
 p=Path(s);need(not p.is_absolute() and '..'not in p.parts and str(p)not in ('','.','manifest.json'),'Unsafe capture path');return p

def inspect():
 need((C/'validation07-terminal-transfer01.json').is_file(),'Single capture transfer not yet certified complete')
 cp=LOCAL/'terminal-capture-01/manifest.json';ap=LOCAL/'terminal-linearization-arrays-01/manifest.json'
 need(pin(cp)['sha256']==CAPTURE and pin(ap)['sha256']==ARRAYS,'Unexpected actual capture identity')
 capture=json.loads(cp.read_bytes());arrays=json.loads(ap.read_bytes())
 auditpath=C/'validation07-terminal-independent-review01.json';need(pin(auditpath)['sha256']=='e1004320bbc53a6d8ec803ae576619cae6bcc0e3a8bd12a1cee58b75501825ef','Actual accepted audit bytes changed');audit=json.loads(auditpath.read_bytes())
 need(audit.get('schema')=='orbit-poc-segmented-validation-terminal-independent-review-v1' and audit.get('consistency_passed') is True and audit.get('cleanup_verified') is True and audit.get('scientific_status')=='passed_scoped_checks','Actual independent terminal acceptance is missing')
 need(audit['benchmark_attempts_executed']==0 and not audit['release_ready'] and not audit['fit_covariance_authorized'],'Audit scope changed')
 for name,p in (('capture',cp),('array_capture',ap)):
  a=audit[name];need(all(pin(p)[k]==a[k]for k in ('sha256','bytes')),'Original/local manifest identity differs')
 need(capture['final_owned_cleanup_verified'] and capture['pipeline_status']=='passed','Capture is not clean terminal pass')
 bench=capture['benchmark_outputs']
 need(set(bench)=={'manifest_present','attempts_directory_present','attempt_entries','scope'} and bench['manifest_present'] is False and bench['attempts_directory_present'] is False and bench['attempt_entries']==[],'Unexpected benchmark outputs')
 need(bench['scope']=='Terminal filesystem metadata only; no benchmark execution is performed by this capture','Unknown benchmark capture scope')
 bysource={};external=[]
 for root,rows,is_array in ((cp.parent,capture['records'],False),(ap.parent,arrays['records'],True)):
  members=set()
  for r in rows:
   p=root/relative(r['stored']['path']);need(not p.is_symlink(),'Captured member symlink');stored=p.read_bytes();match(stored,{**r['stored'],'path':str(p)})
   enc='identity'if is_array else r['encoding'];need(enc in ('identity','gzip'),'Unknown capture encoding')
   raw=gzip.decompress(stored)if enc=='gzip'else stored;match(raw,r['source'])
   need(r['source']['path']not in bysource,'Duplicate original source');members.add(str(p.relative_to(root)))
   bysource[r['source']['path']]={'record':r,'raw':raw,'is_array':is_array}
  actual={str(p.relative_to(root))for p in root.rglob('*')if p.is_file() and p!=root/'manifest.json'}
  need(members==actual,'Capture member inventory differs')
 need(len(arrays['records'])==8,'Missing actual eight-array appendix')
 def raw(p):
  need(p['path']in bysource,'Audited source absent from capture: '+p['path']);b=bysource[p['path']]['raw'];match(b,p);return b
 def value(p):return json.loads(raw(p))
 core={k:value(p)for k,p in audit['artifacts'].items()}
 need(tuple(s['name']for s in audit['stages'])==STAGES,'Audited gate order differs')
 need(tuple(s['name']for s in core['cli_pipeline']['steps'])==STAGES,'Actual gate order differs')
 need(all(s['status']=='passed' and s['independently_consistent'] is True for s in audit['stages']),'A prescribed gate did not pass')
 need(core['cli_pipeline']['status']=='passed' and core['controller']['final_cleanup']['verified'],'Unclosed actual pipeline')
 identity=audit['identity'];freeze=core['source_freeze']
 need(identity['source_file_count']==405 and identity['native_sha256']==NATIVE,'Wrong frozen candidate')
 need(identity['full_source_sha256']==freeze['source']['sha256'] and len(freeze['source']['files'])==405,'Frozen source identity differs')
 provenance=core['native_rebuild_provenance']
 need(provenance.get('schema')=='orbit-poc-v4-native-rebuild-provenance-v3' and provenance.get('status')=='verified_actual_complete_rebuild','Wrong native provenance generation')
 need(len(provenance['native_inputs'])==79 and all(freeze['source']['files'].get(k)==v for k,v in provenance['native_inputs'].items()),'Native input/frozen source mapping differs')
 need(provenance['fixed_stage_names']==list(STAGES),'Native provenance stage inventory changed')
 need(core['config']['segmented_runtime']['native']['sha256']==NATIVE,'Configuration native mismatch')
 need(core['config']['dense_runtime']['native']['sha256']=='f36bb698ea715a7fc3201c71f823315d493d943ecfb8e7ecad8fbb348ba61625','Preserved dense reference mismatch')
 run=core['run_plan'];need(len(run['attempts'])==run['expected_attempts']==68,'Frozen benchmark attempt count differs')
 need(run['plan_hash']==canonical({k:v for k,v in run.items()if k!='plan_hash'}),'Frozen plan hash differs')
 for stage,expected in zip(audit['stages'][:2],(106,51)):
  m=stage['measurements'];need(m['passed']==expected and m['failures']==m['errors']==m['skipped']==0,'Original native/correction counts changed')
  junit=[p for p in stage['raw_artifacts']if p['path'].endswith('/tests.xml')];need(len(junit)==1,'Missing native JUnit')
  tree=ET.fromstring(raw(junit[0]));cases=tree.findall('.//testcase');need(len(cases)==expected and not tree.findall('.//failure') and not tree.findall('.//error') and not tree.findall('.//skipped'),'Actual JUnit counts disagree')
 return cp,ap,capture,arrays,auditpath,audit,core,bysource

def publish(output):
 cp,ap,capture,arrays,auditpath,audit,core,bysource=inspect()
 output=Path(output);need(output.is_absolute() and not output.exists(),'Use fresh publication directory')
 selected={p['path']for p in audit['artifacts'].values()}
 # Every directly audited measured result/JUnit remains byte-for-byte. Repeated
 # megabyte runtime inventories, dense solver covariance/graph payloads and
 # binary arrays stay external with exact pins.
 for stage in audit['stages']:
  for p in stage['raw_artifacts']:
   need(p['path']in bysource,'Missing direct audit artifact');match(bysource[p['path']]['raw'],p)
   if (Path(p['path']).name not in ('request.json','execution.json','graph.json')
       and '/solves/' not in p['path']
       and Path(p['path']).suffix not in ('.npz','.bin','.dat')):
    selected.add(p['path'])
 for path,row in bysource.items():
  name=Path(path).name
  if name in ('worker-result.json','supervisor.json','validation-launch.json') and not row['is_array']:selected.add(path)
 output.mkdir();copies=[];refs=[]
 def save(relative_,b,source=None):
  p=output/relative_;p.parent.mkdir(parents=True,exist_ok=True);need(not p.exists(),'Repeated publication target');p.write_bytes(b)
  if source:copies.append({'publication_path':relative_,'source':source,'sha256':sha(b),'bytes':len(b)})
 def copylocal(path,name=None):
  path=Path(path);p=pin(path);save(name or ('evidence/'+path.name),checked(p),p)
 for path,row in bysource.items():
  r=row['record'];entry={'source':r['source'],'captured_storage':r['stored'],'classification':'external_original_not_copied'}
  if path in selected:
   suffix=path.split('/validation-07/',1)[-1];target='raw/'+suffix
   save(target,row['raw'],r['source']);entry.update(classification='exact_original_copied',publication_path=target)
  refs.append(entry)
 for r in capture['external_not_copied']:refs.append({'classification':'external_original_not_captured','original_record':r})
 copylocal(cp,'capture-manifest.json');copylocal(ap,'array-manifest.json');copylocal(auditpath,'independent-audit.json')
 support=['validation07-terminal-transfer01.json','validation07-actual-startup-independent-review01.json',
 'validation07-startup-independent-readback01.json','validation07-startup01-terminal-capture01.json',
 'validation07-launch-independent-review01.json','validation07-launch-independent-readback01.json',
 'validation07-independent-concrete-packet-review01.json','validation07-host-precheck-independent-review01.json',
 'validation07-host-alias05-root-review01.json','validation07-packet-author-review02.json',
 'validation07-provenance-author-review04.json','validation07-provenance04-root-review01.json',
 'validation07-terminal-auditor01-root-review.json','validation07-terminal-auditor01-author-review.json',
 'validation07-terminal-auditor01-root-tests.log','validation07-terminal-auditor01-root-tests.xml',
 'audit_validation07_terminal01.py','test_validation07_terminal01.py',
 'validation07-flight-propagation-environment-attribution01.json',
 'original150-resume04-current-status-20261017T010852Z.json']
 for name in support:copylocal(C/name)
 # Exact current cleanup evidence is local and already attributed by audit.
 cleanup=audit['actual_owned_process_absence']
 if isinstance(cleanup,dict) and 'path'in cleanup:copylocal(checked_path(cleanup),'evidence/actual-owned-absence.json')
 startup=json.loads((C/'validation07-startup01-terminal-capture01.json').read_text())
 for i,r in enumerate(startup['files']):
  if 'base64'not in r:continue
  b=base64.b64decode(r['base64'],validate=True);match(b,r)
  # Preserve compact actual54 JUnit/result/process and launch controls. The
  # raw base64 receipt above preserves every other captured startup byte.
  if Path(r['path']).name in ('tests.xml','result.json','process.json'):
   save(f'startup-raw/{i:03d}-{Path(r["path"]).name}',b,{k:r[k]for k in ('path','sha256','bytes')})
 old=json.loads((C/'original150-resume04-current-status-20261017T010852Z.json').read_text())
 summary={'schema':'orbit-poc-validation07-publication-summary-v1','prepared_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'scientific_status':audit['scientific_status'],'actual_validation_finished_at':core['controller']['finished_at'],'cli_validation_finished_at':core['cli_pipeline']['finished_at'],
 'identity':audit['identity'],'native_rebuild_provenance':core['native_rebuild_provenance'],
 'stages':audit['stages'],'benchmark_attempts_executed':0,'planned_benchmark_attempts':68,'release_ready':False,'fit_covariance_authorized':False,
 'startup_supplemental_tests':54,'startup_tests_are_additional_to106_51':True,
 'original150_dated_snapshot':{'observed_at':old['observed_at'],'terminal_count':old['terminal_count'],'status_counts':old['status_counts'],
 'active_attempts':[{'order':r['order'],'attempt_id':r['attempt_id']}for r in old['started_without_terminal']],
 'scope':'Live process/status observation only, not a new full scientific/checkpoint audit; archived legacy completions remain legacy.'},
 'remaining':['Independent supplemental actual Polynomial/Time batch-boundary gate','Separately attributed actual Apr24 anchored-flight typed-export/STM gate','Fresh shifted-cut equivalence','Successful multi-day preparation','All 68 frozen benchmark attempts and release gates','Completion/report of the separate original 150-attempt campaign'],
 'flight_scope':'Existing flight_gravity_drag_v1 omits thermal-history sensitivities, other force gradients and event-time derivatives. The preserved controller/source chain indicates the flight-refinement propagation had no QR_PREFIX; only later prediction enabled it. This passed gate does not qualify an anchored-flight replay.',
 'lineage_links':{'complete_build':'../native-complete-build02-terminal01/index.html','bounded_native_checks':'../native-complete-four-checks01/index.html','prior_failures':'../native-complete-build-controls01/index.html','earlier_candidate_failures':'../tangent-rhs-family01/index.html'}}
 save('summary.json',(json.dumps(summary,indent=2,allow_nan=False)+'\n').encode())
 copylocal(Path(__file__),'publication-builder.py')
 save('copy-attribution.json',(json.dumps({'schema':'orbit-poc-publication-copy-attribution-v1','copies':copies},indent=2)+'\n').encode())
 save('external-evidence.json',(json.dumps({'schema':'orbit-poc-publication-external-inventory-v1','references':refs,'array_manifest_original':audit['array_capture'],'local_array_manifest':pin(ap),'bulk_arrays_copied':False},indent=2)+'\n').encode())
 save('manifest-relocation.json',(json.dumps({'schema':'orbit-poc-validation-evidence-relocation-v1','capture':{'original':audit['capture'],'local':pin(cp)},'array_capture':{'original':audit['array_capture'],'local':pin(ap)},'raw_audit_rewritten':False},indent=2)+'\n').encode())
 esc=html.escape
 rows=''.join('<tr><td>'+esc(s['name'])+'</td><td>passed</td><td><details><summary>Audited measurements</summary><pre>'+esc(json.dumps(s['measurements'],indent=2))+'</pre></details></td></tr>'for s in audit['stages'])
 attempts=''.join('<tr><td>'+str(a['order']+1)+'</td><td>'+esc(a['attempt_id'])+'</td><td>not run</td></tr>'for a in core['run_plan']['attempts'])
 text='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Validation07 — actual 14-stage acceptance</title><style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem;line-height:1.45}table{border-collapse:collapse;width:100%}td,th{padding:.5rem;border:1px solid #bbb;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere}a{color:#1656a6}</style><h1>Validation07: all 14 prescribed stages independently accepted</h1><p>The actual pipeline finished <strong>'''+esc(summary['actual_validation_finished_at'])+'''</strong>, with clean owned-process termination. The 106 native and 51 correction tests passed without failures or skips. All four refinements, both objective/prior checks, both distinct nuisance replays and the tangent/structural/linearization stages passed their unchanged criteria. The 54 supplemental startup checks are separate.</p><p><strong>V4 remains unfinished: 0/68 benchmark fits.</strong> Supplemental actual batch/anchored-flight gates, fresh shifted cuts, multi-day preparation, the frozen benchmark and the separate original 150-attempt campaign remain outstanding. No accepted-fit covariance, accuracy superiority or release readiness is claimed.</p><p><a href="independent-audit.json">Exact terminal audit</a> · <a href="summary.json">Measured summary</a> · <a href="capture-manifest.json">Original capture manifest</a> · <a href="array-manifest.json">Eight-array manifest</a> · <a href="external-evidence.json">Complete omitted/copy inventory</a> · <a href="copy-attribution.json">Exact-byte attribution</a></p><p>Lineage: <a href="../native-complete-build02-terminal01/index.html">fresh 611-object build</a>, <a href="../native-complete-four-checks01/index.html">four bounded native checks</a>, <a href="../native-complete-build-controls01/index.html">retained control failures</a> and <a href="../tangent-rhs-family01/index.html">retained rejected numerical experiment</a>. Earlier evidence stays immutable.</p><h2>Actual prescribed gates</h2><table><tr><th>Gate</th><th>Status</th><th>Evidence</th></tr>'''+rows+'''</table><h2>Flight qualification limit</h2><p>'''+esc(summary['flight_scope'])+'''</p><h2>Separate original 150-attempt campaign</h2><p>The dated 01:08:52 UTC October 17 snapshot observed 20 terminal outcomes: 6 failures, 10 timeouts, 2 interruptions and 2 archived legacy completions; attempt 21 was active on its owned CPU 30 chain. This is not a campaign-completion or new scientific audit.</p><p><a href="evidence/original150-resume04-current-status-20261017T010852Z.json">Exact dated live snapshot</a></p><h2>Source and native identity</h2><pre>'''+esc(json.dumps(summary['identity'],indent=2))+'''</pre><h2>All 68 planned attempts</h2><table><tr><th>Order</th><th>Attempt</th><th>Status</th></tr>'''+attempts+'''</table></html>'''
 save('index.html',text.encode())
 members=[{'path':str(p.relative_to(output)),'sha256':pin(p)['sha256'],'bytes':p.stat().st_size}for p in sorted(output.rglob('*'))if p.is_file()]
 manifest={'schema':'orbit-poc-compact-publication-manifest-v1','files':members,'file_count':len(members),'bytes':sum(r['bytes']for r in members),'scope':'Exact-byte compact validation07 evidence; bulky source datasets, native binaries and eight numerical arrays remain external.'}
 save('manifest.json',(json.dumps(manifest,indent=2)+'\n').encode())
 return {'output':str(output),'manifest':pin(output/'manifest.json'),'files':len(members),'bytes':manifest['bytes'],'audit':pin(auditpath)}

def checked_path(p):checked(p);return p['path']
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--output',required=True);args=p.parse_args();print(json.dumps(publish(args.output),indent=2))
