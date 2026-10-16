#!/usr/bin/env python3
"""Read-only independent parsing of actual constrained-QR inputs and outputs."""
from pathlib import Path
import argparse,hashlib,json,math

def need(x,s):
 if not x:raise AssertionError(s)
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def read(p):
 p=Path(p);before=pin(p);raw=p.read_text().splitlines();need(raw[0]=='SEGMENTED_QR_V1','protocol');n,ne,na,ng,nq=map(int,raw[1].split());need(len(raw)==2+n+ne+na+ng+nq,'record count');pos=2
 variables=[tuple(x.split()) for x in raw[pos:pos+n]];pos+=n
 need([int(x[0]) for x in variables]==list(range(n)),'variable IDs')
 def rows(lines):
  result=[]
  for line in lines:
   v=line.split();i,stage,rhs,count=int(v[0]),int(v[1]),float(v[2]),int(v[3]);need(len(v)==4+2*count,'row count');terms=[(int(v[4+2*j]),float(v[5+2*j])) for j in range(count)];need(len({i for i,a in terms})==count and all(0<=i<n and math.isfinite(a) for i,a in terms) and math.isfinite(rhs),'row terms');result.append((i,stage,rhs,terms))
  return result
 eqtext=raw[pos:pos+ne];eq=rows(eqtext);pos+=ne;atext=raw[pos:pos+na];a=rows(atext);pos+=na
 groups=[];owners={}
 for line in raw[pos:pos+ng]:
  v=list(map(int,line.split()));stage,npivot,nfree=v[:3];need(len(v)==3+npivot+nfree,'group size')
  for i in v[3:]:need(0<=i<n and i not in owners,'group ownership');owners[i]=stage
  groups.append(tuple(v))
 pos+=ng;need(len(owners)==n,'complete ownership');queries=raw[pos:]
 need(pin(p)==before,'row bytes mutated')
 return {'pin':before,'variables':variables,'equalities':eq,'stochastic':a,'equality_text':eqtext,'stochastic_text':atext,'groups':groups,'owners':owners,'queries':queries}
def identities(g):
 def h(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return {k:h(g[k]) for k in ('variables','equality_text','stochastic_text')}
def evaluate(g,payload):
 ids=payload.get('variable_ids',list(range(len(g['variables']))));values=payload['step'];need(len(ids)==len(values)==len(g['variables']) and set(ids)==set(range(len(ids))),'solution identity');x=dict(zip(ids,values));need(all(math.isfinite(v) for v in values),'finite step')
 maximum=0.
 for _,_,rhs,terms in g['equalities']:
  products=[a*x[i] for i,a in terms];res=rhs-math.fsum(products);den=abs(rhs)+math.fsum(abs(v) for v in products);ratio=abs(res)/den if den else 0.;maximum=max(maximum,ratio)
 energy=math.fsum((rhs-math.fsum(a*x[i] for i,a in terms))**2 for _,_,rhs,terms in g['stochastic'])
 return maximum,energy

def audit(root):
 import numpy as np
 root=Path(root);plan=json.loads((root/'control/plan.json').read_text());out={'schema':'orbit-poc-shifted-original-row-independent-arithmetic-v1','scope':'Read-only original/shifted row parsing with binary64 products and math.fsum; no native solve or propagation.','plan':pin(root/'control/plan.json'),'methods':[]}
 for method in ('log_drag_ou','pulses'):
  original=json.loads(Path(plan['validations'][method]['path']).read_text());current=json.loads((root/'run'/method/'validation.json').read_text());need(current['passed'] and current['physical_evaluations']==0,'method terminal scope')
  dense=original['comparison']['dense_reference'];need(pin(dense['path'])['sha256']==dense['sha256'],'dense identity');z=np.load(dense['path'],allow_pickle=False);scales=z['scales'];dynamic=z['dynamic'];n=len(scales)
  methods={'method':method,'validation':pin(root/'run'/method/'validation.json'),'profiles':[]}
  for profile in current['comparison']['profiles']:
   seconds=profile['segment_seconds'];base=next(x for x in original['comparison']['profiles'] if x['segment_seconds']==seconds);b=read(base['calls'][0]['input']);baseline_id=identities(b);nlast=json.loads(Path(base['graph']['path']).read_text())['native_epochs']-1;calls=[];owners=None
   for j,call in enumerate(profile['calls']):
    g=read(call['input']);p=pin(call['output']);payload=json.loads(Path(call['output']).read_text());need(payload['status']=='complete' and call['returncode']==0,'native complete')
    need(g['variables']==b['variables'] and g['equality_text']==b['equality_text'],'native variable/equality ledger changed')
    need(g['stochastic_text'][:len(b['stochastic_text'])]==b['stochastic_text'],'native stochastic ledger changed')
    need([int(v[1]) for v in g['variables'][:n]]==[1]*n and all(int(v[1])==0 for v in g['variables'][n:]),'original chart map')
    lam=(0.,.001,1000.,0.)[j];extra=g['stochastic'][len(b['stochastic']):];active=[k for k,v in enumerate(dynamic) if v] if lam else []
    need(len(extra)==len(active),'damping count')
    start=max(x[0] for x in b['equalities']+b['stochastic'])+1
    for row,k in zip(extra,active):need(row[0]==start+k and row[1]==int(g['variables'][k][3]) and row[2]==0 and row[3]==[(k,math.sqrt(lam)/float(scales[k]))],'dynamic-only damping coefficient')
    if j<3:need(not g['queries'],'step query support')
    else:need(g['queries']==[f'1 {k} 1' for k in range(n)],'undamped original covariance queries')
    if owners is None:owners=g['owners']
    else:need(owners==g['owners'],'ownership changed between same-layout calls')
    equality,energy=evaluate(g,payload);need(equality<2e-12,'independent exact-equation residual');relative=abs(energy-payload['residual_energy'])/max(1.,abs(energy));need(relative<2e-12,'independent complete stochastic energy')
    calls.append({'input':g['pin'],'output':p,'damping':lam,'maximum_equality_backward_error':equality,'stochastic_row_residual_energy':energy,'relative_native_energy_difference':relative,'base_stochastic_rows':len(b['stochastic']),'added_dynamic_damping_rows':len(extra)})
   moved=[i for i in range(n) if owners[i]!=b['owners'][i] and 0<owners[i]<nlast];declared=profile['coverage'];need(declared['interior_movement_count']==len(moved) and [x['identifier'] for x in declared['interior_movements']]==moved,'actual interior ownership attribution');need(declared['changed_original_elimination_ids']==sum(owners[i]!=b['owners'][i] for i in range(n)),'changed original owners');need(bool(moved)==declared['adequate'],'coverage classification')
   for row in declared['interior_movements']:need(row['old_stage']==b['owners'][row['identifier']] and row['new_stage']==owners[row['identifier']],'exact original/new owner')
   methods['profiles'].append({'segment_seconds':seconds,'segment_offset_seconds':profile['segment_offset_seconds'],'baseline_rows':b['pin'],'unchanged_base_ledger_hashes':baseline_id,'original_columns':n,'interior_movement_count':len(moved),'calls':calls})
  out['methods'].append(methods)
 out['passed']=True;return out
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--root',type=Path,required=True);v=a.parse_args();print(json.dumps(audit(v.root),sort_keys=True))
