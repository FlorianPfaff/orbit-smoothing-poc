from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit,unquote
import hashlib,json,math,struct,datetime
B=Path(__file__).parent;P=B/'packet';checks=[]
def ck(n,v):checks.append({'name':n,'passed':bool(v)})
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
m=read(P/'manifest.json');listed={r['path'] for r in m['files']};actual={str(p.relative_to(P)) for p in P.rglob('*') if p.is_file() and p!=P/'manifest.json'}
ck('exact_unique_membership',listed==actual and len(listed)==len(m['files']))
for row in m['files']:
 p=P/row['path'];ck('safe_member:'+row['path'],p.resolve().is_relative_to(P) and not p.is_symlink());ck('identity:'+row['path'],p.stat().st_size==row['bytes'] and sha(p)==row['sha256'])
sm=read(P/'source-map.json')['files'];mapping={x['source']:P/x['path'] for x in sm}
for row in sm:ck('original_copy:'+row['path'],sha(Path(row['source']))==row['sha256']==sha(P/row['path']))
r=read(P/'report.json');base=P/'evidence/one-hour-run01';term=read(base/'result.json');ck('both_terminal_outcomes',term['status']=='failed' and [(x['stage'],x['status']) for x in term['stages']]==[('cold-pulses','passed'),('cold-density','failed')]);ck('reported_counts',r['counts']=={'planned':2,'passed':1,'failed':1})
for name in ('cold-pulses','cold-density'):
 root=base/name;q=read(root/'strict-result.json');be=read(root/'backend-result.json');sup=read(root/'supervisor.json');orig=base/'originals'/f'{name}.json';req=read(root/'request.json');reb=read(root/'rebinding.json');value=read(orig)
 ck('original_pinned:'+name,sha(orig)==reb['original']['sha256'])
 ck('only_runtime_edits:'+name,{tuple(x['path']) for x in reb['journal']}=={('backend','groops_executable'),('expected_native_binary_sha256',),('source_hash',)} and len(reb['journal'])==3)
 for x in reb['journal']:
  cur=value
  for k in x['path'][:-1]:cur=cur[k]
  ck('before_value:'+name+str(x['path']),cur[x['path'][-1]]==x['before']);cur[x['path'][-1]]=x['after']
 ck('rebinding_complete:'+name,value==req)
 ck('strict_cleanup:'+name,sup['owned_process_group_cleaned'] is True and sup['cleanup']['verified'] is True and sup['cleanup']['empty_tree_certificate']=='kernel_ECHILD' and sup['cleanup']['remaining']==[] and not sup['signals_received'])
 ck('limits_unchanged:'+name,sup['elapsed_seconds']<7200 and sup['peak_process_tree_rss_bytes']<8*1024**3)
 cold=q['cold_start_evidence'];ck('original_cold:'+name,cold['initial_state_exact'] and cold['no_nuisance_donor'] and cold['no_physical_override'] and cold['nominal_orbit_sha256']=='16bb3d709b50d6918c0ee2dbb6d419f17f17e934c04f39d607c77abcf73f3db1')
 for k,v in cold.items():
  if isinstance(v,dict) and 'path'in v:ck('cold_hash:'+name+':'+k,sha(mapping[v['path']])==v['sha256'])
 ck('native_identity:'+name,be['native_binary_sha256']=='28c725765201e4702875ec8407d3bc497aa4bdfa3092a305b15a3233cfbd675d')
 if name=='cold-pulses':
  ev=q['evidence'];profile=read(mapping[ev['final_profile']['path']]);co=ev['fresh_final_correction'];raw=co['raw_correction'];history=read(root/'fit/iterations.json');ck('ten_accepted',history['accepted_iterations']==history['trial_evaluations']==10)
  ck('strict_completion',q['whole_fit_verified'] and q['accepted_covariance'] and be['converged'] and be['covariance_valid'])
  ck('strict_final_nuisance',profile['nuisance_converged'] and not profile['nuisance_floor_limited'] and profile['fresh_full_nuisance_confirmed'] and 0<=profile['fresh_full_nuisance_update_m']<1e-8 and len(profile['history'])>=2 and all(0<=x['maximum_update_m']<1e-8 for x in profile['history'][-2:]))
  ck('strict_final_dynamics',co['stationary'] and not co['nuisance_floor_limited'] and 0<=co['normalized_gradient']<1e-8 and 0<=raw['position_change_m']<3e-5 and 0<=raw['pulse_update_m_s']<1e-8 and 0<=raw['density_update']<1e-4)
  ck('full_rank',ev['rank']['status']=='full_rank' and ev['rank']['rank']==ev['rank']['columns']==91 and ev['rank']['minimum_singular_value']>10*ev['rank']['threshold'])
  last=[x for x in history['history'] if 'trial'in x][-1];ck('floor_caveat',0<last['actual_reduction']<last['objective_floor'] and last['objective_reduction_numerically_resolved'] is False and 'below the measured numerical floor' in (P/'README.md').read_text() and r['pulse_last_accepted_trial']['actual_reduction']==last['actual_reduction'])
 else:
  ck('density_rejected',not q['whole_fit_verified'] and not q['accepted_covariance'] and not be['converged'] and not be['covariance_valid'] and be['numerical_status']=='native_failure')
  er=root/'fit/point-004-trial-001/closure-02';ex=read(er/'propagate.execution.json');ck('density_actual_error','Nonfinite equinoctial reference input'in (er/'propagate.log').read_text() and ex['returncode']==1 and ex['timed_out'] is False)
ck('no_release_claim',r['release_authority'] is False and r['scientific_accuracy_superiority_claim'] is False and r['covariance_calibration_verified'] is False and r['frozen_benchmarks_changed'] is False)
class Links(HTMLParser):
 def handle_starttag(self,tag,attrs):
  for k,v in attrs:
   if k in ('href','src'):
    u=urlsplit(v)
    if not u.scheme and u.path:ck('html_link:'+v,(P/unquote(u.path)).is_file())
Links().feed((P/'index.html').read_text())
body=(B/'pr-body.md').read_text();ck('pr_outcomes_and_limits',all(t in body for t in ['one-hour-cold01','Nonfinite equinoctial reference input','91/91','remains a draft','coverage is untested']))
result={'schema':'orbit-poc-one-hour-publication-independent-review-v1','created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'approved':all(x['passed'] for x in checks),'packet_manifest_sha256':sha(P/'manifest.json'),'check_count':len(checks),'checks':checks,'failed':[x['name'] for x in checks if not x['passed']],'scope':'Independent artifact, source-copy, original-request, strict-terminal-evidence, failure-inclusion and portable-report audit. No nonlinear refit or empirical covariance calibration.','release_authority':False,'prior_audit_attempt':{'file':'independent-review-attempt01.json','sha256':sha(B/'independent-review-attempt01.json'),'failed_check':'floor_caveat','cause':'Auditor required literal Python e-09 formatting while Markdown used mathematically identical e-9; numeric evidence and caveat were present. Corrected auditor compares numeric receipt values and explicit caveat prose. Packet unchanged.'}}
with (B/'independent-review.json').open('x') as f:json.dump(result,f,indent=2);f.write('\n')
print(json.dumps({k:result[k] for k in ['approved','check_count','failed','packet_manifest_sha256']}));raise SystemExit(0 if result['approved'] else 1)
