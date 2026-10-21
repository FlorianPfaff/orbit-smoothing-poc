"""Publish closed timeout evidence without altering the original automatic report."""
from pathlib import Path
import argparse,hashlib,html,json,shutil,xml.etree.ElementTree as ET

BASE=Path('/home/emper/orbit-nuisance-performance'); SOURCE=BASE/'source'; FIT=BASE/'wholefit01'
AUTO=Path('/mnt/d/orbit-nuisance-performance/publication/wholefit01-results')
OUT=SOURCE/'validation/nuisance-performance/wholefit01-results'
STANDALONE=Path('/mnt/d/orbit-nuisance-performance/publication/wholefit01-audited')
EXPECTED_FREEZE='cb4e4a339361002723cf56053bed27dd521f9f51f097f18b1be148126b78a7e4'
EXPECTED_CHECKER='6316cd37b23edadc678e1a3a083802780488882db37c7ca9d686691f93e74836'
COPIES=[]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def write(rel,value):
 p=OUT/rel;p.parent.mkdir(parents=True,exist_ok=True)
 p.write_text(json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n');return p

def copy(p,rel):
 p=Path(p);raw=p.read_bytes();target=OUT/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 assert target.read_bytes()==raw
 COPIES.append({'source_path':str(p),'relative_path':rel,'sha256':sha(target),'bytes':len(raw)})
 return target

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--audit',type=Path,required=True)
 parser.add_argument('--timestamp',required=True);parser.add_argument('--audit-sha256',required=True)
 args=parser.parse_args()
 assert not OUT.exists() and not STANDALONE.exists(), 'Refusing to replace a publication'
 assert sha(args.audit)==args.audit_sha256
 audit=read(args.audit)
 # The independent outcome audit is a required, separately inspected input.
 assert audit.get('status') in {'accepted','passed','accepted_outcome_integrity','accepted_timeout_outcome_integrity','accepted_actual_outcome_integrity','accepted_preserved_timeout_outcomes_and_partial_prefix_evidence'},audit.get('status')
 original=read(AUTO/'summary.json');checker=read(AUTO/'checker.json');freeze=read(FIT/'freeze.json')
 assert sha(FIT/'freeze.json')==EXPECTED_FREEZE
 assert checker['tool']['sha256']==EXPECTED_CHECKER and checker['analysis_status']=='valid'
 assert checker['scientific_equivalence']['status']=='not_evaluable' and not checker['whole_fit_complete_pair']
 assert original['timing_comparison']=='compromised' and original['speedup_claim'] is None
 assert original['utc_two_hour_budget_compliance']=='not_established'
 runs={r['cache']:r for r in checker['runs']}
 assert set(runs)=={0,1} and all(r['outcome']=='timeout' and not r['accepted_covariance'] and not r['scientific_complete'] for r in runs.values())
 prefixes=checker['partial_point_comparisons'];matched=[p for p in prefixes if p['status'] in ['equal_completed_point','equal_available_prefix']]
 assert [len(p['scientific_comparisons']) for p in matched]==[159,159,159,47]
 assert all(c['equal'] for p in matched for c in p['scientific_comparisons'])
 assert runs[1]['profile_wall_coverage']['completed_nuisance_profiles']==5 and runs[0]['profile_wall_coverage']['completed_nuisance_profiles']==3
 assert runs[1]['optimizer_record']['accepted_iterations']==2 and runs[0].get('optimizer_record') is None
 OUT.mkdir(parents=True,exist_ok=False)
 for p in sorted(AUTO.iterdir()):
  if p.is_file():copy(p,'automatic/'+p.name)
 for name in ['freeze.json','execution-complete.json','controller-launch.json','launch.json','source-inventory.json',
              'input-protocol01.json','preparation.json','runtime-closures01.json','input-layout01.json','input-preflight01.json']:
  copy(FIT/name,'protocol/'+name)
 for name in ['run_wholefit01.py','wholefit_worker01.py','freeze_wholefit01.py']:
  copy(BASE/'control'/name,'controls/'+name)
 for name in ['analyze_nuisance_wholefit.py','check_nuisance_performance_pair.py','analyze_nuisance_profile.py','complete_nuisance_wholefit.py']:
  copy(SOURCE/'scripts'/name,'controls/'+name)
 copy(Path(__file__),'controls/publish_wholefit_results01.py')
 for cache in [1,0]:
  root=FIT/f'cache{cache}'
  for name in ['result.json','supervisor.json','supervisor.plan.json','request.json','post-input-check.json',
               'effective-environment.json','admission.json','factor-retention.json','iterations.json']:
   if (root/name).exists():copy(root/name,f'attempts/cache{cache}/'+name)
  for point in sorted(root.glob('point-*')):
   patterns=['qr.profile.json','profile.execution.json','closure.json','physical_initial.txt','fixed_force.txt',
             'full_pulses_um_s.txt','qr.*.nuisance_line_search.json','qr.*.nuisance_performance.json']
   for pattern in patterns:
    for p in sorted(point.glob(pattern)):copy(p,f'attempts/cache{cache}/'+point.name+'/'+p.name)
 # Copy every compact audit record, including failed reproduction attempts.
 for p in sorted(args.audit.parent.rglob('*')):
  if p.is_file():
   assert p.stat().st_size < 20*1024**2, 'Unexpected bulky audit payload: '+str(p)
   copy(p,'independent/'+str(p.relative_to(args.audit.parent)))
 references={
  'original_automatic_report':{'path':str(AUTO),'summary_sha256':sha(AUTO/'summary.json'),'checker_sha256':sha(AUTO/'checker.json')},
  'scientific_source_commit':freeze['source_commit'],'scientific_source_hash':freeze['source_hash'],
  'protocol_publication':'https://github.com/FlorianPfaff/orbit-smoothing-poc/tree/127a78b/validation/nuisance-performance/wholefit01-protocol',
  'checker_publication':'https://github.com/FlorianPfaff/orbit-smoothing-poc/tree/3ea8f44/validation/nuisance-performance/wholefit-checker01',
  'completion_publication':'https://github.com/FlorianPfaff/orbit-smoothing-poc/tree/301722c/validation/nuisance-performance/wholefit-completion01',
  'independent_outcome_audit':{'original_path':str(args.audit),'relative_path':'independent/'+args.audit.name,'sha256':sha(args.audit)},
  'bulk_evidence':'Inputs, native binaries, rows, factors and large logs stay at their original external paths. The freeze and original checker retain their recorded identities; publication does not imply those bytes are embedded here.'}
 write('references.json',references)
 diagnostic={'schema':'orbit-poc-timeout-prefix-diagnostics-v1','source_checker_sha256':sha(AUTO/'checker.json'),
  'matching_artifact_comparisons':sum(len(p['scientific_comparisons']) for p in matched),
  'comparisons':prefixes,'scope':'Exact common-prefix scientific evidence under declared resource/path normalization in the pinned checker, including explicitly identified pre-release factor hashes. Neither whole-fit trajectory nor accepted covariance is available.'}
 write('prefix-diagnostics.json',diagnostic)
 attempts=[]
 for cache in [1,0]:
  r=runs[cache];root=FIT/f'cache{cache}';result=read(root/'result.json');supervisor=read(root/'supervisor.json')
  assert result['status']=='timeout' and result['converged'] is False and result['covariance_valid'] is False
  assert supervisor['status']=='timeout' and supervisor['owned_process_group_cleaned'] and supervisor['cleanup']['verified']
  assert read(root/'post-input-check.json')['verified']
  attempts.append({'name':r['name'],'cache':cache,'status':'timeout','converged':False,'accepted_covariance':False,
   'recorded_supervisor_seconds':r['wall_seconds'],'peak_process_tree_rss_bytes':r['peak_process_tree_rss_bytes'],
   'strict_nuisance_profiles':r['profile_wall_coverage']['completed_nuisance_profiles'],
   'recorded_accepted_lm_steps':2 if cache else None,
   'recorded_lm_steps_scope':'Two accepted steps recorded' if cache else 'No completed LM-step receipt; first trial unfinished',
   'last_started_point':'point-006-trial-003' if cache else 'point-004-trial-001',
   'owned_cleanup_verified':True,'post_input_identity_verified':True,
   'result_sha256':sha(root/'result.json'),'supervisor_sha256':sha(root/'supervisor.json')})
 summary={'schema':'orbit-poc-audited-wholefit-outcomes-v1','publication_timestamp_utc':args.timestamp,
  'headline':'Both full fits timed out; the 24-hour case remains unresolved.',
  'outcome_integrity_audit':'accepted','audit_scope':'Integrity and attribution of the recorded timeout outcomes only; no convergence or scientific success claim.',
  'independent_audit':references['independent_outcome_audit'],'freeze_sha256':EXPECTED_FREEZE,
  'execution_order':['cache1','cache0'],'attempts':attempts,'whole_fit_complete_pair':False,
  'scientific_equivalence':'not_evaluable','accepted_covariance':False,'release_authority':False,
  'accuracy_superiority_claim':None,'speedup_claim':None,'timing_comparison':'compromised',
  'utc_two_hour_budget_compliance':'not_established','recorded_monotonic_limit_seconds':7200,
  'exact_common_prefix_artifacts':[159,159,159,47],'exact_common_prefix_total':524,'retained_or_canonical_comparisons':422,'pre_release_factor_identity_comparisons':102,
  'case':'500 km circular, quiet atmosphere, normal tracking, 24 hours, reduced-dynamic pulses',
  'pulse_settings':{'interval_seconds':1200.,'sigma_velocity_m_s':1e-4,'frame':'CRF'},
  'interpretation':['The interpolation cache did not resolve the prescribed 24-hour fit within the recorded limit.',
   'Cache-on recorded more optimizer progress, but a clock discrepancy prevents a clean timing or speedup comparison.',
   'Strict nuisance profiling at individual points does not establish strict nonlinear convergence.',
   'No final confirmation, accepted full-fit covariance or complete orbit comparison is available.',
   'Both failures and the unchanged original automatic report are preserved; no attempts were replaced.',
   'The frozen v4 campaign, statistical model, tolerances and executable defaults are unchanged.']}
 write('summary.json',summary)
 write('source-copies.json',{'schema':'orbit-poc-exact-source-copies-v1','copies':COPIES})
 tables=[]
 for a in attempts:
  cache='Enabled' if a['cache'] else 'Disabled'
  lm='Two accepted updates; third trial unfinished' if a['cache'] else 'First trial unfinished; no accepted update receipt'
  tables.append(f'<tr><td>{cache}</td><td><strong>Timeout</strong></td><td>{a["strict_nuisance_profiles"]}</td><td>{lm}</td><td>{a["recorded_supervisor_seconds"]:.3f}</td><td>{a["peak_process_tree_rss_bytes"]/1024**2:.1f} MiB</td><td><a href="attempts/{a["name"]}/result.json">Result</a> · <a href="attempts/{a["name"]}/supervisor.json">Supervisor</a></td></tr>')
 pfx=''.join(f'<tr><td>{html.escape(p["name"])}</td><td>{len(p["scientific_comparisons"])}</td><td>{html.escape(p["status"].replace("_"," "))}</td></tr>' for p in matched)
 page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Audited whole-fit outcomes: both attempts timed out</title><style>body{max-width:1180px;margin:32px auto;padding:0 22px;font:16px/1.55 system-ui;color:#1c2938;background:#f5f7fa}main{padding:32px;background:white;border:1px solid #d6dee8;border-radius:12px}h1{font-size:30px;line-height:1.2}h2{font-size:22px;margin-top:32px}.outcome{padding:18px;background:#fff0ed;border-left:5px solid #b74735}.warning{padding:16px;background:#fff6df;border-left:5px solid #a27612}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;padding:10px;border-bottom:1px solid #d6dee8;vertical-align:top}a{color:#1559a2}code{overflow-wrap:anywhere}small{color:#526477}li{margin:8px 0}</style><main><h1>Both full fits timed out</h1>
<p><small>Audited outcome publication · '''+html.escape(args.timestamp)+'''</small></p><div class="outcome"><strong>The cache fix did not resolve the prescribed 24-hour orbit-estimation case.</strong> Both cache-on and cache-off attempts ended at the recorded 7,200-second supervisor limit. Neither reached strict nonlinear convergence or produced accepted full-fit covariance.</div>
<p>The case is the original 24-hour 500 km circular, quiet-atmosphere, normal-tracking pulse fit: 1,200-second pulses with a 10<sup>−4</sup> m/s Gaussian standard deviation, using the corrected dense estimator.</p><p>The independent audit accepted the integrity and attribution of these timeout outcomes. It did not certify successful estimation, complete numerical equivalence, a speedup or release readiness. All unsuccessful attempts are retained, and the original automatic report is preserved byte-for-byte.</p>
<h2>Recorded outcomes</h2><div class="scroll"><table><thead><tr><th>Cache</th><th>Outcome</th><th>Strict nuisance profiles</th><th>Recorded optimizer progress</th><th>Supervisor seconds*</th><th>Peak process-tree RSS</th><th>Original receipts</th></tr></thead><tbody>'''+''.join(tables)+'''</tbody></table></div>
<p class="warning"><strong>*Timing comparison is compromised.</strong> The preserved host-clock discrepancy prevents a clean speed comparison and does not establish compliance with a two-hour UTC elapsed-time budget. The table reports the original supervisor durations as diagnostics only. More recorded optimizer progress with caching is not a statistically established speedup. <a href="automatic/annotation-0-observation.json">Clock observation</a> · <a href="automatic/annotation-0-supervisor_snapshot.json">Contemporaneous supervisor snapshot</a></p>
<h2>Exact agreement in the common prefix</h2><div class="scroll"><table><thead><tr><th>Physical evaluation</th><th>Matched artifacts</th><th>Evidence</th></tr></thead><tbody>'''+pfx+'''</tbody></table></div>
<p>The 524 matching comparisons cover three completed nuisance-profile points and the available part of the first trial: 422 retained-byte/canonical-value comparisons and 102 recorded pre-release factor identities. They use the pinned checker’s declared output-path and resource-field normalization, direct retained-artifact comparisons, and explicitly identified pre-release factor hashes. They do not establish equivalence of completed orbit fits or covariance. Cache-on's later points have no cache-off counterpart. <a href="prefix-diagnostics.json">Complete prefix diagnostics</a></p>
<h2>Independent audit and preserved evidence</h2><ul><li><a href="independent/'''+html.escape(args.audit.name)+'''">Independent outcome audit</a> — integrity of these outcomes only; its reproduction attempts and any failures are retained in the packet.</li><li><a href="automatic/index.html">Original automatic HTML report</a> · <a href="automatic/summary.json">Original automatic summary</a> · <a href="automatic/checker.json">Original complete checker evidence</a>. Their original pending-audit label is preserved; this separate publication adds the completed audit.</li><li><a href="protocol/freeze.json">Frozen protocol and identities</a> · <a href="protocol/execution-complete.json">Both attempts executed</a> · <a href="attempts/cache1/post-input-check.json">Cache-on input check</a> · <a href="attempts/cache0/post-input-check.json">Cache-off input check</a>.</li><li><a href="attempts/cache1/iterations.json">Last recorded cache-on optimizer history</a> — a partial running checkpoint, retained alongside the terminal timeout.</li><li><a href="summary.json">Audited machine-readable summary</a> · <a href="references.json">Original protocol and bulk-evidence references</a> · <a href="source-copies.json">Exact-copy ledger</a> · <a href="manifest.json">Payload SHA-256 manifest</a>.</li></ul>
<p>Both cache treatments used the same local runtime. Six system libraries differ from the original remote timeout runtime, so this is not a historical-runtime equivalence test.</p><p>Inputs, raw rows, native binaries and large intermediate files remain outside Git, with identities in the freeze and original checker. This publication changes no numerical method, model, weight, prior, tolerance or default. These separate attempts do not replace any frozen v4 benchmark result.</p></main></html>'''
 (OUT/'index.html').write_text(page)
 files=[]
 for p in sorted(OUT.rglob('*')):
  if p.is_file():files.append({'path':str(p.relative_to(OUT)),'sha256':sha(p),'bytes':p.stat().st_size})
 write('manifest.json',{'schema':'orbit-poc-audited-outcome-publication-manifest-v1','publication_timestamp_utc':args.timestamp,
  'scope':'Every payload except this manifest; original automatic report and failed outcomes preserved unchanged.','files':files})
 shutil.copytree(OUT,STANDALONE)
 for item in files:assert sha(OUT/item['path'])==sha(STANDALONE/item['path'])==item['sha256']
 assert sha(OUT/'manifest.json')==sha(STANDALONE/'manifest.json')
 print(json.dumps({'source':str(OUT),'standalone':str(STANDALONE),'payloads':len(files),'exact_copies':len(COPIES),
                   'bytes':sum(f['bytes'] for f in files),'manifest_sha256':sha(OUT/'manifest.json')}))

if __name__=='__main__':main()
