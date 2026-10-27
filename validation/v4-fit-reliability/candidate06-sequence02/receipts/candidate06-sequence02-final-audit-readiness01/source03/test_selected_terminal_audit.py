"""UNEXECUTED stdlib regression source for STA01-STA03; no numerical work.

Run only in a future explicitly granted serial test slot. Archived parser fixtures
are real saved shapes; the reporting tests use in-memory /fixture/ paths, never
invented live-result pins or an imitation native execution receipt. Numerical
reconstruction and terminal_identity are mocked in reporting-only tests.
"""
from pathlib import Path
import copy
import gzip
import hashlib
import importlib.util
import json
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).absolute().parent
SPEC = importlib.util.spec_from_file_location('selected_audit_source03_under_test', HERE/'selected_terminal_audit.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def fixture(name):
    return json.loads((HERE/'fixtures'/name).read_text())


class CompressedRows(unittest.TestCase):
    """Temporary small bytes only; no actual campaign files or numerical arrays."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.raw = Path(self.temp.name)/'qr.1.rows.tsv'
        self.archive = Path(str(self.raw)+'.gz')
        self.payload = b'row\tweight\n1\t0.3\n'
        self.archive.write_bytes(gzip.compress(self.payload, mtime=0))
        self.receipt = {
            'policy': 'verified_row_compression_v1', 'role': 'closed_native_row_provenance',
            'compression_level': 6, 'round_trip_verified': True, 'crc_verified': True,
            'source': {'path': str(self.raw), 'bytes': len(self.payload),
                       'sha256': hashlib.sha256(self.payload).hexdigest()},
            'compressed': self.pin(self.archive),
        }

    @staticmethod
    def pin(path):
        return {'path': str(path), 'bytes': path.stat().st_size,
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}

    def reader(self):
        return audit.Reader({'schema': 'candidate06-terminal-selected-inputs-v1',
                             'sequence_plan_sha256': audit.SEQ_SHA,
                             'files': [copy.deepcopy(self.receipt['compressed'])]})

    def test_missing_raw_is_verified_without_restoration_and_attributed(self):
        reader = self.reader()
        self.assertEqual(reader.nested_pins({'row_compression': [self.receipt]}), [str(self.archive)])
        row = reader.reconstructed_rows[str(self.raw)]
        self.assertEqual(row['source'], self.receipt['source'])
        self.assertEqual(row['verification'], 'streamed_gzip_crc_size_sha256')
        self.assertFalse(row['raw_file_restored'])
        self.assertFalse(row['original_raw_present_and_verified'])
        self.assertFalse(self.raw.exists())
        self.assertNotIn(str(self.raw), reader.consumed)

    def test_existing_raw_must_also_match(self):
        self.raw.write_bytes(b'wrong')
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            self.reader().nested_pins(self.receipt)

    def test_ordinary_missing_pin_still_pending(self):
        with self.assertRaises(audit.Pending):
            self.reader().nested_pins(self.receipt['source'])

    def test_missing_archive_still_pending(self):
        reader = self.reader()
        self.archive.unlink()
        with self.assertRaises(audit.Pending):
            reader.nested_pins(self.receipt)

    def test_archive_hash_and_manifest_identity_are_checked(self):
        reader = self.reader()
        self.archive.write_bytes(gzip.compress(b'other', mtime=0))
        with self.assertRaisesRegex(ValueError, 'hash differs'):
            reader.nested_pins(self.receipt)
        self.receipt['compressed'] = self.pin(self.archive)
        with self.assertRaisesRegex(ValueError, 'manifest pin differs'):
            reader.nested_pins(self.receipt)

    def test_raw_hash_size_and_expansion_must_match(self):
        for key, value in (('sha256', '0'*64), ('bytes', len(self.payload)-1),
                           ('bytes', len(self.payload)+1)):
            with self.subTest(key=key, value=value):
                receipt = copy.deepcopy(self.receipt)
                receipt['source'][key] = value
                with self.assertRaises(ValueError):
                    self.reader().nested_pins(receipt)

    def test_crc_and_truncation_checked_even_when_archive_hash_is_pinned(self):
        original = self.archive.read_bytes()
        corrupt = bytearray(original)
        corrupt[-8] ^= 1
        for data in (bytes(corrupt), original[:-4]):
            with self.subTest(length=len(data)):
                self.archive.write_bytes(data)
                self.receipt['compressed'] = self.pin(self.archive)
                with self.assertRaises((OSError, EOFError)):
                    self.reader().nested_pins(self.receipt)

    def test_policy_flags_extra_fields_and_path_binding_are_not_ignored(self):
        for key, value in (('role', 'other'), ('crc_verified', False),
                           ('round_trip_verified', False), ('unexpected_pin', {}),
                           ('compression_level', True), ('status', 'failed')):
            with self.subTest(key=key):
                receipt = copy.deepcopy(self.receipt)
                receipt[key] = value
                with self.assertRaises(ValueError):
                    self.reader().nested_pins(receipt)
        receipt = copy.deepcopy(self.receipt)
        receipt['source']['path'] += '.different'
        with self.assertRaisesRegex(ValueError, 'path attribution'):
            self.reader().nested_pins(receipt)

    def test_unknown_policy_does_not_authorize_missing_raw(self):
        self.receipt['policy'] = 'unknown_compression'
        with self.assertRaises(audit.Pending):
            self.reader().nested_pins(self.receipt)

    def test_per_archive_and_total_resource_bounds(self):
        with mock.patch.object(audit, 'MAX_ROW_ARCHIVE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'bounded exact pin'):
                self.reader().nested_pins(self.receipt)
        with mock.patch.object(audit, 'MAX_TOTAL_RECONSTRUCTED_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'resource bound'):
                self.reader().nested_pins(self.receipt)

    def test_repeated_receipt_is_not_double_counted_and_conflict_fails(self):
        reader = self.reader()
        reader.nested_pins([self.receipt, self.receipt])
        self.assertEqual(reader.reconstructed_bytes, len(self.payload))
        changed = copy.deepcopy(self.receipt)
        changed['source']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Conflicting reconstructed'):
            reader.nested_pins(changed)


class NativeSchema(unittest.TestCase):
    def test_archived_diagnostic_identity_and_full_status(self):
        path = HERE/'fixtures/native-diagnostics-archived.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), '5ab4e15c87a65bffd4edf5865681657219343e0b22a4210fd6821df818d689c8')
        item = fixture(path.name)
        self.assertEqual(item['rank_status'], 'full')
        audit.native_full_factor(item, 91)

    def test_python_certificate_status_cannot_replace_native_status(self):
        for status in ('full_rank', 'deficient', 'unresolved', 'conditional', 'unknown'):
            with self.subTest(status=status):
                item = fixture('native-diagnostics-archived.json')
                item['rank_status'] = status
                with self.assertRaises(ValueError):
                    audit.native_full_factor(item, 91)

    def test_wrong_schema_damping_and_incomplete_dimension_remain_rejected(self):
        for key, value in (('schema', 'python-rank-certificate'), ('lambda', 0.001), ('rank', 90), ('retained_parameters', 90)):
            with self.subTest(key=key):
                item = fixture('native-diagnostics-archived.json')
                item[key] = value
                with self.assertRaises(ValueError):
                    audit.native_full_factor(item, 91)


class PlaceholderSchema(unittest.TestCase):
    def test_real_unlaunched_shape_is_pending_before_any_pin_access(self):
        row = fixture('unlaunched-gate-archived.json')
        self.assertEqual(set(row), {'stage', 'status'})
        reader = mock.Mock()
        with self.assertRaisesRegex(audit.Pending, 'without receipt'):
            audit.gate_stage(reader, {'stage': row['stage']}, row, {}, {})
        reader.read.assert_not_called()

    def test_explicit_failed_attempt_is_failed_before_optional_pin_access(self):
        for status in ('failed', 'timeout', 'interrupted', 'memory_limit', 'resource_limit'):
            with self.subTest(status=status):
                with self.assertRaisesRegex(ValueError, 'Recorded unsuccessful attempt'):
                    audit.gate_stage(mock.Mock(), {'stage': 'native-tests'}, {'stage': 'native-tests', 'status': status}, {}, {})

    def test_malformed_claimed_pass_is_distinct_from_unlaunched(self):
        with self.assertRaisesRegex(ValueError, 'Claimed passed gate lacks required receipt fields'):
            audit.gate_stage(mock.Mock(), {'stage': 'native-tests'}, {'stage': 'native-tests', 'status': 'passed'}, {}, {})

    def test_absent_outcome_remains_pending(self):
        with self.assertRaises(audit.Pending):
            audit.require_attempt_receipt(None)


class MemoryReader:
    """No disk artifact reads, hashing or native imports in reporting fixtures."""
    def __init__(self, documents):
        self.documents = documents

    def read(self, item):
        path = item['path'] if isinstance(item, dict) else str(item)
        if path not in self.documents:
            raise audit.Pending('Unit fixture intentionally has no receipt: '+path)
        value = self.documents[path]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def verify(self, item):
        raise AssertionError('Reporting-only fixture must not claim artifact verification')


def mock_pin(label):
    # Only consumed by MemoryReader or equality comparisons. Not a real pin and
    # never written to a production manifest; Reader.pin_shape would reject it.
    return {'path': '/fixture/'+label, 'sha256': 'mock-identity-not-a-file-hash'}


def reporting_fixture(gate_mode='passed', cold_mode='passed'):
    plan = {key: mock_pin(key) for key in ('gate_freeze', 'gate_review', 'cold_freeze', 'cold_review')}
    gate_plan_pin = mock_pin('gate-plan')
    context = {'plan': plan, 'terminal': {
        'status': 'complete' if gate_mode == cold_mode == 'passed' else 'failed',
        'returncode': 0 if gate_mode == cold_mode == 'passed' else 1,
        'phase': 'finished', 'error': None if gate_mode == cold_mode == 'passed' else 'Fixture failure',
        'signals_received': [], 'phase_receipt_errors': [],
    }}
    documents = {
        str(audit.GATES/'plan.json'): {'schema': 'orbit-poc-candidate06-correctness-plan-v2', 'stages': list(audit.STAGES), 'jobs': [{'stage': s} for s in audit.STAGES]},
        str(audit.GATES/'freeze.json'): {'plan': gate_plan_pin},
        str(audit.COLD/'plan.json'): {'jobs': [{'stage': s} for s in audit.COLD_STAGES]},
    }
    gate_rows = [{'stage': stage, 'status': 'passed'} for stage in audit.STAGES]
    if gate_mode == 'failed':
        gate_rows = [{'stage': stage, 'status': 'failed' if i == 0 else audit.UNLAUNCHED_STATUS} for i, stage in enumerate(audit.STAGES)]
    documents[str(audit.GATES/'result.json')] = {
        'planned_stages': list(audit.STAGES), 'plan': gate_plan_pin, 'freeze': plan['gate_freeze'],
        'stages': gate_rows, 'all_eleven_strict_passed': gate_mode == 'passed',
    }
    documents[str(audit.GATES/'detached-result.json')] = {
        'freeze_sha256': plan['gate_freeze']['sha256'], 'review_sha256': plan['gate_review']['sha256'],
        'status': 'complete' if gate_mode == 'passed' else 'failed',
        'returncode': 0 if gate_mode == 'passed' else 1,
        'error': None if gate_mode == 'passed' else 'Fixture failed gate', 'signals_received': [],
    }
    cold_rows = []
    for i, stage in enumerate(audit.COLD_STAGES):
        status = 'passed' if cold_mode == 'passed' else ('failed' if i == 0 else audit.UNLAUNCHED_STATUS)
        strict_pin = mock_pin(stage+'-strict')
        supervisor_pin = mock_pin(stage+'-supervisor')
        row = {'stage': stage, 'status': status}
        if status != audit.UNLAUNCHED_STATUS:
            row.update(strict_result=strict_pin, supervisor=supervisor_pin)
            documents[strict_pin['path']] = {'status': status, 'accepted_covariance': status == 'passed'}
            documents[supervisor_pin['path']] = {'status': 'complete' if status == 'passed' else 'failed', 'returncode': 0 if status == 'passed' else 1}
            documents[str(audit.COLD/stage/'backend-result.json')] = {'status': 'complete' if status == 'passed' else 'failed', 'covariance_valid': status == 'passed', 'artifacts': []}
        cold_rows.append(row)
    documents[str(audit.COLD/'result.json')] = {'planned_stages': list(audit.COLD_STAGES), 'freeze_sha256': plan['cold_freeze']['sha256'], 'stages': cold_rows, 'status': 'passed' if cold_mode == 'passed' else 'failed'}
    documents[str(audit.COLD/'detached-result.json')] = {'freeze_sha256': plan['cold_freeze']['sha256'], 'audit_sha256': plan['cold_review']['sha256'], 'status': 'complete' if cold_mode == 'passed' else 'failed', 'returncode': 0 if cold_mode == 'passed' else 1, 'error': None if cold_mode == 'passed' else 'Fixture failed cold fit', 'signals_received': []}
    for mode, root in ((gate_mode, audit.GATES), (cold_mode, audit.COLD)):
        if mode == 'incomplete':
            documents.pop(str(root/'result.json'))
            documents.pop(str(root/'detached-result.json'))
    return context, documents


def checked_stage_stub(reader, job, row, *args):
    audit.require_attempt_receipt(row)
    return {'stage': job['stage'], 'recorded_status': row['status'], 'selected_checks_completed': True}


def checked_cold_stub(reader, stage, job, row):
    audit.require_attempt_receipt(row)
    return {'stage': stage, 'recorded_status': row['status'], 'selected_checks_completed': True}


class PlannedLedger(unittest.TestCase):
    def evaluate(self, context, documents):
        with mock.patch.object(audit, 'terminal_identity', return_value=context), mock.patch.object(audit, 'gate_stage', side_effect=checked_stage_stub), mock.patch.object(audit, 'cold_selected', side_effect=checked_cold_stub) as cold_check:
            result = audit.audit(MemoryReader(documents))
            return result, cold_check.call_count

    def inventory(self, result):
        self.assertEqual([r['stage'] for r in result['gates']], list(audit.STAGES))
        self.assertEqual([r['stage'] for r in result['cold']], list(audit.COLD_STAGES))

    def test_nine_passed_failed_incomplete_phase_combinations_keep_inventory(self):
        for gate_mode in ('passed', 'failed', 'incomplete'):
            for cold_mode in ('passed', 'failed', 'incomplete'):
                with self.subTest(gate=gate_mode, cold=cold_mode):
                    context, documents = reporting_fixture(gate_mode, cold_mode)
                    result, calls = self.evaluate(context, documents)
                    self.inventory(result)
                    if gate_mode == cold_mode == 'passed':
                        self.assertEqual(result['errors'], [])
                        self.assertEqual(calls, 2)
                    else:
                        self.assertTrue(result['errors'])
                        self.assertEqual(calls, 0)
                    if gate_mode == 'failed':
                        self.assertEqual(result['gates'][0]['audit_status'], 'failed')
                        self.assertEqual(result['gates'][0]['recorded_status'], 'failed')
                        self.assertTrue(all(r['audit_status'] == 'pending' and r['recorded_status'] == audit.UNLAUNCHED_STATUS for r in result['gates'][1:]))
                    if gate_mode == 'incomplete':
                        self.assertTrue(all(r['audit_status'] == 'pending' and r['recorded_status'] is None for r in result['gates']))
                    if cold_mode == 'failed':
                        self.assertEqual(result['cold'][0]['audit_status'], 'failed')
                        self.assertEqual(result['cold'][0]['recorded_status'], 'failed')
                        self.assertEqual(result['cold'][1]['audit_status'], 'pending')
                        self.assertEqual(result['cold'][1]['recorded_status'], audit.UNLAUNCHED_STATUS)

    def test_each_missing_phase_file_keeps_available_rows_and_blocks_cold_selection(self):
        for root in (audit.GATES, audit.COLD):
            for filename in ('result.json', 'detached-result.json'):
                with self.subTest(root=str(root), filename=filename):
                    context, documents = reporting_fixture()
                    documents.pop(str(root/filename))
                    result, calls = self.evaluate(context, documents)
                    self.inventory(result)
                    self.assertEqual(calls, 0)
                    self.assertTrue(result['errors'])
                    if filename == 'detached-result.json':
                        selected = result['gates'] if root == audit.GATES else result['cold']
                        self.assertTrue(all(r['recorded_status'] == 'passed' for r in selected))

    def test_failed_detached_does_not_erase_successful_or_failed_recorded_rows(self):
        context, documents = reporting_fixture()
        documents[str(audit.GATES/'detached-result.json')].update(status='interrupted', returncode=1, signals_received=[15])
        result, calls = self.evaluate(context, documents)
        self.inventory(result)
        self.assertEqual(calls, 0)
        self.assertTrue(all(r['recorded_status'] == 'passed' for r in result['gates']))
        self.assertTrue(any(e.get('phase') == 'correctness' and e.get('recorded_status') == 'interrupted' for e in result['errors']))

    def test_changed_aggregate_attribution_is_failed_phase_with_pending_attempts(self):
        context, documents = reporting_fixture()
        documents[str(audit.GATES/'result.json')]['plan'] = mock_pin('wrong-plan')
        result, calls = self.evaluate(context, documents)
        self.inventory(result)
        self.assertEqual(calls, 0)
        self.assertTrue(all(r['audit_status'] == 'pending' for r in result['gates']))
        self.assertEqual(result['phase_evidence']['correctness/result.json']['audit_status'], 'failed')

    def test_archived_mixed_cold_outcome_preserves_pass_and_failure_separately(self):
        context, documents = reporting_fixture()
        archived = fixture('cold-outcomes-archived.json')
        aggregate = documents[str(audit.COLD/'result.json')]
        aggregate['status'] = archived['status']
        for row, old in zip(aggregate['stages'], archived['stages']):
            self.assertEqual(row['stage'], old['stage'])
            row['status'] = old['status']
            documents[row['strict_result']['path']]['status'] = old['status']
        documents[str(audit.COLD/'detached-result.json')].update(status='failed', returncode=1, error='Fixture density failure')
        result, calls = self.evaluate(context, documents)
        self.inventory(result)
        self.assertEqual(calls, 1)
        self.assertTrue(result['cold'][0]['selected_checks_completed'])
        self.assertEqual(result['cold'][0]['recorded_status'], 'passed')
        self.assertEqual(result['cold'][1]['recorded_status'], 'failed')
        self.assertEqual(result['cold'][1]['audit_status'], 'failed')
        self.assertTrue(any(e.get('phase') == 'cold' for e in result['errors']))

    def test_malformed_phase_document_retains_all_attempts(self):
        context, documents = reporting_fixture()
        documents[str(audit.GATES/'result.json')] = {'planned_stages': list(audit.STAGES)}
        result, calls = self.evaluate(context, documents)
        self.inventory(result)
        self.assertEqual(calls, 0)
        self.assertEqual(result['phase_evidence']['correctness/result.json']['audit_status'], 'failed')


if __name__ == '__main__':
    unittest.main()
