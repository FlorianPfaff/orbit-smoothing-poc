from pathlib import Path
import json,base64,hashlib,xml.etree.ElementTree as ET
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(n):
 p=C/n;return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
current=json.loads((C/'captured-tangent03-04-independent-current-readback01.json').read_text());outputs=[]
cases=[('03','passed','f172b81438d7c5cf0c4d2ada953a2a2f42282c833293a8fbf120c75607bf4044','nominal-tangent-capture03-standalone-trace.jsonl'),('04','failed','b1fd97fe4f004a87d459455f0625d609b8d5f9140d63a5dcdb7448e093bc5fd2','tangent72-diagnostic05/actual-trace01.jsonl')]
for n,expected,capturehash,baselinefile in cases:
 j=json.loads((C/f'captured-tangent{n}-terminal-capture01.json').read_text());items={}
 for x in j['files']:
  b=base64.b64decode(x['base64']);assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'];assert x['path'] not in items;items[x['path']]=(x,b)
 def one(s):
  found=[v for k,v in items.items() if k.endswith(s)];assert len(found)==1;return found[0]
 def obj(s):return json.loads(one(s)[1])
 p=obj('/control/plan.json');r=obj('/run/replay/result.json');pipe=obj('/control/pipeline.json');trace=one('/run/replay/trace.jsonl');rows=[json.loads(x) for x in trace[1].splitlines()];baseline=[json.loads(x) for x in (C/baselinefile).read_text().splitlines()]
 assert p['inputs']==r['inputs'] and p['inputs']['capture']['sha256']==capturehash
 assert p['inputs']['reader_manifest']['sha256']=='cb08e2dffff7bcdcb9eb767db48d8b4a1127d5741b863ba166aaf7d12ce3ec6a'
 assert p['inputs']['reader_tangent']['sha256']=='def5e4e87080ccd1329f162d10bdecb0320320dbe821087bc794b35021795759'
 assert r['groops_propagations']==r['fit_attempts']==0 and not r['release_evidence']
 assert pipe['final_cleanup']['verified'] and not pipe['final_cleanup']['errors'];assert rows[-1]['status']==expected
 assert {k:rows[0][k] for k in ['tolerance','maximum_iterations','restart']}=={'tolerance':2e-12,'maximum_iterations':120,'restart':20}
 for kind in ['projected_residual','true_residual']:
  aa=[x for x in baseline if x['kind']==kind];bb=[x for x in rows if x['kind']==kind];count=5 if kind=='projected_residual' else 2;assert aa[:count]==bb[:count]
 crossings=[x for x in rows if x['kind']=='projected_crossing_true_check'];assert crossings[0]['iteration']==crossings[0]['cycle_count']==5 and not crossings[0]['accepted'];assert crossings[1]['cycle_count']==6 and crossings[1]['iteration']==6
 counts=[x for x in rows if x['kind']=='operator_counts'];assert len(counts)==1 and counts[0]['arnoldi']==rows[-1]['iterations'];assert counts[0]['true_residual']==sum(x['kind']=='true_residual' for x in rows)
 suite=list(ET.fromstring(one('/fixtures/tests.xml')[1]).iter('testsuite'));assert len(suite)==1 and suite[0].attrib['tests']=='3' and all(suite[0].attrib[k]=='0' for k in ['errors','failures','skipped'])
 bestq=[x for x in rows if x['kind']=='best_native_iterate_quad_residual'];assert len(bestq)==1;best=min((x for x in rows if x['kind']=='true_residual'),key=lambda x:x['native_relative_residual']);assert bestq[0]['iteration']==best['iteration'] and bestq[0]['native_relative_residual']==best['native_relative_residual']
 if n=='03':
  q=[x for x in rows if x['kind']=='accepted_quad_residual'];assert len(q)==1 and q[0]['iteration']==rows[-1]['iterations']==7;assert q[0]['relative_residual_native_velocity_conversion']<2e-12;assert rows[-1]['relative_residual']==crossings[-1]['true_relative_residual'] and crossings[-1]['accepted'];assert all(not x['accepted'] for x in crossings[:-1]);assert counts[0]=={'kind':'operator_counts','true_residual':4,'arnoldi':7}
 else:
  q=[x for x in rows if x['kind']=='quad_residual'];assert len(q)==1 and q[0]['iteration']==rows[-1]['iterations']==120;assert q[0]['relative_residual_native_velocity_conversion']>2e-12 and bestq[0]['relative_residual_native_velocity_conversion']>2e-12;assert all(not x['accepted'] for x in crossings)
 owned=next(x for x in current['jobs'] if x['number']==n);assert not any(x['same_live'] for x in owned['owned'])
 outputs.append({'case':n,'capture':p['inputs']['capture'],'compact_capture':pin(f'captured-tangent{n}-terminal-capture01.json'),'actual_result':{k:one('/run/replay/result.json')[0][k] for k in ['path','sha256','bytes']},'baseline_trace':pin(baselinefile),'trace':{k:trace[0][k] for k in ['path','sha256','bytes']},'status':expected,'native_terminal':rows[-1],'best_native_quad':bestq[0],'accepted_or_final_quad':q[0],'operator_counts':counts[0],'compact_records_verified':len(items),'owned_current_nonlive':len(owned['owned']),'prefix_check':'initial true and first5projected and first rejected true crossing exact baseline matches','fixture_tests_passed':3,'nested_original_checks':8})
v={'schema':'orbit-poc-independent-crossing-experiment-terminal-review-v1','passed':True,'observed_at':current['observed_at'],'scope':'Diagnostic07 outcome/provenance audit for two captured systems. Experimental candidate does not qualify for production promotion.','control_review':pin('captured-tangent02-independent-code-review01.json'),'candidate_review':pin('tangent72-diagnostic07-independent-review01.json'),'current_readback':pin('captured-tangent03-04-independent-current-readback01.json'),'audit_script':pin('audit_captured_tangent03_04_terminal02.py'),'outcomes':outputs,'findings':['The new small-RHS system meets both original native and independent113-bit residual thresholds after7steps.','The old large-RHS system fails after120steps, including its lowest observed native residual under113-bit re-evaluation.','Both traces match their prior baseline until the first rejected projected crossing; the intended basis-continuation divergence begins afterward.','A fresh current diagnostic06 baseline on oldb1fd is being requested to strengthen regression attribution; prior05 comparison alone is not a new baseline execution.'],'promotion_approved':False,'release_evidence':False,'benchmark_attempts':0,'reviewer_native_runs':0,'reviewer_tooling_note':'An earlier inline audit invocation had a Python conditional-expression spacing syntax error before execution; it made no output or evidence mutation. This saved script is the successful audit.'}
p=C/'captured-tangent03-04-independent-terminal-review01.json'
with p.open('x') as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(p.name)))
