from typing import Optional, Tuple
import wx

import weakref
import numpy
import math

from amulet_map_editor.api.opengl.camera import Camera
from amulet_map_editor.api.opengl.matrix import rotation_matrix_xy
from amulet_map_editor.api.studio.widgets import StudioButton
from amulet_map_editor.programs.edit.api.key_config import (
    KeybindGroup,
    ACT_MOVE_UP,
    ACT_MOVE_DOWN,
    ACT_MOVE_FORWARDS,
    ACT_MOVE_BACKWARDS,
    ACT_MOVE_LEFT,
    ACT_MOVE_RIGHT,
    ACT_BOX_CLICK,
)
from amulet_map_editor.api.wx.util.button_input import (
    ButtonInput,
    InputPressEvent,
    EVT_INPUT_PRESS,
    InputReleaseEvent,
    EVT_INPUT_RELEASE,
    InputHeldEvent,
    EVT_INPUT_HELD,
)

_MoveActions = {
    ACT_MOVE_UP,
    ACT_MOVE_DOWN,
    ACT_MOVE_FORWARDS,
    ACT_MOVE_BACKWARDS,
    ACT_MOVE_LEFT,
    ACT_MOVE_RIGHT,
}


class _NudgeBehaviour:
    """Catching the movement actions, independent of what draws the button.

    Split out from :class:`NudgeButton` so a panel that has been migrated to
    Material can have the same button without the native one changing at all.
    The behaviour is one implementation with two shells rather than two
    implementations: a nudge that worked in one panel and not the other would
    be the worst possible outcome of a restyle.
    """

    def _init_nudge(
        self, camera: Camera, keybinds: KeybindGroup, tooltip: str = ""
    ) -> None:
        if tooltip:
            self.SetToolTip(tooltip)
        self._camera = weakref.ref(camera)
        self._buttons = ButtonInput(self)
        self._buttons.register_actions(keybinds)
        # This is fine here because we are binding to a custom button not the
        # canvas.
        self._buttons.bind_events()
        self.Bind(EVT_INPUT_PRESS, self._on_down)
        self.Bind(EVT_INPUT_RELEASE, self._on_up)
        self.Bind(EVT_INPUT_HELD, self._on_held)
        self.Bind(wx.EVT_SET_FOCUS, self._on_focus)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_blur)
        self._listen = False
        self._focused = False
        self._timeout = 10

    @property
    def listening(self) -> bool:
        """Whether the movement keys currently nudge through this button.

        Two ways in.  Holding the box-click action on the button is the
        original one, and it needs a mouse: the default binding for that action
        is the left mouse button, so the "hold this and press W" route is not
        reachable from a keyboard at all.  Having keyboard focus is the second,
        and it is what makes every nudge this button offers -- all three axes,
        both directions -- doable without a pointer.  Tab to the button, press
        the movement keys.
        """
        return self._listen or self._focused

    def _on_focus(self, evt):
        self._focused = True
        evt.Skip()

    def _on_blur(self, evt):
        self._focused = False
        evt.Skip()

    @property
    def camera(self) -> Camera:
        return self._camera()

    def enable(self):
        self._buttons.enable()

    def disable(self):
        self._buttons.disable()

    def _on_down(self, evt: InputPressEvent):
        if evt.action_id == ACT_BOX_CLICK:
            self._listen = True
        elif evt.action_id in _MoveActions:
            self._timeout = 10

    def _on_up(self, evt: InputReleaseEvent):
        if evt.action_id == ACT_BOX_CLICK:
            self._listen = False

    def _on_held(self, evt: InputHeldEvent):
        if self.listening:
            if self._timeout == 0 or self._timeout == 10:
                x = y = z = 0
                if ACT_MOVE_LEFT in evt.action_ids:
                    x += 1
                if ACT_MOVE_RIGHT in evt.action_ids:
                    x -= 1
                if ACT_MOVE_UP in evt.action_ids:
                    y += 1
                if ACT_MOVE_DOWN in evt.action_ids:
                    y -= 1
                if ACT_MOVE_FORWARDS in evt.action_ids:
                    z += 1
                if ACT_MOVE_BACKWARDS in evt.action_ids:
                    z -= 1
                if any((x, y, z)):
                    self._move(self._rotate((x, y, z)))
            if self._timeout:
                self._timeout -= 1

    def _rotate(self, offset: Tuple[int, int, int]) -> Tuple[int, int, int]:
        x, y, z = offset
        ry = self.camera.rotation[0]
        x, y, z, _ = (
            numpy.round(
                numpy.matmul(
                    rotation_matrix_xy(0, -math.radians(round(ry / 90) * 90)),
                    (x, y, z, 0),
                )
            )
            .astype(int)
            .tolist()
        )
        return x, y, z

    def _move(self, offset: Tuple[int, int, int]):
        pass


class NudgeButton(wx.Button, _NudgeBehaviour):
    """A button that catches actions when pressed."""

    def __init__(
        self,
        parent: wx.Window,
        camera: Camera,
        keybinds: KeybindGroup,
        label: str,
        tooltip: str,
    ):
        wx.Button.__init__(self, parent, label=label, style=wx.WANTS_CHARS)
        self._init_nudge(camera, keybinds, tooltip)


class MaterialNudgeButton(StudioButton, _NudgeBehaviour):
    """The same nudge button, drawn as one of the shell's own buttons.

    ``ButtonInput`` binds its mouse and key handlers *after* the Studio button
    has bound its own, so wx runs ``ButtonInput`` first and the Studio button's
    press, hover and focus states still arrive behind it -- each of those
    handlers calls ``Skip``.  That ordering is the whole reason this can be a
    subclass rather than a re-implementation, and it is what the
    ``_NudgeBehaviour`` split above exists to keep true for both shells.
    """

    def __init__(
        self,
        parent: wx.Window,
        camera: Camera,
        keybinds: KeybindGroup,
        label: str,
        tooltip: str,
        *,
        variant: str = "outlined",
        height: Optional[int] = 34,
    ):
        StudioButton.__init__(
            self,
            parent,
            label,
            variant=variant,
            hint=tooltip,
            name=label,
            height=height,
        )
        self._init_nudge(camera, keybinds, tooltip)

    def activate(self) -> None:
        """Do nothing on a plain click.

        A nudge button is held rather than pressed: the movement it offers
        arrives through ``ButtonInput`` while the box-click action is down or
        while it has focus.  ``StudioButton`` would post an ``EVT_BUTTON`` here,
        and a button that announces a command it does not have is the kind of
        decorative control this interface is not allowed to ship.
        """
        return None
