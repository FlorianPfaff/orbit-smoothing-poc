import copy, importlib.util, json, os, tempfile, unittest, sys
sys.dont_write_bytecode=True
from pathlib import Path
from unittest.mock import patch
import contracts as c
import one_hour_controls as runner

class Contracts(unittest.TestCase):
 def test_two_originals_are_exact_and_rebinding_is_only_runtime(self):
  for stage in c.CASES:
   raw=Path(c.REQUESTS[stage]['path']).read_bytes();old=c.original_request(stage,raw);new,journal=c.rebind(stage,raw,'a'*64)
   self.assertTrue(c.verify_rebinding(stage,raw,new,journal,'a'*64))
   self.assertEqual({tuple(e['path']) for e in journal},{('backend','groops_executable'),('expected_native_binary_sha256',),('source_hash',)})
   self.assertEqual(new['estimation_inputs'],old['estimation_inputs']);self.assertEqual(new['parameters'],old['parameters']);self.assertEqual(new['numerical_controls'],old['numerical_controls'])
 def test_unknown_case_rejected(self):
  with self.assertRaises(ValueError):c.original_request('warm-pulses',b'{}')
 def test_wrong_original_bytes_rejected(self):
  for stage in c.CASES:
   with self.assertRaises(ValueError):c.original_request(stage,Path(c.REQUESTS[stage]['path']).read_bytes()+b' ')
 def test_no_statistical_field_rebinding(self):
  raw=Path(c.REQUESTS['cold-density']['path']).read_bytes();new,j=c.rebind('cold-density',raw,'a'*64);new['parameters']['tau_seconds']=1800
  with self.assertRaises(ValueError):c.verify_rebinding('cold-density',raw,new,j,'a'*64)
 def test_no_initial_override_or_nuisance_donor(self):
  raw=Path(c.REQUESTS['cold-pulses']['path']).read_bytes()
  for key in ['initial_state_from','nuisance_donor','warm_start','truth']:
   with self.subTest(key=key):
    new,j=c.rebind('cold-pulses',raw,'a'*64);new[key]='saved'
    with self.assertRaises(ValueError):c.verify_rebinding('cold-pulses',raw,new,j,'a'*64)
 def test_exact_onehour_density_params(self):self.assertEqual(c.PARAMETERS['cold-density']['tau_seconds'],7200.);self.assertEqual(c.PARAMETERS['cold-density']['sigma_log_density'],.3)
 def test_unchanged_numerical_limits(self):
  self.assertEqual(c.LIMITS['timeout_seconds'],7200);self.assertEqual(c.LIMITS['process_tree_rss_bytes'],8*1024**3);self.assertEqual(c.LIMITS['min_free_disk_bytes'],32*1024**3);self.assertEqual(c.LIMITS['minimum_available_memory_bytes'],16*1024**3);self.assertEqual(c.CONTROLS['maximum_accepted_iterations'],32);self.assertEqual(c.CONTROLS['maximum_trial_evaluations'],96)
 def test_save_never_overwrites(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   p=Path(tmp)/'x.json';c.save(p,{'original':True})
   with self.assertRaises(FileExistsError):c.save(p,{'original':False})
   self.assertEqual(c.read(p),{'original':True})
 def make_stage(self,tmp):
  p=Path(tmp)/'stage';p.mkdir()
  for leaf in ['tmp','scratch','row-spool','legacy-output']:(p/leaf).mkdir()
  for leaf in ['request.json','rebinding.json']:(p/leaf).write_text('{}')
  return p
 def test_fresh_stage_accepts_empty_leaves(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:self.assertTrue(c.fresh_stage(self.make_stage(tmp)))
 def test_used_stage_rejected_and_left_untouched(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   p=self.make_stage(tmp);(p/'strict-result.json').write_text('failure')
   with self.assertRaises(ValueError):c.fresh_stage(p)
   self.assertEqual((p/'strict-result.json').read_text(),'failure')
 def test_foreign_symlink_leaf_rejected(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   p=self.make_stage(tmp);(p/'tmp').rmdir();other=Path(tmp)/'other';other.mkdir();(p/'tmp').symlink_to(other)
   with self.assertRaises(ValueError):c.fresh_stage(p)
 def test_used_scratch_rejected(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   p=self.make_stage(tmp);(p/'scratch/x').write_text('preserved')
   with self.assertRaises(ValueError):c.fresh_stage(p)
   self.assertTrue((p/'scratch/x').exists())
 def supervisor(self,status='complete',returncode=0):return {'status':status,'returncode':returncode,'owned_process_group_cleaned':True,'cleanup':{'verified':True,'empty_tree_certificate':'kernel_ECHILD','remaining':[]}}
 def test_strict_pass_is_necessary(self):
  for worker in [None,{}, {'status':'passed','whole_fit_verified':False,'accepted_covariance':True},{'status':'passed','whole_fit_verified':True,'accepted_covariance':False}]:
   with self.subTest(worker=worker):self.assertEqual(c.terminal_classification(self.supervisor(),worker,True)['status'],'failed')
 def test_complete_process_is_not_fit_success(self):self.assertEqual(c.terminal_classification(self.supervisor(),{'status':'failed'},True)['status'],'failed')
 def test_success_needs_all_authorities(self):self.assertEqual(c.terminal_classification(self.supervisor(),{'status':'passed','whole_fit_verified':True,'accepted_covariance':True},True)['status'],'passed')
 def test_timeout_remains_timeout(self):self.assertEqual(c.terminal_classification(self.supervisor('timeout'),None,True)['status'],'timeout')
 def test_interruption_blocks_next_fit(self):self.assertFalse(c.terminal_classification(self.supervisor('interrupted'),None,True)['continue'])
 def test_identity_failure_blocks_next_fit(self):self.assertFalse(c.terminal_classification(self.supervisor(),None,False)['continue'])
 def test_missing_cleanup_blocks_next_fit(self):
  s=self.supervisor();s['cleanup']['verified']=False;self.assertFalse(c.terminal_classification(s,None,True)['continue'])
 def test_worker_exit_nonzero_cannot_pass(self):self.assertEqual(c.terminal_classification(self.supervisor(returncode=1),{'status':'passed','whole_fit_verified':True,'accepted_covariance':True},True)['status'],'failed')
 def test_inner_timeout_retained_after_worker_nonzero(self):
  outcome={'status':'timeout','numerical_status':'timeout','error':'Per-fit wall time exhausted'}
  d=c.terminal_classification(self.supervisor(returncode=1),{'status':'failed','backend_outcome':outcome},True)
  self.assertEqual(d['status'],'timeout');self.assertEqual(d['backend_outcome'],outcome)
 def test_modified_or_missing_helper_rejected_before_exec(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   p=Path(tmp)/'helper.py';p.write_text('raise RuntimeError("MUST NOT EXECUTE")');digest=c.sha(p);p.write_text('raise RuntimeError("CHANGED")')
   with self.assertRaises(ValueError):runner.load(p,digest,'bad_helper_test')
   p.unlink()
   with self.assertRaises(ValueError):runner.load(p,digest,'missing_helper_test')
 def good_strict(self):
  result={'status':'complete','converged':True,'covariance_valid':True,'native_binary_sha256':c.NATIVE_SHA}
  profile={'nuisance_converged':True,'nuisance_floor_limited':False,'threshold_m':1e-8,'required_consecutive_small_updates':2,'fresh_full_nuisance_confirmed':True,'fresh_full_nuisance_update_m':1e-10,'history':[{'maximum_update_m':1e-10},{'maximum_update_m':1e-10}]}
  confirmation={'stationary':True,'raw_correction':{'position_change_m':1e-6,'density_update':1e-6,'pulse_update_m_s':1e-10},'normalized_gradient':1e-10};return result,profile,confirmation
 def test_strict_completed_summary(self):self.assertTrue(c.strict_summary(*self.good_strict()))
 def test_floor_limited_final_cannot_pass(self):
  r,p,z=self.good_strict();p['nuisance_floor_limited']=True
  with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_stale_covariance_cannot_pass(self):
  for field in ['converged','covariance_valid']:
   r,p,z=self.good_strict();r[field]=False
   with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_strict_equality_boundary_fails(self):
  for key,value in [('position_change_m',3e-5),('density_update',1e-4),('pulse_update_m_s',1e-8)]:
   r,p,z=self.good_strict();z['raw_correction'][key]=value
   with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_strict_gradient_boundary_fails(self):
  r,p,z=self.good_strict();z['normalized_gradient']=1e-8
  with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_nuisance_threshold_cannot_be_relaxed(self):
  r,p,z=self.good_strict();p['threshold_m']=1e-7
  with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_two_consecutive_updates_required(self):
  r,p,z=self.good_strict();p['history'][0]['maximum_update_m']=1e-7
  with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_fresh_full_confirmation_required(self):
  r,p,z=self.good_strict();p['fresh_full_nuisance_confirmed']=False
  with self.assertRaises(ValueError):c.strict_summary(r,p,z)
 def test_no_extra_objective_resolvability_gate(self):
  r,p,z=self.good_strict();p['objective_reduction_numerically_resolved']=False;self.assertTrue(c.strict_summary(r,p,z))
 def test_unknown_ambient_flags_rejected(self):
  expected=runner.environment(c.BASE/'candidate06-cold01/cold-pulses')
  for key in ['ORBIT_POC_NUISANCE_WARM_START','LD_PRELOAD','PYTHONHOME']:
   actual={**expected,key:'bad'}
   with self.assertRaises(ValueError):runner.validate_environment(expected,actual)
 def test_environment_does_not_inherit_ambient_values(self):
  with patch.dict(os.environ,{'ORBIT_POC_NUISANCE_WARM_START':'bad','LD_PRELOAD':'bad'}):
   env=runner.environment(c.BASE/'candidate06-cold01/cold-pulses');self.assertNotIn('LD_PRELOAD',env);self.assertNotIn('ORBIT_POC_NUISANCE_WARM_START',env)
 def test_review_must_bind_exact_freeze(self):
  a={'schema':'orbit-poc-one-hour-launch-review-v1','approved':True,'freeze_sha256':'a'*64,'runner_sha256':c.sha(runner.__file__),'two_original_cold_fullfits':True,'thresholds_unchanged':True,'namespace_preflight_passed':True}
  runner.audit_authority(a,'a'*64,{})
  with self.assertRaises(ValueError):runner.audit_authority(a,'b'*64,{})
  a['approved']=False
  with self.assertRaises(ValueError):runner.audit_authority(a,'a'*64,{})
 def test_prepare_rejects_existing_output_before_native(self):
  with tempfile.TemporaryDirectory(dir=c.BASE) as d:
   with self.assertRaises(ValueError):runner.prepare(Path(d),Path('/home/emper/not-created-test'))
 def test_namespace_never_binds_host_root_or_whole_archives(self):
  output=c.BASE/'candidate06-cold01';stage='cold-pulses';root=output/stage
  p={'output':str(output),'scratch_root':'/home/emper/orbit-candidate06-cold01','directory_bindings':[{'host':str(c.SOURCE/'src'),'target':str(c.SOURCE/'src')}],'bindings':[{'host':str(runner.GATES),'target':str(runner.GATES)}],'originals':{},'jobs':[{'stage':stage,'request':{'path':str(root/'request.json')},'rebinding':{'path':str(root/'rebinding.json')}}],'prepared':{'output_dir':'/mnt/c/inputs/prepared'}}
  argv=runner.namespace(p,stage,['python','worker']);self.assertIn('--clearenv',argv);self.assertIn('--unshare-all',argv)
  for i,x in enumerate(argv):
   if x in ['--ro-bind','--bind']:self.assertNotIn(argv[i+1],['/','/mnt','/home',str(c.BASE)])
  self.assertIn(str(root/'fit/row-spool'),argv)
 def test_assessment_source_checks_actual_fresh_factor(self):
  # Guard against accidentally replacing the independently reviewed final path with prior optimizer confirmation.
  import inspect
  text=inspect.getsource(runner.assessment)
  self.assertIn("'-final-covariance'",text);self.assertIn('proposal-000/proposal-retention.json',text);self.assertIn('optimizer.certify_rank(point)',text);self.assertIn('optimizer.proposal(point)',text);self.assertIn('backend.require_full_native_factor(coords,diag)',text)

if __name__=='__main__':unittest.main(verbosity=2)
