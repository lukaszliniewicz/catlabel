"""Exclusive process lease for a CatLabel runtime data directory."""

from __future__ import annotations

import errno
import os
from pathlib import Path
from typing import BinaryIO


class RuntimeBusyError(RuntimeError):
    """Raised when another process already owns the runtime lease."""


def _platform_name() -> str:
    return os.name


def _lock_file(lock_file: BinaryIO) -> None:
    platform_name = _platform_name()
    if platform_name == "posix":
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    if platform_name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        return
    raise NotImplementedError(f"Runtime leases are unsupported on {platform_name!r}.")


def _unlock_file(lock_file: BinaryIO) -> None:
    platform_name = _platform_name()
    if platform_name == "posix":
        import fcntl

        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        return
    if platform_name == "nt":
        import msvcrt

        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        return
    raise NotImplementedError(f"Runtime leases are unsupported on {platform_name!r}.")


class RuntimeLease:
    """Hold an OS-level exclusive lock at ``data_directory/.runtime.lock``."""

    def __init__(self, data_directory: Path) -> None:
        self._data_directory = Path(data_directory).resolve()
        self._lock_file_handle: BinaryIO | None = None

    def acquire(self) -> RuntimeLease:
        """Create the data directory and acquire its nonblocking process lease."""
        if self._lock_file_handle is not None:
            raise RuntimeError("This RuntimeLease instance is already acquired.")

        self._data_directory.mkdir(parents=True, exist_ok=True)
        lock_file = (self._data_directory / ".runtime.lock").open("a+b")
        try:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            lock_file.seek(0)
            try:
                _lock_file(lock_file)
            except OSError as exc:
                if exc.errno in (errno.EACCES, errno.EAGAIN):
                    raise RuntimeBusyError(
                        f"Another process already owns the runtime at {self._data_directory}."
                    ) from exc
                raise
        except BaseException:
            lock_file.close()
            raise

        self._lock_file_handle = lock_file
        return self

    def release(self) -> None:
        """Release the lease and close its descriptor; repeated calls are safe."""
        lock_file = self._lock_file_handle
        if lock_file is None:
            return

        self._lock_file_handle = None
        try:
            _unlock_file(lock_file)
        finally:
            lock_file.close()

    def __enter__(self) -> RuntimeLease:
        return self.acquire()

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.release()
