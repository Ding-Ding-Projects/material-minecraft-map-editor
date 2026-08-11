"""The shared Material dialog scaffold, driven rather than read.

Every assertion here exists because the corresponding defect is invisible to a
source-text check.

The one that matters most is :func:`test_the_record_table_actually_paints_its
_rows`.  A painted widget that never overrides ``render_to`` inherits the
backdrop-only default: it draws correctly on screen through its own paint
handler, photographs as a blank rectangle, and the capture report calls that
success -- ``routes: {render: 1}``, ``skipped: []``.  That is the exact reason
the record table exists at all, so it is the exact thing worth proving.
"""

from __future__ import annotations

import pytest

wx = pytest.importorskip("wx")

from amulet_map_editor.api.studio import tokens  # noqa: E402
from amulet_map_editor.api.wx.ui import material_dialog as md  # noqa: E402

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = (-32000, -32000)


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = None
    if existing is None:
        created = wx.App(False)
    yield existing or created


@pytest.fixture
def frame(app):
    window = wx.Frame(None, size=wx.Size(640, 480))
    window.SetPosition(wx.Point(*OFFSCREEN))
    try:
        yield window
    finally:
        window.Destroy()


def _render(widget, width=520, height=260):
    """Return the image ``widget.render_to`` draws, on an unmistakable backdrop.

    Magenta, so a rectangle the widget never touched is obvious rather than
    plausible.
    """
    bitmap = wx.Bitmap(width, height, 24)
    memory = wx.MemoryDC(bitmap)
    memory.SetBackground(wx.Brush(wx.Colour(255, 0, 255)))
    memory.Clear()
    context = wx.GCDC(memory)
    widget.render_to(context, wx.Rect(0, 0, width, height))
    del context
    memory.SelectObject(wx.NullBitmap)
    return bitmap.ConvertToImage()


def _colours(image, region=None):
    """Return the distinct colours inside ``region`` of ``image``."""
    area = region or wx.Rect(0, 0, image.GetWidth(), image.GetHeight())
    seen = set()
    for x in range(area.x, min(area.GetRight(), image.GetWidth() - 1), 2):
        for y in range(area.y, min(area.GetBottom(), image.GetHeight() - 1), 2):
            seen.add((image.GetRed(x, y), image.GetGreen(x, y), image.GetBlue(x, y)))
    return seen


def _ink(image, region):
    """Return how many pixels in ``region`` are dark enough to be text.

    This is the assertion that discriminates, and the weaker one it replaces is
    why it is written this way. Counting distinct colours over the whole widget
    passes on a table that drew only its own rounded outline: an antialiased
    border contributes dozens of shades on its own, so a surface with no text
    whatever cleared a colour-count threshold comfortably. Row ink is near-black
    on a near-white fill, and an empty band has none of it.
    """
    found = 0
    for x in range(region.x, min(region.GetRight(), image.GetWidth() - 1)):
        for y in range(region.y, min(region.GetBottom(), image.GetHeight() - 1)):
            red, green, blue = (
                image.GetRed(x, y),
                image.GetGreen(x, y),
                image.GetBlue(x, y),
            )
            if red < 120 and green < 120 and blue < 120:
                found += 1
    return found


def _row_band(table, width, height):
    """Return the rectangle the rows are drawn in, below the header."""
    top = tokens.scaled(table.HEADER_HEIGHT) + 2
    return wx.Rect(0, top, width, max(0, height - top - 2))


def test_the_record_table_actually_paints_its_rows(frame):
    """Drive ``render_to`` into a bitmap and look for the row text in it.

    A widget that draws in ``EVT_PAINT`` and never overrides ``render_to``
    photographs as an empty rectangle while the capture report calls it drawn.
    This is the whole reason the table exists rather than a ``wx.ListCtrl``, so
    it is what gets proved: the rows are read back out of the bitmap.
    """
    width, height = 520, 260
    empty = md.RecordTable(frame, (("Action", 2), ("Record", 4)), name="Empty list")
    blank_ink = _ink(_render(empty, width, height), _row_band(empty, width, height))

    table = md.RecordTable(
        frame,
        (("Action", 2), ("Record", 4), ("Timestamp", 4)),
        name="Probe list",
    )
    table.set_rows(
        [
            (action, f"record-{index}", "2026-08-11T00:00:00Z")
            for index, action in enumerate(("created", "updated", "deleted"))
        ]
    )
    table.select(1)
    image = _render(table, width, height)
    assert (255, 0, 255) not in _colours(
        image
    ), "the table left part of its own rectangle unpainted"
    ink = _ink(image, _row_band(table, width, height))
    assert ink > blank_ink + 200, (
        f"the rows band carries {ink} dark pixels against {blank_ink} for an "
        "empty table, so the row text did not reach the bitmap -- which is the "
        "blank-capture defect this class exists to avoid"
    )


def test_an_empty_table_still_paints_its_frame_and_header(frame):
    """An empty list draws its frame and its headings, and no row ink."""
    width, height = 520, 200
    table = md.RecordTable(frame, (("Action", 1), ("Record", 1)), name="Empty list")
    image = _render(table, width, height)
    assert (255, 0, 255) not in _colours(image)
    header = wx.Rect(0, 0, width, tokens.scaled(table.HEADER_HEIGHT))
    assert _ink(image, header) > 20, "the column headings did not draw"


def test_the_text_field_paints_its_outline(frame):
    field = md.TextField(frame, placeholder="Search", name="Probe field")
    colours = _colours(_render(field, 240, 40))
    assert (255, 0, 255) not in colours
    assert len(colours) > 3, "the field drew no outline"


def test_the_surface_paints_its_role_rather_than_the_default(frame):
    body = md.Surface(frame, role="surface")
    footer = md.Surface(frame, role="surface_container")
    assert body.GetBackgroundColour() != footer.GetBackgroundColour(), (
        "both dialog regions resolved to the same colour, so a footer would be "
        "indistinguishable from the body above it"
    )
    # The native styling pass reads this attribute; without it that pass paints
    # every panel the plain surface role and the distinction above is undone.
    assert footer._material3_surface_role == "surface_container"


def test_selecting_scrolls_the_cursor_back_into_view(frame):
    """A cursor moved past the last visible row must bring the view with it."""
    table = md.RecordTable(frame, (("Row", 1),), name="Long list")
    table.SetSize(wx.Size(200, tokens.scaled(30) + tokens.scaled(28) * 4))
    table.set_rows([(f"row {index}",) for index in range(40)])
    assert table.offset == 0

    end = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    end.SetKeyCode(wx.WXK_END)
    table._on_key_down(end)
    assert table.focused_index() == 39
    assert table.offset > 0, "the cursor left the viewport without scrolling to it"
    assert table.offset <= 39

    home = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    home.SetKeyCode(wx.WXK_HOME)
    table._on_key_down(home)
    assert table.focused_index() == 0
    assert table.offset == 0


def test_replacing_the_rows_drops_the_selection(frame):
    """A refreshed list is a different list.

    Keeping index-based selection across a refresh would point the next bulk
    action at whichever records happened to land on the same row numbers.
    """
    table = md.RecordTable(frame, (("Row", 1),), name="Refreshed list")
    table.set_rows([(f"row {index}",) for index in range(5)])
    table.select_all()
    assert table.selection_count() == 5
    table.set_rows([(f"other {index}",) for index in range(5)])
    assert table.selected_indices() == []


def test_the_accessible_name_carries_the_row_and_the_state(frame):
    """A screen reader reads this control's name, so the row has to be in it."""
    table = md.RecordTable(frame, (("Row", 1),), name="Named list")
    table.set_rows([("alpha",), ("beta",)])
    down = wx.KeyEvent(wx.wxEVT_KEY_DOWN)
    down.SetKeyCode(wx.WXK_DOWN)
    table._on_key_down(down)
    name = table.GetName()
    assert "beta" in name, name
    assert "row 2 of 2" in name, name
    assert "1 selected" in name, name


def test_an_elided_cell_is_recoverable_from_the_tooltip(frame):
    """Shortening a value is fine; losing it is not."""
    table = md.RecordTable(frame, (("Row", 1), ("Detail", 1)), name="Tooltip list")
    table.set_rows([("a value long enough to be shortened", "and its detail")])
    assert "and its detail" in table._tooltip_for(
        tokens.scaled(table.HEADER_HEIGHT) + 2, 0
    )
    # Bilingual column headings carry two languages in the space one was
    # measured for, so the header needs the same recovery the rows have.
    assert "Detail" in table._tooltip_for(1, -1)


def test_a_disabled_action_is_still_built_and_still_named(frame):
    """A control that vanishes when unusable is a control nobody discovers."""
    dialog = wx.Dialog(frame, style=wx.NO_BORDER | wx.RESIZE_BORDER)
    try:
        chrome = md.DialogChrome(dialog, status_name="Probe status")
        button = chrome.action(
            "Open export",
            variant="outlined",
            enabled=False,
            hint="Nothing exported yet",
        )
        assert button.IsShown()
        assert not button.IsEnabled()
        assert button.GetName() == "Open export"
        chrome.set_status("Exported to C:/tmp/history.json")
        assert "Exported to" in chrome.status_text()
        # The base name survives, so the line still says what it belongs to.
        assert chrome.status.GetName().startswith("Probe status")
    finally:
        dialog.Destroy()
