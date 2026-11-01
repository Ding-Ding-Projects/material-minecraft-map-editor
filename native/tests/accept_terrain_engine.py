"""Explicit native terrain acceptance against the actual compiled engine.

Run from the repository root with an explicitly selected MWE_TEST_REFERENCE_ROOT:
    native/.venv/Scripts/python.exe -m unittest native.tests.accept_terrain_engine -v

This module intentionally does not match ordinary test discovery. Missing inputs,
missing terrain methods and unsupported hosts fail; they never become skipped
successes. It creates no window, render surface, synthetic frame receipt or GPU
result. Fixtures are generated in an owned temporary directory, not product data.
"""

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import unittest

from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QSettings, QTimer

from native.amulet_native.engine_coordinator import EngineCoordinator
from native.amulet_native.framing import Decoder, encode_request
from native.amulet_native.references import ReferenceSettings
from native.amulet_native.terrain_scene import TerrainRequest
from native.amulet_native.terrain_session import TerrainSession
from native.tests.chunk_fixture import write_terrain_world
from native.tests.process_snapshot import snapshot, descendants, process_identity, system_directory


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine" / "target" / "debug" / "material-world-engine.exe"
REFERENCE_FILES = (
    "reports/blocks.json", "reports/registries.json",
    "registry-source-receipt.json", "java-geometry-reference-evidence.json",
)
TERRAIN_METHODS = ("world.terrain_begin", "world.terrain_page", "world.terrain_end")
ACCEPTANCE_RECEIPTS = []
PRESERVED_FAILURES = []
UNACKNOWLEDGED_OWNED_PROCESSES = []
MAX_FIXTURE_EVIDENCE_BYTES = 1024 * 1024
MAX_RECEIPT_BYTES = 65536
RECEIPT_SCOPE = "Owned QProcess exit plus a complete point-in-time process inventory; historical orphan descendants are not verified"


def record_receipt(receipt):
    ACCEPTANCE_RECEIPTS.append(receipt)
    del ACCEPTANCE_RECEIPTS[:-8]


def preserve_failure_evidence(root, receipt, fixture_before):
    """Retain at most 1 MiB of original fixture bytes and a 64 KiB receipt.

    The existing failed-run directory stays intact. Unexpected changed files
    are never copied without bounds or deleted to manufacture a small result.
    """
    info = root.stat(follow_symlinks=False)
    if (root.is_symlink() or not stat.S_ISDIR(info.st_mode)
            or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise AssertionError("Failure evidence root is not an owned directory")
    root = root.resolve(strict=True)
    if len(fixture_before) > 16 or sum(len(value) for value in fixture_before.values()) > MAX_FIXTURE_EVIDENCE_BYTES:
        raise AssertionError("Original fixture evidence exceeds the retention bound")
    for name, value in fixture_before.items():
        parts = PurePosixPath(name)
        if (not isinstance(value, bytes) or parts.is_absolute() or ':' in name or '\\' in name
                or any(part in ('', '.', '..') for part in name.split('/'))):
            raise AssertionError("Unsafe fixture evidence path or value")
    encoded = json.dumps(receipt, ensure_ascii=True, allow_nan=False, sort_keys=True).encode('utf-8')
    if len(encoded) > MAX_RECEIPT_BYTES:
        raise AssertionError("Failure receipt exceeds its retention bound")
    copies = root / 'fixture-before'
    copies.mkdir(exist_ok=False)
    for name, value in fixture_before.items():
        destination = copies.joinpath(*PurePosixPath(name).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(value)
        if file_hash(destination, MAX_FIXTURE_EVIDENCE_BYTES)['sha256'] != hashlib.sha256(value).hexdigest():
            raise AssertionError("Preserved fixture copy failed its hash readback")
    output = root / 'failure-receipt.json'
    with output.open('xb') as handle:
        handle.write(encoded)
    if output.read_bytes() != encoded:
        raise AssertionError("Failure receipt readback differs from its source")
    retained = {'root': str(root), 'receiptSha256': hashlib.sha256(encoded).hexdigest(),
                'fixtureBytes': sum(len(value) for value in fixture_before.values())}
    PRESERVED_FAILURES.append(retained)
    del PRESERVED_FAILURES[:-8]
    return retained


def child_start_receipt(pid):
    identity = process_identity(pid)
    expected = os.path.normcase(str(ENGINE.resolve(strict=True)))
    observed = os.path.normcase(str(Path(identity['imagePath']).resolve(strict=True)))
    if observed != expected:
        raise AssertionError("Owned process executable does not match the compiled engine")
    tree = snapshot()
    if tree.get(pid) != os.getpid():
        raise AssertionError("Compiled engine was not observed as a direct child")
    hosts = observed_console_hosts(pid, identity['creationTimeFileTime'], tree)
    return {'pid': pid, 'creationTimeFileTime': identity['creationTimeFileTime'],
            'imagePathMatchesEngine': True, 'parentMatched': True,
            'initialObservedReachableChildren': len(hosts), 'observedConsoleHosts': hosts}


def observed_console_hosts(engine_pid, engine_created, tree):
    """Admit only the observed direct OS console host, never arbitrary children."""
    children = sorted(descendants(engine_pid, tree))
    if len(children) > 1:
        raise AssertionError('Unexpected number of observed engine children')
    expected = os.path.normcase(str((Path(system_directory()) / 'conhost.exe').resolve(strict=True)))
    hosts = []
    for pid in children:
        if tree.get(pid) != engine_pid:
            raise AssertionError('An observed engine child is not a direct console host')
        identity = process_identity(pid)
        observed = os.path.normcase(str(Path(identity['imagePath']).resolve(strict=True)))
        if observed != expected:
            raise AssertionError('Unexpected child executable; only the actual system console host is admitted')
        if identity['creationTimeFileTime'] < engine_created:
            raise AssertionError('Console-host creation identity predates the owned engine')
        hosts.append({'pid': pid, 'parentPid': engine_pid,
                      'creationTimeFileTime': identity['creationTimeFileTime'],
                      'imagePathMatchesSystemConsoleHost': True})
    return hosts


def process_exit_observation(receipt):
    """Compare recorded identities, reporting PID reuse without touching replacements."""
    if (not receipt.get('finished') or not receipt.get('imagePathMatchesEngine')
            or type(receipt.get('pid')) is not int or not 1 <= receipt['pid'] <= 2**32 - 1
            or type(receipt.get('creationTimeFileTime')) is not int
            or receipt['creationTimeFileTime'] <= 0):
        raise AssertionError('Recorded engine identity or QProcess exit acknowledgement is incomplete')
    hosts = receipt.get('observedConsoleHosts')
    if (not isinstance(hosts, list) or len(hosts) > 1
            or type(receipt.get('initialObservedReachableChildren')) is not int
            or receipt.get('initialObservedReachableChildren') != len(hosts)):
        raise AssertionError('Observed child inventory is incomplete')
    tree = snapshot()

    def gone(record):
        pid = record['pid']
        if pid not in tree:
            return {'pid': pid, 'state': 'absent', 'originalIdentityAbsent': True, 'pidReused': False}
        try:
            current = process_identity(pid)
        except OSError:
            # An exit may race the query. Absence requires another complete
            # inventory, not treating the query error itself as success.
            if pid not in snapshot():
                return {'pid': pid, 'state': 'absent-after-resnapshot', 'originalIdentityAbsent': True, 'pidReused': False}
            raise
        if current['creationTimeFileTime'] != record['creationTimeFileTime']:
            return {'pid': pid, 'state': 'pid-reused', 'originalIdentityAbsent': True, 'pidReused': True,
                    'replacementCreationTimeFileTime': current['creationTimeFileTime']}
        return {'pid': pid, 'state': 'still-running', 'originalIdentityAbsent': False, 'pidReused': False}

    engine = gone(receipt)
    tracked = set()
    observations = []
    for host in hosts:
        if (host.get('parentPid') != receipt['pid'] or host.get('imagePathMatchesSystemConsoleHost') is not True
                or type(host.get('pid')) is not int or not 1 <= host['pid'] <= 2**32 - 1
                or host['pid'] == receipt['pid']
                or type(host.get('creationTimeFileTime')) is not int or host['creationTimeFileTime'] <= 0
                or host.get('pid') in tracked):
            raise AssertionError('Recorded console-host identity is invalid')
        tracked.add(host['pid'])
        observations.append(gone(host))
    reachable = descendants(receipt['pid'], tree)
    if reachable - tracked:
        raise AssertionError('Unexpected observed child remains after engine exit')
    if engine['pidReused'] and reachable:
        raise AssertionError('Parent links under a reused engine PID cannot be attributed safely')
    return {'completeInventory': True, 'observerSeen': os.getpid() in tree,
            'engine': engine, 'consoleHosts': observations,
            'complete': engine['originalIdentityAbsent'] and all(item['originalIdentityAbsent'] for item in observations),
            'observedReachableChildren': len(reachable), 'historicalOrphansVerified': False}


def wait_for_process_exit_observation(receipt, milliseconds=3000):
    observations = {}
    def complete():
        observations['latest'] = process_exit_observation(receipt)
        receipt['exitObservation'] = observations['latest']
        return observations['latest']['complete']
    wait_for(complete, milliseconds)
    return observations['latest']


def wait_for(predicate, milliseconds=35000):
    """One bounded Qt-core wait. Never substitutes sleeping or a GUI loop."""
    if not 1 <= milliseconds <= 35000:
        raise ValueError("Acceptance waits must be at most 35 seconds")
    if predicate():
        return
    loop = QEventLoop()
    poll = QTimer()
    poll.setInterval(5)
    deadline = QTimer()
    deadline.setSingleShot(True)
    failure = []
    def check():
        try:
            if predicate(): loop.quit()
        except BaseException as error:
            failure.append(error)
            loop.quit()
    poll.timeout.connect(check)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(milliseconds)
    loop.exec()
    poll.stop()
    deadline.stop()
    if failure:
        raise failure[0]
    if not predicate():
        raise AssertionError("The owned terrain operation did not acknowledge completion within the bounded wait")


def file_hash(path, maximum=8 * 1024 * 1024):
    info = path.stat(follow_symlinks=False)
    if (not stat.S_ISREG(info.st_mode) or path.is_symlink()
            or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
        raise AssertionError("Acceptance inputs must be regular, unlinked files")
    if info.st_size > maximum:
        raise AssertionError("Acceptance input exceeds its byte bound")
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while block := handle.read(65536):
            total += len(block)
            if total > maximum:
                raise AssertionError("Acceptance input grew beyond its byte bound")
            digest.update(block)
    if total != info.st_size:
        raise AssertionError("Acceptance input changed while hashing")
    return {"bytes": total, "sha256": digest.hexdigest()}


def world_hashes(root):
    """Bounded inventory, refusing links instead of walking outside the fixture."""
    root = root.resolve(strict=True)
    result = {}
    pending = [(root, 0)]
    entries = 0
    while pending:
        directory, depth = pending.pop()
        if depth > 4:
            raise AssertionError("Unexpected fixture directory depth")
        for path in directory.iterdir():
            entries += 1
            if entries > 32:
                raise AssertionError("Unexpected fixture inventory growth")
            info = path.stat(follow_symlinks=False)
            if path.is_symlink() or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise AssertionError("Unexpected link in the owned fixture")
            relative = path.relative_to(root).as_posix()
            if stat.S_ISDIR(info.st_mode):
                result[relative] = {"kind": "directory"}
                pending.append((path, depth + 1))
            elif stat.S_ISREG(info.st_mode):
                result[relative] = {"kind": "file", **file_hash(path)}
            else:
                raise AssertionError("Unexpected nonregular fixture entry")
    return result


def reference_hashes(root):
    result = {}
    for name in REFERENCE_FILES:
        path = root / name
        for component in (root / "reports",) if name.startswith("reports/") else ():
            info = component.stat(follow_symlinks=False)
            if getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise AssertionError("Reference directories must not redirect the acceptance read")
        if not path.resolve(strict=True).is_relative_to(root):
            raise AssertionError("Reference file escapes the explicitly selected directory")
        result[name] = file_hash(path)
    return result


def assert_process_absent(test, receipt, milliseconds=3000):
    test.assertIsNotNone(receipt.get("pid"), "The compiled engine did not start")
    test.assertTrue(receipt.get("finished"), "Engine exit was not acknowledged")
    test.assertTrue(receipt.get('imagePathMatchesEngine'), 'Engine image identity was not verified')
    test.assertGreater(receipt.get('creationTimeFileTime', 0), 0)
    receipt['exitObservation'] = wait_for_process_exit_observation(receipt, milliseconds)
    test.assertTrue(receipt['exitObservation']['complete'])


class ObservedSession(TerrainSession):
    """Records actual queued protocol actions without changing their behavior."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.sent_methods = []

    def _send(self, phase, method, params):
        eligible = self.process is not None and not self._cancelled
        super()._send(phase, method, params)
        if eligible:
            self.sent_methods.append(method)


class TerrainEngineAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if UNACKNOWLEDGED_OWNED_PROCESSES:
            raise AssertionError('A prior owned-process stop remains unresolved; no additional acceptance process will start')
        if os.name != "nt":
            raise AssertionError("This explicit acceptance requires native Windows process-identity checks")
        selected = os.environ.get("MWE_TEST_REFERENCE_ROOT")
        if not selected or not Path(selected).is_absolute():
            raise AssertionError("Set MWE_TEST_REFERENCE_ROOT explicitly to an absolute prepared reference directory")
        cls.reference_root = Path(selected).resolve(strict=True)
        if not cls.reference_root.is_dir() or not ENGINE.is_file():
            raise AssertionError("The explicitly selected references and actual compiled debug engine are required")
        cls.app = QCoreApplication.instance() or QCoreApplication([])
        cls.engine_fingerprint = file_hash(ENGINE, 256 * 1024 * 1024)
        cls.references_before = reference_hashes(cls.reference_root)
        cls._require_real_capabilities()

    @classmethod
    def _require_real_capabilities(cls):
        """Fail the class once when the explicit engine lacks the required RPCs."""
        process = QProcess()
        decoder = Decoder()
        replies, errors = [], []
        receipt = {"pid": None, "finished": False, "stderrBytes": 0}
        failure = None
        process.setProgram(str(ENGINE))
        process.setArguments(["--reference-root", str(cls.reference_root),
                              "--reference-profile", "vanilla-java-1.20.1"])

        def started():
            receipt["pid"] = int(process.processId())
            try:
                receipt.update(child_start_receipt(receipt['pid']))
            except (OSError, ValueError, RuntimeError, AssertionError) as error:
                errors.append(type(error).__name__ + ': ' + str(error)[:300])
                process.kill()
                return
            payload = encode_request("acceptance:capabilities", "engine.info")
            if process.write(payload) != len(payload):
                errors.append("Capability request was not completely queued")
                process.kill()

        def read():
            try:
                while process.bytesAvailable():
                    replies.extend(decoder.feed(bytes(process.read(65536))))
                if replies:
                    process.closeWriteChannel()
            except (ValueError, TypeError, RecursionError) as error:
                errors.append(str(error))
                process.kill()

        def diagnostics():
            process.setReadChannel(QProcess.ProcessChannel.StandardError)
            receipt["stderrBytes"] += len(process.read(8192))
            remaining = process.bytesAvailable()
            process.setReadChannel(QProcess.ProcessChannel.StandardOutput)
            if receipt["stderrBytes"] > 65536:
                errors.append("Capability diagnostics exceeded the bounded limit")
                process.kill()
            elif remaining:
                QTimer.singleShot(0, diagnostics)

        process.started.connect(started)
        process.readyReadStandardOutput.connect(read)
        process.readyReadStandardError.connect(diagnostics)
        process.finished.connect(lambda code, status: receipt.update(finished=True, exitCode=code, exitStatus=status.name))
        process.start()
        try:
            wait_for(lambda: process.state() == QProcess.ProcessState.NotRunning)
            if process.bytesAvailable():
                read()
            if errors or len(replies) != 1 or receipt.get("exitCode") != 0 or receipt["stderrBytes"]:
                raise AssertionError("Actual engine capability handshake did not complete quietly: " + "; ".join(errors))
            reply = replies[0]
            if reply.get("id") != "acceptance:capabilities" or "result" not in reply:
                raise AssertionError("Actual engine capability response is invalid")
            result = reply["result"]
            methods = result.get("methods") if isinstance(result, dict) else None
            if not isinstance(methods, list) or any(method not in methods for method in TERRAIN_METHODS):
                raise AssertionError("Actual compiled engine does not advertise all terrain begin/page/end methods")
            reference = result.get("reference", {})
            if reference.get("status") != "ready" or reference.get("availableGeometryEvidence") != ["cube-shapes-v1"]:
                raise AssertionError("Actual engine has not admitted the explicit pinned geometry references")
            receipt['exitObservation'] = wait_for_process_exit_observation(receipt)
            record_receipt({"case": "capabilities", **receipt,
                            "engineSha256": cls.engine_fingerprint["sha256"],
                            "directIdentityAbsentAfterExit": True, 'receiptScope': RECEIPT_SCOPE,
                            'historicalOrphansVerified': False})
        except BaseException as error:
            failure = {'errorType': type(error).__name__, 'error': str(error)[:1000]}
            raise
        finally:
            stop_error = None
            try:
                if process.state() != QProcess.ProcessState.NotRunning:
                    process.kill()
                    wait_for(lambda: process.state() == QProcess.ProcessState.NotRunning, 3000)
            except BaseException as error:
                stop_error = error
            if failure or stop_error:
                retained = Path(tempfile.mkdtemp(prefix='mwe-terrain-accept-capabilities-'))
                preserve_failure_evidence(retained, {'schemaVersion': 1, 'case': 'capabilities',
                    'failure': failure, 'process': receipt, 'receiptScope': RECEIPT_SCOPE,
                    'stopError': None if stop_error is None else type(stop_error).__name__,
                    'engineFingerprint': cls.engine_fingerprint}, {})
            if process.state() == QProcess.ProcessState.NotRunning:
                process.deleteLater()
                cls.app.processEvents()
            else:
                UNACKNOWLEDGED_OWNED_PROCESSES.append(process)
            if stop_error:
                raise AssertionError('Capability engine stop remains unacknowledged; bounded failure evidence retained') from stop_error

    @classmethod
    def tearDownClass(cls):
        if file_hash(ENGINE, 256 * 1024 * 1024) != cls.engine_fingerprint:
            raise AssertionError("Compiled engine changed during the acceptance run")
        if reference_hashes(cls.reference_root) != cls.references_before:
            raise AssertionError("Reference bytes changed during the acceptance run")

    def setUp(self):
        if UNACKNOWLEDGED_OWNED_PROCESSES:
            raise AssertionError('A prior owned-process stop remains unresolved; no additional fixture will start')
        self._case_verified = False
        self._fixture_before = {}
        self.owned_root = Path(tempfile.mkdtemp(prefix="mwe-terrain-accept-")).resolve(strict=True)
        self.addCleanup(self._finish_owned_case)
        self.assertEqual(self.owned_root.parent, Path(tempfile.gettempdir()).resolve(strict=True))
        self.world = self.owned_root / "world"
        self.fixture = write_terrain_world(self.world)
        self.before = world_hashes(self.world)
        total = sum(row.get('bytes', 0) for row in self.before.values())
        self.assertLessEqual(total, MAX_FIXTURE_EVIDENCE_BYTES)
        self._fixture_before = {name: (self.world / name).read_bytes()
                                for name, row in self.before.items() if row['kind'] == 'file'}
        self.settings = QSettings(str(self.owned_root / "settings.ini"), QSettings.Format.IniFormat)
        self.references = ReferenceSettings(self.settings, str(self.reference_root))
        self.coordinator = EngineCoordinator()
        self.session = ObservedSession(ENGINE, self.coordinator, self.references)
        self.accepted = []
        self.receipt = {"pid": None, "finished": False}
        self.session.completed.connect(self.accepted.append)
        self.coordinator.changed.connect(self._observe_lease)

    def _observe_lease(self):
        process = self.coordinator.process
        if process is None:
            return

        def started():
            self.receipt["pid"] = int(process.processId())
            try:
                self.receipt.update(child_start_receipt(self.receipt['pid']))
            except (OSError, ValueError, RuntimeError, AssertionError) as error:
                self.receipt['identityError'] = type(error).__name__ + ': ' + str(error)[:300]
                self.session.cancel()

        process.started.connect(started)
        process.finished.connect(lambda code, status: self.receipt.update(
            finished=True, exitCode=code, exitStatus=status.name))

    def _finish_owned_case(self):
        stop_error = None
        session = getattr(self, 'session', None)
        phase_before = getattr(session, 'phase', 'setup')
        status_before = str(getattr(session, 'status', 'Setup did not complete'))[:1000]
        outcome = getattr(self, '_outcome', None)
        result = getattr(outcome, 'result', None)
        failures = []
        for category in ('failures', 'errors'):
            for case, detail in getattr(result, category, []):
                if case is self or getattr(case, 'test_case', None) is self:
                    failures.append({'category': category, 'detail': str(detail)[-4096:]})
        failures = failures[-4:]
        try:
            if session is not None:
                session.cancel()
                wait_for(lambda: not session.busy and not self.coordinator.busy, 35000)
        except BaseException as error:
            stop_error = error
        after = None
        inventory_error = None
        try:
            if hasattr(self, 'world') and self.world.exists():
                after = world_hashes(self.world)
        except (OSError, ValueError, RuntimeError, AssertionError) as error:
            inventory_error = type(error).__name__ + ': ' + str(error)[:300]
        stopped = session is None or (not session.busy and not self.coordinator.busy)
        if session is not None and stopped:
            session.deleteLater(); self.coordinator.deleteLater(); self.references.deleteLater()
            self.app.processEvents()
        elif session is not None:
            UNACKNOWLEDGED_OWNED_PROCESSES.append((session, self.coordinator, self.references))
        verified = (self._case_verified and stopped and stop_error is None
                    and inventory_error is None and after == getattr(self, 'before', None))
        if verified:
            # Verify this exact task-created root again before recursive removal.
            info = self.owned_root.stat(follow_symlinks=False)
            if (self.owned_root.resolve(strict=True) != self.owned_root
                    or self.owned_root.parent != Path(tempfile.gettempdir()).resolve(strict=True)
                    or not self.owned_root.name.startswith('mwe-terrain-accept-')
                    or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
                raise AssertionError('Owned cleanup target changed; retained for inspection')
            shutil.rmtree(self.owned_root)
        else:
            preserve_failure_evidence(self.owned_root, {
                'schemaVersion': 1, 'case': self._testMethodName, 'verified': False,
                'receiptScope': RECEIPT_SCOPE, 'process': getattr(self, 'receipt', {}),
                'engineFingerprint': getattr(self, 'engine_fingerprint', None),
                'sourceHashesBefore': getattr(self, 'before', None), 'sourceHashesAfter': after,
                'inventoryError': inventory_error,
                'stopError': None if stop_error is None else type(stop_error).__name__,
                'phaseBeforeCleanup': phase_before, 'statusBeforeCleanup': status_before,
                'phaseAfterCleanup': getattr(session, 'phase', 'setup'),
                'testFailures': failures,
                'currentWorldCopied': False,
                'retentionLimits': {'originalFixtureBytes': MAX_FIXTURE_EVIDENCE_BYTES,
                                    'receiptBytes': MAX_RECEIPT_BYTES},
            }, self._fixture_before)
        if stop_error:
            raise AssertionError('Owned process stop remains unacknowledged; failure evidence retained') from stop_error
        if self._case_verified and not verified:
            raise AssertionError('Final fixture/stop verification failed; bounded evidence retained')

    def request(self, generation, x=-1, z=-1):
        bounds = {"chunkXMin": x, "chunkXMax": x, "chunkZMin": z, "chunkZMax": z,
                  "sectionYMin": -4, "sectionYMax": -4}
        return TerrainRequest(str(self.world), "explicit-acceptance-world", "minecraft:overworld", generation, bounds)

    def assert_preserved_and_stopped(self):
        self.assertEqual(world_hashes(self.world), self.before, "Synthetic world bytes or inventory changed")
        self.assertTrue(self.receipt.get("parentMatched"), "Engine PID was not observed as a direct owned child")
        self.assertEqual(self.receipt.get("initialObservedReachableChildren"), len(self.receipt.get('observedConsoleHosts', [])))
        assert_process_absent(self, self.receipt)

    def test_present_scene_real_stream_and_source_preservation(self):
        self.session.request(self.request(1))
        wait_for(lambda: not self.session.busy, 35000)
        self.assertEqual(self.session.phase, "complete", self.session.status)
        self.assertEqual(len(self.accepted), 1, self.session.status)
        self.assertTrue(self.references.ready)
        scene = self.accepted[0]
        totals = scene.manifest["totals"]
        expected = {"sections": 1, "decodedCells": 4096, "cubeCells": 1052,
                    "airCells": 0, "unsupportedCells": 3044, "faces": 6312}
        for key, value in expected.items():
            self.assertEqual(totals[key], value, key)
        self.assertEqual(sum(len(values) for values in scene.section_cells.values()), 4096)
        self.assertEqual(len(list(scene.faces())), 6312)
        for coordinate, name, supported in (
            ((-16, -64, -16), "minecraft:stone", True),
            ((-12, -58, -12), "minecraft:cobblestone", True),
            ((-6, -58, -6), "minecraft:glass", False),
            ((-16, -58, -16), "minecraft:air", False),
        ):
            state = scene.cell_state(*coordinate)
            self.assertIsNotNone(state)
            self.assertEqual(scene.state_table[state]["name"], name)
            self.assertEqual(scene.supported(state), supported)
        self.assertEqual(self.session.sent_methods,
                         ["engine.info", "world.terrain_begin"]
                         + ["world.terrain_page"] * totals["pages"] + ["world.terrain_end"])
        self.assertEqual(self.receipt["exitCode"], 0)
        self.assertEqual(self.receipt["exitStatus"], "NormalExit")
        self.assertEqual(self.session.diagnostic_bytes, 0)
        self.assert_preserved_and_stopped()
        record_receipt({"case": "present", **self.receipt, "totals": dict(totals),
                        "sourceHashesBefore": self.before, "sourceHashesAfter": world_hashes(self.world),
                        "readSetDigest": scene.manifest["readSetDigest"], "directIdentityAbsentAfterExit": True,
                        'receiptScope': RECEIPT_SCOPE, 'historicalOrphansVerified': False})
        self._case_verified = True

    def test_absent_region_is_explicit_and_contains_no_invented_cells(self):
        self.session.request(self.request(2, 32, 32))
        wait_for(lambda: not self.session.busy, 35000)
        self.assertEqual(self.session.phase, "complete", self.session.status)
        self.assertEqual(len(self.accepted), 1)
        scene = self.accepted[0]
        self.assertEqual(len(scene.coverage), 1)
        row = scene.coverage[(32, 32, -4)]
        self.assertEqual(row["availability"], "absent-region")
        for name in ("decodedCells", "cubeCells", "airCells", "unsupportedCells"):
            self.assertEqual(row[name], 0)
        self.assertEqual(scene.manifest["pages"], [])
        self.assertTrue(all(value == 0 for value in scene.manifest["totals"].values()))
        self.assertEqual(list(scene.cells()), [])
        self.assertEqual(list(scene.faces()), [])
        self.assertEqual(self.session.sent_methods, ["engine.info", "world.terrain_begin", "world.terrain_end"])
        self.assertEqual(self.receipt["exitCode"], 0)
        self.assertEqual(self.session.diagnostic_bytes, 0)
        self.assert_preserved_and_stopped()
        record_receipt({"case": "absent-region", **self.receipt,
                        "coverage": dict(row), "sourceHashesBefore": self.before,
                        "sourceHashesAfter": world_hashes(self.world), "directIdentityAbsentAfterExit": True,
                        'receiptScope': RECEIPT_SCOPE, 'historicalOrphansVerified': False})
        self._case_verified = True

    def test_cancel_after_manifest_stops_owned_child_without_accepting_scene(self):
        cancellation = {"requested": False, "phase": None, "pid": None}

        def cancel_after_manifest():
            if not cancellation["requested"] and self.session.phase == "page" and self.session.scene is not None:
                cancellation.update(requested=True, phase=self.session.phase,
                                    pid=int(self.session.process.processId()) if self.session.process else None)
                self.session.cancel()

        self.session.changed.connect(cancel_after_manifest)
        self.session.request(self.request(3))
        wait_for(lambda: not self.session.busy, 35000)
        self.assertTrue(cancellation["requested"], "A real accepted manifest/page boundary was not reached: " + self.session.status)
        self.assertEqual(cancellation["pid"], self.receipt["pid"])
        self.assertEqual(self.session.phase, "canceled", self.session.status)
        self.assertEqual(self.accepted, [])
        self.assertIsNone(self.session.scene)
        self.assertIn("world.terrain_begin", self.session.sent_methods)
        self.assertIn("world.terrain_page", self.session.sent_methods)
        self.assertNotIn("world.terrain_end", self.session.sent_methods)
        self.assert_preserved_and_stopped()
        record_receipt({"case": "canceled-after-manifest", **self.receipt,
                        "cancellation": cancellation, "acceptedScenes": 0,
                        "sourceHashesBefore": self.before, "sourceHashesAfter": world_hashes(self.world),
                        "directIdentityAbsentAfterExit": True, 'receiptScope': RECEIPT_SCOPE,
                        'historicalOrphansVerified': False})
        self._case_verified = True


if __name__ == "__main__":
    unittest.main(verbosity=2)
