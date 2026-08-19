"""Core data types shared by the API layer, the poller and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

SEVERITY_NORMAL = "normal"
SEVERITY_WARNING = "warning"
SEVERITY_DANGER = "danger"

#: Percent thresholds used when the server does not send a severity itself.
WARNING_AT = 80.0
DANGER_AT = 95.0


def severity_for(percent: float | None) -> str:
    if percent is None:
        return SEVERITY_NORMAL
    if percent >= DANGER_AT:
        return SEVERITY_DANGER
    if percent >= WARNING_AT:
        return SEVERITY_WARNING
    return SEVERITY_NORMAL


@dataclass(frozen=True)
class LimitBucket:
    """One rate-limit window (5h session, weekly, weekly-per-model, ...)."""

    key: str
    label: str
    percent: float
    resets_at: datetime | None = None
    severity: str = SEVERITY_NORMAL
    is_active: bool = False
    scope_model: str | None = None
    group: str = ""

    @property
    def remaining(self) -> float:
        return max(0.0, 100.0 - self.percent)

    def resets_in(self, now: datetime | None = None) -> float | None:
        """Seconds until this window resets, or None when unknown/past."""
        if self.resets_at is None:
            return None
        now = now or datetime.now(timezone.utc)
        return (self.resets_at - now).total_seconds()


@dataclass(frozen=True)
class SpendInfo:
    """Usage credits / spend on top of the plan limits."""

    enabled: bool = False
    percent: float | None = None
    used_minor: int | None = None
    limit_minor: int | None = None
    currency: str = "USD"
    exponent: int = 2
    disabled_reason: str | None = None

    def _fmt(self, minor: int | None) -> str | None:
        if minor is None:
            return None
        return f"{minor / (10 ** self.exponent):,.2f} {self.currency}"

    @property
    def used_text(self) -> str | None:
        return self._fmt(self.used_minor)

    @property
    def limit_text(self) -> str | None:
        return self._fmt(self.limit_minor)


@dataclass(frozen=True)
class UsageSnapshot:
    """Parsed result of one /api/oauth/usage call."""

    account_id: str
    fetched_at: datetime
    buckets: tuple[LimitBucket, ...] = ()
    spend: SpendInfo | None = None
    subscription_type: str | None = None
    error: str | None = None
    #: Short line safe to show in the overlay (the raw error goes to the log).
    error_short: str | None = None
    retry_after: float | None = None
    raw: dict[str, Any] | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.error is None

    def bucket(self, key: str) -> LimitBucket | None:
        for b in self.buckets:
            if b.key == key:
                return b
        return None

    @property
    def session(self) -> LimitBucket | None:
        return self.bucket("session")

    @property
    def weekly(self) -> LimitBucket | None:
        return self.bucket("weekly_all")

    @property
    def worst_severity(self) -> str:
        order = {SEVERITY_NORMAL: 0, SEVERITY_WARNING: 1, SEVERITY_DANGER: 2}
        worst = SEVERITY_NORMAL
        for b in self.buckets:
            if order.get(b.severity, 0) > order[worst]:
                worst = b.severity
        return worst

    def age_seconds(self, now: datetime | None = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.fetched_at).total_seconds()


@dataclass
class Account:
    """An account the watcher polls.

    ``source`` is either ``"claude-code"`` (tokens live in
    ~/.claude/.credentials.json and are shared with the CLI) or ``"app"``
    (the watcher logged in itself and owns the tokens).
    """

    id: str
    label: str
    source: str = "claude-code"
    email: str | None = None
    plan: str | None = None
    enabled: bool = True
    #: True only when the name came from /api/oauth/profile (or a cached
    #: result of one). ~/.claude.json is a guess: it can name a different
    #: account than the token in .credentials.json actually belongs to.
    identity_verified: bool = False

    @property
    def display(self) -> str:
        return self.label or self.email or self.id[:8]
