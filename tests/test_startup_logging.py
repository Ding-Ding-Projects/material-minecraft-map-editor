"""A fault in this application must survive past the moment it happened.

Before this module existed, the only evidence of a broken screen was a user's
screenshot, and an agent had to reason backwards from a picture. These tests
prove the startup diagnostic block actually lands in the real log file, that
an exception raised inside a wx event handler reaches it too, and that the
one surface explicitly carved out as secret-adjacent -- the display-text
overlay -- never does.
"""

from __future__ import annotations

import logging
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import wx

from amulet_map_editor.api import startup_diagnostics
import amulet_map_editor

assert amulet_map_editor.__file__.startswith(REPO_ROOT)


def _make_logger(tmp_path, name: str) -> tuple:
    """Return a file-backed logger and the path it writes to."""
    log_path = str(tmp_path / f"{name}.log")
    logger = logging.getLogger(f"amulet_test.{name}")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    logger.addHandler(handler)
    return logger, handler, log_path


def _read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def test_startup_report_contains_dpi_mode_and_display_geometry(tmp_path):
    logger, handler, log_path = _make_logger(tmp_path, "startup")
    try:
        frame = wx.Frame(None, size=wx.Size(800, 600))
        try:
            report = startup_diagnostics.log_startup(
                logger, window=frame, repo_root=REPO_ROOT
            )
        finally:
            frame.Destroy()
    finally:
        handler.close()
        logger.removeHandler(handler)

    assert "dpi_awareness=" in report
    assert "display[0]:" in report
    assert "window[actual]:" in report
    assert "window[min]:" in report
    assert "theme=" in report
    assert "language_mode=" in report

    on_disk = _read(log_path)
    assert "Startup diagnostics:" in on_disk
    assert "dpi_awareness=" in on_disk
    assert "display[0]:" in on_disk


def test_startup_report_without_a_window_says_so(tmp_path):
    logger, handler, _ = _make_logger(tmp_path, "no_window")
    try:
        report = startup_diagnostics.build_report(window=None, repo_root=REPO_ROOT)
    finally:
        handler.close()
        logger.removeHandler(handler)
    assert "window: none constructed yet" in report


def test_exception_in_event_handler_reaches_the_log_file(tmp_path):
    logger, handler, log_path = _make_logger(tmp_path, "handler_fault")

    def error_hook(exc_type, exc_value, exc_tb):
        if exc_value is None:
            return
        logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    previous_hook = sys.excepthook
    sys.excepthook = error_hook
    frame = wx.Frame(None)
    button = wx.Button(frame, label="boom")

    def _boom(_event):
        raise RuntimeError("deliberate handler fault for logging coverage")

    button.Bind(wx.EVT_BUTTON, _boom)
    try:
        # wx.App routes an exception raised inside a bound event handler to
        # sys.excepthook rather than letting it propagate to this call --
        # ProcessEvent itself must not raise, or the fault never reached the
        # log the way it does for a real click.
        button.ProcessEvent(wx.CommandEvent(wx.EVT_BUTTON.typeId, button.GetId()))
    finally:
        sys.excepthook = previous_hook
        frame.Destroy()
        handler.close()
        logger.removeHandler(handler)

    on_disk = _read(log_path)
    assert "Unhandled exception" in on_disk
    assert "deliberate handler fault for logging coverage" in on_disk


def test_text_overlay_module_never_touches_logging():
    """The display-text overlay is explicitly excluded from every log."""
    import amulet_map_editor.api.text_overlay as text_overlay

    source_path = text_overlay.__file__
    with open(source_path, "r", encoding="utf-8") as fp:
        source = fp.read()
    assert "logging" not in source
    assert "log.debug" not in source
    assert "log.info" not in source
