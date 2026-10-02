from __future__ import annotations

import argparse
import os
import time

from app.infrastructure.database import Database
from app.infrastructure.events import EventService, WebhookSecretRegistry


def run_once(
    service: EventService,
    *,
    batch_size: int = 50,
    lease_seconds: int = 300,
) -> dict[str, int]:
    return service.process_due_deliveries(
        limit=max(1, batch_size),
        lease_seconds=max(1, lease_seconds),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deliver due Lyra Hub event webhooks from the persistent outbox."
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=float(os.getenv("LYRA_EVENT_WORKER_POLL_SECONDS", "5")),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=int(os.getenv("LYRA_EVENT_WORKER_BATCH_SIZE", "50")),
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(os.getenv("LYRA_EVENT_WORKER_LEASE_SECONDS", "300")),
    )
    args = parser.parse_args()

    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    if args.batch_size <= 0:
        parser.error("--batch-size must be positive")
    if args.lease_seconds <= 0:
        parser.error("--lease-seconds must be positive")

    database = Database()
    database.initialize()
    service = EventService(
        database,
        secrets=WebhookSecretRegistry.from_env(),
    )

    while True:
        summary = run_once(
            service,
            batch_size=args.batch_size,
            lease_seconds=args.lease_seconds,
        )
        if args.once:
            print(summary, flush=True)
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
