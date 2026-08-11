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
    problems = [
        f"{tab.key}/{group.title}/{select.label}: {select.command!r}"
        for tab in ribbon_defs.RIBBON_TABS
        for group in tab.groups
        for select in group.selects
        if select.command
        and commands.command(commands.resolve(select.command)) is None
    ]
    assert not problems, problems


def test_the_drawn_accelerator_and_the_registered_one_cannot_drift():
    assert commands.mismatched_accelerators() == ()
