from __future__ import annotations

import argparse
import os
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.infrastructure.database import Database
from app.infrastructure.maintenance import LeaseLostError, MaintenanceStore
from app.infrastructure.platform_connections import load_saved_settings
from app.infrastructure.platforms import MaintenanceChecks, PlatformSettings

SCHEDULE_ID = "platform-health"
LEASE_NAME = "maintenance"
DEFAULT_INTERVAL_SECONDS = 300


class MaintenanceWorker:
    def __init__(
        self,
        store: MaintenanceStore,
        checks: Any,
        *,
        worker_id: str | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        lease_seconds: int = 60,
        jitter_seconds: float = 0.25,
        enabled: bool = True,
    ) -> None:
        if interval_seconds < 1 or lease_seconds < 1:
            raise ValueError("interval_seconds and lease_seconds must be positive")
        worker_jitter = min(max(0.0, jitter_seconds), 1.0)
        probe_budget = float(getattr(checks, "max_run_seconds", 0.0))
        required_lease = probe_budget + worker_jitter + 5.0
        if lease_seconds < required_lease:
            raise ValueError(
                f"lease_seconds must be at least {required_lease:.1f} to cover the bounded probe budget"
            )
        self.store = store
        self.checks = checks
        self.worker_id = worker_id or f"maintenance-{uuid.uuid4().hex}"
        self.interval_seconds = interval_seconds
        self.lease_seconds = lease_seconds
        self.jitter_seconds = worker_jitter
        self.enabled = enabled

    def run_once(self, *, now: datetime | None = None) -> dict[str, int | bool]:
        started_at = now or datetime.now(UTC)
        if not self.store.acquire_worker_lease(
            lease_name=LEASE_NAME,
            owner_id=self.worker_id,
            now=started_at,
            lease_seconds=self.lease_seconds,
        ):
            return {"acquired": False, "checks": 0, "alerts_opened": 0, "alerts_resolved": 0}

        checks_written = 0
        alerts_opened = 0
        alerts_resolved = 0
        lease_now = started_at if now is not None else None
        try:
            schedule = self.store.get_schedule(SCHEDULE_ID)
            if schedule is None:
                schedule = self.store.save_schedule(
                    schedule_id=SCHEDULE_ID,
                    service_id="platform",
                    interval_seconds=self.interval_seconds,
                    enabled=self.enabled,
                    next_run_at=started_at,
                    lease_name=LEASE_NAME,
                    owner_id=self.worker_id,
                    lease_now=lease_now,
                )
            elif schedule.interval_seconds != self.interval_seconds or schedule.enabled != self.enabled:
                schedule = self.store.save_schedule(
                    schedule_id=SCHEDULE_ID,
                    service_id="platform",
                    interval_seconds=self.interval_seconds,
                    enabled=self.enabled,
                    next_run_at=started_at + timedelta(seconds=self.interval_seconds),
                    lease_name=LEASE_NAME,
                    owner_id=self.worker_id,
                    lease_now=lease_now,
                )
            if not schedule.enabled or _as_utc(schedule.next_run_at) > _as_utc(started_at):
                return {"acquired": True, "checks": 0, "alerts_opened": 0, "alerts_resolved": 0}

            # Explicitly extend ownership immediately before network work. The
            # default lease exceeds the bounded probe budget; callers can use a
            # larger lease for slower environments.
            if not self.store.renew_worker_lease(
                lease_name=LEASE_NAME,
                owner_id=self.worker_id,
                now=None if now is None else started_at,
                lease_seconds=self.lease_seconds,
            ):
                return {"acquired": False, "checks": 0, "alerts_opened": 0, "alerts_resolved": 0}

            if self.jitter_seconds:
                time.sleep(random.uniform(0.0, self.jitter_seconds))
            results = self.checks.run_all()
            if not self.store.renew_worker_lease(
                lease_name=LEASE_NAME,
                owner_id=self.worker_id,
                now=datetime.now(UTC) if now is None else started_at,
                lease_seconds=self.lease_seconds,
            ):
                # The lease may have expired and been acquired by another
                # worker. Never let a stale owner write outcomes or alerts.
                return {"acquired": False, "checks": 0, "alerts_opened": 0, "alerts_resolved": 0}

            recorded_at = now or datetime.now(UTC)
            for result in results:
                history = self.store.list_checks(service_id=result.service_id, limit=500)
                matching = [item for item in history if item.check_name == result.check_name]
                check_id = f"check_{uuid.uuid4().hex}"
                status = str(result.status)
                error_code = result.error_code
                self.store.record_check(
                    check_id=check_id,
                    schedule_id=SCHEDULE_ID,
                    service_id=result.service_id,
                    check_name=result.check_name,
                    status=status,
                    checked_at=recorded_at,
                    error_code=error_code,
                    details={
                        **(result.details or {}),
                        "duration_ms": int(result.duration_ms),
                    },
                    lease_name=LEASE_NAME,
                    owner_id=self.worker_id,
                    lease_now=lease_now,
                    advance_schedule=False,
                )
                checks_written += 1
                if status == "healthy":
                    unresolved = [
                        alert
                        for alert in self.store.list_alerts(limit=500)
                        if alert.service_id == result.service_id
                        and alert.check_name == result.check_name
                        and alert.status != "resolved"
                    ]
                    for alert in unresolved:
                        resolved = self.store.resolve_alert(
                            fingerprint=alert.fingerprint,
                            check_id=check_id,
                            resolved_at=recorded_at,
                            lease_name=LEASE_NAME,
                            owner_id=self.worker_id,
                            lease_now=lease_now,
                        )
                        if resolved is not None and resolved.status == "resolved":
                            alerts_resolved += 1
                    continue

                normalized_error = error_code or "CHECK_FAILED"
                failures = 1
                for previous in matching:
                    if previous.status == "healthy" or previous.error_code != normalized_error:
                        break
                    failures += 1
                if failures >= 2:
                    self.store.upsert_alert(
                        fingerprint=_fingerprint(result.service_id, result.check_name, normalized_error),
                        service_id=result.service_id,
                        check_name=result.check_name,
                        error_code=normalized_error,
                        severity="warning" if status == "empty_catalog" else "error",
                        check_id=check_id,
                        occurred_at=recorded_at,
                        consecutive_failures=failures,
                        lease_name=LEASE_NAME,
                        owner_id=self.worker_id,
                        lease_now=lease_now,
                    )
                    alerts_opened += 1

            # Advance only after every probe outcome and alert write succeeds.
            # An interrupted batch stays due so the next lease owner retries.
            self.store.complete_schedule_cycle(
                schedule_id=SCHEDULE_ID,
                completed_at=recorded_at,
                lease_name=LEASE_NAME,
                owner_id=self.worker_id,
                lease_now=lease_now,
            )

            return {
                "acquired": True,
                "checks": checks_written,
                "alerts_opened": alerts_opened,
                "alerts_resolved": alerts_resolved,
            }
        except LeaseLostError:
            return {
                "acquired": False,
                "checks": checks_written,
                "alerts_opened": alerts_opened,
                "alerts_resolved": alerts_resolved,
            }
        finally:
            self.store.release_worker_lease(lease_name=LEASE_NAME, owner_id=self.worker_id)


def _fingerprint(service_id: str, check_name: str, error_code: str) -> str:
    return f"{service_id}:{check_name}:{error_code}"


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def run_once(
    store: MaintenanceStore,
    checks: Any,
    *,
    worker_id: str | None = None,
    now: datetime | None = None,
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    lease_seconds: int = 60,
) -> dict[str, int | bool]:
    return MaintenanceWorker(
        store,
        checks,
        worker_id=worker_id,
        interval_seconds=interval_seconds,
        lease_seconds=lease_seconds,
    ).run_once(now=now)


def build_checks(
    database: Database,
    *,
    timeout_seconds: float,
    retries: int,
    max_concurrency: int,
) -> MaintenanceChecks:
    """Use Hub's active, encrypted platform connections for scheduled checks."""
    settings = load_saved_settings(database, PlatformSettings.from_env())
    return MaintenanceChecks(
        settings=settings,
        timeout_seconds=timeout_seconds,
        retries=retries,
        max_concurrency=max_concurrency,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run persistent Lyra Hub read-only service health checks.")
    parser.add_argument("--once", action="store_true", help="run one due maintenance cycle and exit")
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("LYRA_MAINTENANCE_POLL_SECONDS", "5")))
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.getenv("LYRA_MAINTENANCE_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))),
    )
    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=int(os.getenv("LYRA_MAINTENANCE_LEASE_SECONDS", "60")),
    )
    parser.add_argument(
        "--check-timeout-seconds",
        type=float,
        default=float(os.getenv("LYRA_MAINTENANCE_CHECK_TIMEOUT_SECONDS", "3")),
    )
    parser.add_argument(
        "--check-retries",
        type=int,
        default=int(os.getenv("LYRA_MAINTENANCE_CHECK_RETRIES", "1")),
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=int(os.getenv("LYRA_MAINTENANCE_MAX_CONCURRENCY", "5")),
    )
    args = parser.parse_args()
    if (
        args.poll_seconds <= 0
        or args.interval_seconds <= 0
        or args.lease_seconds <= 0
        or args.check_timeout_seconds <= 0
        or args.check_retries < 0
        or args.max_concurrency < 1
    ):
        parser.error("poll, interval, lease, and timeout must be positive; retries must be non-negative")

    database = Database()
    database.initialize()
    store = MaintenanceStore(database)
    checks = build_checks(
        database,
        timeout_seconds=args.check_timeout_seconds,
        retries=args.check_retries,
        max_concurrency=args.max_concurrency,
    )
    try:
        worker = MaintenanceWorker(
            store,
            checks,
            interval_seconds=args.interval_seconds,
            lease_seconds=args.lease_seconds,
        )
    except ValueError as exc:
        parser.error(str(exc))
    while True:
        checks.settings = load_saved_settings(database, PlatformSettings.from_env())
        summary = worker.run_once()
        if args.once:
            print(summary, flush=True)
            return 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
