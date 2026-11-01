"""Explicit native terrain acceptance against the actual compiled engine.

Run from the repository root with an explicitly selected MWE_TEST_REFERENCE_ROOT:
    native/.venv/Scripts/python.exe -m unittest native.tests.accept_terrain_engine -v

This module intentionally does not match ordinary test discovery. Missing inputs,
missing terrain methods and unsupported hosts fail; they never become skipped
successes. It creates no window, render surface, synthetic frame receipt or GPU
result. Fixtures are generated in an owned temporary directory, not product data.
"""

import hashlib
import os
from pathlib import Path
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
from native.tests.process_snapshot import snapshot, descendants


ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine" / "target" / "debug" / "material-world-engine.exe"
REFERENCE_FILES = (
    "reports/blocks.json", "reports/registries.json",
    "registry-source-receipt.json", "java-geometry-reference-evidence.json",
)
TERRAIN_METHODS = ("world.terrain_begin", "world.terrain_page", "world.terrain_end")
ACCEPTANCE_RECEIPTS = []


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
    poll.timeout.connect(lambda: loop.quit() if predicate() else None)
    deadline.timeout.connect(loop.quit)
    poll.start()
    deadline.start(milliseconds)
    loop.exec()
    poll.stop()
    deadline.stop()
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


def assert_process_absent(test, receipt):
    test.assertIsNotNone(receipt.get("pid"), "The compiled engine did not start")
    test.assertTrue(receipt.get("finished"), "Engine exit was not acknowledged")
    tree = snapshot()
    test.assertNotIn(receipt["pid"], tree, "Owned engine PID remains present after exit acknowledgement")
    test.assertEqual(descendants(receipt["pid"], tree), set(), "An engine descendant remains present")


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
        process.setProgram(str(ENGINE))
        process.setArguments(["--reference-root", str(cls.reference_root),
                              "--reference-profile", "vanilla-java-1.20.1"])

        def started():
            receipt["pid"] = int(process.processId())
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
            tree = snapshot()
            if receipt["pid"] in tree or descendants(receipt["pid"], tree):
                raise AssertionError("Capability engine or a descendant remains after acknowledged exit")
            ACCEPTANCE_RECEIPTS.append({"case": "capabilities", **receipt,
                                        "engineSha256": cls.engine_fingerprint["sha256"], "absentAfterExit": True})
        finally:
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                wait_for(lambda: process.state() == QProcess.ProcessState.NotRunning, 3000)
            process.deleteLater()
            cls.app.processEvents()

    @classmethod
    def tearDownClass(cls):
        if file_hash(ENGINE, 256 * 1024 * 1024) != cls.engine_fingerprint:
            raise AssertionError("Compiled engine changed during the acceptance run")
        if reference_hashes(cls.reference_root) != cls.references_before:
            raise AssertionError("Reference bytes changed during the acceptance run")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mwe-terrain-accept-")
        self.owned_root = Path(self.temporary.name).resolve(strict=True)
        self.assertEqual(self.owned_root.parent, Path(tempfile.gettempdir()).resolve(strict=True))
        self.world = self.owned_root / "world"
        self.fixture = write_terrain_world(self.world)
        self.before = world_hashes(self.world)
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
            tree = snapshot()
            self.receipt["parentMatched"] = tree.get(self.receipt["pid"]) == os.getpid()
            self.receipt["initialDescendants"] = len(descendants(self.receipt["pid"], tree))

        process.started.connect(started)
        process.finished.connect(lambda code, status: self.receipt.update(
            finished=True, exitCode=code, exitStatus=status.name))

    def tearDown(self):
        self.session.cancel()
        wait_for(lambda: not self.session.busy and not self.coordinator.busy, 35000)
        self.session.deleteLater()
        self.coordinator.deleteLater()
        self.references.deleteLater()
        self.app.processEvents()
        # This exact task-created root was resolved and checked in setUp.
        self.temporary.cleanup()

    def request(self, generation, x=-1, z=-1):
        bounds = {"chunkXMin": x, "chunkXMax": x, "chunkZMin": z, "chunkZMax": z,
                  "sectionYMin": -4, "sectionYMax": -4}
        return TerrainRequest(str(self.world), "explicit-acceptance-world", "minecraft:overworld", generation, bounds)

    def assert_preserved_and_stopped(self):
        self.assertEqual(world_hashes(self.world), self.before, "Synthetic world bytes or inventory changed")
        self.assertTrue(self.receipt.get("parentMatched"), "Engine PID was not observed as a direct owned child")
        self.assertEqual(self.receipt.get("initialDescendants"), 0)
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
        ACCEPTANCE_RECEIPTS.append({"case": "present", **self.receipt, "totals": dict(totals),
                                    "sourceHashesBefore": self.before, "sourceHashesAfter": world_hashes(self.world),
                                    "readSetDigest": scene.manifest["readSetDigest"], "absentAfterExit": True})

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
        ACCEPTANCE_RECEIPTS.append({"case": "absent-region", **self.receipt,
                                    "coverage": dict(row), "sourceHashesBefore": self.before,
                                    "sourceHashesAfter": world_hashes(self.world), "absentAfterExit": True})

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
        ACCEPTANCE_RECEIPTS.append({"case": "canceled-after-manifest", **self.receipt,
                                    "cancellation": cancellation, "acceptedScenes": 0,
                                    "sourceHashesBefore": self.before, "sourceHashesAfter": world_hashes(self.world),
                                    "absentAfterExit": True})


if __name__ == "__main__":
    unittest.main(verbosity=2)
