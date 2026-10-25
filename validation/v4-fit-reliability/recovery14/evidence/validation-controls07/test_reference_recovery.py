"""Pure recovery-control tests; no native, SSH, compiler, or model execution."""
import copy
import importlib.util
import json
from pathlib import Path
import signal
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).with_name('reference_recovery.py')
spec = importlib.util.spec_from_file_location('reference_recovery_tested', SCRIPT)
r = importlib.util.module_from_spec(spec)
exec(compile(SCRIPT.read_bytes(), str(SCRIPT), 'exec'), r.__dict__)


def process(pid, parent=1, name='sleep', argv=None, state='S', start_ticks=100):
    return {'pid': pid, 'parent': parent, 'name': name, 'argv': argv or [name],
            'state': state, 'start_ticks': start_ticks}


class AdmissionTests(unittest.TestCase):
    def admit(self, rows=None, **changes):
        settings = {'self_pid': 10, 'affinity': {3, 4},
                    'available_memory': 9 * 1024**3, 'boot_id': 'new-boot', 'host': 'current-host'}
        settings.update(changes)
        return r.admission_from_snapshot(rows or [process(10)], **settings)

    def test_current_boot_is_recorded_without_old_boot_authorization(self):
        receipt = self.admit()
        self.assertEqual(receipt['boot_id'], 'new-boot')
        self.assertEqual(receipt['host'], 'current-host')
        self.assertNotIn('old_boot_id', receipt)

    def test_cpu_must_be_available(self):
        with self.assertRaisesRegex(RuntimeError, 'CPU'):
            self.admit(affinity={0, 1})

    def test_memory_requirement_unchanged(self):
        with self.assertRaisesRegex(RuntimeError, '8 GiB'):
            self.admit(available_memory=8 * 1024**3 - 1)

    def test_native_and_compiler_jobs_block(self):
        for name in ('groops', 'groops-v41', 'segmented-qr', 'cc1plus', 'ninja', 'make'):
            with self.subTest(name=name), self.assertRaisesRegex(RuntimeError, 'preserve it'):
                self.admit([process(10), process(20, name=name)])

    def test_numerical_python_controller_blocks_without_native_child(self):
        with self.assertRaisesRegex(RuntimeError, 'numerical Python'):
            self.admit([process(10), process(20, name='python',
                argv=['python', '/mnt/d/orbit-v4/controls/controller.py'])])

    def test_source_code_argument_is_not_interpreted_as_controller(self):
        self.admit([process(10), process(20, name='python',
            argv=['python', '-c', "print('/mnt/d/orbit-native/run.py')"])])

    def test_only_self_and_ancestry_are_exempt(self):
        self.admit([process(10, 9, 'python'), process(9, 1, 'python',
            ['python', '/mnt/d/orbit-v4/controller.py'])])
        with self.assertRaises(RuntimeError):
            self.admit([process(10), process(20, 10, 'groops')])

    def test_reused_historical_pid_is_not_exempt(self):
        with self.assertRaises(RuntimeError):
            self.admit([process(10), process(29414, name='groops', start_ticks=999999)])

    def test_zombie_is_not_active_workload(self):
        self.admit([process(10), process(20, name='groops', state='Z')])


class ReviewTests(unittest.TestCase):
    def review(self):
        return {'schema': 'orbit-v41-recovery02-launch-review-v1', 'approved': True,
                'freeze_sha256': 'freeze', 'runner_sha256': 'runner', 'launcher_sha256': 'launcher',
                'old_attempt_unchanged': True, 'scientific_settings_unchanged': True, 'all_eight_fresh': True}

    def verify(self, review):
        return r.verify_review(review, freeze_hash='freeze', runner_hash='runner', launcher_hash='launcher')

    def test_exact_review_accepted(self):
        self.verify(self.review())

    def test_each_review_identity_or_assertion_is_required(self):
        for key in self.review():
            changed = self.review()
            changed[key] = False if isinstance(changed[key], bool) else 'different'
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.verify(changed)

    def test_home_inherited_without_mutating_parent_environment(self):
        parent = {'HOME': '/home/emper', 'UNCHANGED': 'yes'}
        before = dict(parent)
        result = r.inherited_environment({'HOME': '/home/emper', 'OMP_NUM_THREADS': '1'}, parent)
        self.assertEqual(parent, before)
        self.assertEqual(result['HOME'], parent['HOME'])
        self.assertEqual(result['OMP_NUM_THREADS'], '1')

    def test_home_mismatch_or_absence_refused(self):
        for parent in ({'HOME': '/other'}, {}):
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                r.inherited_environment({'HOME': '/home/emper'}, parent)


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.controls = self.base / 'validation-controls'
        self.controls.mkdir()
        self.output = self.base / 'attempt'
        self.output.mkdir()
        self.freeze = self.output / 'freeze.json'
        self.freeze.write_text('{}')
        self.audit = self.base / 'review.json'
        self.audit.write_text('{}')
        self.plan = {'cpu': 4, 'output': str(self.output), 'runtime': {'python': {'path': '/pinned/python'}}}
        self.g = SimpleNamespace(SOURCE=Path('/unchanged/candidate04/source'),
            base_env=lambda: {'HOME': '/home/emper', 'OMP_NUM_THREADS': '1'}, run=Mock(return_value=0))
        self.context = []
        for patcher in (patch.object(r, 'ROOT', self.controls), patch.object(r, 'OUTPUT_ROOT', self.base),
                        patch.object(r, 'verified_launch', return_value=(self.g, self.plan)),
                        patch.object(r, 'admission', return_value={'boot_id': 'new'})):
            self.context.append(patcher.start())
            self.addCleanup(patcher.stop)

    def test_detach_uses_regular_file_and_owned_supervision_entrypoint(self):
        def launch(command, **kwargs):
            self.assertTrue(kwargs['start_new_session'])
            self.assertTrue(kwargs['close_fds'])
            self.assertEqual(kwargs['stdin'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], subprocess.STDOUT)
            self.assertEqual(kwargs['cwd'], self.g.SOURCE)
            self.assertEqual(kwargs['stdout'].name, str(self.output / 'detached.log'))
            self.assertTrue((self.output / 'detached.log').is_file())
            self.assertEqual(kwargs['env']['HOME'], '/home/emper')
            self.assertIn('_run', command)
            self.assertEqual(command[0], '/pinned/python')
            return SimpleNamespace(pid=456)
        with patch.object(r.subprocess, 'Popen', side_effect=launch), \
                patch.object(r, 'process_snapshot', return_value=[process(456)]), \
                patch.dict(r.os.environ, {'HOME': '/home/emper'}):
            result = r.launch(self.freeze, 'freeze-hash', self.audit, 'audit-hash')
        self.assertFalse(result['old_results_reused'])
        self.assertFalse(result['release_authority'])
        self.assertFalse((self.output / 'detached-result.json').exists())

    def test_existing_launch_evidence_prevents_relaunch(self):
        for name in ('detached-launch.json', 'detached-started.json', 'detached-result.json', 'detached.log', 'run.lock'):
            protected = self.output / name
            protected.write_text('preserve')
            with self.subTest(name=name), patch.object(r.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(ValueError, 'Preserve existing'):
                    r.launch(self.freeze, 'freeze-hash', self.audit, 'audit-hash')
                popen.assert_not_called()
                self.assertEqual(protected.read_text(), 'preserve')
            protected.unlink()

    def result(self):
        return json.loads((self.output / 'detached-result.json').read_text())

    def test_execution_delegates_to_unchanged_owned_runner(self):
        with patch.object(r.subprocess, 'Popen') as popen:
            self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 0)
            popen.assert_not_called()
        self.g.run.assert_called_once_with(self.freeze, 'f')
        receipt = self.result()
        self.assertEqual(receipt['status'], 'complete')
        self.assertNotIn('cleanup_complete', receipt)
        self.assertFalse(receipt['release_authority'])

    def test_repeated_child_verification_failure_retains_terminal_record(self):
        with patch.object(r, 'verified_launch', side_effect=ValueError('changed input')):
            self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 1)
        self.assertEqual(self.result()['status'], 'failed')
        self.assertIn('changed input', self.result()['error'])
        self.g.run.assert_not_called()

    def test_failed_stage_is_not_passed(self):
        self.g.run.return_value = 1
        self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 1)
        self.assertEqual(self.result()['status'], 'failed')

    def test_interruption_preserved(self):
        self.g.run.side_effect = r.RecoveryInterrupted('test interruption')
        self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 1)
        self.assertEqual(self.result()['status'], 'interrupted')

    def test_runner_caught_wrapper_signal_still_reports_interrupted(self):
        def caught_signal(*_):
            try:
                signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            except BaseException:
                return 1
        self.g.run.side_effect = caught_signal
        self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 1)
        self.assertEqual(self.result()['status'], 'interrupted')
        self.assertEqual(self.result()['signals_received'], [signal.SIGTERM])

    def test_native_supervisor_interruption_is_preserved(self):
        def owned_interruption(*_):
            (self.output / 'result.json').write_text(json.dumps({
                'stages': [{'stage': 'example', 'status': 'interrupted'}]}))
            return 1
        self.g.run.side_effect = owned_interruption
        self.assertEqual(r.execute(self.freeze, 'f', self.audit, 'a'), 1)
        self.assertEqual(self.result()['status'], 'interrupted')
        self.assertEqual(self.result()['signals_received'], [])

    def test_old_output_refused_without_writes(self):
        old = self.base.parent / 'old-attempt' / 'freeze.json'
        with self.assertRaisesRegex(ValueError, 'canonical recovery'):
            r.execute(old, 'f', self.audit, 'a')
        self.g.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
