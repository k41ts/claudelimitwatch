"""Parsing for GET https://api.anthropic.com/api/oauth/usage.

The endpoint is the one the Claude Code /usage screen calls (verified against
CLI 2.1.234). It is internal, so every field here is treated as optional:
unknown keys are surfaced generically instead of raising.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..models import LimitBucket, SpendInfo, UsageSnapshot, severity_for

USAGE_PATH = "/api/oauth/usage"

#: Canonical labels for the ``kind`` values the server sends in ``limits[]``.
KIND_LABELS = {
    "session": "Session (5h)",
    "weekly_all": "Weekly (all models)",
    "weekly_opus": "Weekly - Opus",
    "weekly_sonnet": "Weekly - Sonnet",
    "weekly_oauth_apps": "Weekly - OAuth apps",
    "weekly_overage": "Weekly - extra usage",
    "weekly_cowork": "Weekly - Cowork",
    "overage": "Usage credits",
}

#: Legacy top-level keys -> canonical kind, used to fill gaps in ``limits[]``.
TOPLEVEL_KINDS = {
    "five_hour": "session",
    "seven_day": "weekly_all",
    "seven_day_opus": "weekly_opus",
    "seven_day_sonnet": "weekly_sonnet",
    "seven_day_oauth_apps": "weekly_oauth_apps",
    "seven_day_overage_included": "weekly_overage",
    "seven_day_cowork": "weekly_cowork",
}

#: Display order; anything unlisted sorts after these, alphabetically.
KIND_ORDER = [
    "session",
    "weekly_all",
    "weekly_opus",
    "weekly_sonnet",
    "weekly_overage",
    "weekly_cowork",
    "weekly_oauth_apps",
]


def _parse_ts(value: Any) -> datetime | None:
    """Accept ISO-8601 strings (with or without offset) and epoch seconds."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _parse_percent(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(100.0, float(value)))
    return None


def _prettify(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _label_for(kind: str, scope_model: str | None) -> str:
    if scope_model:
        return f"Weekly - {scope_model}"
    return KIND_LABELS.get(kind, _prettify(kind))


def _scope_model(scope: Any) -> str | None:
    if not isinstance(scope, dict):
        return None
    model = scope.get("model")
    if isinstance(model, dict):
        name = model.get("display_name")
        if isinstance(name, str) and name:
            return name
    return None


def _sort_key(bucket: LimitBucket) -> tuple[int, str]:
    base = bucket.key.split("@", 1)[0]
    try:
        return (KIND_ORDER.index(base), bucket.label)
    except ValueError:
        return (len(KIND_ORDER), bucket.label)


def _buckets_from_limits(payload: dict[str, Any]) -> list[LimitBucket]:
    entries = payload.get("limits")
    if not isinstance(entries, list):
        return []
    out: list[LimitBucket] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        kind = entry.get("kind")
        if not isinstance(kind, str) or not kind:
            continue
        percent = _parse_percent(entry.get("percent"))
        if percent is None:
            continue
        scope_model = _scope_model(entry.get("scope"))
        severity = entry.get("severity")
        group = entry.get("group")
        out.append(
            LimitBucket(
                key=f"{kind}@{scope_model}" if scope_model else kind,
                label=_label_for(kind, scope_model),
                percent=percent,
                resets_at=_parse_ts(entry.get("resets_at")),
                severity=severity if isinstance(severity, str) else severity_for(percent),
                is_active=bool(entry.get("is_active")),
                scope_model=scope_model,
                group=group if isinstance(group, str) else "",
            )
        )
    return out


def _buckets_from_toplevel(payload: dict[str, Any], seen: set[str]) -> list[LimitBucket]:
    """Fill in windows that ``limits[]`` did not report.

    Covers older and experimental keys (``tangelo``, ``nimbus_quill``, ...) too,
    so a new limit type shows up as a generic row rather than disappearing.
    """
    out: list[LimitBucket] = []
    for raw_key, value in payload.items():
        if raw_key in ("limits", "spend", "extra_usage") or not isinstance(value, dict):
            continue
        percent = _parse_percent(value.get("utilization"))
        if percent is None:
            continue
        kind = TOPLEVEL_KINDS.get(raw_key, raw_key)
        if kind in seen:
            continue
        # Experimental buckets the server ships disabled show up as a flat 0%
        # with no reset window; showing them would just be noise.
        if kind not in KIND_LABELS and percent == 0 and value.get("resets_at") is None:
            continue
        seen.add(kind)
        out.append(
            LimitBucket(
                key=kind,
                label=_label_for(kind, None),
                percent=percent,
                resets_at=_parse_ts(value.get("resets_at")),
                severity=severity_for(percent),
                is_active=False,
                group="weekly" if kind.startswith("weekly") else "",
            )
        )
    return out


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _parse_spend(payload: dict[str, Any]) -> SpendInfo | None:
    spend_raw = payload.get("spend")
    extra_raw = payload.get("extra_usage")
    if not isinstance(spend_raw, dict) and not isinstance(extra_raw, dict):
        return None
    spend = spend_raw if isinstance(spend_raw, dict) else {}
    extra = extra_raw if isinstance(extra_raw, dict) else {}

    used = spend.get("used") if isinstance(spend.get("used"), dict) else {}
    limit = spend.get("limit") if isinstance(spend.get("limit"), dict) else {}
    disabled_reason = spend.get("disabled_reason") or extra.get("disabled_reason")
    exponent = _int_or_none(used.get("exponent"))
    return SpendInfo(
        enabled=bool(spend.get("enabled") or extra.get("is_enabled")),
        percent=_parse_percent(spend.get("percent")),
        used_minor=_int_or_none(used.get("amount_minor")),
        limit_minor=_int_or_none(limit.get("amount_minor")),
        currency=used.get("currency") or extra.get("currency") or "USD",
        exponent=exponent if exponent is not None else 2,
        disabled_reason=disabled_reason if isinstance(disabled_reason, str) else None,
    )


def parse_usage(
    payload: Any,
    account_id: str,
    fetched_at: datetime | None = None,
    subscription_type: str | None = None,
) -> UsageSnapshot:
    """Turn a raw usage response into a :class:`UsageSnapshot`.

    Never raises on malformed input: an unusable payload comes back as a
    snapshot with ``error`` set, so the UI can show stale data instead of dying.
    """
    fetched_at = fetched_at or datetime.now(timezone.utc)
    if not isinstance(payload, dict):
        return UsageSnapshot(
            account_id=account_id,
            fetched_at=fetched_at,
            error="Unexpected response format (not an object)",
        )

    buckets = _buckets_from_limits(payload)
    seen = {b.key.split("@", 1)[0] for b in buckets}
    buckets.extend(_buckets_from_toplevel(payload, seen))
    buckets.sort(key=_sort_key)

    error = None
    if not buckets:
        api_error = payload.get("error")
        if isinstance(api_error, dict):
            error = str(api_error.get("message") or api_error.get("type") or "API error")
        else:
            error = "No limit data in response"

    return UsageSnapshot(
        account_id=account_id,
        fetched_at=fetched_at,
        buckets=tuple(buckets),
        spend=_parse_spend(payload),
        subscription_type=subscription_type,
        error=error,
        raw=payload,
    )
