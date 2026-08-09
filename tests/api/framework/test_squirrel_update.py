from pathlib import Path
import sys
import importlib.util

import pytest

_MODULE_PATH = (
    Path(__file__).parents[3] / "amulet_map_editor/api/framework/squirrel_update.py"
)
_SPEC = importlib.util.spec_from_file_location("squirrel_update", _MODULE_PATH)
assert _SPEC and _SPEC.loader
squirrel_update = importlib.util.module_from_spec(_SPEC)
sys.modules["squirrel_update"] = squirrel_update
_SPEC.loader.exec_module(squirrel_update)

SquirrelUpdateState = squirrel_update.SquirrelUpdateState
check_for_update = squirrel_update.check_for_update
find_update_exe = squirrel_update.find_update_exe
stage_update = squirrel_update.stage_update
validate_feed_url = squirrel_update.validate_feed_url


def test_feed_requires_https_and_no_credentials():
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest/download/"
    assert validate_feed_url(feed).startswith("https://")
    with pytest.raises(ValueError):
        validate_feed_url("http://updates.example.test/releases/")
    with pytest.raises(ValueError):
        validate_feed_url("https://user:pass@github.com/releases/")


def test_update_detection_is_explicit(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    assert find_update_exe(updater.parent) == updater


def test_check_reports_available_without_wx(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    # Keep subprocess testing platform-neutral by replacing the bridge runner.
    monkeypatch.setattr(
        squirrel_update,
        "_run_update",
        lambda *_args, **_kwargs: {"futureReleaseEntry": {"version": "1.2.3"}},
    )
    feed = "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest/download/"
    state = check_for_update(feed, update_exe=updater)
    assert state == SquirrelUpdateState("available", version="1.2.3", feed_url=feed)


def test_stage_update_is_ready_and_unsigned(tmp_path, monkeypatch):
    updater = tmp_path / "Update.exe"
    updater.write_bytes(b"fixture")
    monkeypatch.setattr(squirrel_update, "_run_update", lambda *_args, **_kwargs: {})
    state = stage_update(
        "https://github.com/Ding-Ding-Projects/material-minecraft-map-editor/releases/latest/download/",
        update_exe=updater,
    )
    assert state.status == "ready_to_restart"
    assert state.unsigned_warning is True
