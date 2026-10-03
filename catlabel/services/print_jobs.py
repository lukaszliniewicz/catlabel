"""Durable immutable print plans and conservative job lifecycle tracking."""

# The artifact store deliberately exposes these methods as private: its pins
# must participate in the coordinator's existing SQL transaction.
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from threading import RLock
from typing import Any, cast

from sqlalchemy import UniqueConstraint, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Field, Session, SQLModel, col, select

from .artifacts import ArtifactError, ArtifactStore, _set_busy_timeout

_DEFAULT_PLAN_TTL_SECONDS = 900
_TERMINAL_RETENTION_SECONDS = 90 * 24 * 60 * 60
_UNCERTAIN_PIN_RETENTION_SECONDS = 7 * 24 * 60 * 60
_VALID_HASH = re.compile(r"[0-9a-f]{64}\Z")
_JOB_ACTIVE_STATES = ("accepted", "sending")
_JOB_TERMINAL_STATES = (
    "submitted",
    "failed_before_delivery",
    "cancelled_before_delivery",
    "delivery_uncertain",
)
_SERVICE_DETAIL_KEYS = (
    "code",
    "stage",
    "error_id",
    "error",
    "delivery_uncertain",
    "suggestion",
)


class JobError(Exception):
    """A stable, adapter-independent print-job operation error."""

    def __init__(
        self,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        self.details = {} if details is None else details
        super().__init__(message)


class PrintPlanRecord(SQLModel, table=True):
    """Canonical immutable manifest and its expiry fence."""

    id: str = Field(primary_key=True)
    plan_hash: str
    manifest_json: str
    created_at: float
    expires_at: float


class PrintJobRecord(SQLModel, table=True):
    """Idempotency reservation and durable print lifecycle receipt."""

    __table_args__ = (
        UniqueConstraint(
            "principal", "idempotency_key", name="uq_mcp_print_job_principal_key"
        ),
    )

    id: str = Field(primary_key=True)
    principal: str = Field(index=True)
    idempotency_key: str
    request_hash: str
    plan_id: str = Field(index=True)
    plan_hash: str
    manifest_json: str
    forensic_json: str = "{}"
    state: str = Field(index=True)
    created_at: float
    updated_at: float
    accepted_at: float
    sending_at: float | None = None
    completed_at: float | None = None
    uncertain_at: float | None = None
    attempt: int = 0
    error_stage: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    error_retryable: bool = False
    error_details_json: str | None = None
    receipt_json: str | None = None
    delivery_verification: str | None = None
    forensic_compacted: bool = False


def _canonical_json(value: Any, *, error_code: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError) as exc:
        raise JobError(error_code, "Value is not valid canonical JSON.") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _invalid_integer(
    value: object, *, minimum: int, maximum: int | None = None
) -> bool:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        return True
    return maximum is not None and value > maximum


def _begin_short_write(session: Session) -> None:
    """Serialize SQLite reservation reads before their unique-key insert."""
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _validate_uuid(value: object, *, code: str) -> str:
    if not isinstance(value, str):
        raise JobError(code, "Identifier is invalid.")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise JobError(code, "Identifier is invalid.") from None
    if normalized != value:
        raise JobError(code, "Identifier is invalid.")
    return normalized


class PrintJobCoordinator:
    """Own accepted executor tasks and persist all delivery-boundary states."""

    def __init__(
        self,
        db_engine: Engine,
        artifacts: ArtifactStore,
        executor: Callable[
            [dict[str, Any], Callable[[], Awaitable[None]]], Awaitable[dict[str, Any]]
        ],
        max_active: int = 4,
    ) -> None:
        if _invalid_integer(max_active, minimum=1, maximum=4):
            raise ValueError("max_active must be between 1 and 4")
        self._engine = db_engine
        self._artifacts = artifacts
        self._executor = executor
        self._max_active = max_active
        self._lock = RLock()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closing = False
        self._recover_on_startup()

    def create_plan(
        self,
        manifest: dict[str, Any],
        artifact_ids: list[str],
        ttl_seconds: int = _DEFAULT_PLAN_TTL_SECONDS,
    ) -> dict[str, Any]:
        """Freeze the manifest, source hashes and ownership in one plan record."""
        if "source_artifacts" in manifest:
            raise JobError(
                "invalid_plan", "source_artifacts is reserved for managed sources."
            )
        if _invalid_integer(ttl_seconds, minimum=1):
            raise JobError("invalid_plan", "Plan TTL must be a positive integer.")

        try:
            copied_manifest = cast(
                dict[str, Any],
                json.loads(_canonical_json(manifest, error_code="invalid_plan")),
            )
        except json.JSONDecodeError as exc:
            raise JobError("invalid_plan", "Plan manifest is invalid.") from exc

        source_ids: list[str] = []
        sources: list[dict[str, Any]] = []
        with self._artifacts._lock:
            try:
                for artifact_id in artifact_ids:
                    metadata = self._artifacts.get(artifact_id)
                    source_ids.append(metadata["id"])
                    sources.append(
                        {
                            "id": metadata["id"],
                            "sha256": metadata["sha256"],
                            "mime_type": metadata["mime_type"],
                            "size_bytes": metadata["size_bytes"],
                        }
                    )
            except ArtifactError as exc:
                raise self._from_artifact_error(exc) from exc

            copied_manifest["source_artifacts"] = sources
            manifest_json = _canonical_json(copied_manifest, error_code="invalid_plan")
            plan_hash = _sha256_text(manifest_json)
            plan_id = str(uuid.uuid4())
            created_at = time.time()
            record = PrintPlanRecord(
                id=plan_id,
                plan_hash=plan_hash,
                manifest_json=manifest_json,
                created_at=created_at,
                expires_at=created_at + ttl_seconds,
            )
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    _set_busy_timeout(session)
                    session.add(record)
                    self._artifacts._pin_in_session(
                        self._plan_owner(plan_id), source_ids, session
                    )
                    session.commit()
            except ArtifactError as exc:
                raise self._from_artifact_error(exc) from exc
            except OperationalError as exc:
                raise JobError(
                    "database_busy", "Plan storage is temporarily busy.", True
                ) from exc
        return self._plan_result(record, copied_manifest)

    def get_plan(
        self, plan_id: str, expected_hash: str | None = None
    ) -> dict[str, Any]:
        """Return an unexpired plan only after verifying its manifest and files."""
        plan_id = _validate_uuid(plan_id, code="invalid_plan_id")
        if expected_hash is not None:
            self._validate_hash(expected_hash, code="invalid_plan_hash")
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            record = session.get(PrintPlanRecord, plan_id)
        if record is None:
            raise JobError("plan_not_found", "Print plan was not found.")
        if record.expires_at <= time.time():
            raise JobError("plan_expired", "Print plan has expired.")
        try:
            raw_manifest = json.loads(record.manifest_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise JobError(
                "plan_content_invalid", "Print plan content is invalid."
            ) from exc
        if not isinstance(raw_manifest, dict):
            raise JobError("plan_content_invalid", "Print plan content is invalid.")
        manifest = cast(dict[str, Any], raw_manifest)
        if (
            _sha256_text(_canonical_json(manifest, error_code="plan_content_invalid"))
            != record.plan_hash
        ):
            raise JobError(
                "plan_hash_mismatch", "Print plan content failed verification."
            )
        if expected_hash is not None and expected_hash != record.plan_hash:
            raise JobError("plan_hash_mismatch", "Print plan hash does not match.")

        raw_sources: object = manifest.get("source_artifacts")
        if not isinstance(raw_sources, list):
            raise JobError(
                "plan_content_invalid", "Plan source references are invalid."
            )
        sources = cast(list[object], raw_sources)
        try:
            verified: dict[str, dict[str, Any]] = {}
            for source_value in sources:
                if not isinstance(source_value, dict):
                    raise JobError(
                        "plan_content_invalid", "Plan source references are invalid."
                    )
                source = cast(dict[str, Any], source_value)
                source_id: object = source.get("id")
                if not isinstance(source_id, str):
                    raise JobError(
                        "plan_content_invalid", "Plan source references are invalid."
                    )
                metadata = verified.get(source_id)
                if metadata is None:
                    metadata = self._artifacts.get(source_id)
                    verified[source_id] = metadata
                if any(
                    metadata.get(field) != source.get(field)
                    for field in ("id", "sha256", "mime_type", "size_bytes")
                ):
                    raise JobError(
                        "artifact_hash_mismatch",
                        "A plan source no longer matches its frozen identity.",
                    )
        except ArtifactError as exc:
            raise self._from_artifact_error(exc) from exc
        return self._plan_result(record, manifest)

    async def start(
        self,
        plan_id: str,
        expected_plan_hash: str,
        key: str,
        principal: str,
    ) -> dict[str, Any]:
        """Reserve one idempotent job, pin sources, and schedule owned work."""
        if self._closing:
            raise JobError("coordinator_closed", "Print job coordinator is closing.")
        plan_id = _validate_uuid(plan_id, code="invalid_plan_id")
        self._validate_hash(expected_plan_hash, code="invalid_plan_hash")
        self._validate_key(key)
        self._validate_principal(principal)

        existing = self._find_by_key(principal, key)
        if existing is not None:
            return self._same_key_result(existing, plan_id, expected_plan_hash)

        plan = self.get_plan(plan_id, expected_plan_hash)
        manifest = cast(dict[str, Any], plan["manifest"])
        request_hash = _sha256_text(
            _canonical_json(
                {
                    "plan_id": plan_id,
                    "expected_plan_hash": expected_plan_hash,
                    "manifest": manifest,
                },
                error_code="invalid_plan",
            )
        )
        manifest_json = _canonical_json(manifest, error_code="plan_content_invalid")
        source_ids = [source["id"] for source in manifest["source_artifacts"]]

        with self._lock, self._artifacts._lock:
            record: PrintJobRecord | None = None
            was_existing = False
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    _set_busy_timeout(session)
                    _begin_short_write(session)
                    winner = self._job_by_key(session, principal, key)
                    if winner is not None:
                        record = winner
                        was_existing = True
                    else:
                        current_plan = session.get(PrintPlanRecord, plan_id)
                        now = time.time()
                        if current_plan is None or current_plan.expires_at <= now:
                            raise JobError(
                                "plan_expired", "Print plan has expired or was removed."
                            )
                        if (
                            current_plan.plan_hash != expected_plan_hash
                            or current_plan.manifest_json != manifest_json
                        ):
                            raise JobError(
                                "plan_hash_mismatch",
                                "Print plan changed during job reservation.",
                            )
                        record = PrintJobRecord(
                            id=str(uuid.uuid4()),
                            principal=principal,
                            idempotency_key=key,
                            request_hash=request_hash,
                            plan_id=plan_id,
                            plan_hash=expected_plan_hash,
                            manifest_json=manifest_json,
                            state="accepted",
                            created_at=now,
                            updated_at=now,
                            accepted_at=now,
                            attempt=0,
                        )
                        session.add(record)
                        self._artifacts._pin_in_session(
                            self._job_owner(record.id), source_ids, session
                        )
                        session.commit()
            except ArtifactError as exc:
                raise self._from_artifact_error(exc) from exc
            except IntegrityError:
                # The unique principal/key reservation is authoritative across
                # simultaneous requests, including separate coordinator objects.
                winner = self._find_by_key(principal, key)
                if winner is None:
                    raise JobError(
                        "database_busy", "Job reservation is temporarily busy.", True
                    ) from None
                return self._same_key_result(winner, plan_id, expected_plan_hash)
            except OperationalError as exc:
                raise JobError(
                    "database_busy", "Job reservation is temporarily busy.", True
                ) from exc

            assert record is not None
            if record.plan_id != plan_id or record.plan_hash != expected_plan_hash:
                return self._same_key_result(record, plan_id, expected_plan_hash)
            if was_existing:
                return self._job_result(record)

            active = sum(not task.done() for task in self._tasks.values())
            if active >= self._max_active:
                self._fail_before_delivery(
                    record.id,
                    code="printer_busy",
                    message="Print admission is busy; start a new key to retry.",
                    stage="admission",
                    retryable=True,
                )
                updated = self._get_job(record.id)
                return self._job_result(updated)

            try:
                task = asyncio.create_task(
                    self._run_job(record.id, manifest),
                    name=f"catlabel-print-{record.id}",
                )
            except RuntimeError as exc:
                self._fail_before_delivery(
                    record.id,
                    code="job_schedule_failed",
                    message="Print job could not be scheduled.",
                    stage="scheduling",
                    retryable=True,
                )
                raise JobError(
                    "job_schedule_failed",
                    "Print job could not be scheduled.",
                    True,
                    {"job_id": record.id},
                ) from exc
            self._tasks[record.id] = task
            task.add_done_callback(
                lambda completed, job_id=record.id: self._discard_task(
                    job_id, completed
                )
            )
            return self._job_result(record)

    def job_get(self, job_id: str, principal: str) -> dict[str, Any]:
        job_id = _validate_uuid(job_id, code="invalid_job_id")
        self._validate_principal(principal)
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            record = session.exec(
                select(PrintJobRecord).where(
                    col(PrintJobRecord.id) == job_id,
                    col(PrintJobRecord.principal) == principal,
                )
            ).first()
        if record is None:
            raise JobError("job_not_found", "Print job was not found.")
        return self._job_result(record)

    def jobs_list(
        self, principal: str, limit: int = 50, after_id: str | None = None
    ) -> dict[str, Any]:
        self._validate_principal(principal)
        if _invalid_integer(limit, minimum=1, maximum=100):
            raise JobError("invalid_limit", "Job list limit must be between 1 and 100.")
        if after_id is not None:
            after_id = _validate_uuid(after_id, code="invalid_after_id")
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            query = select(PrintJobRecord).where(
                col(PrintJobRecord.principal) == principal
            )
            if after_id is not None:
                query = query.where(col(PrintJobRecord.id) > after_id)
            rows = session.exec(
                query.order_by(col(PrintJobRecord.id)).limit(limit + 1)
            ).all()
        has_more = len(rows) > limit
        visible = rows[:limit]
        next_after_id = visible[-1].id if has_more and visible else None
        return {
            "jobs": [self._job_result(record) for record in visible],
            "next_after_id": next_after_id,
        }

    async def cancel(self, job_id: str, principal: str) -> dict[str, Any]:
        job_id = _validate_uuid(job_id, code="invalid_job_id")
        self._validate_principal(principal)
        now = time.time()
        changed = 0
        try:
            with (
                self._artifacts._lock,
                Session(self._engine, expire_on_commit=False) as session,
            ):
                _set_busy_timeout(session)
                result = session.exec(
                    update(PrintJobRecord)
                    .where(
                        col(PrintJobRecord.id) == job_id,
                        col(PrintJobRecord.principal) == principal,
                        col(PrintJobRecord.state) == "accepted",
                    )
                    .values(
                        state="cancelled_before_delivery",
                        updated_at=now,
                        completed_at=now,
                        error_stage="cancellation",
                        error_code="cancelled_before_delivery",
                        error_message="Job was cancelled before delivery started.",
                        error_retryable=False,
                        error_details_json=None,
                    )
                    .execution_options(synchronize_session=False)
                )
                changed = result.rowcount or 0
                if changed == 1:
                    self._artifacts._unpin_in_session(self._job_owner(job_id), session)
                session.commit()
        except OperationalError as exc:
            raise JobError(
                "database_busy", "Cancellation is temporarily blocked.", True
            ) from exc

        record = self._get_job_for_principal(job_id, principal)
        if record is None:
            raise JobError("job_not_found", "Print job was not found.")
        if changed == 1:
            return self._job_result(record)
        raise JobError(
            "cancel_not_supported_after_delivery_started",
            "Cancellation is unavailable for the current job state.",
            False,
            {"job_id": job_id, "state": record.state},
        )

    def reap(self) -> dict[str, int]:
        """Apply durable plan, job-receipt and uncertain-pin retention rules."""
        now = time.time()
        expired_plans = 0
        compacted_uncertain = 0
        removed_jobs = 0
        with (
            self._lock,
            self._artifacts._lock,
            Session(self._engine, expire_on_commit=False) as session,
        ):
            _set_busy_timeout(session)
            plans = session.exec(
                select(PrintPlanRecord).where(col(PrintPlanRecord.expires_at) <= now)
            ).all()
            for plan in plans:
                self._artifacts._unpin_in_session(self._plan_owner(plan.id), session)
                session.delete(plan)
                expired_plans += 1

            uncertain = session.exec(
                select(PrintJobRecord).where(
                    col(PrintJobRecord.state) == "delivery_uncertain",
                    col(PrintJobRecord.uncertain_at)
                    <= now - _UNCERTAIN_PIN_RETENTION_SECONDS,
                    col(PrintJobRecord.forensic_compacted).is_(False),
                )
            ).all()
            for record in uncertain:
                manifest = self._decode_manifest(record.manifest_json)
                sources = manifest.get("source_artifacts", [])
                self._artifacts._unpin_in_session(self._job_owner(record.id), session)
                record.forensic_json = _canonical_json(
                    {
                        "plan_hash": record.plan_hash,
                        "source_artifacts": sources,
                        "error": self._error_value(record),
                    },
                    error_code="job_content_invalid",
                )
                record.manifest_json = "{}"
                record.forensic_compacted = True
                record.updated_at = now
                compacted_uncertain += 1

            old_terminal = session.exec(
                select(PrintJobRecord).where(
                    col(PrintJobRecord.state).in_(_JOB_TERMINAL_STATES),
                    col(PrintJobRecord.completed_at)
                    <= now - _TERMINAL_RETENTION_SECONDS,
                )
            ).all()
            for record in old_terminal:
                self._artifacts._unpin_in_session(self._job_owner(record.id), session)
                session.delete(record)
                removed_jobs += 1
            session.commit()
        return {
            "expired_plans": expired_plans,
            "compacted_uncertain_jobs": compacted_uncertain,
            "removed_jobs": removed_jobs,
        }

    async def close(self) -> None:
        """Boundedly drain owned tasks, marking any interrupted delivery safely."""
        self._closing = True
        tasks = [task for task in self._tasks.values() if not task.done()]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=1.0)
        if pending:
            for task in pending:
                task.cancel()
            _, pending = await asyncio.wait(pending, timeout=1.0)
        if pending:
            self._mark_interrupted(
                [job_id for job_id, task in self._tasks.items() if task in pending]
            )

    async def _run_job(self, job_id: str, manifest: dict[str, Any]) -> None:
        boundary_crossed = False

        async def before_delivery() -> None:
            nonlocal boundary_crossed
            if boundary_crossed:
                raise JobError(
                    "delivery_boundary_already_crossed",
                    "The delivery boundary can only be crossed once.",
                )
            self._mark_sending(job_id)
            boundary_crossed = True

        try:
            receipt = await self._executor(manifest, before_delivery)
            receipt_json = _canonical_json(
                receipt, error_code="invalid_executor_receipt"
            )
            if not boundary_crossed:
                self._fail_before_delivery(
                    job_id,
                    code="executor_skipped_delivery_boundary",
                    message="Executor returned before recording delivery start.",
                    stage="executor",
                )
                return
            try:
                self._mark_submitted(job_id, receipt_json)
            except JobError:
                self._mark_uncertain(
                    job_id,
                    code="receipt_persist_failed",
                    message="Submission completed but its receipt could not be persisted.",
                    stage="receipt",
                )
        except asyncio.CancelledError:
            self._settle_cancelled(job_id)
            raise
        except Exception as exc:
            state = self._get_state(job_id)
            if state == "sending" or boundary_crossed:
                code, message, retryable, details, service_stage = (
                    self._exception_fields(exc)
                )
                if details is not None and "status_code" in details:
                    details["delivery_uncertain"] = True
                self._mark_uncertain(
                    job_id,
                    code=code,
                    message=message,
                    stage=service_stage or "executor_after_delivery_started",
                    retryable=retryable,
                    details=details,
                )
            elif state == "accepted":
                code, message, retryable, details, service_stage = (
                    self._exception_fields(exc)
                )
                self._fail_before_delivery(
                    job_id,
                    code=code,
                    message=message,
                    stage=service_stage or "executor_before_delivery",
                    retryable=retryable,
                    details=details,
                )

    def _mark_sending(self, job_id: str) -> None:
        now = time.time()
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                _set_busy_timeout(session)
                result = session.exec(
                    update(PrintJobRecord)
                    .where(
                        col(PrintJobRecord.id) == job_id,
                        col(PrintJobRecord.state) == "accepted",
                    )
                    .values(
                        state="sending",
                        sending_at=now,
                        updated_at=now,
                        attempt=1,
                    )
                    .execution_options(synchronize_session=False)
                )
                changed = result.rowcount or 0
                session.commit()
        except OperationalError as exc:
            raise JobError(
                "database_busy", "Delivery boundary could not be persisted.", True
            ) from exc
        if changed != 1:
            record = self._get_job(job_id)
            raise JobError(
                "job_state_conflict",
                "Job is no longer accepted for delivery.",
                False,
                {"state": record.state},
            )

    def _mark_submitted(self, job_id: str, receipt_json: str) -> None:
        now = time.time()
        try:
            with (
                self._artifacts._lock,
                Session(self._engine, expire_on_commit=False) as session,
            ):
                _set_busy_timeout(session)
                result = session.exec(
                    update(PrintJobRecord)
                    .where(
                        col(PrintJobRecord.id) == job_id,
                        col(PrintJobRecord.state) == "sending",
                    )
                    .values(
                        state="submitted",
                        manifest_json="{}",
                        updated_at=now,
                        completed_at=now,
                        error_stage=None,
                        error_code=None,
                        error_message=None,
                        error_retryable=False,
                        error_details_json=None,
                        receipt_json=receipt_json,
                        delivery_verification="unverified",
                    )
                    .execution_options(synchronize_session=False)
                )
                if (result.rowcount or 0) == 1:
                    self._artifacts._unpin_in_session(self._job_owner(job_id), session)
                session.commit()
        except OperationalError as exc:
            raise JobError(
                "database_busy", "Submission receipt could not be persisted.", True
            ) from exc

    def _fail_before_delivery(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        stage: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with (
            self._artifacts._lock,
            Session(self._engine, expire_on_commit=False) as session,
        ):
            _set_busy_timeout(session)
            result = session.exec(
                update(PrintJobRecord)
                .where(
                    col(PrintJobRecord.id) == job_id,
                    col(PrintJobRecord.state) == "accepted",
                )
                .values(
                    state="failed_before_delivery",
                    manifest_json="{}",
                    updated_at=now,
                    completed_at=now,
                    error_stage=stage,
                    error_code=code,
                    error_message=message[:500],
                    error_retryable=retryable,
                    error_details_json=self._encode_details(details),
                )
                .execution_options(synchronize_session=False)
            )
            if (result.rowcount or 0) == 1:
                self._artifacts._unpin_in_session(self._job_owner(job_id), session)
            session.commit()

    def _mark_cancelled_before_delivery(
        self, job_id: str, *, code: str, message: str, stage: str
    ) -> None:
        now = time.time()
        with (
            self._artifacts._lock,
            Session(self._engine, expire_on_commit=False) as session,
        ):
            _set_busy_timeout(session)
            result = session.exec(
                update(PrintJobRecord)
                .where(
                    col(PrintJobRecord.id) == job_id,
                    col(PrintJobRecord.state) == "accepted",
                )
                .values(
                    state="cancelled_before_delivery",
                    manifest_json="{}",
                    updated_at=now,
                    completed_at=now,
                    error_stage=stage,
                    error_code=code,
                    error_message=message[:500],
                    error_retryable=False,
                    error_details_json=None,
                )
                .execution_options(synchronize_session=False)
            )
            if (result.rowcount or 0) == 1:
                self._artifacts._unpin_in_session(self._job_owner(job_id), session)
            session.commit()

    def _mark_uncertain(
        self,
        job_id: str,
        *,
        code: str,
        message: str,
        stage: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            session.exec(
                update(PrintJobRecord)
                .where(
                    col(PrintJobRecord.id) == job_id,
                    col(PrintJobRecord.state) == "sending",
                )
                .values(
                    state="delivery_uncertain",
                    updated_at=now,
                    completed_at=now,
                    uncertain_at=now,
                    error_stage=stage,
                    error_code=code,
                    error_message=message[:500],
                    error_retryable=retryable,
                    error_details_json=self._encode_details(details),
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()

    def _settle_cancelled(self, job_id: str) -> None:
        state = self._get_state(job_id)
        if state == "accepted":
            self._mark_cancelled_before_delivery(
                job_id,
                code="cancelled_before_delivery",
                message="Job was interrupted before delivery started.",
                stage="shutdown",
            )
        elif state == "sending":
            self._mark_uncertain(
                job_id,
                code="delivery_interrupted",
                message="Job was interrupted after delivery started.",
                stage="shutdown_after_delivery_started",
                retryable=True,
            )

    def _mark_interrupted(self, job_ids: list[str]) -> None:
        if not job_ids:
            return
        now = time.time()
        with (
            self._artifacts._lock,
            Session(self._engine, expire_on_commit=False) as session,
        ):
            _set_busy_timeout(session)
            accepted = session.exec(
                select(PrintJobRecord.id).where(
                    col(PrintJobRecord.id).in_(job_ids),
                    col(PrintJobRecord.state) == "accepted",
                )
            ).all()
            session.exec(
                update(PrintJobRecord)
                .where(
                    col(PrintJobRecord.id).in_(job_ids),
                    col(PrintJobRecord.state) == "accepted",
                )
                .values(
                    state="cancelled_before_delivery",
                    manifest_json="{}",
                    updated_at=now,
                    completed_at=now,
                    error_stage="shutdown",
                    error_code="cancelled_before_delivery",
                    error_message="Job was interrupted before delivery started.",
                )
                .execution_options(synchronize_session=False)
            )
            session.exec(
                update(PrintJobRecord)
                .where(
                    col(PrintJobRecord.id).in_(job_ids),
                    col(PrintJobRecord.state) == "sending",
                )
                .values(
                    state="delivery_uncertain",
                    updated_at=now,
                    completed_at=now,
                    uncertain_at=now,
                    error_stage="shutdown_after_delivery_started",
                    error_code="delivery_interrupted",
                    error_message="Job was interrupted after delivery started.",
                    error_retryable=True,
                )
                .execution_options(synchronize_session=False)
            )
            for job_id in accepted:
                self._artifacts._unpin_in_session(self._job_owner(job_id), session)
            session.commit()

    def _recover_on_startup(self) -> None:
        now = time.time()
        with (
            self._artifacts._lock,
            Session(self._engine, expire_on_commit=False) as session,
        ):
            _set_busy_timeout(session)
            accepted = session.exec(
                select(PrintJobRecord.id).where(col(PrintJobRecord.state) == "accepted")
            ).all()
            session.exec(
                update(PrintJobRecord)
                .where(col(PrintJobRecord.state) == "accepted")
                .values(
                    state="cancelled_before_delivery",
                    manifest_json="{}",
                    updated_at=now,
                    completed_at=now,
                    error_stage="startup_recovery",
                    error_code="process_restarted_before_delivery",
                    error_message="Accepted job was cancelled during restart recovery.",
                )
                .execution_options(synchronize_session=False)
            )
            session.exec(
                update(PrintJobRecord)
                .where(col(PrintJobRecord.state) == "sending")
                .values(
                    state="delivery_uncertain",
                    updated_at=now,
                    completed_at=now,
                    uncertain_at=now,
                    error_stage="startup_recovery_after_delivery_started",
                    error_code="process_interrupted_during_delivery",
                    error_message="Delivery was interrupted; automatic replay is disabled.",
                    error_retryable=False,
                )
                .execution_options(synchronize_session=False)
            )
            for job_id in accepted:
                self._artifacts._unpin_in_session(self._job_owner(job_id), session)
            session.commit()

    def _find_by_key(self, principal: str, key: str) -> PrintJobRecord | None:
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            return self._job_by_key(session, principal, key)

    @staticmethod
    def _job_by_key(
        session: Session, principal: str, key: str
    ) -> PrintJobRecord | None:
        return session.exec(
            select(PrintJobRecord).where(
                col(PrintJobRecord.principal) == principal,
                col(PrintJobRecord.idempotency_key) == key,
            )
        ).first()

    def _same_key_result(
        self, record: PrintJobRecord, plan_id: str, expected_plan_hash: str
    ) -> dict[str, Any]:
        if record.plan_id != plan_id or record.plan_hash != expected_plan_hash:
            raise JobError(
                "idempotency_conflict",
                "Idempotency key was already used for a different print request.",
                False,
                {"job_id": record.id},
            )
        return self._job_result(record)

    def _get_job(self, job_id: str) -> PrintJobRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            record = session.get(PrintJobRecord, job_id)
        if record is None:
            raise JobError("job_not_found", "Print job was not found.")
        return record

    def _get_job_for_principal(
        self, job_id: str, principal: str
    ) -> PrintJobRecord | None:
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            return session.exec(
                select(PrintJobRecord).where(
                    col(PrintJobRecord.id) == job_id,
                    col(PrintJobRecord.principal) == principal,
                )
            ).first()

    def _get_state(self, job_id: str) -> str | None:
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            return session.exec(
                select(PrintJobRecord.state).where(col(PrintJobRecord.id) == job_id)
            ).first()

    def _discard_task(self, job_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(job_id) is task:
            self._tasks.pop(job_id, None)

    @staticmethod
    def _plan_result(
        record: PrintPlanRecord, manifest: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "id": record.id,
            "plan_hash": record.plan_hash,
            "expires_at": record.expires_at,
            "manifest": manifest,
        }

    @staticmethod
    def _error_value(record: PrintJobRecord) -> dict[str, Any] | None:
        if record.error_code is None:
            return None
        details: dict[str, Any] = {}
        if record.error_details_json:
            try:
                parsed = json.loads(record.error_details_json)
                if isinstance(parsed, dict):
                    details = cast(dict[str, Any], parsed)
            except json.JSONDecodeError:
                pass
        return {
            "code": record.error_code,
            "message": record.error_message or "Print job failed.",
            "stage": record.error_stage,
            "retryable": record.error_retryable,
            "details": details,
        }

    @classmethod
    def _job_result(cls, record: PrintJobRecord) -> dict[str, Any]:
        receipt: dict[str, Any] | None = None
        if record.receipt_json:
            try:
                parsed = json.loads(record.receipt_json)
                if isinstance(parsed, dict):
                    receipt = cast(dict[str, Any], parsed)
            except json.JSONDecodeError:
                receipt = None
        return {
            "id": record.id,
            "state": record.state,
            "plan_id": record.plan_id,
            "plan_hash": record.plan_hash,
            "created_at": record.created_at,
            "updated_at": record.updated_at,
            "accepted_at": record.accepted_at,
            "sending_at": record.sending_at,
            "completed_at": record.completed_at,
            "attempt": record.attempt,
            "error": cls._error_value(record),
            "receipt": receipt,
            "delivery_verification": record.delivery_verification,
            "forensic": cast(dict[str, Any], json.loads(record.forensic_json)),
        }

    @staticmethod
    def _decode_manifest(value: str) -> dict[str, Any]:
        try:
            manifest = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return cast(dict[str, Any], manifest) if isinstance(manifest, dict) else {}

    @staticmethod
    def _encode_details(details: dict[str, Any] | None) -> str | None:
        if details is None:
            return None
        try:
            encoded = _canonical_json(details, error_code="invalid_job_error")
        except JobError:
            return None
        if len(encoded) > 4_096:
            return None
        return encoded

    @staticmethod
    def _exception_fields(
        exc: Exception,
    ) -> tuple[str, str, bool, dict[str, Any] | None, str | None]:
        if isinstance(exc, JobError):
            return exc.code, exc.message, exc.retryable, exc.details, None
        status_code: object = getattr(exc, "status_code", None)
        detail: object = getattr(exc, "detail", None)
        if (
            isinstance(status_code, int)
            and not isinstance(status_code, bool)
            and 100 <= status_code <= 599
        ):
            safe_details: dict[str, Any] = {"status_code": status_code}
            service_stage: str | None = None
            message = "Print service failed."
            code = "print_service_error"
            retryable = status_code >= 500
            if isinstance(detail, dict):
                fields = cast(dict[str, Any], detail)
                raw_message = fields.get("message")
                if isinstance(raw_message, str) and raw_message:
                    message = raw_message[:500]
                raw_stage = fields.get("stage")
                if isinstance(raw_stage, str) and raw_stage:
                    service_stage = raw_stage[:100]
                raw_code = fields.get("code")
                if isinstance(raw_code, str) and raw_code:
                    code = raw_code[:100]
                raw_retryable = fields.get("retryable")
                if isinstance(raw_retryable, bool):
                    retryable = raw_retryable
                for key in _SERVICE_DETAIL_KEYS:
                    value = fields.get(key)
                    if isinstance(value, str):
                        safe_details[key] = value[:500]
                    elif isinstance(value, (bool, int, float)) or value is None:
                        safe_details[key] = value
            elif isinstance(detail, str) and detail:
                message = detail[:500]
                safe_details["detail"] = message
            if status_code == 409 and service_stage == "admission":
                code = "printer_busy"
                retryable = True
            return code, message, retryable, safe_details, service_stage
        # Arbitrary executor messages may contain local device or credential data.
        return (
            "executor_failed",
            "Print executor failed.",
            False,
            {"exception_type": type(exc).__name__},
            None,
        )

    @staticmethod
    def _from_artifact_error(exc: ArtifactError) -> JobError:
        return JobError(exc.code, exc.message, exc.retryable)

    @staticmethod
    def _validate_hash(value: object, *, code: str) -> None:
        if not isinstance(value, str) or _VALID_HASH.fullmatch(value) is None:
            raise JobError(code, "SHA-256 value is invalid.")

    @staticmethod
    def _validate_key(value: object) -> None:
        if not isinstance(value, str) or not 1 <= len(value) <= 128:
            raise JobError(
                "invalid_idempotency_key", "Idempotency key must be 1–128 characters."
            )

    @staticmethod
    def _validate_principal(value: object) -> None:
        if not isinstance(value, str) or not 1 <= len(value) <= 255:
            raise JobError("invalid_principal", "Principal identifier is invalid.")

    @staticmethod
    def _plan_owner(plan_id: str) -> str:
        return f"plan:{plan_id}"

    @staticmethod
    def _job_owner(job_id: str) -> str:
        return f"job:{job_id}"
