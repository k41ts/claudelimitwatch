"""Account naming.

The Claude Code account is named from ~/.claude.json, which is only a guess:
it can name a different account than the token in .credentials.json belongs
to. Getting this wrong is worse than showing no name at all, because the user
reads one account's usage under another account's label.
"""

import pytest

from climitwatch.accounts import AccountSource, ProfileInfo
from climitwatch.models import Account


def source(**kwargs) -> AccountSource:
    defaults = dict(id="claude-code", label="Guess", source="claude-code")
    defaults.update(kwargs)
    return AccountSource(Account(**defaults))


def test_guessed_identity_starts_unverified():
    assert source(email="guess@example.com").account.identity_verified is False


def test_profile_overrides_the_guess_and_verifies_it():
    s = source(email="guess@example.com", label="Guess")
    s.note_profile(
        ProfileInfo(email="real@example.com", display_name="Real", plan="claude_pro")
    )

    assert s.account.email == "real@example.com"
    assert s.account.label == "Real"
    assert s.account.plan == "claude_pro"
    assert s.account.identity_verified is True


def test_profile_without_a_display_name_falls_back_to_email():
    s = source()
    s.note_profile(ProfileInfo(email="real@example.com"))
    assert s.account.label == "real@example.com"


def test_two_accounts_named_alike_stay_distinguishable_by_id():
    a = source(id="claude-code", label="Vina")
    b = source(id="uuid-2", label="Vina", source="app")
    assert a.account.id != b.account.id


@pytest.mark.parametrize(
    "profile,expected_label",
    [
        (ProfileInfo(display_name="Kai", email="kai@example.com"), "Kai"),
        (ProfileInfo(email="only@example.com"), "only@example.com"),
        (ProfileInfo(account_uuid="abcdef123456"), "abcdef12"),
    ],
)
def test_label_resolution_order(profile, expected_label):
    s = source()
    s.note_profile(profile)
    assert s.account.label == expected_label
