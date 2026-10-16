from pathlib import Path
from decimal import Decimal
import json,hashlib,argparse,collections
C=Path('/mnt/d/orbit-segmented-v4/control')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def pin(p):return {'path':str(p),'sha256':sha(p)}
def rows(p):return [json.loads(x,parse_float=Decimal)for x in p.read_text().splitlines()]
def events(values):
 out=[]
 for r in values:
  if r['kind']in('true_residual','legacy_true_residual'):out.append(('true',r['iteration'],r.get('native_relative_residual',r.get('relative_residual')),r['final']))
  if r['kind']in('projected_residual','legacy_projected_residual'):out.append(('projected',r['iteration'],r['relative_residual']))
 return out
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
resultpath=a.root/'run/replay/result.json';result=json.loads(resultpath.read_text());attribution=C/'tangent-rhs-family-baseline-attribution01.json';comparisons=[]
for r in json.loads(attribution.read_text())['rows']:
 old=Path(r['prior_trace']['path']);assert sha(old)==r['prior_trace']['sha256'];item=next(x for x in result['attempts']if x['case_id']==r['new_case_id']and x['profile']=='baseline');new=a.root/'run/replay/attempts'/item['attempt_id']/'trace.jsonl';assert sha(new)==item['trace']['sha256'];before=rows(old);after=rows(new);x,y=events(before),events(after);mismatch=next((i for i,(u,v)in enumerate(zip(x,y))if u!=v),None)
 comparisons.append({'anchor':r['anchor'],'prior_trace':pin(old),'common_binary_trace':pin(new),'prior_terminal':before[-1],'current_terminal':after[-1],'normalized_kernel_events_identical':x==y,'prior_event_count':len(x),'current_event_count':len(y),'first_mismatch_index':mismatch,'first_mismatch_prior':x[mismatch]if mismatch is not None else None,'first_mismatch_current':y[mismatch]if mismatch is not None else None,'outcome_changed':before[-1]['status']!=after[-1]['status'],'iterations_changed':before[-1]['iterations']!=after[-1]['iterations']})
counts=collections.Counter((r['profile'],r['status'])for r in result['attempts']);summary={'schema':'orbit-poc-rhs-common-baseline-comparison-v1','source_result':pin(resultpath),'frozen_attribution':pin(attribution),'planned':len(result['planned_attempts']),'completed':len(result['attempts']),'status_counts':[dict(profile=k[0],status=k[1],count=v)for k,v in counts.items()],'comparisons':comparisons,'scope':'Same-binary bounded RHS diagnostics. Old/new reader traces may differ due code generation; report actual differences. No native closure, physical benchmark or release claim.'}
with a.output.open('x')as f:json.dump(summary,f,indent=2,default=str);f.write('\n')
print(json.dumps({'planned':summary['planned'],'completed':summary['completed'],'counts':summary['status_counts'],'baseline_comparisons':[{k:r[k]for k in('anchor','normalized_kernel_events_identical','outcome_changed','iterations_changed','first_mismatch_index')}for r in comparisons]}))
