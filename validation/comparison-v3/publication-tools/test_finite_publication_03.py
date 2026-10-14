import subprocess
import tempfile
import unittest
from pathlib import Path

from run_finite_publication_03 import digest, execute


class FinitePublicationTests(unittest.TestCase):
    def setup_paths(self, root):
        worker = root / 'worker.py'
        worker.write_text('reviewed worker')
        verifier = root / 'completion_handoff_03.py'
        verifier.write_text('reviewed verifier')
        return worker, verifier

    def test_wait_failure_never_publishes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); worker, verifier = self.setup_paths(root); calls = []
            def run(argv, **kwargs):
                calls.append(argv[2]); return subprocess.CompletedProcess(argv, 2)
            result = execute(worker, root / 'repo', root / 'control', digest(worker), digest(verifier), run)
            self.assertEqual(calls, ['--wait-for-bundle'])
            self.assertEqual(result['status'], 'stopped')

    def test_success_is_ordered_and_cannot_be_relaunched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); worker, verifier = self.setup_paths(root); calls = []
            def run(argv, **kwargs):
                calls.append(argv[2]); return subprocess.CompletedProcess(argv, 0)
            args = (worker, root / 'repo', root / 'control', digest(worker), digest(verifier), run)
            self.assertEqual(execute(*args)['status'], 'complete')
            self.assertEqual(calls, ['--wait-for-bundle', '--publish'])
            with self.assertRaisesRegex(ValueError, 'reconciliation'):
                execute(*args)

    def test_changed_verifier_between_steps_blocks_publish(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); worker, verifier = self.setup_paths(root); calls = []
            def run(argv, **kwargs):
                calls.append(argv[2]); verifier.write_text('changed'); return subprocess.CompletedProcess(argv, 0)
            result = execute(worker, root / 'repo', root / 'control', digest(worker), digest(verifier), run)
            self.assertEqual(calls, ['--wait-for-bundle'])
            self.assertEqual(result['status'], 'stopped')
            self.assertIn('changed', result['reason'])


if __name__ == '__main__':
    unittest.main()
