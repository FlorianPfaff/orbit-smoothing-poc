"""Portable packet checks; optional original-host byte checks. No native execution."""
import argparse,copy,hashlib,json,math,re,struct
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote,urlsplit
A=argparse.ArgumentParser();A.add_argument('--verify-originals',action='store_true');args=A.parse_args()
P=Path(__file__).parent
if not (P/'manifest.json').exists():P=P/'packet'
checks=[]
def check(name,ok):checks.append({'name':name,'passed':bool(ok)})
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def matrix(p):
 data=p.read_bytes();m,n=struct.unpack('<QQ',data[:16]);v=struct.unpack('<'+str(m*n)+'d',data[16:]);return m,n,v
m=read(P/'manifest.json');paths={x['path'] for x in m['files']};actual={str(p.relative_to(P)) for p in P.rglob('*') if p.is_file() and p.name!='manifest.json'}
check('exact_packet_membership',paths==actual);check('unique_manifest_paths',len(paths)==len(m['files']))
for f in m['files']:
 p=P/f['path'];check('bytes:'+f['path'],p.is_file() and not p.is_symlink() and p.stat().st_size==f['bytes'] and sha(p)==f['sha256'])
sm=read(P/'source-map.json')['files'];mapping={x['source']:x['path'] for x in sm}
for f in sm:
 check('unchanged_packaged_copy:'+f['path'],sha(P/f['path'])==f['sha256'])
 if args.verify_originals:check('original_host_copy:'+f['path'],sha(Path(f['source']))==f['sha256'])
r=read(P/'report.json');base=P/'evidence/one-hour-run01';terminal=read(base/'result.json');freeze=read(base/'freeze.json');compact=read(P/'plan-summary.json')
check('exact_two_outcomes',r['counts']=={'planned':2,'passed':1,'failed':1} and [x['status'] for x in terminal['stages']]==['passed','failed'])
check('exact_order',r['execution_order']==terminal['planned_stages']==['cold-pulses','cold-density'])
check('freeze_original_plan',freeze['plan']['sha256']==compact['original_plan']['sha256'])
check('freeze_identity',r['freeze_sha256']==sha(base/'freeze.json'))
check('no_benchmark_or_release_claim',r['no_new_native_runs_for_publication'] is True and not any(r[k] for k in ['frozen_benchmarks_changed','release_authority','scientific_accuracy_superiority_claim','covariance_calibration_verified']))
allowed={('backend','groops_executable'),('expected_native_binary_sha256',),('source_hash',)}
for row in r['stages']:
 s=row['stage'];b=base/s;q=read(b/'strict-result.json');u=read(b/'supervisor.json');backend=read(b/'backend-result.json');it=read(b/'fit/iterations.json');job=read(b/'request.json');j=read(b/'rebinding.json');original=read(base/'originals'/f'{s}.json')
 check('status:'+s,row['status']==q['status'] and row['numerical_status']==backend['numerical_status'])
 check('counters:'+s,row['accepted_iterations']==it['accepted_iterations'] and row['trial_evaluations']==it['trial_evaluations'])
 check('timing_memory:'+s,row['backend_fit_seconds']==backend['elapsed_seconds'] and row['supervised_seconds']==u['elapsed_seconds'] and row['peak_process_tree_rss_bytes']==u['peak_process_tree_rss_bytes'])
 check('cleanup:'+s,u['owned_process_group_cleaned'] and u['cleanup']['verified'] and not u['signals_received'])
 check('no_resource_exhaustion:'+s,u['elapsed_seconds']<7200 and u['peak_process_tree_rss_bytes']<8*1024**3)
 check('cold_receipt:'+s,q['cold_start_evidence']['initial_state_exact'] and q['cold_start_evidence']['no_nuisance_donor'] and q['cold_start_evidence']['no_physical_override'] and not q['initial_state_override'] and not q['nuisance_donor'])
 check('only_runtime_rebindings:'+s,len(j['journal'])==3 and {tuple(x['path']) for x in j['journal']}==allowed)
 reconstructed=copy.deepcopy(original)
 for x in j['journal']:
  parent=reconstructed
  for key in x['path'][:-1]:parent=parent[key]
  check('before_value:'+s+':'+'.'.join(x['path']),parent[x['path'][-1]]==x['before']);parent[x['path'][-1]]=x['after']
 check('reconstructed_request:'+s,reconstructed==job)
 check('original_request_sha:'+s,sha(base/'originals'/f'{s}.json')==j['original']['sha256'])
 for key,x in q['cold_start_evidence'].items():
  if isinstance(x,dict) and 'path' in x:check('cold_file:'+s+':'+key,sha(P/mapping[x['path']])==x['sha256'])
 check('same_native_source:'+s,backend['native_binary_sha256']==r['native_binary_sha256'] and backend['source_hash']==r['source_hash'])
pb=base/'cold-pulses';q=read(pb/'strict-result.json');ev=q['evidence'];final=pb/'fit/point-019-final-covariance';profile=read(final/'qr.profile.json');diag=read(final/'qr.7.diagnostics.json');it=read(pb/'fit/iterations.json')
check('pulse_complete_covariance',q['whole_fit_verified'] and q['accepted_covariance'] and q['backend_outcome']['converged'] and q['backend_outcome']['covariance_valid'])
check('pulse_ten_accepted_trials',it['accepted_iterations']==it['trial_evaluations']==10 and all(x['accepted'] for x in it['history'] if 'trial' in x))
check('strict_fresh_nuisance',profile['nuisance_converged'] and not profile['nuisance_floor_limited'] and profile['fresh_full_nuisance_confirmed'] and profile['fresh_full_nuisance_update_m']<1e-8 and all(x['maximum_update_m']<1e-8 for x in profile['history'][-2:]))
corr=ev['fresh_final_correction'];check('strict_final_thresholds',corr['normalized_gradient']<1e-8 and corr['raw_correction']['position_change_m']<30e-6 and corr['raw_correction']['pulse_update_m_s']<1e-8 and corr['stationary'] and not corr['nuisance_floor_limited'])
check('fresh_final_factor_identity',sha(final/'qr.7.R.bin')==ev['final_factor']['sha256'] and sha(final/'qr.profile.json')==ev['final_profile']['sha256'])
check('undamped_reported_rank',diag['lambda']==0 and diag['rank']==diag['retained_parameters']==91 and diag['sigma_min']>10*diag['rank_threshold'] and ev['rank']['rank']==ev['rank']['columns']==91)
a,n,R=matrix(final/'qr.7.R.bin');br,bc,b=matrix(final/'qr.7.rhs.bin');check('factor_dimensions',a==n==br==91 and bc==1)
objective=read(pb/'backend-result.json')['objective'];gradient=max(abs(sum(R[i*n+j]*b[i] for i in range(n))) for j in range(n))/max(1.,math.sqrt(2*objective))
check('recomputed_final_gradient',math.isclose(gradient,corr['normalized_gradient'],rel_tol=1e-10,abs_tol=1e-16) and gradient<1e-8)
last=[x for x in it['history'] if 'trial' in x][-1];check('floor_caveat_preserved',last['actual_reduction']<last['objective_floor'] and not last['objective_reduction_numerically_resolved'] and r['pulse_last_accepted_trial']['actual_reduction']==last['actual_reduction'])
db=base/'cold-density';dq=read(db/'strict-result.json');di=read(db/'fit/iterations.json');de=read(db/'fit/point-004-trial-001/closure-02/propagate.execution.json')
check('density_failure_preserved',dq['status']=='failed' and not dq['accepted_covariance'] and not dq['whole_fit_verified'] and di['status']=='native_failure' and di['accepted_iterations']==0 and di['trial_evaluations']==1)
check('native_failure_not_timeout','Nonfinite equinoctial reference input' in (db/'fit/point-004-trial-001/closure-02/propagate.log').read_text() and de['returncode']==1 and not de['timed_out'])
v=[float(x.split()[-1]) for x in (db/'fit/point-004-trial-001/native/log_density.txt').read_text().splitlines() if x.strip()]
check('extreme_unaccepted_trial',max(v)==r['density_failure']['trial_log_density_max'] and min(v)==r['density_failure']['trial_log_density_min'] and math.exp(max(v))==r['density_failure']['maximum_trial_density_multiplier'])
review=read(P/r['independent_prelaunch_review']['path']);tests=read(P/r['control_tests']['path'])
check('prelaunch_review',review['approved'] and review['check_count']==583 and review['freeze_sha256']==r['freeze_sha256'] and all(x['passed'] for x in review['checks']))
check('controls_tests',tests['passed'] and tests['tests']==50 and not tests['failures'] and not tests['errors'] and not tests['skipped'])
check('earlier_fixture_failure_preserved',(P/'evidence/one-hour-controls01/tests03.log').is_file() and (P/'evidence/one-hour-controls01/development-test-history.json').is_file())
class Links(HTMLParser):
 def __init__(self):super().__init__();self.links=[]
 def handle_starttag(self,t,attrs):
  for k,v in attrs:
   if k in ['href','src']:self.links.append(v)
for rel in ['index.html','README.md']:
 p=P/rel
 if p.suffix=='.html':a=Links();a.feed(p.read_text());links=a.links
 else:links=re.findall(r'\]\(([^)]+)\)',p.read_text())
 for href in links:
  u=urlsplit(href)
  if not u.scheme and u.path:check('link:'+rel+':'+href,(p.parent/unquote(u.path)).is_file())
out={'schema':'orbit-poc-cold-publication-check-v1','passed':all(x['passed'] for x in checks),'check_count':len(checks),'failed':[x['name'] for x in checks if not x['passed']],'checks':checks,'manifest_sha256':sha(P/'manifest.json'),'original_sources_verified':args.verify_originals,'recomputed_final_gradient':gradient,'scope':'Packet membership/bytes, original receipt semantics, exact cold request rebinding and final factor gradient. No native rerun, independent covariance calibration or complete scientific audit.','release_authority':False}
print(json.dumps(out,indent=2));raise SystemExit(0 if out['passed'] else 1)
