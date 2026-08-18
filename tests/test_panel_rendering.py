"""The detail panel is re-rendered every few seconds, so it must not leak.

Clearing a layout by hand used to miss widgets nested more than one level deep
(the per-bucket name/value labels), leaving orphans stacked over the header.
"""

import datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QLabel  # noqa: E402

from climitwatch.models import LimitBucket, UsageSnapshot  # noqa: E402
from climitwatch.ui.panel import DetailPanel  # noqa: E402
from climitwatch.ui.theme import set_theme  # noqa: E402

NOW = datetime.datetime.now(datetime.timezone.utc)


def snapshot(session: float, weekly: float) -> UsageSnapshot:
    return UsageSnapshot(
        account_id="a",
        fetched_at=NOW,
        buckets=(
            LimitBucket("session", "Session (5h)", session, NOW + datetime.timedelta(hours=4)),
            LimitBucket("weekly_all", "Weekly (all models)", weekly, NOW + datetime.timedelta(days=3)),
        ),
        subscription_type="claude_pro",
    )


@pytest.fixture()
def panel(qt_app):
    set_theme("cyberpunk")
    widget = DetailPanel()
    yield widget
    widget.deleteLater()


def label_count(card) -> int:
    return len(card.findChildren(QLabel))


def test_repeated_renders_do_not_pile_up_widgets(panel):
    entries = lambda error: [("a", "acct@example.com", "claude_pro", snapshot(10, 20), error)]  # noqa: E731

    panel.render_accounts(entries(None))
    card = panel._card_widgets["a"]
    baseline = label_count(card)

    for _ in range(6):
        panel.render_accounts(entries(None))
    assert label_count(card) == baseline, "each render must replace the body, not add to it"


def test_error_banner_does_not_displace_the_title(panel):
    panel.render_accounts([("a", "acct@example.com", "claude_pro", snapshot(10, 20), None)])
    card = panel._card_widgets["a"]

    panel.render_accounts(
        [("a", "acct@example.com", "claude_pro", snapshot(10, 20), "Rate limited by the API")]
    )
    assert card.title.text() == "ACCT@EXAMPLE.COM"
    banners = [
        label.text()
        for label in card.findChildren(QLabel)
        if "showing last known values" in label.text()
    ]
    assert len(banners) == 1


def test_switching_between_error_and_ok_keeps_one_body(panel):
    for error in (None, "Offline", None, "Rate limited by the API", None):
        panel.render_accounts([("a", "acct@example.com", "claude_pro", snapshot(10, 20), error)])
    card = panel._card_widgets["a"]

    stale = [label for label in card.findChildren(QLabel) if "showing last known values" in label.text()]
    assert stale == [], "the banner must disappear once polling recovers"


def test_removed_account_drops_its_card(panel):
    panel.render_accounts(
        [
            ("a", "acct@example.com", "claude_pro", snapshot(10, 20), None),
            ("b", "second", "claude_pro", snapshot(30, 40), None),
        ]
    )
    assert set(panel._card_widgets) == {"a", "b"}

    panel.render_accounts([("a", "acct@example.com", "claude_pro", snapshot(10, 20), None)])
    assert set(panel._card_widgets) == {"a"}
