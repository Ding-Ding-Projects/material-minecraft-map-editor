"""Walk the Amulet Studio interface and photograph it, writing a manifest.

**Menus and overlays are photographed too, and for a long time they were not.**
The matrix covered backstage tabs, workspace panes, ribbon tabs and spec
surfaces -- 141 surfaces -- and not one context menu, dropdown, popover or
anchored panel. That is how six blank menu rows shipped unnoticed: a gate
cannot catch what a run never photographs, and every structural field in the
report stays green for a surface nobody asked to be drawn.

So the run now opens each searchable context menu, each dropdown popup, the
move-into-group picker, the anchored regex builder, the tab overflow list, both
command-palette presentations and the owner-drawn appearance and application
menus, and photographs them **open, with their rows drawn**.

Runs in-process on purpose. Two capture routes look plausible here and only one
of them tells the truth about this interface:

* ``PrintWindow`` (what an out-of-process screenshot uses) asks each window to
  draw itself. Native controls answer; a window that paints in its own
  ``EVT_PAINT`` with a buffered device context generally does not. This
  interface is owner-drawn end to end, so that route returns a plausible-looking
  grid of empty boxes and reads as a broken renderer rather than a broken
  capture.
* Blitting the window's own client device context copies the pixels actually on
  the surface, asking the window nothing. That is what ``capture_surface``
  does, and it is the only route that sees this interface.

One further trap, which cost a blank white file before it was understood: blit
the *individual* windows, not the composite panel that contains them. A device
context for a parent does not include its child windows on Windows, so
capturing the shell as one object omits everything inside it.

Every capture records its distinct-colour count in the manifest. A number near
the floor is a picture to retake rather than ship, because a blank capture is
worse than none: it looks like evidence.

Nothing here retouches an image. If a face renders as Segoe rather than the
design's IBM Plex, the capture shows Segoe and the manifest says so.

``--commit`` is for a caller that genuinely knows better, and it is a foot-gun
for everyone else: passing the *main* checkout's HEAD while running the harness
in a linked worktree files a whole matrix under a commit that was never
photographed, which is the same lie the sys.path trap above tells by accident.
Left off, the commit comes from the checkout the run is in and the manifest is
self-consistent by construction.

Usage:
    pythonw -3.11 scripts/capture_studio_surfaces.py --out resource/img
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import traceback
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Callable, List, Optional

import wx

_SCRIPTS = Path(__file__).resolve().parent
_ROOT = _SCRIPTS.parent

# The repository root goes FIRST, ahead of the scripts directory and ahead of
# anything an editable install has put on the path.
#
# Running `py scripts/capture_studio_surfaces.py` puts *scripts/* on sys.path
# and the current directory nowhere, so `import amulet_map_editor` resolved
# through an editable-install .pth file -- which on this machine pointed at a
# different worktree of this same repository, thirteen commits behind. Every
# capture the harness produced was therefore a photograph of a checkout nobody
# was working on, while the filenames carried the commit of the checkout
# nobody had photographed.
#
# Nothing failed. The captures came out, the manifest recorded the intended
# commit, and the pictures showed an interface that no longer existed. Two
# copies of one package on one path is the whole trap, and it is silent by
# construction.
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_ROOT))

from capture_surface import MIN_DISTINCT_COLOURS, capture_composite  # noqa: E402

import amulet_map_editor  # noqa: E402

# Prove the package on the path is the one in THIS checkout before anything is
# photographed.  The insert above is only an intention; an editable install can
# still be the thing that answered, and the failure is silent -- correct-looking
# captures of a different worktree, filed under this one's commit.
_PACKAGE = str(Path(amulet_map_editor.__file__).resolve())
if not _PACKAGE.startswith(str(_ROOT)):
    raise SystemExit(
        f"amulet_map_editor resolved to {_PACKAGE}, which is outside {_ROOT}; "
        "the captures would show a different checkout than the one being "
        "recorded"
    )

from amulet_map_editor.api.studio import context_menu  # noqa: E402
from amulet_map_editor.api.studio import palette_dialog  # noqa: E402
from amulet_map_editor.api.studio import ribbon_defs  # noqa: E402
from amulet_map_editor.api.studio import specs as spec_registry  # noqa: E402
from amulet_map_editor.api.studio import widgets  # noqa: E402
from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402
from amulet_map_editor.api.studio.spec_dialog import SpecDialog  # noqa: E402
from amulet_map_editor.api.wx.components import MaterialMenu  # noqa: E402

BACKSTAGE_TABS = ("home", "open", "info", "convert", "features", "account")
PANES = ("ribbon", "navigator", "viewport", "properties", "status")

#: Where every popup this run opens is put, and why it is put there.
#:
#: ``Popup()`` grabs the mouse and the keyboard so a transient window can see
#: the click that dismisses it.  A capture run must not take those from the
#: machine it is running on, and ``popup_at`` clamps its point into the display
#: work area, so an off-screen coordinate handed in would be dragged back onto
#: the user's desktop and shown there.  :func:`_show_offscreen` replaces the
#: grab with a plain ``Show()`` at a coordinate no display covers, which is the
#: same thing the harness frame already does.
OFFSCREEN = wx.Point(-31900, -31900)

#: Every popup shown since the list was last cleared, newest last.  A popup is
#: not a child a caller is handed back -- ``open_popup`` keeps its own reference
#: and drops it the moment anything dismisses it -- so the harness records them
#: as they are shown rather than trying to find them afterwards.
_SHOWN: List[wx.Window] = []


def _show_offscreen(self: wx.Window, *_args, **_kwargs) -> None:
    """Show a popup where no display covers it, instead of grabbing the desktop."""
    self.SetPosition(OFFSCREEN)
    self.Show()
    _SHOWN.append(self)


def _install_offscreen_popups() -> None:
    """Route every popup class this run opens through :func:`_show_offscreen`."""
    context_menu.SearchableContextMenu.Popup = _show_offscreen
    widgets.AnchoredPopup.Popup = _show_offscreen
    MaterialMenu.Popup = _show_offscreen


def _slug(text: str, fallback: str = "item") -> str:
    """Return a filesystem-safe fragment of ``text`` for a capture filename."""
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return cleaned[:40] or fallback


def _descendants(window: wx.Window):
    """Yield every descendant of ``window``, breadth first."""
    pending = [window]
    while pending:
        current = pending.pop(0)
        for child in current.GetChildren():
            yield child
            pending.append(child)


#: How far a channel must move from the row's own commonest colour before the
#: pixel counts as something drawn on the row rather than as the row's backdrop.
#: Small enough to catch a disabled row's pale ink, large enough to ignore the
#: antialiasing along a rounded corner.
_INK_DELTA = 24

#: A row varying less than this from its own backdrop has drawn nothing on it.
#:
#: The question is "did this row draw *anything*", never "did it draw enough",
#: and the difference cost two more good captures before it was set here.  A
#: row's ink is a share of its whole rectangle, so it depends on how long the
#: label is: a menu row reading "Close tabs not containing text…" inks four to
#: ten percent of itself, and a dropdown row whose entire label is ``X`` inks
#: **0.4%** of the same-sized rectangle -- one glyph in 244x30 pixels.  A floor
#: set for the first calls the second blank and deletes a perfectly good
#: picture of the workplane axis list.
#:
#: A row that drew nothing measures exactly zero, so the floor only has to sit
#: above rounding.  This one leaves the shortest real label in this interface a
#: factor of five clear of it.
_MIN_ROW_INK = 0.0005


def _row_ink(
    pixels: bytes,
    width: int,
    height: int,
    window: wx.Window,
    row: wx.Window,
    step: int = 2,
) -> float:
    """Return how much of ``row``'s rectangle is drawn on, or ``-1``.

    Ink is measured against the row's **own commonest colour** rather than
    against a luminance threshold, and the difference is not academic: it is a
    correction to a check that deleted two perfectly good captures.

    A disabled menu row draws its label in the palette's disabled ink, which on
    this light surface sits at roughly 170 luminance -- lighter than any
    threshold that would still call the surface itself blank.  Measured for
    darkness, every disabled row in the shell reads as exactly zero ink and a
    healthy menu is thrown away as broken.  Measured against its own backdrop,
    the same row reads between five and seven percent, because pale text is
    still text.

    ``pixels`` is the whole picture's RGB bytes, read once by the caller.
    ``wx.Image.GetRed`` and its siblings are a call across the wrapper per
    channel per pixel, which put a run measuring a couple of hundred surfaces
    into the hours; indexing the buffer costs nothing and measures the same
    pixels.

    ``-1`` means the row is not inside the picture at all -- a menu clamps its
    height to the display and scrolls, so the rows past the cut are legitimately
    absent rather than blank, and measuring them would report every long menu as
    broken.
    """
    root = window.ClientToScreen(wx.Point(0, 0))
    origin = row.ClientToScreen(wx.Point(0, 0))
    size = row.GetClientSize()
    left = max(origin.x - root.x, 0)
    top = max(origin.y - root.y, 0)
    right = min(origin.x - root.x + size.width, width)
    bottom = min(origin.y - root.y + size.height, height)
    if right - left < 8 or bottom - top < 8:
        return -1.0
    seen: Counter = Counter()
    for y in range(top, bottom, step):
        base = y * width
        for x in range(left, right, step):
            at = (base + x) * 3
            seen[pixels[at : at + 3]] += 1
    total = sum(seen.values())
    if not total:
        return -1.0
    backdrop = seen.most_common(1)[0][0]
    drawn = sum(
        count
        for colour, count in seen.items()
        if max(
            abs(colour[0] - backdrop[0]),
            abs(colour[1] - backdrop[1]),
            abs(colour[2] - backdrop[2]),
        )
        >= _INK_DELTA
    )
    return drawn / total


def _blank_rows(path: Path, window: wx.Window, rows) -> tuple:
    """Return which of ``rows`` drew no ink, and how many could be measured.

    This is the check the structural fields cannot make.  A row composites, its
    route reports success, ``skipped`` and ``blitted_leaves`` stay empty, and
    the row is a blank rectangle -- which is exactly what six menu rows did.
    Ink is what separates a row that drew its label from a row that drew only
    its backdrop: stubbing the row's paint handler takes it to precisely zero,
    whatever the label was.
    """
    if not rows:
        return (), 0
    image = wx.Image(str(path))
    if not image.IsOk():
        return (), 0
    # ``bytes`` rather than what wx hands back: ``GetData`` returns a bytearray
    # on this build, and a slice of one is unhashable, so every pixel lookup
    # below would raise instead of counting.
    pixels = bytes(image.GetData())
    width, height = image.GetWidth(), image.GetHeight()
    blank = []
    measured = 0
    for index, row in enumerate(rows):
        try:
            ink = _row_ink(pixels, width, height, window, row)
        except RuntimeError:  # pragma: no cover - the row has gone
            continue
        if ink < 0:
            continue
        measured += 1
        if ink < _MIN_ROW_INK:
            label = row.GetLabel() or row.GetName() or f"row {index + 1}"
            blank.append(f"{label} ({type(row).__name__})")
    return tuple(blank), measured


class Driver:
    def __init__(self, out: Path, commit: str, stamp: str) -> None:
        self.out = out
        self.commit = commit
        self.short = commit[:8]
        self.stamp = stamp
        self.rows: List[dict] = []
        self.failures: List[dict] = []
        #: Menus and overlays this run could not open, and exactly why. A gap
        #: nobody mentions reads as coverage, so an unreachable surface is
        #: written down here rather than left out of the manifest.
        self.not_opened: List[dict] = []
        #: Whether the builder has been photographed from inside a dropdown yet.
        self.dropdown_builder = False
        self.app = wx.App(False)
        self.frame = wx.Frame(
            None, title="Amulet Studio", size=(1600, 1000), pos=(-32000, -32000)
        )
        self.host = wx.Panel(self.frame)
        host = self.host
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.shell = StudioShell(host, self.frame)
        sizer.Add(self.shell, 1, wx.EXPAND)
        host.SetSizer(sizer)
        self.frame.Show()
        for _ in range(4):
            wx.Yield()

    # -- opening things ------------------------------------------------------
    def settle(self, passes: int = 6) -> None:
        """Let the event loop finish what the last call started."""
        for _ in range(passes):
            wx.Yield()
            wx.SafeYield()

    def opened(self, name: str, call: Callable[[], object]) -> Optional[wx.Window]:
        """Run ``call`` and return the popup it showed, or ``None``.

        The application's own opener is what runs: a harness that built the
        popup itself would photograph a window the product never constructs,
        which is the one thing a capture must not do.  A popup that did not
        appear is written into ``not_opened`` with the reason, because a menu
        missing from the manifest reads as a menu nobody has.
        """
        _SHOWN.clear()
        try:
            call()
        except Exception as error:
            self.not_opened.append(
                {"name": name, "reason": f"{type(error).__name__}: {error}"}
            )
            return None
        self.settle()
        if not _SHOWN:
            self.not_opened.append(
                {"name": name, "reason": "the opener ran but showed no popup"}
            )
            return None
        return _SHOWN[-1]

    def shoot(
        self,
        name: str,
        window,
        *,
        group: str,
        alt: str,
        surface: str,
        rows=(),
    ) -> None:
        filename = f"{name}-{self.short}-{self.stamp}.png"
        try:
            report = capture_composite(window, self.out / filename)
        except Exception as error:  # a blank or absent surface, reported not shipped
            self.failures.append(
                {"name": name, "reason": f"{type(error).__name__}: {error}"}
            )
            return

        # The capture frame lives at -32000,-32000 so a run cannot disturb the
        # desktop.  That makes the blit route worthless rather than merely
        # weaker: blitting copies the composited screen surface, and a window
        # nobody composited has no surface to copy, so every control that falls
        # through to it arrives as a white rectangle.
        #
        # This is why the first run of this harness reported "captured 139,
        # failed 0" while backstage tabs were shipping with three rail items
        # drawn as blank boxes and an entirely empty body.  A colour count
        # cannot see that -- the container's own gradient supplies plenty of
        # colours -- so the route is what gets checked.  A control that lands
        # here needs a render_to of its own; being photographed by accident is
        # not a capability.
        blanks = report.get("blitted_leaves", [])
        if blanks or report["skipped"]:
            self.failures.append(
                {
                    "name": name,
                    "reason": (
                        f"{len(blanks)} leaf control(s) could only be blitted "
                        f"and {len(report['skipped'])} drew by no route at "
                        "all, so they are blank rectangles in the file."
                    ),
                    "routes": report["routes"],
                    "skipped": report["skipped"][:12],
                    "blank": blanks[:12],
                }
            )
            try:
                (self.out / filename).unlink()
            except OSError:
                pass
            return

        # The hole the two lists above cannot see.  Both of them only ever name
        # a window that *said* it could not draw, so a route reporting success
        # over an empty rectangle leaves them clean and the file blank -- which
        # is exactly what ``PrintWindow`` does for an owner-drawn control on a
        # window nobody composited.  It is not hypothetical: the appearance
        # menu and the application command menus each composited every one of
        # their descendants by the ``print`` route, reported no skips and no
        # blits, and wrote a picture with an empty card and nothing in it.
        #
        # A colour count is a bad *quality* bar and a decisive *blankness* one:
        # a surface with real content in this interface returns dozens, so
        # anything under the floor is empty beyond argument.
        if report["colours"] < MIN_DISTINCT_COLOURS:
            self.failures.append(
                {
                    "name": name,
                    "reason": (
                        f"{report['descendants']} descendant(s) reported drawing "
                        f"but the picture holds only {report['colours']} distinct "
                        f"colours and is {report['uniform_fraction']:.0%} one "
                        "colour: the rows did not draw, so the file was deleted "
                        "rather than shipped as evidence."
                    ),
                    "routes": report["routes"],
                    "uniformFraction": report["uniform_fraction"],
                }
            )
            try:
                (self.out / filename).unlink()
            except OSError:
                pass
            return

        # And the hole a whole-picture measurement cannot see either: one row
        # among nineteen drawing nothing. The picture still has a header, a
        # search field and eighteen good rows in it, so its colour count is
        # healthy and its uniform fraction actually *improves* -- stubbing the
        # row paint handler took it from 0.829 to 0.631, in the wrong
        # direction. Ink inside each row's own rectangle is what separates a
        # row that drew its label from a row that drew only its backdrop.
        blank_rows, measured = _blank_rows(self.out / filename, window, rows)
        if blank_rows:
            self.failures.append(
                {
                    "name": name,
                    "reason": (
                        f"{len(blank_rows)} of {measured} visible rows drew no "
                        "ink at all, so they are blank rectangles in an "
                        "otherwise healthy picture: " + ", ".join(blank_rows[:6])
                    ),
                    "blankRows": list(blank_rows[:12]),
                }
            )
            try:
                (self.out / filename).unlink()
            except OSError:
                pass
            return

        self.rows.append(
            {
                "filename": filename,
                "surface": surface,
                "group": group,
                "theme": "light",
                "density": "comfortable",
                "viewport": f"{window.GetClientSize().width}x{window.GetClientSize().height}",
                "colours": report["colours"],
                "descendants": report["descendants"],
                "routes": report["routes"],
                # Recorded because it is the one number that sees a route
                # reporting success over an empty rectangle.  Near 1.0 with a
                # nonzero descendant count is a picture to look at before
                # believing.
                "uniformFraction": report["uniform_fraction"],
                # How many of this surface's own rows were inside the picture
                # and proved to carry ink. Zero means the surface has no rows,
                # not that none of them drew.
                "rowsWithInk": measured,
                "alt": alt,
                "verified": self.commit,
            }
        )

    def run(self) -> None:
        for tab in BACKSTAGE_TABS:
            self.shell.show_backstage(tab)
            # Switching a tab hides the outgoing page, and the hide does not
            # take effect until the event loop has run. Capturing too soon
            # composited the previous page's cards over the incoming one --
            # which reads as a layout collapse and is really a photograph taken
            # mid-transition.
            for _ in range(8):
                wx.Yield()
                wx.SafeYield()
            self.shoot(
                f"backstage-{tab}",
                self.shell.backstage,
                group="Backstage",
                surface=f"backstage.{tab}",
                alt=f"Amulet Studio backstage, {tab} tab, in the light theme.",
            )

        self.shell.open_project(title="Capture World", platform="java")
        self.shell.show_workspace()
        for _ in range(4):
            wx.Yield()

        workspace = self.shell.workspace
        for pane in PANES:
            window = getattr(workspace, pane, None)
            if window is None:
                self.failures.append({"name": f"pane-{pane}", "reason": "not exposed"})
                continue
            self.shoot(
                f"workspace-{pane}",
                window,
                group="Workspace",
                surface=f"workspace.{pane}",
                alt=f"The Amulet Studio workspace {pane}, in the light theme.",
            )

        ribbon = getattr(workspace, "ribbon", None)
        if ribbon is not None and hasattr(ribbon, "set_tab"):
            for key in ribbon_defs.TAB_KEYS:
                ribbon.set_tab(key)
                for _ in range(3):
                    wx.Yield()
                self.shoot(
                    f"ribbon-{key}",
                    ribbon,
                    group="Ribbon tabs",
                    surface=f"ribbon.{key}",
                    alt=(
                        f"The Amulet Studio ribbon with the {key} tab selected and "
                        "its panel open, in the light theme."
                    ),
                )

        self.capture_context_menus()
        self.capture_dropdowns(self.shell, "shell", "the Studio shell")
        self.capture_overlays()

        for key in spec_registry.keys():
            spec = spec_registry.get(key)
            if spec is None:
                continue
            dialog = SpecDialog(self.frame, spec)
            dialog.Layout()
            dialog.Show()
            for _ in range(3):
                wx.Yield()
            self.shoot(
                key.lower(),
                dialog,
                group="Surfaces",
                surface=key,
                alt=(
                    f"The {spec.title} surface ({spec.eyebrow}), showing its window "
                    f"search and {len(spec.sections)} sections, in the light theme."
                ),
            )
            self.capture_dropdowns(dialog, key, f"the {spec.title} surface")
            dialog.Hide()
            dialog.Destroy()
            wx.Yield()

        self.capture_application_menus()
        self.report_builder_scope()

    # -- menus and overlays --------------------------------------------------
    def capture_context_menus(self) -> None:
        """Open every searchable right-click menu and photograph its rows.

        Each menu is raised over the surface that really raises it, so the rows
        whose availability is answered against a live window -- collapse the
        ribbon, hide the properties pane -- are drawn in the state a user would
        actually meet rather than uniformly greyed.
        """
        workspace = self.shell.workspace
        targets = {
            "viewport": getattr(workspace, "viewport", None),
            "navigator": getattr(workspace, "navigator", None),
            "ribbon": getattr(workspace, "ribbon", None),
            "pane": getattr(workspace, "properties", None),
            "statusbar": getattr(workspace, "status", None),
            "boxes": getattr(workspace, "navigator", None),
        }
        for key, (title, items) in context_menu.CTX_MENUS.items():
            target = targets.get(key) or self.shell
            menu = self.opened(
                f"menu-{key}",
                lambda key=key, target=target: context_menu.open_context_menu(
                    target,
                    key,
                    OFFSCREEN,
                    on_surface=lambda _key: None,
                    on_command=lambda _key: None,
                    target=target,
                ),
            )
            if menu is None:
                continue
            self.shoot(
                f"menu-{key.lower()}",
                menu,
                group="Context menus",
                surface=f"menu.{key}",
                alt=(
                    f"The {title} right-click menu, open, showing its search "
                    f"field, its counted feedback line and its {len(items)} "
                    "rows with their keyboard shortcuts, in the light theme."
                ),
                rows=menu._rows,
            )
            self.dismiss(menu)

    def capture_dropdowns(self, window: wx.Window, key: str, where: str) -> None:
        """Open every dropdown inside ``window`` and photograph its option list.

        Every select in this shell is a :class:`SearchableChoice`, which is a
        popup carrying its own search field and its own owner-drawn rows -- so
        every one of them is a surface that can come back blank, and a run that
        photographs the closed combo has photographed none of them.
        """
        combos = [
            child
            for child in _descendants(window)
            if isinstance(child, widgets.SearchableChoice)
        ]
        disabled = [combo.label for combo in combos if not combo.IsEnabled()]
        if disabled:
            # A disabled combo will not open, and ``open_popup`` says nothing
            # when it declines.  Naming it is the difference between "this
            # surface has no dropdown" and "this surface has one you cannot
            # open in this state", which are not the same fact.
            self.not_opened.append(
                {
                    "name": f"dropdown-{_slug(key)}-disabled",
                    "reason": (
                        f"{len(disabled)} dropdown(s) on this surface are "
                        "disabled in a capture run and refuse to open: "
                        + ", ".join(disabled[:6])
                    ),
                }
            )
        for index, combo in enumerate(combos):
            label = combo.label or f"option {index + 1}"
            name = f"dropdown-{_slug(key)}-{index + 1}-{_slug(label, 'options')}"
            popup = self.opened(name, combo.open_popup)
            if popup is None:
                continue
            self.shoot(
                name,
                popup,
                group="Dropdowns",
                surface=f"dropdown.{key}.{label}",
                alt=(
                    f"The {label} dropdown on {where}, open, showing its search "
                    f"field and its {len(combo.options)} options with the "
                    "current choice marked, in the light theme."
                ),
                rows=combo._rows,
            )
            # The anchored regex builder, from a dropdown that is already open.
            # Only once: it is the same popover every time, and the point is
            # that it draws when its parent is itself a popup.
            if not self.dropdown_builder:
                bar = next(
                    (
                        child
                        for child in _descendants(popup)
                        if isinstance(child, widgets.SearchBar)
                    ),
                    None,
                )
                if bar is not None:
                    self.dropdown_builder = self.shoot_builder(
                        "dropdown", bar, f"the {label} dropdown on {where}"
                    )
            try:
                combo.close_popup()
            except RuntimeError:  # pragma: no cover - already gone
                pass
            self.settle(3)

    def capture_overlays(self) -> None:
        """Photograph the anchored popovers, the palette and the app menus."""
        workspace = self.shell.workspace
        ribbon = getattr(workspace, "ribbon", None)

        # -- the move-into-group picker
        #
        # Anchored to a ribbon tab rather than to the shell, because the picker
        # widens itself to its anchor: hung off the whole shell it came out
        # 1584px wide with a 240px list of groups adrift in it, which is a
        # truthful photograph of a thing no user can produce.
        anchor = self.tab_anchor(ribbon)
        picker = self.opened(
            "picker-tab-groups",
            lambda: context_menu.open_group_picker(
                anchor, anchor, surface_id="main-window"
            ),
        )
        if picker is not None:
            self.shoot(
                "picker-tab-groups",
                picker,
                group="Overlays",
                surface="picker.moveIntoGroup",
                alt=(
                    "The Move into group picker, open, showing its search "
                    "field, the existing tab groups with their colours and "
                    "member counts, and the create-a-group action, in the "
                    "light theme."
                ),
                rows=picker._rows,
            )
            self.dismiss(picker)

        # -- the anchored regex builder, from each kind of field that opens one
        self.capture_regex_builders()

        # -- the ribbon's tab overflow list, which needs a strip too narrow
        self.capture_tab_overflow(ribbon)

        # -- the command palette, in both presentations
        for layout in ("card", "full"):
            self.capture_palette(layout)

        # -- the owner-drawn appearance menu bound to every native control
        self.capture_appearance_menu()

    def tab_anchor(self, ribbon) -> wx.Window:
        """Return a ribbon tab to anchor a tab-owned popover to."""
        strip = getattr(ribbon, "strip", None)
        tabs = list(getattr(strip, "tabs", []) or [])
        return tabs[0] if tabs else self.shell

    def capture_regex_builders(self) -> None:
        """Photograph the anchored builder from each kind of field that opens one.

        The builder is one class shared by every search bar in the product, so
        what a capture answers is whether it draws when opened from a panel,
        from inside a menu, from inside a dropdown and from the palette -- four
        different parents, three of them popups already.  How many search bars
        were not photographed individually is written into the manifest rather
        than left to look like coverage.

        Each host is opened, used and closed one at a time.  Opening them all
        first looked tidier and does not work: they are transient windows, so
        raising the second one dismissed the first, and the builder call then
        arrived at a ``SearchBar`` whose C++ object had already been deleted.

        The dropdown host is not here.  It is taken from a dropdown the spec
        walk has *already* opened, in :meth:`capture_dropdowns`, because
        building one here needs a spec dialog of its own -- and opening and
        destroying extra dialogs ahead of the walk left three later dropdowns
        compositing no descendants at all.  Reusing a popup that is already up
        costs nothing and disturbs nothing.
        """
        for kind in ("panel", "menu", "palette"):
            host, where, close = self.regex_builder_host(kind)
            if host is None:
                # Say so. A host that could not be produced left no trace at
                # all in the first run of this: `regexBuilder.dropdown` was
                # simply absent from the manifest, in neither the captures nor
                # the gaps, which is precisely the silent hole this harness
                # exists to stop.
                self.not_opened.append(
                    {
                        "name": f"regexbuilder-{kind}",
                        "reason": (
                            f"no live {kind} search field could be produced to "
                            "open the builder from"
                        ),
                    }
                )
                continue
            self.shoot_builder(kind, host, where)
            close()
            self.settle(3)

    def shoot_builder(self, kind: str, host, where: str) -> bool:
        """Open the anchored builder from ``host`` and photograph it."""
        name = f"regexbuilder-{kind}"
        builder = self.opened(name, host.open_builder)
        if builder is None:
            return False
        self.shoot(
            name,
            builder,
            group="Overlays",
            surface=f"regexBuilder.{kind}",
            alt=(
                "The anchored regular-expression builder opened from a search "
                f"field on {where}, showing its guided token buttons, its "
                "pattern editor, its flags and its live match preview, in the "
                "light theme."
            ),
        )
        self.dismiss(builder)
        return True

    def report_builder_scope(self) -> None:
        """Say how many kinds of host the builder was photographed from, and why.

        Written at the end of the run rather than beside the loop, because the
        dropdown host is reached from the spec walk and the count would
        otherwise be one short of the truth.
        """
        hosts = sorted(
            row["surface"]
            for row in self.rows
            if row["surface"].startswith("regexBuilder.")
        )
        bars = sum(
            1
            for child in _descendants(self.shell)
            if isinstance(child, widgets.SearchBar)
        )
        self.not_opened.append(
            {
                "name": "regexbuilder-every-other-search-field",
                "reason": (
                    "The builder is one class, opened by every search bar in "
                    f"the product; it is photographed from {len(hosts)} kinds "
                    f"of host ({', '.join(hosts) or 'none'}). The Studio shell "
                    f"alone carries {bars} search bars and every spec surface "
                    "carries at least one more, so photographing each field's "
                    "builder would repeat the same popover under a different "
                    "anchor name."
                ),
            }
        )
        if not any(name.endswith(".dropdown") for name in hosts):
            self.not_opened.append(
                {
                    "name": "regexbuilder-dropdown",
                    "reason": (
                        "no dropdown opened in this run yielded a search field "
                        "to open the builder from"
                    ),
                }
            )

    def regex_builder_host(self, kind: str):
        """Return one live search bar of ``kind``, where it is, and how to close it.

        The host is opened here rather than by the caller so it is alive for
        exactly as long as the builder it opens, which is what a transient
        popup requires.
        """
        nothing: Callable[[], None] = lambda: None
        if kind == "panel":
            bar = next(
                (
                    child
                    for child in _descendants(self.shell)
                    if isinstance(child, widgets.SearchBar)
                ),
                None,
            )
            return bar, "a Studio panel", nothing
        if kind == "menu":
            menu = self.opened(
                "regexbuilder-menu-host",
                lambda: context_menu.open_context_menu(
                    self.shell, "navigator", OFFSCREEN
                ),
            )
            if menu is None:
                return None, "", nothing
            return (
                menu.search,
                "the Navigator right-click menu",
                (lambda: self.dismiss(menu)),
            )
        if kind == "palette":
            try:
                palette = palette_dialog.CommandPalette(
                    self.frame, shell=self.shell, layout="card"
                )
            except Exception as error:
                self.not_opened.append(
                    {
                        "name": "regexbuilder-palette",
                        "reason": f"{type(error).__name__}: {error}",
                    }
                )
                return None, "", nothing
            palette.SetPosition(OFFSCREEN)
            palette.Show()
            self.settle()
            return (
                palette.search,
                "the command palette",
                (lambda: self.destroy(palette)),
            )
        return None, "", nothing

    def capture_tab_overflow(self, ribbon) -> None:
        """Narrow the window until the ribbon strip overflows, then shoot the list."""
        strip = getattr(ribbon, "strip", None)
        if strip is None or not hasattr(strip, "open_overflow"):
            self.not_opened.append(
                {
                    "name": "popup-tab-overflow",
                    "reason": "the ribbon exposes no tab strip with an overflow list",
                }
            )
            return
        original = self.frame.GetSize()
        self.frame.SetSize(wx.Size(560, 900))
        self.settle(8)
        overflowed = list(getattr(strip, "_overflowed", []) or [])
        if not overflowed:
            self.frame.SetSize(original)
            self.settle(4)
            self.not_opened.append(
                {
                    "name": "popup-tab-overflow",
                    "reason": (
                        "no tab overflowed even with the window narrowed to "
                        "560px, so the list has nothing to show and a capture "
                        "would be an empty popover rather than the surface"
                    ),
                }
            )
            return
        popup = self.opened("popup-tab-overflow", strip.open_overflow)
        if popup is not None:
            self.shoot(
                "popup-tab-overflow",
                popup,
                group="Overlays",
                surface="popup.tabOverflow",
                alt=(
                    "The ribbon tab overflow list, open on a narrowed window, "
                    f"showing its search field and the {len(overflowed)} tabs "
                    "the strip could not fit, in the light theme."
                ),
                rows=[
                    child
                    for child in popup.content.GetChildren()
                    if isinstance(child, widgets._OptionRow)
                ],
            )
        try:
            strip.close_overflow()
        except RuntimeError:  # pragma: no cover - already gone
            pass
        self.frame.SetSize(original)
        self.settle(6)

    def capture_palette(self, layout: str) -> None:
        """Photograph one presentation of the command palette."""
        name = f"palette-{layout}"
        try:
            palette = palette_dialog.CommandPalette(
                self.frame, shell=self.shell, layout=layout
            )
        except Exception as error:
            self.not_opened.append(
                {"name": name, "reason": f"{type(error).__name__}: {error}"}
            )
            return
        palette.SetPosition(OFFSCREEN)
        palette.Show()
        self.settle(8)
        self.shoot(
            name,
            palette,
            group="Overlays",
            surface=f"palette.{layout}",
            alt=(
                f"The Ctrl+Shift+F command palette in its {layout} "
                "presentation, showing its search field, its result count and "
                "its result rows with their live controls, in the light theme."
            ),
            rows=palette.rows,
        )
        self.destroy(palette)

    def capture_appearance_menu(self) -> None:
        """Photograph the appearance menu every native control raises.

        The menu is built inside a handler the shared Material layer binds, so
        the run raises a real context-menu event on a real native control and
        photographs whatever that handler put up, rather than assembling a menu
        of its own.
        """
        from amulet_map_editor.api.wx import material3

        probe = wx.TextCtrl(self.host, value="Appearance menu probe")
        probe.Hide()
        try:
            material3.apply_material3(self.frame)
        except Exception as error:
            self.not_opened.append(
                {
                    "name": "menu-appearance",
                    "reason": f"the Material layer refused to bind: {error}",
                }
            )
            probe.Destroy()
            return

        def raise_menu() -> None:
            event = wx.ContextMenuEvent(wx.wxEVT_CONTEXT_MENU, probe.GetId())
            event.SetEventObject(probe)
            probe.GetEventHandler().ProcessEvent(event)

        menu = self.opened("menu-appearance", raise_menu)
        if menu is not None:
            self.shoot(
                "menu-appearance",
                menu,
                group="Context menus",
                surface="menu.appearance",
                alt=(
                    "The appearance menu a native control raises, open, "
                    "showing its search field and its Edit appearance and "
                    "Reset element appearance rows, in the light theme."
                ),
            )
            self.dismiss(menu)
        probe.Destroy()

    def capture_application_menus(self) -> None:
        """Photograph the application command-bar menus the main window builds.

        These belong to the main frame rather than to the Studio shell this
        harness drives, so the frame is built off-screen for them and torn down
        immediately afterwards.
        """
        try:
            from amulet_map_editor.api.framework import amulet_ui
        except Exception as error:
            self.not_opened.append(
                {
                    "name": "menu-application",
                    "reason": f"the main window module would not import: {error}",
                }
            )
            return
        window = None
        try:
            window = amulet_ui.AmuletUI(None)
            window.SetPosition(wx.Point(-32000, -32000))
            window.Show()
            self.settle(8)
            menus = list(getattr(window, "_command_menus", []) or [])
            bar = getattr(window, "_command_bar", None)
            if bar is not None and not bar.IsShown():
                # The bar is hidden because the Studio chrome replaces it, and
                # a menu inside a hidden parent answers IsShownOnScreen False,
                # so every row would composite as a blank rectangle. Showing
                # the bar is what a capture of its menus needs.
                bar.Show()
                self.settle(4)
            if not menus:
                self.not_opened.append(
                    {
                        "name": "menu-application",
                        "reason": (
                            "the main window built no command-bar menus in this "
                            "run, so there is nothing to open"
                        ),
                    }
                )
            for menu in menus:
                title = menu.GetName().replace(" menu", "") or "Application"
                name = f"menu-application-{_slug(title)}"
                shown = self.opened(
                    name, lambda menu=menu, bar=bar: menu.show_for(bar or window)
                )
                if shown is None:
                    continue
                self.shoot(
                    name,
                    shown,
                    group="Context menus",
                    surface=f"menu.application.{title}",
                    alt=(
                        f"The application {title} menu, open, showing its "
                        "search field and its command rows, in the light theme."
                    ),
                )
                self.dismiss(shown)
        except Exception as error:
            self.not_opened.append(
                {
                    "name": "menu-application",
                    "reason": f"{type(error).__name__}: {error}",
                }
            )
        finally:
            if window is not None:
                self.destroy(window)

    # -- tearing down --------------------------------------------------------
    def dismiss(self, popup: wx.Window) -> None:
        """Hide a popup without letting its dismiss handler steal the keyboard."""
        try:
            popup.Hide()
        except RuntimeError:  # pragma: no cover - already gone
            pass
        self.destroy(popup)

    def destroy(self, window: wx.Window) -> None:
        """Destroy a window and let wx finish with it."""
        try:
            window.Destroy()
        except RuntimeError:  # pragma: no cover - already gone
            pass
        self.settle(3)

    def report(self) -> dict:
        self.frame.Destroy()
        wx.Yield()
        return {
            "schemaVersion": 1,
            "commit": self.commit,
            "captured": self.stamp,
            "wxPython": wx.version(),
            "method": "in-process client-DC blit (capture_surface.capture_window)",
            "note": (
                "PrintWindow cannot see this interface: it is owner-drawn end to end "
                "and returns empty boxes. Colour counts are recorded so a capture "
                "near the floor can be retaken rather than shipped."
            ),
            "menuNote": (
                "Menus, dropdowns and popovers are opened through the "
                "application's own openers and shown at a coordinate no display "
                "covers, because Popup() grabs the mouse and the keyboard and a "
                "capture run must not take those from the machine it runs on."
            ),
            "captures": self.rows,
            "failures": self.failures,
            "notOpened": self.not_opened,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("resource/img"))
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    commit = (
        args.commit
        or subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True
        ).stdout.strip()
    )
    if not commit:
        raise SystemExit("could not resolve the commit being captured")

    args.out.mkdir(parents=True, exist_ok=True)
    _install_offscreen_popups()
    driver = Driver(args.out, commit, date.today().strftime("%Y%m%d"))
    try:
        driver.run()
    except Exception:
        traceback.print_exc()
    report = driver.report()

    manifest = args.manifest or (args.out / f"capture-manifest-{commit[:8]}.json")
    manifest.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    menus = sum(
        1
        for row in report["captures"]
        if row["group"] in ("Context menus", "Dropdowns", "Overlays")
    )
    print(
        f"captured {len(report['captures'])} ({menus} menus and overlays), "
        f"failed {len(report['failures'])}, "
        f"not opened {len(report['notOpened'])}"
    )
    for entry in report["failures"][:12]:
        print(f"  FAILED {entry['name']}: {entry['reason']}")
    for entry in report["notOpened"][:12]:
        print(f"  NOT OPENED {entry['name']}: {entry['reason']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
