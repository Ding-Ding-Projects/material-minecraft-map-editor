import wx
from amulet_map_editor.api.wx.material3 import apply_material3
import wx.lib.scrolledpanel
from typing import List

import PyMCTranslate

from amulet_map_editor.api.studio import tokens
from amulet_map_editor.api.studio import widgets as studio
from amulet_map_editor.api.wx.ui.block_select import BlockDefine, EVT_PROPERTIES_CHANGE


class MultiBlockDefine(wx.lib.scrolledpanel.ScrolledPanel):
    def __init__(self, parent, translation_manager, style=0):
        super().__init__(parent, style=style)
        self.SetupScrolling()

        self._translation_manager = translation_manager

        self._sizer = wx.BoxSizer(wx.VERTICAL)

        self._add_button = studio.StudioButton(
            self,
            variant="icon",
            glyph="+",
            name="Add block definition",
            hint="Add another block definition",
        )
        self._sizer.Add(self._add_button, 0, wx.TOP | wx.LEFT | wx.RIGHT | wx.EXPAND, 5)

        self._block_picker_sizer = wx.BoxSizer(wx.VERTICAL)

        self._block_picker_sizer.Add(
            _CollapsibleBlockDefine(self, translation_manager), 0, wx.TOP | wx.EXPAND, 5
        )
        self._sizer.Add(
            self._block_picker_sizer, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 5
        )

        self.SetSizerAndFit(self._sizer)
        self.Layout()

        self._add_button.Bind(wx.EVT_BUTTON, self._add)
        self._fix_enabled_buttons()

    def _add(self, evt):
        self.Freeze()
        self.collapse()
        block_picker = _CollapsibleBlockDefine(self, self._translation_manager)
        self._block_picker_sizer.Add(block_picker, 1, wx.TOP | wx.EXPAND, 5)
        self._block_picker_sizer.Layout()
        self._sizer.Layout()
        self.Layout()
        self._fix_enabled_buttons()
        self.Refresh()
        self.Thaw()

    def move_up(self, obj):
        sizer = self._block_picker_sizer
        index = [child.Window for child in sizer.GetChildren()].index(obj)

        sizer.Detach(obj)
        sizer.Insert(index - 1 if index > 0 else 0, obj, 0, wx.TOP | wx.EXPAND, 5)
        self._fix_enabled_buttons()
        self.Layout()

    def move_down(self, obj):
        sizer = self._block_picker_sizer
        length = sizer.ItemCount
        index = [child.Window for child in sizer.GetChildren()].index(obj)

        sizer.Detach(obj)
        sizer.Insert(
            index + 1 if index < length - 1 else length - 1,
            obj,
            0,
            wx.TOP | wx.EXPAND,
            5,
        )
        self._fix_enabled_buttons()
        self.Layout()

    def delete(self, obj):
        obj.Hide()
        obj.Destroy()
        self._fix_enabled_buttons()
        self.Layout()

    def collapse(self):
        for child in self._block_picker_sizer.GetChildren():
            child.Window.collapsed = True

    def _fix_enabled_buttons(self):
        windows: List[_CollapsibleBlockDefine] = [
            child.Window for child in self._block_picker_sizer.GetChildren()
        ]
        for window in windows:
            window.up_button.Enable()
            window.down_button.Enable()
            window.delete_button.Enable()

        if len(windows) >= 1:
            windows[0].up_button.Disable()
            windows[-1].down_button.Disable()
        if len(windows) == 1:
            windows[0].delete_button.Disable()


class _CollapsibleBlockDefine(wx.Panel):
    def __init__(self, parent: MultiBlockDefine, translation_manager, collapsed=False):
        super().__init__(parent, style=wx.BORDER_SIMPLE)

        self._collapsed = collapsed

        sizer = wx.BoxSizer(wx.VERTICAL)
        self.SetSizer(sizer)

        header_sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(header_sizer, 0, wx.ALL, 5)

        # The four bitmap buttons this header used to draw -- expand, move up,
        # move down, delete -- are the same glyph-only icon buttons the rest
        # of this design system already reaches for in a compact row, using
        # the exact glyphs this project already uses for the same actions
        # elsewhere: "▾"/"▸" for expand/collapse (``CollapsibleSection``),
        # "+"/"−" for add/remove (the block property editor beside this one),
        # and "×" for a dismissing delete (the properties pane's own close
        # button).
        self.expand_button = studio.StudioButton(
            self,
            variant="icon",
            glyph="▸",
            name="Expand block definition",
            hint="Show or hide this block's fields",
        )
        header_sizer.Add(self.expand_button, 0, 5)

        self.up_button = studio.StudioButton(
            self,
            variant="icon",
            glyph="▲",
            name="Move block definition up",
            hint="Move this block definition up",
        )
        header_sizer.Add(self.up_button, 0, wx.LEFT, 5)
        self.up_button.Bind(wx.EVT_BUTTON, lambda evt: parent.move_up(self))

        self.down_button = studio.StudioButton(
            self,
            variant="icon",
            glyph="▼",
            name="Move block definition down",
            hint="Move this block definition down",
        )
        header_sizer.Add(self.down_button, 0, wx.LEFT, 5)
        self.down_button.Bind(wx.EVT_BUTTON, lambda evt: parent.move_down(self))

        self.delete_button = studio.StudioButton(
            self,
            variant="icon",
            glyph="×",
            name="Delete block definition",
            hint="Remove this block definition",
        )
        header_sizer.Add(self.delete_button, 0, wx.LEFT, 5)
        self.delete_button.Bind(wx.EVT_BUTTON, lambda evt: parent.delete(self))

        self.block_define = BlockDefine(self, translation_manager, wx.HORIZONTAL)
        sizer.Add(self.block_define, 1, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 5)
        self.collapsed = collapsed

        # The floating-width cap the native ``wx.StaticText`` used to get from
        # a fixed ``size=(500, -1)`` -- so a long block string still elides
        # rather than pushing the header wider than the list it sits in --
        # comes from ``wrap_width`` here: the label is not wrapped into extra
        # lines, only measured and painted no wider than the cap.
        self.block_label = studio.StudioText(
            self,
            self._gen_block_string(),
            size_px=13,
            role="on_surface",
            wrap_width=tokens.scaled(500),
            ellipsize=True,
            name="Block definition summary",
        )
        header_sizer.Add(self.block_label, 1, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, 5)

        self.expand_button.Bind(
            wx.EVT_BUTTON, lambda evt: self._toggle_block_expand(parent)
        )
        self.block_define.Bind(EVT_PROPERTIES_CHANGE, self._on_properties_change)

    @property
    def collapsed(self) -> bool:
        return self._collapsed

    @collapsed.setter
    def collapsed(self, collapsed: bool):
        self._collapsed = collapsed
        if self._collapsed:
            self.expand_button.glyph = "▸"
            self.expand_button.SetName("Expand block definition")
            self.block_define.Hide()
        else:
            self.expand_button.glyph = "▾"
            self.expand_button.SetName("Collapse block definition")
            self.block_define.Show()
        self.expand_button.Refresh()
        self.TopLevelParent.Layout()

    def _toggle_block_expand(self, parent: MultiBlockDefine):
        if self.collapsed:
            parent.collapse()
        self.collapsed = not self.collapsed

    def _on_properties_change(self, evt):
        self.block_label.SetLabel(self._gen_block_string())
        self.TopLevelParent.Layout()
        evt.Skip()

    def _gen_block_string(self):
        base = f"{self.block_define.namespace}:{self.block_define.block_name}"
        properties = ",".join(
            (
                f"{key}={value}"
                for key, value in self.block_define.str_properties.items()
            )
        )
        return f"{base}[{properties}]" if properties else base


if __name__ == "__main__":

    def main():
        app = wx.App()
        translation_manager = PyMCTranslate.new_translation_manager()
        dialog = wx.Dialog(None, style=wx.NO_BORDER | wx.RESIZE_BORDER)
        sizer = wx.BoxSizer()
        dialog.SetSizer(sizer)
        sizer.Add(MultiBlockDefine(dialog, translation_manager), 1, wx.EXPAND)
        dialog.Show()
        dialog.Fit()
        apply_material3(dialog)
        app.MainLoop()

    main()
