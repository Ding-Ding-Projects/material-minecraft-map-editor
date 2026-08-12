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
    # Reuse a live ``wx.App`` when the session already has one, and only
    # create -- and later destroy -- a fresh instance when it does not.
    # Unconditionally creating a second ``wx.App`` while one is already
    # current silently orphans it, and destroying that second instance then
    # clears wx's notion of "the current app" out from under every other
    # test module -- the exact sequence that corrupts wxPython's SIP class
    # table for platform-native widgets such as ``wx.PopupTransientWindow``.
    existing = wx.App.Get()
    created = existing is None and wx.App()
    yield existing or created
    if created:
        created.Destroy()


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

    The label assertion at the end is the one that matters and the one the
    control this replaces fails.  ``wx.StaticText.Wrap`` writes its line breaks
    into the label itself, so ``GetLabel`` answers with newlines the caller
    never set -- and the navigator copies that label straight into an
    accessible name on every rebuild.

    It does *not* degrade cumulatively, which is worth stating because the
    surrounding code used to claim it did: measured on wxWidgets 3.3.3, a
    native ``Wrap`` re-derives from the original text, so the same width twice
    is idempotent and a wider re-wrap restores the string exactly.  Asserting
    the recovery here holds ``StudioText`` to the behaviour that was already
    correct, so a rewrite cannot quietly lose it.
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


def native_leaves(surface: wx.Window, name: str) -> list[str]:
    """Return every ``wx.StaticText`` or ``wx.CheckBox`` under ``surface``.

    ``wx.TextCtrl`` and ``wx.Slider`` are deliberately not looked for, and the
    two are not exempt for the same reason.  A field has to be editable, and it
    does answer ``PrintWindow``, so it photographs.  A slider carries the arrow,
    page, and home/end handling plus the screen-reader value announcement that
    a painted track would have to reproduce -- but it does **not** photograph:
    see ``test_the_surviving_sliders_are_a_known_hole_in_every_capture``, which
    measures that rather than assuming it either way.
    """
    offenders: list[str] = []
    pending = [surface]
    while pending:
        window = pending.pop()
        for child in window.GetChildren():
            if isinstance(child, (wx.StaticText, wx.CheckBox)):
                offenders.append(
                    f"{name}: {type(child).__name__} {child.GetName()!r} "
                    f"label={child.GetLabel()!r} shown={child.IsShown()}"
                )
            pending.append(child)
    return offenders


# ---------------------------------------------------------------------------
# Every surface that must be free of native labels and boxes, listed by hand.
#
# Hand-written is the whole point, and the previous version of this file made
# the argument and then wrote a two-entry list.  A rule shaped "every surface
# that has a StudioText renders it" passes cleanly on a surface that has none,
# so the only thing that catches a migration which skipped a file is a list
# that NAMES the file.  It shipped with SearchBar and RangeRow on it and the
# local-history revision row missing, and that row went on drawing its message
# and its timestamp as two invisible native labels for exactly that reason.
#
# Adding a surface here is cheap; leaving one off is how the last one was
# missed.  A new panel, dialog, or bar belongs on this list in the change that
# adds it.
# ---------------------------------------------------------------------------
def _surface_builders():
    """Return ``(name, builder)`` for every surface the guard must walk.

    Built lazily, inside a function, because importing the studio modules at
    collection time would make an import error look like a collection error.
    """
    from amulet_map_editor.api.studio import (
        memory_console,
        navigator,
        nbt_studio,
        palette_dialog,
        properties_pane,
        ribbon,
        spec_dialog,
        status_bar,
        title_bar,
        widgets,
    )
    from amulet_map_editor.api.studio.search import SearchState

    return (
        ("SearchBar", lambda p: widgets.SearchBar(p, "Search", SearchState(label="T"))),
        ("RangeRow", lambda p: widgets.RangeRow(p, "Speed", 4, 1, 10)),
        ("PathField", lambda p: widgets.PathField(p, "World folder", "")),
        (
            "SearchableChoice",
            lambda p: widgets.SearchableChoice(p, "Dimension", ("overworld", "nether")),
        ),
        ("KeyGate", lambda p: widgets.KeyGate(p)),
        ("BulkActionBar", lambda p: widgets.BulkActionBar(p)),
        (
            "spec_dialog._CommitRow",
            lambda p: spec_dialog._CommitRow(
                p, "Deleted the GitHub account", "3 minutes ago · a1b2c3d", True
            ),
        ),
        (
            "PropertiesPane",
            lambda p: properties_pane.PropertiesPane(p, title="Sunset Ridge"),
        ),
        ("NavigatorPanel", lambda p: navigator.NavigatorPanel(p)),
        (
            "StudioTitleBar",
            lambda p: title_bar.StudioTitleBar(p, p.GetTopLevelParent()),
        ),
        ("StatusBar", lambda p: status_bar.StatusBar(p)),
        ("RibbonBar", lambda p: ribbon.RibbonBar(p)),
        ("CommandPalette", lambda p: palette_dialog.CommandPalette(p)),
        (
            "MemoryConsoleDialog",
            lambda p: memory_console.MemoryConsoleDialog(p.GetTopLevelParent()),
        ),
        (
            "NbtStudioDialog",
            lambda p: nbt_studio.NbtStudioDialog(p.GetTopLevelParent()),
        ),
    )


def test_the_surface_list_covers_every_surface_this_lane_touched() -> None:
    """The hand-written list must not quietly shrink to the easy surfaces.

    Every other assertion in this section iterates that list, so a list that
    lost an entry keeps passing while covering less.  The floor is stated
    rather than derived for the same reason the list is hand-written.
    """
    names = [name for name, _builder in _surface_builders()]
    assert len(names) >= 15, (
        "the surface list has shrunk to "
        f"{len(names)}: {names}. Surfaces are added to it, never removed."
    )
    assert len(set(names)) == len(names), f"a surface is listed twice: {names}"


@pytest.mark.parametrize(
    "name,builder", _surface_builders(), ids=[n for n, _ in _surface_builders()]
)
def test_no_listed_surface_still_builds_a_native_text_or_checkbox(
    frame, name, builder
) -> None:
    """Walk one built surface and fail on a native label or box that survived.

    This asks the constructed window tree, not the source, so it cannot be
    satisfied by a call that was renamed or by a file that no longer builds the
    control it used to.
    """
    surface = builder(frame)
    try:
        offenders = native_leaves(surface, name)
    finally:
        if isinstance(surface, wx.Dialog):
            surface.Destroy()
    assert not offenders, "native controls survived the migration: " + "; ".join(
        offenders
    )


def test_no_spec_dialog_still_builds_a_native_text_or_checkbox(frame) -> None:
    """Sweep every declared surface, not a sample of them.

    The renderer turns one data entry into a window, so a native control in one
    section kind is a native control in every surface that declares it.  The
    swatch hint and the texture identifier were each a single constructor line
    and between them reached eighteen of these dialogs; a sample that happened
    to miss both would have reported the whole set clean.
    """
    from amulet_map_editor.api.studio import specs as registry
    from amulet_map_editor.api.studio.spec_dialog import SpecDialog

    keys = list(registry.keys())
    assert len(keys) >= 100, f"the spec registry has shrunk to {len(keys)} surfaces"

    offenders: list[str] = []
    for key in keys:
        dialog = SpecDialog(frame.GetTopLevelParent(), registry.get(key))
        try:
            offenders.extend(native_leaves(dialog, key))
        finally:
            dialog.Destroy()
    assert not offenders, (
        f"{len(offenders)} native control(s) survived across the spec dialogs: "
        + "; ".join(offenders[:12])
    )


def test_no_shell_view_still_builds_a_native_text_or_checkbox(app) -> None:
    """Sweep the assembled shell, on every backstage tab and the workspace.

    A surface can be clean on its own and still be reached through a shell that
    builds a label of its own around it, so the shell is walked as the user
    meets it rather than as a sum of its parts.  Every tab is visited because a
    tab nobody switched to is a tab whose contents were never built.
    """
    from amulet_map_editor.api.studio import backstage
    from amulet_map_editor.api.studio.shell import StudioShell

    window = wx.Frame(None, size=(1280, 800), pos=(-32000, -32000))
    offenders: list[str] = []
    try:
        shell = StudioShell(window, window)
        window.Show()
        wx.Yield()
        for tab in backstage.TABS:
            shell.show_backstage(tab)
            wx.Yield()
            offenders.extend(native_leaves(shell, f"backstage/{tab}"))
        shell.show_workspace()
        wx.Yield()
        offenders.extend(native_leaves(shell, "workspace"))
    finally:
        window.Destroy()
        wx.Yield()

    # One offender can be reached from several tabs, so report the distinct set
    # rather than a count inflated by the sweep's own repetition.
    distinct = sorted({entry.split(": ", 1)[1] for entry in offenders})
    assert (
        not distinct
    ), f"{len(distinct)} native control(s) survived in the shell: " + "; ".join(
        distinct[:12]
    )


# ---------------------------------------------------------------------------
# The one exemption, measured rather than asserted.
# ---------------------------------------------------------------------------
#: Every ``wx.Slider`` still in the interface, named by where it lives.  The
#: list is hand-written for the reason every list in this file is: a guard that
#: counts whatever it finds cannot tell a slider that was migrated from one
#: that was added, and both change the count.
SURVIVING_SLIDERS = (
    "widgets.RangeRow._slider",
    "widgets.KeyGate.slider",
    "status_bar.StatusBar.speed_slider",
    "nbt_studio._NumberRow.slider",
    "palette_dialog._build_slider",
)


def test_a_native_slider_photographs_as_nothing(app) -> None:
    """Measure the exemption's real cost instead of assuming it away.

    The first version of this file's exemption note said a slider photographs
    through ``PrintWindow`` "for exactly this reason", which reads as a reason
    the exemption is free.  It is not: a bare ``wx.Slider`` composited on an
    off-screen frame comes back a single flat colour, so every slider left in
    the interface is a blank gap in every capture -- the status bar's camera
    speed reads as an empty space between "Speed" and the camera state.

    Recording it as a test rather than a comment means the day a platform or a
    wx release starts answering ``PrintWindow`` for sliders, this goes red and
    somebody deletes the exemption instead of inheriting it forever.
    """
    from scripts.capture_surface import _distinct_colours, _composite

    window = wx.Frame(None, size=(400, 120), pos=(-32000, -32000))
    try:
        panel = wx.Panel(window)
        slider = wx.Slider(panel, value=40, minValue=0, maxValue=100)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(slider, 0, wx.EXPAND | wx.ALL, 10)
        panel.SetSizer(sizer)
        window.Show()
        wx.Yield()
        window.Layout()
        wx.Yield()
        image, _contributed, routes, _skipped, _size, _blitted = _composite(slider)
        colours = _distinct_colours(image)
    finally:
        window.Destroy()
        wx.Yield()

    # What "photographs as nothing" means is that no capture route answered --
    # not that the resulting image has exactly one colour value in it.
    #
    # The colour count was the proxy, and it is a brittle one: it moved from 1
    # to 2 without any route starting to work, which failed this test while the
    # thing it guards was completely unchanged. A background that renders as
    # two near-identical values, an anti-aliased edge, or a theme tweak is
    # enough to shift it. Asserting on the routes measures the actual claim,
    # and the colour count stays as a loose sanity bound so a slider that
    # genuinely started drawing still trips this.
    answered = [name for name, count in routes.items() if count]
    assert not answered, (
        f"a native slider now photographs through {answered} (routes {routes}, "
        f"{colours} distinct colours). If that is real, the slider exemption in "
        "native_leaves has stopped costing anything and the note above it is "
        "out of date -- delete the exemption rather than inheriting it."
    )
    assert colours <= 4, (
        f"no capture route answered, yet the slider came back with {colours} "
        "distinct colours. That is not the flat nothing this exemption is "
        "documented as costing, so the note above it no longer describes what "
        "actually happens."
    )


def test_the_surviving_sliders_are_a_known_hole_in_every_capture() -> None:
    """The exempt sliders are enumerated, so a new one cannot arrive silently.

    Given the test above, every entry here is a control that is present, laid
    out, operable, and invisible in a capture.  Five is the debt this lane did
    not pay; the list exists so the number cannot grow without somebody saying
    so in a diff.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "amulet_map_editor" / "api" / "studio"
    found: list[str] = []
    for path in sorted(root.glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if re.search(r"\bwx\.Slider\(", line):
                found.append(f"{path.name}:{number}")

    assert len(found) == len(SURVIVING_SLIDERS), (
        f"{len(found)} wx.Slider construction site(s) exist "
        f"({', '.join(found)}) but {len(SURVIVING_SLIDERS)} are listed. Every "
        "one of them is invisible in a capture, so the list has to be kept "
        "honest: add a new slider to SURVIVING_SLIDERS, or remove an entry "
        "when its surface is migrated."
    )
