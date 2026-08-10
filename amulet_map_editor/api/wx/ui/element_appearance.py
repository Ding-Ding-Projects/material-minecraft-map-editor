"""Bounded per-element Material 3 appearance editor for native controls."""

from __future__ import annotations

from dataclasses import asdict
import re

import wx

from amulet_map_editor.api import config, local_history
from amulet_map_editor.api.wx.material3 import TOKENS

APPEARANCE_ID = "amulet_element_appearance"
MAX_KEY_LENGTH = 160
MAX_ENTRIES = 512
DEFAULTS = {
    "background": "",
    "foreground": "",
    "font_size": 0,
    "weight": "normal",
    "italic": False,
    "underline": False,
    "strikethrough": False,
    "letter_spacing": 0,
}


def element_key(control: wx.Window) -> str:
    """Return a bounded stable role key, never a process-local object id."""

    name = control.GetName() or control.__class__.__name__
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name)).strip("_")
    return (name or control.__class__.__name__)[:MAX_KEY_LENGTH]


def _normalise_colour(value: str) -> str:
    if not isinstance(value, str) or not value:
        return ""
    value = value.strip()
    return value if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else ""


def load_overrides() -> dict[str, dict[str, object]]:
    raw = config.get(APPEARANCE_ID, {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for key, value in list(raw.items())[:MAX_ENTRIES]:
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        try:
            font_size = max(0, min(72, int(value.get("font_size", 0) or 0)))
        except (TypeError, ValueError, OverflowError):
            font_size = 0
        result[key[:MAX_KEY_LENGTH]] = {
            "background": _normalise_colour(value.get("background", "")),
            "foreground": _normalise_colour(value.get("foreground", "")),
            "font_size": font_size,
            "weight": (
                value.get("weight", "normal")
                if value.get("weight") in {"normal", "medium", "bold"}
                else "normal"
            ),
            "italic": bool(value.get("italic", False)),
            "underline": bool(value.get("underline", False)),
            "strikethrough": bool(value.get("strikethrough", False)),
            "letter_spacing": max(
                -8, min(32, int(value.get("letter_spacing", 0) or 0))
            ),
        }
    return result


def save_override(key: str, values: dict[str, object]) -> dict[str, dict[str, object]]:
    key = str(key)[:MAX_KEY_LENGTH]
    current = load_overrides()
    current[key] = {
        "background": _normalise_colour(str(values.get("background", ""))),
        "foreground": _normalise_colour(str(values.get("foreground", ""))),
        "font_size": max(0, min(72, int(values.get("font_size", 0) or 0))),
        "weight": (
            values.get("weight", "normal")
            if values.get("weight") in {"normal", "medium", "bold"}
            else "normal"
        ),
        "italic": bool(values.get("italic", False)),
        "underline": bool(values.get("underline", False)),
        "strikethrough": bool(values.get("strikethrough", False)),
        "letter_spacing": max(-8, min(32, int(values.get("letter_spacing", 0) or 0))),
    }
    config.put(APPEARANCE_ID, dict(list(current.items())[-MAX_ENTRIES:]))
    local_history.safe_record("element-appearance", current, record_type="settings")
    return current


def reset_override(key: str) -> dict[str, dict[str, object]]:
    current = load_overrides()
    current.pop(key, None)
    config.put(APPEARANCE_ID, current)
    local_history.safe_record("element-appearance", current, record_type="settings")
    return current


def apply_override(control: wx.Window) -> None:
    override = load_overrides().get(element_key(control))
    if not override:
        return
    for field, setter in (
        ("background", control.SetBackgroundColour),
        ("foreground", control.SetForegroundColour),
    ):
        value = override.get(field)
        if value:
            setter(wx.Colour(value))
    size = int(override.get("font_size", 0) or 0)
    if size:
        font = wx.Font(control.GetFont())
        font.SetPointSize(size)
        font.SetWeight(
            {
                "normal": wx.FONTWEIGHT_NORMAL,
                "medium": wx.FONTWEIGHT_MEDIUM,
                "bold": wx.FONTWEIGHT_BOLD,
            }[override.get("weight", "normal")]
        )
        font.SetStyle(
            wx.FONTSTYLE_ITALIC if override.get("italic") else wx.FONTSTYLE_NORMAL
        )
        font.SetUnderlined(bool(override.get("underline")))
        if hasattr(font, "SetStrikethrough"):
            font.SetStrikethrough(bool(override.get("strikethrough")))
        control.SetFont(font)


class ElementAppearanceDialog(wx.Dialog):
    """Modeless-friendly editor for the exact control that opened it."""

    def __init__(self, parent: wx.Window, control: wx.Window):
        super().__init__(
            parent,
            title="Edit appearance",
            size=wx.Size(500, 460),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self.control = control
        values = load_overrides().get(element_key(control), DEFAULTS)
        root = wx.BoxSizer(wx.VERTICAL)
        title = wx.StaticText(self, label=f"Edit appearance · {element_key(control)}")
        title.SetName("Element appearance heading")
        root.Add(title, 0, wx.ALL | wx.EXPAND, 16)
        self.background = wx.TextCtrl(
            self, value=str(values.get("background", "")), name="Element background HEX"
        )
        self.background.SetHint("Background HEX, for example #6750A4")
        self.foreground = wx.TextCtrl(
            self, value=str(values.get("foreground", "")), name="Element foreground HEX"
        )
        self.foreground.SetHint("Foreground HEX, or leave blank for the M3 role")
        self.font_size = wx.SpinCtrl(
            self,
            min=0,
            max=72,
            initial=int(values.get("font_size", 0) or 0),
            name="Element font size",
        )
        self.weight = wx.Choice(
            self, choices=["normal", "medium", "bold"], name="Element font weight"
        )
        self.weight.SetSelection(
            ["normal", "medium", "bold"].index(values.get("weight", "normal"))
        )
        self.italic = wx.CheckBox(self, label="Italic", name="Element italic")
        self.italic.SetValue(bool(values.get("italic", False)))
        self.underline = wx.CheckBox(self, label="Underline", name="Element underline")
        self.underline.SetValue(bool(values.get("underline", False)))
        self.strikethrough = wx.CheckBox(
            self, label="Strikethrough", name="Element strikethrough"
        )
        self.strikethrough.SetValue(bool(values.get("strikethrough", False)))
        self.letter_spacing = wx.SpinCtrl(
            self,
            min=-8,
            max=32,
            initial=int(values.get("letter_spacing", 0) or 0),
            name="Element letter spacing",
        )
        for label, control in (
            ("Background", self.background),
            ("Foreground", self.foreground),
            ("Font size (0 = inherited)", self.font_size),
            ("Font weight", self.weight),
            ("Letter spacing (-8 to 32)", self.letter_spacing),
        ):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                wx.StaticText(self, label=label),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                12,
            )
            row.Add(control, 1, wx.EXPAND)
            root.Add(row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)
        style_row = wx.BoxSizer(wx.HORIZONTAL)
        for control in (self.italic, self.underline, self.strikethrough):
            style_row.Add(control, 0, wx.RIGHT, 12)
        root.Add(style_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 16)
        note = wx.StaticText(
            self,
            label="Portable M3 roles are editable here. Italic, underline, and strikethrough apply live. Letter spacing is retained for backends that support it; this wx backend reports it as capability-limited. Unsupported Word-only axes are not silently saved.",
        )
        note.SetName("Element appearance capability note")
        note.Wrap(430)
        root.Add(note, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)
        self.feedback = wx.StaticText(self, label="")
        root.Add(self.feedback, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)
        buttons = self.CreateButtonSizer(wx.OK | wx.CANCEL)
        reset = wx.Button(self, label="Reset this element")
        reset.Bind(wx.EVT_BUTTON, self._reset)
        button_row = wx.BoxSizer(wx.HORIZONTAL)
        button_row.Add(reset, 0, wx.RIGHT, 8)
        button_row.Add(buttons, 1, wx.ALIGN_RIGHT)
        root.Add(button_row, 0, wx.ALL | wx.EXPAND, 16)
        self.SetSizerAndFit(root)
        self.Bind(wx.EVT_BUTTON, self._save, id=wx.ID_OK)
        self.Bind(
            wx.EVT_BUTTON, lambda _event: self.EndModal(wx.ID_CANCEL), id=wx.ID_CANCEL
        )
        from amulet_map_editor.api.wx.material3 import apply_material3

        apply_material3(self)

    def _values(self) -> dict[str, object]:
        return {
            "background": self.background.GetValue(),
            "foreground": self.foreground.GetValue(),
            "font_size": self.font_size.GetValue(),
            "weight": self.weight.GetStringSelection(),
            "italic": self.italic.GetValue(),
            "underline": self.underline.GetValue(),
            "strikethrough": self.strikethrough.GetValue(),
            "letter_spacing": self.letter_spacing.GetValue(),
        }

    def _save(self, _event) -> None:
        values = self._values()
        if any(
            value and not re.fullmatch(r"#[0-9a-fA-F]{6}", value)
            for value in (values["background"], values["foreground"])
        ):
            self.feedback.SetLabel(
                "Use six-digit HEX colours such as #6750A4, or leave a field blank."
            )
            return
        save_override(element_key(self.control), values)
        apply_override(self.control)
        self.EndModal(wx.ID_OK)

    def _reset(self, _event) -> None:
        reset_override(element_key(self.control))
        self.control.SetBackgroundColour(TOKENS.surface)
        self.control.SetForegroundColour(TOKENS.on_surface)
        self.control.Refresh()
        self.EndModal(wx.ID_OK)


def open_element_appearance(control: wx.Window) -> None:
    dialog = ElementAppearanceDialog(control.GetTopLevelParent(), control)
    dialog.CentreOnParent()
    dialog.ShowModal()
    dialog.Destroy()


__all__ = [
    "ElementAppearanceDialog",
    "apply_override",
    "element_key",
    "open_element_appearance",
    "reset_override",
    "save_override",
]
