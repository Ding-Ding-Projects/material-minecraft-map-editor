"""Structural contract for the declarative Amulet Studio surface registry.

Most Studio windows are data rather than code: one :class:`Spec` entry becomes a
rendered dialog, an index row, a palette result, and a ribbon launcher target.
That leverage is the reason these checks exist -- a spec with an unknown section
kind, an action pointing at a surface nobody registered, or a ribbon tile naming
a command that was never implemented all look completely fine in the source and
only fail when a user presses the button.

Nothing here imports wxPython: the registry is pure data by design, so the whole
file runs on a machine with no display.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amulet_map_editor.api.studio import commands, ribbon_defs, specs, surfaces
from amulet_map_editor.api.studio import spec as spec_module
from amulet_map_editor.api.studio.spec import ACTION_KINDS, SECTION_KINDS

#: The section kinds the design declares.  Written out again here rather than
#: imported alone, because a test that only compares ``SECTION_KINDS`` to itself
#: would pass after somebody deleted a renderer and its kind together.
EXPECTED_SECTION_KINDS = (
    "search",
    "fields",
    "selects",
    "list",
    "keys",
    "tree",
    "chips",
    "checks",
    "ranges",
    "swatches",
    "progress",
    "keygate",
    "code",
    "note",
    "commits",
    "texture",
)


def test_every_declared_section_kind_is_the_designs_own_set():
    assert set(SECTION_KINDS) == set(EXPECTED_SECTION_KINDS)
    assert len(SECTION_KINDS) == len(EXPECTED_SECTION_KINDS)


def test_every_spec_family_loaded():
    assert specs.UNAVAILABLE_MODULES == ()
    assert set(specs.SPEC_MODULES) == {
        "core",
        "terrain_build",
        "entities_data",
        "analysis_worldgen",
        "tools_panels",
    }


def test_the_registry_is_not_empty():
    # A rule about "every spec" is satisfied by a registry holding none, so the
    # floor is asserted before anything is iterated.
    assert len(specs.SPECS) >= 100


def test_every_spec_is_addressable_and_titled():
    problems = []
    for key, spec in specs.SPECS.items():
        if spec.key != key:
            problems.append(f"{key}: registered under a key it does not carry")
        if not spec.eyebrow.strip():
            problems.append(f"{key}: no eyebrow")
        if not spec.title.strip():
            problems.append(f"{key}: no title")
        if not spec.confirm.strip():
            problems.append(f"{key}: no confirm label")
        if spec.width < 320:
            problems.append(f"{key}: width {spec.width} is narrower than a dialog")
    assert not problems, problems


def test_every_spec_has_sections_and_every_section_has_a_known_kind():
    problems = []
    for key, spec in specs.SPECS.items():
        if not spec.sections:
            problems.append(f"{key}: no sections")
        for index, section in enumerate(spec.sections):
            if section.kind not in SECTION_KINDS:
                problems.append(f"{key}: section {index} has kind {section.kind!r}")
    assert not problems, problems


def test_every_section_kind_is_actually_used_by_a_surface():
    """A renderer nobody reaches is a renderer nobody has ever seen work."""
    used = {section.kind for spec in specs.SPECS.values() for section in spec.sections}
    assert set(SECTION_KINDS) - used == set()


def test_no_section_is_empty_of_the_content_its_kind_promises():
    #: The member each kind must carry to draw anything at all.  ``note`` draws
    #: its hint, ``search`` draws a field the dialog owns, and ``keygate`` draws
    #: the shared gate, so those three carry no records of their own.
    required = {
        "fields": "fields",
        "selects": "selects",
        "list": "rows",
        "keys": "keys",
        "tree": "tree",
        "chips": "chips",
        "checks": "checks",
        "ranges": "ranges",
        "swatches": "swatches",
        "commits": "commits",
        "code": "code",
        "texture": "block_id",
    }
    problems = []
    for key, spec in specs.SPECS.items():
        for section in spec.sections:
            member = required.get(section.kind)
            if member is None:
                if section.kind == "note" and not section.hint.strip():
                    problems.append(f"{key}: a note section says nothing")
                continue
            if not getattr(section, member):
                problems.append(f"{key}: {section.kind} section has no {member}")
    assert not problems, problems


def test_texture_sections_name_a_block_and_a_drop_target():
    problems = []
    for key, spec in specs.SPECS.items():
        for section in spec.sections:
            if section.kind != "texture":
                continue
            if not section.block_id:
                problems.append(f"{key}: texture section previews no block")
            if not section.slot_id:
                problems.append(f"{key}: texture section has no drop-target slot")
            if not section.faces:
                problems.append(f"{key}: texture section draws no faces")
    assert not problems, problems


def test_a_generated_preview_always_admits_that_it_is_generated():
    """The swatch is generated, and a preview that implies otherwise misleads.

    A spec may replace the standard hint with wording of its own -- several do,
    because the design gives them one -- so the disclaimer cannot be asserted on
    the hint alone.  It travels with the tile instead: the renderer always draws
    a :class:`TextureTile`, whose own label says what it is.
    """
    assert "placeholder" in spec_module.TEXTURE_HINT.lower()
    assert "resource pack" in spec_module.TEXTURE_HINT.lower()
    renderer = (
        Path("amulet_map_editor/api/studio/spec_dialog.py")
        .read_text(encoding="utf-8")
        .split("def _render_texture", 1)[1]
        .split("\n    def ", 1)[0]
    )
    assert "widgets.TextureTile(" in renderer
    assert "spec_api.TEXTURE_HINT" in renderer
    tile = (
        Path("amulet_map_editor/api/studio/widgets.py")
        .read_text(encoding="utf-8")
        .split("class TextureTile", 1)[1]
        .split("\nclass ", 1)[0]
    )
    assert "label: str = blocks.PLACEHOLDER_LABEL" in tile
    blocks_source = Path("amulet_map_editor/api/studio/blocks.py").read_text(
        encoding="utf-8"
    )
    assert 'PLACEHOLDER_LABEL = "placeholder swatch"' in blocks_source


def test_every_progress_section_reports_a_bounded_fraction():
    problems = []
    for key, spec in specs.SPECS.items():
        for section in spec.sections:
            if section.kind != "progress":
                continue
            if not 0.0 <= section.progress_fraction <= 1.0:
                problems.append(f"{key}: fraction {section.progress_fraction}")
            if not section.progress_label.strip():
                problems.append(f"{key}: progress section has no readout")
    assert not problems, problems


def test_every_range_has_a_usable_span_and_a_value_inside_it():
    problems = []
    for key, spec in specs.SPECS.items():
        for section in spec.sections:
            for item in section.ranges:
                if item.min >= item.max:
                    problems.append(f"{key}/{item.label}: min is not below max")
                elif not item.min <= item.value <= item.max:
                    problems.append(f"{key}/{item.label}: value is outside its bounds")
                if item.step <= 0:
                    problems.append(f"{key}/{item.label}: step {item.step}")
    assert not problems, problems


def test_every_select_defaults_to_one_of_its_own_options():
    problems = []
    for key, spec in specs.SPECS.items():
        for section in spec.sections:
            for item in section.selects:
                if not item.options:
                    problems.append(f"{key}/{item.label}: no options")
                elif item.value and item.value not in item.options:
                    problems.append(f"{key}/{item.label}: default is not an option")
                if item.current() not in item.options and item.options:
                    problems.append(f"{key}/{item.label}: current() is not an option")
    assert not problems, problems


def test_every_action_resolves_to_a_real_surface_or_a_real_command():
    problems = []
    for key, spec in specs.SPECS.items():
        for action in spec.actions:
            if not action.label.strip():
                problems.append(f"{key}: an action has no label")
            if action.kind not in ACTION_KINDS:
                problems.append(f"{key}/{action.label}: kind {action.kind!r}")
            if action.surface and surfaces.surface(action.surface) is None:
                problems.append(
                    f"{key}/{action.label}: opens {action.surface!r}, which is "
                    "not in the surface index"
                )
            if action.command:
                resolved = commands.command(commands.resolve(action.command))
                if resolved is None:
                    problems.append(
                        f"{key}/{action.label}: runs {action.command!r}, which is "
                        "not a registered command"
                    )
    assert not problems, problems


def test_the_ribbon_definition_is_structurally_sound():
    assert ribbon_defs.validate() == ()
    assert len(ribbon_defs.RIBBON_TABS) == 17
    assert len(set(ribbon_defs.TAB_KEYS)) == len(ribbon_defs.TAB_KEYS)


def test_every_ribbon_button_opens_a_surface_or_runs_a_command_that_exists():
    indexed = set(surfaces.keys())
    problems = []
    for tab_key, group_title, button in ribbon_defs.all_buttons():
        where = f"{tab_key}/{group_title}/{button.label}"
        if button.surface and button.surface not in indexed:
            problems.append(f"{where}: surface {button.surface!r} is not indexed")
        if button.command:
            resolved = commands.command(commands.resolve(button.command))
            if resolved is None:
                problems.append(f"{where}: command {button.command!r} is unregistered")
    assert not problems, problems


def test_every_ribbon_group_launcher_opens_an_indexed_surface():
    indexed = set(surfaces.keys())
    problems = [
        f"{tab.key}/{group.title}: launcher {group.launcher!r} is not indexed"
        for tab in ribbon_defs.RIBBON_TABS
        for group in tab.groups
        if group.launcher not in indexed
    ]
    assert not problems, problems


def test_every_ribbon_dropdown_raises_a_registered_command():
    """Every dropdown names a command, and that command exists.

    The ``select.command and`` guard this filter used to open with made the rule
    "a command, if there is one, must be registered" -- which the Structures tab
    passed for two years by naming no command at all.  Its Format dropdown stored
    the user's choice, raised nothing, and was read by nobody, so all four of its
    options exported a ``.construction``.  A rule about a thing done wrongly is
    always satisfied by the thing not being done, so the empty case is now the
    first thing checked rather than the case skipped.
    """
    dropdowns = [
        (f"{tab.key}/{group.title}/{select.label}", select)
        for tab in ribbon_defs.RIBBON_TABS
        for group in tab.groups
        for select in group.selects
    ]
    assert dropdowns, (
        "the ribbon defines no dropdowns at all, so every assertion below "
        "passes on an empty list"
    )
    problems = []
    for where, select in dropdowns:
        if not select.command:
            problems.append(f"{where}: raises no command, so changing it runs nothing")
        elif commands.command(commands.resolve(select.command)) is None:
            problems.append(f"{where}: command {select.command!r} is unregistered")
    assert not problems, problems


#: A command key nothing registers, for feeding the rules below a binding that
#: names something real-looking and absent.
UNREGISTERED_COMMAND = "noCommandIsRegisteredUnderThisName"


def _field_problems(tabs) -> list:
    """Return every fault in the field grids of ``tabs``.

    The rule lives in a function rather than inline in its test so that the
    real ribbon and a definition broken on purpose are judged by *the same
    code*.  A guard nobody has watched fail is a guard nobody has tested, and
    the only way to watch this one fail without breaking the shipped ribbon is
    to hand it something broken -- which requires the rule to be callable.

    Order matters and is the whole point.  The empty binding is the first thing
    checked, unconditionally; the registration check hangs off it as an
    ``elif``.  Written the other way round -- ``if entry.command and ...`` --
    the rule says "a command, if there is one, must be registered", which a
    field naming no command satisfies perfectly.  That is not hypothetical:
    :func:`_field_problems_written_the_skipping_way` below is that version, and
    a test proves it misses exactly this case.
    """
    fields = [
        (f"{tab.key}/{group.title}/{entry.label}", entry)
        for tab in tabs
        for group in tab.groups
        for entry in group.fields
    ]
    if not fields:
        return [
            "the definition holds no field grids at all, so every rule below "
            "passes on an empty list"
        ]
    problems = []
    for where, entry in fields:
        if not entry.command:
            problems.append(f"{where}: raises no command, so typing in it runs nothing")
        elif commands.command(commands.resolve(entry.command)) is None:
            problems.append(f"{where}: command {entry.command!r} is unregistered")
        if entry.value:
            problems.append(
                f"{where}: ships the literal value {entry.value!r}, which is "
                "shown as though it described the open world"
            )
    return problems


def _field_problems_written_the_skipping_way(tabs) -> list:
    """The same rule as :func:`_field_problems`, in the shape that ships bugs.

    Kept deliberately, and exercised by a test below, because the difference
    between this function and the real one is one word, no reviewer has ever
    caught it by reading, and it is the exact shape that let a command-less
    dropdown pass its own guard for two years.
    """
    problems = []
    for tab in tabs:
        for group in tab.groups:
            for entry in group.fields:
                where = f"{tab.key}/{group.title}/{entry.label}"
                if (
                    entry.command
                    and commands.command(commands.resolve(entry.command)) is None
                ):
                    problems.append(
                        f"{where}: command {entry.command!r} is unregistered"
                    )
    return problems


def _tabs_with_one_field(command: str) -> tuple:
    """Return a one-group ribbon whose only control is a single typed box."""
    return (
        ribbon_defs.RibbonTab(
            key="probe",
            label="Probe",
            groups=(
                ribbon_defs.RibbonGroup(
                    title="Probe",
                    fields=(ribbon_defs.RibbonField("Probe box", command=command),),
                    launcher="probeLauncher",
                ),
            ),
        ),
    )


def _tabs_with_one_dropdown(command: str, option_value: str = "probeValue") -> tuple:
    """Return a one-group ribbon whose only control is a single dropdown."""
    return (
        ribbon_defs.RibbonTab(
            key="probe",
            label="Probe",
            groups=(
                ribbon_defs.RibbonGroup(
                    title="Probe",
                    selects=(
                        ribbon_defs.RibbonSelect(
                            "Probe list",
                            options=(
                                ribbon_defs.RibbonOption(option_value, "Probe option"),
                            ),
                            command=command,
                        ),
                    ),
                    launcher="probeLauncher",
                ),
            ),
        ),
    )


def test_every_ribbon_field_raises_a_registered_command():
    """Every typed box names a command, and that command exists.

    The same rule the dropdowns get one test above, because a text box that
    raises nothing has exactly the dropdown's defect.  All six of Selection >
    Coordinates were that: what was typed went into a dictionary whose only
    reader re-seeded the widget it had come from, so the boxes could be filled
    in with anything and the world never heard about it -- while displaying six
    numbers from the design mock as though they described the open selection.
    """
    assert _field_problems(ribbon_defs.RIBBON_TABS) == []


def test_the_field_rule_refuses_a_box_whose_binding_is_empty():
    """The empty case, asserted before the present-but-wrong one.

    This is the case the rule exists for and the case the natural way of
    writing it skips, so it is checked first here and first inside the rule.
    """
    problems = _field_problems(_tabs_with_one_field(""))
    assert problems, "the rule accepted a box that raises nothing at all"
    assert "raises no command" in problems[0], problems


def test_the_field_rule_refuses_a_box_naming_a_binding_nobody_registered():
    problems = _field_problems(_tabs_with_one_field(UNREGISTERED_COMMAND))
    assert problems, "the rule accepted a box naming a command that does not exist"
    assert "is unregistered" in problems[0], problems


def test_the_field_rule_notices_a_definition_holding_no_boxes_at_all():
    """A rule about every box is satisfied completely by there being none.

    So the collection's own emptiness is a fault the rule reports, rather than
    the silent pass it would otherwise be.
    """
    empty = (ribbon_defs.RibbonTab(key="probe", label="Probe", groups=()),)
    assert _field_problems(empty), "the rule passed on a definition with no boxes"


def test_the_field_rule_accepts_a_box_that_is_properly_bound():
    """The floor for the three tests above.

    Without it they would all pass on a rule that simply complained about
    everything it was ever shown.
    """
    assert _field_problems(_tabs_with_one_field(ribbon_defs.SELECTION_COMMAND)) == []


def test_the_skipping_shape_is_what_the_empty_case_check_prevents():
    """Proof that the shape matters, not merely that the check is present.

    The same unbound box is handed to both versions of the rule.  The shape
    this project keeps catching it; the shape that reads just as correct does
    not notice it at all.  If somebody ever rewrites :func:`_field_problems`
    into the skipping form, the second assertion here is what goes red.
    """
    unbound = _tabs_with_one_field("")
    assert _field_problems_written_the_skipping_way(unbound) == [], (
        "the demonstration has stopped demonstrating: the skipping form now "
        "catches the empty case, so this test proves nothing"
    )
    assert _field_problems(unbound), (
        "the real rule has been rewritten into the shape that skips the empty "
        "case, and an unbound box now ships silently"
    )


def test_validate_itself_refuses_a_field_that_names_no_command(monkeypatch):
    """The refusal inside ``validate()`` is exercised, not merely written.

    Deleting that refusal used to leave every test in this file green: the
    shipped ribbon has no unbound field, so ``validate()`` returned ``()``
    either way and the rule was decoration.  Feeding it a definition broken on
    purpose is what makes the refusal itself load-bearing.
    """
    monkeypatch.setattr(ribbon_defs, "RIBBON_TABS", _tabs_with_one_field(""))
    problems = ribbon_defs.validate()
    assert problems, "validate() accepted a field that raises nothing"
    assert any("raises no command" in problem for problem in problems), problems


def test_validate_accepts_the_same_field_once_it_is_bound(monkeypatch):
    """The floor for the refusal tests: this probe shape is otherwise clean."""
    monkeypatch.setattr(
        ribbon_defs, "RIBBON_TABS", _tabs_with_one_field(ribbon_defs.SELECTION_COMMAND)
    )
    assert ribbon_defs.validate() == ()


def test_validate_itself_refuses_a_dropdown_that_names_no_command(monkeypatch):
    monkeypatch.setattr(ribbon_defs, "RIBBON_TABS", _tabs_with_one_dropdown(""))
    problems = ribbon_defs.validate()
    assert problems, "validate() accepted a dropdown that raises nothing"
    assert any("raises no command" in problem for problem in problems), problems


def test_validate_refuses_a_dropdown_option_that_stores_no_value(monkeypatch):
    """An option is operable too, and its value is its binding.

    ``RibbonBar.set_select`` returns early on a value it cannot resolve, so a
    blank one is a row the user can pick that stores nothing and raises the
    dropdown's command not at all -- silent in a way that reads as the
    application ignoring the click.
    """
    monkeypatch.setattr(
        ribbon_defs,
        "RIBBON_TABS",
        _tabs_with_one_dropdown(ribbon_defs.SELECTION_COMMAND, option_value=""),
    )
    problems = ribbon_defs.validate()
    assert problems, "validate() accepted an option that stores no value"
    assert any("stores no value" in problem for problem in problems), problems


def test_validate_accepts_the_same_dropdown_once_it_is_bound(monkeypatch):
    monkeypatch.setattr(
        ribbon_defs,
        "RIBBON_TABS",
        _tabs_with_one_dropdown(ribbon_defs.SELECTION_COMMAND),
    )
    assert ribbon_defs.validate() == ()


def _probe_group(title: str, *, fields=(), selects=()) -> ribbon_defs.RibbonGroup:
    return ribbon_defs.RibbonGroup(
        title=title, fields=fields, selects=selects, launcher="probeLauncher"
    )


def _tabs(*groups) -> tuple:
    """Return a ribbon of one tab per ``(key, group)`` pair."""
    return tuple(
        ribbon_defs.RibbonTab(key=key, label=key.title(), groups=(group,))
        for key, group in groups
    )


def _bound_select(label: str, *options) -> ribbon_defs.RibbonSelect:
    return ribbon_defs.RibbonSelect(
        label,
        options=options or (ribbon_defs.RibbonOption("probeValue", "Probe option"),),
        command=ribbon_defs.SELECTION_COMMAND,
    )


def _bound_field(label: str) -> ribbon_defs.RibbonField:
    return ribbon_defs.RibbonField(label, command=ribbon_defs.SELECTION_COMMAND)


#: One deliberately broken definition per refusal ``validate()`` makes, beside a
#: phrase its complaint must contain.  Each of these was watched failing before
#: the rule that catches it was written: a guard nobody has seen fail is a guard
#: nobody has tested, and every one of these faults is invisible in the source.
BROKEN_DEFINITIONS = [
    pytest.param(
        _tabs(("probe", _probe_group("Probe", selects=(_bound_select(""),)))),
        "has no label",
        id="dropdown-with-no-label-cannot-be-read-back",
    ),
    pytest.param(
        _tabs(
            (
                "probe",
                _probe_group(
                    "Probe",
                    selects=(
                        _bound_select(
                            "Probe list",
                            ribbon_defs.RibbonOption("same", "One"),
                            ribbon_defs.RibbonOption("same", "Two"),
                        ),
                    ),
                ),
            )
        ),
        "lists the value",
        id="two-rows-that-do-the-same-thing",
    ),
    pytest.param(
        _tabs(
            (
                "probe",
                _probe_group(
                    "Probe",
                    selects=(
                        _bound_select(
                            "Probe list", ribbon_defs.RibbonOption("probeValue", "")
                        ),
                    ),
                ),
            )
        ),
        "draws a blank row",
        id="option-with-no-label",
    ),
    pytest.param(
        _tabs(
            ("one", _probe_group("One", selects=(_bound_select("Format"),))),
            ("two", _probe_group("Two", selects=(_bound_select("Format"),))),
        ),
        "share one entry in select_values",
        id="two-dropdowns-sharing-one-stored-value",
    ),
    pytest.param(
        _tabs(
            ("one", _probe_group("Probe", fields=(_bound_field("x1"),))),
            ("two", _probe_group("Probe", fields=(_bound_field("x1"),))),
        ),
        "share one entry in field_values",
        id="two-fields-sharing-one-stored-value",
    ),
]


@pytest.mark.parametrize("tabs, expected", BROKEN_DEFINITIONS)
def test_validate_refuses_each_definition_it_claims_to_refuse(
    monkeypatch, tabs, expected
):
    monkeypatch.setattr(ribbon_defs, "RIBBON_TABS", tabs)
    problems = ribbon_defs.validate()
    assert any(expected in problem for problem in problems), (expected, problems)


def test_every_ribbon_option_stores_a_value_the_dropdown_can_act_on():
    """Every row a user can pick names what picking it does.

    The empty case first, as everywhere else in this file: a rule about every
    option is satisfied entirely by a ribbon that offers none.
    """
    options = [
        (f"{tab.key}/{group.title}/{select.label}", option)
        for tab in ribbon_defs.RIBBON_TABS
        for group in tab.groups
        for select in group.selects
        for option in select.options
    ]
    assert options, (
        "the ribbon defines no dropdown options at all, so every assertion "
        "below passes on an empty list"
    )
    problems = []
    for where, option in options:
        if not option.value.strip():
            problems.append(f"{where}: an option stores no value")
        if not option.label.strip():
            problems.append(f"{where}: an option draws a blank row")
    assert not problems, problems


def test_the_drawn_accelerator_and_the_registered_one_cannot_drift():
    assert commands.mismatched_accelerators() == ()
