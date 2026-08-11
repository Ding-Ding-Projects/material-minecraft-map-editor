from pathlib import Path

import pytest

BASE = Path("amulet_map_editor/api/wx/ui/base_select.py").read_text(encoding="utf-8")
DIALOG = Path("amulet_map_editor/api/wx/ui/regex_dialog.py").read_text(encoding="utf-8")


def test_base_select_has_adjacent_regex_builder_and_bounded_search():
    assert "RegexBuilderDialog" in BASE
    assert 'label="Regex…"' in BASE
    assert "RegexBuilder(" in BASE
    assert "search_str[:4096]" in BASE


def test_regex_builder_dialog_is_m3_styled_and_validates_samples():
    assert "wx.NO_BORDER | wx.RESIZE_BORDER" in DIALOG
    assert "apply_material3(self)" in DIALOG
    assert ".evaluate(" in DIALOG
    assert ".validate()" in DIALOG


@pytest.fixture
def builder():
    """A constructed builder, with a live app and a parent to hang it on."""
    wx = pytest.importorskip("wx")
    from amulet_map_editor.api.wx.ui.regex_dialog import RegexBuilderDialog

    # Held in a local: an unassigned ``wx.App()`` is collected immediately and
    # the next wx call raises "The wx.App object must be created first!".
    app = wx.App.Get() or wx.App()
    assert app is not None
    frame = wx.Frame(None)
    dialog = RegexBuilderDialog(frame, pattern="chunk ", sample="chunk 12\nchunk 340")
    try:
        yield wx, dialog
    finally:
        dialog.Destroy()
        frame.Destroy()


def test_the_builder_opens_wide_enough_to_read_a_pattern_in(builder):
    """It used to open 182 pixels wide and stay there until dragged.

    ``SetSizerAndFit`` sized the window to its narrowest child and the
    ``SetMinSize`` after it only constrained later dragging, so the builder
    every search field in the product opens appeared as a column too narrow to
    read a pattern in. A minimum is not a size.
    """
    _wx, dialog = builder
    size = dialog.GetSize()
    minimum = dialog.GetMinSize()
    assert size.width >= minimum.width, (
        f"the builder opened {size.width}px wide against a {minimum.width}px "
        "minimum, so its own floor is not being applied to its first appearance"
    )
    assert size.width >= 400, f"{size.width}px is too narrow to read a pattern in"


def test_the_token_buttons_build_a_pattern_at_the_caret(builder):
    """The guided construction the design asks a builder for, actually building.

    A row of buttons that looks like a palette and inserts nothing is the
    decorative-control defect, so this presses them and reads the field back.
    """
    _wx, dialog = builder
    dialog.pattern_input.SetValue("chunk ")
    dialog.pattern_input.SetInsertionPointEnd()

    digits = next(
        button for button in dialog.token_buttons if button.GetLabel() == "\\d"
    )
    digits.activate()
    assert dialog.pattern_input.GetValue() == "chunk \\d"

    plus = next(button for button in dialog.token_buttons if button.GetLabel() == "+")
    plus.activate()
    assert dialog.pattern_input.GetValue() == "chunk \\d+"

    # A pair goes in whole and leaves the caret between its halves, which is
    # where the next character belongs.
    group = next(button for button in dialog.token_buttons if button.GetLabel() == "()")
    group.activate()
    assert dialog.pattern_input.GetValue() == "chunk \\d+()"
    assert dialog.pattern_input.GetInsertionPoint() == len("chunk \\d+(")


def test_the_builder_reports_what_the_pattern_actually_matched(builder):
    """A count says the pattern compiled; the preview says what it caught."""
    _wx, dialog = builder
    dialog.regex_toggle.SetValue(True)
    dialog.pattern_input.SetValue("chunk \\d+")
    dialog._validate(None)
    assert "2 sample match" in dialog.validation.GetLabel()
    preview = dialog.preview.GetLabel()
    assert "chunk 12" in preview and "chunk 340" in preview, preview


def test_enter_applies_and_escape_cancels(builder):
    """Owner-drawn actions carry no dialog ids, so both keys are bound by hand.

    A native ``wx.ID_OK``/``wx.ID_CANCEL`` pair gave these two keys their
    meaning for free. Replacing those buttons without rebinding the keys would
    have silently removed the keyboard route out of this window.
    """
    wx, dialog = builder
    dialog.pattern_input.SetValue("chunk \\d+")

    # Dispatched through the dialog's own event handler rather than by calling
    # the method: a test that calls the handler directly passes whether or not
    # anything is bound to it, which is the wiring this exists to check.
    def press(code):
        event = wx.KeyEvent(wx.wxEVT_CHAR_HOOK)
        event.SetKeyCode(code)
        dialog.GetEventHandler().ProcessEvent(event)

    cancelled = []
    dialog.EndModal = lambda code: cancelled.append(code)
    press(wx.WXK_ESCAPE)
    assert cancelled == [wx.ID_CANCEL], "Escape no longer cancels the builder"

    applied = []
    dialog.EndModal = lambda code: applied.append(code)
    press(wx.WXK_RETURN)
    assert applied == [wx.ID_OK], "Enter no longer applies the built pattern"
    assert dialog.pattern == "chunk \\d+", "Enter applied without carrying the pattern"
