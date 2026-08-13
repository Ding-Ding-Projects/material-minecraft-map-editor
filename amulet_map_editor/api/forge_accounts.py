"""Several forge accounts signed in at once, with every token in the OS vault.

Publishing a world, a script, or a report to a forge is an ordinary thing to
want to do from two accounts -- a personal one and one that belongs to an
organisation -- and an application that holds exactly one token forces the user
to sign out of one to use the other.  So this holds as many as they like.

Two rules shape the whole module and neither of them bends:

**A token never exists outside the operating system's credential store.**  Not
in the configuration record, not in a database column, not in an export, not in
a log line, not in a command argument, not in this module's return values.  The
record kept beside the vault holds only what a person could read over your
shoulder without harm: the host, the login, the display name, the scopes, and
when it was added.  :func:`export_accounts` returns exactly that record, and
:func:`audit_plaintext_tokens` exists so a verification run can prove it.

**Nobody is ever asked to paste a credential.**  Sign-in is the OAuth device
flow: the application asks the forge for a short-lived user code, shows it, and
polls while the user approves it in their own browser.  The user code is a
pairing string that is worthless without that approval, so showing it is safe;
the access token that comes back at the end is written straight into the vault
and is never returned to a caller, printed, or logged.

The active account is what keeps single-account callers working unchanged:
:func:`authorization_header` with no argument uses it, so code that never knew
about multiple accounts keeps working exactly as it did.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import wx

from amulet_map_editor.api import config, process
from amulet_map_editor.api.studio import tokens, widgets
from amulet_map_editor.api.studio.search import SearchState
from amulet_map_editor.api.wx.ui.colour_picker import Note, Surface

log = logging.getLogger(__name__)

__all__ = [
    "Account",
    "CredentialStoreUnavailable",
    "DeviceCode",
    "DevicePoll",
    "ForgeAccountError",
    "ForgeAccountsDialog",
    "SERVICE_PREFIX",
    "active_account",
    "audit_plaintext_tokens",
    "authorization_header",
    "begin_device_authorisation",
    "complete_device_authorisation",
    "credential_store",
    "export_accounts",
    "forget_account",
    "has_token",
    "list_accounts",
    "open_forge_accounts",
    "poll_device_authorisation",
    "record_account",
    "set_active_account",
    "with_token",
]

#: Bounded config record holding **metadata only**.  Every field in it is
#: something a screenshot may safely show.
ACCOUNTS_ID = "amulet_forge_accounts"
MAX_ACCOUNTS = 32
MAX_FIELD_LENGTH = 200

#: The credential-store key every token is filed under.  It is scoped to the
#: host and the login, so two accounts on the same forge, or the same login on
#: two forges, never share a slot -- which is what makes "signed in to several
#: at once" true rather than nearly true.
SERVICE_PREFIX = "AmuletMapEditor/forge"

#: How long a device-flow poll will keep asking before giving up regardless of
#: what the forge said, so a caller cannot be left waiting for ever.
MAX_POLL_SECONDS = 900

# The credential vault lives in amulet_map_editor.api.credential_vault, which
# imports no GUI toolkit. This module does -- it defines a wx.Dialog -- so any
# code that must run without wx (the authenticator, the per-surface locks, the
# sidecar that carries both into the Electron application) imports the vault
# directly and never reaches through here.
#
# Re-exported rather than moved silently: every existing caller of
# forge_accounts.credential_store keeps working.
from amulet_map_editor.api.credential_vault import (  # noqa: F401
    CredentialStoreUnavailable,
    ForgeAccountError,
    account_key,
    credential_store,
    _bounded,
    _Store,
)


@dataclass(frozen=True)
class Account:
    """One signed-in account.  **Every field here is safe to display.**

    There is deliberately no token field, and no field that could hold one: the
    class is the record that gets written to the configuration file and handed
    to exports, so the safest way to keep a token out of both is for there to
    be nowhere to put it.
    """

    host: str
    login: str
    display_name: str = ""
    scopes: Tuple[str, ...] = ()
    added_at: float = 0.0

    @property
    def key(self) -> str:
        """The credential-store key this account's token lives under."""
        return account_key(self.host, self.login)

    def label(self) -> str:
        """A one-line description for a list row."""
        name = self.display_name or self.login
        return f"{name} · {self.login} on {self.host}"


def _read_record() -> Dict[str, Any]:
    raw = config.get(ACCOUNTS_ID, {})
    return raw if isinstance(raw, dict) else {}


def _write_record(accounts: Sequence[Account], active: str) -> None:
    payload = {
        "accounts": [
            {
                "host": _bounded(item.host),
                "login": _bounded(item.login),
                "display_name": _bounded(item.display_name),
                "scopes": [_bounded(scope) for scope in item.scopes][:32],
                "added_at": float(item.added_at or 0.0),
            }
            for item in list(accounts)[:MAX_ACCOUNTS]
        ],
        "active": _bounded(active),
    }
    try:
        config.put(ACCOUNTS_ID, payload)
    except OSError as error:
        raise ForgeAccountError(
            f"The account list could not be written: {error}"
        ) from error


def list_accounts() -> Tuple[Account, ...]:
    """Return every signed-in account, in the order they were added."""
    record = _read_record()
    entries = record.get("accounts", ())
    if not isinstance(entries, (list, tuple)):
        return ()
    accounts: List[Account] = []
    for entry in list(entries)[:MAX_ACCOUNTS]:
        if not isinstance(entry, dict):
            continue
        host = _bounded(entry.get("host"))
        login = _bounded(entry.get("login"))
        if not host or not login:
            continue
        scopes = entry.get("scopes", ())
        accounts.append(
            Account(
                host,
                login,
                _bounded(entry.get("display_name")),
                tuple(
                    _bounded(scope)
                    for scope in (scopes if isinstance(scopes, (list, tuple)) else ())
                )[:32],
                float(entry.get("added_at", 0.0) or 0.0),
            )
        )
    return tuple(accounts)


def active_account() -> Optional[Account]:
    """Return the account single-account calls use, or ``None`` when there is none.

    When the stored active key names an account that no longer exists, the
    first signed-in account stands in rather than the application behaving as
    though nobody were signed in -- but the record is not rewritten behind the
    user's back, so nothing about their choice is lost if the account returns.
    """
    accounts = list_accounts()
    if not accounts:
        return None
    wanted = _bounded(_read_record().get("active"))
    for account in accounts:
        if account.key == wanted:
            return account
    return accounts[0]


def set_active_account(host: str, login: str) -> Account:
    """Make one signed-in account the one single-account calls use."""
    key = account_key(host, login)
    accounts = list_accounts()
    for account in accounts:
        if account.key == key:
            _write_record(accounts, key)
            return account
    raise ForgeAccountError(f"No account is signed in for {login} on {host}.")


def record_account(
    host: str,
    login: str,
    *,
    display_name: str = "",
    scopes: Sequence[str] = (),
    make_active: bool = True,
) -> Account:
    """Add or update an account's **metadata**, without touching any token.

    Sign-in calls this after the token has already gone into the vault, so the
    two halves stay separate: this function has no way to write a secret even
    if it were handed one.
    """
    account = Account(
        _bounded(host),
        _bounded(login),
        _bounded(display_name),
        tuple(_bounded(scope) for scope in scopes)[:32],
        time.time(),
    )
    if not account.host or not account.login:
        raise ForgeAccountError("An account needs both a host and a login.")
    existing = [item for item in list_accounts() if item.key != account.key]
    accounts = existing + [account]
    if len(accounts) > MAX_ACCOUNTS:
        raise ForgeAccountError(
            f"This application holds at most {MAX_ACCOUNTS} signed-in accounts."
        )
    active = account.key if make_active else _bounded(_read_record().get("active"))
    _write_record(accounts, active or account.key)
    return account


def forget_account(host: str, login: str) -> Tuple[Account, ...]:
    """Sign an account out: delete its token from the vault and drop its record.

    The token is deleted first.  If the order were reversed and the delete
    failed, the record would be gone and the secret would still be in the
    vault, unreferenced and unremovable by this application ever again.
    """
    key = account_key(host, login)
    store = credential_store()
    if store.available:
        try:
            store.delete(key)
        except ForgeAccountError:
            log.exception("The credential store would not delete %s", key)
            raise
    remaining = [item for item in list_accounts() if item.key != key]
    active = _bounded(_read_record().get("active"))
    if active == key:
        active = remaining[0].key if remaining else ""
    _write_record(remaining, active)
    return tuple(remaining)


def has_token(host: str, login: str) -> bool:
    """Return whether the vault holds a token for an account.

    It answers yes or no and nothing else.  There is no function anywhere in
    this module that returns a token's length, its prefix, or any other partial
    value, because each of those narrows an attack on it.
    """
    store = credential_store()
    if not store.available:
        return False
    try:
        return store.exists(account_key(host, login))
    except ForgeAccountError:
        return False


# ---------------------------------------------------------------------------
# using a token without ever handling one
# ---------------------------------------------------------------------------


def with_token(
    consumer: Callable[[str], Any],
    *,
    host: str = "",
    login: str = "",
) -> Any:
    """Call ``consumer`` with the account's token and return its result.

    The token is fetched, passed in, and dropped.  It is never returned to the
    caller of this function, so the value cannot end up in a variable somebody
    later logs, formats into a message, or writes to a file by accident.  With
    no host and login, the active account is used, which is what keeps
    single-account call sites working unchanged.
    """
    account = (
        Account(_bounded(host), _bounded(login)) if host and login else active_account()
    )
    if account is None:
        raise ForgeAccountError("No forge account is signed in.")
    store = credential_store()
    if not store.available:
        raise CredentialStoreUnavailable(store.explanation)
    secret = store.read(account.key)
    if not secret:
        raise ForgeAccountError(
            f"No token is stored for {account.login} on {account.host}. "
            "Sign in again to obtain one."
        )
    try:
        return consumer(secret)
    finally:
        del secret


def authorization_header(*, host: str = "", login: str = "") -> Dict[str, str]:
    """Return the ``Authorization`` header for an account.

    This is the one place a token reaches a value a caller holds, because a
    request has to carry it, and it is deliberately shaped as a header rather
    than a bare string: a header is something you attach to a request, not
    something that reads naturally in a log line or an error message.  Never
    print, store, or serialise the result.
    """
    return with_token(
        lambda secret: {"Authorization": f"Bearer {secret}"}, host=host, login=login
    )


# ---------------------------------------------------------------------------
# the device flow
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeviceCode:
    """What the forge returned when sign-in began.

    ``user_code`` is safe to display and must be displayed: it is a short-lived
    pairing string that does nothing at all without the account holder
    approving it in their own browser, so hiding it would only stop sign-in
    from working.  ``device_code`` is the half this application keeps.
    """

    host: str
    verification_uri: str
    user_code: str
    device_code: str
    interval: int = 5
    expires_in: int = 900

    def safe_summary(self) -> str:
        """A line safe to show, log, or screenshot: no device code in it."""
        return (
            f"Open {self.verification_uri} and enter {self.user_code}. "
            f"The code expires in about {max(1, self.expires_in // 60)} minute(s)."
        )


@dataclass(frozen=True)
class DevicePoll:
    """One poll's outcome.  ``token_stored`` never carries the token itself."""

    #: ``pending``, ``slow_down``, ``expired``, ``denied``, ``stored``, ``error``.
    status: str
    message: str
    interval: int = 5
    account: Optional[Account] = None


def _post_form(
    url: str, payload: Dict[str, str], *, timeout: float = 20.0
) -> Dict[str, Any]:
    """POST a form to an HTTPS endpoint and read a JSON reply."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ForgeAccountError("Sign-in only ever talks to an https endpoint.")
    if parsed.username or parsed.password:
        raise ForgeAccountError("A sign-in URL must not carry credentials.")
    data = urllib.parse.urlencode(payload).encode("ascii")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "AmuletMapEditor",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1 << 20)
    except urllib.error.HTTPError as error:
        try:
            raw = error.read(1 << 20)
        except OSError:
            raise ForgeAccountError(
                f"The forge refused the request with HTTP {error.code}."
            ) from error
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise ForgeAccountError(f"The forge could not be reached: {error}") from error
    try:
        parsed_body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise ForgeAccountError(
            "The forge's reply was not the JSON this flow expects."
        ) from error
    if not isinstance(parsed_body, dict):
        raise ForgeAccountError("The forge's reply was not the JSON this flow expects.")
    return parsed_body


def begin_device_authorisation(
    *,
    host: str,
    client_id: str,
    scopes: Sequence[str],
    device_endpoint: str = "",
) -> DeviceCode:
    """Ask the forge to start a device sign-in and return the code to show.

    Ask for every scope the work will need in one call, including any the
    account already granted: the flow issues a fresh token rather than adding
    to an old one, so a scope left out here is a scope silently dropped, and
    the user gets asked to approve a second time for no reason.
    """
    host = _bounded(host)
    endpoint = device_endpoint or f"https://{host}/login/device/code"
    body = _post_form(
        endpoint,
        {"client_id": _bounded(client_id), "scope": " ".join(str(s) for s in scopes)},
    )
    if "error" in body:
        raise ForgeAccountError(
            f"The forge would not start sign-in: {body.get('error_description') or body['error']}"
        )
    for required in ("device_code", "user_code", "verification_uri"):
        if not body.get(required):
            raise ForgeAccountError(
                f"The forge's reply is missing {required}, so sign-in cannot continue."
            )
    return DeviceCode(
        host,
        str(body["verification_uri"]),
        str(body["user_code"]),
        str(body["device_code"]),
        max(1, int(body.get("interval", 5) or 5)),
        max(60, int(body.get("expires_in", 900) or 900)),
    )


def poll_device_authorisation(
    code: DeviceCode,
    *,
    client_id: str,
    login: str = "",
    display_name: str = "",
    scopes: Sequence[str] = (),
    token_endpoint: str = "",
    make_active: bool = True,
) -> DevicePoll:
    """Ask once whether the user has approved, and store the token if they have.

    The token never leaves this function.  On success it goes straight into the
    credential store and what comes back is an :class:`Account` -- metadata
    only -- so no caller of this flow ever holds the secret, which means no
    caller can log it.
    """
    endpoint = token_endpoint or f"https://{code.host}/login/oauth/access_token"
    body = _post_form(
        endpoint,
        {
            "client_id": _bounded(client_id),
            "device_code": code.device_code,
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        },
    )
    error = str(body.get("error", ""))
    if error == "authorization_pending":
        return DevicePoll(
            "pending", "Waiting for approval in the browser.", code.interval
        )
    if error == "slow_down":
        interval = max(code.interval + 5, int(body.get("interval", code.interval + 5)))
        return DevicePoll("slow_down", "The forge asked for a slower poll.", interval)
    if error == "expired_token":
        return DevicePoll(
            "expired",
            "The code expired before it was approved. Start again.",
            code.interval,
        )
    if error == "access_denied":
        return DevicePoll(
            "denied", "Sign-in was declined in the browser.", code.interval
        )
    if error:
        return DevicePoll(
            "error",
            f"The forge reported: {body.get('error_description') or error}",
            code.interval,
        )

    secret = body.get("access_token")
    if not isinstance(secret, str) or not secret:
        return DevicePoll(
            "error", "The forge approved sign-in but returned no token.", code.interval
        )
    store = credential_store()
    if not store.available:
        # The token is dropped rather than written somewhere weaker.  Refusing
        # is the point: a fallback here would defeat the whole module.
        del secret
        return DevicePoll("error", store.explanation, code.interval)

    account_login = _bounded(login) or _bounded(display_name) or "signed-in account"
    try:
        store.write(account_key(code.host, account_login), secret)
    finally:
        del secret
    granted = tuple(scopes) or tuple(
        str(body.get("scope", "")).split() if body.get("scope") else ()
    )
    account = record_account(
        code.host,
        account_login,
        display_name=display_name,
        scopes=granted,
        make_active=make_active,
    )
    return DevicePoll(
        "stored", f"Signed in as {account.label()}.", code.interval, account
    )


def complete_device_authorisation(
    code: DeviceCode,
    *,
    client_id: str,
    login: str = "",
    display_name: str = "",
    scopes: Sequence[str] = (),
    token_endpoint: str = "",
    on_status: Optional[Callable[[DevicePoll], None]] = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
) -> DevicePoll:
    """Poll until the user approves, declines, or the code expires.

    Meant to be run off the interface thread -- it sleeps between polls -- with
    ``on_status`` reporting each turn so a window can keep saying what is
    happening rather than showing a spinner that is indistinguishable from a
    hang.
    """
    deadline = now() + min(MAX_POLL_SECONDS, code.expires_in)
    interval = code.interval
    while now() < deadline:
        result = poll_device_authorisation(
            code,
            client_id=client_id,
            login=login,
            display_name=display_name,
            scopes=scopes,
            token_endpoint=token_endpoint,
        )
        if on_status is not None:
            on_status(result)
        if result.status not in ("pending", "slow_down"):
            return result
        interval = max(1, result.interval)
        sleep(interval)
    return DevicePoll(
        "expired", "Sign-in was not approved before the code expired.", interval
    )


# ---------------------------------------------------------------------------
# proving the rule
# ---------------------------------------------------------------------------


def export_accounts() -> Dict[str, Any]:
    """Return everything this module would ever put in an export.

    Metadata only, by construction: :class:`Account` has no token field, so
    there is nothing here that could carry one even if a future edit were
    careless.
    """
    return {
        "store": credential_store().name,
        "active": (active_account().key if active_account() else ""),
        "accounts": [asdict(account) for account in list_accounts()],
    }


def audit_plaintext_tokens(candidates: Sequence[str]) -> Tuple[str, ...]:
    """Return which of ``candidates`` appear anywhere this application writes.

    A verification run passes the token values it knows about and gets back the
    ones it found.  An empty result is the proof that the rule at the top of
    this module held; a non-empty one names exactly which value leaked.

    It searches the **decoded** contents of every configuration record in the
    active profile, not only this module's own.  That distinction is the whole
    point: the records are gzipped pickles, so a raw byte search of the files
    would find nothing whether a token were in them or not, and would be a
    check that could never fail.  Decoding every record also covers the case
    that matters most -- a token that leaked into somebody else's record, where
    nobody would think to look.
    """
    haystacks = [json.dumps(_read_record(), sort_keys=True, default=str)]
    try:
        haystacks.append(json.dumps(export_accounts(), sort_keys=True, default=str))
    except ForgeAccountError:  # pragma: no cover - defensive
        pass
    directory = os.environ.get("CONFIG_DIR") or "."
    try:
        entries = sorted(os.listdir(directory))
    except OSError:  # pragma: no cover - a profile that has never been written
        entries = []
    for entry in entries:
        if not entry.endswith(".config"):
            continue
        try:
            haystacks.append(
                json.dumps(config.get(entry[: -len(".config")]), default=str)
            )
        except (OSError, ValueError, TypeError):  # pragma: no cover - defensive
            log.debug("Could not decode the config record %s", entry, exc_info=True)
    found: List[str] = []
    for candidate in candidates:
        text = str(candidate)
        if text and any(text in haystack for haystack in haystacks):
            found.append(text)
    return tuple(found)


# ---------------------------------------------------------------------------
# the window
# ---------------------------------------------------------------------------
#
# Everything below is the surface.  It constructs no window at import time, so
# the library above stays importable -- and auditable -- in a process with no
# display, which is exactly where a check on where tokens end up belongs.


class ForgeAccountsDialog(wx.Dialog):
    """Sign in, switch, refresh, and sign out, several accounts at a time.

    Shown non-modally.  Nothing in it ever asks for a password or a token: the
    only credential on screen is the device flow's user code, which is
    worthless without the account holder approving it in their own browser, and
    the window says so plainly beside it.
    """

    #: How the sign-in fields start.  They are prompts, not assumptions: the
    #: client id is left empty because inventing one would produce a sign-in
    #: that fails in a way nobody could diagnose.
    DEFAULT_HOST = "github.com"
    DEFAULT_SCOPES = "repo read:org"

    def __init__(
        self,
        parent: wx.Window,
        *,
        title: str = "Forge accounts",
        subject: str = "Accounts",
    ) -> None:
        super().__init__(
            parent,
            title=title,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
            name=f"{subject}: {title}",
        )
        self._opener = wx.Window.FindFocus()
        self._focus_returned = False
        self._alive = True
        self._code: Optional[DeviceCode] = None
        self._worker: Optional[threading.Thread] = None
        self._pending_signout: Optional[Account] = None
        self.search = SearchState(label="Signed-in accounts")
        self._theme_unsubscribe = tokens.register_theme_listener(self.refresh_theme)

        self.root = Surface(self)
        header = self._build_header()
        body = self._build_body()
        footer = self._build_footer()
        layout = wx.BoxSizer(wx.VERTICAL)
        layout.Add(header, 0, wx.EXPAND)
        layout.Add(body, 1, wx.EXPAND)
        layout.Add(footer, 0, wx.EXPAND)
        self.root.SetSizer(layout)
        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(self.root, 1, wx.EXPAND)
        self.SetSizer(outer)
        self.SetMinSize(wx.Size(tokens.scaled(680), tokens.scaled(620)))
        self.SetSize(wx.Size(tokens.scaled(740), tokens.scaled(780)))
        self.Bind(wx.EVT_CLOSE, self._on_close)
        self.Bind(wx.EVT_CHAR_HOOK, self._on_char_hook)
        self.refresh_accounts()

    # -- construction --------------------------------------------------------
    def _build_header(self) -> wx.Window:
        header = Surface(self.root, role="surface_container")
        self.eyebrow = Note(header, "Accounts", role="primary", size_px=11)
        self.title_label = Note(
            header,
            "Forge accounts",
            role="on_surface",
            size_px=22,
            name="Forge accounts",
        )
        self.search_bar = widgets.SearchBar(
            header,
            "Search signed-in accounts",
            self.search,
            on_change=lambda _state: self.refresh_accounts(),
            compact=True,
        )
        close = widgets.StudioButton(
            header,
            "✕",
            variant="icon",
            on_click=self.close,
            name="Close the accounts window",
            hint="Close the accounts window",
            height=30,
            min_width=34,
        )
        titles = wx.BoxSizer(wx.VERTICAL)
        titles.Add(self.eyebrow, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(4))
        titles.Add(self.title_label, 0, wx.EXPAND)
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(titles, 1, wx.ALIGN_CENTER_VERTICAL)
        row.Add(self.search_bar, 0, wx.ALIGN_CENTER_VERTICAL)
        row.Add(close, 0, wx.ALIGN_CENTER_VERTICAL | wx.LEFT, tokens.scaled(8))
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        header.SetSizer(padded)
        return header

    def _build_body(self) -> wx.Window:
        body = wx.ScrolledWindow(self.root, style=wx.VSCROLL | wx.TAB_TRAVERSAL)
        body.SetScrollRate(0, tokens.scaled(12))
        body.SetBackgroundColour(tokens.palette().surface)
        self.body = body
        sizer = wx.BoxSizer(wx.VERTICAL)

        store = credential_store()
        self.store_note = Note(
            body,
            f"Credential store: {store.name}. {store.explanation}",
            role="on_surface_variant" if store.available else "error",
            size_px=12,
        )
        sizer.Add(self.store_note, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))

        sizer.Add(
            widgets.SectionLabel(body, "Signed in"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.accounts_holder = Surface(body)
        self.accounts_sizer = wx.BoxSizer(wx.VERTICAL)
        self.accounts_holder.SetSizer(self.accounts_sizer)
        sizer.Add(
            self.accounts_holder,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.accounts_note = Note(body, "", size_px=12)
        sizer.Add(
            self.accounts_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )

        sizer.Add(
            widgets.SectionLabel(body, "Add an account"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        sizer.Add(
            Note(
                body,
                "Sign-in uses the device flow. This window will show you a short "
                "code to type into your own browser, and it will never ask you "
                "for a password or a token — if any window ever does, it is not "
                "this one.",
                size_px=11,
            ),
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.host_field = widgets.OutlinedField(
            body, "Forge host", self.DEFAULT_HOST, placeholder="github.com"
        )
        self.client_field = widgets.OutlinedField(
            body,
            "Client id",
            "",
            placeholder="The public OAuth client id of the app you are signing in with",
        )
        self.login_field = widgets.OutlinedField(
            body, "Account name", "", placeholder="How this account is listed here"
        )
        self.scopes_field = widgets.OutlinedField(
            body,
            "Scopes",
            self.DEFAULT_SCOPES,
            placeholder="Every scope the work needs, space separated",
        )
        for field_control in (
            self.host_field,
            self.client_field,
            self.login_field,
            self.scopes_field,
        ):
            sizer.Add(
                field_control,
                0,
                wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
                tokens.scaled(16),
            )
        self.start_button = widgets.StudioButton(
            body,
            "Start sign-in",
            variant="filled",
            on_click=self.start_sign_in,
            name="Start sign-in",
            hint="Ask the forge for a device code",
        )
        sizer.Add(
            self.start_button, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16)
        )

        self.code_note = Note(
            body, "", role="on_surface", size_px=26, name="Device code"
        )
        self.address_note = Note(body, "", size_px=13)
        self.status_note = Note(body, "", size_px=12)
        for note in (self.code_note, self.address_note, self.status_note):
            sizer.Add(
                note, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16)
            )
        copy_row = wx.BoxSizer(wx.HORIZONTAL)
        self.copy_code_button = widgets.StudioButton(
            body,
            "Copy the code",
            variant="outlined",
            on_click=lambda: self._copy(self._code.user_code if self._code else ""),
            name="Copy the device code",
        )
        self.copy_address_button = widgets.StudioButton(
            body,
            "Copy the address",
            variant="outlined",
            on_click=lambda: self._copy(
                self._code.verification_uri if self._code else ""
            ),
            name="Copy the verification address",
        )
        copy_row.Add(self.copy_code_button, 0, wx.RIGHT, tokens.scaled(8))
        copy_row.Add(self.copy_address_button, 0)
        sizer.Add(copy_row, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16))

        sizer.Add(
            widgets.SectionLabel(body, "Signing out"),
            0,
            wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.gate_note = Note(
            body,
            "Choose Sign out on an account above to arm this gate. Signing out "
            "deletes that account's token from the credential store, which cannot "
            "be undone from here — the account has to sign in again.",
            size_px=11,
        )
        sizer.Add(
            self.gate_note,
            0,
            wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM,
            tokens.scaled(16),
        )
        self.gate = widgets.KeyGate(
            body, on_authorize=self._authorise_signout, on_exit=self._cancel_signout
        )
        self.gate.Show(False)
        sizer.Add(
            self.gate, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, tokens.scaled(16)
        )

        body.SetSizer(sizer)
        return body

    def _build_footer(self) -> wx.Window:
        footer = Surface(self.root, role="surface_container")
        done = widgets.StudioButton(
            footer, "Done", variant="filled", on_click=self.close, name="Done"
        )
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.AddStretchSpacer(1)
        row.Add(done, 0)
        padded = wx.BoxSizer(wx.VERTICAL)
        padded.Add(row, 0, wx.EXPAND | wx.ALL, tokens.scaled(16))
        footer.SetSizer(padded)
        return footer

    # -- the account list ----------------------------------------------------
    def refresh_accounts(self) -> None:
        """Rebuild the list of signed-in accounts from the stored record."""
        if not self._alive:
            return
        self.accounts_sizer.Clear(True)
        accounts = list_accounts()
        active = active_account()
        shown = [item for item in accounts if self.search.matches(item.label())]
        for account in shown:
            is_active = active is not None and active.key == account.key
            row = wx.BoxSizer(wx.HORIZONTAL)
            row.Add(
                Note(
                    self.accounts_holder,
                    f"{account.label()}"
                    + (" · active" if is_active else "")
                    + (
                        " · token stored"
                        if has_token(account.host, account.login)
                        else " · no token stored; sign in again"
                    )
                    + (
                        f" · scopes: {' '.join(account.scopes)}"
                        if account.scopes
                        else " · no scopes recorded"
                    ),
                    role="on_surface" if is_active else "on_surface_variant",
                    size_px=12,
                ),
                1,
                wx.ALIGN_CENTER_VERTICAL | wx.RIGHT,
                tokens.scaled(8),
            )
            if not is_active:
                row.Add(
                    widgets.StudioButton(
                        self.accounts_holder,
                        "Make active",
                        variant="text",
                        on_click=lambda item=account: self._make_active(item),
                        name=f"Make {account.login} the active account",
                    ),
                    0,
                    wx.RIGHT,
                    tokens.scaled(6),
                )
            row.Add(
                widgets.StudioButton(
                    self.accounts_holder,
                    "Refresh sign-in",
                    variant="outlined",
                    on_click=lambda item=account: self._refresh_sign_in(item),
                    name=f"Refresh the sign-in for {account.login}",
                    hint="Run the device flow again to replace this account's token",
                ),
                0,
                wx.RIGHT,
                tokens.scaled(6),
            )
            row.Add(
                widgets.StudioButton(
                    self.accounts_holder,
                    "Sign out",
                    variant="danger",
                    on_click=lambda item=account: self._arm_signout(item),
                    name=f"Sign {account.login} out",
                ),
                0,
            )
            self.accounts_sizer.Add(row, 0, wx.EXPAND | wx.BOTTOM, tokens.scaled(8))
        if not accounts:
            self.accounts_note.set_text(
                "No forge account is signed in. Nothing has been stored, and "
                "nothing is being hidden — the list is genuinely empty."
            )
        elif not shown:
            self.accounts_note.set_text(
                f"None of the {len(accounts)} signed-in account(s) match "
                f"{self.search.query!r}."
            )
        else:
            self.accounts_note.set_text(
                f"{len(shown)} of {len(accounts)} signed-in account(s) shown. "
                "Single-account calls use the active one."
            )
        self.accounts_holder.Layout()
        self.body.Layout()
        self.body.FitInside()

    def _make_active(self, account: Account) -> None:
        try:
            set_active_account(account.host, account.login)
        except ForgeAccountError as error:
            self.status_note.set_text(str(error), role="error")
            return
        self.status_note.set_text(f"{account.label()} is now the active account.")
        self.refresh_accounts()

    # -- sign-in -------------------------------------------------------------
    def start_sign_in(self, account: Optional[Account] = None) -> None:
        """Ask the forge for a device code and begin polling for approval."""
        store = credential_store()
        if not store.available:
            self.status_note.set_text(
                f"Sign-in is unavailable: {store.explanation}", role="error"
            )
            return
        if self._worker is not None and self._worker.is_alive():
            self.status_note.set_text(
                "A sign-in is already running; wait for it to finish or expire."
            )
            return
        host = (account.host if account else self.host_field.value()).strip()
        login = (account.login if account else self.login_field.value()).strip()
        client_id = self.client_field.value().strip()
        scopes = tuple(self.scopes_field.value().split())
        if not host or not client_id:
            self.status_note.set_text(
                "A forge host and a client id are both needed before sign-in can "
                "start. Nothing was sent.",
                role="error",
            )
            return
        self.start_button.Enable(False)
        self.status_note.set_text(f"Asking {host} for a device code…")

        def work() -> None:
            # Every exit from this thread has to re-enable the button, or a
            # failure nobody predicted leaves the window permanently unable to
            # try again -- which reads as the application being broken rather
            # than the network being down.
            try:
                code = begin_device_authorisation(
                    host=host, client_id=client_id, scopes=scopes
                )
                wx.CallAfter(self._show_code, code)
                result = complete_device_authorisation(
                    code,
                    client_id=client_id,
                    login=login,
                    scopes=scopes,
                    on_status=lambda poll: wx.CallAfter(self._poll_reported, poll),
                )
            except ForgeAccountError as error:
                wx.CallAfter(self._sign_in_failed, str(error))
                return
            except Exception as error:  # pragma: no cover - defensive
                log.exception("The forge sign-in thread failed unexpectedly")
                wx.CallAfter(
                    self._sign_in_failed,
                    f"Sign-in stopped unexpectedly: {type(error).__name__}. "
                    "Nothing was stored.",
                )
                return
            wx.CallAfter(self._sign_in_finished, result)

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def _refresh_sign_in(self, account: Account) -> None:
        self.host_field.set_value(account.host)
        self.login_field.set_value(account.login)
        if account.scopes:
            self.scopes_field.set_value(" ".join(account.scopes))
        self.status_note.set_text(
            f"Refreshing {account.label()}. Ask for every scope this account needs, "
            "including the ones it already has: the flow issues a fresh token "
            "rather than adding to the old one."
        )
        self.start_sign_in(account)

    def _show_code(self, code: DeviceCode) -> None:
        if not self._alive:
            return
        self._code = code
        self.code_note.set_text(code.user_code)
        self.address_note.set_text(
            f"Open {code.verification_uri} in your browser and enter the code above. "
            "The code is a pairing string: it does nothing until you approve it while "
            "signed in to your own account."
        )
        self.status_note.set_text(code.safe_summary())
        self.body.Layout()

    def _poll_reported(self, poll: DevicePoll) -> None:
        if not self._alive or poll.status == "stored":
            return
        self.status_note.set_text(
            poll.message,
            role="error" if poll.status == "error" else "on_surface_variant",
        )

    def _sign_in_failed(self, message: str) -> None:
        if not self._alive:
            return
        self.start_button.Enable(True)
        self.status_note.set_text(message, role="error")

    def _sign_in_finished(self, poll: DevicePoll) -> None:
        if not self._alive:
            return
        self.start_button.Enable(True)
        self._code = None
        self.code_note.set_text("")
        self.address_note.set_text("")
        self.status_note.set_text(
            poll.message,
            role="on_surface_variant" if poll.status == "stored" else "error",
        )
        self.refresh_accounts()

    # -- sign-out ------------------------------------------------------------
    def _arm_signout(self, account: Account) -> None:
        self._pending_signout = account
        self.gate.Show(True)
        self.gate_note.set_text(
            f"Signing out {account.label()} deletes its token from "
            f"{credential_store().name}. Hold both keys and slide to authorise, or "
            "take the emergency exit to leave everything as it is."
        )
        self.body.Layout()
        self.body.FitInside()
        self.gate.SetFocus()

    def _cancel_signout(self) -> None:
        self._pending_signout = None
        self.gate.Show(False)
        self.gate_note.set_text("Sign-out cancelled. Nothing was deleted.")
        self.body.Layout()
        self.body.FitInside()

    def _authorise_signout(self) -> None:
        account = self._pending_signout
        self._pending_signout = None
        self.gate.Show(False)
        if account is None:
            return
        try:
            forget_account(account.host, account.login)
        except ForgeAccountError as error:
            self.status_note.set_text(str(error), role="error")
            return
        self.status_note.set_text(
            f"{account.label()} was signed out and its token deleted from "
            f"{credential_store().name}."
        )
        self.refresh_accounts()

    # -- odds and ends -------------------------------------------------------
    def _copy(self, text: str) -> None:
        if not text:
            self.status_note.set_text(
                "There is nothing to copy yet: start a sign-in first.", role="error"
            )
            return
        if not wx.TheClipboard.Open():
            self.status_note.set_text(
                "The clipboard could not be opened, so nothing was copied.",
                role="error",
            )
            return
        try:
            wx.TheClipboard.SetData(wx.TextDataObject(text))
            wx.TheClipboard.Flush()
        finally:
            wx.TheClipboard.Close()
        self.status_note.set_text("Copied.")

    def refresh_theme(self) -> None:
        try:
            if self.IsBeingDeleted():
                return
            self.root.refresh_theme()
            self.body.SetBackgroundColour(tokens.palette().surface)
            for child in self.body.GetChildren():
                refresh = getattr(child, "refresh_theme", None)
                if callable(refresh):
                    refresh()
            self.Refresh()
        except RuntimeError:  # pragma: no cover - window already gone
            self._theme_unsubscribe = None

    def close(self) -> None:
        self.Close()

    def _on_char_hook(self, event: wx.KeyEvent) -> None:
        if event.GetKeyCode() == wx.WXK_ESCAPE:
            self.close()
            return
        event.Skip()

    def _return_focus(self) -> None:
        if self._focus_returned:
            return
        self._focus_returned = True
        opener = self._opener
        if opener is None:
            return
        try:
            if opener and not opener.IsBeingDeleted():
                opener.SetFocus()
        except RuntimeError:  # pragma: no cover - the opener has gone
            pass

    def _on_close(self, event: wx.CloseEvent) -> None:
        # The polling thread outlives the window by design -- it is a network
        # wait, not something to interrupt half-way -- so the flag is what
        # stops its callbacks touching a destroyed window.
        self._alive = False
        if self._theme_unsubscribe is not None:
            self._theme_unsubscribe()
            self._theme_unsubscribe = None
        self._return_focus()
        event.Skip()
        self.Destroy()


def open_forge_accounts(
    parent: "wx.Window",
    *,
    title: str = "Forge accounts",
    subject: str = "Accounts",
) -> ForgeAccountsDialog:
    """Open the accounts window beside ``parent`` and return it.

    This is the entry point an application surface calls.  It is non-blocking:
    signing in is a network wait measured in minutes, and a modal window would
    stop everything else for the whole of it.
    """
    dialog = ForgeAccountsDialog(parent, title=title, subject=subject)
    dialog.CentreOnParent()
    dialog.Show()
    return dialog
