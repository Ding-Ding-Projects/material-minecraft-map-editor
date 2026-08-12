"""A funny level styles the application's voice, never the text on a control.

The two funny-level sliders are a shipping requirement and they reach every
message the Studio renders, errors included.  What they must not reach is a
*label*: the text on a button, a tab, a placeholder, a column heading, a window
title, a menu item, a status pill, or the accessible name a screen reader reads
out.  Those strings are the application naming a thing rather than talking, and
an aside on the end of a name costs the reader the name and the layout at once.
It shipped that way: at level five the command palette's own button read

    Tell me what to do (the code is dancing; the facts stay put)

in a 40-pixel title bar, and the palette's result rows carried the same clause
into a 660-pixel card that elides its labels.

This file builds the two surfaces for real, at level five, in both languages,
and reads the labels back.  It is deliberately not a grep: the styling happens
at construction time from the persisted profile, so the only way to know what a
control actually says is to build it and ask it.

The stock asides are *derived from* :func:`amulet_map_editor.api.tts_narrator.
style_text` rather than copied here, by styling a sentinel at every level in
both languages and keeping what was appended.  A sixth aside added tomorrow is
therefore covered the moment it exists, and this file needs no edit.

And the contract runs the other way too, which is the half that was missing.
Forbidding tone on a name catches a message built with the wrong function only
if somebody happens to look; nothing about a silent, deadpan sentence *fails*.
It shipped that way as well: the five template cards on Home and the four
source rows on Open had their description sentences quietly moved onto the
label function, so the paragraph above the cards moved with the funny level and
every sentence below it went flat.  Nine strings, all of them full sentences,
and the whole suite stayed green -- because a guard that only forbids can only
ever notice the thing that was done, never the thing that stopped being done.
:data:`TONED_MESSAGE_SURFACES` is the hand-written other half.
"""

from __future__ import annotations

import os
from typing import List, Tuple

import pytest

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api import preferences, tts_narrator  # noqa: E402
from amulet_map_editor.api.studio import copy as studio_copy  # noqa: E402
from amulet_map_editor.api.studio import backstage  # noqa: E402
from amulet_map_editor.api.studio import palette_dialog, title_bar  # noqa: E402

#: The corner the host frame lives at, so running this on a visible desktop
#: never throws a title bar and a palette across somebody's screen.
OFFSCREEN = (-32000, -32000)

#: Both baseline languages.  Bilingual is the two of them joined, so an aside
#: that reached either one would be caught in that mode as well.
LANGUAGE_MODES: Tuple[str, ...] = ("english", "cantonese")

#: Sentence used to make the narrator reveal its asides.  It carries no facts
#: worth styling and ends in a full stop, so whatever comes back after it is
#: exactly the aside and nothing else.
SENTINEL = "Amulet Studio label contract sentinel."

#: Attributes the Studio's owner-drawn controls keep their painted text in.
#: ``GetLabel`` covers the native controls and the shared button; a control that
#: paints its own text -- the title bar's shortcut pill, the palette's eyebrow
#: and its rows -- keeps it in one of these instead, and it is precisely those
#: that a screenshot would show and a naive sweep would miss.
PAINTED_TEXT_ATTRIBUTES: Tuple[str, ...] = (
    "label",
    "text",
    "accelerator",
    "_display",
    "_label",
    "_text",
)


def stock_asides() -> Tuple[str, ...]:
    """Return every aside the shared narrator tone can append, stripped.

    Read out of :func:`tts_narrator.style_text` by styling a sentinel rather
    than transcribed, so this file cannot drift from the module it is guarding
    and a newly added level or language is covered without anybody remembering
    to come back here.
    """
    found: List[str] = []
    for language in ("english", "cantonese"):
        for level in range(1, 6):
            styled = tts_narrator.style_text(SENTINEL, language, level)
            if styled == SENTINEL or not styled.startswith(SENTINEL):
                continue
            aside = styled[len(SENTINEL) :].strip()
            if aside and aside not in found:
                found.append(aside)
    return tuple(found)


ASIDES = stock_asides()


def _record(collected: List[Tuple[str, str]], owner: wx.Window, kind: str, value):
    text = str(value or "").strip()
    if text:
        collected.append((f"{type(owner).__name__}.{kind}", text))


def _control_labels(
    root: wx.Window, *, include_tooltips: bool
) -> List[Tuple[str, str]]:
    """Return every piece of control text under ``root``, with where it came from.

    Accessible names, rendered labels, and placeholders are swept on every
    surface, because all three are text on a control.  Tooltips are swept only
    where every tooltip on the surface names its control; the palette's size
    button carries an explanation instead, which is the application speaking and
    keeps its tone, so sweeping it there would fail a deliberate decision.
    """
    collected: List[Tuple[str, str]] = []
    stack: List[wx.Window] = [root]
    while stack:
        window = stack.pop()
        stack.extend(window.GetChildren())
        _record(collected, window, "name", window.GetName())
        for getter_name, kind in (("GetLabel", "label"), ("GetHint", "placeholder")):
            getter = getattr(window, getter_name, None)
            if not callable(getter):
                continue
            try:
                _record(collected, window, kind, getter())
            except Exception:  # pragma: no cover - platform boundary
                continue
        for attribute in PAINTED_TEXT_ATTRIBUTES:
            value = getattr(window, attribute, None)
            if isinstance(value, str):
                _record(collected, window, attribute, value)
        if include_tooltips:
            tip = window.GetToolTip()
            if tip is not None:
                _record(collected, window, "tooltip", tip.GetTip())
    return collected


def _offenders(labels: List[Tuple[str, str]]) -> List[str]:
    """Return every collected label carrying a stock aside, named and quoted."""
    return [
        f"{where} = {text!r} carries {aside!r}"
        for where, text in labels
        for aside in ASIDES
        if aside in text
    ]


def _tone_would_reach(labels: List[Tuple[str, str]]) -> List[str]:
    """Return the collected labels the funny level would actually have styled.

    ``studio_text`` leaves a short, unpunctuated string alone, so a surface made
    entirely of one-word buttons would pass the assertion below no matter which
    function built it.  Counting the strings tone *could* have reached is what
    stops this file quietly guarding nothing -- and it is why the Cantonese
    threshold is lower than the English one, since a Cantonese label has no
    spaces in it and so reads as short to that heuristic.
    """
    return [text for _where, text in labels if not studio_copy.is_verbatim(text)]


@pytest.fixture(scope="module")
def app():
    # Reuse a live ``wx.App`` when the session already has one, and only
    # create -- and later destroy -- a fresh instance when it does not.
    # Unconditionally creating a second ``wx.App`` and then unconditionally
    # destroying it clears wx's notion of "the current app" out from under
    # every other test module -- the exact sequence that corrupts wxPython's
    # SIP class table for platform-native widgets such as
    # ``wx.PopupTransientWindow``.
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


@pytest.fixture(scope="module")
def profile(tmp_path_factory):
    """Point the profile at a throwaway directory for the whole module.

    The tone is read from the persisted preferences at construction time, so the
    test has to write real preferences; writing them into a temporary profile is
    what keeps it from editing the language and funny levels of whoever ran it.
    """
    directory = tmp_path_factory.mktemp("studio-label-tone-profile")
    previous = os.environ.get("CONFIG_DIR")
    os.environ["CONFIG_DIR"] = str(directory)
    try:
        yield directory
    finally:
        if previous is None:
            os.environ.pop("CONFIG_DIR", None)
        else:
            os.environ["CONFIG_DIR"] = previous


@pytest.fixture(scope="module")
def host(app):
    frame = wx.Frame(None, title="studio label tone contract", pos=OFFSCREEN)
    frame.Show()
    wx.Yield()
    yield frame
    frame.Destroy()
    wx.Yield()


def _at_maximum_playfulness(mode: str) -> None:
    """Put the profile in ``mode`` with both funny levels at five."""
    preferences.update(
        language_mode=mode,
        funny_level_english=5,
        funny_level_cantonese=5,
    )
    assert studio_copy.language_mode() == mode
    assert studio_copy.funny_levels() == (5, 5)


def test_the_asides_were_actually_found():
    """Guarding the guard: an empty aside list would pass every check below."""
    assert len(ASIDES) >= 6, f"only {len(ASIDES)} asides came back: {ASIDES}"
    assert all(aside.strip() for aside in ASIDES)


def test_the_asides_are_read_from_the_narrator_rather_than_copied():
    """Every aside this file checks must be one the narrator really produces."""
    produced = {
        tts_narrator.style_text(SENTINEL, language, level)
        for language in ("english", "cantonese")
        for level in range(3, 6)
    }
    for aside in ASIDES:
        assert any(
            aside in styled for styled in produced
        ), f"{aside!r} is not something style_text produces"


@pytest.mark.parametrize("mode", LANGUAGE_MODES)
def test_no_title_bar_label_carries_a_funny_level_aside(profile, host, mode):
    _at_maximum_playfulness(mode)
    bar = title_bar.StudioTitleBar(host, host, title="Untitled project")
    try:
        wx.Yield()
        bar.Layout()
        labels = _control_labels(bar, include_tooltips=True)
        assert len(labels) >= 15, f"only {len(labels)} label(s) were read back"
        assert any(
            "Tell me what to do" in text or "話我知你想做乜" in text
            for _where, text in labels
        ), "the palette pill's own label was not among the text that was read"
        assert _tone_would_reach(labels), (
            "no title-bar label is long enough for the funny level to have "
            "styled it, so this assertion proves nothing"
        )
        assert not _offenders(labels), "\n".join(
            ["title-bar control text carrying a narrator aside:"]
            + ["  " + line for line in _offenders(labels)]
        )
    finally:
        bar.Destroy()
        wx.Yield()


@pytest.mark.parametrize("mode", LANGUAGE_MODES)
def test_no_command_palette_label_carries_a_funny_level_aside(profile, host, mode):
    _at_maximum_playfulness(mode)
    palette_dialog.build_index(refresh=True)
    palette = palette_dialog.CommandPalette(host, layout="card")
    try:
        wx.Yield()
        assert palette.rows, "the palette rendered no rows, so nothing was read"
        labels = _control_labels(palette, include_tooltips=False)
        assert len(labels) >= 40, f"only {len(labels)} label(s) were read back"
        assert (
            len(_tone_would_reach(labels)) >= 3
        ), "no palette label is long enough for the funny level to have styled it"
        assert not _offenders(labels), "\n".join(
            ["command-palette control text carrying a narrator aside:"]
            + ["  " + line for line in _offenders(labels)]
        )
    finally:
        palette.Destroy()
        wx.Yield()


@pytest.mark.parametrize("mode", LANGUAGE_MODES)
def test_every_palette_row_label_is_built_without_tone(profile, host, mode):
    """The rows are checked at the source as well as on the built controls.

    A row's rendered label is also what :func:`palette_dialog.reveal` matches
    against the accessible name of the element it teleports to, so tone leaking
    in here would break navigation rather than merely look wrong -- and it would
    break it only for readers who had turned the funny level up.
    """
    _at_maximum_playfulness(mode)
    index = palette_dialog.build_index(refresh=True)
    assert len(index) >= 50, f"the palette index holds only {len(index)} rows"
    offenders = _offenders(
        [(f"{result.kind}:{result.key}", result.display_label()) for result in index]
    )
    assert not offenders, "\n".join(
        ["palette row labels carrying a narrator aside:"]
        + ["  " + line for line in offenders[:12]]
    )


# ----------------------------------------------------------------------
# The other half: messages that must still be styled.
# ----------------------------------------------------------------------


def _template_cards(parent: wx.Window) -> List[Tuple[str, wx.Window]]:
    """Build every Home template card for real."""
    return [
        (f"template:{template.title}", backstage._TemplateCard(parent, template))
        for template in backstage.TEMPLATES
    ]


def _source_rows(parent: wx.Window) -> List[Tuple[str, wx.Window]]:
    """Build every Open source row for real."""
    return [
        (f"source:{source.title}", backstage._SourceRow(parent, source))
        for source in backstage.OPEN_SOURCES
    ]


#: Surfaces whose painted prose MUST move with the funny level, written out by
#: hand rather than discovered.
#:
#: Hand-written is the whole point.  A rule that says "whatever prose is here
#: must be toned" is satisfied by a surface with no prose left on it, so it goes
#: on passing while the sentences it was guarding disappear one at a time.  This
#: list names the surface, so removing the last toned string from one of them
#: fails here and has to be argued for rather than merely happening.
#:
#: Each entry is (name, builder, attribute holding the painted message).  The
#: attribute is the card's ``hint`` in both cases: the sentence painted under
#: the title, and the same string handed to ``SetToolTip``.
TONED_MESSAGE_SURFACES: Tuple = (
    ("Home template cards", _template_cards, "hint"),
    ("Open source rows", _source_rows, "hint"),
)


@pytest.mark.parametrize("mode", LANGUAGE_MODES)
@pytest.mark.parametrize(
    "surface",
    TONED_MESSAGE_SURFACES,
    ids=[entry[0] for entry in TONED_MESSAGE_SURFACES],
)
def test_a_card_description_still_reads_in_the_readers_voice(
    profile, host, mode, surface
):
    """Every card's description sentence carries the level-five aside.

    These are messages by every test the project applies: full sentences, ending
    in sentence punctuation, the application explaining rather than naming.  They
    are painted under the title and handed to ``SetToolTip``, and both of those
    are the application talking.
    """
    name, builder, attribute = surface
    _at_maximum_playfulness(mode)
    built = builder(host)
    try:
        assert built, f"{name} built nothing, so this assertion proves nothing"
        flat: List[str] = []
        for where, control in built:
            text = str(getattr(control, attribute, "") or "")
            assert text, f"{where}.{attribute} is empty"
            if not any(aside in text for aside in ASIDES):
                flat.append(f"{where}.{attribute} = {text!r}")
        assert not flat, "\n".join(
            [
                f"{name}: {len(flat)} of {len(built)} description(s) went deadpan "
                f"at funny level five in {mode} -- a message built with the label "
                f"function, which strips the tone the sliders exist to apply:"
            ]
            + ["  " + line for line in flat]
        )
    finally:
        for _where, control in built:
            control.Destroy()
        wx.Yield()


@pytest.mark.parametrize(
    "surface",
    TONED_MESSAGE_SURFACES,
    ids=[entry[0] for entry in TONED_MESSAGE_SURFACES],
)
def test_those_descriptions_are_prose_the_tone_can_actually_reach(surface):
    """Guarding the guard: tone leaves a short unpunctuated string alone.

    If every description were three words long the assertion above would be
    unfalsifiable -- ``studio_text`` would return them unchanged and a reader
    would conclude the tone was broken.  Each one is checked here to be prose
    the styling would really have touched.
    """
    name, builder, _attribute = surface
    sources = (
        backstage.TEMPLATES if builder is _template_cards else backstage.OPEN_SOURCES
    )
    verbatim = [
        source.hint for source in sources if studio_copy.is_verbatim(source.hint)
    ]
    assert not verbatim, (
        f"{name}: {len(verbatim)} description(s) are short enough that the funny "
        f"level would leave them alone either way, so the test above cannot fail "
        f"on them: {verbatim}"
    )


@pytest.mark.parametrize("mode", LANGUAGE_MODES)
@pytest.mark.parametrize(
    "surface",
    TONED_MESSAGE_SURFACES,
    ids=[entry[0] for entry in TONED_MESSAGE_SURFACES],
)
def test_the_title_above_each_description_stays_a_name(profile, host, mode, surface):
    """The two halves of the contract, on one control, at the same moment.

    A card is where the distinction is easiest to see and easiest to get wrong:
    the title names the card and takes no tone, the sentence two lines below it
    is the application talking and does.  ``Pick from a detected Minecraft
    install`` is the title that shipped with an aside appended at title weight,
    which is what started all of this.
    """
    name, builder, _attribute = surface
    _at_maximum_playfulness(mode)
    built = builder(host)
    try:
        offenders = _offenders(
            [
                (f"{where}.title", str(getattr(control, "title", "") or ""))
                for where, control in built
            ]
        )
        assert not offenders, "\n".join(
            [f"{name}: card titles carrying a narrator aside:"]
            + ["  " + line for line in offenders]
        )
    finally:
        for _where, control in built:
            control.Destroy()
        wx.Yield()
