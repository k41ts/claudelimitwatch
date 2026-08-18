"""Store for accounts the watcher logged into itself.

These tokens are *not* the ones Claude Code uses -- they come from our own
login flow, so refreshing them cannot disturb the CLI session.

At rest:

* **Windows** -- sealed with DPAPI, scoped to the current user.
* **Linux** -- the session keyring through SecretStorage when it is available
  and unlocked, otherwise a 0600 file. That fallback is *not* encrypted; it is
  as protected as ``~/.claude/.credentials.json``, which Claude Code itself
  keeps in the clear. :func:`protection` reports which one is in effect so the
  UI and the docs never overstate it.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..config import accounts_path, atomic_write
from .oauth import TokenSet

log = logging.getLogger(__name__)

_IS_WINDOWS = sys.platform == "win32"

if _IS_WINDOWS:
    from ctypes import wintypes
else:  # pragma: no cover - ctypes.wintypes does not exist off Windows
    wintypes = None

#: Lazily resolved SecretStorage module; False means "not looked up yet".
_secretstorage: Any = False

KEYRING_LABEL = "climitwatch accounts"
KEYRING_ATTRS = {"application": "climitwatch", "kind": "accounts"}


def _load_secretstorage() -> Any:
    """Import SecretStorage on demand; it is an optional Linux extra."""
    global _secretstorage
    if _secretstorage is False:
        try:
            import secretstorage  # type: ignore
        except Exception as exc:  # pragma: no cover - depends on the host
            log.debug("SecretStorage unavailable (%s); using a 0600 file", exc)
            _secretstorage = None
        else:
            _secretstorage = secretstorage
    return _secretstorage


def _keyring_collection() -> Any:
    """The unlocked default keyring collection, or None."""
    module = _load_secretstorage()
    if module is None:
        return None
    try:
        connection = module.dbus_init()
        collection = module.get_default_collection(connection)
        return None if collection.is_locked() else collection
    except Exception as exc:  # pragma: no cover - depends on the host
        log.debug("Keyring unavailable (%s)", exc)
        return None


def keyring_read() -> bytes | None:
    collection = _keyring_collection()
    if collection is None:
        return None
    try:
        for item in collection.search_items(KEYRING_ATTRS):
            return bytes(item.get_secret())
    except Exception as exc:  # pragma: no cover - depends on the host
        log.debug("Keyring read failed (%s)", exc)
    return None


def keyring_write(payload: bytes) -> bool:
    collection = _keyring_collection()
    if collection is None:
        return False
    try:
        for item in collection.search_items(KEYRING_ATTRS):
            item.delete()
        collection.create_item(KEYRING_LABEL, KEYRING_ATTRS, payload)
    except Exception as exc:  # pragma: no cover - depends on the host
        log.debug("Keyring write failed (%s)", exc)
        return False
    return True


def protection() -> str:
    """How the store is protected here. Shown in docs and diagnostics."""
    if _IS_WINDOWS:
        return "DPAPI (current user)"
    if _keyring_collection() is not None:
        return "session keyring (SecretStorage)"
    return "file permissions only (0600)"


# --- DPAPI ------------------------------------------------------------------


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob(data: bytes) -> _DataBlob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _blob_bytes(blob: _DataBlob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _free(blob: _DataBlob) -> None:
    if blob.pbData:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def dpapi_protect(data: bytes) -> bytes:
    if not _IS_WINDOWS:
        return data
    out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(_blob(data)), "climitwatch", None, None, None, 0, ctypes.byref(out)
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return _blob_bytes(out)
    finally:
        _free(out)


def dpapi_unprotect(data: bytes) -> bytes:
    if not _IS_WINDOWS:
        return data
    out = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(_blob(data)), None, None, None, None, 0, ctypes.byref(out)
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return _blob_bytes(out)
    finally:
        _free(out)


# --- store ------------------------------------------------------------------


@dataclass
class StoredAccount:
    id: str
    label: str
    email: str | None = None
    plan: str | None = None
    access_token: str = ""
    refresh_token: str | None = None
    expires_at_ms: int = 0
    refresh_expires_at_ms: int | None = None
    scopes: list[str] | None = None
    enabled: bool = True
    needs_login: bool = False

    def tokens(self) -> TokenSet:
        return TokenSet(
            access_token=self.access_token,
            refresh_token=self.refresh_token,
            expires_at_ms=self.expires_at_ms,
            refresh_expires_at_ms=self.refresh_expires_at_ms,
            scopes=tuple(self.scopes or ()),
        )

    def apply(self, tokens: TokenSet) -> None:
        self.access_token = tokens.access_token
        self.refresh_token = tokens.refresh_token
        self.expires_at_ms = tokens.expires_at_ms
        self.refresh_expires_at_ms = tokens.refresh_expires_at_ms
        if tokens.scopes:
            self.scopes = list(tokens.scopes)


class AccountStore:
    """List of app-owned accounts, persisted encrypted."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or accounts_path()
        self.accounts: list[StoredAccount] = []
        self.load()

    def load(self) -> None:
        if not _IS_WINDOWS:
            blob = keyring_read()
            if blob is not None:
                self._decode(blob)
                return
        try:
            blob = self.path.read_bytes()
        except FileNotFoundError:
            self.accounts = []
            return
        except OSError as exc:
            log.warning("Cannot read account store: %s", exc)
            self.accounts = []
            return
        self._decode(blob)

    def _decode(self, blob: bytes) -> None:
        try:
            raw: Any = json.loads(dpapi_unprotect(blob).decode("utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as exc:
            log.warning("Account store unreadable (%s); starting empty", exc)
            self.accounts = []
            return
        entries = raw.get("accounts") if isinstance(raw, dict) else None
        known = set(StoredAccount.__dataclass_fields__)
        self.accounts = [
            StoredAccount(**{k: v for k, v in entry.items() if k in known})
            for entry in entries or []
            if isinstance(entry, dict) and entry.get("id")
        ]

    def save(self) -> None:
        payload = json.dumps({"version": 1, "accounts": [asdict(a) for a in self.accounts]})
        blob = dpapi_protect(payload.encode("utf-8"))
        if not _IS_WINDOWS and keyring_write(blob):
            # Never leave a plaintext copy behind once the keyring holds it.
            try:
                self.path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        os.replace(tmp, self.path)
        if not _IS_WINDOWS:
            os.chmod(self.path, 0o600)

    def add(self, tokens: TokenSet, label: str, email: str | None, plan: str | None) -> StoredAccount:
        existing = self.by_email(email) if email else None
        if existing is not None:
            existing.apply(tokens)
            existing.label = label or existing.label
            existing.plan = plan or existing.plan
            existing.needs_login = False
            self.save()
            return existing
        account = StoredAccount(
            id=str(uuid.uuid4()),
            label=label,
            email=email,
            plan=plan,
        )
        account.apply(tokens)
        self.accounts.append(account)
        self.save()
        return account

    def remove(self, account_id: str) -> None:
        self.accounts = [a for a in self.accounts if a.id != account_id]
        self.save()

    def by_id(self, account_id: str) -> StoredAccount | None:
        return next((a for a in self.accounts if a.id == account_id), None)

    def by_email(self, email: str) -> StoredAccount | None:
        return next((a for a in self.accounts if a.email and a.email.lower() == email.lower()), None)


def atomic_write_text(path: Path, text: str) -> None:
    """Re-exported for callers that keep plain-text sidecars next to the store."""
    atomic_write(path, text)
