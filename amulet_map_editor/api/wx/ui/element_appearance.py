"""Bounded per-element Material 3 appearance editor for native controls."""

from __future__ import annotations

import re

import wx

from amulet_map_editor.api import config, local_history
from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio.widgets import StudioCheckBox
from amulet_map_editor.api.wx.material3 import TOKENS
from amulet_map_editor.api.wx.ui.material_dialog import (
    DialogChrome,
    card,
    heading,
    studio,
)
from amulet_map_editor.api.wx.ui.material_forms import (
    MaterialChoice,
    MaterialColourField,
    MaterialSpin,
)

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


class _ColourOverride:
    """Pairs an "Override" toggle with the project's continuous colour picker.

    A native hex text box let a value be blank -- meaning "inherit the M3
    role colour" -- or any six-digit hex a person could type and mistype.
    :class:`~amulet_map_editor.api.wx.ui.material_forms.MaterialColourField`
    always shows a real colour, so blank needs its own control rather than an
    empty string threaded through it: this toggle is that control.  Turning it
    off is what "no override" now means, and disables the field beside it
    rather than hiding it, so its last colour is not lost by unchecking it by
    mistake.
    """

    def __init__(self, parent: wx.Window, *, label: str, value: str, name: str) -> None:
        self._label = str(label)
        self.toggle = studio(
            StudioCheckBox(
                parent,
                f"Override {self._label.lower()}",
                value=bool(value),
                name=f"Override {name}",
            )
        )
        # Opted out of the native styling pass: it is built inside a tinted
        # ``surface_container`` card, and that pass repaints every ``wx.Panel``
        # it walks to the plain ``surface`` role, which would leave this field
        # a shade lighter than the card drawn behind it.
        self.field = studio(
            MaterialColourField(
                parent,
                value or "#6750A4",
                name=name,
                subject="Element appearance",
            )
        )
        self.toggle.Bind(wx.EVT_CHECKBOX, lambda _event: self._sync())
        self._sync()

    def _sync(self) -> None:
        enabled = self.toggle.GetValue()
        self.field.Enable(enabled)
        self.field.button.SetToolTip(
            "Open the colour picker, its translator, and its contrast readout"
            if enabled
            else f"Turn on “Override {self._label.lower()}” to choose a colour; "
            "this element currently uses the Material role colour."
        )

    def add_to(self, sizer: wx.Sizer) -> None:
        sizer.Add(
            self.toggle,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(tokens.SPACE_SM),
        )
        sizer.Add(self.field, 0, wx.ALIGN_CENTER_VERTICAL)

    def GetValue(self) -> str:  # noqa: N802 - kept for parity with a text box
        if not self.toggle.GetValue():
            return ""
        colour = self.field.GetColour()
        return "#%02X%02X%02X" % (colour.Red(), colour.Green(), colour.Blue())


class ElementAppearanceDialog(wx.Dialog):
    """Modeless-friendly editor for the exact control that opened it."""

    def __init__(self, parent: wx.Window, control: wx.Window):
        super().__init__(
            parent,
            title="Edit appearance",
            size=wx.Size(tokens.scaled(560), tokens.scaled(660)),
            style=wx.NO_BORDER | wx.RESIZE_BORDER,
        )
        self.control = control
        values = load_overrides().get(element_key(control), DEFAULTS)

        self.chrome = DialogChrome(self, status_name="Element appearance status")
        self.chrome.add(
            heading(
                self.chrome.body,
                f"Edit appearance · {element_key(control)}",
                size_px=16,
                role="on_surface",
                name="Element appearance heading",
            ),
            0,
            wx.EXPAND,
        )
        self.chrome.gap()

        colours, colours_sizer = card(
            self.chrome.body,
            role="surface_container",
            orientation=wx.VERTICAL,
            name="Element colour overrides",
        )
        self.background = _ColourOverride(
            colours,
            label="Background",
            value=str(values.get("background", "")),
            name="Element background colour",
        )
        self.foreground = _ColourOverride(
            colours,
            label="Foreground",
            value=str(values.get("foreground", "")),
            name="Element foreground colour",
        )
        for label, override in (
            ("Background", self.background),
            ("Foreground", self.foreground),
        ):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                heading(colours, label, size_px=12, role="on_surface_variant"),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(tokens.SPACE_SM),
            )
            override.add_to(row)
            colours_sizer.Add(row, 0, wx.BOTTOM, tokens.scaled(tokens.SPACE_SM))
        self.chrome.add(colours, 0, wx.EXPAND)
        self.chrome.gap()

        typography, typography_sizer = card(
            self.chrome.body,
            role="surface_container",
            orientation=wx.VERTICAL,
            name="Element typography",
        )
        self.font_size = MaterialSpin(
            typography,
            min=0,
            max=72,
            initial=int(values.get("font_size", 0) or 0),
            name="Element font size",
        )
        # Opted out for the same reason as the colour field above: it is a
        # ``wx.Panel`` living on a tinted card, and the native pass repaints
        # every panel it walks to the plain ``surface`` role.
        self.weight = studio(
            MaterialChoice(
                typography,
                ["normal", "medium", "bold"],
                label="Font weight",
                name="Element font weight",
                value=values.get("weight", "normal"),
            )
        )
        self.letter_spacing = MaterialSpin(
            typography,
            min=-8,
            max=32,
            initial=int(values.get("letter_spacing", 0) or 0),
            name="Element letter spacing",
        )
        for label, typo_control in (
            ("Font size (0 = inherited)", self.font_size),
            ("Font weight", self.weight),
            ("Letter spacing (-8 to 32)", self.letter_spacing),
        ):
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                heading(typography, label, size_px=12, role="on_surface_variant"),
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(tokens.SPACE_SM),
            )
            row.Add(typo_control, 0, wx.ALIGN_CENTER_VERTICAL)
            typography_sizer.Add(row, 0, wx.BOTTOM, tokens.scaled(tokens.SPACE_SM))
        self.chrome.add(typography, 0, wx.EXPAND)
        self.chrome.gap()

        style_row = wx.BoxSizer(wx.HORIZONTAL)
        self.italic = studio(
            StudioCheckBox(
                self.chrome.body,
                "Italic",
                value=bool(values.get("italic", False)),
                name="Element italic",
            )
        )
        self.underline = studio(
            StudioCheckBox(
                self.chrome.body,
                "Underline",
                value=bool(values.get("underline", False)),
                name="Element underline",
            )
        )
        self.strikethrough = studio(
            StudioCheckBox(
                self.chrome.body,
                "Strikethrough",
                value=bool(values.get("strikethrough", False)),
                name="Element strikethrough",
            )
        )
        for check in (self.italic, self.underline, self.strikethrough):
            style_row.Add(
                check,
                0,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(tokens.SPACE_MD),
            )
        self.chrome.add(style_row, 0, wx.EXPAND)
        self.chrome.gap()

        note = heading(
            self.chrome.body,
            "Portable M3 roles are editable here. Italic, underline, and "
            "strikethrough apply live. Letter spacing is retained for backends "
            "that support it; this wx backend reports it as capability-limited. "
            "Unsupported Word-only axes are not silently saved.",
            size_px=12,
            role="on_surface_variant",
            name="Element appearance capability note",
        )
        note.set_available_width(tokens.scaled(480))
        self.chrome.add(note, 0, wx.EXPAND)

        self.reset_button = self.chrome.action(
            "Reset this element",
            variant="outlined",
            on_click=self._reset,
            name="Reset this element",
        )
        self.cancel_button = self.chrome.action(
            "Cancel", variant="text", on_click=self._cancel, name="Cancel"
        )
        self.save_button = self.chrome.action(
            "Save", variant="filled", on_click=self._save, name="Save appearance"
        )
        self.save_button.SetId(wx.ID_OK)
        self.cancel_button.SetId(wx.ID_CANCEL)
        self.SetAffirmativeId(wx.ID_OK)
        self.SetEscapeId(wx.ID_CANCEL)
        self.SetMinSize(wx.Size(tokens.scaled(440), tokens.scaled(560)))
        self.Layout()

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

    def _save(self) -> None:
        save_override(element_key(self.control), self._values())
        apply_override(self.control)
        self.EndModal(wx.ID_OK)

    def _cancel(self) -> None:
        self.EndModal(wx.ID_CANCEL)

    def _reset(self) -> None:
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
