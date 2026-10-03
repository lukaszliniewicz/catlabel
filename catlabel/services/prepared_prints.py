"""Bounded temporary storage for browser-rendered print pages."""

from __future__ import annotations

import logging
import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

from PIL import Image

from ..core.resource_limits import (
    MAX_IMAGE_BYTES,
    MAX_PRINT_JOBS,
    MAX_REQUEST_BYTES,
    ResourceLimitError,
    validate_image_budget,
)

logger = logging.getLogger(__name__)


class PreparedPrintError(Exception):
    """Base class for prepared-print lifecycle errors."""


class PreparedPrintNotFound(PreparedPrintError):
    """A prepared session is missing or has expired."""


class PreparedPrintConflict(PreparedPrintError):
    """A prepared session is incomplete, out of order, or committing."""


class PreparedPrintCapacityError(PreparedPrintError):
    """The store has reached its active-session limit."""


class PreparedPrintStoreStopped(PreparedPrintError):
    """The store is closing and no longer accepts sessions."""


class PreparedPrintTooLarge(PreparedPrintError):
    """A page or session exceeds its byte budget."""


class PreparedPrintInvalidImage(PreparedPrintError):
    """A staged page is not a valid bounded PNG image."""


@dataclass(frozen=True, slots=True)
class PreparedPrintProgress:
    prepared_id: str
    total: int
    next_index: int


@dataclass(frozen=True, slots=True)
class PreparedPrintLease:
    """Immutable ownership of a complete session transferred to its committer."""

    prepared_id: str
    total: int
    page_paths: tuple[Path, ...]
    _owner_token: object = field(repr=False, compare=False)

    def matches_owner(self, token: object) -> bool:
        return self._owner_token is token


@dataclass(slots=True)
class _PreparedPrintSession:
    prepared_id: str
    expected_jobs: int
    directory: TemporaryDirectory[str]
    page_paths: list[Path]
    total_bytes: int
    total_pixels: int
    next_index: int
    last_touch: float
    committing: bool
    owner_token: object


class PreparedPrintStore:
    """Thread-safe, process-local storage for short-lived PNG print sessions."""

    def __init__(
        self,
        max_sessions: int = 4,
        ttl_seconds: float = 900,
        clock: Callable[[], float] = time.monotonic,
        temp_root: str | Path | None = None,
    ) -> None:
        if type(max_sessions) is not int or max_sessions < 1:
            raise ValueError("max_sessions must be a positive integer.")
        if type(ttl_seconds) not in (int, float):
            raise ValueError("ttl_seconds must be a positive number.")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive number.")

        self.max_sessions = max_sessions
        self.ttl_seconds = float(ttl_seconds)
        self._clock = clock
        self._temp_root = temp_root
        self._lock = RLock()
        self._sessions: dict[str, _PreparedPrintSession] = {}
        self._stopped = False

    def _now(self) -> float:
        return self._clock()

    @staticmethod
    def _cleanup(session: _PreparedPrintSession) -> None:
        try:
            session.directory.cleanup()
        except Exception:
            logger.exception(
                "Failed to remove prepared print session %s", session.prepared_id
            )

    def _expire_locked(self, now: float) -> list[_PreparedPrintSession]:
        expired: list[_PreparedPrintSession] = []
        for prepared_id, session in tuple(self._sessions.items()):
            if not session.committing and now - session.last_touch >= self.ttl_seconds:
                expired.append(self._sessions.pop(prepared_id))
        return expired

    def _lookup_locked(self, prepared_id: str, now: float) -> _PreparedPrintSession:
        session = self._sessions.get(prepared_id)
        if session is None:
            raise PreparedPrintNotFound("Prepared print was not found.")
        if not session.committing and now - session.last_touch >= self.ttl_seconds:
            self._sessions.pop(prepared_id)
            self._cleanup(session)
            raise PreparedPrintNotFound("Prepared print was not found.")
        return session

    @staticmethod
    def _progress(session: _PreparedPrintSession) -> PreparedPrintProgress:
        return PreparedPrintProgress(
            prepared_id=session.prepared_id,
            total=session.expected_jobs,
            next_index=session.next_index,
        )

    @staticmethod
    def _inspect_png(payload: bytes, pixels_so_far: int) -> int:
        try:
            with Image.open(BytesIO(payload)) as source:
                if source.format != "PNG":
                    raise PreparedPrintInvalidImage("Prepared page must be a PNG.")
                return validate_image_budget(source.width, source.height, pixels_so_far)
        except (PreparedPrintInvalidImage, ResourceLimitError):
            raise
        except Exception as exc:
            raise PreparedPrintInvalidImage(
                "Prepared page is not a valid PNG."
            ) from exc

    @staticmethod
    def _write_page(path: Path, payload: bytes) -> None:
        with path.open("xb") as stream:
            written = stream.write(payload)
            if written != len(payload):
                raise OSError("Short write while storing a prepared page.")
            stream.flush()

    def start(self, expected_jobs: int) -> PreparedPrintProgress:
        if type(expected_jobs) is not int or not 1 <= expected_jobs <= MAX_PRINT_JOBS:
            raise ValueError(f"expected_jobs must be between 1 and {MAX_PRINT_JOBS}.")

        with self._lock:
            now = self._now()
            expired = self._expire_locked(now)
            for session in expired:
                self._cleanup(session)
            if self._stopped:
                raise PreparedPrintStoreStopped("Prepared print storage is stopped.")
            if len(self._sessions) >= self.max_sessions:
                raise PreparedPrintCapacityError("Prepared print storage is full.")

            directory = TemporaryDirectory(
                prefix="catlabel-prepared-print-", dir=self._temp_root
            )
            prepared_id = uuid.uuid4().hex
            session = _PreparedPrintSession(
                prepared_id=prepared_id,
                expected_jobs=expected_jobs,
                directory=directory,
                page_paths=[],
                total_bytes=0,
                total_pixels=0,
                next_index=0,
                last_touch=now,
                committing=False,
                owner_token=object(),
            )
            self._sessions[prepared_id] = session
            return self._progress(session)

    def append(
        self, prepared_id: str, index: int, png_bytes: object
    ) -> PreparedPrintProgress:
        with self._lock:
            now = self._now()
            session = self._lookup_locked(prepared_id, now)
            if session.committing:
                raise PreparedPrintConflict("Prepared print is already committing.")
            if type(index) is not int or index < 0:
                raise PreparedPrintConflict("Page index must be a nonnegative integer.")
            if index != session.next_index or index >= session.expected_jobs:
                raise PreparedPrintConflict("Prepared pages must be appended in order.")
            if not isinstance(png_bytes, bytes):
                raise PreparedPrintInvalidImage(
                    "Prepared page must be binary PNG data."
                )
            if len(png_bytes) > MAX_IMAGE_BYTES:
                raise PreparedPrintTooLarge("A prepared page exceeds the byte limit.")
            next_bytes = session.total_bytes + len(png_bytes)
            if next_bytes > MAX_REQUEST_BYTES:
                raise PreparedPrintTooLarge(
                    "Prepared print exceeds the cumulative byte limit."
                )

            next_pixels = self._inspect_png(png_bytes, session.total_pixels)
            candidate = Path(session.directory.name) / f"page-{index:06d}.png"
            try:
                self._write_page(candidate, png_bytes)
            except BaseException:
                try:
                    candidate.unlink(missing_ok=True)
                except OSError:
                    logger.exception(
                        "Failed to remove partial prepared page %s", candidate
                    )
                raise

            session.page_paths.append(candidate)
            session.total_bytes = next_bytes
            session.total_pixels = next_pixels
            session.next_index += 1
            session.last_touch = now
            return self._progress(session)

    def cancel(self, prepared_id: str) -> None:
        with self._lock:
            now = self._now()
            session = self._lookup_locked(prepared_id, now)
            if session.committing:
                raise PreparedPrintConflict("Prepared print is already committing.")
            self._sessions.pop(prepared_id)
            self._cleanup(session)

    def take_for_commit(self, prepared_id: str) -> PreparedPrintLease:
        with self._lock:
            now = self._now()
            session = self._lookup_locked(prepared_id, now)
            if session.committing:
                raise PreparedPrintConflict("Prepared print is already committing.")
            if session.next_index != session.expected_jobs:
                raise PreparedPrintConflict("Prepared print is incomplete.")
            session.committing = True
            session.last_touch = now
            return PreparedPrintLease(
                prepared_id=session.prepared_id,
                total=session.expected_jobs,
                page_paths=tuple(session.page_paths),
                _owner_token=session.owner_token,
            )

    def finish(self, lease: PreparedPrintLease) -> bool:
        with self._lock:
            session = self._sessions.get(lease.prepared_id)
            if (
                session is None
                or not session.committing
                or not lease.matches_owner(session.owner_token)
            ):
                return False
            self._sessions.pop(lease.prepared_id)
            self._cleanup(session)
            return True

    def reap(self) -> int:
        with self._lock:
            now = self._now()
            expired = self._expire_locked(now)
            for session in expired:
                self._cleanup(session)
        return len(expired)

    def close(self) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            preparing = [
                self._sessions.pop(prepared_id)
                for prepared_id, session in tuple(self._sessions.items())
                if not session.committing
            ]
            for session in preparing:
                self._cleanup(session)
