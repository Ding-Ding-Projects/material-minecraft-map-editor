"""A funny level styles the application's voice; it must never reach a control.

The tone is a shipping requirement and it belongs on every message the Studio
renders, errors included.  What it must not reach is the text *on a control*: a
button, a tab, a placeholder, a column heading, a menu item, a window title, a
card title, or the accessible name a screen reader reads out.  Those strings are
the application naming a thing rather than talking, and an aside on the end of a
name costs the reader the name and the layout together -- the Properties pane's
own status line wanted 904 pixels of a 202-pixel column at level five in
bilingual mode.

:mod:`tests.test_studio_label_tone_contract` guards this at *runtime* on two
surfaces, by building them and reading their labels back.  That is the stronger
test and it stays the primary one.  It cannot, however, cover a surface nobody
thought to build, and it cannot see a call site at all: a control whose label is
five words long passes it no matter which function produced the label, because
``studio_text`` leaves a short unpunctuated string alone.  That leniency is a
word-count guess standing in for the author's intent, and the first six-word
button anybody writes is styled the moment it is written -- which is exactly how
"Pick from a detected Minecraft install" shipped as a card title reading

    Pick from a detected Minecraft install (the code is dancing; the facts …)

while every runtime assertion in the suite stayed green.

So this file reads the call sites instead.  It is deliberately a source-text
test, because the question it answers is about what the source *says*, not about
what any particular window renders: a control-text sink must be fed
``studio_label``, and feeding it ``studio_text`` is the defect whether or not
that string happens to be short enough today.

Two halves, because a rule alone is not a guard:

* :func:`test_no_control_text_sink_is_toned` is the rule.  It fails on a sink
  fed a toned string.
* :func:`test_the_scan_still_finds_the_sinks` is the inverted assertion beside
  it.  A rule that only checks the sinks it can find passes cleanly on a file it
  has stopped matching -- a renamed module, a restructured constructor, a
  refactor that moved the labels somewhere the pattern no longer reaches.  The
  minimum counts below are hand-written for exactly that reason.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "amulet_map_editor" / "api" / "studio"

#: The toned function.  Reaching a control-text sink is what this file forbids.
TONED = "studio_text"

#: Keyword arguments that are, by name, text drawn on or announced for a
#: control.  ``hint`` is deliberately absent: a hint is an explanatory tooltip,
#: which is the application speaking about a control rather than naming it, and
#: the project keeps its tone on purpose -- see the note in
#: ``test_studio_label_tone_contract`` about the palette's size button.
CONTROL_KEYWORDS = frozenset({"name", "label", "title", "placeholder"})

#: Methods that write text onto a live control.  Each one is unambiguous about
#: what it is writing: ``SetName`` an accessible name, ``SetHint`` a
#: placeholder, ``SetTitle`` a window title.
#:
#: ``SetLabel`` is deliberately absent, and it is the interesting omission.  It
#: is wx's generic "put this text on this widget", so on a ``StudioButton`` it
#: writes a control's name and on a ``wx.StaticText`` it writes whatever prose
#: that label happens to display -- the Properties pane uses it for three
#: status sentences that are messages and rightly keep their tone.  Including it
#: made this file fail on all three, which would have been the guard reporting
#: its own imprecision as a defect in the product.  ``SetToolTip`` is absent for
#: the same reason ``hint`` is: an explanation is the application speaking.
CONTROL_SETTERS = frozenset({"SetName", "SetHint", "SetTitle"})

#: Constructors whose first text argument is unambiguously a control's own
#: label.  Widgets that take prose as readily as a name -- ``_Text``, which
#: draws both page headings and paragraphs -- are deliberately not here: a
#: sink list that guesses produces false failures, and a guard nobody trusts
#: gets deleted.
CONTROL_CONSTRUCTORS = frozenset(
    {
        "BarLabel",
        "Chip",
        "DashedButton",
        "SearchBar",
        "SectionLabel",
        "StudioButton",
        "_Caption",
        "_Eyebrow",
        "_InfoRow",
        "_RailButton",
        "_SegmentButton",
    }
)

#: Attributes a painted control keeps its own drawn name in.
CONTROL_ATTRIBUTES = frozenset({"title", "label", "labels"})

#: A notification's title names the event -- and for a good many of them it is
#: literally ``commands.label_for(key)``, the same string the ribbon tile and
#: the palette row render.  The body underneath is the sentence saying what
#: happened, and that one keeps its tone.
NOTIFY_TITLE_POSITION = {"notify": 0, "notify_exception": 0}

#: Every module that must be scanned, with the least number of control-text
#: sinks it must still yield.  Hand-written rather than discovered: the failure
#: this catches is a file quietly falling out of the scan, and a discovered list
#: shrinks silently along with it.  The floors are well under the real counts so
#: ordinary editing does not trip them.
REQUIRED_COVERAGE: Dict[str, int] = {
    "backstage.py": 60,
    "navigator.py": 10,
    "nbt_studio.py": 60,
    "palette_dialog.py": 20,
    "properties_pane.py": 25,
    "shell.py": 40,
    "status_bar.py": 10,
    "title_bar.py": 10,
    "widgets.py": 40,
}

#: The least number of sinks each *entry* in the lists above must still find.
#:
#: The per-file floors turned out not to be enough, and finding that out is the
#: reason this exists.  Renaming one widget out of
#: :data:`CONTROL_CONSTRUCTORS` -- the exact way a sink list rots -- left every
#: per-file total comfortably above its floor, because the ``name=`` keyword
#: alone carries most files.  A whole-rule total was not enough either:
#: ``StudioButton`` accounts for 56 of the 104 constructor sinks, so losing
#: ``BarLabel`` moved the total by four and nothing noticed.  The unit that has
#: to be counted is therefore the unit that rots -- one entry.
#:
#: ``SetTitle`` sits at zero on purpose, and it is the entry worth reading
#: twice: it is a real sink shape that this codebase currently expresses as a
#: ``title=`` keyword instead, so the rule matches nothing today.  Written down
#: as a zero it is a documented absence; left out of this table it would have
#: been an unguarded rule that looked guarded.
REQUIRED_BY_SINK: Dict[str, int] = {
    # constructors
    "BarLabel": 3,
    "Chip": 2,
    "DashedButton": 1,
    "SearchBar": 12,
    "SectionLabel": 7,
    "StudioButton": 45,
    "_Caption": 5,
    "_Eyebrow": 4,
    "_InfoRow": 1,
    "_RailButton": 3,
    "_SegmentButton": 1,
    # setters
    "SetHint": 3,
    "SetName": 140,
    "SetTitle": 0,
    # keywords
    "keyword:label": 150,
    "keyword:name": 280,
    "keyword:placeholder": 28,
    "keyword:title": 120,
    # painted attributes
    "attribute:label": 17,
    "attribute:labels": 1,
    "attribute:title": 5,
    # notification titles
    "notify": 45,
    "notify_exception": 0,
}


def _module_paths() -> List[Path]:
    return sorted(path for path in STUDIO.glob("*.py"))


def _contains_toned_call(node: ast.AST) -> ast.Call | None:
    """Return the ``studio_text`` call inside ``node``, at any depth.

    Depth matters: the Properties pane's placeholder was
    ``SetHint(single_line(studio_text(...)))``, so a check that only looked at
    the immediate argument would have called that sink clean.
    """
    for inner in ast.walk(node):
        if isinstance(inner, ast.Call):
            function = inner.func
            name = getattr(function, "id", None) or getattr(function, "attr", None)
            if name == TONED:
                return inner
    return None


def _sinks(tree: ast.AST) -> Iterator[Tuple[int, str, str, ast.AST]]:
    """Yield each control-text sink as (line, rule, description, value).

    The rule name travels with the sink so a caller can count per rule rather
    than only per file -- see :data:`REQUIRED_BY_RULE` for why that matters.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            called = getattr(function, "id", None) or getattr(function, "attr", None)

            if called in CONTROL_SETTERS and node.args:
                yield node.lineno, "setter", f"{called}(…)", node.args[0]

            if called in CONTROL_CONSTRUCTORS and len(node.args) >= 2:
                # (parent, label, …) is the shared shape of every widget listed.
                yield node.lineno, "constructor", f"{called}(parent, <label>)", node.args[
                    1
                ]

            position = NOTIFY_TITLE_POSITION.get(called or "")
            if position is not None and len(node.args) > position + 1:
                # nonblocking.notify(parent, title, body) shifts everything by
                # one; StudioShell.notify(title, body) does not.
                offset = (
                    1
                    if isinstance(function, ast.Attribute)
                    and not (
                        isinstance(function.value, ast.Name)
                        and function.value.id == "self"
                    )
                    else 0
                )
                index = position + offset
                if index < len(node.args):
                    yield node.lineno, "notify-title", f"{called}(<title>)", node.args[
                        index
                    ]

            for keyword in node.keywords:
                if keyword.arg in CONTROL_KEYWORDS:
                    yield node.lineno, "keyword", f"{called}({keyword.arg}=…)", keyword.value

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Attribute)
                    and target.attr in CONTROL_ATTRIBUTES
                ):
                    yield node.lineno, "attribute", f"self.{target.attr} = …", node.value


def _scan(path: Path) -> Tuple[int, List[str]]:
    """Return how many sinks ``path`` holds and which of them are toned."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    total = 0
    offenders: List[str] = []
    for line, _rule, description, value in _sinks(tree):
        total += 1
        toned = _contains_toned_call(value)
        if toned is not None:
            excerpt = ast.get_source_segment(source, value) or "?"
            offenders.append(
                f"{path.name}:{line}  {description}  <- {' '.join(excerpt.split())[:96]}"
            )
    return total, offenders


@pytest.mark.parametrize("path", _module_paths(), ids=lambda path: path.name)
def test_no_control_text_sink_is_toned(path: Path) -> None:
    """No button, tab, placeholder, heading, title, or name is built with tone."""
    _total, offenders = _scan(path)
    assert not offenders, "\n".join(
        [
            f"{len(offenders)} control-text call site(s) built with "
            f"{TONED}() instead of studio_label():",
        ]
        + ["  " + line for line in offenders]
        + [
            "",
            "A funny level styles what the application SAYS, never what it "
            "NAMES.  If one of these really is a message rather than a label, "
            "it does not belong in a control-text sink -- move the string, do "
            "not widen the rule.",
        ]
    )


def test_the_scan_still_finds_the_sinks() -> None:
    """Guard the guard: a scan that matches nothing passes every check above.

    Every assertion in this file is of the form "none of what I found is
    wrong".  On a file the scan has stopped matching -- renamed, restructured,
    or refactored so the labels arrive by a route the sink list does not know
    -- that sentence is true and meaningless.  This is the half that notices.
    """
    missing: List[str] = []
    thin: List[str] = []
    for name, floor in sorted(REQUIRED_COVERAGE.items()):
        path = STUDIO / name
        if not path.exists():
            missing.append(f"{name} is gone from {STUDIO}")
            continue
        found, _offenders = _scan(path)
        if found < floor:
            thin.append(f"{name}: {found} sink(s) found, at least {floor} expected")
    assert not missing, "\n".join(
        ["Modules on the coverage list have moved:"] + missing
    )
    assert not thin, "\n".join(
        [
            "The scan found far fewer control-text sinks than these modules "
            "hold, which means it has stopped matching them rather than that "
            "the product lost its controls:",
        ]
        + ["  " + line for line in thin]
    )


def _sink_keys() -> List[str]:
    """Return every entry the sink lists hold, in the table's own key form."""
    return sorted(
        list(CONTROL_CONSTRUCTORS)
        + list(CONTROL_SETTERS)
        + [f"keyword:{name}" for name in CONTROL_KEYWORDS]
        + [f"attribute:{name}" for name in CONTROL_ATTRIBUTES]
        + list(NOTIFY_TITLE_POSITION)
    )


def _count_by_sink() -> Dict[str, int]:
    """Return how many sites each sink-list entry currently matches."""
    counts: Dict[str, int] = {key: 0 for key in _sink_keys()}
    for path in _module_paths():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (
                        isinstance(target, ast.Attribute)
                        and target.attr in CONTROL_ATTRIBUTES
                    ):
                        counts[f"attribute:{target.attr}"] += 1
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if called in CONTROL_SETTERS and node.args:
                counts[called] += 1
            if called in CONTROL_CONSTRUCTORS and len(node.args) >= 2:
                counts[called] += 1
            if called in NOTIFY_TITLE_POSITION:
                counts[called] += 1
            for keyword in node.keywords:
                if keyword.arg in CONTROL_KEYWORDS:
                    counts[f"keyword:{keyword.arg}"] += 1
    return counts


def test_every_sink_entry_still_matches_the_studio() -> None:
    """Guard the guard, one sink-list entry at a time.

    Counting per file was not enough and counting per rule was not enough
    either -- both were tried, and both stayed green while a widget was renamed
    out of the constructor list, because one busy entry hid the loss of a quiet
    one.  ``StudioButton`` alone is 56 of the 104 constructor sinks.

    An entry is the unit that actually rots, so an entry is the unit counted.
    """
    counts = _count_by_sink()
    unlisted = [key for key in _sink_keys() if key not in REQUIRED_BY_SINK]
    assert not unlisted, "\n".join(
        [
            "These sink-list entries have no floor in REQUIRED_BY_SINK, so "
            "nothing would notice if they stopped matching. Add each one with "
            "the number of sites it finds today (0 is a fine answer, written "
            "down):",
        ]
        + ["  " + key for key in unlisted]
    )
    thin = [
        f"{key}: {counts.get(key, 0)} site(s) found, at least {floor} expected"
        for key, floor in sorted(REQUIRED_BY_SINK.items())
        if counts.get(key, 0) < floor
    ]
    assert not thin, "\n".join(
        [
            "These sink-list entries have stopped matching the Studio.  An "
            "entry that finds nothing cannot fail, so every green result above "
            "is silent about whatever it used to cover.  Either the widget was "
            "renamed and this list needs the new name, or the sites really are "
            "gone and the floor should come down deliberately:",
        ]
        + ["  " + line for line in thin]
    )


def test_the_rule_can_actually_fail() -> None:
    """Prove the detector fires, so a green run above is worth something.

    Written against a synthetic source rather than a real file: a rule that has
    never been seen to fail is a decoration, and hand-editing a shipped module
    to check it is a change nobody remembers to undo.
    """
    sample = ast.parse(
        "StudioButton(parent, studio_text('Remove from list…', '喺清單移除…'))\n"
        "widget.SetHint(single_line(studio_text('Search recent projects')))\n"
        "self.title = studio_text(source.title, source.cantonese_title)\n"
        "self.notify(studio_text(commands.label_for(key), ''), body)\n"
        "widget.SetName(studio_text('Dimension list'))\n"
        "Chip(parent, studio_text('Worlds', '世界'))\n"
        "_RailButton(parent, label, glyph, name=studio_text('Options'))\n"
    )
    caught = [
        description
        for _line, _rule, description, value in _sinks(sample)
        if _contains_toned_call(value) is not None
    ]
    assert len(caught) == 7, f"the detector caught only {caught}"

    clean = ast.parse(
        "StudioButton(parent, studio_label('Remove from list…', '喺清單移除…'))\n"
        "widget.SetToolTip(single_line(studio_text('An explanation.')))\n"
        "button = StudioButton(parent, label, hint=studio_text('An explanation.'))\n"
        "self.notify(studio_label('Saved'), studio_text('It was written.'))\n"
    )
    assert not [
        description
        for _line, _rule, description, value in _sinks(clean)
        if _contains_toned_call(value) is not None
    ], "the detector fired on a tooltip or a hint, which keep their tone by design"
