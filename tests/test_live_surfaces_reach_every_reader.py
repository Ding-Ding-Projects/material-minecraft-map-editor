"""A surface built from live state must be live everywhere it is read.

``specs.get`` rebuilds a surface whose content comes from something that can
change under it -- the Key Select window reads the reader's own 3D editor key
group.  Two readers went round it:

* **The window that is already open.**  ``open_spec`` builds the description
  and hands it to the modeless helper, which raises the window that is already
  registered under that key and returns it, dropping the new description on the
  floor.  So the rebuild ran on every press of the ribbon button and changed
  nothing: a key group edited mid-session left the open window teaching the
  keys it was opened with until somebody closed it.

* **The command palette.**  Its setting index read ``specs.SPECS[key]``
  directly, which is the map built when this process imported the package.  The
  rebuilder never ran for the palette at all, so the key-group dropdown it
  offered was read before the reader's configuration was.

Both are the same shape as the defect they sit beside: a reading taken once and
then trusted forever.  Both tests below were watched failing against the code
as it shipped.
"""

from __future__ import annotations

from typing import Dict, List

import pytest

from amulet_map_editor.api.studio import specs as spec_registry
from amulet_map_editor.api.studio.spec import Spec

#: A surface built by hand, standing in for one whose live state has changed.
#: Using a real key group would tie this to whatever groups the host machine
#: has; the property under test is "does the new description reach the reader",
#: which any two distinguishable descriptions prove.
_MARKER = "rebuilt-for-this-test"


def _marked(key: str) -> Spec:
    original = spec_registry.get(key)
    assert original is not None, f"the {key!r} surface is no longer registered"
    return Spec(
        key=original.key,
        eyebrow=original.eyebrow,
        title=original.title,
        width=original.width,
        confirm=original.confirm,
        intro=_MARKER,
        sections=original.sections,
        actions=original.actions,
    )


def test_reopening_a_surface_refreshes_the_window_already_on_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Press the button again and the raised window must show the new reading."""
    wx = pytest.importorskip("wx")

    from amulet_map_editor.api.studio import spec_dialog

    app = wx.App.Get() or wx.App()
    frame = wx.Frame(None, size=(1200, 900))
    frame.Show()
    try:
        first = spec_dialog.open_spec(frame, "controls")
        assert isinstance(first, spec_dialog.SpecDialog)
        assert first.spec.intro != _MARKER, "the surface already carries the marker"

        rebuilt = _marked("controls")
        monkeypatch.setattr(
            spec_dialog.spec_registry,
            "get",
            lambda key: rebuilt if key == "controls" else None,
        )
        again = spec_dialog.open_spec(frame, "controls")

        assert again is first, (
            "opening the surface a second time made a second window; this test "
            "is about the one that gets reused"
        )
        assert first.spec.intro == _MARKER, (
            "the window already on screen kept the description it was opened "
            "with, so a surface read from live state stays frozen for as long "
            "as it stays open"
        )
        intros = [
            child.text
            for child in first.body.GetChildren()
            if getattr(child, "text", None) == _MARKER
        ]
        assert intros, (
            "the window took the new description but never redrew, so nothing "
            "on screen changed"
        )
    finally:
        for window in list(frame.GetChildren()):
            if isinstance(window, wx.Dialog):
                window.Destroy()
        frame.Destroy()
        wx.Yield()
        del app


def _palette_settings() -> List[object]:
    from amulet_map_editor.api.studio import palette_dialog

    return palette_dialog._spec_setting_results()


def test_the_command_palette_indexes_the_rebuilt_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The palette must read surfaces the same way a window opens them.

    The marker is placed on a *dropdown*, because the palette indexes settings
    rather than prose: a surface whose options are read live -- which is the
    whole reason the Key Select window has a rebuilder -- must reach the
    palette with the options it has now.
    """
    from amulet_map_editor.api.studio import palette_dialog
    from amulet_map_editor.api.studio.spec import Section, Select

    original = spec_registry.get("controls")
    assert original is not None

    rebuilt = Spec(
        key="controls",
        eyebrow=original.eyebrow,
        title=original.title,
        width=original.width,
        confirm=original.confirm,
        intro=original.intro,
        sections=(
            Section(
                title="Key group",
                kind="selects",
                selects=(Select(_MARKER, ("one", "two"), "one"),),
            ),
        ),
        actions=original.actions,
    )

    real_get = spec_registry.get
    monkeypatch.setattr(
        spec_registry,
        "get",
        lambda key: rebuilt if key == "controls" else real_get(key),
    )

    labels = {getattr(result, "label", "") for result in _palette_settings()}
    assert _MARKER in labels, (
        "the command palette did not index the rebuilt description of the "
        "surface, so it is reading the snapshot taken when this process "
        "imported the registry rather than the surface as it is now"
    )


def test_the_palette_index_is_not_empty_without_the_marker() -> None:
    """The precondition: the rule above must be able to fail.

    An index that returned nothing would satisfy a "does not contain the stale
    label" test and could satisfy a mis-written positive one, so this states
    that the palette really does index these surfaces at all.
    """
    results = _palette_settings()
    assert results, "the command palette indexes no surface settings whatsoever"
    surfaces: Dict[str, int] = {}
    for result in results:
        surfaces[getattr(result, "surface", "")] = (
            surfaces.get(getattr(result, "surface", ""), 0) + 1
        )
    assert len(surfaces) > 1, (
        "the palette indexed settings from a single surface, so the rule "
        f"above is not covering what it claims: {surfaces}"
    )
