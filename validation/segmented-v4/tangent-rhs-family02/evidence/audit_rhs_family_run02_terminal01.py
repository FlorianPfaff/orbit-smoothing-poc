from pathlib import Path
from decimal import Decimal
from collections import Counter
import base64,datetime,hashlib,json,math
C=Path('/mnt/d/orbit-segmented-v4/control')
D='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-rhs-family-run-02'
F='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-rhs-family-preflight-03'
def digest(raw):return hashlib.sha256(raw).hexdigest()
def pin(p):return {'path':str(p),'sha256':digest(Path(p).read_bytes())}
def reject(v):raise ValueError(v)
def parse(raw,decimal=False):return json.loads(raw,parse_float=Decimal if decimal else float,parse_constant=reject)
def unpack(path):
 c=parse(path.read_bytes());records={}
 for r in c['files']:
  raw=base64.b64decode(r['base64'],validate=True);assert len(raw)==r['bytes']and digest(raw)==r['sha256'];assert r['path']not in records;records[r['path']]=raw
 return c,records
capture=C/'tangent-rhs-family-run02-terminal-capture01.json';cap,raw=unpack(capture);assert len(raw)==172; expected_owned=len(cap['owned_processes'])
precap,preraw=unpack(C/'tangent-rhs-family-preflight03-terminal-capture01.json')
plan=parse(raw[D+'/control/plan.json']);result=parse(raw[D+'/run/replay/result.json']);pipeline=parse(raw[D+'/control/pipeline.json'])
assert digest(raw[D+'/control/plan.json'])=='2d1597f75c42d5d4b506296e2ecaa9d276585c508d6199db01217d596823b73e'
assert result['plan_sha256']==digest(raw[D+'/control/plan.json']) and result['status']=='completed_all_planned_calls'and result['phase']=='run'
assert result['fit_attempts']==result['groops_propagations']==0 and result['release_evidence']is False
assert pipeline['status']=='passed_diagnostic'and pipeline['returncode']==0 and pipeline['final_cleanup']['verified']and not pipeline['final_cleanup']['errors']
assert plan['inputs']['family_audit']['sha256']==digest(raw[D+'/control/family-audit.json'])=='88839f0e53b79d97fda49d85c7ddc833469b37b97984ba43edbfa611027e1de9'
freeze=parse(raw[D+'/control/family-audit.json']);family=parse(preraw[F+'/run/preflight/family/manifest.json']);preflight=parse(preraw[F+'/run/preflight/result.json'])
assert freeze['family_manifest']==plan['inputs']['family_manifest']==preflight['family_manifest']
assert freeze['binary']==preflight['binary']==result['binary']and freeze['source_bundle']==result['source_bundle']==plan['inputs']['source_bundle']
assert result['planned_attempts']==family['execution_order']and len(result['attempts'])==54
cases={c['id']:c for c in family['cases']};tol=Decimal.from_float(2e-12);summaries=[];traces={}
for item,a in zip(family['execution_order'],result['attempts']):
 assert all(a[k]==v for k,v in item.items());case=cases[item['case_id']]
 assert a['capture']=={'path':case['path'],'sha256':case['sha256']}and a['binary']==result['binary']
 assert a['argv']==[result['binary']['path'],item['profile'],case['path']]and a['fit_attempts']==0
 assert a==parse(raw[D+'/run/replay/attempts/'+item['attempt_id']+'/result.json'])
 assert a['status']in('reader_certified','numerical_failure')and math.isfinite(a['elapsed_seconds'])and a['elapsed_seconds']>=0
 for k in('trace','stderr'):assert digest(raw[a[k]['path']])==a[k]['sha256']
 lines=raw[a['trace']['path']].splitlines();rows=[parse(line)for line in lines];exact=[parse(line,True)for line in lines];traces[item['attempt_id']]=exact
 assert len(rows)==a['record_count']and rows[0]==a['input']and rows[-1]==a['terminal']
 assert sum(r.get('kind')=='input'for r in rows)==sum(r.get('kind')=='terminal'for r in rows)==1
 assert rows[0]=={'kind':'input','profile':item['profile'],'epochs':51840,'dt':5,'duration':259195,'tolerance':2e-12,'maximum_iterations':120,'restart':20,'extended_digits':64}
 t=exact[-1];assert type(t['iterations'])is int and 0<=t['iterations']<=120
 if a['status']=='reader_certified':
  assert a['returncode']==0 and t['status']==t['kernel_status']=='passed'
  assert 0<=t['relative_residual']<=tol and 0<=t['physical_double_quad_relative_residual']<=tol
  q=[r for r in exact if r['kind']=='physical_double_quad_residual'and r['selection']=='returned']
  assert len(q)==1 and q[0]['binary_digits']==113 and q[0]['iteration']==t['iterations']and q[0]['relative_residual']==t['physical_double_quad_relative_residual']
  assert raw[a['stderr']['path']]==b''
 else:
  assert a['returncode']==1 and t['status']==t['kernel_status']=='failed'and t['iterations']==120 and t['relative_residual']>tol
  assert raw[a['stderr']['path']] and 'physical_double_quad_relative_residual'not in t
  q=[r for r in exact if r['kind']=='physical_double_quad_residual'];assert len(q)==2 and {r['selection']for r in q}=={'best_kernel_checked','last_checked'}and all(r['binary_digits']==113 for r in q)
  assert next(r for r in q if r['selection']=='last_checked')['iteration']==120
 wide_checks=[r for r in exact if r['kind']=='wide_returned_state_check']
 if item['profile']=='wide':
  assert wide_checks and wide_checks[-1]['iteration']==t['iterations']
  if a['status']=='reader_certified':assert wide_checks[-1]['physical_double_relative_residual']<=tol
  else:assert all(r['physical_double_relative_residual']>tol for r in wide_checks)
 summaries.append(dict(item,status=a['status'],iterations=t['iterations'],kernel_residual=str(t['relative_residual']),returned_quad_residual=str(t.get('physical_double_quad_relative_residual'))if 'physical_double_quad_relative_residual'in t else None,oracle_checks=[{k:str(v)if isinstance(v,Decimal)else v for k,v in r.items()}for r in q]))
counts={p:dict(Counter(a['status']for a in result['attempts']if a['profile']==p))for p in('baseline','wide')}
assert all(sum(v.values())==27 for v in counts.values())
mapping=[('historical_large','captured-tangent07-trace.jsonl','31d568dbc89b64abcdd5593e0c32e26786cb3adfd668c700a4f969ca3b8ea613'),('current_small','captured-tangent06-trace.jsonl','adf78fd45cdaa04fee4454cd25d793f6947c01e00e14fcd83ef1f46e63d2fcc5'),('current_large','nominal-tangent-capture04-standalone-trace.jsonl','45998ee99c0b1cf843520b495b01ab68330ced3c93c0961686f23fca35de62b9')]
def events(rows):
 out=[]
 for r in rows:
  k=r['kind']
  if k in('true_residual','legacy_true_residual'):out.append(('true',r['iteration'],r.get('native_relative_residual',r.get('relative_residual')),r['final']))
  if k in('projected_residual','legacy_projected_residual'):out.append(('projected',r['iteration'],r['relative_residual']))
 return out
comparisons=[]
for anchor,name,h in mapping:
 oldpath=C/name;assert pin(oldpath)['sha256']==h;old=[parse(x,True)for x in oldpath.read_bytes().splitlines()]
 a=next(a for a in result['attempts']if a['case_id']==anchor+'-original'and a['profile']=='baseline');now=traces[a['attempt_id']]
 event_equal=events(old)==events(now)
 terminal_equal=all(old[-1][k]==now[-1][k]for k in('status','iterations','relative_residual'))
 comparisons.append({'anchor':anchor,'prior_trace':pin(oldpath),'current_trace':a['trace'],'normalized_kernel_events_identical':event_equal,'kernel_event_count':len(events(now)),'status_iterations_and_kernel_residual_identical':terminal_equal,'certificate_scope':'Earlier113-bit diagnostic checks and current physical-returned-state certificates have distinct state/conversion semantics; their numeric values are not asserted identical.'})

first_audit_path=C/'tangent-rhs-family-run01-independent-terminal-review01.json'
assert pin(first_audit_path)['sha256']=='192962a052de5e06b754daaa84932a5804a1f585ebead7bf9415b8e55c851d45'
first_audit=parse(first_audit_path.read_bytes());firstcap,firstr=unpack(C/'tangent-rhs-family-run01-terminal-capture01.json')
assert pin(C/'tangent-rhs-family-run01-terminal-capture01.json')==first_audit['run_capture']
firstresult=parse(firstr['/mnt/seagate10tb/orbit-segmented-v4-florianpfaff/tangent-rhs-family-run-01/run/replay/result.json'])
assert result['planned_attempts']==firstresult['planned_attempts']
repeat_comparisons=[]
for a in result['attempts']:
 if a['profile']!='baseline':continue
 olda=next(v for v in firstresult['attempts']if v['attempt_id']==a['attempt_id'])
 assert a['capture']['sha256']==olda['capture']['sha256']
 oldrows=[parse(line,True)for line in firstr[olda['trace']['path']].splitlines()];now=traces[a['attempt_id']]
 oldevents=events(oldrows);newevents=events(now)
 terminal_equal=all(oldrows[-1].get(k)==now[-1].get(k)for k in('status','kernel_status','iterations','relative_residual'))
 complete_trace_equal=oldrows==now
 repeat_comparisons.append({'case_id':a['case_id'],'attempt_id':a['attempt_id'],'previous_trace':olda['trace'],'current_trace':a['trace'],'normalized_kernel_events_identical':oldevents==newevents,'previous_kernel_event_count':len(oldevents),'current_kernel_event_count':len(newevents),'status_iterations_and_kernel_residual_identical':terminal_equal,'complete_trace_semantically_identical':complete_trace_equal,'attempt_status_identical':olda['status']==a['status']})
assert len(repeat_comparisons)==27
paired=Counter()
for case in family['cases']:
 pair={a['profile']:a['status']=='reader_certified'for a in summaries if a['case_id']==case['id']}
 paired['both_certified'if all(pair.values())else 'baseline_only'if pair['baseline']else 'wide_only'if pair['wide']else 'both_failed']+=1

regressions=[]
for case in family['cases']:
 pair={a['profile']:a for a in summaries if a['case_id']==case['id']}
 if pair['baseline']['status']=='reader_certified'and pair['wide']['status']=='numerical_failure':regressions.append({'case_id':case['id'],'baseline':pair['baseline'],'wide':pair['wide']})
# Preserve all paired regressions; no success count is assumed.
readback=C/'tangent-rhs-family-run02-independent-terminal-readback01.json';current=parse(readback.read_bytes());assert current['passed']and len(current['owned'])==expected_owned and not any(r['live']for r in current['owned'])
assert current['result']=={'path':D+'/run/replay/result.json','sha256':digest(raw[D+'/run/replay/result.json'])}
assert current['binary']==result['binary']and current['family_manifest']==preflight['family_manifest']
out={'schema':'orbit-poc-rhs-family-independent-terminal-review-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run_capture':pin(capture),'result':current['result'],'family_manifest':preflight['family_manifest'],'binary':result['binary'],'source_bundle':result['source_bundle'],'preflight_plan':plan['inputs']['preflight_plan'],'preflight_result':plan['inputs']['preflight_result'],'family_audit':pin(C/'tangent-rhs-family-preflight03-independent-family-review01.json'),'actual_cleanup_and_membership':pin(readback),'audit_script':pin(Path(__file__)),'planned_calls':54,'recorded_calls':54,'raw_records_verified':172,'owned_identities_currently_nonlive':expected_owned,'status_counts':counts,'attempts':summaries,'original_baseline_comparisons':comparisons,'repeat_baseline_comparisons':repeat_comparisons,'first_run_audit':pin(first_audit_path),'paired_counts':dict(paired),'regressions':regressions,'conclusion':('The repeated diagnostic retains wide regressions and cannot authorize native integration.' if regressions else 'The repeated frozen diagnostic has no paired wide regression; its measured results are diagnostic evidence only and do not establish native closure, orbit-estimation or release readiness.'),'scope':{'frozen_diagnostic_only':True,'independent_scientific_trials':False,'native_propagations':0,'orbit_benchmark_attempts':0,'native_correction_verified':False,'release_ready':False,'speedup_claim':False}}
target=C/'tangent-rhs-family-run02-independent-terminal-review01.json';target.open('x').write(json.dumps(out,indent=2)+'\n');print(json.dumps(pin(target)))
