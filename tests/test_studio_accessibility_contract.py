"""Every Studio control names itself, takes the keyboard, and follows the theme.

Accessibility is a completion requirement in this shell, not a later pass, and
the three properties checked here are the ones a screenshot cannot show: a
control with no accessible name is invisible to a screen reader while looking
perfect; a control that only answers a click is unreachable to anybody who does
not use one; a control that never re-reads the tokens keeps the old palette
after a theme change and looks like a rendering fault.

The widget inventory is hand-written.  "Every class that sets a name sets a good
one" is true of a file that sets none, so an enumeration is what makes a control
losing its name a failure instead of a silence.  The file reads the package as
source rather than importing it, so it proves what it proves on a machine
without wxPython.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "amulet_map_editor" / "api" / "studio"

#: The owner-drawn primitives every Studio surface is assembled from.  A user
#: operates each of these directly, so each must name itself.
REQUIRED_WIDGETS = (
    "StudioButton",
    "Chip",
    "SectionLabel",
    "Card",
    "Divider",
    "ToggleSwitch",
    "Stepper",
    "RangeRow",
    "Swatch",
    "ProgressRow",
    "OutlinedField",
    "PathField",
    "SearchBar",
    "SearchableChoice",
    "TextureTile",
    "FaceRow",
    "ImageSlot",
    "ListRow",
    "VectorField",
    "SlotGrid",
    "TreeRows",
    "KeyGate",
    "CollapsibleSection",
    "BulkActionBar",
)

#: The composed surfaces: the shell, its regions, and the two hand-built
#: windows.  ``(module, class)`` pairs.
REQUIRED_SURFACE_CLASSES = (
    ("shell.py", "StudioShell"),
    ("title_bar.py", "StudioTitleBar"),
    ("backstage.py", "BackstageView"),
    ("workspace.py", "WorkspaceView"),
    ("workspace.py", "BreadcrumbBar"),
    ("ribbon.py", "RibbonBar"),
    ("navigator.py", "NavigatorPanel"),
    ("viewport.py", "ViewportHost"),
    ("properties_pane.py", "PropertiesPane"),
    ("status_bar.py", "StatusBar"),
    ("spec_dialog.py", "SpecDialog"),
    ("palette_dialog.py", "CommandPalette"),
    ("context_menu.py", "SearchableContextMenu"),
    ("nbt_studio.py", "NbtStudioDialog"),
    ("memory_console.py", "MemoryConsoleDialog"),
)


#: ``module:class`` pairs allowed to answer a pointer without a matching key,
#: with the reason.  Dragging a window by its title bar is a pointer gesture
#: that has no keyboard equivalent; every control drawn *on* that bar is an
#: ordinary interactive widget and is not exempt.
POINTER_ONLY_EXCEPTIONS = {
    "title_bar.py:StudioTitleBar": "dragging the frame by its bar",
}


def _classes(module):
    """Return ``{name: (bases, source)}`` for the classes in one module."""
    path = module if isinstance(module, Path) else STUDIO / module
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: ([ast.unparse(base) for base in node.bases], ast.unparse(node))
        for node in tree.body
        if isinstance(node, ast.ClassDef)
    }


def _names_itself(body: str) -> bool:
    """Return whether a class gives its window an accessible name."""
    return "self._install(" in body or "SetName(" in body


def test_the_inventories_are_not_empty():
    # Guarding the guard: every check below is vacuous on an emptied list.
    assert len(REQUIRED_WIDGETS) >= 24
    assert len(REQUIRED_SURFACE_CLASSES) >= 15


def test_every_documented_widget_still_exists_and_is_exported():
    widgets = _classes("widgets.py")
    exported = (STUDIO / "widgets.py").read_text(encoding="utf-8").split("__all__", 1)[1]
    missing = [name for name in REQUIRED_WIDGETS if name not in widgets]
    unexported = [name for name in REQUIRED_WIDGETS if f'"{name}"' not in exported]
    assert not missing, f"these widgets have gone: {missing}"
    assert not unexported, f"these widgets are no longer exported: {unexported}"


def test_every_widget_gives_its_control_an_accessible_name():
    widgets = _classes("widgets.py")
    unnamed = [
        name for name in REQUIRED_WIDGETS if not _names_itself(widgets[name][1])
    ]
    assert not unnamed, f"these controls are invisible to a screen reader: {unnamed}"


def test_every_widget_inherits_the_shared_theme_and_focus_plumbing():
    """``refresh_theme`` comes from the shared mixins, so a repaint reaches all."""
    widgets = _classes("widgets.py")
    problems = []
    for name in REQUIRED_WIDGETS:
        bases, body = widgets[name]
        if not ({"_Themed", "_Interactive"} & set(bases)):
            problems.append(f"{name}: bases {bases} carry no theme plumbing")
        if "refresh_theme" not in body and "_install(" not in body:
            problems.append(f"{name}: never registers for a theme change")
    assert not problems, problems
    mixin = widgets["_Themed"][1]
    assert "def refresh_theme" in mixin
    assert "tokens.register_theme_listener" in mixin
    assert "self.SetName(name)" in mixin


def test_every_control_a_user_operates_answers_the_keyboard_as_well_as_a_click():
    interactive = _classes("widgets.py")["_Interactive"][1]
    for marker in (
        "wx.EVT_KEY_DOWN",
        "wx.WXK_RETURN",
        "wx.WXK_SPACE",
        "wx.EVT_SET_FOCUS",
        "wx.EVT_KILL_FOCUS",
        "self.activate()",
    ):
        assert marker in interactive, marker
    # Anything anywhere in the package that answers a click answers a key too,
    # either by mixing in the shared behaviour or by binding its own.
    offenders = []
    for path in sorted(STUDIO.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for name, (bases, body) in _classes(path).items():
            if f"{path.name}:{name}" in POINTER_ONLY_EXCEPTIONS:
                continue
            takes_click = "wx.EVT_LEFT_UP" in body or "wx.EVT_LEFT_DOWN" in body
            takes_key = (
                any(base.endswith("_Interactive") for base in bases)
                or "wx.EVT_KEY_DOWN" in body
                or "wx.EVT_CHAR_HOOK" in body
            )
            if takes_click and not takes_key:
                offenders.append(f"{path.name}/{name}")
    assert not offenders, f"these answer a click but not a key: {offenders}"


def test_focus_is_visible_wherever_it_can_land():
    widgets = (STUDIO / "widgets.py").read_text(encoding="utf-8")
    assert "def draw_focus_ring" in widgets
    assert widgets.count("draw_focus_ring(") >= 10


def test_every_composed_surface_names_itself_and_refreshes_its_theme():
    problems = []
    for module, name in REQUIRED_SURFACE_CLASSES:
        classes = _classes(module)
        if name not in classes:
            problems.append(f"{module}: {name} has gone")
            continue
        _bases, body = classes[name]
        if not _names_itself(body):
            problems.append(f"{module}/{name}: no accessible name")
        if "def refresh_theme" not in body:
            problems.append(f"{module}/{name}: cannot re-read the palette")
    assert not problems, problems


def test_control_height_comes_from_the_density_token_rather_than_a_number():
    """A touch target is a floor the tokens set, not a value each surface picks."""
    users = []
    for path in sorted(STUDIO.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if "tokens.control_height()" in path.read_text(encoding="utf-8"):
            users.append(path.name)
    assert "widgets.py" in users
    assert len(users) >= 5, users


def test_a_long_label_is_elided_rather_than_painted_past_its_control():
    widgets = (STUDIO / "widgets.py").read_text(encoding="utf-8")
    assert "def elide(" in widgets
    assert "def wrap_text(" in widgets
    # Bilingual mode returns two lines, and a control that drew only the first
    # would silently drop half the label.
    assert widgets.count('label.split("\\n")') >= 2
    assert 'self.GetLabel().split("\\n")' in widgets


def test_reduced_motion_is_honoured_rather_than_assumed_off():
    widgets = (STUDIO / "widgets.py").read_text(encoding="utf-8")
    assert "def reduced_motion(" in widgets


def test_the_shell_installs_real_accelerators_rather_than_drawing_them_only():
    shell = (STUDIO / "shell.py").read_text(encoding="utf-8")
    assert "def install_accelerators" in shell
    commands = (STUDIO / "commands.py").read_text(encoding="utf-8")
    assert "def accelerator_table" in commands
    assert "def mismatched_accelerators" in commands


def test_the_popup_surfaces_paint_themselves_and_stay_on_the_display():
    """An undecorated popup reads straight through to whatever is behind it."""
    widgets = (STUDIO / "widgets.py").read_text(encoding="utf-8")
    popup = widgets.split("class AnchoredPopup", 1)[1].split("\nclass ", 1)[0]
    assert "def refresh_theme" in popup
    assert "wx.EVT_PAINT" in popup
    assert "def work_area" in popup
    assert "wx.ScrolledWindow" in popup, "content taller than the popup must scroll"
