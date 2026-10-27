"""Prepared binding/eligibility fixtures only; not imported or run."""
import importlib.util
from pathlib import Path
import unittest

source=Path(__file__).resolve().parents[1]/'probe.py'
spec=importlib.util.spec_from_file_location('undamped_probe',source)
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class ProbeBindingTests(unittest.TestCase):
    def test_reference_subtraction_density_baseline_and_velocity_conversion(self):
        reference=[3.]*67;proposal=reference.copy()
        proposal[0]+=0.25;proposal[61]+=2.;proposal[64]+=4.
        design=[[0.]*67 for _ in range(6)]
        for i in range(3):design[i][61+i]=1.;design[i+3][64+i]=0.125
        result=probe.candidate([10.]*6,design,proposal,reference,[0.5]*61)
        self.assertEqual(result['force'],[0.75]+[0.5]*60)
        self.assertEqual(result['initial'],[12.,10.,10.,10.5,10.,10.])
        self.assertEqual(result['dynamic_delta'][1:61],[0.]*60)

    def test_full_design_is_used_and_nonfinite_or_wrong_shape_is_rejected(self):
        design=[[0.]*67 for _ in range(6)];design[0][0]=2.;design[5][66]=0.25
        result=probe.candidate([0.]*6,design,[1.]*67,[0.]*67,[0.]*61)
        self.assertEqual(result['initial'],[2.,0.,0.,0.,0.,0.25])
        with self.assertRaises(probe.Ineligible):probe.candidate([0.]*6,design,[1.]*66,[0.]*67,[0.]*61)
        bad=[0.]*61;bad[12]=float('nan')
        with self.assertRaises(probe.Ineligible):probe.candidate([0.]*6,design,[1.]*67,[0.]*67,bad)

    def test_matrix_envelope_rejects_missing_extra_and_nonfinite_values(self):
        good='groops matrix version=20200123\nMatrix( 2 x 1 )\n 1\n 2\n'
        self.assertEqual(probe.matrix(good,2,1),[[1.],[2.]])
        for bad in (good+'3\n',good.replace(' 2\n',''),good.replace(' 2\n','nan\n'),good.replace('2 x 1','1 x 2')):
            with self.subTest(text=bad),self.assertRaises(probe.Ineligible):probe.matrix(bad,2,1)

    def test_strict_gate_requires_two_updates_full_confirmation_and_no_floor(self):
        profile={'nuisance_converged':True,'nuisance_floor_limited':False,'conditional_nuisance_qr':True,
            'fresh_full_nuisance_confirmed':True,'threshold_m':1e-8,'required_consecutive_small_updates':2,
            'fixed_weights':True,'dynamic_updates':False,'fresh_full_nuisance_update_m':5e-9,
            'history':[{'maximum_update_m':6e-9},{'maximum_update_m':5e-9}]}
        confirmation={'stationary_without_update':True,'accepted':False,'alpha':0,'undamped_maximum_update_m':5e-9,
            'zero_update_replay':{'status':0,'actual_reduction':0,'maximum_update_m':0,'error':''},
            'trials':[{'alpha':1,'status':0,'error':'','maximum_update_m':5e-9}]}
        probe.strict_profile(profile,confirmation)
        for changed in ({'nuisance_floor_limited':True},{'fresh_full_nuisance_confirmed':False},
                        {'fresh_full_nuisance_update_m':1e-8},{'history':[{'maximum_update_m':5e-9}]}):
            with self.subTest(changed=changed),self.assertRaises(probe.Ineligible):
                probe.strict_profile(dict(profile,**changed),confirmation)
        with self.assertRaises(probe.Ineligible):probe.strict_profile(profile,dict(confirmation,trials=[]))

    def test_one_ordinary_evaluation_has_no_optimizer_or_covariance_call(self):
        marker=object();state=object();calls=[]
        class Model:
            def evaluate(self,*args,**kwargs):calls.append((args,kwargs));return marker
            def __getattr__(self,name):raise AssertionError('Unexpected model operation: '+name)
        self.assertIs(probe.evaluate_once(Model(),state),marker)
        self.assertEqual(calls,[((state,'archived-undamped'),{'tighter':False,'covariance':False})])
