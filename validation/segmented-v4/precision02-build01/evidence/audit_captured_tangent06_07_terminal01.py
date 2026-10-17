from pathlib import Path
import json,base64,hashlib,xml.etree.ElementTree as ET
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(p):
 p=Path(p);p=p if p.is_absolute() else C/p
 return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
current=json.loads((C/'captured-tangent06-07-independent-current-readback01.json').read_text())
outputs=[];results=[]
for n,capturehash,iterations in [('06','f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044',5),('07','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2',46)]:
 j=json.loads((C/f'captured-tangent{n}-terminal-capture01.json').read_text());items={}
 for x in j['files']:
  b=base64.b64decode(x['base64'],validate=True)
  assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'] and x['path'] not in items
  items[x['path']]=(x,b)
 def one(s):
  found=[v for k,v in items.items() if k.endswith(s)];assert len(found)==1;return found[0]
 def obj(s):return json.loads(one(s)[1])
 p=obj('/control/plan.json');r=obj('/run/replay/result.json');pipe=obj('/control/pipeline.json');results.append(r)
 trace=one('/run/replay/trace.jsonl');rows=[json.loads(x) for x in trace[1].splitlines()]
 assert r['plan_sha256']==one('/control/plan.json')[0]['sha256']
 assert p['inputs']==r['inputs'] and p['inputs']['capture']['sha256']==capturehash
 assert p['inputs']['reader_manifest']['sha256']=='d67e09baf6cc9465c1ef2a3b5949e4edf181832d613167269d5fcc6f58e63f9e'
 assert p['inputs']['reader_tangent']['sha256']=='608cc5af8975084d2b39c92939bdfe8a6da4eb87447a38d7f303b91f4ef11a91'
 assert r['groops_propagations']==r['fit_attempts']==0 and r['release_evidence'] is False
 assert pipe['returncode']==0 and pipe['final_cleanup']['verified'] and not pipe['final_cleanup']['errors']
 assert rows[-1]['status']=='passed' and rows[-1]['iterations']==iterations
 assert r['status']=='reader_passed' and r['terminal']==rows[-1]
 assert {k:rows[0][k] for k in ['tolerance','maximum_iterations','restart']}=={'tolerance':2e-12,'maximum_iterations':120,'restart':20}
 assert rows[0]['epochs']==51840 and rows[0]['dt']==5 and rows[0]['duration']==259195
 projected=[x for x in rows if x['kind']=='projected_residual'];true=[x for x in rows if x['kind']=='true_residual']
 assert len(projected)==iterations and [x['iteration'] for x in projected]==list(range(1,iterations+1))
 assert true[-1]['iteration']==iterations and true[-1]['native_relative_residual']==rows[-1]['relative_residual']<=2e-12
 assert not any(x['kind']=='projected_crossing_true_check' for x in rows)
 q=[x for x in rows if x['kind']=='accepted_quad_residual'];assert len(q)==1
 assert q[0]['iteration']==iterations and q[0]['binary_digits']==113
 assert q[0]['relative_residual_native_velocity_conversion']<=2e-12 and q[0]['relative_residual_exact_velocity_conversion']<=2e-12
 bestq=[x for x in rows if x['kind']=='best_native_iterate_quad_residual'];assert len(bestq)==1
 best=min(true,key=lambda x:x['native_relative_residual'])
 assert bestq[0]['iteration']==best['iteration'] and bestq[0]['native_relative_residual']==best['native_relative_residual']
 assert bestq[0]['relative_residual_native_velocity_conversion']==q[0]['relative_residual_native_velocity_conversion']
 suite=list(ET.fromstring(one('/fixtures/tests.xml')[1]).iter('testsuite'));assert len(suite)==1 and suite[0].attrib['tests']=='3'
 assert all(suite[0].attrib[k]=='0' for k in ['errors','failures','skipped'])
 assert r['fixture_preflight']['status']=='passed' and r['fixture_preflight']['nested_original_reader_checks']==8
 assert r['fixture_preflight']['junit']['sha256']==one('/fixtures/tests.xml')[0]['sha256']
 assert r['trace']['sha256']==trace[0]['sha256'] and r['record_count']==len(rows)
 owned=next(x for x in current['jobs'] if x['number']==n);assert not any(x['same_live'] for x in owned['owned'])
 assert len(owned['owned'])==len(j['owned'])==12
 outputs.append({'case':n,'capture':p['inputs']['capture'],'compact_capture':pin(f'captured-tangent{n}-terminal-capture01.json'),'actual_result':{k:one('/run/replay/result.json')[0][k] for k in ['path','sha256','bytes']},'trace':{k:trace[0][k] for k in ['path','sha256','bytes']},'terminal':rows[-1],'accepted_quad':q[0],'best_native_quad':bestq[0],'compact_records_verified':len(items),'owned_current_nonlive':len(owned['owned']),'fixture_tests_passed':3,'nested_original_reader_checks':8,'reader':r['reader']})
assert results[0]['reader']['sha256']==results[1]['reader']['sha256']
assert results[0]['compiler_version']==results[1]['compiler_version'] and results[0]['reader_libraries']==results[1]['reader_libraries']
v={'schema':'orbit-poc-independent-compensated-quadrature-terminal-review-v1','passed':True,'observed_at':current['observed_at'],'scope':'Diagnostic08 outcome and provenance audit for two distinct captured systems; no full native propagation or release evidence.','control_review':pin('captured-tangent03-independent-control-review01.json'),'candidate_review':pin('tangent72-diagnostic08-independent-review01.json'),'current_readback':pin('captured-tangent06-07-independent-current-readback01.json'),'audit_script':pin('audit_captured_tangent06_07_terminal01.py'),'outcomes':outputs,'findings':['Both captured systems satisfy the unchanged native and independent113-bit residual thresholds.','The same compiled reader and resolved libraries were used for both systems.','Compensation changes floating-point operator evaluations; unchanged preconditioner, GMRES policy, weights and model do not imply identical iteration histories.','These two successes do not certify new tangent matrices encountered during nonlinear native closure.'],'candidate_native_validation_supported':True,'production_release_approved':False,'release_evidence':False,'benchmark_attempts':0,'reviewer_native_runs':0}
p=C/'captured-tangent06-07-independent-terminal-review01.json'
with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(p)))
