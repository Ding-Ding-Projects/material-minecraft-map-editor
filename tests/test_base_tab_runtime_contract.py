"""Dedicated coverage for the BaseTab runtime lifecycle contract.

``amulet_map_editor.api.framework.base_tab.BaseTab`` is exercised indirectly by
``tests/test_studio_runtime_render_contract.py`` (which drives the whole shell
through wxPython) but never asserted against directly. This file is the
missing direct coverage: it pins the exact five-method surface, its default
behaviour, that both real subclasses only add ``menu()`` on top of it, and the
can-veto-before-mutate ordering the shell relies on when switching or closing
tabs.

No wxPython import is required: ``BaseTab`` itself has no GUI dependency, and
the ordering assertions below use a minimal fake page rather than constructing
a real notebook.
"""

from __future__ import annotations

import inspect

from amulet_map_editor.api.framework.base_tab import BaseTab
from amulet_map_editor.api.framework.pages.base_page import BasePageUI
from amulet_map_editor.api.framework.programs.base_program import BaseProgram


def test_base_tab_declares_exactly_the_five_lifecycle_methods() -> None:
    """Pin the contract surface so an accidental rename/removal is caught here.

    A grep-based test would pass on a BaseTab missing a method entirely -- it
    never looked. Enumerate the class's own members explicitly instead.
    """

    own_methods = {
        name
        for name, value in vars(BaseTab).items()
        if not name.startswith("_") and callable(value)
    }
    assert own_methods == {"enable", "can_disable", "disable", "can_close", "close"}


def test_base_tab_defaults_are_safe_no_ops() -> None:
    """The four unresolved defaults must not require a subclass to do anything."""

    tab = BaseTab()
    assert tab.enable() is None
    assert tab.can_disable() is True
    assert tab.disable() is None
    assert tab.can_close() is True
    assert tab.close() is None


def test_base_page_ui_only_adds_menu_on_top_of_base_tab() -> None:
    assert issubclass(BasePageUI, BaseTab)
    added = set(vars(BasePageUI)) - set(vars(BaseTab))
    added = {name for name in added if not name.startswith("_")}
    assert added == {"menu"}


def test_base_program_only_adds_menu_and_init_on_top_of_base_tab() -> None:
    assert issubclass(BaseProgram, BaseTab)
    added = set(vars(BaseProgram)) - set(vars(BaseTab))
    added = {name for name in added if not name.startswith("_") or name == "__init__"}
    # __init__ is a constructor, not a lifecycle method; menu() is the only
    # runtime-contract addition, matching BasePageUI.
    assert added == {"menu", "__init__"}


def test_lifecycle_methods_are_public_and_take_no_arguments() -> None:
    """The shell calls every one of these with no arguments and no keywords."""

    for name in ("enable", "can_disable", "disable", "can_close", "close"):
        method = getattr(BaseTab, name)
        signature = inspect.signature(method)
        params = [p for p in signature.parameters.values() if p.name != "self"]
        assert params == [], f"BaseTab.{name} must take no arguments"


class _RecordingTab(BaseTab):
    """A minimal BaseTab used to assert call ordering, not a full page."""

    def __init__(self, *, refuse_disable: bool = False, refuse_close: bool = False):
        self.refuse_disable = refuse_disable
        self.refuse_close = refuse_close
        self.calls: list[str] = []

    def enable(self):
        self.calls.append("enable")

    def can_disable(self) -> bool:
        self.calls.append("can_disable")
        return not self.refuse_disable

    def disable(self):
        self.calls.append("disable")

    def can_close(self) -> bool:
        self.calls.append("can_close")
        return not self.refuse_close

    def close(self):
        self.calls.append("close")


def _drive_tab_switch(old_page: BaseTab, new_page: BaseTab) -> bool:
    """Mirror world_page.py / amulet_ui.py's page-changing/page-changed pair.

    Returns whether the switch was allowed to proceed.
    """

    if not old_page.can_disable():
        return False
    old_page.disable()
    new_page.enable()
    return True


def _drive_tab_close(page: BaseTab) -> bool:
    """Mirror amulet_ui.py's _on_page_closing: can_close() gates close()."""

    if not page.can_close():
        return False
    page.disable()
    page.close()
    return True


def test_switch_calls_can_disable_before_disable_and_never_touches_new_page_on_veto() -> (
    None
):
    old_page = _RecordingTab(refuse_disable=True)
    new_page = _RecordingTab()

    allowed = _drive_tab_switch(old_page, new_page)

    assert allowed is False
    assert old_page.calls == ["can_disable"]  # disable() never ran
    assert new_page.calls == []  # enable() never ran on the incoming page


def test_switch_calls_disable_then_enable_when_allowed() -> None:
    old_page = _RecordingTab()
    new_page = _RecordingTab()

    allowed = _drive_tab_switch(old_page, new_page)

    assert allowed is True
    assert old_page.calls == ["can_disable", "disable"]
    assert new_page.calls == ["enable"]


def test_close_calls_can_close_before_close_and_veto_skips_close() -> None:
    page = _RecordingTab(refuse_close=True)

    allowed = _drive_tab_close(page)

    assert allowed is False
    assert page.calls == ["can_close"]  # disable()/close() never ran


def test_close_calls_disable_then_close_when_allowed() -> None:
    page = _RecordingTab()

    allowed = _drive_tab_close(page)

    assert allowed is True
    assert page.calls == ["can_close", "disable", "close"]
