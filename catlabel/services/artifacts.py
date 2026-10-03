"""Persistent, bounded storage for immutable MCP artifacts."""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
import uuid
from contextlib import suppress
from pathlib import Path
from threading import RLock
from typing import Any, cast

from sqlalchemy import delete, or_
from sqlalchemy.engine import Engine
from sqlmodel import Field, Session, SQLModel, col, select

_DEFAULT_QUOTA_BYTES = 1024 * 1024 * 1024
_BUSY_TIMEOUT_MS = 5_000
_STARTUP_CLEANUP_LIMIT = 1_000
_UUID_PATTERN = r"[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}"
_ARTIFACT_FILE_RE = re.compile(rf"({_UUID_PATTERN})\.blob\Z")
_TEMP_FILE_RE = re.compile(rf"\.({_UUID_PATTERN})\.tmp\Z")


class ArtifactError(Exception):
    """A stable, adapter-independent artifact operation error."""

    def __init__(self, code: str, message: str, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


class ArtifactRecord(SQLModel, table=True):
    """Metadata for one opaque artifact identifier."""

    id: str = Field(primary_key=True)
    sha256: str
    mime_type: str
    kind: str
    size_bytes: int
    created_at: float
    expires_at: float


class ArtifactPin(SQLModel, table=True):
    """Durable ownership that prevents TTL cleanup of an artifact."""

    owner: str = Field(primary_key=True)
    artifact_id: str = Field(primary_key=True, index=True)
    expires_at: float | None = None


def _set_busy_timeout(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        connection.exec_driver_sql(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")


def _strict_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ArtifactError("invalid_artifact_id", "Artifact ID is invalid.")
    try:
        normalized = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        raise ArtifactError("invalid_artifact_id", "Artifact ID is invalid.") from None
    if normalized != value:
        raise ArtifactError("invalid_artifact_id", "Artifact ID is invalid.")
    return normalized


def _invalid_integer(value: object, *, minimum: int) -> bool:
    return isinstance(value, bool) or not isinstance(value, int) or value < minimum


class ArtifactStore:
    """Atomically store and verify artifacts beneath one managed directory."""

    def __init__(
        self,
        db_engine: Engine,
        root: Path,
        quota_bytes: int = _DEFAULT_QUOTA_BYTES,
    ) -> None:
        if _invalid_integer(quota_bytes, minimum=1):
            raise ValueError("quota_bytes must be an integer")
        self._engine = db_engine
        self._root = Path(root)
        self._quota_bytes = quota_bytes
        self._lock = RLock()
        self._closed = False
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self._root.is_dir():
            raise ValueError("artifact root must be a directory")
        self._cleanup_startup_orphans()

    def put_bytes(
        self,
        data: bytes,
        *,
        mime_type: str,
        kind: str,
        ttl_seconds: int = 86_400,
    ) -> dict[str, Any]:
        """Install bytes atomically, then persist their metadata."""
        self._ensure_open()
        if not mime_type or len(mime_type) > 255:
            raise ArtifactError("invalid_artifact", "MIME type is invalid.")
        if not kind or len(kind) > 128:
            raise ArtifactError("invalid_artifact", "Artifact kind is invalid.")
        if _invalid_integer(ttl_seconds, minimum=0):
            raise ArtifactError("invalid_artifact", "Artifact TTL is invalid.")

        size_bytes = len(data)
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = str(uuid.uuid4())
        final_path = self._path(artifact_id)
        temporary_path = self._root / f".{artifact_id}.tmp"
        now = time.time()
        record = ArtifactRecord(
            id=artifact_id,
            sha256=digest,
            mime_type=mime_type,
            kind=kind,
            size_bytes=size_bytes,
            created_at=now,
            expires_at=now + ttl_seconds,
        )

        with self._lock:
            self._ensure_open()
            with Session(self._engine, expire_on_commit=False) as session:
                _set_busy_timeout(session)
                used_bytes = session.exec(select(ArtifactRecord.size_bytes)).all()
            used = sum(used_bytes)
            if used + size_bytes > self._quota_bytes:
                raise ArtifactError(
                    "artifact_quota_exceeded",
                    "Managed artifact storage quota would be exceeded.",
                )

            self._write_atomic(temporary_path, final_path, data)
            try:
                with Session(self._engine, expire_on_commit=False) as session:
                    _set_busy_timeout(session)
                    session.add(record)
                    session.commit()
            except Exception:
                # A failed commit can have an ambiguous outcome. Leave the file
                # for startup reconciliation instead of risking a missing blob.
                raise
        return self._metadata(record)

    def read_bytes(self, artifact_id: str) -> bytes:
        """Read one artifact and reject missing or hash-mismatched content."""
        record = self._load_record(artifact_id)
        path = self._path(record.id)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise ArtifactError(
                "artifact_missing", "Artifact content is unavailable."
            ) from exc
        if (
            len(data) != record.size_bytes
            or hashlib.sha256(data).hexdigest() != record.sha256
        ):
            raise ArtifactError(
                "artifact_hash_mismatch",
                "Artifact content failed integrity verification.",
            )
        return data

    def get(self, artifact_id: str) -> dict[str, Any]:
        """Return verified metadata without exposing a filesystem path."""
        record = self._load_record(artifact_id)
        self._verify_file(record)
        return self._metadata(record)

    def pin(
        self,
        owner: str,
        artifact_ids: list[str],
        *,
        expires_at: float | None = None,
    ) -> None:
        """Replace an owner's artifact set in one short database transaction."""
        self._ensure_open()
        with self._lock, Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            self._pin_in_session(owner, artifact_ids, session, expires_at=expires_at)
            session.commit()

    def unpin(self, owner: str) -> None:
        """Release every artifact owned by one stable owner identifier."""
        self._ensure_open()
        with self._lock, Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            self._unpin_in_session(owner, session)
            session.commit()

    def reap(self) -> int:
        """Delete expired, unpinned records and then their files."""
        self._ensure_open()
        now = time.time()
        removed: list[str] = []
        with self._lock:
            with Session(self._engine, expire_on_commit=False) as session:
                _set_busy_timeout(session)
                session.exec(
                    delete(ArtifactPin).where(
                        col(ArtifactPin.expires_at).is_not(None),
                        col(ArtifactPin.expires_at) <= now,
                    )
                )
                session.commit()
            while True:
                with Session(self._engine, expire_on_commit=False) as session:
                    _set_busy_timeout(session)
                    pinned = select(ArtifactPin.artifact_id).where(
                        col(ArtifactPin.artifact_id) == ArtifactRecord.id,
                        or_(
                            col(ArtifactPin.expires_at).is_(None),
                            col(ArtifactPin.expires_at) > now,
                        ),
                    )
                    expired_ids = session.exec(
                        select(ArtifactRecord)
                        .where(
                            col(ArtifactRecord.expires_at) <= now,
                            ~pinned.exists(),
                        )
                        .order_by(col(ArtifactRecord.expires_at))
                        .limit(500)
                    ).all()
                    candidate_ids = [record.id for record in expired_ids]
                if not candidate_ids:
                    break
                with Session(self._engine, expire_on_commit=False) as session:
                    _set_busy_timeout(session)
                    deleted_ids = self._delete_expired_candidates(
                        session, candidate_ids, now
                    )
                    session.commit()
                if not deleted_ids:
                    # A concurrent owner may have pinned every selected row.
                    # Query again so any other eligible rows can still be reaped.
                    continue
                removed.extend(deleted_ids)

            for artifact_id in removed:
                try:
                    self._path(artifact_id).unlink(missing_ok=True)
                except OSError:
                    # Database ownership is already gone; startup orphan cleanup
                    # will retry this bounded file removal later.
                    continue
        return len(removed)

    @staticmethod
    def _delete_expired_candidates(
        session: Session, artifact_ids: list[str], now: float
    ) -> list[str]:
        live_pins = select(ArtifactPin.artifact_id).where(
            col(ArtifactPin.artifact_id) == ArtifactRecord.id,
            or_(
                col(ArtifactPin.expires_at).is_(None),
                col(ArtifactPin.expires_at) > now,
            ),
        )
        result = session.exec(
            delete(ArtifactRecord)
            .where(
                col(ArtifactRecord.id).in_(artifact_ids),
                col(ArtifactRecord.expires_at) <= now,
                ~live_pins.exists(),
            )
            .returning(col(ArtifactRecord.id))
        )
        return list(result.scalars().all())

    def close(self) -> None:
        """Close the lightweight store; the shared Engine remains app-owned."""
        with self._lock:
            self._closed = True

    def _pin_in_session(
        self,
        owner: str,
        artifact_ids: list[str],
        session: Session,
        *,
        expires_at: float | None = None,
    ) -> None:
        """Set ownership within a caller's existing SQLModel transaction."""
        self._validate_owner(owner)
        raw_expires_at: object = expires_at
        if expires_at is not None and (
            isinstance(raw_expires_at, bool)
            or not isinstance(raw_expires_at, (int, float))
            or not math.isfinite(raw_expires_at)
        ):
            raise ArtifactError(
                "invalid_artifact_owner", "Artifact owner expiry is invalid."
            )
        normalized = list(dict.fromkeys(_strict_uuid(item) for item in artifact_ids))
        if normalized:
            found = set(
                session.exec(
                    select(ArtifactRecord.id).where(
                        col(ArtifactRecord.id).in_(normalized)
                    )
                ).all()
            )
            missing = [item for item in normalized if item not in found]
            if missing:
                raise ArtifactError("artifact_not_found", "Artifact was not found.")

        session.exec(delete(ArtifactPin).where(col(ArtifactPin.owner) == owner))
        session.add_all(
            ArtifactPin(
                owner=owner,
                artifact_id=artifact_id,
                expires_at=None if expires_at is None else float(expires_at),
            )
            for artifact_id in normalized
        )

    def _unpin_in_session(self, owner: str, session: Session) -> None:
        """Remove one owner's pins inside a caller's existing transaction."""
        self._validate_owner(owner)
        session.exec(delete(ArtifactPin).where(col(ArtifactPin.owner) == owner))

    def _load_record(self, artifact_id: str) -> ArtifactRecord:
        self._ensure_open()
        normalized = _strict_uuid(artifact_id)
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            record = session.get(ArtifactRecord, normalized)
        if record is None:
            raise ArtifactError("artifact_not_found", "Artifact was not found.")
        return record

    def _verify_file(self, record: ArtifactRecord) -> None:
        digest = hashlib.sha256()
        size_bytes = 0
        try:
            with self._path(record.id).open("rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
                    size_bytes += len(chunk)
        except OSError as exc:
            raise ArtifactError(
                "artifact_missing", "Artifact content is unavailable."
            ) from exc
        if size_bytes != record.size_bytes or digest.hexdigest() != record.sha256:
            raise ArtifactError(
                "artifact_hash_mismatch",
                "Artifact content failed integrity verification.",
            )

    def _path(self, artifact_id: str) -> Path:
        return self._root / f"{_strict_uuid(artifact_id)}.blob"

    def _write_atomic(
        self, temporary_path: Path, final_path: Path, data: bytes
    ) -> None:
        try:
            descriptor = os.open(
                temporary_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, final_path)
            directory_flag = getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(self._root, os.O_RDONLY | directory_flag)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
            raise ArtifactError(
                "artifact_write_failed", "Artifact content could not be stored.", True
            ) from exc

    def _cleanup_startup_orphans(self) -> None:
        candidates: list[tuple[str, str]] = []
        try:
            with os.scandir(self._root) as entries:
                for entry in entries:
                    if len(candidates) >= _STARTUP_CLEANUP_LIMIT:
                        break
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    temp_match = _TEMP_FILE_RE.fullmatch(entry.name)
                    if temp_match:
                        candidates.append(("temp", temp_match.group(1)))
                        continue
                    artifact_match = _ARTIFACT_FILE_RE.fullmatch(entry.name)
                    if artifact_match:
                        candidates.append(("artifact", artifact_match.group(1)))
        except OSError:
            return
        if not candidates:
            return

        artifact_ids = [
            artifact_id for kind, artifact_id in candidates if kind == "artifact"
        ]
        with Session(self._engine, expire_on_commit=False) as session:
            _set_busy_timeout(session)
            known: set[str] = set()
            if artifact_ids:
                known = set(
                    cast(
                        list[str],
                        session.exec(
                            select(ArtifactRecord.id).where(
                                col(ArtifactRecord.id).in_(artifact_ids)
                            )
                        ).all(),
                    )
                )
        for kind, artifact_id in candidates:
            if kind == "temp" or artifact_id not in known:
                try:
                    path = (
                        self._root / f".{artifact_id}.tmp"
                        if kind == "temp"
                        else self._path(artifact_id)
                    )
                    path.unlink(missing_ok=True)
                except OSError:
                    continue

    @staticmethod
    def _metadata(record: ArtifactRecord) -> dict[str, Any]:
        return {
            "id": record.id,
            "uri": "catlabel://artifacts/" + record.id,
            "sha256": record.sha256,
            "mime_type": record.mime_type,
            "kind": record.kind,
            "size_bytes": record.size_bytes,
            "created_at": record.created_at,
            "expires_at": record.expires_at,
        }

    @staticmethod
    def _validate_owner(owner: object) -> None:
        if not isinstance(owner, str) or not 1 <= len(owner) <= 512:
            raise ArtifactError("invalid_artifact_owner", "Artifact owner is invalid.")

    def _ensure_open(self) -> None:
        if self._closed:
            raise ArtifactError("artifact_store_closed", "Artifact store is closed.")
