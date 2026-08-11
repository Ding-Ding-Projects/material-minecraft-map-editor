"""The Position section is readable in every language mode, not only English.

The section exists to disclose a rule the interface was keeping to itself: a
pasted coordinate names the *centre* of the copy, so somebody who types the
coordinate they want gets blocks half a structure away.  A disclosure a
Cantonese reader cannot read discloses nothing to them -- it leaves them exactly
where the defect found them.

Every string here reaches the reader through
:func:`amulet_map_editor.api.studio.copy.studio_label` or
:func:`~amulet_map_editor.api.studio.copy.studio_text`, and both of those return
the *English* untouched when no Cantonese was supplied.  That is the failure
this module is built around, and it is a silent one: the call compiles, the
control renders, the tests that only ever run in English pass, and the section
is simply in the wrong language for anybody who asked for the other one.

**The picker gets its own test for a reason.**  Translating the options while
leaving the reverse lookup matching against the English table would leave every
Cantonese choice matching nothing and falling back to the centre, so picking
"the lowest corner" would silently select the centre -- a control quietly doing
something other than what it says, which is worse than the defect the section
was built to remove.  ``test_choosing_an_option_in_cantonese_selects_it`` drives
that round trip through the real control rather than trusting the mapping.
"""

from __future__ import annotations

from typing import Any, Iterator, List, Optional, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api import preferences  # noqa: E402
from amulet_map_editor.api.studio import editor_tools  # noqa: E402
from amulet_map_editor.api.studio import properties_pane as pane_module  # noqa: E402
from amulet_map_editor.api.studio.widgets import (  # noqa: E402
    SearchableChoice,
    StudioText,
)

EXTENT: Tuple[int, int, int] = (4, 1, 4)
LOCATION: Tuple[int, int, int] = (8, 40, 8)


def _has_han(text: str) -> bool:
    """Whether ``text`` carries a CJK ideograph.

    The cheapest honest test for "this is not the English string".  Asserting
    inequality with the English alone would pass on a typo, an empty string, or
    a placeholder; asserting a Han character is present says something was
    actually written in the other language.
    """
    return any("㐀" <= character <= "鿿" for character in str(text))


class FakeTool:
    """A pending object that answers like the paste tool holding one."""

    def __init__(self) -> None:
        self.location: Tuple[int, int, int] = LOCATION

    def pending(self) -> editor_tools.PendingObject:
        return editor_tools.PendingObject(
            location=self.location,
            rotation=(0.0, 0.0, 0.0),
            scale=(1.0, 1.0, 1.0),
            following=False,
            drawn=True,
            size=" by ".join(str(value) for value in EXTENT),
            extent=EXTENT,
        )

    def set_location(self, location, *args: Any, **kwargs: Any) -> bool:
        self.location = tuple(int(round(float(value))) for value in location)
        return True


@pytest.fixture(scope="module")
def app() -> Iterator[Any]:
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


@pytest.fixture()
def cantonese(monkeypatch: pytest.MonkeyPatch, tmp_path) -> FakeTool:
    """A throwaway profile reading Cantonese, and a stand-in paste tool.

    The profile is a temporary directory rather than the real one because this
    changes the language mode and the stored anchor, and a test that leaves the
    developer's own editor speaking a language they did not choose is a test
    that has broken something to check something.
    """
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "profile"))
    preferences.update(language_mode="cantonese")
    assert preferences.load().language_mode == "cantonese", (
        "the throwaway profile did not take the language mode, so everything "
        "below would be asserting against English and passing for the wrong "
        "reason"
    )
    fake = FakeTool()
    monkeypatch.setattr(editor_tools, "pending_object", lambda *a, **k: fake.pending())
    monkeypatch.setattr(editor_tools, "set_pending_location", fake.set_location)
    monkeypatch.setattr(editor_tools, "active_tool_name", lambda *a, **k: "Paste")
    monkeypatch.setattr(editor_tools, "camera_location", lambda *a, **k: None)
    monkeypatch.setattr(editor_tools, "movement_sentence", lambda *a, **k: "")
    return fake


@pytest.fixture()
def pane(app, cantonese: FakeTool) -> Iterator[Any]:
    """A properties pane showing a Clone activation, reading Cantonese."""
    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    built = pane_module.PropertiesPane(window, title="Test world")
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(built, 1, wx.EXPAND)
    window.SetSizer(sizer)
    window.Show()
    window.Layout()
    wx.Yield()
    built.show_tool_activation(
        editor_tools.Activation(
            key="cloneTool",
            label="Clone",
            ok=True,
            tool="Paste",
            kind="pending",
            message="The selection was copied and the paste tool is holding it.",
        )
    )
    built.Layout()
    wx.Yield()
    try:
        yield built
    finally:
        window.Destroy()
        wx.Yield()


def _descendants(window: Any) -> Iterator[Any]:
    stack = [window]
    while stack:
        node = stack.pop()
        yield node
        try:
            stack.extend(node.GetChildren())
        except Exception:  # noqa: BLE001 - a control mid-teardown
            continue


def _anchor_choice(pane: Any) -> Optional[SearchableChoice]:
    """Find the anchor picker without assuming which language it is in.

    Deliberately not matched on its label carrying Cantonese.  That would make
    a picker still labelled in English simply *not found*, and every assertion
    below would then fail with "there is no picker" -- true, unhelpful, and
    pointing at the wrong thing.  Matched on the shape of its option list
    instead, so a picker in the wrong language is found and then reported for
    being in the wrong language.
    """
    wanted = {
        editor_tools.anchor_label(key) for key, _label in editor_tools.ANCHORS
    } | {
        editor_tools.anchor_label_cantonese(key) for key, _label in editor_tools.ANCHORS
    }
    for node in _descendants(pane):
        if not isinstance(node, SearchableChoice):
            continue
        if len(node.options) == len(editor_tools.ANCHORS) and set(node.options) <= (
            wanted
        ):
            return node
    return None


# ----------------------------------------------------------------------
# every string the section shows
# ----------------------------------------------------------------------


def test_every_anchor_name_has_a_cantonese_counterpart() -> None:
    """No anchor is offered without a name in the other language.

    Written against the keys rather than a copied list, so an anchor added
    later without a translation fails here instead of shipping one English
    option sitting in a list of Cantonese ones.
    """
    for key, english in editor_tools.ANCHORS:
        cantonese = editor_tools.anchor_label_cantonese(key)
        assert _has_han(cantonese), (
            f"the {key!r} anchor's Cantonese name is {cantonese!r}, which "
            "carries no Cantonese at all"
        )
        assert cantonese != english, f"the {key!r} anchor was not translated"


def test_every_disclosure_sentence_has_a_cantonese_counterpart() -> None:
    """The sentence that discloses the rule exists in both languages."""
    for key in dict(editor_tools.ANCHORS):
        assert key in pane_module.ANCHOR_SENTENCES_CANTONESE, (
            f"the {key!r} anchor has an English disclosure and no Cantonese "
            "one, so choosing it says nothing to a Cantonese reader"
        )
        assert _has_han(pane_module.ANCHOR_SENTENCES_CANTONESE[key])
    assert _has_han(pane_module.ANCHOR_SIZE_UNKNOWN_CANTONESE)
    assert _has_han(pane_module.ANCHOR_FIELD_LABEL_CANTONESE)
    assert _has_han(pane_module.BOX_VALUE_UNKNOWN_CANTONESE)
    for key, _english in pane_module.PASTE_BOX_ROWS:
        assert (
            key in pane_module.PASTE_BOX_ROW_LABELS_CANTONESE
        ), f"the {key!r} box row has no Cantonese label"
        assert _has_han(pane_module.PASTE_BOX_ROW_LABELS_CANTONESE[key])


def test_the_section_is_drawn_in_cantonese(pane) -> None:
    """The built controls carry Cantonese, not English served in its place.

    This is the one that fails on the real defect.  Every constant above can be
    present and correct while the pane goes on passing a single argument to
    ``studio_label``, which returns the English in every mode -- so the strings
    are checked where they end up rather than where they are written.
    """
    choice = _anchor_choice(pane)
    assert choice is not None, "the pane built no anchor picker at all"
    assert _has_han(choice.label), (
        f"the anchor picker is labelled {choice.label!r}, which is English, "
        "for a reader who asked for Cantonese"
    )
    for option in choice.options:
        assert _has_han(option), (
            f"the anchor picker offers {option!r}, which is English, to a "
            f"reader who asked for Cantonese. Its options are {choice.options}"
        )
    assert _has_han(
        choice.value
    ), f"the anchor picker opens holding {choice.value!r}, which is English"

    sentences = [
        " ".join(str(node.GetLabel()).split())
        for node in _descendants(pane)
        if isinstance(node, StudioText)
    ]
    assert any(_has_han(text) and "x" in text for text in sentences), (
        "the disclosure under the position boxes -- the entire point of this "
        f"section -- is not in Cantonese. The paragraphs shown are {sentences}"
    )

    labels = [
        node.label
        for node in _descendants(pane)
        if isinstance(node, pane_module.PropertyRow)
    ]
    # Each expected label by name rather than a count of rows carrying Han.  A
    # count is satisfied by any other row that happens to be translated, which
    # would leave these two English and the assertion green.
    for key, english in pane_module.PASTE_BOX_ROWS:
        wanted = pane_module.PASTE_BOX_ROW_LABELS_CANTONESE[key]
        assert wanted in labels, (
            f"the {english!r} row -- which says where the blocks actually land "
            f"-- is not labelled {wanted!r}, so it is still English. The rows "
            f"in the pane are {labels}"
        )


def test_choosing_an_option_in_cantonese_selects_it(pane) -> None:
    """A Cantonese option chosen is the anchor that gets selected.

    The reverse lookup and the displayed list have to agree, and the way they
    stop agreeing is that one of them gets translated and the other does not.
    When that happens nothing raises: every choice simply matches nothing and
    falls back to the centre, so the picker silently does something other than
    what its options say.
    """
    choice = _anchor_choice(pane)
    assert choice is not None
    wanted = editor_tools.ANCHOR_MINIMUM
    label = editor_tools.anchor_label_cantonese(wanted)
    assert label in choice.options, (
        f"the picker does not offer {label!r} at all, so this test would be "
        f"checking a value nobody can pick. It offers {choice.options}"
    )

    choice.set_value(label, notify=True)
    wx.Yield()

    assert pane.position_anchor == wanted, (
        f"choosing {label!r} -- the lowest corner -- selected "
        f"{pane.position_anchor!r} instead. A Cantonese reader picking a "
        "corner would silently get the centre, which is the defect this "
        "section exists to remove rather than one to add"
    )


def test_an_unreadable_size_says_so_in_cantonese(
    app, cantonese: FakeTool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The honest unknown is a string the reader has to be able to read.

    This is the reading the rows carry when something has gone wrong, so it is
    the one a reader most needs and the easiest to leave in English -- and it
    is resolved on a different path from the rest, cached at build time rather
    than translated where it is used, so the wiring gets its own check.
    """
    monkeypatch.setattr(
        editor_tools,
        "pending_object",
        lambda *a, **k: editor_tools.PendingObject(
            location=LOCATION, drawn=True, extent=(0, 0, 0)
        ),
    )

    window = wx.Frame(None, size=(360, 700), pos=(-32000, -32000))
    try:
        built = pane_module.PropertiesPane(window, title="Test world")
        window.Show()
        wx.Yield()
        built.show_tool_activation(
            editor_tools.Activation(
                key="cloneTool", label="Clone", ok=True, tool="Paste", kind="pending"
            )
        )
        wx.Yield()

        rows = {
            node.label: node.value
            for node in _descendants(built)
            if isinstance(node, pane_module.PropertyRow)
        }
        unknown = [value for value in rows.values() if _has_han(value)]
        assert unknown, (
            "no row reads its unknown value in Cantonese, so a reader who "
            f"asked for Cantonese is told 'not known' in English: {rows}"
        )
        assert pane_module.BOX_VALUE_UNKNOWN_CANTONESE in unknown, (
            "the rows do not carry the Cantonese unknown reading the module "
            f"defines; they carry {unknown}"
        )

        sentences = [
            " ".join(str(node.GetLabel()).split())
            for node in _descendants(built)
            if isinstance(node, StudioText)
        ]
        assert any(_has_han(text) and "x" in text for text in sentences), (
            "the pane does not say in Cantonese that the size could not be "
            f"read. The paragraphs shown are {sentences}"
        )
    finally:
        window.Destroy()
        wx.Yield()


# ----------------------------------------------------------------------
# a setting that could not be remembered says so
# ----------------------------------------------------------------------


def test_an_anchor_that_could_not_be_stored_is_reported(
    pane, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed persist is said out loud, not swallowed.

    ``store_paste_anchor`` already answered whether the write reached disk and
    the answer was discarded, which is survivable for exactly one session: the
    anchor is right until the editor is closed and back to the centre when it
    reopens, with nothing on screen having admitted it.  A setting that
    silently forgets itself overnight is one the user changes again tomorrow
    without ever learning why.

    The notification is captured rather than shown, because what is being
    checked is that one was raised at all -- and a toast escaping into a test
    run is a window nobody closes.
    """
    raised: List[Tuple[str, str, str]] = []

    def refuse(_identifier: str, _value: Any) -> None:
        raise OSError("the profile is read-only")

    def record(_parent: Any, title: str, body: str, **kwargs: Any) -> None:
        raised.append((str(title), str(body), str(kwargs.get("severity", "info"))))

    monkeypatch.setattr(pane_module.config, "put", refuse)
    monkeypatch.setattr(pane_module, "notify", record)

    choice = _anchor_choice(pane)
    assert choice is not None
    choice.set_value(
        editor_tools.anchor_label_cantonese(editor_tools.ANCHOR_MAXIMUM), notify=True
    )
    wx.Yield()

    assert pane.position_anchor == editor_tools.ANCHOR_MAXIMUM, (
        "a profile that refused the write also lost the anchor for this "
        "session; the choice should still hold until the editor is closed"
    )
    assert raised, (
        "the anchor could not be written to the profile and nothing said so, "
        "so it will be back to the centre at the next start with no "
        "explanation anywhere"
    )
    title, body, severity = raised[0]
    assert severity == "warning", f"the failure was reported as {severity!r}"
    assert _has_han(title) and _has_han(body), (
        "the failure is reported in English to a reader who asked for "
        f"Cantonese: {title!r} / {body!r}"
    )
