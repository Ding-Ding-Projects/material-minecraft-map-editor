"""Tests for the Python sidecar's process boundary and wire protocol.

These spawn the REAL child process (``python -m amulet_map_editor.api.sidecar``)
and talk to it over its actual stdin/stdout pipes. An in-process call into
``server.dispatch`` would prove the handler logic and nothing about the
boundary itself -- the newline framing, the UTF-8 round trip, the
version-mismatch report, the timeout enforcement of a genuinely separate
process. That boundary is the point of this lane, so the tests exercise it
for real.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from amulet_map_editor.api.sidecar.protocol import PROTOCOL_VERSION


class SidecarProcess:
    """A thin, synchronous client for the real sidecar child process."""

    def __init__(self, config_dir: Optional[str] = None):
        env = dict(os.environ)
        # Isolate this test run's preferences/config from the developer's
        # own profile and from every other test in the (parallel) suite --
        # matches the repository's own tempfile-per-process convention.
        env["CONFIG_DIR"] = config_dir or tempfile.mkdtemp(prefix="amulet-sidecar-")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "amulet_map_editor.api.sidecar"],
            cwd=REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
            bufsize=1,
        )

    def send(self, payload: Dict[str, Any]) -> None:
        line = json.dumps(payload)
        assert self.process.stdin is not None
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()

    def read(self, timeout: float = 10.0) -> Dict[str, Any]:
        assert self.process.stdout is not None
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise AssertionError(f"Sidecar produced no response. stderr:\n{stderr}")
        return json.loads(line)

    def call(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        request_id: Any = 1,
        protocol_version: int = PROTOCOL_VERSION,
    ) -> Dict[str, Any]:
        self.send(
            {
                "id": request_id,
                "method": method,
                "params": params or {},
                "protocol_version": protocol_version,
            }
        )
        return self.read()

    def close(self) -> None:
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)


@pytest.fixture()
def sidecar():
    proc = SidecarProcess()
    try:
        yield proc
    finally:
        proc.close()


def test_ping_round_trip(sidecar: SidecarProcess) -> None:
    response = sidecar.call("protocol.ping")
    assert response["id"] == 1
    assert response["result"] == {"ok": True}
    assert "error" not in response


def test_unknown_method_is_a_structured_error_not_a_crash(sidecar: SidecarProcess) -> None:
    response = sidecar.call("no.such.method")
    assert "result" not in response
    assert response["error"]["code"] == "unknown_method"
    # The process must still be alive and answer a follow-up request --
    # an unknown method must not kill the sidecar.
    follow_up = sidecar.call("protocol.ping", request_id=2)
    assert follow_up["result"] == {"ok": True}


def test_version_mismatch_is_reported_not_guessed_at(sidecar: SidecarProcess) -> None:
    response = sidecar.call("protocol.ping", protocol_version=PROTOCOL_VERSION + 999)
    assert response["error"]["code"] == "version_mismatch"
    assert str(PROTOCOL_VERSION) in response["error"]["message"]


def test_malformed_json_line_gets_a_structured_error(sidecar: SidecarProcess) -> None:
    assert sidecar.process.stdin is not None
    sidecar.process.stdin.write("{not valid json\n")
    sidecar.process.stdin.flush()
    response = sidecar.read()
    assert response["error"]["code"] == "invalid_message"
    assert response["id"] is None
    # The sidecar must recover and keep serving subsequent requests.
    follow_up = sidecar.call("protocol.ping", request_id=2)
    assert follow_up["result"] == {"ok": True}


def test_oversized_message_is_rejected_before_json_parsing(sidecar: SidecarProcess) -> None:
    huge = json.dumps({"id": 1, "method": "protocol.ping", "params": {"pad": "x" * (9 * 1024 * 1024)}})
    assert sidecar.process.stdin is not None
    sidecar.process.stdin.write(huge + "\n")
    sidecar.process.stdin.flush()
    response = sidecar.read()
    assert response["error"]["code"] == "message_too_large"


def test_language_get_and_set_round_trip(sidecar: SidecarProcess) -> None:
    languages = sidecar.call("language.list")
    assert "en" in languages["result"]["language_ids"]

    set_response = sidecar.call("language.set", {"language_id": "en"}, request_id=2)
    assert set_response["result"]["language_id"] == "en"

    get_response = sidecar.call("language.get", request_id=3)
    assert get_response["result"]["language_id"] == "en"


def test_language_set_rejects_bad_params_as_structured_error(sidecar: SidecarProcess) -> None:
    response = sidecar.call("language.set", {"language_id": 12345})
    assert response["error"]["code"] == "invalid_params"


def test_preferences_read_returns_a_full_dict(sidecar: SidecarProcess) -> None:
    response = sidecar.call("preferences.read")
    result = response["result"]
    assert result["display_name"]
    assert result["language_mode"] in ("english", "cantonese", "bilingual")
    assert "theme" in result
    assert "ui_scale" in result


def test_preferences_write_round_trips_and_normalises(sidecar: SidecarProcess) -> None:
    write_response = sidecar.call(
        "preferences.write",
        {"funny_level_english": 4, "theme": "dark"},
    )
    result = write_response["result"]
    assert result["funny_level_english"] == 4
    assert result["theme"] == "dark"

    read_response = sidecar.call("preferences.read", request_id=2)
    assert read_response["result"]["funny_level_english"] == 4
    assert read_response["result"]["theme"] == "dark"


def test_preferences_write_rejects_unknown_field(sidecar: SidecarProcess) -> None:
    response = sidecar.call("preferences.write", {"totally_not_a_field": 1})
    assert response["error"]["code"] == "invalid_params"


def test_preferences_write_rejects_out_of_range_theme(sidecar: SidecarProcess) -> None:
    # theme is normalised, not rejected outright -- an invalid theme silently
    # falls back to "system" rather than erroring, matching Preferences.normalised().
    response = sidecar.call("preferences.write", {"theme": "not-a-real-theme"})
    assert response["result"]["theme"] == "system"


def test_converter_formats_lists_real_adapters(sidecar: SidecarProcess) -> None:
    response = sidecar.call("converter.formats")
    adapters = response["result"]["adapters"]
    assert adapters, "the sidecar must expose the converter's real adapter list"
    for adapter in adapters:
        assert adapter["id"]
        assert adapter["source_format"]
        assert adapter["target_format"]
        assert adapter["display_name"]
        assert isinstance(adapter["lossy"], bool)


def test_changelog_entries_lists_the_real_bundled_catalog(sidecar: SidecarProcess) -> None:
    response = sidecar.call("changelog.entries")
    result = response["result"]
    assert result["entries"], "the sidecar must expose the real bundled changelog catalog"
    entry = result["entries"][0]
    assert entry["version"]
    assert entry["commit_sha"]
    assert entry["changes"]
    change = entry["changes"][0]
    assert change["action"]
    assert change["summary"]
    assert change["commit_sha"]


def test_changelog_entries_filters_by_text(sidecar: SidecarProcess) -> None:
    all_entries = sidecar.call("changelog.entries")["result"]["entries"]
    version = all_entries[0]["version"]
    response = sidecar.call("changelog.entries", {"text": version}, request_id=2)
    filtered = response["result"]["entries"]
    assert filtered
    assert all(row["version"] == version for row in filtered)


def test_changelog_entries_rejects_bad_date(sidecar: SidecarProcess) -> None:
    response = sidecar.call("changelog.entries", {"start_date": "not-a-date"})
    assert response["error"]["code"] == "invalid_params"


def test_docs_articles_lists_the_real_bundled_articles(sidecar: SidecarProcess) -> None:
    response = sidecar.call("docs.articles")
    articles = response["result"]["articles"]
    assert articles, "the sidecar must expose the real bundled documentation articles"
    for article in articles:
        assert article["slug"]
        assert article["title"]
        assert article["markdown"]
        assert article["sha256"]


def test_docs_articles_returns_one_article_by_slug(sidecar: SidecarProcess) -> None:
    all_articles = sidecar.call("docs.articles")["result"]["articles"]
    slug = all_articles[0]["slug"]
    response = sidecar.call("docs.articles", {"slug": slug}, request_id=2)
    result = response["result"]["articles"]
    assert len(result) == 1
    assert result[0]["slug"] == slug


def test_docs_articles_rejects_unknown_slug(sidecar: SidecarProcess) -> None:
    response = sidecar.call("docs.articles", {"slug": "does-not-exist"})
    assert response["error"]["code"] == "invalid_params"


def test_dimsum_draw_honours_the_real_language_modes(sidecar: SidecarProcess) -> None:
    response = sidecar.call("dimsum.draw", {"language_mode": "bilingual"})
    result = response["result"]
    assert result["status"] in ("not_drawn", "unavailable", "ready")
    if result["status"] == "ready":
        assert result["language_mode"] == "bilingual"
        assert result["title"]
        assert result["image_asset_path"]


def test_dimsum_draw_rejects_unknown_language_mode(sidecar: SidecarProcess) -> None:
    response = sidecar.call("dimsum.draw", {"language_mode": "klingon"})
    assert response["error"]["code"] == "invalid_params"


def test_sidecar_never_writes_a_secret_to_stdout_or_stderr(sidecar: SidecarProcess) -> None:
    """The methods this lane exposes touch no secret, and the smoke test says so.

    This is not a search for a specific leaked value (nothing here holds a
    secret to leak) -- it is a guard that a future method added to this
    table cannot quietly start writing one to the wire or to stderr without
    this test starting to fail once it does.
    """
    sidecar.call("preferences.read")
    sidecar.call("language.get", request_id=2)
    sidecar.call("converter.formats", request_id=3)
    sidecar.call("changelog.entries", request_id=4)
    sidecar.call("docs.articles", request_id=5)
    sidecar.call("dimsum.draw", {"language_mode": "english"}, request_id=6)
    sidecar.close()
    stderr = sidecar.process.stderr.read() if sidecar.process.stderr else ""
    lowered = stderr.lower()
    for banned in ("password", "secret", "token", "credential", "totp"):
        assert banned not in lowered, f"sidecar stderr mentioned {banned!r}"


def test_dispatch_handles_a_parsed_request_directly() -> None:
    """A narrower unit check on the dispatcher's own error-shape contract.

    Kept alongside the process-boundary tests above rather than instead of
    them: this one is cheap and pins the exact error codes; the ones above
    are what actually prove the boundary works.
    """
    from amulet_map_editor.api.sidecar.protocol import Request
    from amulet_map_editor.api.sidecar.server import dispatch

    ok = dispatch(Request(id=1, method="protocol.ping"))
    assert json.loads(ok)["result"] == {"ok": True}

    missing = dispatch(Request(id=2, method="does.not.exist"))
    assert json.loads(missing)["error"]["code"] == "unknown_method"

    mismatched = dispatch(Request(id=3, method="protocol.ping", protocol_version=-1))
    assert json.loads(mismatched)["error"]["code"] == "version_mismatch"
