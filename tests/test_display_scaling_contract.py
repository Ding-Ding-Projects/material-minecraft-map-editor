"""The application draws its own pixels; Windows must not stretch them.

A Windows process that declares no DPI awareness is assumed to predate
high-resolution displays.  Windows then reports a fictional 96 DPI, lets the
application lay itself out for that, and bitmap-stretches the finished frame up
to the panel's real scale.  At 100% that costs nothing, which is why the fault
reproduced on a 150% laptop and not on the desktop beside it -- and why nothing
inside the application looked wrong from the inside.  It measured 96 DPI, it
drew for 96 DPI, and every size it reported back was the size it meant.

These tests pin the two halves that only work together: the declaration that
stops the stretching, and the scaling that keeps the interface the right
physical size once it has stopped.
"""

from __future__ import annotations

import pathlib
import re
import xml.etree.ElementTree as ElementTree

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


class TestAwarenessIsDeclared:
    """Half one: Windows has to be told, before the first window exists."""

    def test_source_checkout_declares_before_the_app_is_built(self) -> None:
        source = _read("amulet_map_editor/__main__.py")
        assert "declare_awareness()" in source, (
            "A source checkout has no manifest, so the ctypes declaration is the "
            "only thing standing between it and being stretched."
        )
        # Order is the whole point: Windows fixes a process's awareness the
        # first time it is asked for, and afterwards the value cannot be
        # changed. A declaration made after the wx.App is a declaration that
        # silently does nothing.
        assert source.index("declare_awareness()") < source.index(
            "AmuletApp(0)"
        ), "DPI awareness must be declared before wx creates anything"

    def test_packaged_build_declares_it_in_the_manifest(self) -> None:
        spec = _read("installer/Amulet.spec")
        assert 'manifest="amulet.manifest"' in spec

        manifest = ElementTree.parse(ROOT / "installer" / "amulet.manifest")
        text = ElementTree.tostring(manifest.getroot(), encoding="unicode")
        assert "PerMonitorV2" in text, (
            "Per-monitor v2 is the only mode that rescales the window frame "
            "with its contents and survives a drag between two displays."
        )
        assert "asInvoker" in text, "A map editor must never request elevation"

    def test_declaration_never_raises_on_this_platform(self) -> None:
        from amulet_map_editor.api import dpi

        # Whatever this host is, the call must return a mode rather than throw:
        # a degraded interface on one class of display is survivable, an
        # application that cannot start is not.
        assert dpi.declare_awareness() in {
            "per-monitor-v2",
            "per-monitor-v1",
            "system",
            "manifest",
            "unavailable",
        }
        # Declaring twice must agree with itself; Windows would refuse the
        # second call anyway, and reporting a different answer would be a lie.
        assert dpi.declare_awareness() == dpi.declared_mode()


class TestScalingDoesNotDouble:
    """Half two: scale pixels, never points. This is the regression guard."""

    @pytest.fixture(autouse=True)
    def _restore_factor(self):
        tokens = pytest.importorskip("amulet_map_editor.api.studio.tokens")
        original = tokens.dpi_factor()
        yield
        tokens._dpi_factor = original

    def test_pixel_constants_follow_the_display(self) -> None:
        tokens = pytest.importorskip("amulet_map_editor.api.studio.tokens")
        tokens._dpi_factor = 1.0
        at_100 = tokens.scaled(236), tokens.control_height()
        tokens._dpi_factor = 1.5
        at_150 = tokens.scaled(236), tokens.control_height()
        assert at_150[0] == round(at_100[0] * 1.5)
        assert at_150[1] == round(at_100[1] * 1.5)

    def test_font_point_sizes_do_not(self) -> None:
        """Points are physical; the toolkit already converts them by real DPI.

        This is the one that brings the bug back.  Somebody sees small text at
        150%, reasonably concludes the scale is not being applied to fonts, and
        applies it -- at which point every label is scaled twice while every box
        around it is scaled once, and the interface overflows its own controls.
        """
        wx = pytest.importorskip("wx")
        tokens = pytest.importorskip("amulet_map_editor.api.studio.tokens")
        app = wx.App()  # noqa: F841 - a wx.Font needs a live app
        frame = wx.Frame(None)
        try:
            tokens._dpi_factor = 1.0
            at_100 = tokens.font(frame, 10).GetPointSize()
            tokens._dpi_factor = 2.0
            at_200 = tokens.font(frame, 10).GetPointSize()
            assert at_100 == at_200, (
                "Font point size changed with the display scale. Points are "
                "already device-relative, so this is the doubled scaling that "
                "made the interface oversized in the first place."
            )
        finally:
            frame.Destroy()

    def test_a_nonsense_reading_is_refused(self) -> None:
        """A zero factor would collapse the entire interface to one pixel."""
        tokens = pytest.importorskip("amulet_map_editor.api.studio.tokens")
        tokens._dpi_factor = 1.0

        class _Liar:
            def GetDPIScaleFactor(self):
                return 0.0

        assert tokens.refresh_dpi(_Liar()) == 1.0

        class _AlsoLying:
            def GetDPIScaleFactor(self):
                return 400.0

        assert tokens.refresh_dpi(_AlsoLying()) == 1.0

    def test_a_dpi_change_is_followed_not_only_read_once(self) -> None:
        """A window dragged to another monitor changes scale with no resize."""
        source = _read("amulet_map_editor/api/framework/app.py")
        assert "EVT_DPI_CHANGED" in source
        assert "refresh_dpi" in source
        # Owner-drawn controls cache sizes from tokens.scaled(), so a repaint
        # alone would redraw them at their old dimensions.
        # Split on the definition, not the name: the name appears first in the
        # Bind call, and slicing there checks the wrong body entirely.
        handler = source.split("def _on_dpi_changed")[1].split("\n    def ")[0]
        assert ".Layout()" in handler


class TestNothingBypassesTheScaling:
    """A size that stays at 96 DPI while its neighbours grow is a clip."""

    def test_no_fixed_pixel_minimum_sizes_remain(self) -> None:
        """Minimums are the dangerous ones, so they are what this pins.

        A fixed ``SetMinSize`` is a floor written in device pixels.  Once every
        child inside it scales with the display and the floor does not, the
        window can be dragged to a size where its own contents no longer fit --
        which looks like a broken layout rather than a window that is too
        small.  Touch targets have the same problem in reverse: 44 device
        pixels is about a fingertip at 96 DPI and about a third of a
        centimetre at 200%.
        """
        offenders: list[str] = []
        pattern = re.compile(
            r"(SetMinSize|SetMaxSize)\(\s*wx\.Size\(\s*\d+\s*,\s*\d+\s*\)"
        )
        for path in (ROOT / "amulet_map_editor").rglob("*.py"):
            for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1
            ):
                if pattern.search(line) and "scaled(" not in line:
                    offenders.append(
                        f"{path.relative_to(ROOT).as_posix()}:{number}: {line.strip()}"
                    )
        assert not offenders, (
            "These sizes are written in device pixels and will not follow a "
            "scaled display:\n  " + "\n  ".join(offenders)
        )


class TestRenamingShowsTheChosenName:
    """A rename shows the typed name, not the typed name plus a suffix."""

    def test_the_suffix_belongs_to_the_shipped_name_only(self) -> None:
        source = _read("amulet_map_editor/api/studio/backstage.py")
        assert '"{display_name} Studio"' not in source, (
            'Appending " Studio" to a chosen name rendered "My Map Studio" as '
            '"My Map Studio Studio", and made every rename read as somebody '
            "else's product line."
        )
        assert re.search(r"DEFAULT_DISPLAY_NAME", source), (
            "The suffix must be conditional on the name still being the " "shipped one."
        )
