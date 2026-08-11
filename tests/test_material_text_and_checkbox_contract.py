"""Build the two Material primitives and the surfaces that now use them.

Every assertion here constructs a real control and asks it a question its own
drawing code has to answer.  None of it reads source text, deliberately: a
source-text test for this lane would pass on a widget that renders nothing,
which is precisely the failure the widgets exist to fix.

Two distinct claims are checked, because a migration can break either half
while leaving the other perfect:

* the primitives *behave* -- a checkbox posts the event a ``wx.CheckBox``
  posts, keeps the accessible name a surface gave it, and re-measures when its
  label changes;
* the migrated surfaces *draw* -- every text and boolean control on them
  answers ``render_to``, so a capture on a desktop nobody is looking at shows
  them rather than leaving blank rectangles where they were.

The second claim is the one a source-text test cannot make at all.  Before this
lane, the shipped capture of the navigator showed an empty column: three
``wx.StaticText`` empty-state notes were present, laid out, and invisible,
because a native control photographed off-screen has no surface to read back.
"""

from __future__ import annotations

import os
import tempfile

import pytest

wx = pytest.importorskip("wx")


@pytest.fixture(scope="module")
def app():
    """A live wx.App on an isolated profile, so a run cannot touch real settings."""
    os.environ.setdefault("CONFIG_DIR", tempfile.mkdtemp(prefix="amulet-material-"))
    application = wx.App()
    yield application


@pytest.fixture()
def frame(app):
    """An off-screen frame to build controls inside, destroyed after each test."""
    window = wx.Frame(None, size=(600, 400), pos=(-32000, -32000))
    panel = wx.Panel(window)
    window.Show()
    wx.Yield()
    try:
        yield panel
    finally:
        window.Destroy()


# ---------------------------------------------------------------------------
# the checkbox behaves like the control it replaces
# ---------------------------------------------------------------------------
def test_the_checkbox_posts_the_event_a_native_checkbox_posts(frame) -> None:
    """Activation must reach a handler bound to ``wx.EVT_CHECKBOX``.

    This is what makes the widget a drop-in.  Every migrated surface binds that
    event and reads ``IsChecked`` off it, so a control that changed its own
    value without posting the event would leave each of those surfaces showing
    a ticked box and acting on the opposite state -- with nothing failing.
    """
    from amulet_map_editor.api.studio.widgets import StudioCheckBox

    box = StudioCheckBox(frame, "Regex")
    seen: list[bool] = []
    box.Bind(wx.EVT_CHECKBOX, lambda event: seen.append(event.IsChecked()))

    box.activate()
    assert seen == [True], "activating the box posted no EVT_CHECKBOX carrying True"
    assert box.GetValue() is True
    assert box.IsChecked() is True

    box.activate()
    assert seen == [True, False], "the second activation did not post False"
    assert box.GetValue() is False


def test_setting_the_checkbox_value_does_not_post_an_event(frame) -> None:
    """``SetValue`` is silent, exactly as ``wx.CheckBox.SetValue`` is.

    A surface that restores a stored setting calls this during construction.  If
    it posted, every such surface would re-enter its own change handler while
    still being built and write the restored value back out as a user edit.
    """
    from amulet_map_editor.api.studio.widgets import StudioCheckBox

    box = StudioCheckBox(frame, "Regex")
    seen: list[bool] = []
    box.Bind(wx.EVT_CHECKBOX, lambda event: seen.append(event.IsChecked()))

    box.SetValue(True)
    assert box.GetValue() is True
    assert seen == [], f"SetValue posted an event it should not have: {seen!r}"


def test_the_checkbox_keyboard_path_works(frame) -> None:
    """Space must operate it.  A pointer-only control is a completion blocker."""
    from amulet_map_editor.api.studio.widgets import StudioCheckBox

    box = StudioCheckBox(frame, "Regex")
    event = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    event.SetEventObject(box)
    # ``SetKeyCode``, not the ``m_keyCode`` member: on wxPython 4.3.1 assigning
    # the member is silently inert and ``GetKeyCode`` keeps answering 0, so a
    # test written that way asserts that the widget ignores key code zero --
    # which it correctly does, for every key.
    event.SetKeyCode(wx.WXK_SPACE)
    assert event.GetKeyCode() == wx.WXK_SPACE, "the synthetic event carries no key"
    box.GetEventHandler().ProcessEvent(event)
    assert box.GetValue() is True, "Space did not tick the box"


def test_the_checkbox_grows_to_fit_a_longer_label(frame) -> None:
    """A relabelled box re-measures, so its own text cannot be cut off.

    The minimum size is the assertion, not the best size: a best size computed
    on demand grows whether or not the control ever told its sizer, and the
    minimum is what the layout actually gives it.
    """
    from amulet_map_editor.api.studio.widgets import StudioCheckBox

    box = StudioCheckBox(frame, "On")
    narrow = box.GetMinSize().width
    box.SetLabel("A considerably longer explanation of what this does")
    assert box.GetMinSize().width > narrow


# ---------------------------------------------------------------------------
# the text control behaves like the control it replaces
# ---------------------------------------------------------------------------
def test_relabelling_keeps_an_accessible_name_a_surface_chose(frame) -> None:
    """A named status line must not rename itself to its latest message.

    ``wx.StaticText`` never did, and several surfaces rely on it: the local
    history filter status, the navigator search result, the tab-group results.
    A screen-reader user navigating by name would otherwise find a differently
    named control every time the text changed.
    """
    from amulet_map_editor.api.studio.widgets import StudioText

    named = StudioText(frame, "12 events", name="Local history filter status")
    named.SetLabel("Invalid history filter: bad escape")
    assert named.GetName() == "Local history filter status"

    # A control given no name still describes itself by its text, which is what
    # makes an unnamed caption reachable at all.
    anonymous = StudioText(frame, "Selection boxes")
    anonymous.SetLabel("Dimensions")
    assert anonymous.GetName() == "Dimensions"


def test_wrapping_is_not_destructive(frame) -> None:
    """Re-wrapping narrower then wider must recover the original layout.

    ``wx.StaticText.Wrap`` wrote newlines back into the label, so wrapping an
    already-wrapped string again fragmented it further every time.  The
    navigator re-wraps its empty-state notes on every rebuild.
    """
    from amulet_map_editor.api.studio.widgets import StudioText

    note = StudioText(frame, "No world is open, so there are no dimensions to list.")
    wide = note.DoGetBestSize()
    note.Wrap(120)
    narrow = note.DoGetBestSize()
    assert narrow.height > wide.height, "wrapping narrower did not add lines"
    note.Wrap(0)
    assert note.DoGetBestSize().height == wide.height, "the text did not recover"
    assert "\n" not in note.GetLabel(), "wrapping wrote newlines into the label"


def test_an_explicit_foreground_colour_wins_over_the_role(frame) -> None:
    """A caller that paints its own error ink means it.

    The search feedback line and the title bar's save state both set a colour
    directly, and both would silently lose it to the palette role otherwise.
    """
    from amulet_map_editor.api.studio import tokens
    from amulet_map_editor.api.studio.widgets import StudioText

    palette = tokens.palette()
    line = StudioText(frame, "Invalid filter", role="on_surface_variant")
    assert line._ink(palette) == palette.on_surface_variant

    line.SetForegroundColour(palette.error)
    assert line._ink(palette) == palette.error

    line.set_role("on_surface_variant")
    assert line._ink(palette) == palette.on_surface_variant


def test_both_controls_re_measure_when_the_interface_scale_changes(
    frame, monkeypatch
) -> None:
    """A scale change must move the control, not just the text inside it.

    This is the one behaviour the migration could have quietly dropped.  The
    native controls were re-measured as a side effect of the ``SetFont`` every
    surface pushed into them on a theme change; nothing pushes a font into an
    owner-drawn control, so it has to re-measure itself when asked to refresh.
    Without it a user who raises the interface scale gets larger text inside
    controls that stayed the size they were -- every label clipped, and no test
    that reads source could see it.
    """
    from amulet_map_editor.api import preferences
    from amulet_map_editor.api.studio import tokens
    from amulet_map_editor.api.studio.widgets import StudioCheckBox, StudioText

    text = StudioText(frame, "Unsaved changes")
    box = StudioCheckBox(frame, "Use a regular expression")
    # The MINIMUM size, not the best size.  A best size computed live answers
    # the new scale whether or not the control ever re-measured, so a guard
    # written against it stays green on a control that never updates -- and the
    # minimum is what a sizer actually lays the control out at, which is the
    # thing that clips the text when it goes stale.
    before = (text.GetMinSize().width, box.GetMinSize().width)

    doubled = preferences.Preferences(ui_scale=2.0).normalised()
    monkeypatch.setattr(tokens, "_presentation", lambda: doubled)
    text.refresh_theme()
    box.refresh_theme()
    after = (text.GetMinSize().width, box.GetMinSize().width)

    assert (
        after[0] > before[0]
    ), f"the text did not re-measure at twice the scale: {before[0]} -> {after[0]}"
    assert (
        after[1] > before[1]
    ), f"the checkbox did not re-measure at twice the scale: {before[1]} -> {after[1]}"


# ---------------------------------------------------------------------------
# the migrated surfaces draw
# ---------------------------------------------------------------------------
#: Surfaces this lane migrated, and the widget attribute on each that must now
#: be owner-drawn.  It is a hand-written list on purpose: a rule that only
#: checks "every StudioText present renders" passes cleanly on a surface that
#: has none, which is the same surface a migration forgot.
MIGRATED = (
    ("SearchBar.feedback", "feedback"),
    ("SearchBar.regex_box", "regex_box"),
)


@pytest.mark.parametrize("description,attribute", MIGRATED)
def test_the_search_bar_controls_are_owner_drawn(frame, description, attribute) -> None:
    """Every control on a search bar must answer ``render_to``.

    ``SearchBar`` is the highest-multiplier surface in the shell: three
    constructor lines in it account for several hundred controls across the
    interface, so a native control here is a native control everywhere.
    """
    from amulet_map_editor.api.studio.search import SearchState
    from amulet_map_editor.api.studio.widgets import SearchBar

    bar = SearchBar(frame, "Search", SearchState(label="Test"))
    control = getattr(bar, attribute)
    assert control is not None, f"{description} is missing"
    assert callable(
        getattr(control, "render_to", None)
    ), f"{description} has no render_to, so it photographs as a blank rectangle"


def test_no_migrated_surface_still_builds_a_native_text_or_checkbox(frame) -> None:
    """Walk the built surfaces and fail on a native label or box that survived.

    This asks the constructed window tree, not the source, so it cannot be
    satisfied by a call that was renamed or by a file that no longer builds the
    control it used to.  ``wx.TextCtrl`` and ``wx.Slider`` are deliberately
    exempt: a field has to be editable and a slider already carries the arrow,
    page, and home/end handling plus the screen-reader value announcement that
    a painted track would have to reproduce.
    """
    from amulet_map_editor.api.studio.search import SearchState
    from amulet_map_editor.api.studio.widgets import RangeRow, SearchBar

    surfaces = {
        "SearchBar": SearchBar(frame, "Search", SearchState(label="Test")),
        "RangeRow": RangeRow(frame, "Speed", 4, 1, 10),
    }

    offenders: list[str] = []
    for name, surface in surfaces.items():
        pending = [surface]
        while pending:
            window = pending.pop()
            for child in window.GetChildren():
                if isinstance(child, (wx.StaticText, wx.CheckBox)):
                    offenders.append(
                        f"{name}: {type(child).__name__} {child.GetName()!r}"
                    )
                pending.append(child)
    assert not offenders, "native controls survived the migration: " + "; ".join(
        offenders
    )
