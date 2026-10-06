from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from app.api.routes.platform_connections import (
    _check as check_platform_connection,
)
from app.api.routes.platform_connections import (
    connection_update_lock,
    get_database,
    get_platform_services,
    require_platform_admin,
)
from app.infrastructure.database import (
    Database,
    MaintenanceAlertRecord,
    MaintenanceCheckRecord,
    MaintenanceRepairAuditRecord,
    PlatformConnectionRecord,
    record_audit,
)
from app.infrastructure.maintenance import MaintenanceStore
from app.infrastructure.platform_connections import SERVICE_FIELDS, deserialize_connection
from app.infrastructure.platforms import MaintenanceCheckResult, MaintenanceChecks, PlatformServices

router = APIRouter(prefix="/maintenance", tags=["maintenance"])
ServiceId = Literal["gateway", "agent-os"]


class RepairConfirmation(BaseModel):
    action: Literal["restore_last_good"]
    expected_revision: int = Field(ge=0)
    confirmed: bool


def get_maintenance_store(database: Database = Depends(get_database)) -> MaintenanceStore:
    return MaintenanceStore(database)


def get_maintenance_checks(services: PlatformServices = Depends(get_platform_services)) -> MaintenanceChecks:
    return MaintenanceChecks(settings=services.settings)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _alert_payload(alert: MaintenanceAlertRecord) -> dict[str, Any]:
    return {
        "id": alert.id,
        "service_id": alert.service_id,
        "check_name": alert.check_name,
        "error_code": alert.error_code,
        "severity": alert.severity,
        "status": alert.status,
        "first_check_id": alert.first_check_id,
        "last_check_id": alert.last_check_id,
        "recovery_check_id": alert.recovery_check_id,
        "consecutive_failures": alert.consecutive_failures,
        "first_occurred_at": _iso(alert.first_occurred_at),
        "last_occurred_at": _iso(alert.last_occurred_at),
        "resolved_at": _iso(alert.resolved_at),
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": _iso(alert.acknowledged_at),
    }


def _check_payload(result: MaintenanceCheckResult) -> dict[str, Any]:
    return {
        "service_id": result.service_id,
        "check_name": result.check_name,
        "status": result.status,
        "error_code": result.error_code,
        "details": result.details or {},
        "duration_ms": result.duration_ms,
    }


@router.get("/overview", dependencies=[Depends(require_platform_admin)])
def get_overview(
    store: MaintenanceStore = Depends(get_maintenance_store),
) -> dict[str, Any]:
    schedule = store.get_schedule("platform-health")
    checks = store.list_checks(limit=500)
    checks_by_service: dict[str, dict[str, Any]] = {}
    status_rank = {"unknown": 0, "healthy": 1, "empty_catalog": 2, "unhealthy": 3}
    for check in checks:
        service_checks = checks_by_service.setdefault(check.service_id, {})
        candidate = {
                "status": check.status,
                "checked_at": _iso(check.checked_at),
                "check_name": check.check_name,
                "error_code": check.error_code,
                "details": check.details,
            }
        current = service_checks.get(check.check_name)
        if current is None or _check_is_newer_or_worse(check, current, status_rank):
            service_checks[check.check_name] = candidate
    services: dict[str, dict[str, Any]] = {}
    for service_id in ("hub", "gateway", "agents", "narrative", "print"):
        grouped = checks_by_service.get(service_id, {})
        if not grouped:
            services[service_id] = {"status": "unknown", "checks": {}}
            continue
        worst_status = max(
            (item["status"] for item in grouped.values()),
            key=lambda item: status_rank.get(item, status_rank["unknown"]),
        )
        latest_check = max(grouped.values(), key=lambda item: item["checked_at"] or "")
        services[service_id] = {
            "status": worst_status,
            "checked_at": latest_check["checked_at"],
            "checks": dict(sorted(grouped.items())),
        }
    agents_status = services["agents"]["status"]
    return {
        "data": {
            "schedule": (
                {
                    "schedule_id": schedule.schedule_id,
                    "interval_seconds": schedule.interval_seconds,
                    "enabled": schedule.enabled,
                    "next_run_at": _iso(schedule.next_run_at),
                    "last_run_at": _iso(schedule.last_run_at),
                }
                if schedule is not None
                else None
            ),
            "services": services,
            "open_alerts": len(store.list_alerts(status="open", limit=500)),
            "agents_available": (
                None if agents_status == "unknown" else agents_status in {"healthy", "empty_catalog"}
            ),
        }
    }


def _check_is_newer_or_worse(check: Any, current: dict[str, Any], status_rank: dict[str, int]) -> bool:
    current_at = current["checked_at"] or ""
    candidate_at = _iso(check.checked_at) or ""
    return candidate_at > current_at or (
        candidate_at == current_at
        and status_rank.get(check.status, 0) > status_rank.get(current["status"], 0)
    )


@router.get("/alerts", dependencies=[Depends(require_platform_admin)])
def get_alerts(
    alert_status: Literal["open", "acknowledged", "resolved"] | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    store: MaintenanceStore = Depends(get_maintenance_store),
) -> dict[str, Any]:
    return {"data": [_alert_payload(item) for item in store.list_alerts(status=alert_status, limit=limit)]}


@router.post("/checks", dependencies=[Depends(require_platform_admin)])
def run_checks(
    store: MaintenanceStore = Depends(get_maintenance_store),
    database: Database = Depends(get_database),
    checks: MaintenanceChecks = Depends(get_maintenance_checks),
) -> dict[str, Any]:
    results = checks.run_all()
    checked_at = datetime.now(UTC)
    payloads: list[dict[str, Any]] = []
    for result in results:
        check_id = f"check_{hashlib.sha256(f'{result.service_id}:{result.check_name}:{checked_at.isoformat()}'.encode()).hexdigest()[:32]}"
        store.record_check(
            check_id=check_id,
            schedule_id=None,
            service_id=result.service_id,
            check_name=result.check_name,
            status=result.status,
            error_code=result.error_code,
            checked_at=checked_at,
            details={**(result.details or {}), "duration_ms": result.duration_ms, "source": "manual"},
        )
        _update_alerts_for_check(store, result, check_id, checked_at)
        with database.session() as session, session.begin():
            record_audit(
                session,
                action="maintenance.check_triggered",
                target_type="maintenance-check",
                target_id=check_id,
                payload={"service_id": result.service_id, "check_name": result.check_name,
                         "status": result.status, "error_code": result.error_code},
            )
        payloads.append({**_check_payload(result), "check_id": check_id, "checked_at": checked_at.isoformat()})
    return {"data": payloads}


def _update_alerts_for_check(
    store: MaintenanceStore,
    result: MaintenanceCheckResult,
    check_id: str,
    checked_at: datetime,
) -> None:
    history = store.list_checks(service_id=result.service_id, limit=500)
    prior = [item for item in history if item.check_name == result.check_name][1:]
    if result.status == "healthy":
        for alert in store.list_alerts(limit=500):
            if alert.service_id == result.service_id and alert.check_name == result.check_name and alert.status != "resolved":
                store.resolve_alert(fingerprint=alert.fingerprint, check_id=check_id, resolved_at=checked_at)
        return
    error_code = result.error_code or "CHECK_FAILED"
    failures = 1
    for previous in prior:
        if previous.status == "healthy" or previous.error_code != error_code:
            break
        failures += 1
    if failures >= 2:
        store.upsert_alert(
            fingerprint=f"{result.service_id}:{result.check_name}:{error_code}",
            service_id=result.service_id,
            check_name=result.check_name,
            error_code=error_code,
            severity="warning" if result.status == "empty_catalog" else "error",
            check_id=check_id,
            occurred_at=checked_at,
            consecutive_failures=failures,
        )


@router.post("/alerts/{alert_id}/acknowledge", dependencies=[Depends(require_platform_admin)])
def acknowledge_alert(
    alert_id: int,
    database: Database = Depends(get_database),
) -> dict[str, Any]:
    now = datetime.now(UTC)
    with database.session() as session, session.begin():
        changed = session.execute(
            update(MaintenanceAlertRecord)
            .where(
                MaintenanceAlertRecord.id == alert_id,
                MaintenanceAlertRecord.status == "open",
            )
            .values(status="acknowledged", acknowledged_by="platform-admin", acknowledged_at=now)
        )
        alert = session.get(MaintenanceAlertRecord, alert_id)
        if alert is None:
            raise HTTPException(status_code=404, detail={"code": "ALERT_NOT_FOUND"})
        if alert.status == "resolved":
            raise HTTPException(status_code=409, detail={"code": "ALERT_ALREADY_RESOLVED"})
        if changed.rowcount == 1:
            record_audit(
                session,
                action="maintenance.alert_acknowledged",
                target_type="maintenance-alert",
                target_id=str(alert_id),
                payload={"actor_id": "platform-admin", "service_id": alert.service_id},
            )
        session.flush()
        payload = _alert_payload(alert)
    return {"data": payload}


def _repair_identity(idempotency_key: str, service_id: str) -> str:
    return hashlib.sha256(f"maintenance-repair:{service_id}:{idempotency_key}".encode()).hexdigest()


def _repair_response_from_audit(record: MaintenanceRepairAuditRecord) -> dict[str, Any]:
    details = record.details
    check = details.get("check")
    verification_status = (
        "healthy"
        if isinstance(check, dict) and check.get("reachable") is True and check.get("catalog_access") is True
        else "unhealthy"
    )
    return {
        "data": {
            "service_id": record.service_id,
            "action": record.action,
            "configuration_status": "restored",
            "verification_status": verification_status,
            "revision": details.get("result_revision"),
            "check": check,
            "replayed": True,
        }
    }


def _complete_repair_verification(
    *,
    database: Database,
    services: PlatformServices,
    service_id: ServiceId,
    url: str,
    token: str,
    audit_id: str,
    request_hash: str,
    result_revision: int,
    replayed: bool,
) -> dict[str, Any]:
    check = check_platform_connection(service_id, url, token, services)
    safe_check = {
        key: check.get(key)
        for key in ("service_id", "reachable", "catalog_access", "catalog_name", "catalog_count", "error_code", "checked_at")
    }
    checked_at = datetime.now(UTC)
    check_id = f"repair-check-{audit_id[:32]}"
    with database.session() as session:
        already_recorded = session.get(MaintenanceCheckRecord, check_id) is not None
    if not already_recorded:
        try:
            MaintenanceStore(database).record_check(
                check_id=check_id,
                schedule_id=None,
                service_id=service_id,
                check_name=f"{service_id}.models" if service_id == "gateway" else f"{service_id}.agents",
                status="healthy" if check["reachable"] and check["catalog_access"] else "unhealthy",
                error_code=check["error_code"],
                checked_at=checked_at,
                details={"source": "repair_verification", "catalog_count": check.get("catalog_count")},
            )
        except IntegrityError:
            # A concurrent replay may have inserted this deterministic check ID.
            with database.session() as session:
                if session.get(MaintenanceCheckRecord, check_id) is None:
                    raise

    with database.session() as session, session.begin():
        audit = session.get(MaintenanceRepairAuditRecord, audit_id)
        audit.details_json = json.dumps(
            {"request_hash": request_hash, "result_revision": result_revision, "check": safe_check},
            sort_keys=True,
        )
        audit.result = (
            "succeeded" if check["reachable"] and check["catalog_access"] else "restored_unhealthy"
        )
    return {
        "data": {
            "service_id": service_id,
            "action": "restore_last_good",
            "configuration_status": "restored",
            "verification_status": "healthy" if check["reachable"] and check["catalog_access"] else "unhealthy",
            "revision": result_revision,
            "check": safe_check,
            "replayed": replayed,
        }
    }


@router.post("/repairs/{service_id}/confirm", dependencies=[Depends(require_platform_admin)])
def confirm_repair(
    service_id: ServiceId,
    request: RepairConfirmation,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    database: Database = Depends(get_database),
    services: PlatformServices = Depends(get_platform_services),
) -> dict[str, Any]:
    if not request.confirmed:
        raise HTTPException(status_code=422, detail={"code": "CONFIRMATION_REQUIRED"})
    if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 255:
        raise HTTPException(status_code=422, detail={"code": "IDEMPOTENCY_KEY_REQUIRED"})

    key = idempotency_key.strip()
    audit_id = _repair_identity(key, service_id)
    request_hash = hashlib.sha256(
        json.dumps(
            {"service_id": service_id, "action": request.action, "expected_revision": request.expected_revision},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with database.session() as session:
        previous = session.get(MaintenanceRepairAuditRecord, audit_id)
    if previous is not None:
        if previous.details.get("request_hash") != request_hash:
            raise HTTPException(status_code=409, detail={"code": "IDEMPOTENCY_KEY_REUSED"})
        if previous.result in {"succeeded", "restored_unhealthy"}:
            return _repair_response_from_audit(previous)
        with connection_update_lock():
            with database.session() as session:
                restored_record = session.get(PlatformConnectionRecord, service_id)
                expected_result_revision = previous.details.get("result_revision")
                if restored_record is None or restored_record.revision != expected_result_revision:
                    raise HTTPException(status_code=503, detail={"code": "REPAIR_RESULT_PENDING"})
                url, token = deserialize_connection(restored_record.current_json)
            url_field, token_field = SERVICE_FIELDS[service_id]
            services.configure(
                services.settings.__class__(**{**services.settings.__dict__, url_field: url, token_field: token})
            )
        return _complete_repair_verification(
            database=database,
            services=services,
            service_id=service_id,
            url=url,
            token=token,
            audit_id=audit_id,
            request_hash=request_hash,
            result_revision=int(expected_result_revision),
            replayed=True,
        )

    url_field, token_field = SERVICE_FIELDS[service_id]
    with database.session() as session:
        record = session.get(PlatformConnectionRecord, service_id)
        if record is None or not record.last_good_json:
            raise HTTPException(status_code=409, detail={"code": "NO_LAST_GOOD_CONNECTION"})
        if record.revision != request.expected_revision:
            raise HTTPException(
                status_code=409,
                detail={"code": "REVISION_CONFLICT", "current_revision": record.revision},
            )
        try:
            url, token = deserialize_connection(record.last_good_json)
        except HTTPException:
            raise
        current_revision = record.revision
        serialized = record.last_good_json

    next_revision = current_revision + 1
    now = datetime.now(UTC)
    try:
        with connection_update_lock():
            with database.session() as session, session.begin():
                changed = session.execute(
                    update(PlatformConnectionRecord)
                    .where(
                        PlatformConnectionRecord.service_id == service_id,
                        PlatformConnectionRecord.revision == request.expected_revision,
                        PlatformConnectionRecord.last_good_json == serialized,
                    )
                    .values(current_json=serialized, revision=next_revision, checked_at=now)
                )
                if changed.rowcount != 1:
                    current = session.get(PlatformConnectionRecord, service_id)
                    raise HTTPException(
                        status_code=409,
                        detail={"code": "REVISION_CONFLICT", "current_revision": current.revision if current else 0},
                    )
                audit = MaintenanceRepairAuditRecord(
                    id=audit_id,
                    actor_id="platform-admin",
                    action=request.action,
                    service_id=service_id,
                    target_revision=current_revision,
                    result="pending",
                    details_json=json.dumps(
                        {"request_hash": request_hash, "result_revision": next_revision},
                        sort_keys=True,
                    ),
                    occurred_at=now,
                )
                session.add(audit)
                record_audit(
                    session,
                    action="maintenance.repair_confirmed",
                    target_type="platform-connection",
                    target_id=service_id,
                    payload={"action": request.action, "from_revision": current_revision, "to_revision": next_revision},
                )
            url_field, token_field = SERVICE_FIELDS[service_id]
            services.configure(
                services.settings.__class__(**{**services.settings.__dict__, url_field: url, token_field: token})
            )
    except HTTPException:
        with database.session() as session:
            previous = session.get(MaintenanceRepairAuditRecord, audit_id)
        if previous is not None and previous.details.get("request_hash") == request_hash:
            if previous.result in {"succeeded", "restored_unhealthy"}:
                return _repair_response_from_audit(previous)
            raise HTTPException(status_code=503, detail={"code": "REPAIR_RESULT_PENDING"})
        raise

    return _complete_repair_verification(
        database=database,
        services=services,
        service_id=service_id,
        url=url,
        token=token,
        audit_id=audit_id,
        request_hash=request_hash,
        result_revision=next_revision,
        replayed=False,
    )
