"""The desktop surfaces for :mod:`amulet_map_editor.api.item_locks`.

Everything here is deliberately small and deliberately silly.  **This is a
toy lock, not security** -- every prompt says so, and every prompt names the
real recovery route (deleting the application's local profile folder) rather
than pretending there is protection to fall back on.

Three surfaces live here:

* :func:`open_unlock_prompt` -- the anchored, non-modal prompt a locked item
  opens when it is activated.
* :func:`open_create_lock_prompt` -- the anchored prompt a context menu's
  "Lock…" row opens.
* :class:`ManageLocksDialog` -- the real, searchable, bulk-manageable list of
  every lock, reachable from Help/Preferences.

:func:`lock_menu_rows` is the one function a context menu actually calls: it
returns the "Lock…" / "Unlock" / "Remove lock…" rows for one target, already
wired to the popovers above, so a tab menu, a group menu, or an appearance
menu can each add three lines and be done.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import item_locks
from amulet_map_editor.api.forge_accounts import CredentialStoreUnavailable
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.studio.widgets import AnchoredPopup, StudioButton, StudioText
from amulet_map_editor.api.wx.ui.material_dialog import TextField

log = logging.getLogger(__name__)

#: wxPython 4.1 added a medium weight; an older build falls back to bold
#: rather than raising while a header is being drawn.
_MEDIUM = getattr(wx, "FONTWEIGHT_MEDIUM", wx.FONTWEIGHT_BOLD)

__all__ = [
    "ManageLocksDialog",
    "lock_menu_rows",
    "open_create_lock_prompt",
    "open_manage_locks",
    "open_unlock_prompt",
]

#: Shown on every prompt this module opens.  Stated once so the wording never
#: drifts between the create prompt, the unlock prompt, and the manage list.
_TOY_NOTICE = (
    "Just for fun: this is not security, encryption, or protection from "
    "anyone else with this computer."
)


def _recovery_line() -> str:
    return (
        "Forgot it? Delete the app's local profile folder to reset every "
        f"lock: {item_locks.profile_directory_hint()}"
    )


# ---------------------------------------------------------------------------
# the unlock prompt
# ---------------------------------------------------------------------------


class _UnlockPopup(AnchoredPopup):
    """The anchored prompt a locked item opens when it is activated."""

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        lock: item_locks.Lock,
        on_unlocked: Callable[[], None],
    ) -> None:
        super().__init__(parent, anchor, width=tokens.scaled(300), max_height=320)
        self.lock = lock
        self.on_unlocked = on_unlocked
        self.SetName(f"Unlock {lock.label}")
        header = wx.BoxSizer(wx.VERTICAL)
        header.Add(
            StudioText(
                self.header,
                f"“{lock.label}” is locked",
                size_px=14,
                weight=_MEDIUM,
                name="Unlock prompt title",
            ),
            0,
            wx.EXPAND,
        )
        self.header.SetSizer(header)

        body = self.content_sizer
        body.Add(
            StudioText(
                self.content,
                _TOY_NOTICE,
                size_px=11,
                name="Unlock prompt toy notice",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.SPACE_XS,
        )
        prompt = "Password" if lock.method == "password" else "6-digit code"
        self.field = TextField(
            self.content,
            placeholder=prompt,
            name=f"Unlock {lock.label} — {prompt.casefold()}",
            password=(lock.method == "password"),
        )
        body.Add(self.field, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        self.feedback = StudioText(
            self.content, "", size_px=11, name="Unlock prompt feedback"
        )
        body.Add(self.feedback, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        body.Add(
            StudioText(
                self.content,
                _recovery_line(),
                size_px=10,
                name="Unlock prompt recovery route",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.SPACE_XS,
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(
            StudioButton(
                self.content,
                "Unlock",
                variant="filled",
                on_click=self._submit,
                name="Unlock",
            ),
            0,
        )
        row.Add((tokens.SPACE_XS, 0))
        row.Add(
            StudioButton(
                self.content,
                "Emergency exit",
                variant="text",
                on_click=self._cancel,
                name="Emergency exit",
            ),
            0,
        )
        body.Add(row, 0, wx.TOP, tokens.SPACE_XS)
        self.field.text.SetWindowStyleFlag(
            self.field.text.GetWindowStyleFlag() | wx.TE_PROCESS_ENTER
        )
        self.field.text.Bind(wx.EVT_TEXT_ENTER, lambda _e: self._submit())
        self.layout()

    def _submit(self) -> None:
        answer = self.field.text.GetValue()
        try:
            ok = item_locks.attempt_unlock(self.lock.lock_id, answer)
        except CredentialStoreUnavailable as error:
            self.feedback.SetLabel(str(error))
            self.layout()
            return
        if ok:
            self.Dismiss()
            widgets.invoke(self.on_unlocked)
            return
        self.feedback.SetLabel(
            "That did not match. Recovery is deleting the profile folder above."
        )
        self.field.text.SetValue("")
        self.layout()

    def _cancel(self) -> None:
        self.Dismiss()


def open_unlock_prompt(
    parent: wx.Window,
    anchor: wx.Window,
    lock: item_locks.Lock,
    on_unlocked: Callable[[], None],
) -> None:
    """Open the anchored unlock prompt beside ``anchor`` for ``lock``."""
    popup = _UnlockPopup(parent, anchor, lock, on_unlocked)
    popup.popup()
    popup.field.text.SetFocus()


# ---------------------------------------------------------------------------
# the create-lock prompt
# ---------------------------------------------------------------------------


class _CreateLockPopup(AnchoredPopup):
    """The anchored prompt a "Lock…" menu row opens."""

    def __init__(
        self,
        parent: wx.Window,
        anchor: wx.Window,
        scope: item_locks.LockScope,
        target_id: str,
        label: str,
        on_created: Callable[[item_locks.Lock], None],
    ) -> None:
        super().__init__(parent, anchor, width=tokens.scaled(320), max_height=420)
        self.scope = scope
        self.target_id = target_id
        self.label_text = label
        self.on_created = on_created
        self.SetName(f"Lock {label}")
        header = wx.BoxSizer(wx.VERTICAL)
        header.Add(
            StudioText(
                self.header,
                f"Lock “{label}”",
                size_px=14,
                weight=_MEDIUM,
                name="Lock prompt title",
            ),
            0,
            wx.EXPAND,
        )
        self.header.SetSizer(header)

        body = self.content_sizer
        body.Add(
            StudioText(
                self.content, _TOY_NOTICE, size_px=11, name="Lock prompt toy notice"
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.SPACE_XS,
        )
        self.method = "password"
        methods = wx.BoxSizer(wx.HORIZONTAL)
        methods.Add(
            StudioButton(
                self.content,
                "Password",
                variant="tonal",
                on_click=lambda: self._choose_method("password"),
                name="Lock with a password",
            ),
            0,
        )
        methods.Add((tokens.SPACE_XS, 0))
        methods.Add(
            StudioButton(
                self.content,
                "TOTP code",
                variant="text",
                on_click=lambda: self._choose_method("totp"),
                name="Lock with a TOTP code",
            ),
            0,
        )
        body.Add(methods, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        self.field = TextField(
            self.content,
            placeholder="Password",
            name="New lock password",
            password=True,
        )
        body.Add(self.field, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        self.secret_hint = StudioText(
            self.content, "", size_px=10, name="Lock prompt TOTP secret"
        )
        body.Add(self.secret_hint, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        body.Add(
            StudioText(
                self.content,
                _recovery_line(),
                size_px=10,
                name="Lock prompt recovery route",
            ),
            0,
            wx.EXPAND | wx.BOTTOM,
            tokens.SPACE_XS,
        )
        self.feedback = StudioText(
            self.content, "", size_px=11, name="Lock prompt feedback"
        )
        body.Add(self.feedback, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
        body.Add(
            StudioButton(
                self.content,
                "Create lock",
                variant="filled",
                on_click=self._submit,
                name="Create lock",
            ),
            0,
            wx.TOP,
            tokens.SPACE_XS,
        )
        self._totp_secret = ""
        self.layout()

    def _choose_method(self, method: str) -> None:
        self.method = method
        if method == "totp":
            self._totp_secret = item_locks.generate_totp_secret()
            self.field.Hide()
            self.secret_hint.SetLabel(
                "Manual TOTP secret (add it to any authenticator): "
                f"{self._totp_secret}"
            )
        else:
            self._totp_secret = ""
            self.field.Show()
            self.field.SetToolTip("Password")
            self.secret_hint.SetLabel("")
        self.layout()

    def _submit(self) -> None:
        try:
            if self.method == "password":
                lock = item_locks.create_lock(
                    self.scope,
                    self.target_id,
                    self.label_text,
                    "password",
                    password=self.field.text.GetValue(),
                )
            else:
                lock = item_locks.create_lock(
                    self.scope,
                    self.target_id,
                    self.label_text,
                    "totp",
                    totp_secret=self._totp_secret,
                )
        except item_locks.LockError as error:
            self.feedback.SetLabel(str(error))
            self.layout()
            return
        except CredentialStoreUnavailable as error:
            self.feedback.SetLabel(str(error))
            self.layout()
            return
        self.Dismiss()
        widgets.invoke(lambda: self.on_created(lock))


def open_create_lock_prompt(
    parent: wx.Window,
    anchor: wx.Window,
    scope: item_locks.LockScope,
    target_id: str,
    label: str,
    on_created: Callable[[item_locks.Lock], None] = lambda lock: None,
) -> None:
    popup = _CreateLockPopup(parent, anchor, scope, target_id, label, on_created)
    popup.popup()


# ---------------------------------------------------------------------------
# menu rows -- what a tab / group / appearance context menu actually calls
# ---------------------------------------------------------------------------


def lock_menu_rows(
    parent: wx.Window,
    anchor: wx.Window,
    scope: item_locks.LockScope,
    target_id: str,
    label: str,
    *,
    on_change: Callable[[], None] = lambda: None,
) -> List[Tuple[str, Callable[[], None]]]:
    """Return the lock-related rows for one item's context menu.

    A context menu adds these three lines beside its other rows -- exactly the
    way ``material_tabs.py`` already adds ``"Edit tab appearance…"`` -- and the
    popovers above handle the rest.
    """
    existing = item_locks.locks_for_target(scope, target_id)
    rows: List[Tuple[str, Callable[[], None]]] = []
    if not existing:
        rows.append(
            (
                "Lock…",
                lambda: open_create_lock_prompt(
                    parent, anchor, scope, target_id, label, lambda _lock: on_change()
                ),
            )
        )
        return rows
    lock = existing[0]
    if item_locks.is_unlocked(lock.lock_id):
        rows.append(
            ("Lock again", lambda: (item_locks.relock(lock.lock_id), on_change()))
        )
    else:
        rows.append(
            ("Unlock…", lambda: open_unlock_prompt(parent, anchor, lock, on_change))
        )
    rows.append(
        ("Remove lock…", lambda: (item_locks.remove_lock(lock.lock_id), on_change()))
    )
    return rows


# ---------------------------------------------------------------------------
# the manage-locks dialog: the real, searchable, enumerable list
# ---------------------------------------------------------------------------


class ManageLocksDialog(wx.Dialog):
    """Every lock the app holds, in one searchable, bulk-manageable list."""

    def __init__(self, parent: Optional[wx.Window]) -> None:
        super().__init__(
            parent,
            title="Locks",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            size=(tokens.scaled(520), tokens.scaled(420)),
        )
        self.SetName("Locks")
        palette = tokens.palette()
        self.SetBackgroundColour(palette.surface)
        root = wx.BoxSizer(wx.VERTICAL)
        root.Add(
            StudioText(
                self,
                _TOY_NOTICE,
                size_px=11,
                name="Manage locks toy notice",
            ),
            0,
            wx.EXPAND | wx.ALL,
            tokens.SPACE_SM,
        )
        self.state = SearchState(label="locks")
        self.search = widgets.SearchBar(
            self,
            "Search locks",
            self.state,
            on_change=lambda _state: self._rebuild(),
        )
        root.Add(self.search, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.SPACE_SM)
        self.list_panel = wx.ScrolledWindow(self, style=wx.VSCROLL)
        self.list_panel.SetScrollRate(0, 10)
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_panel.SetSizer(self.list_sizer)
        root.Add(self.list_panel, 1, wx.EXPAND | wx.ALL, tokens.SPACE_SM)
        self.feedback = StudioText(self, "", size_px=11, name="Manage locks feedback")
        root.Add(
            self.feedback,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.SPACE_SM,
        )
        self._rows: List[wx.Window] = []
        self.SetSizer(root)
        self._rebuild()

    def _rebuild(self) -> None:
        for row in self._rows:
            row.Destroy()
        self._rows = []
        self.list_sizer.Clear(False)
        locks = item_locks.list_locks()
        labels = [f"{lock.label} ({lock.scope})" for lock in locks]
        try:
            surviving = set(self.state.filter(labels))
        except Exception:
            surviving = set()
        shown = 0
        for lock, text in zip(locks, labels):
            if text not in surviving:
                continue
            shown += 1
            row = wx.BoxSizer(wx.HORIZONTAL)
            container = wx.Panel(self.list_panel)
            container.SetSizer(row)
            row.Add(
                StudioText(
                    container,
                    f"{lock.label} — {lock.scope} — {lock.method}",
                    size_px=12,
                    name=f"Lock row {lock.label}",
                ),
                1,
                wx.ALIGN_CENTER_VERTICAL,
            )
            row.Add(
                StudioButton(
                    container,
                    "Remove",
                    variant="text",
                    on_click=self._remover(lock.lock_id),
                    name=f"Remove lock {lock.label}",
                ),
                0,
            )
            self.list_sizer.Add(container, 0, wx.EXPAND | wx.BOTTOM, tokens.SPACE_XS)
            self._rows.append(container)
        self.feedback.SetLabel(
            f"{shown} of {len(labels)} locks · {self.state.feedback()}"
        )
        self.list_panel.Layout()
        self.list_panel.FitInside()
        self.Layout()

    def _remover(self, lock_id: str) -> Callable[[], None]:
        def remove() -> None:
            item_locks.remove_lock(lock_id)
            self._rebuild()

        return remove


def open_manage_locks(parent: Optional[wx.Window]) -> ManageLocksDialog:
    dialog = ManageLocksDialog(parent)
    dialog.Show()
    return dialog
