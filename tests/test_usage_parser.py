from datetime import datetime, timezone

import pytest

from climitwatch.api.usage import parse_usage
from climitwatch.models import SEVERITY_DANGER, SEVERITY_WARNING

NOW = datetime(2026, 8, 18, 15, 0, tzinfo=timezone.utc)

# Trimmed copy of a real response from CLI 2.1.234 (Pro account).
REAL = {
    "five_hour": {
        "utilization": 46.0,
        "resets_at": "2026-08-18T16:09:59.518853+00:00",
        "limit_dollars": None,
    },
    "seven_day": {"utilization": 48.0, "resets_at": "2026-08-21T19:59:59.518873+00:00"},
    "seven_day_oauth_apps": None,
    "seven_day_opus": None,
    "seven_day_sonnet": None,
    "nimbus_quill": {"utilization": 0.0, "resets_at": None},
    "extra_usage": {"is_enabled": False, "monthly_limit": None, "used_credits": None},
    "limits": [
        {
            "kind": "session",
            "group": "session",
            "percent": 46,
            "severity": "normal",
            "resets_at": "2026-08-18T16:09:59.518853+00:00",
            "scope": None,
            "is_active": False,
        },
        {
            "kind": "weekly_all",
            "group": "weekly",
            "percent": 48,
            "severity": "normal",
            "resets_at": "2026-08-21T19:59:59.518873+00:00",
            "scope": None,
            "is_active": True,
        },
    ],
    "spend": {
        "used": {"amount_minor": 0, "currency": "USD", "exponent": 2},
        "limit": None,
        "percent": 0,
        "enabled": False,
    },
}


def test_parses_real_response():
    snap = parse_usage(REAL, "acct", fetched_at=NOW)

    assert snap.ok
    assert [b.key for b in snap.buckets] == ["session", "weekly_all"]

    session = snap.session
    assert session is not None
    assert session.percent == 46
    assert session.remaining == 54
    assert session.label == "Session (5h)"
    assert session.resets_in(NOW) == pytest.approx(69 * 60 + 59.5, abs=1)

    weekly = snap.weekly
    assert weekly is not None and weekly.is_active
    assert snap.spend is not None and snap.spend.enabled is False


def test_disabled_experimental_bucket_is_hidden():
    snap = parse_usage(REAL, "acct", fetched_at=NOW)
    assert all(b.key != "nimbus_quill" for b in snap.buckets)


def test_active_experimental_bucket_is_shown_generically():
    payload = {**REAL, "tangelo": {"utilization": 12.0, "resets_at": "2026-08-19T00:00:00Z"}}
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    bucket = snap.bucket("tangelo")
    assert bucket is not None
    assert bucket.label == "Tangelo"
    assert bucket.percent == 12


def test_falls_back_to_toplevel_when_limits_missing():
    payload = {k: v for k, v in REAL.items() if k != "limits"}
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    assert snap.ok
    assert snap.session is not None and snap.session.percent == 46
    assert snap.weekly is not None and snap.weekly.percent == 48


def test_model_scoped_weekly_bucket():
    payload = {
        "limits": [
            {
                "kind": "weekly_scoped",
                "group": "weekly",
                "percent": 71,
                "severity": "warning",
                "resets_at": "2026-08-21T19:59:59+00:00",
                "scope": {"model": {"display_name": "Opus 5"}},
                "is_active": True,
            }
        ]
    }
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    bucket = snap.buckets[0]
    assert bucket.key == "weekly_scoped@Opus 5"
    assert bucket.label == "Weekly - Opus 5"
    assert bucket.scope_model == "Opus 5"
    assert bucket.severity == SEVERITY_WARNING


def test_severity_is_derived_when_absent():
    payload = {"five_hour": {"utilization": 97.0, "resets_at": None}}
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    assert snap.session is not None
    assert snap.session.severity == SEVERITY_DANGER
    assert snap.worst_severity == SEVERITY_DANGER


def test_all_null_payload_reports_error_without_raising():
    payload = {"five_hour": None, "seven_day": None, "limits": []}
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    assert not snap.ok
    assert snap.buckets == ()


def test_non_dict_payload():
    snap = parse_usage(["nope"], "acct", fetched_at=NOW)
    assert not snap.ok
    assert "not an object" in (snap.error or "")


def test_api_error_envelope_is_surfaced():
    payload = {"error": {"type": "rate_limit_error", "message": "slow down"}}
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    assert snap.error == "slow down"


def test_epoch_seconds_reset_and_spend_amounts():
    payload = {
        "five_hour": {"utilization": 10, "resets_at": 1787067202},
        "spend": {
            "used": {"amount_minor": 1234, "currency": "USD", "exponent": 2},
            "limit": {"amount_minor": 5000, "currency": "USD", "exponent": 2},
            "percent": 24,
            "enabled": True,
        },
    }
    snap = parse_usage(payload, "acct", fetched_at=NOW)
    assert snap.session is not None and snap.session.resets_at is not None
    assert snap.session.resets_at.year == 2026
    assert snap.spend is not None
    assert snap.spend.used_text == "12.34 USD"
    assert snap.spend.limit_text == "50.00 USD"
