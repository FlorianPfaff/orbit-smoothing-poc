"""Pure sequence policy tests. Only temporary receipts and mocked controller calls."""
from pathlib import Path
import contextlib,copy,hashlib,importlib.util,json,signal,sys,tempfile,types,unittest
from unittest.mock import patch,Mock
SOURCE=Path(__file__).with_name('sequence.py')
spec=importlib.util.spec_from_file_location('sequence_under_test',SOURCE);seq=importlib.util.module_from_spec(spec);exec(compile(SOURCE.read_bytes(),str(SOURCE),'exec'),seq.__dict__)
def write(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d));return p
class Fixture(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory(prefix='candidate06-sequence-test-');self.addCleanup(self.temp.cleanup);self.t=Path(self.temp.name);self.root=self.t/'sequence';self.root.mkdir();self.go=self.t/'gates';self.go.mkdir();self.co=self.t/'cold';self.co.mkdir();self.stack=contextlib.ExitStack();self.addCleanup(self.stack.close)
  values={'ROOT':self.root,'BASE':self.t,'GATE':self.t/'controls/reference_recovery.py','GATE_RUNNER':self.t/'controls/reference_gates09.py','COLD':self.t/'cold-controls/one_hour_controls.py','CONTRACTS':self.t/'cold-controls/contracts.py','SOURCE':self.t/'candidate/source','SNAPSHOT':self.t/'candidate/source-snapshot.json','GATE_OUT':self.go,'COLD_OUT':self.co}
  for k,v in values.items():self.stack.enter_context(patch.object(seq,k,v))
  for k in ['GATE','GATE_RUNNER','COLD','CONTRACTS']:
   p=values[k];p.parent.mkdir(parents=True,exist_ok=True);p.write_text('# temporary inert control fixture\n')
  write(seq.SNAPSHOT,{'files':[]});py=self.t/'fake-python';py.write_text('pinned interpreter fixture');self.stack.enter_context(patch.object(seq.sys,'executable',str(py)))
  self.jobs=[{'stage':s,'argv':['fixture-native','--stage',s]} for s in seq.STAGES];self.plan_path=write(self.go/'plan.json',{'jobs':self.jobs});self.freeze_path=write(self.go/'freeze.json',{'plan':seq.pin(self.plan_path)})
  self.gate_review=write(self.t/'gate-review.json',{'approved':True});self.cold_review=write(self.t/'cold-review.json',{'approved':True});write(self.co/'freeze.json',{'purpose':'cold fixture'})
  source_review=write(self.t/'source-review.json',{'approved':True,'candidate_source_snapshot_sha256':seq.sha(seq.SNAPSHOT)})
  self.p={'schema':'candidate06-correctness-cold-sequence-v1','boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'gate_stages':list(seq.STAGES),'cold_stages':['cold-pulses','cold-density'],'helper_pins':[]}
  for k,v in {'driver':SOURCE,'gate_controller':seq.GATE,'gate_runner':seq.GATE_RUNNER,'cold_controller':seq.COLD,'cold_contracts':seq.CONTRACTS,'candidate_snapshot':seq.SNAPSHOT,'gate_freeze':self.freeze_path,'cold_freeze':self.co/'freeze.json','source_review':source_review,'gate_review':self.gate_review,'cold_review':self.cold_review,'python':py}.items():self.p[k]=seq.pin(v)
  rows=[]
  for job in self.jobs:
   s=job['stage'];d=self.go/s;d.mkdir();u={'status':'complete','returncode':0,'owned_process_group_cleaned':True,'cleanup':{'verified':True,'empty_tree_certificate':'kernel_ECHILD','remaining':[]}}
   q={'status':'passed','stage':s,'argv':job['argv'],'returncode':0,'evidence':{'tests':106 if s=='native-tests' else 51 if s=='correction-tests' else None}}
   rows.append({'stage':s,'status':'passed','cleanup_verified':True,'input_identity_after':'verified','execution':seq.pin(write(d/'supervisor.json',u)),'strict_result':seq.pin(write(d/'strict-result.json',q))})
  self.r={'all_ten_strict_passed':True,'error':None,'planned_stages':list(seq.STAGES),'stages':rows,'freeze':self.p['gate_freeze'],'plan':seq.pin(self.plan_path)}
  for row in rows:row.update(freeze=self.p['gate_freeze'],plan=seq.pin(self.plan_path))
  write(self.go/'result.json',self.r)
  self.det={'status':'complete','returncode':0,'error':None,'signals_received':[],'freeze_sha256':self.p['gate_freeze']['sha256'],'review_sha256':self.p['gate_review']['sha256']};write(self.go/'detached-result.json',self.det)
  self.cold_result={'status':'passed','planned_stages':['cold-pulses','cold-density'],'stages':[{'stage':s,'status':'passed'} for s in ['cold-pulses','cold-density']]};write(self.co/'result.json',self.cold_result)
  self.path=write(self.root/'plan.json',self.p);self.digest=seq.sha(self.path);self.audit=write(self.t/'sequence-review.json',{'schema':'candidate06-sequence-launch-review-v1','approved':True,'plan_sha256':self.digest,'driver_sha256':self.p['driver']['sha256'],'strict_gates_before_cold':True});self.audit_sha=seq.sha(self.audit)
 def update_plan(self):
  write(self.plan_path,{'jobs':self.jobs});write(self.freeze_path,{'plan':seq.pin(self.plan_path)});self.p['gate_freeze']=seq.pin(self.freeze_path);self.det['freeze_sha256']=self.p['gate_freeze']['sha256'];write(self.go/'detached-result.json',self.det)
  self.r.update(freeze=self.p['gate_freeze'],plan=seq.pin(self.plan_path))
  for row in self.r['stages']:row.update(freeze=self.p['gate_freeze'],plan=seq.pin(self.plan_path))
  write(self.go/'result.json',self.r)
 def row_mutate(self,kind,key,value,index=0):
  row=self.r['stages'][index]
  if kind=='row':row[key]=value
  else:
   p=Path(row[kind]['path']);d=seq.read(p);d[key]=value;write(p,d);row[kind]=seq.pin(p)
  write(self.go/'result.json',self.r)
 def reject_audit(self):
  with self.assertRaises(Exception):seq.gate_audit(self.p)
 def run_case(self,gate_code=0,cold_code=0,gate_effect=None,cold_effect=None,checked_effect=None,review_effect=None):
  gate=types.SimpleNamespace(execute=Mock(side_effect=gate_effect,return_value=gate_code));cold=types.SimpleNamespace(execute=Mock(side_effect=cold_effect,return_value=cold_code))
  with patch.object(seq,'checked',side_effect=checked_effect,return_value=self.p),patch.object(seq,'review_check',side_effect=review_effect),patch.object(seq,'controls',return_value=(gate,cold)):
   code=seq.run(self.path,self.digest,self.audit,self.audit_sha)
  return code,gate,cold,seq.read(self.root/'result.json')
class GateAudit(Fixture):
 def test_all_ten_pass(self):self.assertEqual(len(seq.gate_audit(self.p)['evidence']),10)
 def test_empty_plan_rejected(self):self.jobs=[];self.update_plan();self.reject_audit()
 def test_truncated_plan_rejected(self):self.jobs=self.jobs[:-1];self.update_plan();self.reject_audit()
 def test_extra_plan_job_rejected(self):self.jobs=self.jobs+[self.jobs[-1]];self.update_plan();self.reject_audit()
 def test_reordered_plan_rejected(self):self.jobs[0],self.jobs[1]=self.jobs[1],self.jobs[0];self.update_plan();self.reject_audit()
 def test_empty_result_stages_rejected(self):self.r['stages']=[];write(self.go/'result.json',self.r);self.reject_audit()
 def test_missing_result_stage_rejected(self):self.r['stages'].pop();write(self.go/'result.json',self.r);self.reject_audit()
 def test_reordered_results_rejected(self):self.r['stages'][0],self.r['stages'][1]=self.r['stages'][1],self.r['stages'][0];write(self.go/'result.json',self.r);self.reject_audit()
 def test_wrong_stage_rejected(self):self.row_mutate('row','stage','wrong');self.reject_audit()
 def test_wrong_planned_inventory_rejected(self):self.r['planned_stages']=list(reversed(seq.STAGES));write(self.go/'result.json',self.r);self.reject_audit()
 def test_aggregate_false_rejected(self):self.r['all_ten_strict_passed']=False;write(self.go/'result.json',self.r);self.reject_audit()
 def test_gate_failed_rejected(self):self.row_mutate('row','status','failed');self.reject_audit()
 def test_changed_input_identity_rejected(self):self.row_mutate('row','input_identity_after','changed');self.reject_audit()
 def test_missing_cleanup_certificate_rejected(self):self.row_mutate('execution','cleanup',{'verified':True,'remaining':[]});self.reject_audit()
 def test_nonempty_owned_tree_rejected(self):self.row_mutate('execution','cleanup',{'verified':True,'empty_tree_certificate':'kernel_ECHILD','remaining':[123]});self.reject_audit()
 def test_unverified_cleanup_rejected(self):self.row_mutate('execution','owned_process_group_cleaned',False);self.reject_audit()
 def test_supervisor_failure_rejected(self):self.row_mutate('execution','status','failed');self.reject_audit()
 def test_nonzero_supervisor_exit_rejected(self):self.row_mutate('execution','returncode',1);self.reject_audit()
 def test_changed_strict_argv_rejected(self):self.row_mutate('strict_result','argv',['wrong']);self.reject_audit()
 def test_changed_strict_stage_rejected(self):self.row_mutate('strict_result','stage','wrong');self.reject_audit()
 def test_nonzero_strict_exit_rejected(self):self.row_mutate('strict_result','returncode',1);self.reject_audit()
 def test_native_count_rejected(self):self.row_mutate('strict_result','evidence',{'tests':105});self.reject_audit()
 def test_correction_count_rejected(self):self.row_mutate('strict_result','evidence',{'tests':50},1);self.reject_audit()
 def test_changed_strict_hash_rejected(self):Path(self.r['stages'][0]['strict_result']['path']).write_text('{}');self.reject_audit()
 def test_changed_plan_hash_rejected(self):self.plan_path.write_text('{}');self.reject_audit()
 def test_wrong_freeze_attribution_rejected(self):self.det['freeze_sha256']='0'*64;write(self.go/'detached-result.json',self.det);self.reject_audit()
 def test_wrong_review_attribution_rejected(self):self.det['review_sha256']='0'*64;write(self.go/'detached-result.json',self.det);self.reject_audit()
 def test_interrupted_gate_rejected(self):self.det['status']='interrupted';write(self.go/'detached-result.json',self.det);self.reject_audit()
 def test_received_signal_rejected(self):self.det['signals_received']=[15];write(self.go/'detached-result.json',self.det);self.reject_audit()
 def test_missing_gate_receipt_rejected(self):(self.go/'detached-result.json').unlink();self.reject_audit()
 def test_aggregate_plan_attribution_rejected(self):self.r['plan']={**self.r['plan'],'sha256':'0'*64};write(self.go/'result.json',self.r);self.reject_audit()
 def test_aggregate_freeze_attribution_rejected(self):self.r['freeze']={**self.r['freeze'],'sha256':'0'*64};write(self.go/'result.json',self.r);self.reject_audit()
 def test_missing_aggregate_plan_rejected(self):del self.r['plan'];write(self.go/'result.json',self.r);self.reject_audit()
 def test_missing_aggregate_freeze_rejected(self):del self.r['freeze'];write(self.go/'result.json',self.r);self.reject_audit()
 def test_row_plan_attribution_rejected(self):self.row_mutate('row','plan',{**self.r['plan'],'sha256':'0'*64});self.reject_audit()
 def test_row_freeze_attribution_rejected(self):self.row_mutate('row','freeze',{**self.r['freeze'],'sha256':'0'*64});self.reject_audit()
 def test_missing_row_plan_rejected(self):del self.r['stages'][0]['plan'];write(self.go/'result.json',self.r);self.reject_audit()
 def test_missing_row_freeze_rejected(self):del self.r['stages'][0]['freeze'];write(self.go/'result.json',self.r);self.reject_audit()
 def test_wrong_attribution_path_same_hash_rejected(self):self.row_mutate('row','plan',{**self.r['plan'],'path':str(self.t/'wrong-plan.json')});self.reject_audit()
class Identity(Fixture):
 def test_checked_fixture_passes(self):self.assertEqual(seq.checked(self.path,self.digest),self.p)
 def test_changed_review_rejected(self):self.gate_review.write_text('{}');self.assertRaises(ValueError,seq.checked,self.path,self.digest)
 def test_changed_driver_rejected(self):self.p['driver']['sha256']='0'*64;write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
 def test_changed_stage_order_rejected(self):self.p['gate_stages'].reverse();write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
 def test_prior_boot_rejected(self):self.p['boot_id']='previous-boot';write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
 def test_wrong_source_review_rejected(self):d=seq.read(self.p['source_review']['path']);d['candidate_source_snapshot_sha256']='0'*64;write(Path(self.p['source_review']['path']),d);self.p['source_review']=seq.pin(self.p['source_review']['path']);write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
 def test_changed_sequence_review_rejected(self):self.audit.write_text('{}');self.assertRaises(ValueError,seq.review_check,self.p,self.digest,self.audit,self.audit_sha)
 def test_wrong_sequence_driver_review_rejected(self):d=seq.read(self.audit);d['driver_sha256']='0'*64;write(self.audit,d);self.assertRaises(ValueError,seq.review_check,self.p,self.digest,self.audit,seq.sha(self.audit))
 def test_truthy_source_approval_rejected(self):
  d=seq.read(self.p['source_review']['path']);d['approved']='yes';write(Path(self.p['source_review']['path']),d);self.p['source_review']=seq.pin(self.p['source_review']['path']);write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
 def test_integer_source_approval_rejected(self):
  d=seq.read(self.p['source_review']['path']);d['approved']=1;write(Path(self.p['source_review']['path']),d);self.p['source_review']=seq.pin(self.p['source_review']['path']);write(self.path,self.p);self.assertRaises(ValueError,seq.checked,self.path,seq.sha(self.path))
class SerialRun(Fixture):
 def test_only_strict_pass_allows_cold(self):
  code,g,c,r=self.run_case();self.assertEqual(code,0);g.execute.assert_called_once();c.execute.assert_called_once();self.assertEqual(r['status'],'complete');self.assertEqual(r['phase'],'finished');self.assertTrue((self.root/'correctness-terminal-audit.json').exists())
 def test_gate_nonzero_prevents_cold(self):
  code,g,c,r=self.run_case(gate_code=1);self.assertEqual(code,1);c.execute.assert_not_called();self.assertEqual(r['phase'],'correctness')
 def test_gate_exception_prevents_cold(self):
  code,g,c,r=self.run_case(gate_effect=RuntimeError('measured gate failure'));self.assertEqual(code,1);c.execute.assert_not_called();self.assertIn('measured gate failure',r['error'])
 def test_gate_receipt_failure_prevents_cold(self):
  self.row_mutate('row','status','failed');code,g,c,r=self.run_case();self.assertEqual(code,1);c.execute.assert_not_called();self.assertEqual(r['phase'],'correctness')
 def test_startup_identity_failure_prevents_all(self):
  code,g,c,r=self.run_case(checked_effect=ValueError('identity changed'));self.assertEqual(code,1);g.execute.assert_not_called();c.execute.assert_not_called();self.assertEqual(r['phase'],'startup')
 def test_startup_review_failure_prevents_all(self):
  code,g,c,r=self.run_case(review_effect=ValueError('review changed'));self.assertEqual(code,1);g.execute.assert_not_called();c.execute.assert_not_called();self.assertEqual(r['phase'],'startup')
 def test_post_gate_identity_failure_prevents_cold(self):
  code,g,c,r=self.run_case(checked_effect=[self.p,ValueError('identity changed after gate')]);self.assertEqual(code,1);g.execute.assert_called_once();c.execute.assert_not_called()
 def test_failed_cold_retained(self):
  self.cold_result['status']='failed';self.cold_result['stages'][1]['status']='failed';write(self.co/'result.json',self.cold_result);before=(self.co/'result.json').read_bytes();code,g,c,r=self.run_case(cold_code=1);self.assertEqual(code,1);self.assertEqual(r['phase'],'cold_fits');self.assertEqual((self.co/'result.json').read_bytes(),before)
 def test_failed_cold_row_cannot_pass_aggregate(self):
  self.cold_result['stages'][1]['status']='failed';write(self.co/'result.json',self.cold_result);code,g,c,r=self.run_case();self.assertEqual(code,1);self.assertEqual(r['status'],'failed')
 def test_missing_cold_stage_fails(self):
  self.cold_result['stages'].pop();write(self.co/'result.json',self.cold_result);code,g,c,r=self.run_case();self.assertEqual(code,1);self.assertEqual(r['phase'],'cold_fits')
 def test_cold_exception_preserved(self):
  code,g,c,r=self.run_case(cold_effect=RuntimeError('cold execution failed'));self.assertEqual(code,1);self.assertIn('cold execution failed',r['error'])
 def test_direct_signal_attributed_and_handlers_restored(self):
  old=signal.getsignal(signal.SIGTERM)
  def interrupted(*_):signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
  code,g,c,r=self.run_case(gate_effect=interrupted);self.assertEqual(code,1);self.assertEqual(r['status'],'interrupted');self.assertEqual(r['signals_received'],[signal.SIGTERM]);self.assertIs(signal.getsignal(signal.SIGTERM),old);c.execute.assert_not_called()
 def test_phase_interruption_attributed(self):
  self.det['status']='interrupted';write(self.go/'detached-result.json',self.det);code,g,c,r=self.run_case(gate_code=1);self.assertEqual(r['status'],'interrupted');c.execute.assert_not_called()
 def test_malformed_phase_receipt_still_records_failure(self):
  (self.go/'detached-result.json').write_text('{bad');code,g,c,r=self.run_case(gate_code=1);self.assertEqual(code,1);self.assertEqual(r['status'],'failed');c.execute.assert_not_called()
if __name__=='__main__':unittest.main()
