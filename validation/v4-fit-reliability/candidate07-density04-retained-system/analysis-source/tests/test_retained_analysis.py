"""Focused saved-factor fixtures; never launch a native or nonlinear evaluation."""
from copy import deepcopy
from pathlib import Path
import struct
import tempfile
import unittest

import numpy as np
import retained_analysis as a


class RetainedAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reader,cls.production=a.libraries()

    def coupled(self):
        return np.array([[2.,1.],[0.,3.]]),np.array([1.,2.]),np.array([True,False])

    def test_coupled_joint_profiled_and_production_against_rationals(self):
        R,b,dynamic=self.coupled()
        scales=np.array([2.,.5])
        point=self.production.Linearization(R,b,scales,dynamic,8,9.,13.,'fixture',None).validate()
        for lam,expected in ((0.,np.array([1/6,2/3])),(2.,np.array([3/28,19/28]))):
            joint=a.joint_solve(R,b,dynamic,lam,self.reader)
            profiled,coupling=a.profiled_solve(R,b,dynamic,lam,self.reader)
            native,_,_=self.production.proposal(point,lam)
            for actual in (joint,profiled,native/scales):
                self.assertLess(float(max(abs(actual-expected))),2e-15)
            self.assertGreater(coupling['conditional_coupling_frobenius'],0.)
            self.assertFalse(coupling['original_eliminated_local_recovery_attempted'])

    def test_damped_stationarity_is_not_undamped_gradient(self):
        R,b,dynamic=self.coupled(); z=np.array([3/28,19/28])
        metrics=a.step_diagnostics(R,b,z,dynamic,2.,9.,13.)
        self.assertLess(metrics['damped_stationarity_inf'],1e-14)
        self.assertAlmostEqual(metrics['undamped_residual_gradient_inf'],3/14,places=14)
        self.assertAlmostEqual(metrics['undamped_predicted_reduction'],1955/784,places=14)
        self.assertAlmostEqual(metrics['retained_residual_cost_with_original_constant'],13/2+5/784,places=14)

    def test_native_scaling_and_initial_velocity_si_mapping(self):
        step=np.zeros(67);step[0]=2.;step[61:]=[3.,4.,5.,3600.,7200.,10800.]
        design=np.zeros((6,67));design[:3,61:64]=np.eye(3);design[3:,64:]=np.eye(3)/3600
        initial=np.array([11.,12.,13.,14.,15.,16.]);force=np.full(61,7.)
        mapped,updated=a.physical_mapping(step,design,initial,force)
        self.assertEqual(mapped.tolist(),[14.,16.,18.,15.,17.,19.])
        self.assertEqual(updated[0],9.);self.assertEqual(updated[-1],7.)
        with self.assertRaisesRegex(ValueError,'shape'):
            a.physical_mapping(step,design,initial,np.zeros(67))

    def test_chart_rejects_wrong_roles_units_scales_and_dynamic_flags(self):
        parameters=[{'index':str(i),'name':f'local{i}','unit':'m','scale':'1','dynamic':'0','coordinate_convention':'direct_native_coordinate'} for i in range(386)]
        for i in range(61):parameters[240+i].update(name=f'GRACEC:logDensity::{i}',unit='1',dynamic='1')
        for i,(kind,axis) in enumerate((kind,axis) for kind in ('position','velocity') for axis in 'xyz'):
            parameters[301+i].update(name=f'GRACEC:arc0.{kind}0.{axis}::',dynamic='1',coordinate_convention='direct_native_coordinate' if kind=='position' else 'initial_velocity_times_arc_scale;SI_map=initial_design_artifact')
        info={'schema':'orbit-poc-qr-factor-v1','rows':146,'columns':146,'retained_global_indices':list(range(240,386)),'local_global_indices':list(range(240)),'dynamic':[True]*67+[False]*79,'scales':[1.]*146,'local_elimination':'independent_epoch_clock_vtec_qr'}
        a.verify_chart(info,parameters,np.eye(146),np.ones(146))
        for field,value,index in (('unit','m/s',304),('scale','2',240),('dynamic','0',240),('name',parameters[240]['name'],241)):
            changed=deepcopy(parameters);changed[index][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):a.verify_chart(info,changed,np.eye(146),np.ones(146))
        for field,value in (('retained_global_indices',list(range(239,385))),('dynamic',[1]*67+[0]*79)):
            changed=deepcopy(info);changed[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):a.verify_chart(changed,parameters,np.eye(146),np.ones(146))

    def test_binary_reader_rejects_truncated_nonfinite_and_wrong_payload(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'factor.bin'
            payload=struct.pack('<QQ4d',2,2,2.,1.,0.,3.)
            path.write_bytes(payload)
            self.assertEqual(self.reader.binary_matrix(path),[[2.,1.],[0.,3.]])
            for broken in (payload[:-1],payload+b'x',struct.pack('<QQ4d',2,2,2.,float('nan'),0.,3.)):
                path.write_bytes(broken)
                with self.assertRaises(Exception):self.reader.binary_matrix(path)

    def test_rank_policy_rejects_deficient_and_unresolved_without_damping(self):
        eps=np.finfo(float).eps;t=eps*100
        self.assertEqual(a.rank_certificate(np.diag([1.,20*t]),100)['status'],'full_rank')
        for last,status in ((0.,'rank_deficient'),(.5*t,'rank_deficient'),(5*t,'unresolved_rank')):
            with self.subTest(last=last),self.assertRaisesRegex(ValueError,status):a.rank_certificate(np.diag([1.,last]),100)

    def test_source_derived_damping_rejects_wrong_accepted_owner(self):
        last={'trial':30,'accepted':True,'objective_trial':108511.68952280404,'damping':0.014243095839601297,'gain_ratio':0.9720673144802097}
        history={'accepted_iterations':22,'trial_evaluations':30,'history':[{} for _ in range(29)]+[last]}
        self.assertEqual(a.source_derived_lambda(history),0.004747698613200432)
        for field,value in (('accepted',False),('trial',31),('damping',.001),('objective_trial',108511.0)):
            changed=deepcopy(history);changed['history'][-1][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):a.source_derived_lambda(changed)

    def test_density_state_is_separate_from_native_zero_correction_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'density.txt'
            path.write_text(''.join(f'{60424+i}.000000000000000000 {i/2}\n' for i in range(61)))
            epochs,values=a.density_table(path)
            self.assertEqual(len(epochs),61);self.assertEqual(values[60],30.)
            path.write_text(''.join('60424.0 1\n' for _ in range(61)))
            with self.assertRaisesRegex(ValueError,'epochs'):a.density_table(path)

    def test_error_units_are_posterior_sd_and_nonfinite_is_rejected(self):
        sd=np.array([2.,.5]);x=np.array([10.,20.]);y=x+sd*1e-8
        self.assertLess(a.sd_error(x,y,sd),1.01e-8)
        self.assertAlmostEqual(a.sd_error(x*1000,y*1000,sd*1000),a.sd_error(x,y,sd),places=11)
        with self.assertRaisesRegex(ValueError,'normalization'):a.sd_error(x,np.array([float('nan'),20.]),sd)


if __name__=='__main__':unittest.main()
