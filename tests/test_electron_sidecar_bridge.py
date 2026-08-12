"""The real seam test for the Electron <-> Python sidecar connection.

This does not stub the bridge. It shells out to Node and runs
``scripts/verify_sidecar_client.js``, which drives ``electron/sidecar-client.js``
against a real, spawned ``amulet_map_editor.api.sidecar`` child process over
its actual stdio pipes: ping, write a preference, read it back, an unknown
method reporting a structured error, and a call after ``stop()`` reporting
"unavailable" rather than hanging. A test that only imported the Python
handler table would prove the handler logic and nothing about the process
boundary this lane exists to build.

The full renderer -> preload -> IPC -> sidecar -> Python -> restart round
trip additionally has its own standalone script,
``scripts/capture_electron_sidecar_roundtrip.js``, which launches the real
built Electron shell headlessly and drives it over the Chrome DevTools
protocol. That one is not run from pytest (it needs the Electron binary
present, which is a separate ``npm install`` step and materially slower);
run it directly with ``node scripts/capture_electron_sidecar_roundtrip.js``
and see ``docs/features/electron-migration/README.md`` for what it proved
most recently.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from amulet_map_editor.api.sidecar.methods import _WRITABLE_PREFERENCE_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def _node() -> str | None:
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="Node is not on PATH")
def test_sidecar_client_round_trips_against_the_real_python_sidecar() -> None:
    node = _node()
    assert node is not None
    result = subprocess.run(
        [node, str(ROOT / "scripts" / "verify_sidecar_client.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        "electron/sidecar-client.js failed its real round trip against the "
        f"Python sidecar.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "All sidecar-client.js round-trip checks passed" in result.stdout


def _electron_binary_present() -> bool:
    return (ROOT / "node_modules" / "electron" / "dist" / "electron.exe").exists()


@pytest.mark.skipif(_node() is None, reason="Node is not on PATH")
@pytest.mark.skipif(not _electron_binary_present(), reason="Electron binary not installed (run npm install)")
def test_sidecar_process_never_outlives_its_electron_parent() -> None:
    """The orphan check: launches the REAL packaged app headlessly (never a
    visible window -- AMULET_HEADLESS=1, per this repository's never-steal-
    focus rule), resolves the Python sidecar's actual OS PID as a child of
    the Electron main process, then proves it in two scenarios:

    1. a graceful quit through the same window.mmweDesktop.window.close()
       IPC path a real titlebar click uses, which must reach
       before-quit -> sidecar.stop();
    2. a hard `taskkill /F` of ONLY the Electron main process (no /T, so
       nothing artificially takes the sidecar down with it) -- the crash /
       "End Task" case, which gives main.js's own quit handlers no chance
       to run at all.

    Both must leave no Python sidecar process behind. See
    scripts/verify_sidecar_orphan.js for the full script; this wrapper
    mirrors test_sidecar_client_round_trips_against_the_real_python_sidecar
    above."""
    node = _node()
    assert node is not None
    result = subprocess.run(
        [node, str(ROOT / "scripts" / "verify_sidecar_orphan.js")],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "The Python sidecar outlived its Electron parent in at least one "
        f"scenario.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "ALL SIDECAR ORPHAN CHECKS PASSED" in result.stdout


def test_main_js_owns_the_sidecar_process_lifetime() -> None:
    """Static wiring guard: main.js must actually spawn, forward to, and
    kill the sidecar -- not merely import the client module and never call
    it. This is deliberately a source check, not a behavioural one; the
    behavioural proof is the round-trip test above."""
    main_js = (ROOT / "electron" / "main.js").read_text(encoding="utf-8")
    assert "SidecarClient" in main_js
    assert "sidecar.start()" in main_js
    assert 'ipcMain.handle("sidecar:call"' in main_js
    assert "sidecar.stop()" in main_js
    assert 'app.on("before-quit"' in main_js


def test_preload_exposes_a_narrow_sidecar_bridge_and_nothing_wider() -> None:
    preload_js = (ROOT / "electron" / "preload.js").read_text(encoding="utf-8")
    assert "sidecar:" in preload_js
    assert '"sidecar:call"' in preload_js
    # The bridge must never hand the renderer ipcRenderer itself, a raw
    # child_process, or filesystem access.
    assert "require(\"fs\")" not in preload_js
    assert "require(\"child_process\")" not in preload_js
    assert "ipcRenderer," not in preload_js.split("exposeInMainWorld")[1]


def test_site_settings_surface_has_a_real_sidecar_call_site() -> None:
    """docs/site/ must actually call the sidecar for at least one real
    setting, per the migration article's stated precondition for Phase 2 to
    be honestly complete."""
    index_html = (ROOT / "docs" / "site" / "index.html").read_text(encoding="utf-8")
    assert '<script src="electron-bridge.js">' in index_html

    bridge_js = (ROOT / "docs" / "site" / "electron-bridge.js").read_text(encoding="utf-8")
    assert "preferences.read" in bridge_js
    assert "preferences.write" in bridge_js
    assert "settings.onChange" in bridge_js


def test_bridge_maps_every_writable_preference_field_but_theme_is_no_longer_alone() -> None:
    """A regression guard for the original gap this lane exists to close:
    only ``preferences.theme`` was wired end to end and every other field was
    still browser-local state pretending to be the application. This does
    not assert 1:1 coverage of every dataclass field (``display_name`` has
    no site setting equivalent that matches the same semantics), but it does
    assert the bridge is no longer a single-field special case: every site
    setting FIELD_MAP entry must reference an actually-writable sidecar
    preference field, and there must be more than one of them."""
    bridge_js = (ROOT / "docs" / "site" / "electron-bridge.js").read_text(encoding="utf-8")
    mapped_prefs = set(re.findall(r'pref:\s*"([a-z_]+)"', bridge_js))
    assert len(mapped_prefs) > 1, (
        "electron-bridge.js must map more than just theme -- got " + repr(mapped_prefs)
    )
    unknown = mapped_prefs - _WRITABLE_PREFERENCE_FIELDS
    assert not unknown, (
        "electron-bridge.js maps a site setting to a preference field the "
        f"sidecar will not accept: {sorted(unknown)}"
    )
    # The fields this lane was explicitly asked to widen beyond theme.
    for expected in ("density", "accent", "ui_font", "language_mode", "ui_scale"):
        assert expected in mapped_prefs, f"electron-bridge.js no longer maps {expected!r}"


def test_bridge_has_real_call_sites_for_changelog_docs_and_dim_sum() -> None:
    """Static wiring guard for the surfaces this lane was asked to stop
    faking: changelog, docs and the dim-sum draw must each have a genuine
    ``bridge.call(...)`` site in electron-bridge.js, not merely be named in
    a comment."""
    bridge_js = (ROOT / "docs" / "site" / "electron-bridge.js").read_text(encoding="utf-8")
    called_methods = set(re.findall(r'\.call\(\s*"([a-z.]+)"', bridge_js))
    assert "changelog.entries" in called_methods
    assert "docs.articles" in called_methods
    assert "dimsum.draw" in called_methods
    # The changelog call site must actually replace the site-bundled global
    # changelog.js reads, not merely stash the response somewhere unused.
    assert "window.AMULET_CHANGELOG = {" in bridge_js
    # drawDimSum must be reachable from other site code, not a private
    # helper nobody outside this file can call.
    assert "drawDimSum: drawDimSum" in bridge_js


def test_bridge_has_real_call_sites_for_the_world_edit_path() -> None:
    """Static wiring guard for the write path: world.fill / world.replace /
    world.undo / world.redo / world.save must each have a genuine
    ``bridge.call(...)`` site in electron-bridge.js and be reachable from
    other site code, not merely named in a comment."""
    bridge_js = (ROOT / "docs" / "site" / "electron-bridge.js").read_text(encoding="utf-8")
    # world.* calls go through the shared callWorldMethod(method, params)
    # helper rather than bridge.call(...) directly, so match either form.
    called_methods = set(re.findall(r'(?:\.call|callWorldMethod)\(\s*"([a-z.]+)"', bridge_js))
    for method in ("world.fill", "world.replace", "world.undo", "world.redo", "world.save"):
        assert method in called_methods, f"electron-bridge.js has no call site for {method!r}"
    for exposed in (
        "fillSelection: fillSelection",
        "replaceInSelection: replaceInSelection",
        "undoEdit: undoEdit",
        "redoEdit: redoEdit",
        "saveWorld: saveWorld",
    ):
        assert exposed in bridge_js, f"electron-bridge.js does not expose {exposed!r} to other site code"


def test_viewport_panel_reaches_the_edit_bridge_and_the_confirm_gate() -> None:
    """Static wiring guard for the call site this lane owns: the viewport
    panel must actually call the bridge's edit methods against the current
    selection, gate the two destructive ones behind the project's real
    destructive-action confirm (never a flag defaulted to true), and say why
    a control is disabled rather than leaving it silently inert."""
    panel_js = (ROOT / "docs" / "site" / "viewport-panel.js").read_text(encoding="utf-8")
    for called in (
        "eb.fillSelection(",
        "eb.replaceInSelection(",
        "eb.undoEdit(",
        "eb.redoEdit(",
        "eb.saveWorld(",
    ):
        assert called in panel_js, f"viewport-panel.js does not call {called!r}"
    # The two mutating write calls must be gated behind a real confirm, not a
    # bridge-side default -- confirmDestructive() is only ever invoked from
    # inside the fill/replace flows, and both defer the actual sidecar call
    # to onConfirm rather than calling it unconditionally.
    assert "site.confirmDestructive(" in panel_js
    assert panel_js.count("onConfirm: do") >= 2
    # Undo/redo/save are not destructive-gated (undo/redo reverse an edit,
    # save persists it) but every control must still say why it is disabled.
    assert "setDisabled" in panel_js
    assert "No world is open yet." in panel_js
    assert "Enter both selection points first." in panel_js
    assert "Nothing to undo yet." in panel_js
    assert "Nothing to redo yet." in panel_js
    assert "No unsaved changes." in panel_js
    # An unsaved-changes state must be visible, not just tracked internally.
    assert "Unsaved changes" in panel_js
