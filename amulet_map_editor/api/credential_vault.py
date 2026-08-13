"""The operating-system credential vault, with no interface layer attached.

Split out of :mod:`amulet_map_editor.api.forge_accounts` because that module
imports ``wx`` at module scope to define its dialog, and the vault is needed by
code that must never import a GUI toolkit at all: the authenticator, the
per-surface locks, and the sidecar that carries both into the Electron
application.

That was not a theoretical boundary. The sidecar's security methods import the
authenticator, which imported the vault, which imported ``wx`` -- so the sidecar
acquired a wxPython dependency. In this checkout wx happens to be installed and
nothing failed; in the packaged application the sidecar runs whatever Python is
on the machine, and there the authenticator and the locks would simply have
stopped working, with an import error in a child process nobody was reading.

Nothing here draws anything. It stores secrets in the platform's own vault --
never in a settings file, an export, a log, or this repository.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from typing import Any, Optional

log = logging.getLogger(__name__)

SERVICE_PREFIX = "AmuletMapEditor/forge"
MAX_FIELD_LENGTH = 200


def _bounded(value: Any) -> str:
    text = "" if value is None else str(value)
    return text[:MAX_FIELD_LENGTH]


def account_key(host: str, login: str) -> str:
    return f"{SERVICE_PREFIX}/{_bounded(host)}/{_bounded(login)}"


class ForgeAccountError(RuntimeError):
    """Something went wrong that the person in front of the window can act on."""


class CredentialStoreUnavailable(ForgeAccountError):
    """This platform has no credential store this module is willing to use.

    Refusing is the correct outcome rather than a degraded one.  The obvious
    fallback -- writing the token to a file, or handing it to a command-line
    tool as an argument -- is precisely the thing this module exists to
    prevent, so a platform without a usable vault gets an honest refusal and an
    explanation instead of a quiet downgrade.
    """



class _Store:
    """The interface a credential store has to provide."""

    name = "none"
    available = False
    explanation = "No credential store has been resolved."

    def write(self, key: str, secret: str) -> None:
        raise CredentialStoreUnavailable(self.explanation)

    def read(self, key: str) -> Optional[str]:
        raise CredentialStoreUnavailable(self.explanation)

    def delete(self, key: str) -> None:
        raise CredentialStoreUnavailable(self.explanation)

    def exists(self, key: str) -> bool:
        try:
            return self.read(key) is not None
        except CredentialStoreUnavailable:
            return False


_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2
_ERROR_NOT_FOUND = 1168


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.c_uint32),
        ("Type", ctypes.c_uint32),
        ("TargetName", ctypes.c_wchar_p),
        ("Comment", ctypes.c_wchar_p),
        ("LastWritten", ctypes.c_uint64),
        ("CredentialBlobSize", ctypes.c_uint32),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_byte)),
        ("Persist", ctypes.c_uint32),
        ("AttributeCount", ctypes.c_uint32),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.c_wchar_p),
        ("UserName", ctypes.c_wchar_p),
    ]


class _WindowsStore(_Store):
    """Windows Credential Manager, reached directly through ``advapi32``.

    Directly rather than through a command-line tool on purpose: every
    command-line route to the vault takes the secret as an argument, and an
    argument is visible to every other process on the machine for as long as the
    command runs.  A ctypes call passes it in this process's own memory and
    nowhere else.
    """

    name = "Windows Credential Manager"

    def __init__(self) -> None:
        self._advapi = None
        self.available = False
        self.explanation = "Windows Credential Manager is not reachable."
        if os.name != "nt":
            self.explanation = "Not running on Windows."
            return
        try:
            self._advapi = ctypes.windll.advapi32
            self._advapi.CredWriteW.argtypes = [
                ctypes.POINTER(_Credential),
                ctypes.c_uint32,
            ]
            self._advapi.CredWriteW.restype = ctypes.c_bool
            self._advapi.CredReadW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.POINTER(_Credential)),
            ]
            self._advapi.CredReadW.restype = ctypes.c_bool
            self._advapi.CredDeleteW.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint32,
                ctypes.c_uint32,
            ]
            self._advapi.CredDeleteW.restype = ctypes.c_bool
            self._advapi.CredFree.argtypes = [ctypes.c_void_p]
            self.available = True
            self.explanation = (
                "Tokens are stored in the Windows Credential Manager under "
                f"{SERVICE_PREFIX}/<host>/<login>, encrypted for this user "
                "account by the operating system."
            )
        except (AttributeError, OSError):  # pragma: no cover - platform boundary
            log.exception("The Windows credential API could not be prepared")

    def write(self, key: str, secret: str) -> None:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        blob = secret.encode("utf-16-le")
        buffer = (ctypes.c_byte * len(blob)).from_buffer_copy(blob)
        credential = _Credential(
            Flags=0,
            Type=_CRED_TYPE_GENERIC,
            TargetName=key,
            Comment=None,
            LastWritten=0,
            CredentialBlobSize=len(blob),
            CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
            Persist=_CRED_PERSIST_LOCAL_MACHINE,
            AttributeCount=0,
            Attributes=None,
            TargetAlias=None,
            UserName=key,
        )
        if not self._advapi.CredWriteW(ctypes.byref(credential), 0):
            raise ForgeAccountError(
                "The Windows Credential Manager refused to store the token "
                f"(error {ctypes.GetLastError()})."
            )

    def read(self, key: str) -> Optional[str]:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        pointer = ctypes.POINTER(_Credential)()
        if not self._advapi.CredReadW(
            key, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)
        ):
            code = ctypes.GetLastError()
            if code == _ERROR_NOT_FOUND:
                return None
            raise ForgeAccountError(
                f"The Windows Credential Manager refused to read the token (error {code})."
            )
        try:
            record = pointer.contents
            size = int(record.CredentialBlobSize)
            if size <= 0:
                return None
            raw = ctypes.string_at(record.CredentialBlob, size)
            return raw.decode("utf-16-le")
        finally:
            self._advapi.CredFree(pointer)

    def delete(self, key: str) -> None:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        if not self._advapi.CredDeleteW(key, _CRED_TYPE_GENERIC, 0):
            code = ctypes.GetLastError()
            if code != _ERROR_NOT_FOUND:
                raise ForgeAccountError(
                    "The Windows Credential Manager refused to delete the token "
                    f"(error {code})."
                )


class _SecretToolStore(_Store):
    """Freedesktop Secret Service, through ``secret-tool``.

    ``secret-tool store`` reads the secret from standard input, which is the
    only command-line route to a vault that does not put the secret on a
    command line.  That is why it is the one used here and why no equivalent
    exists below for macOS.
    """

    name = "Freedesktop Secret Service"

    def __init__(self) -> None:
        self.available = False
        self.explanation = "secret-tool is not installed."
        if os.name == "nt" or sys.platform == "darwin":
            self.explanation = "Not a Freedesktop platform."
            return
        try:
            completed = process.run(
                ["secret-tool", "--version"], capture_output=True, text=True
            )
            self.available = completed.returncode == 0
        except OSError:
            self.available = False
        if self.available:
            self.explanation = (
                "Tokens are stored in the Freedesktop Secret Service through "
                "secret-tool, which reads each secret from standard input so it "
                "never appears on a command line."
            )

    def write(self, key: str, secret: str) -> None:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        completed = process.run(
            ["secret-tool", "store", "--label", key, "amulet-forge", key],
            input=secret,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            raise ForgeAccountError("secret-tool refused to store the token.")

    def read(self, key: str) -> Optional[str]:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        completed = process.run(
            ["secret-tool", "lookup", "amulet-forge", key],
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            return None
        return completed.stdout or None

    def delete(self, key: str) -> None:
        if not self.available:
            raise CredentialStoreUnavailable(self.explanation)
        process.run(
            ["secret-tool", "clear", "amulet-forge", key],
            capture_output=True,
            text=True,
        )


class _RefusingStore(_Store):
    """The store used where no safe one exists, which refuses rather than degrades."""

    name = "none"

    def __init__(self, explanation: str) -> None:
        self.available = False
        self.explanation = explanation


_store: Optional[_Store] = None


def credential_store() -> _Store:
    """Return the credential store this platform provides, resolved once.

    macOS is deliberately refused.  ``security add-generic-password`` takes the
    secret as a command-line argument, which every other process on the machine
    can read while the command runs, and that is exactly the exposure this
    module exists to prevent.  Refusing and saying so is better than a store
    that looks like it works and leaks.
    """
    global _store
    if _store is not None:
        return _store
    if os.name == "nt":
        candidate: _Store = _WindowsStore()
    elif sys.platform == "darwin":  # pragma: no cover - platform boundary
        candidate = _RefusingStore(
            "No credential store is used on macOS: the security command takes "
            "the secret as a command-line argument, where other processes can "
            "read it. Sign-in is unavailable here until a direct Keychain "
            "binding is added."
        )
    else:  # pragma: no cover - platform boundary
        candidate = _SecretToolStore()
    if not candidate.available and not isinstance(candidate, _RefusingStore):
        candidate = _RefusingStore(candidate.explanation)
    _store = candidate
    return _store
