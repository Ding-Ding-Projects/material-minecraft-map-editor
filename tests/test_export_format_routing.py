"""The Structures Format dropdown decides which exporter runs.

Until this module existed it decided nothing.  The dropdown offered four
formats, raised no command, stored a value ``selected_value`` was never asked
for, and the Export button started the editor's Export tool with no operation
named -- so the tool landed on whichever entry its chooser sorted first.  That
entry is ``Export Construction``, because the construction plugin registers
itself as ``"\\tExport Construction"`` with a literal leading tab to sort itself
to the top.  Measured on a real world: pick ``schematic (.schematic)``, press
Export, and the tool opens on
``...export_operations.construction`` while the success toast reads "Export
Construction" back at the person who chose a schematic.

Three of the four options were therefore wrong, and the fourth was right by
accident, which is the worst shape a defect can take -- one visibly correct case
standing in for three broken ones.

**What is asserted here, and what is not.**  This module needs no display and no
world.  It checks the table, the mapping, and the two shell methods that carry a
format into the tool and report it back, each against a stand-in ``self``.  It
cannot see whether pressing Export *does* any of it; that is
``tests/test_export_format_runtime.py``, which opens a real world and reads the
exporter back off the chooser the user is looking at.  Neither is a substitute
for the other, and the runtime module skips itself on a host with no editor,
which in a summary line reads exactly like passing.

The exporter names are not taken on trust either: each one is read out of the
plugin file that declares it, by parsing that file's own ``export`` dictionary.
A name that drifts -- a plugin renamed, a typo introduced into the table -- is a
mismatch here rather than a tool that silently starts on the wrong exporter.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Any, Dict, List, Tuple

import pytest

from amulet_map_editor.api.studio import commands, ribbon_defs

wx = pytest.importorskip("wx", reason="wxPython is not installed in this environment")

from amulet_map_editor.api.studio.shell import StudioShell  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Where the stock export plugins live.  Their ``export["name"]`` is the string
#: the Export tool's chooser shows and the only stable handle on a plugin: the
#: operation loader's identifier is the file's path on this installation.
EXPORT_PLUGINS = (
    ROOT
    / "amulet_map_editor"
    / "programs"
    / "edit"
    / "plugins"
    / "operations"
    / "stock_plugins"
    / "export_operations"
)

#: The format value the dropdown stores, and the plugin file that must run for
#: it.  Written out by hand: a table derived from
#: :data:`ribbon_defs.STRUCTURE_FORMATS` would agree with it by construction and
#: go on agreeing through the exact regression this module exists for -- four
#: options collapsing back onto one exporter.
#:
#: The pairing is deliberately not derivable.  ``schem`` runs
#: ``sponge_schematic.py`` while ``schematic`` runs ``schematic.py``, so any
#: suffix, prefix or containment rule sends Sponge's ``.schem`` to the legacy
#: exporter and does it silently, because both write a real file.
EXPECTED: Tuple[Tuple[str, str], ...] = (
    ("construction", "construction.py"),
    ("mcstructure", "mcstructure.py"),
    ("schematic", "schematic.py"),
    ("schem", "sponge_schematic.py"),
)


def _declared_name(path: pathlib.Path) -> str:
    """Return the ``export["name"]`` a plugin file declares.

    Parsed rather than imported: every one of these modules imports wx and
    amulet-core at module scope, and the point of reading them is to compare
    against the real declaration rather than against a copy of it kept here.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        targets = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if "export" not in targets or not isinstance(node.value, ast.Dict):
            continue
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and key.value == "name"
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                return value.value
    raise AssertionError(f"{path.name} declares no export['name']")


def _format_select() -> Any:
    """Return the Structures tab's Format dropdown, or fail saying it is gone."""
    tab = ribbon_defs.tab("structures")
    assert tab is not None, "the ribbon offers no Structures tab at all"
    for group in tab.groups:
        for select in group.selects:
            if select.label == "Format":
                return select
    raise AssertionError(
        "the Structures tab has no Format dropdown; its groups are "
        f"{[group.title for group in tab.groups]}"
    )


# ----------------------------------------------------------------------
# the table
# ----------------------------------------------------------------------


def test_the_structures_tab_still_offers_a_format_dropdown() -> None:
    """Four options, these four, in this order.

    Without this every assertion below is satisfied by a ribbon with no Format
    dropdown on it, which is a rule about a thing done wrongly passing on the
    thing not being done at all.
    """
    select = _format_select()
    values = [option.value for option in select.options]
    assert values == [value for value, _plugin in EXPECTED], (
        "the Export group should offer construction, mcstructure, schematic and "
        f"Sponge schem as its formats; it offers {values}"
    )


def test_the_format_dropdown_raises_a_command() -> None:
    """The defect, stated directly: the dropdown raised nothing.

    A dropdown with no command is a control the user operates and nothing
    observes.  ``validate`` refuses one now, and this asserts the specific
    control that shipped as one.
    """
    select = _format_select()
    assert select.command, (
        "the Format dropdown raises no command, so changing it runs nothing -- "
        "which is how it came to store a value that decided nothing"
    )
    assert commands.command(commands.resolve(select.command)) is not None, (
        f"the Format dropdown raises {select.command!r}, which is not a "
        "registered command"
    )


def test_every_offered_format_names_an_exporter() -> None:
    """Every option in the list reaches a real exporter, and a different one."""
    select = _format_select()
    problems: List[str] = []
    operations: List[str] = []
    for option in select.options:
        operation = ribbon_defs.structure_format_operation(option.value)
        if not operation:
            problems.append(
                f"{option.value!r} ({option.label}) names no exporter, so "
                "choosing it can only run whichever exporter the tool was "
                "already showing"
            )
        operations.append(operation)
    assert not problems, problems
    assert len(set(operations)) == len(operations), (
        "two formats run the same exporter, so one of them writes a file it "
        f"does not name: {dict(zip([o.value for o in select.options], operations))}"
    )


@pytest.mark.parametrize("value,plugin", EXPECTED)
def test_each_format_names_the_plugin_that_writes_it(value: str, plugin: str) -> None:
    """One format, one plugin file, the name that file declares for itself."""
    path = EXPORT_PLUGINS / plugin
    assert path.is_file(), f"the {plugin} export plugin is missing from this build"
    declared = _declared_name(path)
    mapped = ribbon_defs.structure_format_operation(value)
    assert mapped, f"the {value!r} format names no exporter"
    assert " ".join(mapped.split()) == " ".join(declared.split()), (
        f"the {value!r} format asks for {mapped!r} and {plugin} declares itself "
        f"as {declared!r}. The Export tool matches on this name, so a mismatch "
        "means the tool stays on whatever it was already showing."
    )


def test_no_stock_exporter_is_unreachable_from_the_dropdown() -> None:
    """Every installed stock exporter is offered by some format.

    The rule the task states is the other direction -- every format offered must
    reach an exporter -- and this is its companion: an exporter this build ships
    and the ribbon cannot ask for is a feature nobody can get to from the
    ribbon.  It is asserted because there are exactly four of each; a build that
    grew a fifth exporter without a fifth format should say so here rather than
    in a user's puzzled bug report.
    """
    declared = {
        " ".join(_declared_name(path).split())
        for path in sorted(EXPORT_PLUGINS.glob("*.py"))
        if path.name != "__init__.py"
    }
    offered = {
        " ".join(item.operation.split()) for item in ribbon_defs.STRUCTURE_FORMATS
    }
    assert declared, "no stock export plugins were found to check against"
    assert declared == offered, (
        "the stock exporters and the formats the ribbon offers have drifted. "
        f"Installed but unreachable: {sorted(declared - offered)}. "
        f"Offered but not installed: {sorted(offered - declared)}."
    )


# ----------------------------------------------------------------------
# what the shell does with the chosen format
# ----------------------------------------------------------------------


class _Ribbon:
    """The one method the shell asks the ribbon for."""

    def __init__(self, value: str) -> None:
        self.value = value

    def selected_value(self, label: str) -> str:
        return self.value if label == "Format" else ""


class _Workspace:
    def __init__(self, value: str) -> None:
        self.ribbon = _Ribbon(value)


class _Tool:
    """A stand-in Export tool that reports whichever exporter it was given."""

    def __init__(self, showing: str = "") -> None:
        self.active_operation_name = showing
        self.active_operation_id = ""


class _Shell:
    """The smallest ``self`` the methods under test actually reach for.

    The three lookups that stand between the ribbon and the tool are the real
    implementations rather than stand-ins, because they are part of what is
    being tested: ``_export_operation`` is where a value with no exporter has to
    refuse rather than default, and a stub of it would be a second answer to
    that question that agrees with the test by construction.
    """

    project_path = "/tmp/test-world"
    doc_title = "test world"

    _ribbon_value = StudioShell._ribbon_value
    _export_operation = StudioShell._export_operation
    _selected_exporter = StudioShell._selected_exporter
    _tool_message = StudioShell._tool_message

    def __init__(self, value: str, showing: str = "") -> None:
        self.workspace = _Workspace(value)
        self.tool = _Tool(showing)
        self.activated: List[Tuple[str, Any]] = []
        self.said: List[Dict[str, str]] = []
        self.recorded: List[Tuple[str, Dict[str, Any]]] = []
        self.surfaces: List[str] = []

    # -- what the methods under test call ------------------------------
    def _editor_tool(self, name: str) -> Any:
        return self.tool if name == "Export" else None

    def _activate_tool(self, name: str, state: Any = None) -> bool:
        self.activated.append((name, state))
        # The real tool manager hands ``state`` to the tool's ``set_state``,
        # which selects that operation.  Modelled here so the message the shell
        # then builds is read off a tool that was actually told something.
        if isinstance(state, dict) and state.get("operation"):
            self.tool.active_operation_name = str(state["operation"])
        return True

    def _active_tool_name(self) -> str:
        return "Export"

    def _selection_corners(self) -> Tuple[Any, ...]:
        return (((0, 0, 0), (1, 1, 1)),)

    def _dimension_name(self) -> str:
        return "minecraft:overworld"

    def _record(self, key: str, payload: Dict[str, Any]) -> None:
        self.recorded.append((key, payload))

    def notify(self, title: Any, body: Any, severity: str = "info") -> None:
        self.said.append(
            {"title": str(title), "body": str(body), "severity": str(severity)}
        )

    def open_surface(self, key: str) -> None:
        self.surfaces.append(key)


def _bind(name: str, shell: _Shell, *args: Any) -> Any:
    """Call one ``StudioShell`` method against the stand-in above."""
    return getattr(StudioShell, name)(shell, *args)


@pytest.mark.parametrize("value,plugin", EXPECTED)
def test_pressing_export_asks_for_the_chosen_formats_exporter(
    value: str, plugin: str
) -> None:
    """Four formats, four different exporters asked for -- not four "an exporter".

    The state handed to the tool is the whole fix: without it the tool manager
    calls ``set_state(None)``, the chooser is left alone, and the tool shows
    whatever sorted first.
    """
    wanted = _declared_name(EXPORT_PLUGINS / plugin)
    shell = _Shell(value)
    _bind("_cmd_tool", shell, "export")
    assert shell.activated, "pressing Export did not ask the editor for any tool"
    name, state = shell.activated[-1]
    assert name == "Export", f"pressing Export started the {name!r} tool"
    assert isinstance(state, dict), (
        "pressing Export handed the Export tool no state, so its chooser is "
        "left on whatever it was already showing"
    )
    assert " ".join(str(state.get("operation", "")).split()) == " ".join(
        wanted.split()
    ), (
        f"choosing {value!r} should ask the Export tool for {wanted!r} and asked "
        f"for {state.get('operation')!r}"
    )


@pytest.mark.parametrize("value,plugin", EXPECTED)
def test_the_export_toast_names_the_format_that_was_chosen(
    value: str, plugin: str
) -> None:
    """The message says the format the user picked, not the default.

    It said "Export Construction" for all four, because it read the chooser --
    correctly -- and nothing had ever told the chooser anything.
    """
    wanted = " ".join(_declared_name(EXPORT_PLUGINS / plugin).split())
    label = ribbon_defs.structure_format_label(value)
    shell = _Shell(value)
    _bind("_cmd_tool", shell, "export")
    assert shell.said, "pressing Export said nothing at all"
    body = " ".join(shell.said[-1]["body"].split())
    # The whole sentence, not the two names somewhere in it.  A message saying
    # the tool was *asked* for this exporter and is showing another one contains
    # both names too, and is the opposite of what this test is about.
    assert f"writing {label} through the {wanted} exporter" in body, (
        f"choosing {value!r} should be reported as writing {label!r} through "
        f"{wanted!r}; the message was {shell.said[-1]['body']!r}"
    )
    assert shell.said[-1]["severity"] == "success", shell.said[-1]


def test_the_export_toast_refuses_to_claim_an_exporter_it_did_not_get() -> None:
    """A tool that ignored the request is reported as such, not as a success.

    The tool change is somebody else's handler and it may refuse.  Reporting the
    exporter that was *asked for* would reproduce the original defect one layer
    along: a confident sentence about a file nobody is going to write.
    """

    class _Stubborn(_Shell):
        def _activate_tool(self, name: str, state: Any = None) -> bool:
            self.activated.append((name, state))
            return True  # posted, and the tool declined to move

    shell = _Stubborn("schem", showing="Export Construction")
    _bind("_cmd_tool", shell, "export")
    body = shell.said[-1]["body"]
    assert "Export Sponge Schematic" in body and "Export Construction" in body, (
        "a tool that stayed on the wrong exporter must say both what was asked "
        f"for and what is showing; it said {body!r}"
    )


def test_the_export_history_entry_records_the_format() -> None:
    """The recorded action says which format it was, so a restore can read it."""
    shell = _Shell("mcstructure")
    _bind("_cmd_tool", shell, "export")
    assert shell.recorded, "exporting recorded nothing in the local history"
    _key, payload = shell.recorded[-1]
    assert payload.get("format") == "mcstructure", payload
    assert payload.get("exporter") == "Export Bedrock .mcstructure", payload


def test_an_unmapped_format_is_refused_rather_than_defaulted() -> None:
    """A value with no exporter says so; it does not quietly export something.

    Falling back to the first exporter is precisely the behaviour that shipped,
    and it is indistinguishable from working.
    """
    shell = _Shell("nonesuch")
    _bind("_cmd_tool", shell, "export")
    _name, state = shell.activated[-1]
    assert state is None, (
        "an unmapped format should ask the tool for nothing rather than name an "
        f"exporter nobody chose; it asked for {state!r}"
    )
    body = shell.said[-1]["body"]
    assert "No exporter" in body, body


def test_changing_the_dropdown_retargets_a_live_export_tool() -> None:
    """The dropdown's own command does something visible while Export is showing."""
    shell = _Shell("schematic")
    _bind("_cmd_set_export_format", shell, "setExportFormat")
    assert shell.activated, "changing the format asked the editor for nothing"
    name, state = shell.activated[-1]
    assert name == "Export", name
    assert state == {"operation": "Export Schematic (legacy)"}, state
    assert shell.said[-1]["severity"] == "success", shell.said[-1]
