"""Exact text-only distribution of one pinned, independently audited diagnostic."""
from pathlib import Path
import argparse,hashlib,json,html,shutil
MAX_FILE=16*1024*1024;MAX_TEXT=32*1024*1024

def need(v,m):
 if not v:raise ValueError(m)
def pin(p):
 p=Path(p);b=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)}
def checked(v):
 p=Path(v['path']);need(p.is_absolute() and p.is_file() and not p.is_symlink(),'Expected exact regular input');b=p.read_bytes();need(len(b)==v['bytes'] and hashlib.sha256(b).hexdigest()==v['sha256'],'Input changed: '+str(p));return b
def rel(v):
 p=Path(v);need(not p.is_absolute() and '..' not in p.parts and str(p) not in ('','.','manifest.json'),'Unsafe destination');return str(p)
def numerical(name,value=None):
 p=Path(name)
 if p.suffix in ('.npz','.npy','.bin','.rows','.jsonl','.tsv'):return True
 if isinstance(value,dict):return any((k in {'epoch_conditionals','conditionals','weighted_design_matrix','design_matrix'} and isinstance(v,(dict,list)) and bool(v)) or numerical('',v) for k,v in value.items())
 if isinstance(value,list):return any(numerical('',v) for v in value)
 return False

def assemble(plan,output):
 need(plan['schema']=='orbit-poc-shifted-publication-plan-v1','Unknown plan');cap=json.loads(checked(plan['capture']));audit=json.loads(checked(plan['audit']));root=Path(plan['capture']['path']).parent
 need(audit['capture']==plan['capture'] and audit['scientific_status']=='passed_scoped_checks' and audit['consistency_passed'] and audit['cleanup_verified'],'Audit attribution/scope differs')
 need(audit['benchmark_attempts_executed']==0 and audit['release_ready'] is False and audit['fit_covariance_authorized'] is False and audit['physical_evaluations']==audit['nuisance_profile_evaluations']==0 and audit['solver_calls']==32,'Unexpected diagnostic scope')
 need(cap['controller']==audit['artifacts']['controller'] and len(cap['records'])==109 and len(cap['external_not_copied'])==32 and len(cap['original_unshifted_rows'])==4,'Capture identity/inventory differs')
 originals={};items=[];external=[]
 for record in cap['records']:
  name=rel(record['stored']['path']);need(name not in originals,'Duplicate capture path');orig={**record['stored'],'path':str(root/name)};b=checked(orig);need(record['source']['sha256']==orig['sha256'] and record['source']['bytes']==orig['bytes'],'Capture is not exact identity encoding');originals[name]=orig
  value=json.loads(b) if Path(name).suffix=='.json' else None
  if numerical(name,value):external.append({'category':'captured_numerical_payload','capture_member':name,'source':record['source'],'local_preserved':orig,'reason':'Actual graph, conditional/step/covariance or numerical array payload stays outside Git.'})
  else:b.decode('utf-8');items.append(('raw-capture/'+name,orig,b))
 need(len(external)==48,'Unexpected numerical payload set requires review')
 need({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'}==set(originals),'Capture membership differs')
 bysource={r['source']['path']:r for r in cap['records']}
 for key in ('controller','execution','launch','plan','runner','runtime_checker','diagnostic_helper'):
  a=audit['artifacts'][key];r=bysource[a['path']];need(all(a[k]==r['source'][k] for k in a if k!='path'),'Audit/capture artifact differs')
 methods=[];profile_keys=[]
 for method in audit['methods']:
  need(method['method'] in ('log_drag_ou','pulses') and method['status']=='passed','Method missing or failed');a=method['raw_result'];need(bysource[a['path']]['source']==a,'Raw method result differs')
  rows=[]
  for profile in method['profiles']:
   key=(method['method'],profile['segment_seconds'],profile['offset_seconds']);profile_keys.append(key)
   need(profile['segment_seconds'] in (3600,14400) and profile['offset_seconds'] in (300,1800),'Unexpected profile')
   need(len(profile['trials'])==3 and [t['damping'] for t in profile['trials']]==[0,.001,1000],'Damping trial inventory differs')
   adequate=profile['coverage']['adequate'];need(adequate==(method['method']!='pulses' or profile['offset_seconds']!=300),'Coverage attribution differs')
   rows.append({'segment_seconds':profile['segment_seconds'],'offset_seconds':profile['offset_seconds'],'numerical_equivalence':'passed_scoped_checks','cut_coverage':'genuine_interior_movement' if adequate else 'no_cut_coverage','interior_movement_count':profile['coverage']['interior_movement_count'],'maximum_map_discrepancy_posterior_sd':max(t['map_discrepancy_posterior_sd'] for t in profile['trials']),'covariance_relative_error':profile['covariance_relative_error'],'maximum_independent_equality_backward_error':max(t['independent_all_row_equality_backward_error'] for t in profile['trials']),'maximum_normalized_full_energy_difference':max(t['normalized_full_energy_difference'] for t in profile['trials']),'trials':profile['trials']})
  methods.append({'method':method['method'],'original_columns':method['original_columns'],'profiles':rows})
 need(len(set(profile_keys))==len(profile_keys)==8 and len(methods)==2,'Missing/duplicate profile')
 for r in cap['external_not_copied']:external.append({'category':'shifted_raw_rows','source':r['artifact'],'reason':r['reason']})
 for r in cap['original_unshifted_rows']:external.append({'category':'original_raw_rows',**r})
 items.extend([('raw-capture/manifest.json',plan['capture'],checked(plan['capture'])),('audit.json',plan['audit'],checked(plan['audit']))])
 for row in plan['support']:
  name='provenance/'+rel(row['destination']);b=checked(row['artifact']);b.decode('utf-8');value=json.loads(b) if Path(name).suffix=='.json' else None;need(not numerical(name,value),'Support would copy a numerical payload');items.append((name,row['artifact'],b))
 need(len({n for n,_,_ in items})==len(items),'Duplicate output');need(sum(len(b) for _,_,b in items)<=MAX_TEXT and all(len(b)<=MAX_FILE for _,_,b in items),'Text distribution exceeds bound')
 output=Path(output);need(output.is_absolute() and not output.exists(),'Use fresh output');output.mkdir(parents=True);files=[]
 for name,orig,b in items:
  q=output/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(b);got=pin(q);need(got['sha256']==orig['sha256'] and got['bytes']==orig['bytes'],'Copied bytes differ');files.append({'path':name,'sha256':got['sha256'],'bytes':got['bytes'],'original':orig})
 summary={'schema':'orbit-poc-shifted-cut-publication-summary-v1','scientific_status':audit['scientific_status'],'identity':audit['identity'],'physical_evaluations':0,'nuisance_profile_evaluations':0,'solver_calls':32,'methods':methods,'limitations':audit['limitations'],'benchmark_attempts_executed':0,'benchmark_attempts_planned':68,'benchmark_status':'not_run','release_ready':False,'fit_covariance_authorized':False,'independent_audit':plan['audit'],'capture':plan['capture'],'preserved_history':plan['preserved_history'],'scope':'Read-only post-validation diagnostic on two captured one-hour synthetic linearizations. No new nonlinear/flight fit or change to immutable validation03.'}
 def write(name,v):
  b=(json.dumps(v,sort_keys=True,indent=2)+'\n').encode() if not isinstance(v,str) else v.encode();p=output/name;p.write_bytes(b);got=pin(p);files.append({'path':name,'sha256':got['sha256'],'bytes':got['bytes']})
 write('summary.json',summary);write('external-evidence.json',{'schema':'orbit-poc-shifted-external-evidence-v1','capture':plan['capture'],'files':external,'scope':'48 captured numerical payloads plus 32 shifted and 4 original row files remain outside Git. These exact references are intentional external evidence, not missing or failed cases.'})
 e=html.escape;rows=[]
 for method in methods:
  for p in method['profiles']:rows.append('<tr>'+''.join('<td>'+e(str(x))+'</td>' for x in [method['method'],p['segment_seconds'],p['offset_seconds'],p['cut_coverage'],p['interior_movement_count'],f"{p['maximum_map_discrepancy_posterior_sd']:.6g}",f"{p['covariance_relative_error']:.6g}"] )+'</tr>')
 history=''.join('<li>'+e(x['description'])+' <a href="provenance/'+e(x['evidence'])+'">Preserved evidence</a></li>' for x in plan['preserved_history'])
 text='<!doctype html><meta charset="utf-8"><title>Shifted-cut diagnostic 01</title><style>body{font:16px system-ui;max-width:1150px;margin:3em auto;padding:0 1em}table{border-collapse:collapse}td,th{padding:.5em;border:1px solid #ccc}code{overflow-wrap:anywhere}</style><h1>Shifted-cut diagnostic 01</h1><p><strong>Scoped diagnostic passed. Benchmark: 0 of 68 fits.</strong> This separate test reused two one-hour synthetic linearizations after <a href="../validation03/index.html">validation03</a>; it performed 24 proposal solves and 8 undamped covariance solves and no physical propagation or nuisance refit. It does not establish full v4 release readiness, long-arc/flight equivalence, speedup, or accepted-fit covariance.</p><p>The 1800-second shifts moved original parameter elimination to genuine interior epochs for both methods and both segment periods. The 300-second pulse shifts moved no original parameter: their numerical agreement is retained, but <strong>they provide no cut-coverage evidence</strong>. On these one-hour problems, the two segment periods must not be counted as independent long-arc trials.</p><table><tr><th>Method</th><th>Period (s)</th><th>Offset (s)</th><th>Cut coverage</th><th>Parameters moved</th><th>Max MAP discrepancy (posterior SD)</th><th>Relative covariance error</th></tr>'+''.join(rows)+'</table><p>Covariance comparisons concern the undamped captured linearization. The diagnostic gradient uses a unit denominator; it is not the normalized nonlinear objective gradient. Full residual/equality checks use independently parsed original rows and unchanged limits.</p><p><a href="summary.json">Machine-readable summary and all 24 proposal trials</a> · <a href="audit.json">Independent terminal audit</a> · <a href="raw-capture/manifest.json">Exact 109-file capture inventory</a> · <a href="external-evidence.json">All external row/array/conditional references</a></p><h2>Preserved failures and corrections</h2><p>Actual shifted staging and the owned runtime smoke passed on their first executions. The failures below belong to fabricated control tests or read-only review invocations; they are not failed native scientific runs. Preparation startup failures are a separate record.</p><ul>'+history+'</ul><p>All earlier failed helper/parser/prelaunch records remain separate from the successful terminal result. Numerical source, physical models, observations, priors and thresholds were not changed by this publication.</p>'
 write('index.html',text)
 for _,orig,_ in items:checked(orig)
 for v in originals.values():checked(v)
 checked(plan['capture']);checked(plan['audit']);need({str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p!=root/'manifest.json'}==set(originals),'Source membership changed during copy')
 result={'schema':'orbit-poc-shifted-cut-git-publication-v1','files':files,'bytes':sum(f['bytes'] for f in files),'capture':plan['capture'],'audit':plan['audit'],'external_evidence_count':len(external),'captured_numerical_payloads_external':48,'shifted_row_files_external':32,'original_row_files_external':4,'benchmark_attempts_executed':0,'release_ready':False,'fit_covariance_authorized':False,'builder':pin(__file__)};(output/'manifest.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n');return pin(output/'manifest.json')

def main():
 p=argparse.ArgumentParser();p.add_argument('--plan',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();pp=pin(a.plan);need(pp['sha256']==a.sha256,'Plan changed');print(json.dumps(assemble(json.loads(checked(pp)),a.output)))
if __name__=='__main__':main()
