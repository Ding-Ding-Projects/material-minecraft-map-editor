"""``converter.convert`` over the real sidecar process.

``converter.formats`` listed what the application can convert from the day the
sidecar existed, and nothing could ask it to convert anything. The acceptance
run had to reach past the bridge and call ``core.convert_one`` in-process to
show conversion worked at all -- which proves the core and says nothing about
whether the desktop app can reach it. A catalogue of capabilities the bridge
cannot invoke is a menu with no kitchen behind it.

Every test here spawns the REAL child process and speaks the real protocol. An
in-process call to the handler would pass whether or not the method is
registered, whether or not its result survives JSON, and whether or not the
child can import what it needs -- which are the three things that actually
break at this boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class SidecarConverterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, "-m", "amulet_map_editor.api.sidecar"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            cwd=str(REPO),
        )
        self._id = 0
        self.workspace = tempfile.mkdtemp(prefix="amulet-convert-test-")

    def tearDown(self) -> None:
        try:
            self.process.terminate()
            self.process.wait(timeout=10)
        except Exception:  # pragma: no cover - the child is already gone
            pass

    def call(self, method: str, params: dict) -> dict:
        self._id += 1
        self.process.stdin.write(
            json.dumps(
                {"id": self._id, "method": method, "params": params, "version": 1}
            )
            + "\n"
        )
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line, "the sidecar closed its output instead of answering")
        return json.loads(line)

    def _write_nbt(self, name: str = "in.nbt") -> str:
        from amulet_nbt import CompoundTag, NamedTag, StringTag

        path = os.path.join(self.workspace, name)
        NamedTag(CompoundTag({"greeting": StringTag("hello")}), "root").save_to(
            path, compressed=True
        )
        return path

    def test_a_real_conversion_runs_and_writes_its_output(self) -> None:
        source = self._write_nbt()
        destination = os.path.join(self.workspace, "out.json")

        response = self.call(
            "converter.convert",
            {
                "source_path": source,
                "adapter_id": "gzip_nbt_to_json",
                "destination_path": destination,
            },
        )

        self.assertNotIn("error", response, response)
        self.assertEqual(response["result"]["outcome"], "converted")
        self.assertTrue(
            os.path.exists(destination),
            "the method reported success and wrote no file, which is the one "
            "outcome a caller cannot detect without checking the disk itself",
        )
        written = json.loads(Path(destination).read_text(encoding="utf-8"))
        self.assertIn("root", written, written)

    def test_it_refuses_to_write_over_its_own_input(self) -> None:
        """The destructive one, so it is checked rather than assumed."""
        source = self._write_nbt()
        before = Path(source).read_bytes()

        response = self.call(
            "converter.convert",
            {
                "source_path": source,
                "adapter_id": "gzip_nbt_to_json",
                "destination_path": source,
            },
        )

        self.assertIn("error", response, response)
        self.assertEqual(response["error"]["code"], "invalid_params")
        self.assertEqual(
            Path(source).read_bytes(),
            before,
            "the source file was modified by a conversion that was refused",
        )

    def test_a_missing_source_is_a_structured_error_not_a_crash(self) -> None:
        response = self.call(
            "converter.convert",
            {
                "source_path": os.path.join(self.workspace, "not-here.nbt"),
                "adapter_id": "gzip_nbt_to_json",
                "destination_path": os.path.join(self.workspace, "out.json"),
            },
        )
        self.assertIn("error", response, response)
        self.assertEqual(response["error"]["code"], "invalid_params")

    def test_an_unknown_adapter_is_reported_rather_than_guessed(self) -> None:
        source = self._write_nbt()
        response = self.call(
            "converter.convert",
            {
                "source_path": source,
                "adapter_id": "no_such_adapter",
                "destination_path": os.path.join(self.workspace, "out.json"),
            },
        )
        # Either shape is honest: refused up front, or run and reported failed.
        # What must never happen is a silent success or a crashed child.
        if "error" in response:
            self.assertEqual(response["error"]["code"], "invalid_params")
        else:
            self.assertEqual(response["result"]["outcome"], "failed")
            self.assertTrue(response["result"].get("reason"))

    def test_the_child_survives_every_refusal(self) -> None:
        """A rejected call must not take the process down with it.

        The sidecar serves one request at a time over one pipe, so a handler
        that dies on bad input does not fail one call -- it ends the session,
        and every later request in the application fails with a dead sidecar.
        """
        self.call("converter.convert", {"source_path": "", "adapter_id": "", "destination_path": ""})
        self.call("converter.convert", {"source_path": 5, "adapter_id": None, "destination_path": []})
        alive = self.call("protocol.ping", {})
        self.assertTrue(alive.get("result", {}).get("ok"), alive)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
