"""The desktop built-in authenticator -- registration, codes, and the list.

This is a real destination, not just a factor for this app's own locks: the
user registers and reads live TOTP codes for whatever accounts they like.
Registration never touches the network -- the QR is drawn in-process by
:mod:`amulet_map_editor.api.authenticator`, which is the module doing the
real cryptography; this file only draws the surface around it.
"""

from __future__ import annotations

import logging
from typing import Optional

import wx

from amulet_map_editor.api import authenticator as auth
from amulet_map_editor.api.forge_accounts import (
    CredentialStoreUnavailable,
    credential_store,
)
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.wx.ui.colour_picker import Note, Surface
from amulet_map_editor.api.wx.ui.material_forms import MaterialTextField

log = logging.getLogger(__name__)

__all__ = ["AuthenticatorDialog", "RegisterEntryDialog", "open_authenticator"]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


class RegisterEntryDialog(wx.Dialog):
    """Pair a new TOTP secret: paste a URI, or fill the fields by hand.

    The QR is shown for whichever secret is currently staged (typed manually
    or carried by a pasted URI) so a phone can scan it either way, alongside
    the manual secret in copyable grouped base32.  The factor only arms once
    the user types one live code back -- a mistyped or mis-scanned secret
    then fails loudly here instead of locking someone out later.
    """

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title="Register an authenticator entry",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Register an authenticator entry",
        )
        self._opener = wx.Window.FindFocus()
        self.result: Optional[auth.Entry] = None
        self._secret = auth.generate_secret()
        self._algorithm = auth.DEFAULT_ALGORITHM
        self._digits = auth.DEFAULT_DIGITS
        self._period = auth.DEFAULT_PERIOD

        root = Surface(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        sizer.Add(
            Note(
                root,
                "Register an authenticator entry",
                role="on_surface",
                size_px=18,
            ),
            0,
            wx.ALL,
            tokens.scaled(16),
        )

        # -- paste an otpauth:// URI -----------------------------------
        sizer.Add(
            widgets.SectionLabel(root, "Paste a pairing link"),
            0,
            wx.LEFT | wx.RIGHT,
            tokens.scaled(16),
        )
        self.uri_field = MaterialTextField(
            root,
            "otpauth://totp/... (optional)",
            placeholder="otpauth://totp/Issuer:account?secret=...",
            name="Pairing URI",
            on_change=self._on_uri_change,
        )
        sizer.Add(self.uri_field, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        # -- or fill the fields by hand ----------------------------------
        sizer.Add(
            widgets.SectionLabel(root, "Or enter the fields manually"),
            0,
            wx.LEFT | wx.RIGHT,
            tokens.scaled(16),
        )
        self.issuer_field = MaterialTextField(
            root, "Issuer", name="Issuer", on_change=lambda _v: self._refresh_qr()
        )
        self.account_field = MaterialTextField(
            root,
            "Account",
            placeholder="you@example.com",
            name="Account",
            on_change=lambda _v: self._refresh_qr(),
        )
        self.secret_field = MaterialTextField(
            root,
            "Secret (base32)",
            value=self._secret,
            mono=True,
            name="Secret",
            on_change=self._on_secret_change,
        )
        fields = wx.BoxSizer(wx.HORIZONTAL)
        fields.Add(self.issuer_field, 1, wx.RIGHT, tokens.scaled(8))
        fields.Add(self.account_field, 1)
        sizer.Add(fields, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(16))
        sizer.Add(self.secret_field, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        # -- QR code, drawn locally --------------------------------------
        self.qr_bitmap = wx.StaticBitmap(root, size=wx.Size(*(tokens.scaled(220),) * 2))
        self.qr_bitmap.SetName("Scannable QR code for this pairing")
        self.qr_alt = Note(
            root,
            "",
            role="on_surface_variant",
            size_px=11,
        )
        qr_row = wx.BoxSizer(wx.HORIZONTAL)
        qr_row.Add(self.qr_bitmap, 0, wx.RIGHT, tokens.scaled(16))
        secret_col = wx.BoxSizer(wx.VERTICAL)
        secret_col.Add(
            Note(root, "Manual entry secret", role="on_surface_variant", size_px=11)
        )
        self.grouped_secret = Note(
            root, auth.group_base32(self._secret), role="on_surface", size_px=16
        )
        secret_col.Add(self.grouped_secret, 0, wx.TOP, tokens.scaled(4))
        self.params_note = Note(root, "", role="on_surface_variant", size_px=11)
        secret_col.Add(self.params_note, 0, wx.TOP, tokens.scaled(8))
        qr_row.Add(secret_col, 1, wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(qr_row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        sizer.Add(self.qr_alt, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16))

        # -- confirm with a live code -------------------------------------
        sizer.Add(
            widgets.SectionLabel(root, "Confirm with a current code"),
            0,
            wx.LEFT | wx.RIGHT,
            tokens.scaled(16),
        )
        self.confirm_field = MaterialTextField(
            root,
            "Current 6-8 digit code",
            name="Confirmation code",
            process_enter=True,
        )
        self.confirm_field.text.Bind(
            wx.EVT_TEXT_ENTER, lambda _e: self._on_confirm(None)
        )
        sizer.Add(
            self.confirm_field, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(16)
        )

        self.status = Note(root, "", role="error", size_px=12)
        sizer.Add(self.status, 0, wx.ALL, tokens.scaled(16))

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.AddStretchSpacer()
        self.cancel_button = widgets.StudioButton(
            root, "Cancel", variant="text", on_click=self._on_cancel, name="Cancel"
        )
        self.confirm_button = widgets.StudioButton(
            root,
            "Confirm and add",
            variant="filled",
            on_click=self._on_confirm,
            name="Confirm and add",
        )
        buttons.Add(self.cancel_button, 0, wx.RIGHT, tokens.scaled(8))
        buttons.Add(self.confirm_button, 0)
        sizer.Add(buttons, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        root.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize(wx.Size(tokens.scaled(520), tokens.scaled(560)))
        self.Fit()
        self.Bind(wx.EVT_CLOSE, self._on_cancel)
        self._refresh_qr()

    # -- staged registration fields ---------------------------------------
    def _staged(self) -> dict:
        uri = self.uri_field.GetValue().strip()
        if uri:
            try:
                return auth.parse_otpauth_uri(uri)
            except auth.AuthenticatorError:
                pass
        return {
            "issuer": self.issuer_field.GetValue().strip(),
            "account": self.account_field.GetValue().strip(),
            "secret": self.secret_field.GetValue().strip(),
            "algorithm": self._algorithm,
            "digits": self._digits,
            "period": self._period,
        }

    def _on_uri_change(self, value: str) -> None:
        value = (value or "").strip()
        if value:
            try:
                parsed = auth.parse_otpauth_uri(value)
            except auth.AuthenticatorError as error:
                self.status.set_text(str(error))
                self._refresh_qr()
                return
            self.issuer_field.SetValue(parsed["issuer"])
            self.account_field.SetValue(parsed["account"])
            self.secret_field.SetValue(parsed["secret"])
            self._algorithm = parsed["algorithm"]
            self._digits = parsed["digits"]
            self._period = parsed["period"]
            self.status.set_text("")
        self._refresh_qr()

    def _on_secret_change(self, _value: str) -> None:
        self._refresh_qr()

    def _refresh_qr(self) -> None:
        staged = self._staged()
        secret = staged.get("secret") or ""
        try:
            normalized = auth.normalize_base32(secret).rstrip("=") if secret else ""
        except auth.AuthenticatorError:
            normalized = ""
        self.grouped_secret.set_text(auth.group_base32(normalized or secret))
        issuer = staged.get("issuer") or "This app"
        account = staged.get("account") or "unnamed account"
        self.params_note.set_text(
            f"{staged.get('algorithm', auth.DEFAULT_ALGORITHM)} · "
            f"{staged.get('digits', auth.DEFAULT_DIGITS)} digits · "
            f"every {staged.get('period', auth.DEFAULT_PERIOD)}s"
        )
        if not normalized:
            self.qr_bitmap.SetBitmap(wx.Bitmap())
            self.qr_alt.set_text("No secret yet -- nothing to encode.")
            return
        uri = auth.build_otpauth_uri(
            issuer=issuer,
            account=account,
            secret=normalized,
            algorithm=staged.get("algorithm", auth.DEFAULT_ALGORITHM),
            digits=int(staged.get("digits", auth.DEFAULT_DIGITS)),
            period=int(staged.get("period", auth.DEFAULT_PERIOD)),
        )
        try:
            png = auth.qr_png_bytes_for_uri(uri, box_size=6)
            image = wx.Image(_bytes_to_stream(png), wx.BITMAP_TYPE_PNG)
            bitmap = wx.Bitmap(image)
            size = self.qr_bitmap.GetSize()
            if size.width > 0 and size.height > 0:
                image = bitmap.ConvertToImage().Scale(
                    size.width, size.height, wx.IMAGE_QUALITY_NEAREST
                )
                bitmap = wx.Bitmap(image)
            self.qr_bitmap.SetBitmap(bitmap)
        except Exception:  # pragma: no cover - defensive, no bitmap on failure
            log.exception("Could not render the pairing QR code")
        self.qr_alt.set_text(f"QR code pairing {issuer} · {account}. {uri}")

    def _on_confirm(self, _event) -> None:
        staged = self._staged()
        issuer = staged.get("issuer") or ""
        account = staged.get("account") or ""
        secret = staged.get("secret") or ""
        if not account:
            self.status.set_text("Enter an account name (or paste a pairing URI).")
            return
        try:
            normalized = auth.normalize_base32(secret)
        except auth.AuthenticatorError as error:
            self.status.set_text(str(error))
            return
        code = self.confirm_field.GetValue().strip()
        algorithm = staged.get("algorithm", auth.DEFAULT_ALGORITHM)
        digits = int(staged.get("digits", auth.DEFAULT_DIGITS))
        period = int(staged.get("period", auth.DEFAULT_PERIOD))
        if not auth.verify_code(
            normalized, code, digits=digits, algorithm=algorithm, period=period
        ):
            self.status.set_text(
                "That code did not match. Check the secret, the clock, and try again."
            )
            return
        try:
            self.result = auth.add_entry(
                issuer=issuer,
                account=account,
                secret=normalized,
                algorithm=algorithm,
                digits=digits,
                period=period,
            )
        except (auth.AuthenticatorError, CredentialStoreUnavailable) as error:
            self.status.set_text(str(error))
            return
        self._close()

    def _on_cancel(self, _event) -> None:
        self.result = None
        self._close()

    def _close(self) -> None:
        if self._opener:
            try:
                self._opener.SetFocus()
            except RuntimeError:
                pass
        self.EndModal(wx.ID_OK if self.result else wx.ID_CANCEL)


def _bytes_to_stream(data: bytes):
    import io

    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# the code list
# ---------------------------------------------------------------------------


class _EntryRow(wx.Panel):
    """One registered entry: label, live code, countdown, next-code peek."""

    def __init__(self, parent: wx.Window, entry: auth.Entry, *, on_delete) -> None:
        super().__init__(parent, style=wx.TAB_TRAVERSAL)
        self.entry = entry
        self.on_delete = on_delete
        self.SetBackgroundColour(tokens.palette().surface_container)

        sizer = wx.BoxSizer(wx.HORIZONTAL)
        labels = wx.BoxSizer(wx.VERTICAL)
        labels.Add(Note(self, entry.label(), role="on_surface", size_px=14))
        labels.Add(
            Note(
                self,
                f"{entry.algorithm} · {entry.digits} digits · {entry.period}s",
                role="on_surface_variant",
                size_px=10,
            ),
            0,
            wx.TOP,
            tokens.scaled(2),
        )
        sizer.Add(labels, 1, wx.ALIGN_CENTER_VERTICAL | wx.ALL, tokens.scaled(12))

        self.code_label = Note(self, "------", role="primary", size_px=24)
        self.code_label.SetName(f"Current code for {entry.label()}")
        sizer.Add(
            self.code_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(12)
        )

        self.countdown_label = Note(self, "--s", role="on_surface_variant", size_px=12)
        self.countdown_label.SetName(f"Time remaining for {entry.label()}'s code")
        sizer.Add(
            self.countdown_label,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(8),
        )

        self.next_label = Note(
            self, "next: ------", role="on_surface_variant", size_px=10
        )
        sizer.Add(
            self.next_label, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(8)
        )

        self.copy_button = widgets.StudioButton(
            self,
            "Copy",
            variant="tonal",
            on_click=self._copy,
            name=f"Copy the current code for {entry.label()}",
        )
        sizer.Add(
            self.copy_button, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, tokens.scaled(8)
        )

        self.delete_button = widgets.StudioButton(
            self,
            "Remove",
            variant="text",
            on_click=self._delete,
            name=f"Remove {entry.label()}",
        )
        sizer.Add(
            self.delete_button,
            0,
            wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
            tokens.scaled(12),
        )
        self.SetSizer(sizer)
        self.refresh()

    def refresh(self) -> None:
        try:
            code = auth.current_code(self.entry)
            peek = auth.next_code(self.entry)
            error = None
        except (auth.AuthenticatorError, CredentialStoreUnavailable) as err:
            code = "------"
            peek = "------"
            error = str(err)
        self.code_label.set_text(code)
        self.next_label.set_text(f"next: {peek}")
        remaining = auth.period_remaining(self.entry.period)
        self.countdown_label.set_text(f"{int(remaining)}s")
        if error:
            self.countdown_label.set_text("error")
            self.countdown_label.SetToolTip(error)

    def _copy(self, _event) -> None:
        if wx.TheClipboard.Open():
            wx.TheClipboard.SetData(wx.TextDataObject(self.code_label.text))
            wx.TheClipboard.Close()

    def _delete(self, _event) -> None:
        self.on_delete(self.entry)


class AuthenticatorDialog(wx.Dialog):
    """The full authenticator: entry list, live codes, add/remove."""

    def __init__(self, parent: wx.Window) -> None:
        super().__init__(
            parent,
            title="Authenticator",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name="Authenticator",
        )
        self.search = SearchState(label="Authenticator entries")
        self._rows: list = []

        root = Surface(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        header = wx.BoxSizer(wx.HORIZONTAL)
        header.Add(
            Note(root, "Authenticator", role="on_surface", size_px=18),
            1,
            wx.ALIGN_CENTER_VERTICAL,
        )
        self.add_button = widgets.StudioButton(
            root,
            "Register entry",
            variant="filled",
            on_click=self._on_add,
            name="Register a new authenticator entry",
        )
        header.Add(self.add_button, 0)
        sizer.Add(header, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        self.search_bar = widgets.SearchBar(
            root,
            "Search entries",
            self.search,
            on_change=lambda _s: self._refresh_list(),
        )
        sizer.Add(self.search_bar, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, tokens.scaled(16))

        store = credential_store()
        self.store_note = Note(
            root,
            f"Credential store: {store.name}. Secrets never leave it except to "
            "compute a code.",
            role="on_surface_variant" if store.available else "error",
            size_px=11,
        )
        sizer.Add(self.store_note, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        self.clock_warning = Note(root, "", role="error", size_px=11)
        sizer.Add(
            self.clock_warning,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        self.list_panel = wx.ScrolledWindow(root, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        self.list_panel.SetScrollRate(0, tokens.scaled(12))
        self.list_sizer = wx.BoxSizer(wx.VERTICAL)
        self.list_panel.SetSizer(self.list_sizer)
        sizer.Add(self.list_panel, 1, wx.EXPAND | wx.ALL, tokens.scaled(16))

        self.empty_note = Note(
            self.list_panel,
            "No entries yet. Register one to see live codes here.",
            role="on_surface_variant",
            size_px=12,
        )

        root.SetSizer(sizer)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize(wx.Size(tokens.scaled(640), tokens.scaled(480)))
        self.Fit()

        self._timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_tick, self._timer)
        self._timer.Start(1000)
        self.Bind(wx.EVT_CLOSE, self._on_close)

        self._refresh_list()

    def _matching_entries(self):
        entries = auth.list_entries()
        query = (self.search.query or "").strip()
        if not query:
            return entries
        try:
            import re as _re

            pattern = _re.compile(query, _re.IGNORECASE) if self.search.regex else None
        except Exception:
            pattern = None
        out = []
        for entry in entries:
            haystack = entry.label()
            if pattern is not None:
                if pattern.search(haystack):
                    out.append(entry)
            elif query.lower() in haystack.lower():
                out.append(entry)
        return out

    def _refresh_list(self) -> None:
        self.list_sizer.Clear(delete_windows=True)
        self._rows = []
        entries = self._matching_entries()
        if not entries:
            self.empty_note.Reparent(self.list_panel)
            self.list_sizer.Add(self.empty_note, 0, wx.ALL, tokens.scaled(8))
        else:
            for entry in entries:
                row = _EntryRow(self.list_panel, entry, on_delete=self._on_delete)
                self.list_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(8))
                self._rows.append(row)
        self.list_panel.Layout()
        self.list_panel.FitInside()

    def _on_tick(self, _event) -> None:
        for row in self._rows:
            row.refresh()

    def _on_add(self, _event) -> None:
        dialog = RegisterEntryDialog(self)
        dialog.ShowModal()
        dialog.Destroy()
        self._refresh_list()

    def _on_delete(self, entry: auth.Entry) -> None:
        auth.delete_entry(entry.id)
        self._refresh_list()

    def _on_close(self, _event) -> None:
        if self._timer.IsRunning():
            self._timer.Stop()
        self.Destroy()


def open_authenticator(parent: wx.Window) -> AuthenticatorDialog:
    """Open (or reuse) the authenticator dialog, non-modally."""
    dialog = AuthenticatorDialog(parent)
    dialog.Show()
    return dialog
