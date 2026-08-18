"""Thin HTTP layer over the OAuth-authenticated Anthropic endpoints."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from ..config import API_BASE_URL, USER_AGENT
from .usage import USAGE_PATH

log = logging.getLogger(__name__)

PROFILE_PATH = "/api/oauth/profile"


class ApiError(Exception):
    def __init__(
        self,
        message: str,
        status: int | None = None,
        retry_after: float | None = None,
        kind: str = "http",
    ) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after
        self.kind = kind

    @property
    def is_auth(self) -> bool:
        return self.status in (401, 403)

    @property
    def is_rate_limited(self) -> bool:
        return self.status == 429

    @property
    def user_message(self) -> str:
        """Short line for the overlay -- never a raw JSON body."""
        if self.is_rate_limited:
            return "Rate limited by the API"
        if self.is_auth:
            return "Login expired"
        if self.kind == "network":
            return "Offline"
        if self.status:
            return f"API error {self.status}"
        return "Unavailable"


def _error_detail(response: httpx.Response) -> str:
    """Pull the message out of an error envelope, else a trimmed body."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:160].strip() or "no body"
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error.get("type") or payload)[:160]
    return str(payload)[:160]


class UsageClient:
    """One shared httpx client for all accounts."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            base_url=API_BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Content-Type": "application/json"},
        )

    @property
    def http(self) -> httpx.Client:
        return self._client

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "UsageClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, path: str, access_token: str) -> Any:
        try:
            response = self._client.get(path, headers={"Authorization": f"Bearer {access_token}"})
        except httpx.HTTPError as exc:
            raise ApiError(f"Network error: {exc}", kind="network") from exc

        if response.status_code != 200:
            retry_after = None
            header = response.headers.get("retry-after")
            if header:
                try:
                    retry_after = float(header)
                except ValueError:
                    retry_after = None
            detail = _error_detail(response)
            raise ApiError(
                f"HTTP {response.status_code} from {path}: {detail}",
                status=response.status_code,
                retry_after=retry_after,
                kind="rate_limited" if response.status_code == 429 else "http",
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ApiError(f"Non-JSON response from {path}", kind="format") from exc

    def fetch_usage(self, access_token: str) -> Any:
        return self._get(USAGE_PATH, access_token)

    def fetch_profile(self, access_token: str) -> Any:
        return self._get(PROFILE_PATH, access_token)
