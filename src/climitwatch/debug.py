"""Headless check: print every account's limits once and exit.

    python -m climitwatch.debug [--json] [--raw] [--read-only]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict

from . import cache
from .accounts import AccountManager
from .api.client import UsageClient
from .formatting import age_text, bucket_line, local_time
from .models import UsageSnapshot


def _print_snapshot(snapshot: UsageSnapshot, label: str, show_raw: bool) -> None:
    print(f"\n=== {label} ({snapshot.account_id}) ===")
    if not snapshot.ok:
        print(f"  error: {snapshot.error}")
        return
    print(f"  fetched: {age_text(snapshot)}  plan: {snapshot.subscription_type or '?'}")
    for bucket in snapshot.buckets:
        marker = "*" if bucket.is_active else " "
        print(f"  {marker} {bucket_line(bucket)}  [{bucket.severity}]  resets_at={local_time(bucket.resets_at)}")
    spend = snapshot.spend
    if spend is not None and spend.enabled:
        print(f"    credits: {spend.used_text or '?'} used of {spend.limit_text or 'no cap'}")
    if show_raw:
        print(json.dumps(snapshot.raw, indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="climitwatch.debug")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--raw", action="store_true", help="also dump the raw API payload")
    parser.add_argument("--read-only", action="store_true", help="never write .credentials.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    manager = AccountManager(read_only_credentials=args.read_only)
    # Same identity cache the overlay uses, so both name accounts identically.
    identities = cache.load_identities()
    for source in manager.sources:
        entry = identities.get(source.account.id) or {}
        source.account.label = entry.get("label") or source.account.label
        source.account.email = entry.get("email") or source.account.email
        source.account.plan = entry.get("plan") or source.account.plan

    if not manager.sources:
        print("No accounts found. Log in with Claude Code, or add an account in the app.")
        return 1

    with UsageClient() as client:
        results = [(source, manager.poll(source, client)) for source in manager.sources]

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "account": asdict(source.account),
                        "snapshot": {
                            **asdict(snapshot),
                            "fetched_at": snapshot.fetched_at.isoformat(),
                            "buckets": [
                                {**asdict(b), "resets_at": b.resets_at.isoformat() if b.resets_at else None}
                                for b in snapshot.buckets
                            ],
                            "raw": snapshot.raw if args.raw else None,
                        },
                    }
                    for source, snapshot in results
                ],
                indent=2,
                default=str,
            )
        )
        return 0

    for source, snapshot in results:
        _print_snapshot(snapshot, f"{source.account.display} [{source.account.source}]", args.raw)
    return 0


if __name__ == "__main__":
    sys.exit(main())
