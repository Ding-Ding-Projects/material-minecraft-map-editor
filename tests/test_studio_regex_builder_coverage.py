"""Every Amulet Studio search field carries the regex builder beside it.

The list of fields is hand-written, and that is the whole point.  A rule that
says "every ``SearchBar`` gets a builder" is true of a file containing no search
bar at all, so it would pass on the day a surface quietly shipped a bare text
control instead -- which is exactly the regression this is meant to catch.  Each
entry names the module, the placeholder the field actually shows, and what the
field searches, so a failure says which surface lost its builder rather than
that a count changed.

Adding a search field means adding a line here in the same change.  Deleting a
line to make the file pass is the one edit that defeats it.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDIO = ROOT / "amulet_map_editor" / "api" / "studio"

#: ``(module, placeholder marker, what the field searches)``.
REQUIRED_SEARCH_FIELDS = (
    ("backstage.py", "Search recent projects and worlds", "the recent-projects table"),
    ("backstage.py", "Search all surfaces", "the backstage surface index"),
    ("backstage.py", "Search detected worlds", "the world picker"),
    ("ribbon.py", "Search this tab's commands", "the active ribbon tab"),
    ("context_menu.py", "Search this menu", "every right-click menu"),
    ("context_menu.py", "Search tab groups", "the tab-group picker"),
    ("spec_dialog.py", "Search this window", "one surface's own sections and rows"),
    (
        "palette_dialog.py",
        "Search every command, setting, and pane",
        "the command palette",
    ),
    ("navigator.py", "Search navigator", "dimensions and selection boxes"),
    ("properties_pane.py", "Search these properties", "the properties pane"),
    ("nbt_studio.py", "Search tags", "the NBT tag tree"),
    ("memory_console.py", "Search every view", "the Memory Console's card views"),
    ("memory_console.py", "Search all feature articles", "the documentation reader"),
    ("widgets.py", "Search options", "every searchable dropdown"),
)

#: Modules that must never contain one of these, because each is a search or a
#: dropdown built without the shared behaviour behind it.
FORBIDDEN_CONTROLS = ("wx.SearchCtrl(", "wx.Choice(", "wx.ComboBox(")


def _studio_modules():
    return sorted(
        path
        for path in STUDIO.rglob("*.py")
        if "__pycache__" not in path.parts and path.name != "__init__.py"
    )


def _source(name: str) -> str:
    return (STUDIO / name).read_text(encoding="utf-8")


def test_the_list_of_search_fields_is_not_empty():
    # Guarding the guard: an emptied table would make every check below vacuous.
    assert len(REQUIRED_SEARCH_FIELDS) >= 14


def test_every_named_search_field_is_still_where_it_is_documented():
    missing = [
        f"{module}: {placeholder!r} ({subject})"
        for module, placeholder, subject in REQUIRED_SEARCH_FIELDS
        if placeholder not in _source(module)
    ]
    assert not missing, f"these search fields have disappeared: {missing}"


def test_every_module_holding_a_search_field_builds_it_from_the_shared_bar():
    problems = []
    for module, placeholder, subject in REQUIRED_SEARCH_FIELDS:
        source = _source(module)
        if "SearchBar(" not in source:
            problems.append(f"{module}: {subject} has no SearchBar")
    assert not problems, problems


def test_the_shared_bar_ships_the_builder_and_the_regex_opt_in_by_default():
    widgets = _source("widgets.py")
    signature = widgets.split("class SearchBar", 1)[1].split("\n    # -- state", 1)[0]
    assert "show_regex: bool = True" in signature
    assert "builder: bool = True" in signature
    assert "self.builder_button" in signature
    assert 'name=f"Regex builder for {state.label}"' in signature
    assert 'wx.CheckBox(self, label="Regex")' in signature
    assert "self.feedback = wx.StaticText(self, label=state.feedback())" in signature


def test_no_search_field_anywhere_in_the_studio_opts_out_of_the_builder():
    """Availability is mandatory even though using regex is the user's choice."""
    offenders = []
    for path in _studio_modules():
        source = path.read_text(encoding="utf-8")
        if "builder=False" in source or "show_regex=False" in source:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"these surfaces dropped the regex builder: {offenders}"


def test_the_builder_is_anchored_to_the_field_that_opened_it():
    widgets = _source("widgets.py")
    assert "class _RegexBuilderPopup(AnchoredPopup)" in widgets
    opener = widgets.split("def open_builder", 1)[1].split("\n    def ", 1)[0]
    assert "_RegexBuilderPopup(" in opener
    assert "self.builder_button or self.field" in opener
    # A modal dialog is the fallback for a display too small for the popover,
    # and nothing else; a builder that always opened a separate window would
    # send the user away from the field they are typing in.
    assert "_open_builder_dialog()" in opener
    assert "if self._builder_fits():" in opener


def test_the_builders_result_is_written_back_into_that_field_alone():
    widgets = _source("widgets.py")
    adopt = widgets.split("def _adopt_builder_result", 1)[1].split("\n    def ", 1)[0]
    assert "self.state" in adopt
    assert "self.refresh_feedback()" in adopt


def test_no_studio_surface_reintroduces_an_unsearchable_control():
    offenders = []
    for path in _studio_modules():
        source = path.read_text(encoding="utf-8")
        for marker in FORBIDDEN_CONTROLS:
            if marker in source:
                offenders.append(f"{path.relative_to(ROOT)}: {marker}")
    assert not offenders, offenders


def test_every_context_menu_carries_its_own_search_and_appearance_entry():
    context_menu = _source("context_menu.py")
    assert "SearchBar(" in context_menu
    assert "Edit appearance…" in context_menu
    assert "element_appearance" in context_menu


def test_the_searchable_dropdown_opens_a_real_search_rather_than_a_plain_list():
    widgets = _source("widgets.py")
    popup = widgets.split("def open_popup", 1)[1].split("\n    def ", 1)[0]
    assert "AnchoredPopup(" in popup
    assert "SearchBar(" in popup
    assert '"Search options"' in popup
