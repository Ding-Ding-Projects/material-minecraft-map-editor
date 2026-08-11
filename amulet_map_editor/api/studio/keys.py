"""The one place a Studio surface reads the 3D editor's live key bindings.

The viewport's keys are user-configurable, so **nothing that shows one to a
reader may write it down**.  Every surface that prints a 3D editor key resolves
it here, against the key group the editor is actually listening to: the
viewport's right-click menu, the Key Select window, and the sentences the
selection commands quote when they hand the keyboard a gesture.

This module deliberately imports no ``wx``.  It is read while a surface
description is being *built*, which happens at import time and again every time
the Key Select surface is opened, and a data module that drags the whole widget
toolkit in behind it would make that unaffordable.

**Every failure route returns nothing.**  An unreadable configuration, an
absent editor package, a hand-edited profile: each produces an empty reading,
and a caller then shows no key rather than the shipped default.  That
distinction is the whole point -- the shipped default is precisely the key a
user who rebound the action no longer presses, so printing it is worse than
printing nothing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

from amulet_map_editor.api.studio.spec import KeyBinding

log = logging.getLogger(__name__)

__all__ = [
    "EDITOR_ACTION_LABELS",
    "KEY_NAMES",
    "NOT_BOUND",
    "UNREADABLE",
    "KeyGroups",
    "action_label",
    "active_keybinds",
    "declared_actions",
    "editor_bindings",
    "format_binding",
    "key_config",
    "read_key_groups",
    "viewport_accelerator",
]


#: How the 3D editor's serialised key names read on screen.  A name absent from
#: here is shown exactly as the editor stores it, which is ugly but true.
KEY_NAMES: Mapping[str, str] = MappingProxyType(
    {
        "MOUSE_LEFT": "LMB",
        "MOUSE_MIDDLE": "MMB",
        "MOUSE_RIGHT": "RMB",
        "MOUSE_AUX_1": "Mouse 4",
        "MOUSE_AUX_2": "Mouse 5",
        "MOUSE_WHEEL_SCROLL_UP": "Scroll up",
        "MOUSE_WHEEL_SCROLL_DOWN": "Scroll down",
        "CTRL": "Ctrl",
        "SHIFT": "Shift",
        "ALT": "Alt",
        "SPACE": "Space",
        "TAB": "Tab",
        "ESCAPE": "Esc",
    }
)

#: What a row shows for an action the active key group has no binding for.  It
#: is a sentence rather than a blank, because a blank column reads as a surface
#: that failed to load rather than as an action nobody bound.
NOT_BOUND = "not bound"

#: The one row a bindings list carries when the configuration cannot be read at
#: all.  A surface still shows a bindings section rather than dropping it, so
#: the reader is told the keys are unknown instead of being left to wonder where
#: the list went -- and so the shipped defaults, which are exactly the keys a
#: user who rebound them no longer presses, are still not printed.
UNREADABLE = ("Key configuration", "could not be read")

#: How each 3D editor action reads as a row label.  An action missing from here
#: still appears, labelled from its own identifier by :func:`action_label`, so a
#: new editor action shows up in the Key Select window the day it lands rather
#: than the day somebody remembers to add it to a list.
EDITOR_ACTION_LABELS: Mapping[str, str] = MappingProxyType(
    {
        "ACT_MOVE_UP": "Move Up",
        "ACT_MOVE_DOWN": "Move Down",
        "ACT_MOVE_FORWARDS": "Move Forwards",
        "ACT_MOVE_BACKWARDS": "Move Backwards",
        "ACT_MOVE_LEFT": "Move Left",
        "ACT_MOVE_RIGHT": "Move Right",
        "ACT_BOX_CLICK": "Select Box",
        "ACT_BOX_CLICK_ADD": "Add Box",
        "ACT_CHANGE_MOUSE_MODE": "Rotate Camera",
        "ACT_INCR_SPEED": "Increase Speed (3D)",
        "ACT_DECR_SPEED": "Decrease Speed (3D)",
        "ACT_ZOOM_IN": "Zoom In (2D)",
        "ACT_ZOOM_OUT": "Zoom Out (2D)",
        "ACT_INCR_SELECT_DISTANCE": "Increase Selection Distance",
        "ACT_DECR_SELECT_DISTANCE": "Decrease Selection Distance",
        "ACT_DESELECT_ALL_BOXES": "Deselect All Boxes",
        "ACT_DESELECT_BOX": "Deselect Active Box",
        "ACT_INSPECT_BLOCK": "Inspect Block",
        "ACT_CHANGE_PROJECTION": "Toggle Projection",
    }
)


@dataclass(frozen=True)
class KeyGroups:
    """What one read of the editor's key configuration found.

    ``active`` is the group the editor is listening to, ``ids`` is every group
    the user can choose between, and ``bindings`` is the active group itself.
    Every field is empty when the configuration could not be read, which is how
    a caller tells "nothing is bound" from "nothing could be asked".
    """

    active: str = ""
    ids: Tuple[str, ...] = ()
    bindings: Mapping[str, Any] = field(default_factory=dict)

    @property
    def readable(self) -> bool:
        """Return whether this read answered with a group at all."""
        return bool(self.bindings)


#: The key-configuration module once it has been found, and whether the search
#: has run.  The presets are static data, so one lookup answers for the session.
_KEY_CONFIG: Any = None
_KEY_CONFIG_SEARCHED = False


def _key_config_by_path() -> Any:
    """Load the editor's key configuration without running its package init.

    ``amulet_map_editor.programs.edit.__init__`` reaches the whole 3D editor,
    which reaches the OpenGL renderer, which refuses to import until the Cython
    chunk mesher has been compiled.  So an ordinary ``import`` of the key
    configuration fails on a fresh checkout -- and it is not a module that needs
    any of that: it is a table of action names and key groups.

    Loading the file directly gets the table without the package around it.  The
    module is deliberately *not* registered in ``sys.modules`` under its real
    name: a second copy shadowing the real one would be a far worse problem than
    the one this solves.
    """
    import importlib.util
    from pathlib import Path

    try:
        import amulet_map_editor

        root = Path(amulet_map_editor.__file__).resolve().parent
    except Exception:  # pragma: no cover - the package is already imported
        return None
    path = root / "programs" / "edit" / "api" / "key_config.py"
    if not path.is_file():
        return None
    try:
        spec = importlib.util.spec_from_file_location(
            "amulet_map_editor._studio_key_config", str(path)
        )
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        log.debug("Could not read the key configuration directly", exc_info=True)
        return None
    return module


def key_config() -> Any:
    """Return the 3D editor's key configuration module, or ``None``.

    The ordinary import is tried first, so a normal build uses the module every
    other caller has.  Only when that fails is the file read directly, which is
    what keeps the Key Select window listing real keys on a checkout whose
    Cython extension has not been built yet.
    """
    global _KEY_CONFIG, _KEY_CONFIG_SEARCHED
    if _KEY_CONFIG_SEARCHED:
        return _KEY_CONFIG
    _KEY_CONFIG_SEARCHED = True
    try:
        from amulet_map_editor.programs.edit.api import key_config as module

        _KEY_CONFIG = module
        return _KEY_CONFIG
    except Exception:
        log.debug(
            "The 3D editor package would not import; reading its key "
            "configuration directly instead",
            exc_info=True,
        )
    _KEY_CONFIG = _key_config_by_path()
    if _KEY_CONFIG is None:
        log.warning(
            "The 3D editor key configuration could not be read at all; surfaces "
            "that print its keys will say so rather than show a default"
        )
    return _KEY_CONFIG


def read_key_groups() -> KeyGroups:
    """Return the editor's key groups, or an empty reading.

    The active group is read from the user's own profile first and only falls
    back to the shipped preset when the profile names a group that no longer
    exists.  Both lookup and read are guarded: the editor package is optional
    in a headless build, and a hand-edited profile must not take a window down.
    """
    editor = key_config()
    if editor is None:
        return KeyGroups()
    try:
        from amulet_map_editor.api import config

        DefaultKeybindGroupId = editor.DefaultKeybindGroupId
        PresetKeybinds = editor.PresetKeybinds
    except Exception:  # pragma: no cover - a truncated key configuration
        log.debug("The 3D editor key configuration is unusable", exc_info=True)
        return KeyGroups()
    try:
        edit_config = config.get("amulet_edit", {}) or {}
        group_id = str(edit_config.get("keybind_group", DefaultKeybindGroupId))
        user_groups = edit_config.get("user_keybinds", {}) or {}
        group = user_groups.get(group_id) or PresetKeybinds.get(group_id)
        if not group:
            group_id = str(DefaultKeybindGroupId)
            group = PresetKeybinds.get(DefaultKeybindGroupId, {})
        ids = tuple(PresetKeybinds) + tuple(
            name for name in user_groups if name not in PresetKeybinds
        )
        return KeyGroups(
            active=group_id if group else "",
            ids=ids,
            bindings=MappingProxyType(dict(group or {})),
        )
    except Exception:  # pragma: no cover - a hand-edited profile
        log.exception("Could not read the active 3D editor key group")
        return KeyGroups()


def active_keybinds() -> Mapping[str, Any]:
    """Return the 3D editor's live key group, or an empty mapping."""
    return read_key_groups().bindings


def declared_actions() -> Tuple[str, ...]:
    """Return every action the 3D editor declares, in the order it declares it.

    The order is the editor's, not this module's, so the Key Select window
    lists what the editor has rather than what somebody transcribed from it.
    """
    editor = key_config()
    if editor is None:
        return ()
    try:
        return tuple(str(action) for action in editor.KeybindKeys)
    except Exception:  # pragma: no cover - a malformed action list
        log.exception("Could not read the 3D editor action list")
        return ()


def format_binding(binding: Any) -> str:
    """Return one stored keybind as a person reads it, or ``""``.

    ``None`` and anything that is not a ``(modifiers, key)`` pair both answer
    with an empty string: a binding this build cannot make sense of is one it
    must not put on screen.
    """
    if binding is None:
        return ""
    try:
        modifiers, key = binding
    except (TypeError, ValueError):
        return ""
    try:
        parts = [KEY_NAMES.get(str(part), str(part)) for part in tuple(modifiers)]
    except TypeError:
        return ""
    parts.append(KEY_NAMES.get(str(key), str(key)))
    return "+".join(part for part in parts if part)


def viewport_accelerator(action: str) -> str:
    """Return the live binding for a 3D editor action such as ``ACT_MOVE_UP``.

    An unknown or unreadable action returns an empty string rather than the
    shipped default, because the shipped default is exactly what a user who
    rebound the action no longer presses.
    """
    return format_binding(active_keybinds().get(str(action)))


def action_label(action: str) -> str:
    """Return the row label for one action, falling back to its identifier."""
    text = str(action)
    known = EDITOR_ACTION_LABELS.get(text)
    if known:
        return known
    stripped = text[4:] if text.startswith("ACT_") else text
    words = [word.capitalize() for word in stripped.split("_") if word]
    return " ".join(words) or text


def editor_bindings() -> Tuple[KeyBinding, ...]:
    """Return every 3D editor action with the key it is really bound to.

    This is what the Key Select window shows.  The list is the editor's own
    action list in the editor's own order, each row resolved against the active
    key group, so a key printed here is a key that works -- by construction,
    rather than by somebody remembering to edit two files at once.  An action
    the active group binds nothing to reads :data:`NOT_BOUND`; a configuration
    that could not be read at all returns an empty tuple, and the surface shows
    :data:`UNREADABLE` and says why instead of drawing an empty grid.
    """
    groups = read_key_groups()
    if not groups.readable:
        return ()
    declared = declared_actions()
    ordered: list = [action for action in declared]
    known = set(declared)
    ordered.extend(sorted(action for action in groups.bindings if action not in known))
    if not ordered:
        ordered = sorted(groups.bindings)
    rows: Dict[str, str] = {}
    for action in ordered:
        rows[action] = format_binding(groups.bindings.get(action)) or NOT_BOUND
    return tuple(
        KeyBinding(action_label(action), binding) for action, binding in rows.items()
    )
