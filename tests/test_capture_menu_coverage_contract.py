"""The capture matrix must photograph the menus, not only the pages behind them.

For 141 surfaces the matrix covered backstage tabs, workspace panes, ribbon tabs
and spec surfaces, and not one context menu, dropdown, popover or anchored
panel.  Six blank menu rows shipped under that matrix without a single check
going red, because a gate cannot catch what a run never photographs: every
structural field in the capture report stays clean for a window nobody asked to
be drawn.

Two halves are needed and neither is sufficient alone.

The first is a **hand-written list**.  A rule shaped "every menu in the manifest
is well formed" passes perfectly on a manifest with no menus in it -- it never
looked, so it never failed -- which is exactly the state this module exists to
make impossible.  So the menus and overlays that must appear are enumerated
below by hand, and a name missing from the manifest is a failure rather than an
absence nobody notices.

The second is a **runtime check** that a menu actually composites its rows.  A
manifest is a record of a run, and a record can only say what that run believed;
opening a real menu and looking at the pixels is what says the rows draw.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import capture_studio_surfaces as harness  # noqa: E402
import capture_surface  # noqa: E402

from amulet_map_editor.api.studio import context_menu, widgets  # noqa: E402

#: Off-screen, so a run on a visible desktop never throws a window at anybody.
OFFSCREEN = wx.Point(-32000, -32000)

#: Where a capture run files its manifest and its images.
HUISHOTS = _ROOT / "docs" / "huishots"

#: Overlays that are not right-click menus and must still be photographed open.
#: Hand-written on purpose: derived from the manifest, this list would agree
#: with whatever the last run happened to produce.
REQUIRED_OVERLAYS = (
    "picker.moveIntoGroup",
    "regexBuilder.panel",
    "regexBuilder.menu",
    "regexBuilder.dropdown",
    "regexBuilder.palette",
    "popup.tabOverflow",
    "palette.card",
    "palette.full",
)

#: Surfaces a run opens, finds blank, and refuses to ship -- with the reason.
#:
#: ``MaterialMenu`` and the ``MaterialCard`` / ``MaterialButton`` /
#: ``MaterialSearchField`` controls it is built from paint in ``EVT_PAINT``
#: using device contexts of their own, and expose no ``render_to`` and no
#: handler the shared ``paint_context`` redirect can drive.  Every route a
#: capture has therefore falls through to ``PrintWindow``, which answers
#: *success* and draws nothing for an owner-drawn control on a window nobody
#: composited: the file comes out as an empty card with an empty search field
#: and no rows at all.
#:
#: This is a real hole rather than a harness limitation.  Those rows cannot be
#: proved to draw by this capture harness or any future one until those widgets
#: gain a callable draw route, which is what every Studio widget already has.
#: When they do, this entry starts failing -- correctly, because the surface
#: belongs in the captured list by then.
KNOWN_BLANK = ("menu.appearance",)


def _manifest() -> dict:
    found = sorted(HUISHOTS.glob("capture-manifest-*.json"))
    if not found:
        pytest.skip("no capture manifest has been written yet")
    return json.loads(found[-1].read_text(encoding="utf-8"))


def _surfaces(manifest: dict) -> set:
    return {row["surface"] for row in manifest["captures"]}


def _explained(manifest: dict) -> dict:
    """Return every surface a run refused to ship, mapped to its reason."""
    explained = {}
    for entry in manifest.get("failures", []) + manifest.get("notOpened", []):
        explained[entry["name"]] = entry["reason"]
    return explained


def test_every_context_menu_is_photographed_open() -> None:
    """All nine searchable right-click menus, by name, with their rows drawn.

    Captured rather than merely accounted for.  "Present in the manifest
    somewhere" would be satisfied by nine entries reading "could not open",
    which is the same coverage gap wearing a note.
    """
    manifest = _manifest()
    surfaces = _surfaces(manifest)
    missing = [key for key in context_menu.CTX_MENUS if f"menu.{key}" not in surfaces]
    assert not missing, (
        f"{len(missing)} of {len(context_menu.CTX_MENUS)} right-click menus were "
        f"never photographed: {missing}. A menu absent from the matrix is a "
        "menu whose rows nothing has ever looked at."
    )


def test_every_required_overlay_is_photographed_open() -> None:
    """The pickers, popovers and palette presentations, by name."""
    manifest = _manifest()
    surfaces = _surfaces(manifest)
    missing = [name for name in REQUIRED_OVERLAYS if name not in surfaces]
    assert (
        not missing
    ), f"{len(missing)} overlays were never photographed open: {missing}"


def test_the_dropdowns_are_photographed_open_not_closed() -> None:
    """A dropdown is a popup with its own rows, so the popup is what is shot.

    The floor is deliberately low and the point is not the number: it is that
    the group exists at all.  Photographing the closed combo -- which the page
    captures already do -- proves nothing about the option list.
    """
    manifest = _manifest()
    dropdowns = [row for row in manifest["captures"] if row["group"] == "Dropdowns"]
    assert dropdowns, (
        "no dropdown option list was photographed; every select in this shell "
        "opens a popup carrying its own search field and owner-drawn rows, and "
        "none of them is covered by a capture of the closed combo"
    )
    for row in dropdowns:
        assert row["surface"].startswith("dropdown."), row


def test_a_known_blank_surface_is_named_rather_than_shipped() -> None:
    """The blank ones are recorded with the reason, and their files deleted.

    A blank capture is worse than none because it looks like evidence, so a run
    that finds one deletes the file and writes down what it found.  A gap
    nobody mentions reads as coverage.
    """
    manifest = _manifest()
    surfaces = _surfaces(manifest)
    explained = _explained(manifest)
    for name in KNOWN_BLANK:
        assert name not in surfaces, (
            f"{name} is shipped as a capture, but it is on the known-blank "
            "list. If those widgets gained a callable draw route, move it into "
            "the captured list instead of leaving a stale exemption here."
        )
        key = name.split(".", 1)[-1]
        matches = [reason for label, reason in explained.items() if key in label]
        assert matches, (
            f"{name} is neither captured nor explained; the manifest records "
            f"only {sorted(explained)}"
        )


def test_the_application_menus_are_named_rather_than_shipped() -> None:
    """The rest of the ``MaterialMenu`` family, which fails for the same reason.

    Their titles come from the running main window rather than from a table
    here, so they are checked as a family: none of them may ship as a capture,
    and at least one has to be written down.  Naming them individually in a list
    would make this fail the day somebody adds a menu to the command bar, which
    is not what it is for.
    """
    manifest = _manifest()
    shipped = [
        row["surface"]
        for row in manifest["captures"]
        if row["surface"].startswith("menu.application.")
    ]
    explained = _explained(manifest)
    named = [label for label in explained if label.startswith("menu-application")]
    assert not shipped or not named, (
        f"the manifest both ships {shipped} and records {named}; one run cannot "
        "have found the same surface drawn and blank"
    )
    assert shipped or named, (
        "the application command-bar menus are neither photographed nor "
        f"explained; the manifest records only {sorted(explained)}"
    )


def test_every_capture_carries_the_blankness_measurement() -> None:
    """The one field that sees a route reporting success over an empty rectangle.

    ``skipped`` and ``blitted_leaves`` can only ever name a window that *said*
    it could not draw, so both stay clean while a file comes out empty. Without
    ``uniformFraction`` in the row, a reader of the manifest has no way to tell.
    """
    manifest = _manifest()
    missing = [
        row["surface"] for row in manifest["captures"] if "uniformFraction" not in row
    ]
    assert (
        not missing
    ), f"{len(missing)} captures carry no uniformFraction: {missing[:8]}"


def test_no_shipped_capture_is_blank() -> None:
    """Nothing under the colour floor reaches the matrix, menus included."""
    manifest = _manifest()
    blank = [
        (row["surface"], row["colours"])
        for row in manifest["captures"]
        if row["colours"] < capture_surface.MIN_DISTINCT_COLOURS
    ]
    assert not blank, f"blank captures were shipped as evidence: {blank}"


# ---------------------------------------------------------------------------
# the runtime half
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    existing = wx.App.Get()
    created = None
    if existing is None:
        try:
            created = wx.App(False)
        except Exception as error:  # pragma: no cover - depends on the host
            pytest.skip(f"wx.App could not start on this host: {error!r}")
    yield existing or created
    if created is not None:
        created.Destroy()


def _open_menu(key: str = "viewport"):
    """Build one real menu off-screen and return it with its frame."""
    frame = wx.Frame(None, size=wx.Size(900, 700))
    frame.SetPosition(OFFSCREEN)
    panel = wx.Panel(frame)
    frame.Show()
    capture_surface.settle(frame)
    menu = context_menu.SearchableContextMenu(panel, key)
    menu.layout()
    menu.SetPosition(OFFSCREEN)
    menu.Show()
    capture_surface.settle(menu)
    return frame, menu


def test_a_context_menu_composites_its_rows(app, tmp_path) -> None:
    """Open a real menu off-screen and look at what its rows drew.

    This is the check that would have caught six blank menu rows on the day
    they landed, and none of the fields the capture already reported would
    have.  Every structural field stays clean for a blank row -- it composites,
    its route reports success, nothing is skipped and nothing is blitted -- and
    the whole-picture measurements are worse than useless: with every row's
    paint handler stubbed out, the distinct-colour count stays well above the
    floor and ``uniform_fraction`` moves from 0.829 to 0.631, which is the
    *healthy* direction.

    Ink inside each row's own rectangle is what separates the two, decisively:
    a drawn row measures between two and four percent, a stubbed one measures
    precisely zero.
    """
    frame, menu = _open_menu()
    try:
        rows = menu._rows
        assert len(rows) >= 8, (
            f"the menu built {len(rows)} rows, so nothing below would prove "
            "anything about a menu that draws its rows"
        )
        path = tmp_path / "menu.png"
        report = capture_surface.capture_composite(menu, path)
        assert not report["skipped"], report["skipped"]
        assert not report["blitted_leaves"], report["blitted_leaves"]
        assert report["colours"] >= capture_surface.MIN_DISTINCT_COLOURS, report

        blank, measured = harness._blank_rows(path, menu, rows)
        # The precondition, and the half that makes the assertion mean
        # something: a menu whose rows all fell outside the picture would
        # report no blanks while proving nothing at all.
        assert measured >= 6, (
            f"only {measured} of {len(rows)} rows were inside the picture, so "
            "the blank-row check had almost nothing to measure"
        )
        assert not blank, f"{len(blank)} of {measured} rows drew no ink: {blank}"
    finally:
        menu.Destroy()
        frame.Destroy()


def test_a_disabled_row_is_not_mistaken_for_a_blank_one(app, tmp_path) -> None:
    """Pale text is still text, and the first version of this check disagreed.

    Ink was originally measured as darkness against a luminance threshold. A
    disabled row draws its label in the palette's disabled ink, which on this
    light surface sits lighter than any threshold that would still call the
    surface itself blank -- so every disabled row read as *exactly* zero, and
    the gate deleted two perfectly good menu captures as broken.

    Measuring against the row's own commonest colour is the correction, and
    this is the half that keeps it: without it, tightening the measurement
    again would silently start throwing away healthy pictures.
    """
    frame, menu = _open_menu("ribbon")
    try:
        disabled = [row for row in menu._rows if not row.IsEnabled()]
        assert disabled, (
            "no row in this menu is disabled, so nothing here says anything "
            "about how a disabled row is measured"
        )
        path = tmp_path / "ribbon.png"
        capture_surface.capture_composite(menu, path)
        blank, measured = harness._blank_rows(path, menu, menu._rows)
        assert measured >= 6, measured
        assert not blank, (
            f"{len(blank)} of {measured} rows read as blank, and "
            f"{len(disabled)} of this menu's rows are merely disabled: {blank}"
        )
    finally:
        menu.Destroy()
        frame.Destroy()


def test_a_one_letter_row_is_not_mistaken_for_a_blank_one(app, tmp_path) -> None:
    """A short label is still a label, and the second version of this disagreed.

    Ink is a share of the row's whole rectangle, so it depends on how long the
    label is.  A menu row reading "Close tabs not containing text…" inks four to
    ten percent of itself; a dropdown row whose entire label is ``X`` inks 0.4%
    of a rectangle the same size, because that is one glyph in 244x30 pixels.  A
    floor set for the first calls the second blank, and the workplane axis list
    -- ``Y (height)``, ``X``, ``Z`` -- was deleted as broken while its picture
    showed all three letters perfectly.

    The check asks whether the row drew *anything*, never whether it drew
    enough, and this is what holds it to that.
    """
    frame = wx.Frame(None, size=wx.Size(700, 600))
    frame.SetPosition(OFFSCREEN)
    panel = wx.Panel(frame)
    combo = widgets.SearchableChoice(
        panel, "Axis", ["Y (height)", "X", "Z"], "Y (height)"
    )
    frame.Show()
    capture_surface.settle(frame)

    original = widgets.AnchoredPopup.Popup
    widgets.AnchoredPopup.Popup = harness._show_offscreen
    try:
        combo.open_popup()
        popup = combo._popup
        capture_surface.settle(popup)
        labels = [row.GetLabel() for row in combo._rows]
        assert "X" in labels, (
            f"the popup listed {labels}, so nothing here says anything about a "
            "one-character row"
        )
        path = tmp_path / "axis.png"
        capture_surface.capture_composite(popup, path, require_content=False)
        blank, measured = harness._blank_rows(path, popup, combo._rows)
        assert measured >= 3, measured
        assert not blank, (
            f"{len(blank)} of {measured} rows read as blank in a list whose "
            f"labels are {labels}: {blank}"
        )
    finally:
        widgets.AnchoredPopup.Popup = original
        frame.Destroy()


def test_the_blank_row_check_can_actually_fail(app, tmp_path) -> None:
    """Stub the row paint handler and confirm the check above goes red.

    A guard nobody has watched fail proves nothing, and this one had to be
    rewritten once for exactly that reason: its first version asserted on
    ``uniform_fraction``, which a menu of blank rows passes comfortably.
    """
    original = context_menu._MenuRow._on_paint
    context_menu._MenuRow._on_paint = lambda self, _event: None
    try:
        frame, menu = _open_menu()
        try:
            path = tmp_path / "blank.png"
            capture_surface.capture_composite(menu, path, require_content=False)
            blank, measured = harness._blank_rows(path, menu, menu._rows)
            assert measured >= 6, measured
            assert len(blank) == measured, (
                "with every row's paint handler stubbed out, only "
                f"{len(blank)} of {measured} rows read as blank -- the check "
                "cannot tell a drawn row from an undrawn one"
            )
        finally:
            menu.Destroy()
            frame.Destroy()
    finally:
        context_menu._MenuRow._on_paint = original
