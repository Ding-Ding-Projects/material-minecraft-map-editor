"""Negative regressions for complete, fail-closed process enumeration."""

import ctypes
import os
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from native.tests import process_snapshot


class NativeFunction:
    def __init__(self, action): self.action = action
    def __call__(self, *args): return self.action(*args)


class FakeKernel:
    def __init__(self, rows, first_error=None, terminal_error=18, close_ok=True):
        self.rows = rows
        self.first_error = first_error
        self.terminal_error = terminal_error
        self.close_ok = close_ok
        self.index = 0
        self.closed = False
        self.CreateToolhelp32Snapshot = NativeFunction(lambda flags, pid: 1234)
        self.Process32FirstW = NativeFunction(self.first)
        self.Process32NextW = NativeFunction(self.next)
        self.CloseHandle = NativeFunction(self.close)

    def write(self, pointer):
        entry = pointer._obj
        entry.pid, entry.parent, entry.exe = self.rows[self.index]
        return 1

    def first(self, handle, pointer):
        if self.first_error is not None:
            ctypes.set_last_error(self.first_error)
            return 0
        if not self.rows:
            ctypes.set_last_error(18)
            return 0
        return self.write(pointer)

    def next(self, handle, pointer):
        self.index += 1
        if self.index == len(self.rows):
            ctypes.set_last_error(self.terminal_error)
            return 0
        return self.write(pointer)

    def close(self, handle):
        self.closed = True
        if not self.close_ok: ctypes.set_last_error(6)
        return int(self.close_ok)


@unittest.skipUnless(os.name == "nt", "Native Windows last-error semantics required")
class ProcessSnapshotTests(unittest.TestCase):
    def invoke(self, kernel, names=False):
        with patch.object(process_snapshot.ctypes, "WinDLL", return_value=kernel):
            return process_snapshot.snapshot(names)

    def test_complete_enumeration_requires_normal_terminal_code(self):
        kernel = FakeKernel([(os.getpid(), 7, "python.exe"), (42, os.getpid(), "engine.exe")])
        self.assertEqual(self.invoke(kernel), {os.getpid(): 7, 42: os.getpid()})
        self.assertTrue(kernel.closed)

    def test_first_call_error_cannot_be_an_empty_absence_proof(self):
        for error in (0, 5, 6):
            with self.subTest(error=error):
                kernel = FakeKernel([], first_error=error)
                with self.assertRaises(OSError): self.invoke(kernel)
                self.assertTrue(kernel.closed)

    def test_partial_enumeration_cannot_prove_a_missing_process_absent(self):
        # The observer appears, but the remaining process list was not read.
        # Returning this dictionary would falsely prove PID 999999 absent.
        kernel = FakeKernel([(os.getpid(), 7, "python.exe")], terminal_error=5)
        with self.assertRaises(OSError):
            tree = self.invoke(kernel)
            self.assertNotIn(999999, tree)
        self.assertTrue(kernel.closed)

    def test_zero_last_error_on_next_is_not_normal_completion(self):
        with self.assertRaises(OSError):
            self.invoke(FakeKernel([(os.getpid(), 7, "python.exe")], terminal_error=0))

    def test_missing_observer_and_empty_inventory_fail_closed(self):
        for rows in ([], [(42, 7, "other.exe")]):
            with self.assertRaises(RuntimeError): self.invoke(FakeKernel(rows))

    def test_duplicate_pid_and_failed_handle_release_fail_closed(self):
        with self.assertRaises(RuntimeError):
            self.invoke(FakeKernel([(os.getpid(), 7, "python.exe"), (os.getpid(), 8, "other.exe")]))
        with self.assertRaises(OSError):
            self.invoke(FakeKernel([(os.getpid(), 7, "python.exe")], close_ok=False))

    def test_names_route_has_same_completeness_requirement(self):
        self.assertEqual(self.invoke(FakeKernel([(os.getpid(), 7, "python.exe")]), True),
                         {os.getpid(): (7, "python.exe")})
        with self.assertRaises(OSError):
            self.invoke(FakeKernel([(os.getpid(), 7, "python.exe")], terminal_error=5), True)

    def test_real_snapshot_contains_this_observer(self):
        self.assertIn(os.getpid(), process_snapshot.snapshot())

    def test_real_query_handle_binds_creation_time_and_executable(self):
        first = process_snapshot.process_identity(os.getpid())
        second = process_snapshot.process_identity(os.getpid())
        self.assertEqual(first, second)
        self.assertGreater(first["creationTimeFileTime"], 0)
        self.assertTrue(Path(first["imagePath"]).is_absolute())
        self.assertTrue(Path(first["imagePath"]).is_file())

    def test_failure_evidence_is_retained_verified_and_bounded(self):
        from native.tests.accept_terrain_engine import preserve_failure_evidence, MAX_RECEIPT_BYTES, PRESERVED_FAILURES
        with tempfile.TemporaryDirectory(prefix='mwe-retention-regression-') as directory:
            root = Path(directory)
            receipt = {'schemaVersion': 1, 'verified': False, 'reason': 'deliberate enumeration failure'}
            retained = preserve_failure_evidence(root, receipt, {'region/example.mca': b'bounded synthetic input'})
            self.assertTrue(root.exists())
            self.assertEqual((root / 'fixture-before/region/example.mca').read_bytes(), b'bounded synthetic input')
            encoded = (root / 'failure-receipt.json').read_bytes()
            self.assertLessEqual(len(encoded), MAX_RECEIPT_BYTES)
            self.assertEqual(json.loads(encoded), receipt)
            self.assertEqual(retained['fixtureBytes'], len(b'bounded synthetic input'))
            with self.assertRaises(FileExistsError): preserve_failure_evidence(root, receipt, {})
            PRESERVED_FAILURES[:] = [r for r in PRESERVED_FAILURES if r['root'] != str(root.resolve())]

    def test_overbudget_evidence_is_rejected_before_writing(self):
        from native.tests.accept_terrain_engine import preserve_failure_evidence, MAX_FIXTURE_EVIDENCE_BYTES, MAX_RECEIPT_BYTES
        with tempfile.TemporaryDirectory(prefix='mwe-retention-bound-') as directory:
            root = Path(directory)
            with self.assertRaises(AssertionError):
                preserve_failure_evidence(root, {}, {'fixture': b'x' * (MAX_FIXTURE_EVIDENCE_BYTES + 1)})
            with self.assertRaises(AssertionError):
                preserve_failure_evidence(root, {'tooLarge': 'x' * MAX_RECEIPT_BYTES}, {})
            self.assertEqual(list(root.iterdir()), [])

    def test_current_parent_graph_does_not_claim_unobserved_orphans(self):
        # Parent 20 exited before this snapshot. PID 30 cannot be connected
        # back to PID 10 from these observations, despite being its descendant.
        self.assertEqual(process_snapshot.descendants(10, {30: 20}), set())
        from native.tests.accept_terrain_engine import RECEIPT_SCOPE
        self.assertIn('historical orphan descendants are not verified', RECEIPT_SCOPE)

    def test_failed_case_cleanup_keeps_original_fixture_and_receipt(self):
        from native.tests.accept_terrain_engine import TerrainEngineAcceptance, world_hashes, PRESERVED_FAILURES
        with tempfile.TemporaryDirectory(prefix='mwe-failed-case-regression-') as directory:
            case = TerrainEngineAcceptance('test_present_scene_real_stream_and_source_preservation')
            case.owned_root = Path(directory).resolve()
            case.world = case.owned_root / 'world'
            case.world.mkdir()
            (case.world / 'level.dat').write_bytes(b'synthetic fixture')
            case.before = world_hashes(case.world)
            case._fixture_before = {'level.dat': b'synthetic fixture'}
            case._case_verified = False
            case.receipt = {'pid': None, 'finished': False}
            case._finish_owned_case()
            self.assertTrue(case.owned_root.exists())
            self.assertEqual((case.world / 'level.dat').read_bytes(), b'synthetic fixture')
            self.assertEqual((case.owned_root / 'fixture-before/level.dat').read_bytes(), b'synthetic fixture')
            receipt = json.loads((case.owned_root / 'failure-receipt.json').read_text())
            self.assertFalse(receipt['verified'])
            self.assertEqual(receipt['phaseBeforeCleanup'], 'setup')
            PRESERVED_FAILURES[:] = [r for r in PRESERVED_FAILURES if r['root'] != str(case.owned_root)]


@unittest.skipUnless(os.name == 'nt', 'Native console-host identity contract required')
class ConsoleHostReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtCore import QCoreApplication
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        from native.tests import accept_terrain_engine
        self.acceptance = accept_terrain_engine
        self.temporary = tempfile.TemporaryDirectory(prefix='mwe-console-receipt-')
        self.root = Path(self.temporary.name)
        self.engine = self.root / 'engine.exe'; self.engine.write_bytes(b'not executable test data')
        self.system = self.root / 'system'; self.system.mkdir()
        self.host = self.system / 'conhost.exe'; self.host.write_bytes(b'not executable test data')
        self.engine_pid, self.host_pid = 2000000001, 2000000002
        self.tree = {os.getpid(): 0, self.engine_pid: os.getpid(), self.host_pid: self.engine_pid}
        self.identities = {
            self.engine_pid: {'pid': self.engine_pid, 'creationTimeFileTime': 100, 'imagePath': str(self.engine)},
            self.host_pid: {'pid': self.host_pid, 'creationTimeFileTime': 101, 'imagePath': str(self.host)},
        }

    def tearDown(self): self.temporary.cleanup()

    def admitted(self):
        with patch.object(self.acceptance, 'ENGINE', self.engine), \
             patch.object(self.acceptance, 'snapshot', return_value=self.tree), \
             patch.object(self.acceptance, 'process_identity', side_effect=lambda pid: self.identities[pid]), \
             patch.object(self.acceptance, 'system_directory', return_value=str(self.system)):
            receipt = self.acceptance.child_start_receipt(self.engine_pid)
        receipt['finished'] = True
        return receipt

    def test_known_system_host_requires_path_parent_and_creation_identity(self):
        receipt = self.admitted()
        self.assertEqual(receipt['initialObservedReachableChildren'], 1)
        self.assertEqual(receipt['observedConsoleHosts'], [{
            'pid': self.host_pid, 'parentPid': self.engine_pid, 'creationTimeFileTime': 101,
            'imagePathMatchesSystemConsoleHost': True,
        }])

    def test_same_basename_outside_system_directory_is_rejected(self):
        other = self.root / 'conhost.exe'; other.write_bytes(b'not executable test data')
        self.identities[self.host_pid]['imagePath'] = str(other)
        with self.assertRaises(AssertionError): self.admitted()

    def test_unexpected_nested_child_or_older_identity_is_rejected(self):
        self.tree[2000000003] = self.host_pid
        with self.assertRaises(AssertionError): self.admitted()
        del self.tree[2000000003]
        self.identities[self.host_pid]['creationTimeFileTime'] = 99
        with self.assertRaises(AssertionError): self.admitted()

    def test_observed_host_exit_is_required_after_engine_exit(self):
        receipt = self.admitted()
        remaining = {os.getpid(): 0, self.host_pid: self.engine_pid}
        with patch.object(self.acceptance, 'snapshot', return_value=remaining), \
             patch.object(self.acceptance, 'process_identity', side_effect=lambda pid: self.identities[pid]):
            result = self.acceptance.process_exit_observation(receipt)
            self.assertFalse(result['complete'])
            self.assertEqual(result['consoleHosts'][0]['state'], 'still-running')
            with self.assertRaises(AssertionError):
                self.acceptance.assert_process_absent(self, receipt, milliseconds=1)
        with patch.object(self.acceptance, 'snapshot', return_value={os.getpid(): 0}):
            result = self.acceptance.process_exit_observation(receipt)
            self.assertTrue(result['complete'])
            self.assertFalse(result['historicalOrphansVerified'])

    def test_host_pid_reuse_is_reported_without_touching_replacement(self):
        receipt = self.admitted()
        replacement = dict(self.identities[self.host_pid], creationTimeFileTime=202,
                           imagePath=str(self.root / 'unrelated-replacement.exe'))
        with patch.object(self.acceptance, 'snapshot', return_value={os.getpid(): 0, self.host_pid: 77}), \
             patch.object(self.acceptance, 'process_identity', return_value=replacement) as query:
            result = self.acceptance.process_exit_observation(receipt)
            self.assertTrue(result['complete'])
            self.assertTrue(result['consoleHosts'][0]['pidReused'])
            self.assertEqual(result['consoleHosts'][0]['replacementCreationTimeFileTime'], 202)
            query.assert_called_once_with(self.host_pid)

    def test_engine_pid_reuse_is_not_reported_as_pid_absence(self):
        receipt = self.admitted()
        replacement = dict(self.identities[self.engine_pid], creationTimeFileTime=303,
                           imagePath=str(self.root / 'unrelated-replacement.exe'))
        with patch.object(self.acceptance, 'snapshot', return_value={os.getpid(): 0, self.engine_pid: 77}), \
             patch.object(self.acceptance, 'process_identity', return_value=replacement):
            result = self.acceptance.process_exit_observation(receipt)
            self.assertTrue(result['complete'])
            self.assertEqual(result['engine']['state'], 'pid-reused')
            self.assertTrue(result['engine']['originalIdentityAbsent'])
            self.assertTrue(result['engine']['pidReused'])

    def test_new_unexpected_child_at_exit_fails_closed(self):
        receipt = self.admitted()
        with patch.object(self.acceptance, 'snapshot', return_value={os.getpid(): 0, 2000000003: self.engine_pid}):
            with self.assertRaises(AssertionError): self.acceptance.process_exit_observation(receipt)

    def test_query_error_requires_complete_resnapshot_absence(self):
        receipt = self.admitted()
        remaining = {os.getpid(): 0, self.host_pid: self.engine_pid}
        with patch.object(self.acceptance, 'snapshot', side_effect=[remaining, {os.getpid(): 0}]), \
             patch.object(self.acceptance, 'process_identity', side_effect=OSError(87, 'query raced exit')):
            self.assertTrue(self.acceptance.process_exit_observation(receipt)['complete'])
        with patch.object(self.acceptance, 'snapshot', return_value=remaining), \
             patch.object(self.acceptance, 'process_identity', side_effect=OSError(5, 'identity unavailable')):
            with self.assertRaises(OSError): self.acceptance.process_exit_observation(receipt)

    def test_poll_callback_error_cannot_disappear_before_final_observation(self):
        calls = []
        def predicate():
            calls.append(len(calls) + 1)
            if len(calls) == 1: return False
            if len(calls) == 2: raise AssertionError('unexpected observed child')
            return True
        with self.assertRaisesRegex(AssertionError, 'unexpected observed child'):
            self.acceptance.wait_for(predicate, 100)

    def test_actual_system_directory_api_returns_existing_console_host(self):
        path = Path(process_snapshot.system_directory())
        self.assertTrue(path.is_absolute())
        self.assertTrue((path / 'conhost.exe').is_file())


if __name__ == "__main__": unittest.main()
