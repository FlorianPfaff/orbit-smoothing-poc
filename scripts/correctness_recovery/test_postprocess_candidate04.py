#!/usr/bin/env python3
"""Fabricated finite postprocessing supervisor tests; no real campaign signals."""
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest
from unittest import mock
HERE=Path(__file__).parent
spec=importlib.util.spec_from_file_location('post04',HERE/'postprocess_candidate04.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class WaitTests(unittest.TestCase):
    def test_waits_for_driver_exit_after_terminal_cleanup(self):
        with mock.patch.object(p,'terminal_receipt',return_value={'status':'failed'}), \
             mock.patch.object(p,'process_alive',side_effect=[True,False]),mock.patch.object(p.time,'sleep') as sleep:
            value=p.wait_for_terminal({'driver_process':{}},time.monotonic()+10)
        self.assertEqual(value['status'],'failed');self.assertEqual(sleep.call_count,1)
    def test_failed_launch_missing_results_is_explicit(self):
        with mock.patch.object(p,'terminal_receipt',return_value=None),mock.patch.object(p,'process_alive',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'exited without terminal'):p.wait_for_terminal({'driver_process':{}},time.monotonic()+10)
    def test_wait_timeout_never_launches_work(self):
        with self.assertRaisesRegex(TimeoutError,'Finite wait'):p.wait_for_terminal({'driver_process':{}},time.monotonic()-1)

class SupervisionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='post04-',dir='/dev/shm');self.root=Path(self.tmp.name);self.journal={'steps':[]}
    def tearDown(self):self.tmp.cleanup()
    def test_failed_launch_is_recorded(self):
        with mock.patch.object(p,'verify_small_identities'),mock.patch.object(p.subprocess,'Popen',side_effect=OSError('launch failed')):
            entry=p.run_stage('audit',['never'],self.root,time.monotonic()+5,self.journal,{})
        self.assertEqual(entry['status'],'launch_timeout_or_execution_failure');self.assertIn('launch failed',entry['error']);self.assertTrue(entry['cleanup_verified'])
    def test_timeout_kills_only_owned_helper_group(self):
        child=mock.Mock(pid=987654);child.wait.side_effect=[subprocess.TimeoutExpired('helper',1),-9];child.poll.side_effect=[None,-9]
        with mock.patch.object(p,'verify_small_identities'),mock.patch.object(p.subprocess,'Popen',return_value=child),mock.patch.object(p.os,'killpg') as kill:
            entry=p.run_stage('audit',['never'],self.root,time.monotonic()+5,self.journal,{})
        kill.assert_called_once_with(987654,signal.SIGKILL);self.assertTrue(entry['cleanup_verified'])
    def test_post_popen_receipt_error_still_cleans_helper(self):
        child=mock.Mock(pid=987654);child.poll.side_effect=[None,-9];child.wait.return_value=-9
        real=p.save;calls=0
        def fail_second(path,value):
            nonlocal calls
            calls+=1
            if calls==2:raise OSError('receipt failure')
            return real(path,value)
        with mock.patch.object(p,'verify_small_identities'),mock.patch.object(p.subprocess,'Popen',return_value=child),mock.patch.object(p.os,'killpg') as kill,mock.patch.object(p,'save',side_effect=fail_second):
            entry=p.run_stage('audit',['never'],self.root,time.monotonic()+5,self.journal,{})
        kill.assert_called_once();self.assertTrue(entry['cleanup_verified']);self.assertIn('receipt failure',entry['error'])

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='post04-main-',dir='/dev/shm');self.root=Path(self.tmp.name);self.planfile=self.root/'plan.json';self.planfile.write_text('{}')
        self.output=self.root/'new-output';self.plan={'output_root':str(self.output),'source_sha256':'a'*64,'wait_seconds':60,'reporting_python':{'path':'/fake/python','sha256':'b'*64,'versions':{}},'candidate_pins':{'path':'/fake/pins','sha256':'b'*64}}
        self.stack_runtime=mock.patch.object(p,'EXECUTION',{'fit_cpu':0,'paths':{'binaries':'/fake/binaries'}});self.stack_runtime.start()
        self.stack=ExitStack();self.handlers={n:signal.getsignal(n) for n in (signal.SIGINT,signal.SIGTERM)}
        self.stack.enter_context(mock.patch.object(p,'load_plan',return_value=self.plan))
        self.stack.enter_context(mock.patch.object(p,'verify_small_identities'))
        self.stack.enter_context(mock.patch.object(p,'wait_for_terminal',return_value={'status':'failed','source':{'sha256':'a'*64}}))
        self.stack.enter_context(mock.patch.object(p,'source_identity',return_value={'sha256':'a'*64}))
        self.stack.enter_context(mock.patch.object(p,'artifact',side_effect=lambda path:{'path':str(path),'sha256':'b'*64}))
    def tearDown(self):
        for number,handler in self.handlers.items():signal.signal(number,handler)
        self.stack_runtime.stop();self.stack.close();self.tmp.cleanup()
    def fake_stage(self,name,argv,output,deadline,journal,plan,missing=False):
        entry={'name':name,'returncode':1 if name=='audit' else 0,'cleanup_verified':True};journal['steps'].append(entry)
        if missing and name=='audit':entry['returncode']=2;return entry
        if name=='audit':path=output/'independent-audit.json';data={'schema':'orbit-poc-correctness-independent-audit-v4','passed':False}
        elif name=='report':path=output/'report/summary.json';data={'schema':'orbit-correction-evidence-report-v4','candidate_evidence_status':'failed'}
        else:path=output/'publication/manifest.json';data={'schema':'orbit-poc-correctness-publication-bundle-v4','reported_evidence_status':'failed'}
        path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(data));return entry
    def test_scientific_failure_does_not_hide_report_or_collection(self):
        with mock.patch.object(p,'run_stage',side_effect=self.fake_stage):code=p.main(['--plan',str(self.planfile),'--plan-sha256','b'*64])
        data=json.loads((self.output/'pipeline.json').read_text());self.assertEqual(code,0)
        self.assertEqual(data['status'],'completed');self.assertEqual(data['scientific_status'],'failed');self.assertEqual(len(data['steps']),3)
    def test_missing_audit_output_is_explicit_and_later_stages_attempted(self):
        with mock.patch.object(p,'run_stage',side_effect=lambda *args:self.fake_stage(*args,missing=True)):code=p.main(['--plan',str(self.planfile),'--plan-sha256','b'*64])
        data=json.loads((self.output/'pipeline.json').read_text());self.assertEqual(code,1);self.assertEqual(len(data['steps']),3)
        self.assertIn('missing',data['steps'][0]['result_error']);self.assertEqual(data['status'],'failed')
    def test_audit_exit_code_cannot_contradict_its_pass_flag(self):
        def wrong(*args):
            entry=self.fake_stage(*args)
            if args[0]=='audit':entry['returncode']=0
            return entry
        with mock.patch.object(p,'run_stage',side_effect=wrong):code=p.main(['--plan',str(self.planfile),'--plan-sha256','b'*64])
        data=json.loads((self.output/'pipeline.json').read_text());self.assertEqual(code,1)
        self.assertIn('contradicts',data['steps'][0]['result_error']);self.assertEqual(len(data['steps']),3)
    def test_identity_failure_prevents_helpers(self):
        with mock.patch.object(p,'verify_small_identities',side_effect=RuntimeError('identity changed')),mock.patch.object(p,'run_stage',side_effect=AssertionError('no launch')):
            code=p.main(['--plan',str(self.planfile),'--plan-sha256','b'*64])
        self.assertEqual(code,1);self.assertIn('identity changed',json.loads((self.output/'pipeline.json').read_text())['error'])



class TerminalIdentityTests(unittest.TestCase):
    def test_different_resume_driver_or_control_identity_are_rejected(self):
        with tempfile.TemporaryDirectory(prefix='post04-terminal-',dir='/dev/shm') as folder:
            root=Path(folder);run=root/'run';control=root/'control';run.mkdir();control.mkdir()
            def write(path,data):path.write_text(json.dumps(data))
            pins=control/'candidate04-pins.json';write(pins,{'driver_sha256':'a'*64,'wrapper_sha256':'b'*64})
            pin={'path':str(pins),'sha256':p.sha(pins)};execution={'path':str(control/'execution.json'),'sha256':'c'*64}
            identity={'pid':123,'start_ticks':456,'boot_id':'actual-boot'}
            value={'status':'failed','finished_at':'done','final_cleanup':{'verified':True},
                'resume':{'status':'not_applicable','reason':'no_campaign_running'},'helper_sha256':'a'*64,
                'required_pins':pin,'execution':execution,'wrapper':{'path':str(control/'with_correctness_namespace_04.py'),'sha256':'b'*64},
                'admission':{'status':'admitted','boot_id':'actual-boot','driver_identity':{'pid':123,'start_ticks':456}},'steps':[{'name':'build'}]}
            write(run/'pipeline.json',value);plan={'candidate_pins':pin,'execution':execution,'driver_process':identity}
            with mock.patch.multiple(p,RUN=run,CONTROL=control):
                self.assertEqual(p.terminal_receipt(plan)['status'],'failed')
                value['resume']={'status':'resumed'};write(run/'pipeline.json',value)
                with self.assertRaisesRegex(RuntimeError,'campaign resume'):p.terminal_receipt(plan)
                value['resume']={'status':'not_applicable','reason':'no_campaign_running'};value['helper_sha256']='c'*64;write(run/'pipeline.json',value)
                with self.assertRaisesRegex(RuntimeError,'driver identity'):p.terminal_receipt(plan)
                value['helper_sha256']='a'*64;value['admission']['driver_identity']['start_ticks']=999;write(run/'pipeline.json',value)
                with self.assertRaisesRegex(RuntimeError,'exact watched'):p.terminal_receipt(plan)

    def test_boot_change_and_missing_cleanup_never_claim_completion(self):
        with tempfile.TemporaryDirectory(prefix='post04-boot-',dir='/dev/shm') as folder:
            root=Path(folder);(root/'pipeline.json').write_text(json.dumps({'status':'failed','finished_at':'done','final_cleanup':{'verified':False}}))
            with mock.patch.object(p,'RUN',root):self.assertIsNone(p.terminal_receipt({}))
            plan={'driver_process':{'boot_id':'not-the-current-boot'}}
            with self.assertRaisesRegex(RuntimeError,'boot identity changed'):p.verify_small_identities(plan)

    def test_wrong_helper_pin_prevents_import_and_launch(self):
        with tempfile.TemporaryDirectory(prefix='post04-helper-',dir='/dev/shm') as folder:
            root=Path(folder);control=root/'control';control.mkdir();helper=control/'recovery_evidence_04.py';helper.write_text('raise RuntimeError("must not import")')
            execution=root/'execution.json';execution.write_text(json.dumps({'paths':{'control':str(control)}}))
            plan={'schema':'orbit-poc-correctness-postprocess04-plan-v1','execution':{'path':str(execution),'sha256':p.sha(execution)},
                'candidate_pins':{'path':str(root/'pins'),'sha256':'b'*64},'source_sha256':'a'*64,'source_commit':'f'*40,
                'driver_process':{'pid':1,'start_ticks':1,'boot_id':'boot'},'helpers':{name:'b'*64 for name in p.HELPERS},
                'reporting_python':{'path':'/fake/python','sha256':'a'*64,'versions':dict.fromkeys(('python','numpy','scipy','gtsam','pytest','psutil'),'fixture')},
                'postprocessor_sha256':'c'*64,'output_root':str(root/'postprocess-04-fresh'),'previous':'/old/cases','wait_seconds':60}
            path=root/'plan.json';path.write_text(json.dumps(plan))
            with self.assertRaisesRegex(RuntimeError,'Recovery verifier source changed'):p.load_plan(path,p.sha(path))

if __name__=='__main__':unittest.main(verbosity=2)
