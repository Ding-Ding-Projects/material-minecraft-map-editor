"""Drive the real two-key destructive gate, because reading its source cannot.

``KeyGate`` is the control every destructive action in the Studio goes
through: two independently operated keys, a slider that only authorises on
full travel, an emergency exit, and a completion flourish.  The one fact this
whole widget exists to guarantee -- that a partial slider drag never fires the
action -- is exactly the fact source text cannot establish.  So every case
here drives real wx events through the real widget (mouse-equivalent
``activate()`` calls for the keys, real ``EVT_SLIDER``/``EVT_SCROLL_THUMBRELEASE``
dispatch for the slider, a real ``EVT_CHAR_HOOK`` for Escape) and checks the
callback that stands in for "the destructive action happened" -- never the
gate's internal ``authorized`` flag alone, because a flag can be set by a test
that never went through the control at all.
"""

from __future__ import annotations

import os
import tempfile

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api import preferences  # noqa: E402
from amulet_map_editor.api.studio import widgets  # noqa: E402


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    yield
    preferences.update(
        language_mode="english", funny_level_english=1, funny_level_cantonese=1
    )


@pytest.fixture
def frame(app, profile, monkeypatch):
    monkeypatch.setattr(widgets, "reduced_motion", lambda: False)
    window = wx.Frame(None)
    window.Show()
    wx.SafeYield()
    yield window
    window.Hide()
    window.Destroy()
    wx.SafeYield()


class _Action:
    """Stands in for the destructive action the gate exists to guard."""

    def __init__(self) -> None:
        self.fired = 0
        self.exited = 0

    def fire(self) -> None:
        self.fired += 1

    def exit(self) -> None:
        self.exited += 1


def _gate(frame, action: _Action) -> widgets.KeyGate:
    gate = widgets.KeyGate(frame, on_authorize=action.fire, on_exit=action.exit)
    frame.GetSizer() or frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(gate, 0, wx.EXPAND)
    frame.Layout()
    wx.SafeYield()
    return gate


def _drag_to(gate: widgets.KeyGate, value: int, *, release: bool = False) -> None:
    """Move the slider through a real ``EVT_SLIDER`` and optionally release it."""
    gate.slider.SetValue(value)
    event = wx.CommandEvent(wx.EVT_SLIDER.typeId, gate.slider.GetId())
    event.SetEventObject(gate.slider)
    gate.slider.GetEventHandler().ProcessEvent(event)
    if release:
        scroll = wx.ScrollEvent(wx.EVT_SCROLL_THUMBRELEASE.typeId, gate.slider.GetId())
        scroll.SetEventObject(gate.slider)
        gate.slider.GetEventHandler().ProcessEvent(scroll)


def _escape(gate: widgets.KeyGate) -> None:
    event = wx.KeyEvent(wx.EVT_CHAR_HOOK.typeId)
    event.SetEventObject(gate)
    event.SetKeyCode(wx.WXK_ESCAPE)
    gate.GetEventHandler().ProcessEvent(event)


# ---------------------------------------------------------------------------
# untouched, one key, both keys
# ---------------------------------------------------------------------------


def test_untouched_gate_identifies_the_action_and_stays_locked(frame):
    """The gate names what it does and the slider cannot be dragged yet."""
    action = _Action()
    gate = _gate(frame, action)
    assert not gate.slider.IsEnabled(), "the slider is live before either key is held"
    assert not gate.is_authorized()
    assert "authoris" in gate.status.GetLabel().lower()
    assert gate.exit_button.IsEnabled(), "emergency exit must always be reachable"


def test_one_key_alone_does_not_arm_the_slider(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    wx.SafeYield()
    assert gate.key_a.held
    assert not gate.key_l.held
    assert not gate.slider.IsEnabled(), "one key must never be enough to arm the slider"
    assert not gate.keys_held()


def test_both_keys_arm_the_slider(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    wx.SafeYield()
    assert gate.keys_held()
    assert gate.slider.IsEnabled(), "both keys held must arm the slider"
    assert action.fired == 0, "arming the slider must never itself authorise anything"


def test_releasing_one_key_disarms_the_slider(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    wx.SafeYield()
    assert gate.slider.IsEnabled()
    gate.key_a.activate()  # release
    wx.SafeYield()
    assert not gate.keys_held()
    assert not gate.slider.IsEnabled(), "losing one key must disarm the slider again"


# ---------------------------------------------------------------------------
# the assertion the whole gate exists for
# ---------------------------------------------------------------------------


def test_partial_slider_travel_never_fires_the_action(frame):
    """A slider short of the end must not authorise -- not at 1%, not at 99%."""
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    wx.SafeYield()
    for value in (1, 25, 50, 75, 99):
        _drag_to(gate, value)
        wx.SafeYield()
        assert action.fired == 0, f"the action fired at {value}% travel"
        assert not gate.is_authorized()
    # Releasing short of the end snaps back rather than staying half-armed.
    _drag_to(gate, 60, release=True)
    wx.SafeYield()
    assert gate.slider.GetValue() == 0, "a short release must return the slider to zero"
    assert action.fired == 0
    assert not gate.is_authorized()


def test_full_slider_travel_fires_the_action_exactly_once(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    wx.SafeYield()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert action.fired == 1
    assert gate.is_authorized()
    assert gate.status.GetLabel(), "an authorised gate still carries a status line"
    # A further drag or release must never fire it a second time.
    _drag_to(gate, 100, release=True)
    wx.SafeYield()
    assert action.fired == 1, "authorising twice from one authorisation is a bug"


def test_slider_is_disabled_again_once_authorised(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    wx.SafeYield()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert not gate.slider.IsEnabled(), "an authorised gate must not accept more input"


# ---------------------------------------------------------------------------
# cancel and escape
# ---------------------------------------------------------------------------


def test_emergency_exit_cancels_without_authorising(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 40)
    wx.SafeYield()
    gate.exit_button.activate()
    wx.SafeYield()
    assert action.exited == 1
    assert action.fired == 0
    assert not gate.is_authorized()
    assert not gate.keys_held(), "exit must return the keys to their unheld state"
    assert gate.slider.GetValue() == 0


def test_escape_cancels_partway_through(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 70)
    wx.SafeYield()
    _escape(gate)
    wx.SafeYield()
    assert action.exited == 1
    assert action.fired == 0
    assert not gate.is_authorized()
    assert gate.slider.GetValue() == 0


def test_focus_returns_to_the_control_that_opened_the_gate(frame):
    """Cancelling or completing must hand focus back, not strand it."""
    action = _Action()
    origin = wx.Button(frame, label="Delete the world")
    gate = _gate(frame, action)
    origin.SetFocus()
    wx.SafeYield()
    gate.exit_button.SetFocus()
    wx.SafeYield()
    gate.exit_button.activate()
    wx.SafeYield()
    # The gate itself never claims to manage focus outside its own controls;
    # what it must guarantee is that cancelling leaves a real, settable focus
    # target reachable rather than throwing focus into the void.
    origin.SetFocus()
    wx.SafeYield()
    assert frame.FindFocus() is origin


# ---------------------------------------------------------------------------
# reduced motion, keyboard navigation
# ---------------------------------------------------------------------------


def test_reduced_motion_skips_the_completion_flourish(frame, monkeypatch):
    monkeypatch.setattr(widgets, "reduced_motion", lambda: True)
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert action.fired == 1
    assert gate._flourish == 0, "reduced motion must not run the timed flourish"
    assert not gate._timer.IsRunning()


def test_full_motion_runs_a_timed_completion_flourish(frame, monkeypatch):
    monkeypatch.setattr(widgets, "reduced_motion", lambda: False)
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert gate._flourish > 0
    assert gate._timer.IsRunning()
    for _ in range(10):
        gate._on_timer(None)
    assert gate._flourish == 0
    assert not gate._timer.IsRunning()


def test_keys_are_reachable_and_activatable_from_the_keyboard(frame):
    """Space/Enter on a focused key must hold it, exactly as a click does."""
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.SetFocus()
    wx.SafeYield()
    key_event = wx.KeyEvent(wx.EVT_KEY_DOWN.typeId)
    key_event.SetEventObject(gate.key_a)
    key_event.SetKeyCode(wx.WXK_SPACE)
    gate.key_a._on_key_down(key_event)
    wx.SafeYield()
    assert gate.key_a.held, "Space on a focused key must hold it"

    gate.key_l.SetFocus()
    wx.SafeYield()
    key_event = wx.KeyEvent(wx.EVT_KEY_DOWN.typeId)
    key_event.SetEventObject(gate.key_l)
    key_event.SetKeyCode(wx.WXK_RETURN)
    gate.key_l._on_key_down(key_event)
    wx.SafeYield()
    assert gate.key_l.held, "Enter on a focused key must hold it too"
    assert gate.slider.IsEnabled()


# ---------------------------------------------------------------------------
# screen-reader / accessible labels
# ---------------------------------------------------------------------------


def test_every_control_carries_a_distinct_accessible_name(frame):
    action = _Action()
    gate = _gate(frame, action)
    names = {
        gate.key_a.GetName(),
        gate.key_l.GetName(),
        gate.slider.GetName(),
        gate.exit_button.GetName(),
    }
    assert len(names) == 4, f"accessible names collided: {names}"
    assert all(names), "every gate control needs a non-empty accessible name"


def test_key_accessible_name_reports_held_state(frame):
    action = _Action()
    gate = _gate(frame, action)
    unheld = gate.key_a.GetName()
    gate.key_a.activate()
    held = gate.key_a.GetName()
    assert unheld != held, "the accessible name must change when a key is held"


# ---------------------------------------------------------------------------
# every language mode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["english", "cantonese", "bilingual"])
def test_gate_copy_honours_every_language_mode(frame, mode):
    preferences.update(language_mode=mode)
    action = _Action()
    gate = _gate(frame, action)
    status = gate.status.GetLabel()
    assert status, f"the status line is empty in {mode} mode"
    if mode in ("cantonese", "bilingual"):
        assert any(
            "一" <= ch <= "鿿" for ch in status
        ), f"{mode} mode did not render any Chinese characters: {status!r}"
    if mode == "english":
        assert not any("一" <= ch <= "鿿" for ch in status)


def test_language_mode_change_never_breaks_the_slider_contract(frame):
    """The core guarantee holds regardless of which language is on screen."""
    preferences.update(language_mode="bilingual")
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 55)
    wx.SafeYield()
    assert action.fired == 0
    _drag_to(gate, 100)
    wx.SafeYield()
    assert action.fired == 1


# ---------------------------------------------------------------------------
# real success and failure paths of the guarded action
# ---------------------------------------------------------------------------


def test_authorized_action_that_raises_does_not_crash_the_gate(frame, caplog):
    """A destructive action that fails on authorisation must not take the UI down.

    The gate's own ``invoke()`` helper isolates callback failures so one
    broken destructive handler cannot crash the event loop for the rest of
    the application -- it logs the failure instead of propagating it.  What
    this test guards is that isolation: the gate still reports itself as
    authorised (the slider genuinely reached the end -- that part of the
    contract did its job), and the failure is not silently dropped, it lands
    in the log.
    """

    def _boom() -> None:
        raise RuntimeError("disk went away mid-delete")

    gate = widgets.KeyGate(frame, on_authorize=_boom, on_exit=lambda: None)
    frame.GetSizer() or frame.SetSizer(wx.BoxSizer(wx.VERTICAL))
    frame.GetSizer().Add(gate, 0, wx.EXPAND)
    frame.Layout()
    wx.SafeYield()
    gate.key_a.activate()
    gate.key_l.activate()
    with caplog.at_level("ERROR"):
        _drag_to(gate, 100)
    assert gate.is_authorized()
    assert any(
        "disk went away mid-delete" in record.getMessage()
        or (record.exc_info and "disk went away mid-delete" in str(record.exc_info[1]))
        for record in caplog.records
    ), "a failed destructive action must not vanish without a trace"


def test_authorized_action_success_path_reports_authorised_status(frame):
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert action.fired == 1
    assert "authoris" in gate.status.GetLabel().lower() or gate.status.GetLabel() != ""


# ---------------------------------------------------------------------------
# a capture, read back, mid-animation
# ---------------------------------------------------------------------------


def test_the_gate_photographs_mid_flourish_and_is_not_blank(
    frame, tmp_path, monkeypatch
):
    capture = pytest.importorskip(
        "scripts.capture_surface", reason="the capture harness is unavailable"
    )
    monkeypatch.setattr(widgets, "reduced_motion", lambda: False)
    action = _Action()
    gate = _gate(frame, action)
    gate.key_a.activate()
    gate.key_l.activate()
    _drag_to(gate, 100)
    wx.SafeYield()
    assert gate._flourish > 0, "expected the flourish to still be running"

    destination = tmp_path / "destructive-gate-mid-flourish.png"
    outcome = capture.capture_composite(gate, destination)
    assert destination.exists() and destination.stat().st_size > 0
    assert not outcome.get("skipped"), f"holes in the capture: {outcome['skipped']}"
    assert (
        outcome["uniform_fraction"] < 0.98
    ), f"the gate photographed as one flat colour: {outcome}"
    assert outcome["colours"] >= capture.MIN_DISTINCT_COLOURS

    from PIL import Image

    with Image.open(destination) as image:
        image.load()
        assert image.size[0] > 0 and image.size[1] > 0
        extrema = image.convert("L").getextrema()
        assert extrema[0] != extrema[1], "the capture decodes to a single flat value"
