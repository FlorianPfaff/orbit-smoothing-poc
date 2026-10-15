#!/usr/bin/env python3
"""Independent launcher tests using only short fabricated Python heartbeat drivers."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

HERE=Path(__file__).parent
LAUNCHER=HERE/'launch_recovery04.py'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def proc(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return {'pid':pid,'start_ticks':int(fields[19]),'state':fields[0]}
    except FileNotFoundError:return None


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='orbit-launch04-independent-',dir='/tmp');self.root=Path(self.tmp.name)
        self.control=self.root/'control';self.control.mkdir();self.source=self.root/'source';self.source.mkdir()
        self.driver=self.control/'validate_candidate_04.py';self.heartbeat=self.root/'heartbeat';self.started=self.root/'started.json'
        code=('import json,os,signal,time\nfrom pathlib import Path\n'
            +'Path('+repr(str(self.started))+').write_text(json.dumps({"pid":os.getpid(),"sid":os.getsid(0),"parent":os.getppid(),"sighup_ignored":signal.getsignal(signal.SIGHUP)==signal.SIG_IGN}))\n'
            +'while True:\n Path('+repr(str(self.heartbeat))+').write_text(str(time.monotonic()))\n time.sleep(.02)\n')
        self.driver.write_text(code)
        self.execution=self.control/'execution.json';self.execution.write_text(json.dumps({'paths':{'control':str(self.control),'source':str(self.source)},'runtime_artifacts':{'control_python':{'path':sys.executable}}}))
        self.pins=self.control/'pins.json';self.pins.write_text(json.dumps({'driver_sha256':sha(self.driver),'execution_sha256':sha(self.execution)}))
        self.argv=['--execution',str(self.execution),'--pins',str(self.pins),'--pins-sha256',sha(self.pins)]
        self.identities=[]
    def tearDown(self):
        for name in ('candidate04-launch.json','candidate04-launch-failure.json'):
            path=self.control/name
            if path.is_file():
                try:
                    item=json.loads(path.read_text());identity=item.get('driver_process')
                    if identity:self.identities.append(identity)
                except (ValueError,KeyError):pass
        if self.started.is_file():
            pid=json.loads(self.started.read_text())['pid'];identity=proc(pid)
            if identity:self.identities.append(identity)
        for identity in self.identities:
            actual=proc(identity['pid'])
            if actual and actual['start_ticks']==identity['start_ticks'] and actual['state']!='Z':
                os.kill(identity['pid'],signal.SIGTERM)
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            if not any((x:=proc(i['pid'])) and x['start_ticks']==i['start_ticks'] and x['state']!='Z' for i in self.identities):break
            time.sleep(.02)
        self.tmp.cleanup()
    def call(self,runner=None,args=None):
        if runner is None:command=[sys.executable,str(LAUNCHER),*(args or self.argv)]
        else:
            path=self.root/'runner.py';path.write_text(runner);command=[sys.executable,str(path),*(args or self.argv)]
        return subprocess.run(command,capture_output=True,text=True,timeout=10,env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1'))
    def wait_started(self):
        deadline=time.monotonic()+5
        while not self.started.is_file() and time.monotonic()<deadline:time.sleep(.02)
        self.assertTrue(self.started.is_file());data=json.loads(self.started.read_text());self.assertTrue(self.heartbeat.is_file())
        return data
    def alive(self):
        data=self.wait_started();before=self.heartbeat.read_text();time.sleep(.08)
        self.assertNotEqual(self.heartbeat.read_text(),before);self.assertNotEqual(proc(data['pid'])['state'],'Z');return data
    def import_runner(self):
        return 'import importlib.util,sys\nspec=importlib.util.spec_from_file_location("launcher",'+repr(str(LAUNCHER))+');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)\n'
    def test_detached_success_receipt_and_repeat_refusal(self):
        result=self.call();self.assertEqual(result.returncode,0,result.stderr)
        launch=json.loads((self.control/'candidate04-launch.json').read_text());self.identities.append(launch['driver_process'])
        data=self.alive();self.assertEqual(data['pid'],data['sid']);self.assertTrue(data['sighup_ignored'])
        self.assertTrue(launch['launch_committed']);self.assertTrue(launch['start_new_session']);self.assertEqual(launch['observed_argv'],launch['argv'])
        self.assertEqual(launch['launch_helper_sha256'],sha(LAUNCHER));self.assertEqual(launch['campaign_resume'],'not_applicable')
        original=(self.control/'candidate04-launch.json').read_bytes();again=self.call()
        self.assertNotEqual(again.returncode,0);self.assertIn('no implicit retry',again.stderr)
        self.assertEqual((self.control/'candidate04-launch.json').read_bytes(),original);self.alive()
    def test_broken_stdout_after_durable_receipt_leaves_driver_alive(self):
        runner=self.import_runner()+'''class Broken:
 def write(self,value):raise BrokenPipeError('fabricated disconnected SSH output')
 def flush(self):raise BrokenPipeError('fabricated disconnected SSH flush')
sys.stdout=Broken()
m.main()
'''
        result=self.call(runner);self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((self.control/'candidate04-launch.json').read_text());self.identities.append(receipt['driver_process'])
        self.assertTrue(receipt['launch_committed']);self.assertFalse((self.control/'candidate04-launch-failure.json').exists());self.alive()
    def test_sighup_after_success_does_not_kill_detached_driver(self):
        result=self.call();self.assertEqual(result.returncode,0,result.stderr)
        receipt=json.loads((self.control/'candidate04-launch.json').read_text());self.identities.append(receipt['driver_process'])
        data=self.alive();os.kill(data['pid'],signal.SIGHUP);self.alive()
    def test_wrong_sealed_pin_rejects_before_process_launch(self):
        args=self.argv[:-1]+['a'*64];result=self.call(args=args)
        self.assertNotEqual(result.returncode,0);self.assertIn('Sealed pins mismatch',result.stderr)
        self.assertFalse(self.started.exists());self.assertFalse((self.control/'candidate04-driver.log').exists());self.assertFalse((self.control/'candidate04-launch.json').exists())
    def test_changed_driver_hash_rejects_before_launch(self):
        self.driver.write_text(self.driver.read_text()+'# changed\n');result=self.call()
        self.assertNotEqual(result.returncode,0);self.assertIn('Launch controls changed',result.stderr);self.assertFalse(self.started.exists())
    def test_changed_execution_hash_rejects_before_launch(self):
        self.execution.write_text(self.execution.read_text()+'\n');result=self.call()
        self.assertNotEqual(result.returncode,0);self.assertIn('Launch controls changed',result.stderr);self.assertFalse(self.started.exists())
    def test_receipt_failure_terminates_only_owned_child_and_does_not_certify_descendants(self):
        runner=self.import_runner()+'''real=m.write_new
def fail_receipt(path,value):
 if path.name=='candidate04-launch.json':raise OSError('fabricated durable receipt failure')
 return real(path,value)
m.write_new=fail_receipt
m.main()
'''
        result=self.call(runner);self.assertNotEqual(result.returncode,0);self.assertIn('durable receipt failure',result.stderr)
        failure=json.loads((self.control/'candidate04-launch-failure.json').read_text())
        self.assertFalse(failure['descendant_cleanup_verified']);self.assertIsNotNone(failure['returncode'])
        actual=proc(failure['driver_pid']);self.assertTrue(actual is None or actual['state']=='Z')
        self.assertFalse((self.control/'candidate04-launch.json').exists())
    def test_failed_stdout_flush_does_not_enter_rollback(self):
        runner=self.import_runner()+'''class FailedFlush:
 def write(self,value):return len(value)
 def flush(self):raise OSError('fabricated output flush failure')
sys.stdout=FailedFlush()
m.main()
'''
        result=self.call(runner);self.assertEqual(result.returncode,0,result.stderr)
        self.alive();self.assertFalse((self.control/'candidate04-launch-failure.json').exists())


if __name__=='__main__':unittest.main(verbosity=2)
