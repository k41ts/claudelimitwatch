"""Small text helpers shared by the CLI and the UI."""

from __future__ import annotations

from datetime import datetime, timezone

from .models import LimitBucket, UsageSnapshot


def human_duration(seconds: float | None, short: bool = True) -> str:
    """``4530`` -> ``1h 15m`` (short) or ``1 hour 15 min``."""
    if seconds is None:
        return "-"
    seconds = int(max(0, seconds))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h" if short else f"{days} days {hours} hours"
    if hours:
        return f"{hours}h {minutes}m" if short else f"{hours} hours {minutes} min"
    if minutes:
        return f"{minutes}m" if short else f"{minutes} min"
    return "<1m"


def local_time(moment: datetime | None) -> str:
    if moment is None:
        return "-"
    return moment.astimezone().strftime("%a %d %b %H:%M")


def reset_text(bucket: LimitBucket, now: datetime | None = None) -> str:
    left = bucket.resets_in(now)
    if left is None:
        return ""
    return f"resets in {human_duration(left)}"


def bucket_line(bucket: LimitBucket, now: datetime | None = None) -> str:
    reset = reset_text(bucket, now)
    suffix = f" - {reset}" if reset else ""
    return f"{bucket.label}: {bucket.remaining:.0f}% left ({bucket.percent:.0f}% used){suffix}"


def compact_line(snapshot: UsageSnapshot, now: datetime | None = None) -> str:
    """One-line summary for the mini bar: session + weekly + next reset."""
    now = now or datetime.now(timezone.utc)
    session = snapshot.session
    weekly = snapshot.weekly
    parts: list[str] = []
    if session is not None:
        parts.append(f"5h {session.remaining:.0f}%")
    if weekly is not None:
        parts.append(f"7d {weekly.remaining:.0f}%")
    if not parts:
        for bucket in snapshot.buckets[:2]:
            parts.append(f"{bucket.label} {bucket.remaining:.0f}%")
    soonest = min(
        (b for b in snapshot.buckets if b.resets_in(now) is not None),
        key=lambda b: b.resets_in(now) or 0,
        default=None,
    )
    if soonest is not None:
        parts.append(f"reset {human_duration(soonest.resets_in(now))}")
    return " · ".join(parts) if parts else "no data"


def age_text(snapshot: UsageSnapshot, now: datetime | None = None) -> str:
    age = snapshot.age_seconds(now)
    if age < 90:
        return "just now"
    return f"{human_duration(age)} ago"
