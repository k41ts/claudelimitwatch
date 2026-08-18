"""Last-known snapshots and account identities.

Identities are cached because they come from /api/oauth/profile: without this,
a rate-limited start falls back to whatever ~/.claude.json says, which can name
a different account than the token actually belongs to.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from .api.usage import parse_usage
from .config import atomic_write, cache_path
from .models import UsageSnapshot

log = logging.getLogger(__name__)


def _read_file() -> dict:
    try:
        raw = json.loads(cache_path().read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    except OSError as exc:
        log.debug("Could not read cache: %s", exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    # Older builds stored snapshots at the top level.
    if "snapshots" not in raw and "accounts" not in raw:
        return {"snapshots": raw, "accounts": {}}
    return raw


def _write_file(payload: dict) -> None:
    try:
        atomic_write(cache_path(), json.dumps(payload))
    except OSError as exc:
        log.debug("Could not write cache: %s", exc)


def save_snapshots(snapshots: dict[str, UsageSnapshot]) -> None:
    payload = _read_file()
    payload["snapshots"] = {
        account_id: {
            "fetched_at": snapshot.fetched_at.isoformat(),
            "subscription_type": snapshot.subscription_type,
            "raw": snapshot.raw,
        }
        for account_id, snapshot in snapshots.items()
        if snapshot.ok and snapshot.raw is not None
    }
    _write_file(payload)


def save_identities(identities: dict[str, dict[str, str | None]]) -> None:
    payload = _read_file()
    payload["accounts"] = identities
    _write_file(payload)


def load_identities() -> dict[str, dict[str, str | None]]:
    accounts = _read_file().get("accounts")
    if not isinstance(accounts, dict):
        return {}
    return {
        account_id: entry
        for account_id, entry in accounts.items()
        if isinstance(entry, dict)
    }


def load_snapshots() -> dict[str, UsageSnapshot]:
    raw = _read_file().get("snapshots")
    if not isinstance(raw, dict):
        return {}

    out: dict[str, UsageSnapshot] = {}
    for account_id, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        try:
            fetched_at = datetime.fromisoformat(str(entry.get("fetched_at")))
        except ValueError:
            fetched_at = datetime.now(timezone.utc)
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        snapshot = parse_usage(
            entry.get("raw"),
            account_id=account_id,
            fetched_at=fetched_at,
            subscription_type=entry.get("subscription_type"),
        )
        if snapshot.ok:
            out[account_id] = snapshot
    return out
