from pathlib import Path
import json,hashlib,base64,xml.etree.ElementTree as ET,collections
C=Path('/mnt/d/orbit-segmented-v4/control');B='/mnt/seagate10tb/orbit-segmented-v4-florianpfaff';D=B+'/tangent-telemetry-04'
def pin(p):
 p=Path(p);v=p.read_bytes();return {'path':str(p),'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)}
cp=C/'nominal-tangent-capture04-terminal-capture01.json';cap=json.loads(cp.read_text());files={}
for f in cap['files']:
 raw=base64.b64decode(f['base64'],validate=True);assert len(raw)==f['bytes'] and hashlib.sha256(raw).hexdigest()==f['sha256'];assert f['path']not in files;files[f['path']]=raw
assert len(files)==16
readback=C/'nominal-tangent-capture04-independent-current-readback01.json';rb=json.loads(readback.read_text());assert rb['passed'] and rb['science_launched']==0
p=json.loads(files[D+'/control/plan.json']);e=json.loads(files[D+'/control/execution.json']);pipe=json.loads(files[D+'/control/pipeline.json']);r=json.loads(files[D+'/run/replay/result.json']);trace=[json.loads(v)for v in files[D+'/run/replay/standalone-trace.jsonl'].splitlines()]
assert p==rb['plan']['value'] and e==rb['execution']['value'];assert len(p['inputs'])==18 and rb['runtime_declarations_preserved']==448 and rb['runtime_declarations_total']==452
assert p['native']==r['native'] and r['native']['sha256']=='a392bd16ce1e1b942d358901bbd36c81da8459e3b1ece12222a68512fe2925c6'
assert r['status']=='native_failed' and r['execution']['returncode']==1 and r['native_evaluations']==1 and r['algorithm_delta']is None
assert r['fixed_initial_state_si']==rb['initialization']['value']['fixed_initial_state_si']==rb['baseline_result']['value']['fixed_initial_state_si']
assert r['historical_initialization_native_sha256']==rb['initialization']['value']['native_binary_sha256']=='a66949456ad67b816d09f2f14df792c68c2685f5304139499e4d90092fd75b22'
assert r['initialization_criteria']=={'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}
assert r['exact_failure_reproduced'] and r['original_failure_signature']==r['replay_failure_signature']==rb['baseline_result']['value']['replay_failure_signature']
assert r['replay_failure_signature']in files[D+'/run/replay/single-evaluation/propagate.log'].decode()
assert r['capture']==cap['external_capture'] and r['capture']['sha256']=='b1020102aefcae66220d7af34e12d17b47b8992d1d45c092fbe09a66027214f3'
root=ET.fromstring(rb['template_text']);actual=ET.fromstring(files[D+'/run/replay/single-evaluation/propagate.xml'])
fields=[('./program/PreprocessingVariationalEquation/outputfileVariational','variational.dat'),('./program/OrbitPocEvaluateVariational/inputfileVariational','variational.dat'),('./program/OrbitPocEvaluateVariational/outputfileOrbit','nominal.dat'),('./program/FileConvert/inputfile','nominal.dat'),('./program/FileConvert/outputfile','nominal.txt')]
for xpath,name in fields:root.find(xpath).text=D+'/run/replay/single-evaluation/'+name
for tree in(root,actual):
 for n in tree.iter():
  if n.text is not None:n.text=n.text.strip() or None
  n.tail=None
assert ET.tostring(root)==ET.tostring(actual)
suites=list(ET.fromstring(files[D+'/run/replay/reader-fixtures/tests.xml']).iter('testsuite'));assert len(suites)==1
assert {k:int(suites[0].get(k,'0'))for k in('tests','failures','errors','skipped')}=={'tests':3,'failures':0,'errors':0,'skipped':0}
assert r['fixture_preflight']['nested_original_reader_checks']==8
assert len(trace)==r['standalone']['record_count']==209
assert trace[0]==r['standalone']['input'] and trace[-1]==r['standalone']['terminal']
assert trace[0]['tolerance']==2e-12 and trace[0]['maximum_iterations']==120 and trace[0]['restart']==20
true=[v for v in trace if v['kind']=='true_residual'];proj=[v for v in trace if v['kind']=='projected_residual'];quads=[v for v in trace if v['kind']=='quad_residual'];best=[v for v in trace if v['kind']=='best_native_iterate_quad_residual'];assert len(best)==1;best=best[0]
assert [v['iteration']for v in proj]==list(range(1,121));minimum=min(true,key=lambda v:v['native_relative_residual']);assert minimum['iteration']==best['iteration']==5 and minimum['native_relative_residual']==best['native_relative_residual']
assert best['selection']=='lowest_observed_native_true_residual' and best['binary_digits']==113
assert best['relative_residual_native_velocity_conversion']>2e-12 and best['relative_residual_exact_velocity_conversion']>2e-12
assert true[-1]['final'] and true[-1]['iteration']==120 and true[-1]['native_relative_residual']==trace[-1]['relative_residual']==1.2851453361637898e-11
assert trace[-1]['status']=='failed' and quads[-1]['iteration']==120 and quads[-1]['relative_residual_native_velocity_conversion']>2e-12
assert pipe['status']=='failed_diagnostic' and pipe['returncode']==1 and pipe['final_cleanup']['verified'] and pipe['final_cleanup']['errors']==[] and not pipe['interrupted_or_timeout']
assert pipe['admission']['status']=='admitted' and pipe['admission']['conflicting_processes']==[] and pipe['plan']['sha256']==r['plan_sha256']==rb['plan']['sha256']
assert len(cap['owned'])==len(rb['owned'])==9 and not any(v['same_live']for v in rb['owned'])
assert all(v['expected']==w for v,w in zip(rb['owned'],cap['owned']))
assert r['fit_attempts']==pipe['fit_attempts']==cap['fit_attempts']==0 and not r['release_evidence'] and not pipe['release_evidence']
cycles=[b['iteration']-a['iteration']for a,b in zip(true,true[1:])]
result={'schema':'orbit-poc-tangent-telemetry04-independent-terminal-review-v1','passed':True,'scope':'Outcome attribution only: current candidate25661 exact native failure and standalone failure reproduced. No solver fix, full closure, covariance, fit or release claim.','raw_capture':pin(cp),'readback':pin(readback),'build_audit':pin(C/'tangent-capture-build06-independent-terminal-review01.json'),'control_audit':pin(C/'nominal-tangent-current-capture03-independent-code-review01.json'),'source_audit':pin(C/'tangent72-diagnostic09-independent-review01.json'),'plan':rb['plan']|{'value':None},'actual_result':next({k:f[k]for k in('path','sha256','bytes')}for f in cap['files']if f['path']==D+'/run/replay/result.json'),'capture':r['capture'],'original_physical_input_pins':12,'exact_compact_records':16,'same_fixed_initial_state':True,'xml_semantic_changes':'exact five output/intermediate path fields only','fixture_tests':3,'nested_reader_checks':8,'trace_rows':209,'projected_steps':120,'cycle_counts':dict(collections.Counter(cycles)),'best_observed_native_iterate':best,'final_native_residual':true[-1]['native_relative_residual'],'final_113bit':quads[-1],'unchanged_guard':{'tolerance':2e-12,'maximum_iterations':120,'restart':20},'operator_prefix_comparison':rb['operator_prefix_comparison'],'owned_identities_non_live':9,'fit_attempts':0,'candidate_verified_fixed':False}
result['plan'].pop('value');out=C/'nominal-tangent-capture04-independent-terminal-review01.json';assert not out.exists();out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'path':str(out),'sha256':pin(out)['sha256'],'best':best,'cycle_counts':result['cycle_counts']}))
