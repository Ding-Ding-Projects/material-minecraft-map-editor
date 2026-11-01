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


if __name__ == "__main__": unittest.main()
