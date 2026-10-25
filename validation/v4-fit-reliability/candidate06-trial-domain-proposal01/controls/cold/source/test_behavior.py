"""Tiny artifact tests of the actual final assessment; no subprocess/native fit."""
import json, os, struct, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.dont_write_bytecode=True
import numpy as np
import contracts as c
import one_hour_controls as runner
sys.path.insert(0,str(c.SOURCE/'src'))

class Behavioral(unittest.TestCase):
 def test_exact_file_changed_or_missing_fails(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   f=Path(tmp)/'file';f.write_text('original');rows=[{'host':str(f),'target':str(f),'bytes':f.stat().st_size,'sha256':c.sha(f)}];runner.verify_files(rows)
   f.write_text('modified')
   with self.assertRaises(ValueError):runner.verify_files(rows)
   f.unlink()
   with self.assertRaises(ValueError):runner.verify_files(rows)
 def test_added_import_shadow_and_symlink_fail(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);(root/'file.py').write_text('original');g,_=runner.helpers();inventory=g.runtime_api().tree(root)
   plan={'directory_bindings':[{'host':str(root),'target':str(root),'inventory':inventory}]};runner.verify_directory_membership(plan)
   (root/'shadow.py').write_text('new code')
   with self.assertRaises(ValueError):runner.verify_directory_membership(plan)
   (root/'shadow.py').unlink();(root/'link.py').symlink_to(root/'file.py')
   with self.assertRaises(ValueError):runner.verify_directory_membership(plan)
 def test_changed_existing_runtime_member_fails(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);(root/'file.py').write_text('original');g,_=runner.helpers();inventory=g.runtime_api().tree(root);(root/'file.py').write_text('change')
   with self.assertRaises(ValueError):runner.verify_directory_membership({'directory_bindings':[{'host':str(root),'target':str(root),'inventory':inventory}]})
 def test_backing_not_placeholder_emptiness_is_checked(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp)
   for leaf in ['tmp','scratch','row-spool','legacy-output']:(root/leaf).mkdir()
   self.assertTrue(c.fresh_backing(root));(root/'scratch/stale').write_text('preserve')
   with self.assertRaises(ValueError):c.fresh_backing(root)
   self.assertTrue((root/'scratch/stale').exists())
 def test_replaced_directory_identity_fails(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp)/'owned';root.mkdir();identity=c.directory_identity(root);root.rename(Path(tmp)/'old');root.mkdir()
   with self.assertRaises(ValueError):c.verify_directory_identity(identity)
 def fixture(self,root,*,stale=False,conditional=False,damped=False,bad_gradient=False):
  fit=root/'fit';fit.mkdir();folder=fit/'point-005-final-covariance';folder.mkdir();proposal=folder/'proposal-000';proposal.mkdir()
  def write(name,d):p=folder/name;p.write_text(json.dumps(d));return p
  profile={'nuisance_converged':True,'nuisance_floor_limited':False,'threshold_m':1e-8,'required_consecutive_small_updates':2,'fresh_full_nuisance_confirmed':True,'fresh_full_nuisance_update_m':1e-10,'history':[{'maximum_update_m':1e-10},{'maximum_update_m':1e-10}]}
  profilefile=write('qr.profile.json',profile)
  coords={'schema':'orbit-poc-qr-factor-v1','columns':2,'rows':2,'orthogonal_energy':0.,'scales':[1.,1.],'dynamic':[True,True],'local_global_indices':[],'retained_global_indices':[0,1],'full_rank_certificate':not conditional,'covariance_authority':not conditional}
  coordfile=write('qr.4.factor.json',coords);diagfile=write('qr.4.diagnostics.json',{'schema':'orbit-poc-native-qr-v1','rank_status':'full','rank':2,'retained_parameters':2,'reduced_rows':10,'lambda':1e-3 if damped else 0.});costfile=write('qr.4.profile.json',{'direct_cost':1.})
  factor=folder/'qr.4.R.bin';factor.write_bytes(struct.pack('<QQ',2,2)+np.eye(2).astype('<f8').tobytes());rhs=folder/'qr.4.rhs.bin';rhs.write_bytes(struct.pack('<QQ',2,1)+np.full((2,1),1. if bad_gradient else 1e-12,dtype='<f8').tobytes())
  (proposal/'proposal-retention.json').write_text(json.dumps({'status':'complete','metrics':{'position_change_m':1e-3 if stale else 1e-6,'density_update':0.,'pulse_update_m_s':1e-10}}))
  estimate=fit/'fit.npz';np.savez(estimate,mjd=np.asarray([60000.,60000.1]),states=np.zeros((2,6)),covariance=np.broadcast_to(np.eye(6),(2,6,6)))
  preprocessing=fit/'preprocessing.json';preprocessing.write_text('{}')
  art=[(profilefile,'native_nuisance_profile'),(coordfile,'native_qr_coordinates'),(diagfile,'native_qr_diagnostics'),(costfile,'native_objective'),(factor,'native_qr_factor'),(rhs,'native_qr_rhs'),(estimate,'state_estimate'),(preprocessing,'native_preprocessing_audit')]
  result={'status':'complete','converged':True,'covariance_valid':True,'native_binary_sha256':c.NATIVE_SHA,'method':'groops_pulses','source_hash':'s'*64,'preprocessing_hash':'p'*64,'mask_hash':'m'*64,'runtime':{'source_hash':'s'*64},'force_model_hash':'a'*64,'measurement_model_hash':'b'*64,'preprocessing_audit_sha256':c.sha(preprocessing),'metadata':{'reference_inputs_used':False},'covariance_scope':'marginalized','parameter_blocks':['initial_state','pulses','receiver_clock','float_ambiguities'],'numerical_diagnostics':{},'confirmation_checks':[{'stationary':True}],'artifacts':[{**c.pin(p),'role':r} for p,r in art]}
  job={'method':'groops_pulses','source_hash':'s'*64,'preprocessing_hash':'p'*64,'mask_hash':'m'*64,'runtime':{'source_hash':'s'*64},'force_model_hash':'a'*64,'measurement_model_hash':'b'*64,'expected_native_binary_sha256':c.NATIVE_SHA,'numerics_profile':'qr_lm_staged_jacobian'}
  return result,job,fit
 def test_source_and_support_identity_bound(self):
  for key in ['source_hash','preprocessing_hash','mask_hash']:
   with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
    r,j,f=self.fixture(Path(tmp));r[key]='changed'
    with self.assertRaises(ValueError):runner.assessment(r,j,f)
 def test_cold_start_uses_original_state_and_zero_force(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);fit=root/'fit';point=fit/'point-001-initial';point.mkdir(parents=True);(fit/'initial-input').mkdir()
   nominal=root/'nominal.dat';nominal.write_bytes(b'original nominal')
   (fit/'initial-input/orbit.txt').write_text('60000 1 2 3 4 5 6\n')
   (point/'physical_initial.txt').write_text('1\n2\n3\n4\n5\n6\n')
   (point/'full_pulses_um_s.txt').write_text('0\n'*6);(point/'fixed_force.txt').write_text('0\n'*12)
   with patch.object(c,'NOMINAL_SHA',c.sha(nominal)):
    got=runner.cold_start_evidence({'method':'groops_pulses'},fit,nominal);self.assertTrue(got['initial_state_exact']);self.assertEqual(got['zero_force_count'],6)
    (point/'physical_initial.txt').write_text('2\n2\n3\n4\n5\n6\n')
    with self.assertRaises(ValueError):runner.cold_start_evidence({'method':'groops_pulses'},fit,nominal)
 def test_nonzero_initial_density_rejected(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   root=Path(tmp);fit=root/'fit';point=fit/'point-001-initial';(point/'native').mkdir(parents=True);(fit/'initial-input').mkdir()
   nominal=root/'nominal.dat';nominal.write_bytes(b'original nominal')
   (fit/'initial-input/orbit.txt').write_text('60000 1 2 3 4 5 6\n');(point/'physical_initial.txt').write_text('1\n2\n3\n4\n5\n6\n')
   (point/'native/log_density.txt').write_text('60000 0\n'*60+'60000 0.01\n');(point/'fixed_force.txt').write_text('0\n'*67)
   with patch.object(c,'NOMINAL_SHA',c.sha(nominal)):
    with self.assertRaises(ValueError):runner.cold_start_evidence({'method':'groops_log_drag_ou'},fit,nominal)
 def test_actual_assessment_passes_complete_tiny_final_evidence(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   result=runner.assessment(*self.fixture(Path(tmp)));self.assertEqual(result['rank']['status'],'full_rank');self.assertLess(result['fresh_final_correction']['normalized_gradient'],1e-8)
 def test_stale_final_correction_fails_despite_prior_stationarity(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   with self.assertRaises(ValueError):runner.assessment(*self.fixture(Path(tmp),stale=True))
 def test_conditional_only_final_factor_fails(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   with self.assertRaises(Exception):runner.assessment(*self.fixture(Path(tmp),conditional=True))
 def test_damped_final_factor_fails(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   with self.assertRaises(Exception):runner.assessment(*self.fixture(Path(tmp),damped=True))
 def test_fresh_gradient_recomputed_not_inherited(self):
  with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as tmp:
   with self.assertRaises(ValueError):runner.assessment(*self.fixture(Path(tmp),bad_gradient=True))

if __name__=='__main__':unittest.main(verbosity=2)
