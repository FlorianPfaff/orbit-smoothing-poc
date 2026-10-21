from pathlib import Path
import json,base64,hashlib,datetime,re
C=Path('/mnt/d/orbit-segmented-v4/control')
def pin(n):
 p=C/n;return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
out=[]
for n,status,code in [('01','native_failed',1),('02','native_completed',0)]:
 j=json.loads((C/f'nominal-compensation-single{n}-terminal-capture01.json').read_text());items={}
 for x in j['files']:
  b=base64.b64decode(x['base64'],validate=True);assert len(b)==x['bytes'] and hashlib.sha256(b).hexdigest()==x['sha256'];assert x['path']not in items;items[x['path']]=(x,b)
 def one(s):
  found=[v for k,v in items.items()if k.endswith(s)];assert len(found)==1;return found[0]
 def obj(s):return json.loads(one(s)[1])
 p=obj('/control/plan.json');r=obj('/run/replay/result.json');pipe=obj('/control/pipeline.json');fixture=obj('/supplemental-regression/result.json');now=json.loads((C/f'nominal-compensation-single{n}-independent-terminal-readback01.json').read_text())
 assert r['status']==status and r['native_evaluations']==1 and r['fit_attempts']==0 and r['release_evidence']is False
 assert r['plan_sha256']==one('/control/plan.json')[0]['sha256'] and r['native']==p['native']
 assert r['native']['sha256']=='25661fd88779c009a84f7479b8fb9639aaeb9a37df3a11dc2d4adff2af94f7c2'
 assert r['execution']['returncode']==pipe['returncode']==code and not r['execution']['timed_out']
 assert r['execution']['config_sha256']==one('/single-evaluation/propagate.xml')[0]['sha256']
 assert pipe['final_cleanup']['verified'] and not pipe['final_cleanup']['errors'] and not any(x['same_live']for x in now['owned'])
 assert r['supplemental_regression']==fixture and fixture['status']=='passed' and fixture['frozen_suite_counts_changed']is False
 assert fixture['header']['sha256']=='9a46f04591de8b8956cb6af0888936ace7f35688cef778861a99a859a65cdef0'
 assert all(x in fixture['argv']for x in['-O3','-DNDEBUG','-std=gnu++17'])
 assert one('/supplemental-regression/run.log')[1]==b'compensated quadrature regression passed\n'
 assert r['initialization_criteria']=={'maximum_iterations':10,'position_tolerance_m':2e-6,'velocity_tolerance_m_s':3e-9}
 failure=None
 if n=='01':
  logs=one('/single-evaluation/propagate.log')[1].decode();clean=re.sub(r'\x1b\[[0-9;]*m','',logs)
  assert r['replay_failure_signature']in clean and r['exact_failure_reproduced']is False
  assert 'relative_residual=1.2851453361637898e-11, tolerance=2e-12, iterations=120' in r['replay_failure_signature']
  assert 'rhs_norm=3747.3316555805213' in r['replay_failure_signature'] and 'solve_role=physical_correction, column=0'in r['replay_failure_signature']
  assert now['no_exported_trajectory'];failure={'original_signature':r['original_failure_signature'],'actual_signature':r['replay_failure_signature']}
 else:
  assert r['initial_state_error_si']==[0.]*6 and now['fixed_state_exact']and now['exported_epoch_support_count']==51840 and now['both_full_closures_unlaunched']
 out.append({'case':'preparation03'if n=='01'else'preparation04','status':status,'plan':{k:one('/control/plan.json')[0][k]for k in ['path','sha256','bytes']},'result':{k:one('/run/replay/result.json')[0][k]for k in ['path','sha256','bytes']},'compact_capture':pin(f'nominal-compensation-single{n}-terminal-capture01.json'),'current_readback':pin(f'nominal-compensation-single{n}-independent-terminal-readback01.json'),'native':r['native'],'initial_state':r['fixed_initial_state_si'],'failure':failure,'fixture_status':fixture['status'],'native_execution':r['execution'],'compact_records_verified':len(items),'current_owned_nonlive':len(now['owned'])})
assert out[0]['initial_state']!=out[1]['initial_state']
v={'schema':'orbit-poc-independent-compensation-native-single-outcomes-v1','passed':True,'observed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'audit_script':pin('audit_nominal_compensation_singles01.py'),'controls_review':pin('nominal-compensation-native-controls-independent-review02.json'),'packet_review':pin('nominal-compensation-four-independent-packet-review01.json'),'build_review':pin('tangent-precision-build02-terminal-independent-review01.json'),'outcomes':out,'findings':['The exact preserved P3 physical input fails at original2e-12 residual guard after120iterations; this is a native regression relative to previously passed wide-affine candidateeb41.','The exact preserved P4 iteration03 input passes one native propagation with unchanged fixed state and all51840epochs; this is not fullclosure.','Analytical supplemental fixture passes in both runs under actual compilerflags; neither changes prescribed suitecounts.','tangentIntegrate is called both by integratedJacobian and integratedForce in stagedVariationalBody.h; compensation can alter floating-point RHS as well as operator. Old captured-system success does not certify this new native system.','Both fullclosure attempts remain unexecuted at current readback. Candidate25661 cannot be treated as resolving correctness or authorizing fresh fullsuite/benchmark release.'],'numerical_fix_verified':False,'candidate_release_approved':False,'fit_attempts':0,'reviewer_native_runs':0}
p=C/'nominal-compensation-singles-independent-terminal-review01.json'
with p.open('x')as f:json.dump(v,f,indent=2,sort_keys=True);f.write('\n')
print(json.dumps(pin(p.name)))
