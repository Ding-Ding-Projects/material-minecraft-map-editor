"""Drive the display-text overlay surface, because reading its source cannot.

The overlay mechanism itself (:mod:`amulet_map_editor.api.text_overlay`) is a
small, wx-free module with its own tests. What genuinely needs a real window
is the Preferences surface: that its controls exist, that Load and Remove
take effect immediately rather than waiting for Save, that a refused file
reports why instead of being swallowed, that a refusal never clobbers a good
overlay that was already active, and that the row actually paints something
rather than photographing as a blank rectangle.

Every fixture file used here is deliberately synthetic -- mapping the made-up
word ``"widget"`` to ``"gadget"`` -- and nothing in this file describes,
hints at, or depends on what a real overlay might contain.
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api import config, text_overlay  # noqa: E402
from amulet_map_editor.api.wx.ui import preferences as preferences_module  # noqa: E402


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-overlay-ui-"))
    application = wx.App()
    yield application


def _reset_overlay_storage() -> None:
    """Clear both the mechanism's cache and this surface's own remembered path.

    Several test modules in this suite share one process and, by this
    repository's own convention, set ``CONFIG_DIR`` with ``setdefault`` --
    so whichever module runs first decides the directory every later module
    also reads and writes. Clearing only :mod:`text_overlay`'s cache would
    leave this dialog's own ``_OVERLAY_SOURCE_PATH_ID`` record behind, and a
    "fresh" dialog built by a later test would open with a stale path field.
    """
    text_overlay.clear_cached_overlay()
    config.put(preferences_module._OVERLAY_SOURCE_PATH_ID, "")


@pytest.fixture(autouse=True)
def _clean_overlay_state(app):
    """Every test starts from "nothing loaded", regardless of test order."""
    _reset_overlay_storage()
    yield
    _reset_overlay_storage()


@pytest.fixture
def dialog(app):
    from amulet_map_editor.api.wx.ui.preferences import PreferencesDialog

    parent = wx.Frame(None)
    box = PreferencesDialog(parent)
    yield box
    box.Destroy()
    parent.Destroy()


def _write_overlay(tmp_path, replacements, name="overlay.json", required_phrases=()):
    path = tmp_path / name
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "replacements": replacements,
                "required_phrases": list(required_phrases),
            }
        ),
        encoding="utf-8",
    )
    return str(path)


# ----------------------------------------------------------------------
# the surface exists and starts honest
# ----------------------------------------------------------------------


def test_overlay_controls_exist_with_a_browse_control_beside_the_path_field(dialog):
    for attribute in (
        "overlay_path",
        "overlay_browse",
        "overlay_load",
        "overlay_reload",
        "overlay_remove",
        "overlay_status",
    ):
        assert hasattr(dialog, attribute), f"missing overlay control: {attribute}"
    # Guided-forms rule: a path field always carries a native browse control
    # beside it, keyboard-reachable with its own accessible name.
    assert dialog.overlay_browse.GetName() == "Browse for overlay file"


def test_default_state_says_plainly_that_nothing_is_loaded(dialog):
    assert "No overlay is loaded" in dialog.overlay_status.GetLabel()
    assert "shipped wording" in dialog.overlay_status.GetLabel()
    # Nothing is loaded and the path field is empty, so there is nothing for
    # Reload or Remove to act on.
    assert not dialog.overlay_reload.IsEnabled()
    assert not dialog.overlay_remove.IsEnabled()


# ----------------------------------------------------------------------
# loading is live -- it never waits for Save preferences
# ----------------------------------------------------------------------


def test_loading_a_synthetic_overlay_updates_state_live_and_substitutes_text(
    dialog, tmp_path
):
    path = _write_overlay(tmp_path, {"widget": "gadget"})
    dialog.overlay_path.SetValue(path)
    dialog._load_overlay(None)

    assert "1 replacement" in dialog.overlay_status.GetLabel()
    assert path in dialog.overlay_status.GetLabel()
    assert dialog._overlay_row.provenance.GetLabel().startswith("Cached at ")
    assert dialog.overlay_reload.IsEnabled()
    assert dialog.overlay_remove.IsEnabled()

    # Live: the running cache reflects the load without any restart and
    # without the dialog's Save/OK ever being pressed.
    active = text_overlay.load_cached_overlay()
    assert active is not None
    assert text_overlay.substitute_text(active, "widget") == "gadget"
    assert (
        text_overlay.substitute_text(active, "something else entirely")
        == "something else entirely"
    )


def test_the_dialog_never_shows_the_loaded_mapping_in_bulk(dialog, tmp_path):
    """Only the count and the source path are shown -- never the contents."""
    path = _write_overlay(tmp_path, {"widget": "gadget", "sprocket": "cog"})
    dialog.overlay_path.SetValue(path)
    dialog._load_overlay(None)
    shown = dialog.overlay_status.GetLabel() + dialog._overlay_row.provenance.GetLabel()
    assert "gadget" not in shown
    assert "sprocket" not in shown
    assert "cog" not in shown
    assert "2 replacement" in shown or "2 replacements" in shown


# ----------------------------------------------------------------------
# refusals are shown, not swallowed, and never clobber a good overlay
# ----------------------------------------------------------------------


def test_a_malformed_file_reports_why_in_the_surface(dialog, tmp_path):
    bad = tmp_path / "not-json.json"
    bad.write_text("this is not valid JSON", encoding="utf-8")
    dialog.overlay_path.SetValue(str(bad))
    dialog._load_overlay(None)

    assert "not valid JSON" in dialog.overlay_status.GetLabel()
    assert text_overlay.load_cached_overlay() is None


def test_a_refused_reload_leaves_the_previously_active_overlay_in_place(
    dialog, tmp_path
):
    good_path = _write_overlay(tmp_path, {"widget": "gadget"})
    dialog.overlay_path.SetValue(good_path)
    dialog._load_overlay(None)
    active = text_overlay.load_cached_overlay()
    assert text_overlay.substitute_text(active, "widget") == "gadget"

    # Corrupt the file on disk behind the loaded overlay's back, then reload.
    with open(good_path, "w", encoding="utf-8") as stream:
        stream.write("{not valid json")
    dialog._reload_overlay(None)

    assert "not valid JSON" in dialog.overlay_status.GetLabel()
    # The refusal is reported, but the overlay that was already active is
    # untouched: the substitution still works.
    active = text_overlay.load_cached_overlay()
    assert active is not None
    assert text_overlay.substitute_text(active, "widget") == "gadget"
    assert len(active.replacements) == 1


def test_a_missing_top_level_key_is_refused_with_a_plain_reason(dialog, tmp_path):
    path = tmp_path / "shape.json"
    path.write_text(
        json.dumps({"replacements": {"widget": "gadget"}}), encoding="utf-8"
    )
    dialog.overlay_path.SetValue(str(path))
    dialog._load_overlay(None)
    assert "version" in dialog.overlay_status.GetLabel()
    assert text_overlay.load_cached_overlay() is None


def test_a_missing_file_is_refused_rather_than_raising(dialog, tmp_path):
    dialog.overlay_path.SetValue(str(tmp_path / "does-not-exist.json"))
    dialog._load_overlay(None)
    assert "not found" in dialog.overlay_status.GetLabel()
    assert text_overlay.load_cached_overlay() is None


def test_an_empty_path_is_refused_rather_than_attempting_a_load(dialog):
    dialog.overlay_path.ChangeValue("")
    dialog._load_overlay(None)
    assert "Choose a file to load" in dialog.overlay_status.GetLabel()


# ----------------------------------------------------------------------
# reload re-reads the chosen file; remove returns to shipped wording live
# ----------------------------------------------------------------------


def test_reload_picks_up_an_external_edit_to_the_same_file(dialog, tmp_path):
    path = _write_overlay(tmp_path, {"widget": "gadget"})
    dialog.overlay_path.SetValue(path)
    dialog._load_overlay(None)
    assert len(text_overlay.load_cached_overlay().replacements) == 1

    # Editing the file externally and reloading is meant to be one click.
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "version": 1,
                "replacements": {"widget": "gadget", "sprocket": "cog"},
                "required_phrases": [],
            },
            stream,
        )
    dialog._reload_overlay(None)

    assert len(text_overlay.load_cached_overlay().replacements) == 2
    assert "2 replacement" in dialog.overlay_status.GetLabel()


def test_reload_with_nothing_loaded_refuses_rather_than_doing_nothing_silently(
    dialog,
):
    dialog.overlay_path.ChangeValue("")
    dialog._reload_overlay(None)
    assert "nothing to reload" in dialog.overlay_status.GetLabel()


def test_remove_returns_to_shipped_wording_without_a_restart(dialog, tmp_path):
    path = _write_overlay(tmp_path, {"widget": "gadget"})
    dialog.overlay_path.SetValue(path)
    dialog._load_overlay(None)
    active = text_overlay.load_cached_overlay()
    assert text_overlay.substitute_text(active, "widget") == "gadget"

    dialog._remove_overlay(None)

    assert "No overlay is loaded" in dialog.overlay_status.GetLabel()
    assert dialog.overlay_path.GetValue() == ""
    assert not dialog.overlay_reload.IsEnabled()
    assert not dialog.overlay_remove.IsEnabled()
    # Live: the cache itself reverted, with no dialog restart involved.
    assert text_overlay.load_cached_overlay() is None


def test_browse_stages_a_path_that_load_then_validates_identically(
    dialog, tmp_path, monkeypatch
):
    """A typed path and a browsed path must run through the same validation."""
    path = _write_overlay(tmp_path, {"widget": "gadget"})
    monkeypatch.setattr(
        "amulet_map_editor.api.wx.ui.preferences.choose_path",
        lambda *args, **kwargs: path,
    )
    dialog._browse_overlay_path(None)
    assert dialog.overlay_path.GetValue() == path

    dialog._load_overlay(None)
    active = text_overlay.load_cached_overlay()
    assert text_overlay.substitute_text(active, "widget") == "gadget"


# ----------------------------------------------------------------------
# it survives a restart -- reopening the dialog reads the real cache
# ----------------------------------------------------------------------


def test_reopening_preferences_shows_a_previously_cached_overlay(app, tmp_path):
    from amulet_map_editor.api.wx.ui.preferences import PreferencesDialog

    path = _write_overlay(tmp_path, {"widget": "gadget"})
    text_overlay.load_overlay_file(path)

    parent = wx.Frame(None)
    reopened = PreferencesDialog(parent)
    try:
        assert "1 replacement" in reopened.overlay_status.GetLabel()
        assert reopened.overlay_remove.IsEnabled()
    finally:
        reopened.Destroy()
        parent.Destroy()


# ----------------------------------------------------------------------
# it actually renders
# ----------------------------------------------------------------------


def test_the_language_tab_photographs_as_something_rather_than_a_blank_band(
    dialog, tmp_path
):
    """A capture that reports success over an empty rectangle is a false negative.

    A Studio widget that paints in ``EVT_PAINT`` and never overrode
    ``render_to`` photographs blank while every structural field stays
    healthy, so this checks the picture actually has more than a background
    in it -- not just that the capture call did not raise.
    """
    capture = pytest.importorskip(
        "scripts.capture_surface", reason="the capture harness is unavailable"
    )

    path = _write_overlay(tmp_path, {"widget": "gadget"})
    dialog.overlay_path.SetValue(path)
    dialog._load_overlay(None)

    dialog.Show()
    wx.SafeYield()
    page = dialog._language_page
    assert page.IsShownOnScreen()

    destination = tmp_path / "language-tab.png"
    outcome = capture.capture_composite(page, destination)
    dialog.Hide()

    assert destination.exists() and destination.stat().st_size > 0
    assert not outcome.get("skipped"), f"holes in the capture: {outcome['skipped']}"
    assert outcome["uniform_fraction"] < 0.98, (
        "the language tab photographed as one flat colour; it drew nothing "
        f"({outcome})"
    )
    assert outcome["colours"] >= capture.MIN_DISTINCT_COLOURS


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
