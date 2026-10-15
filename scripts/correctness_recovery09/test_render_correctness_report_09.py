#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('report',HERE/'render_correctness_report_09.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

class ReportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='report-mock-',dir=HERE)
        self.root=Path(self.temp.name);self.run=self.root/'run';self.old=self.root/'old';self.control=self.root/'control'
    def tearDown(self):self.temp.cleanup()
    def write(self,path,data):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data));return path
    def obj(self,passed=True):
        return {'passed':passed,'native_binary_sha256':'a'*64,'source_hash':'b'*64,
            'relative_derivative_tolerance':1e-4,'derivative_refinement_policy':dict(r.POLICY),
            'prior':{'source':'constraint.logDensityOu','maximum_residual_difference':1e-9,'absolute_tolerance':2e-8,'cost':1},
            'directional_derivatives':[{'scale':h,'finite_difference':1,'native_derivative':1,'relative_difference':0.,'empirical_resolution_fraction':1e-6,'relative_difference_plus_resolution':1e-6,'passes_unchanged_tolerance':True} for h in (1.,.5)],
            'profile_evaluations':[]}
    def test_missing_all_evidence_stays_incomplete_and_explicit(self):
        report=r.render(self.run,self.old,self.control,self.root/'report')
        self.assertEqual(report['candidate_evidence_status'],'incomplete')
        self.assertEqual(report['native_tests']['status'],'missing')
        self.assertEqual(len(report['steps']),13)
        page=(self.root/'report/index.html').read_text()
        self.assertIn('does not replace',page);self.assertIn('missing',page)
    def test_all_directional_scales_and_partial_failure_are_retained(self):
        data=self.obj(False);data['error']='Native failed at point-012-direction-0.25-1-repeat/profile.log'
        data['profile_evaluations']=[{'label':'direction-0.25--1','nuisance_converged':False,'nuisance_floor_limited':True}]
        result=r.objective(self.write(self.root/'objective.json',data))
        self.assertEqual(result['status'],'failed');self.assertEqual(len(result['directional_scales']),9)
        self.assertEqual(result['directional_scales'][2]['status'],'incomplete')
        self.assertEqual(result['directional_scales'][3]['status'],'not_attempted')
        self.assertEqual(result['profile_resolution_counts']['audited_floor_only'],1)
    def test_changed_tolerance_or_prior_cannot_be_reported_pass(self):
        data=self.obj();data['relative_derivative_tolerance']=.1
        self.assertEqual(r.objective(self.write(self.root/'x.json',data))['status'],'invalid')
        data=self.obj();data['prior']['absolute_tolerance']=.1
        self.assertEqual(r.objective(self.write(self.root/'x.json',data))['status'],'invalid')
    def test_contradictory_scale_pass_is_invalid(self):
        data=self.obj();data['directional_derivatives'][0]['relative_difference_plus_resolution']=.3
        self.assertEqual(r.objective(self.write(self.root/'x.json',data))['status'],'invalid')
    def test_json_nonfinite_duplicate_and_wrong_root_are_invalid(self):
        path=self.root/'x.json'
        for text in ('{"a":NaN}','{"a":1e999}','{"a":1,"a":2}','[]'):
            path.write_text(text);self.assertEqual(r.evidence(path)[0]['status'],'invalid')
    def test_junit_counts_all_outcomes_and_rejects_declared_mismatch(self):
        path=self.root/'tests.xml'
        path.write_text('<testsuite tests="4" failures="1" errors="1" skipped="1"><testcase name="ok"/><testcase name="bad"><failure message="bad"/></testcase><testcase name="error"><error/></testcase><testcase name="skip"><skipped/></testcase></testsuite>')
        result=r.junit(path);self.assertEqual(result['status'],'failed')
        self.assertEqual(result['counts'],dict(passed=1,failed=1,errors=1,skipped=1,total=4))
        path.write_text('<testsuite tests="2"><testcase/></testsuite>')
        self.assertEqual(r.junit(path)['status'],'invalid')
    def test_junit_skip_is_incomplete_and_entities_rejected(self):
        path=self.root/'tests.xml';path.write_text('<testsuite><testcase><skipped/></testcase></testsuite>')
        self.assertEqual(r.junit(path)['status'],'incomplete')
        path.write_text('<!DOCTYPE testsuite [<!ENTITY x "bad">]><testsuite/>')
        self.assertEqual(r.junit(path)['status'],'invalid')
    def test_floor_audit_is_never_classified_as_strict_convergence(self):
        data={'passed':True,'returncode':0,'timed_out':False,'native_unchanged':True,
            'strict_nuisance_converged':False,'progress_only_floor_validated':True,'allow_floor_limited_requested':True,
            'fixed_observations_and_weights_verified_every_trial':True,'zero_update_replay_exact':True,
            'ambiguity_half_integer_crossings_tested':3,'profile':{'nuisance_converged':False,'nuisance_floor_limited':True,
                'nuisance_predicted_reduction':1e-12,'nuisance_objective_resolution':1e-10,
                'nuisance_floor_audit':[{'success':True,'support_unchanged':True}]}}
        result=r.nuisance(self.write(self.root/'x.json',data))
        self.assertEqual(result['status'],'passed');self.assertEqual(result['resolution_status'],'audited_floor_only_not_converged')
        data['strict_nuisance_converged']=True
        self.assertEqual(r.nuisance(self.write(self.root/'x.json',data))['status'],'invalid')
    def test_html_escapes_all_evidence_and_refuses_overwrite(self):
        self.write(self.run/'pipeline.json',{'status':'failed','error':'<script>alert(1)</script>','source':{'files':{'<img src=x>':'x'}}})
        report=r.render(self.run,self.old,self.control,self.root/'report')
        page=(self.root/'report/index.html').read_text()
        self.assertNotIn('<script>',page);self.assertNotIn('<img src=x>',page)
        self.assertIn('&lt;script&gt;',page)
        with self.assertRaises(ValueError):r.render(self.run,self.old,self.control,self.root/'report')
    def test_native_binary_mismatch_marks_candidate_invalid(self):
        self.write(self.run/'pipeline.json',{'status':'running','native':{'sha256':'c'*64}})
        self.write(self.run/'objective-log_drag_ou/validation.json',self.obj())
        result=r.collect(self.run,self.old,self.control)
        self.assertEqual(result['candidate_evidence_status'],'invalid')
        self.assertEqual(len(result['integrity_errors']),1)
    def test_refinement_requires_all_four_signals_and_exclusive_limit(self):
        data={'passed':True,'status':'complete','state_grid_seconds':[5.,2.5],
            'metrics':{'aligned_position_maximum_m':1e-7,'offgrid_position_maximum_m':1e-6},
            'native_signals':{'comparison_weights_frozen':True,'fixed_nuisance_values_identical':True,
                'signals':[{'observable':o,'frequency_hz':f,'maximum_fraction_of_sigma':.001,'passed':True} for o in ('code','carrier') for f in (1575420000.,1227600000.)]}}
        self.assertEqual(r.refinement(self.write(self.root/'x.json',data))['status'],'passed')
        data['native_signals']['signals'][0]['maximum_fraction_of_sigma']=.01
        self.assertEqual(r.refinement(self.write(self.root/'x.json',data))['status'],'invalid')
    def test_preserved_earlier_failure_does_not_disappear(self):
        self.write(self.old/'log_drag_ou-staged/validation.json',self.obj(False))
        result=r.collect(self.run,self.old,self.control)
        self.assertEqual(result['previous_objectives']['log_drag_ou']['status'],'failed')
        self.assertFalse(result['frozen_campaign_reclassified'])
        self.assertEqual(result['release_acceptance'],'not_assessed')

    def test_unplanned_failed_pipeline_steps_remain_visible(self):
        self.write(self.run/'pipeline.json',{'status':'failed','steps':[{'name':'extra-test','status':'failed','returncode':9}]})
        result=r.collect(self.run,self.old,self.control)
        self.assertEqual(result['steps'][-1]['name'],'extra-test')
        self.assertEqual(result['steps'][-1]['status'],'failed')
    def test_invalid_pipeline_is_not_merely_incomplete(self):
        self.run.mkdir();(self.run/'pipeline.json').write_text('{bad')
        self.assertEqual(r.collect(self.run,self.old,self.control)['candidate_evidence_status'],'invalid')
    def test_independent_audit_must_pin_current_objective_and_nuisance_receipts(self):
        inputs=[]
        for method in r.METHODS:
            path=self.write(self.run/('objective-'+method)/'validation.json',self.obj())
            inputs.append(r.evidence(path)[0])
        path=self.write(self.run/'nuisance-replay/receipt.json',{'passed':False})
        inputs.append(r.evidence(path)[0])
        path=self.write(self.run/'nuisance-replay-candidate1-point012/receipt.json',{'passed':False})
        inputs.append(r.evidence(path)[0])
        audit=self.write(self.root/'audit.json',{'schema':'orbit-poc-correctness-independent-audit09-v1','passed':False,'input_artifacts':inputs,'errors':['preserved failure'],
            'objective_methods':{m:{'passed':False} for m in r.METHODS},'nuisance_replays':{n:{'passed':False} for n in r.REPLAYS}})
        result=r.collect(self.run,self.old,self.control,audit)
        self.assertEqual(result['independent_audit']['status'],'failed')
        changed=self.obj();changed['source_hash']='changed'
        self.write(self.run/'objective-pulses/validation.json',changed)
        self.assertEqual(r.collect(self.run,self.old,self.control,audit)['independent_audit']['status'],'invalid')

    def test_reused_build_keeps_prior_native_test_failure_visible(self):
        native={'sha256':'a'*64}
        prior=self.write(self.root/'prior/pipeline.json',{'status':'failed','native':native,'steps':[
            {'name':'clone','status':'passed'},{'name':'checkout','status':'passed'},{'name':'build','status':'passed'},
            {'name':'native-tests','status':'failed','returncode':1}]})
        pin=r.evidence(prior)[0]
        self.write(self.run/'pipeline.json',{'status':'running','native':native,'reused_build':{'prior_pipeline':pin}})
        result=r.collect(self.run,self.old,self.control)
        self.assertEqual([s['status'] for s in result['steps'][:3]],['reused_not_rerun']*3)
        self.assertEqual(result['prior_validation_attempt']['record']['steps'][-1]['status'],'failed')
        self.assertEqual(result['additional_refinement']['density_24h']['status'],'missing')
        self.assertEqual(result['additional_refinement']['flight_april24']['status'],'missing')
        self.assertIn('native-tests',r.document(result))
        self.assertEqual(result['integrity_errors'],[])
    def test_reused_build_prior_receipt_mutation_is_invalid(self):
        prior=self.write(self.root/'prior.json',{'native':{'sha256':'a'}});pin=r.evidence(prior)[0]
        self.write(self.run/'pipeline.json',{'reused_build':{'prior_pipeline':pin},'native':{'sha256':'a'}})
        self.write(prior,{'native':{'sha256':'changed'}})
        self.assertEqual(r.collect(self.run,self.old,self.control)['candidate_evidence_status'],'invalid')
    def test_flight_refinement_uses_actual_halved_controls_without_accuracy_claim(self):
        data={'passed':True,'status':'complete','controls':{'coarse':{'state_seconds':5.,'thermal_seconds':[.5],'atmosphere_seconds':1.},
            'fine':{'state_seconds':2.5,'thermal_seconds':[.25],'atmosphere_seconds':.5}},
            'metrics':{'aligned_position_maximum_m':1e-7,'offgrid_position_maximum_m':1e-6},
            'native_signals':{'comparison_weights_frozen':True,'fixed_nuisance_values_identical':True,
                'signals':[{'observable':o,'frequency_hz':f,'maximum_fraction_of_sigma':.001,'passed':True} for o in ('code','carrier') for f in (1575420000.,1227600000.)]}}
        path=self.write(self.root/'flight.json',data)
        self.assertEqual(r.refinement(path,flight=True)['status'],'passed')
        data['controls']['fine']['atmosphere_seconds']=1.
        self.assertEqual(r.refinement(self.write(path,data),flight=True)['status'],'invalid')

    def test_recovery_never_uses_historical_pause_as_current_admission(self):
        self.write(self.control/'pause-02.json',{'status':'paused','attempt':2})
        self.write(self.control/'resume-02.json',{'status':'resumed'})
        self.write(self.run/'pipeline.json',{'status':'running'})
        result=r.collect(self.run,self.old,self.control)
        self.assertNotIn('pause-02.json',result['provenance'])
        self.assertNotIn('resume-02.json',result['provenance'])

    def test_both_failed_replay_locations_and_other_gates_stay_visible(self):
        self.write(self.run/'pipeline.json',{'status':'failed','steps':[{'name':'native-tests','status':'passed'}]})
        for name in r.REPLAYS:self.write(self.run/name/'receipt.json',{'passed':False,'returncode':1})
        result=r.collect(self.run,self.old,self.control);page=r.document(result)
        self.assertEqual(set(result['nuisance_replays']),set(r.REPLAYS))
        self.assertTrue(all(v['status']=='failed' for v in result['nuisance_replays'].values()))
        self.assertIn('point-030-direction-0.015625-1-repeat',page)
        self.assertIn('point-012-direction-0.25--1-repeat',page)
        self.assertIn('Native tests',page);self.assertIn('Candidate objective checks',page)
    def test_missing_second_replay_is_explicit_and_not_shared_with_first(self):
        self.write(self.run/'nuisance-replay/receipt.json',{'passed':False})
        result=r.collect(self.run,self.old,self.control)
        self.assertEqual(result['nuisance_replays']['nuisance-replay']['status'],'failed')
        self.assertEqual(result['nuisance_replays']['nuisance-replay-candidate1-point012']['status'],'missing')
    def test_new_build_preserves_old_failed_candidate_without_reuse_claim(self):
        prior=self.write(self.root/'prior.json',{'status':'failed','native':{'sha256':'a'*64},'steps':[{'name':'objective-log_drag_ou','status':'failed'}]})
        self.write(self.run/'pipeline.json',{'status':'failed','native':{'sha256':'b'*64},'prior_failed_validation':r.evidence(prior)[0]})
        result=r.collect(self.run,self.old,self.control);page=r.document(result)
        self.assertEqual(result['integrity_errors'],[])
        self.assertIn('uses a new build',page);self.assertNotIn('build is reused byte for byte',page)
    def test_second_replay_read_cannot_supply_unpinned_failure_diagnostics(self):
        from unittest import mock
        path=self.write(self.root/'receipt.json',{'passed':False,'error':'first'})
        real=r.evidence;calls=0
        def changed(p,**kwargs):
            nonlocal calls
            calls+=1
            if calls==2:path.write_text(json.dumps({'passed':False,'error':'different'}))
            return real(p,**kwargs)
        with mock.patch.object(r,'evidence',side_effect=changed):result=r.exact_replay(path,'case')
        self.assertEqual(result['status'],'invalid')
        self.assertIn('changed between',result['integrity_errors'][0])
    def test_passed_junit_requires_recorded_inventory_and_pinned_count(self):
        self.run.mkdir();(self.run/'native-tests.xml').write_text('<testsuite><testcase/></testsuite>')
        self.write(self.run/'pipeline.json',{'status':'running'})
        self.assertEqual(r.collect(self.run,self.old,self.control)['native_tests']['status'],'invalid')
        inventory={'tests':1,'passed':1,'failures':0,'errors':0,'skipped':0}
        self.write(self.run/'pipeline.json',{'status':'running','native_test_inventory':inventory})
        self.assertEqual(r.collect(self.run,self.old,self.control)['native_tests']['status'],'invalid')
        self.write(self.control/'candidate09-pins.json',{'expected_native_test_count':106})
        self.assertEqual(r.collect(self.run,self.old,self.control)['native_tests']['status'],'invalid')
    def test_claimed_pass_without_cleanup_or_actual_resume_never_passes(self):
        self.write(self.run/'pipeline.json',{'status':'passed','resume':{'status':'resumed'}})
        result=r.collect(self.run,self.old,self.control)
        self.assertNotEqual(result['candidate_evidence_status'],'passed_scoped_checks')
        self.assertIn('Recovery provenance',str(result['integrity_errors']))
    def test_numerical_parsers_are_ast_identical(self):
        import ast
        old=ast.parse((HERE/'render_correctness_report.py').read_text());new=ast.parse((HERE/'render_correctness_report_09.py').read_text())
        for name in ('objective','junit','refinement','nuisance'):
            a=next(n for n in old.body if getattr(n,'name',None)==name);b=next(n for n in new.body if getattr(n,'name',None)==name)
            self.assertEqual(ast.dump(a,include_attributes=False),ast.dump(b,include_attributes=False),name)

if __name__=='__main__':unittest.main(verbosity=2)


def _native_fixture(tmp_path):
    from recovery_fixture_09 import install,write
    run=tmp_path/'validation-09';control=tmp_path/'control'
    modules=['tests/test_numerics_native_qr.py','tests/test_numerics_original_objective.py',
        'tests/test_numerics_mean_residual.py','tests/test_numerics_derivatives.py',
        'tests/test_numerics_geometry_precision.py','tests/test_numerics_synthetic_force_arithmetic.py']
    pipeline={'status':'running','steps':[{'name':'native-tests','status':'passed','returncode':0,'argv':['pytest',*modules]}],
        'native_test_inventory':{'tests':106,'passed':106,'failures':0,'errors':0,'skipped':0}}
    pipeline,_=install(tmp_path,pipeline)
    text='<testsuite tests="106" failures="0" errors="0" skipped="0">'+''.join(f'<testcase classname="fixture" name="test_{i}"/>' for i in range(106))+'</testsuite>'
    (run/'native-tests.xml').write_text(text)
    return run,control,pipeline


def test_exact_106_tests_and_executed_modules_are_required(tmp_path):
    run,control,pipeline=_native_fixture(tmp_path)
    result=r.collect(run,tmp_path/'old',control)
    assert result['native_tests']['status']=='passed'
    assert result['recovery']['status']=='verified'
    assert result['candidate_evidence_status']=='incomplete'


def test_106_duplicate_tests_do_not_substitute_exact_inventory(tmp_path):
    run,control,pipeline=_native_fixture(tmp_path)
    path=run/'native-tests.xml';path.write_text(path.read_text().replace('name="test_105"','name="test_0"'))
    result=r.collect(run,tmp_path/'old',control)
    assert result['native_tests']['status']=='invalid'
    assert 'duplicate' in str(result['integrity_errors'])


def test_test_module_substitution_is_invalid_even_with_106_passes(tmp_path):
    from recovery_fixture_09 import write
    run,control,pipeline=_native_fixture(tmp_path)
    pipeline['steps'][0]['argv'][-1]='tests/easier.py';write(run/'pipeline.json',pipeline)
    result=r.collect(run,tmp_path/'old',control)
    assert result['native_tests']['status']=='invalid'
    assert 'six-module' in str(result['integrity_errors'])
