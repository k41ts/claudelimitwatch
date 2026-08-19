"""Account registry: the Claude Code login plus any accounts we logged into."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .api.client import ApiError, UsageClient
from .api.usage import parse_usage
from .auth.cc_credentials import ClaudeCodeCredentials, read_account_info
from .auth.oauth import AuthError, TokenSet, refresh_tokens
from .auth.store import AccountStore, StoredAccount
from .models import Account, UsageSnapshot

log = logging.getLogger(__name__)

CLAUDE_CODE_ID = "claude-code"


@dataclass(frozen=True)
class ProfileInfo:
    email: str | None = None
    display_name: str | None = None
    plan: str | None = None
    account_uuid: str | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.email or (self.account_uuid or "account")[:8]


def parse_profile(payload: Any) -> ProfileInfo:
    if not isinstance(payload, dict):
        return ProfileInfo()
    account = payload.get("account") if isinstance(payload.get("account"), dict) else {}
    org = payload.get("organization") if isinstance(payload.get("organization"), dict) else {}
    plan = org.get("organization_type")
    if not isinstance(plan, str):
        plan = "max" if account.get("has_claude_max") else "pro" if account.get("has_claude_pro") else None
    return ProfileInfo(
        email=account.get("email") if isinstance(account.get("email"), str) else None,
        display_name=account.get("display_name") if isinstance(account.get("display_name"), str) else None,
        plan=plan,
        account_uuid=account.get("uuid") if isinstance(account.get("uuid"), str) else None,
    )


class AccountSource:
    """An account plus whatever it takes to get a fresh access token."""

    def __init__(self, account: Account) -> None:
        self.account = account
        self.needs_login = False
        self.last_error: str | None = None

    def ensure_fresh(self, client: UsageClient) -> TokenSet:  # pragma: no cover - interface
        raise NotImplementedError

    def note_profile(self, profile: ProfileInfo) -> None:
        if profile.email:
            self.account.email = profile.email
        if profile.plan:
            self.account.plan = profile.plan
        if profile.label:
            self.account.label = profile.label
        self.account.identity_verified = True


class ClaudeCodeSource(AccountSource):
    """Shares ``~/.claude/.credentials.json`` with the CLI."""

    def __init__(self, read_only: bool = False) -> None:
        info = read_account_info()
        super().__init__(
            Account(
                id=CLAUDE_CODE_ID,
                label=info.label,
                source="claude-code",
                email=info.email,
                plan=info.plan,
            )
        )
        self.credentials = ClaudeCodeCredentials(read_only=read_only)

    @property
    def available(self) -> bool:
        return self.credentials.available

    def ensure_fresh(self, client: UsageClient) -> TokenSet:
        tokens = self.credentials.ensure_fresh(client=client.http)
        if tokens.subscription_type and not self.account.plan:
            self.account.plan = tokens.subscription_type
        return tokens


class StoredAccountSource(AccountSource):
    """An account the watcher logged into; tokens are ours alone."""

    def __init__(self, store: AccountStore, stored: StoredAccount) -> None:
        super().__init__(
            Account(
                id=stored.id,
                label=stored.label,
                source="app",
                email=stored.email,
                plan=stored.plan,
                enabled=stored.enabled,
                identity_verified=bool(stored.email),
            )
        )
        self.store = store
        self.stored = stored
        self.needs_login = stored.needs_login

    def ensure_fresh(self, client: UsageClient) -> TokenSet:
        tokens = self.stored.tokens()
        if not tokens.access_token:
            raise AuthError("No token stored for this account", needs_login=True)
        if not tokens.needs_refresh():
            return tokens
        try:
            fresh = refresh_tokens(tokens, client=client.http)
        except AuthError as exc:
            if exc.needs_login:
                self.stored.needs_login = True
                self.needs_login = True
                self.store.save()
            raise
        self.stored.apply(fresh)
        self.stored.needs_login = False
        self.needs_login = False
        self.store.save()
        return fresh

    def note_profile(self, profile: ProfileInfo) -> None:
        super().note_profile(profile)
        changed = False
        if profile.email and self.stored.email != profile.email:
            self.stored.email = profile.email
            changed = True
        if profile.plan and self.stored.plan != profile.plan:
            self.stored.plan = profile.plan
            changed = True
        if profile.label and self.stored.label != profile.label:
            self.stored.label = profile.label
            changed = True
        if changed:
            self.store.save()


class AccountManager:
    """Owns the account list and turns each one into a usage snapshot."""

    def __init__(self, read_only_credentials: bool = False) -> None:
        self.store = AccountStore()
        self.read_only_credentials = read_only_credentials
        self._sources: list[AccountSource] = []
        self._profile_fetched: set[str] = set()
        self.reload()

    def reload(self) -> None:
        sources: list[AccountSource] = []
        # Reuse the existing Claude Code source so its in-memory refresh state
        # (and any token it holds after losing a race with the CLI) survives.
        cc = next(
            (s for s in self._sources if isinstance(s, ClaudeCodeSource)),
            None,
        ) or ClaudeCodeSource(read_only=self.read_only_credentials)
        if cc.available:
            sources.append(cc)
        for stored in self.store.accounts:
            sources.append(StoredAccountSource(self.store, stored))
        self._sources = sources

    @property
    def sources(self) -> list[AccountSource]:
        return list(self._sources)

    @property
    def accounts(self) -> list[Account]:
        return [s.account for s in self._sources]

    def source(self, account_id: str) -> AccountSource | None:
        return next((s for s in self._sources if s.account.id == account_id), None)

    def enabled_sources(self) -> Iterable[AccountSource]:
        return (s for s in self._sources if s.account.enabled and not s.needs_login)

    # -- polling ----------------------------------------------------------

    def poll(self, source: AccountSource, client: UsageClient) -> UsageSnapshot:
        now = datetime.now(timezone.utc)
        try:
            tokens = source.ensure_fresh(client)
        except AuthError as exc:
            source.needs_login = exc.needs_login
            source.last_error = str(exc)
            return UsageSnapshot(
                account_id=source.account.id,
                fetched_at=now,
                error=str(exc),
                error_short="Login expired" if exc.needs_login else "Auth failed",
            )

        try:
            payload = client.fetch_usage(tokens.access_token)
        except ApiError as exc:
            source.last_error = str(exc)
            log.info("Usage fetch failed for %s: %s", source.account.id, exc)
            return UsageSnapshot(
                account_id=source.account.id,
                fetched_at=now,
                error=str(exc),
                error_short=exc.user_message,
                retry_after=exc.retry_after,
            )

        # The profile call resolves who the token really belongs to. Skip it
        # only once that answer is verified (this run, or cached from an earlier
        # one) -- an email guessed from ~/.claude.json does not count, or a
        # mislabelled account would stay mislabelled forever.
        if source.account.id not in self._profile_fetched and not source.account.identity_verified:
            self._profile_fetched.add(source.account.id)
            try:
                source.note_profile(parse_profile(client.fetch_profile(tokens.access_token)))
            except ApiError as exc:
                log.debug("Profile fetch failed for %s: %s", source.account.id, exc)

        source.last_error = None
        return parse_usage(
            payload,
            account_id=source.account.id,
            fetched_at=now,
            subscription_type=source.account.plan or tokens.subscription_type,
        )

    def poll_all(self, client: UsageClient) -> list[UsageSnapshot]:
        return [self.poll(source, client) for source in self.enabled_sources()]

    # -- mutation ---------------------------------------------------------

    def add_logged_in_account(self, tokens: TokenSet, client: UsageClient) -> Account:
        profile = ProfileInfo()
        try:
            profile = parse_profile(client.fetch_profile(tokens.access_token))
        except ApiError as exc:
            log.warning("Could not read profile for new account: %s", exc)
        stored = self.store.add(
            tokens,
            label=profile.label,
            email=profile.email,
            plan=profile.plan,
        )
        self.reload()
        source = self.source(stored.id)
        return source.account if source else Account(id=stored.id, label=stored.label, source="app")

    def remove_account(self, account_id: str) -> None:
        if account_id == CLAUDE_CODE_ID:
            return
        self.store.remove(account_id)
        self.reload()
