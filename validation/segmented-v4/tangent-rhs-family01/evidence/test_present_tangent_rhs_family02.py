"""Pure reporting fixtures: no reader, solver, propagation or network call."""
import copy, hashlib, importlib.util, json, tempfile, unittest
from pathlib import Path
S=Path(__file__).with_name('present_tangent_rhs_family02.py')
spec=importlib.util.spec_from_file_location('present_rhs',S);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

def encode(v):return(json.dumps(v,allow_nan=False)+'\n').encode()
def family():
 cases=[];anchors=[]
 for anchor,h in m.ANCHORS.items():
  anchors.append(dict(id=anchor,path='/external/'+anchor,sha256=h,epochs=2,dt=5.,duration=5.))
  variants=[(None,0,0.)]+[(d,s,z)for d in('smooth','alternating')for z in(1e-12,1e-9)for s in(-1,1)]
  for i,(d,s,z)in enumerate(variants):
   identity=anchor+('-original'if i==0 else'-variant'+str(i));cases.append(dict(id=identity,anchor=anchor,path='/external/'+identity,sha256=h if i==0 else str(i)*64,bytes=120,direction=d,sign=s,relative_scale=z,actual_relative_balanced_norm=z))
 order=[]
 for i,c in enumerate(cases):
  for p in(('baseline','wide')if i%2==0 else('wide','baseline')):order.append(dict(attempt_id=f'{len(order)+1:02d}-{c["id"]}-{p}',case_id=c['id'],profile=p))
 return dict(schema_version=1,kind='bounded-captured-tangent-rhs-sensitivity',case_count=27,attempt_count=54,acceptance=dict(relative_residual=2e-12,maximum_iterations=120,restart=20),anchors=anchors,cases=cases,execution_order=order)
BINARY=dict(path='/external/reader',sha256='a'*64)
def record(f,number,success=True):
 item=f['execution_order'][number];case=next(c for c in f['cases']if c['id']==item['case_id']);profile=item['profile']
 first=dict(kind='input',profile=profile,epochs=2,dt=5.,duration=5.,tolerance=2e-12,maximum_iterations=120,restart=20,extended_digits=64)
 last=dict(kind='terminal',status='passed'if success else'failed',kernel_status='passed'if success else'failed',iterations=5 if success else 120,relative_residual=1e-12 if success else 5e-12,physical_double_quad_relative_residual=1.1e-12 if success else 5.1e-12)
 rows=[first]
 if success:rows.append(dict(kind='physical_double_quad_residual',selection='returned',iteration=5,binary_digits=113,relative_residual=1.1e-12))
 rows.append(last);data=b''.join(encode(x)for x in rows);path='/remote/attempts/'+item['attempt_id']+'/trace.jsonl';trace=dict(path=path,sha256=m.sha(data))
 r=dict(item,capture=dict(path=case['path'],sha256=case['sha256']),binary=BINARY,argv=[BINARY['path'],profile,case['path']],status='reader_certified'if success else'numerical_failure',returncode=0 if success else 1,input=first,terminal=last,record_count=len(rows),trace=trace,stderr=dict(path=path+'.stderr',sha256=m.sha(b'')),elapsed_seconds=.3,fit_attempts=0)
 originals={path:(dict(trace,bytes=len(data)),data),path+'.stderr':(dict(r['stderr'],bytes=0),b'')}
 return r,originals

def result(f,records,status='running'):
 return dict(phase='run',fit_attempts=0,groops_propagations=0,release_evidence=False,planned_attempts=f['execution_order'],binary=BINARY,attempts=records,status=status)

class Reporting(unittest.TestCase):
 def setUp(self):self.f=family()
 def check(self,rs,status='running',originals=None):return m.summarize(self.f,result(self.f,rs,status),originals or{},BINARY)
 def test_all54_missing_remain(self):
  s=self.check([]);self.assertEqual(len(s['attempts']),54);self.assertEqual(s['status_counts'],{'missing_not_recorded':54});self.assertFalse(s['release_ready'])
 def test_failure_and_missing(self):
  r,o=record(self.f,0,False);s=self.check([r],originals=o);self.assertEqual(s['status_counts'],{'numerical_failure':1,'missing_not_recorded':53})
 def test_success_certifies_actual_returned_state(self):
  r,o=record(self.f,0);s=self.check([r],originals=o);self.assertTrue(s['attempts'][0]['accepted'])
 def test_all54_complete_includes_failure(self):
  rs=[];originals={}
  for i in range(54):r,o=record(self.f,i,i%3!=0);rs.append(r);originals.update(o)
  s=self.check(rs,'completed_all_planned_calls',originals);self.assertEqual(s['status_counts'],{'numerical_failure':18,'reader_certified':36})
 def test_completion_cannot_hide_missing(self):
  with self.assertRaises(ValueError):self.check([],'completed_all_planned_calls')
 def test_repeated_call_rejected(self):
  r,o=record(self.f,0)
  with self.assertRaises(ValueError):self.check([r,r],originals=o)
 def test_reordered_call_rejected(self):
  r,o=record(self.f,1)
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_unknown_method_rejected(self):
  self.f['execution_order'][0]['profile']='external_hidden'
  with self.assertRaises(ValueError):self.check([])
 def test_order_change_rejected(self):
  self.f['execution_order'][0],self.f['execution_order'][1]=self.f['execution_order'][1],self.f['execution_order'][0]
  with self.assertRaises(ValueError):self.check([])
 def test_missing_case_rejected(self):
  self.f['cases'].pop()
  with self.assertRaises(ValueError):self.check([])
 def test_changed_anchor_rejected(self):
  self.f['anchors'][0]['sha256']='0'*64
  with self.assertRaises(ValueError):self.check([])
 def test_changed_limit_rejected(self):
  self.f['acceptance']['relative_residual']=3e-12
  with self.assertRaises(ValueError):self.check([])
 def test_bad_binary_rejected(self):
  r,o=record(self.f,0);r['binary']=dict(BINARY,sha256='0'*64)
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_bad_capture_rejected(self):
  r,o=record(self.f,0);r['capture']['sha256']='0'*64
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_bad_profile_rejected(self):
  r,o=record(self.f,0);r['profile']='wide'
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_trace_tamper_rejected(self):
  r,o=record(self.f,0);r['trace']['sha256']='0'*64
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_result_trace_disagreement_rejected(self):
  r,o=record(self.f,0);r['terminal']['iterations']=6
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_pass_without113certificate_rejected(self):
  r,o=record(self.f,0);key=r['trace']['path'];rows=[json.loads(x)for x in o[key][1].splitlines()];rows.pop(1);data=b''.join(encode(x)for x in rows);r['trace']['sha256']=m.sha(data);r['record_count']=2;o[key]=(dict(r['trace'],bytes=len(data)),data)
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_certificate_different_state_rejected(self):
  r,o=record(self.f,0);key=r['trace']['path'];rows=[json.loads(x)for x in o[key][1].splitlines()];rows[1]['selection']='best_observed';data=b''.join(encode(x)for x in rows);r['trace']['sha256']=m.sha(data);o[key]=(dict(r['trace'],bytes=len(data)),data)
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_quad_just_above_binary64_threshold_rejected(self):
  r,o=record(self.f,0);key=r['trace']['path'];data=o[key][1].replace(b'1.1e-12',b'2.00000000000000001e-12');r['trace']['sha256']=m.sha(data);o[key]=(dict(r['trace'],bytes=len(data)),data);r['terminal']['physical_double_quad_relative_residual']=2e-12
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_timeout_is_retained(self):
  r,o=record(self.f,0);r.update(status='timeout',returncode=None);r.pop('terminal');r.pop('input');r.pop('record_count');s=self.check([r],originals=o);self.assertEqual(s['attempts'][0]['status'],'timeout')
 def test_control_failure_before_call_retained(self):
  r=dict(self.f['execution_order'][0],status='not_started_control_failure',error='fixture');s=self.check([r]);self.assertEqual(s['recorded_calls'],1);self.assertFalse(s['attempts'][0]['accepted'])
 def test_running_is_incomplete_not_success(self):
  r,o=record(self.f,0);r['status']='running';s=self.check([r],originals=o);self.assertEqual(s['attempts'][0]['status'],'incomplete_record');self.assertFalse(s['attempts'][0]['accepted'])
 def test_nan_trace_rejected(self):
  with self.assertRaises(ValueError):m.loads('{"residual": NaN}')
 def test_raw_CRLF_preserved(self):
  import base64
  b=b'first\r\nsecond\r\n';r=dict(path='/remote/stdout',sha256=m.sha(b),bytes=len(b),base64=base64.b64encode(b).decode());self.assertEqual(m.raw_records({'files':[r]})[r['path']][1],b)
 def test_raw_duplicate_rejected(self):
  r=dict(path='/remote/stdout',sha256=m.sha(b''),bytes=0,base64='')
  with self.assertRaises(ValueError):m.raw_records({'files':[r,r]})
 def test_raw_wrong_hash_rejected(self):
  with self.assertRaises(ValueError):m.raw_records({'files':[dict(path='/remote/stdout',sha256='0'*64,bytes=0,base64='')]})
 def test_empty_records_distinct_path(self):
  r=dict(path='/remote/stdout',sha256=m.sha(b''),bytes=0,base64='');rr=dict(r,path='/remote/stderr');self.assertEqual(len(m.raw_records({'files':[r,rr]})),2)
 def test_unknown_status_rejected(self):
  r,o=record(self.f,0);r['status']='probably_passed'
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_negative_time_rejected(self):
  r,o=record(self.f,0);r['elapsed_seconds']=-1
  with self.assertRaises(ValueError):self.check([r],originals=o)
 def test_scope_cannot_claim_fits(self):
  v=result(self.f,[]);v['fit_attempts']=1
  with self.assertRaises(ValueError):m.summarize(self.f,v,{},BINARY)
 def test_baseline_changes_reported(self):
  rs=[];orig={}
  for i in range(54):r,o=record(self.f,i);rs.append(r);orig.update(o)
  summary=self.check(rs,'completed_all_planned_calls',orig);mapping={'before_planned_family_calls':True,'rows':[]};traces={}
  for anchor in m.ANCHORS:
   ref=dict(path='/local/'+anchor,sha256='0'*64);mapping['rows'].append(dict(anchor=anchor,new_profile='baseline',new_case_id=anchor+'-original',prior_trace=ref));traces[ref['path']]=encode(dict(kind='terminal',status='passed',iterations=46,relative_residual=1.2e-12))
  rows=m.baseline_comparison(summary,mapping,lambda ref:traces[ref['path']]);self.assertTrue(all(r['changed_status_iterations_or_kernel_residual']for r in rows))
 def test_missing_baseline_unknown_not_equal(self):
  summary=self.check([]);mapping={'before_planned_family_calls':True,'rows':[dict(anchor=a,new_profile='baseline',new_case_id=a+'-original',prior_trace=dict(path='/local/'+a,sha256='0'*64))for a in m.ANCHORS]};rows=m.baseline_comparison(summary,mapping,lambda ref:encode(dict(kind='terminal',status='passed',iterations=5,relative_residual=1e-12)));self.assertTrue(all(r['changed_status_iterations_or_kernel_residual']is None for r in rows))
 def test_html_lists54_rows_and_zero_benchmark(self):
  h=m.render(self.check([])).decode();self.assertEqual(h.count('<tr>'),55);self.assertIn('0/68',h);self.assertIn('missing_not_recorded',h)
 def test_path_symlink_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   p=Path(tmp)/'a';p.write_bytes(b'hello');q=Path(tmp)/'alias';q.symlink_to(p)
   with self.assertRaises(ValueError):m.exact_file(m.pin(q))
 def test_pin_changed_bytes_rejected(self):
  with tempfile.TemporaryDirectory()as tmp:
   p=Path(tmp)/'a';p.write_bytes(b'hello');r=m.pin(p);p.write_bytes(b'changed')
   with self.assertRaises(ValueError):m.exact_file(r)

if __name__=='__main__':unittest.main()
