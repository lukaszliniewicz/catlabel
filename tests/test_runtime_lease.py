from __future__ import annotations

import errno
import os
import select
import subprocess
import sys
import tempfile
import unittest
from contextlib import chdir
from pathlib import Path
from types import SimpleNamespace
from typing import BinaryIO
from unittest.mock import patch

import catlabel.core.runtime_lease as runtime_lease
from catlabel.core.runtime_lease import RuntimeBusyError, RuntimeLease

_HANDSHAKE_TIMEOUT_SECONDS = 5


def _start_lease_holder(data_directory: Path) -> subprocess.Popen[str]:
    script = """
import sys
from pathlib import Path
from catlabel.core.runtime_lease import RuntimeLease

with RuntimeLease(Path(sys.argv[1])):
    print('ready', flush=True)
    sys.stdin.readline()
"""
    return subprocess.Popen(
        [sys.executable, "-c", script, str(data_directory)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _wait_for_ready(process: subprocess.Popen[str]) -> None:
    if process.stdout is None:
        raise AssertionError("Subprocess stdout pipe was not created.")
    readable, _, _ = select.select([process.stdout], [], [], _HANDSHAKE_TIMEOUT_SECONDS)
    if not readable:
        raise AssertionError("Timed out waiting for the subprocess lease handshake.")
    line = process.stdout.readline().strip()
    if line != "ready":
        error_output = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError(
            f"Subprocess exited before acquiring its lease: {line!r} {error_output!r}"
        )


def _stop_process(process: subprocess.Popen[str]) -> None:
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=_HANDSHAKE_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=_HANDSHAKE_TIMEOUT_SECONDS)
    finally:
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                stream.close()


def _busy_msvcrt(error_number: int, descriptor_seen: list[int]) -> SimpleNamespace:
    fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=0)

    def locking(descriptor: int, mode: int, byte_count: int) -> None:
        if mode != fake_msvcrt.LK_NBLCK or byte_count != 1:
            raise AssertionError("Expected a nonblocking one-byte Windows lock.")
        descriptor_seen.append(descriptor)
        raise OSError(error_number, "busy")

    fake_msvcrt.locking = locking
    return fake_msvcrt


class RuntimeLeaseTests(unittest.TestCase):
    tmp_path: Path

    def setUp(self) -> None:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.tmp_path = Path(temporary_directory.name)

    def assert_descriptor_closed(self, descriptor: int) -> None:
        with self.assertRaises(OSError) as error:
            os.fstat(descriptor)
        self.assertEqual(error.exception.errno, errno.EBADF)

    def test_acquire_creates_absolute_lock_file_and_release_is_idempotent(self) -> None:
        with chdir(self.tmp_path):
            data_directory = Path("new") / "runtime"
            lease = RuntimeLease(data_directory)

            self.assertIs(lease.acquire(), lease)
            lock_path = self.tmp_path / data_directory / ".runtime.lock"
            self.assertTrue(lock_path.is_absolute())
            self.assertTrue(lock_path.is_file())
            self.assertGreaterEqual(lock_path.stat().st_size, 1)
            with self.assertRaisesRegex(RuntimeError, "already acquired"):
                lease.acquire()

            lease.release()
            lease.release()
            self.assertTrue(lock_path.exists())

    @unittest.skipUnless(os.name == "posix", "Uses POSIX pipe readiness and flock.")
    def test_subprocess_contention_and_normal_release(self) -> None:
        data_directory = self.tmp_path / "runtime"
        process = _start_lease_holder(data_directory)
        try:
            _wait_for_ready(process)
            with self.assertRaises(RuntimeBusyError):
                RuntimeLease(data_directory).acquire()

            if process.stdin is None:
                self.fail("Subprocess stdin pipe was not created.")
            process.stdin.write("release\n")
            process.stdin.flush()
            self.assertEqual(process.wait(timeout=_HANDSHAKE_TIMEOUT_SECONDS), 0)

            with RuntimeLease(data_directory):
                pass
        finally:
            _stop_process(process)

    @unittest.skipUnless(os.name == "posix", "Uses POSIX pipe readiness and flock.")
    def test_process_death_releases_lease(self) -> None:
        data_directory = self.tmp_path / "runtime"
        process = _start_lease_holder(data_directory)
        try:
            _wait_for_ready(process)
            process.terminate()
            self.assertLess(process.wait(timeout=_HANDSHAKE_TIMEOUT_SECONDS), 0)

            with RuntimeLease(data_directory):
                pass
        finally:
            _stop_process(process)

    def test_context_releases_when_base_exception_escapes(self) -> None:
        class StopNow(BaseException):
            pass

        lease = RuntimeLease(self.tmp_path / "runtime")
        with self.assertRaises(StopNow), lease:
            raise StopNow

        with RuntimeLease(self.tmp_path / "runtime"):
            pass

    def test_unrelated_lock_error_propagates_and_closes_descriptor(self) -> None:
        descriptor_seen: list[int] = []

        def fail_to_lock(lock_file: BinaryIO) -> None:
            descriptor_seen.append(lock_file.fileno())
            raise OSError(errno.EIO, "native lock failure")

        with (
            patch.object(runtime_lease, "_lock_file", fail_to_lock),
            self.assertRaises(OSError) as error,
        ):
            RuntimeLease(self.tmp_path / "runtime").acquire()

        self.assertEqual(error.exception.errno, errno.EIO)
        self.assertEqual(len(descriptor_seen), 1)
        self.assert_descriptor_closed(descriptor_seen[0])

    def test_windows_branch_locks_one_byte_and_closes_descriptor(self) -> None:
        lock_calls: list[tuple[int, int, int]] = []
        fake_msvcrt = SimpleNamespace(LK_NBLCK=1, LK_UNLCK=0)

        def locking(descriptor: int, mode: int, byte_count: int) -> None:
            lock_calls.append((descriptor, mode, byte_count))

        fake_msvcrt.locking = locking
        with (
            patch.object(runtime_lease, "_platform_name", return_value="nt"),
            patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
        ):
            lease = RuntimeLease(self.tmp_path / "windows-runtime")
            lease.acquire()
            lock_file = lease._lock_file_handle
            if lock_file is None:
                self.fail("Acquired lease did not retain its descriptor.")
            descriptor = lock_file.fileno()
            lease.release()

        self.assertEqual(
            lock_calls,
            [
                (descriptor, fake_msvcrt.LK_NBLCK, 1),
                (descriptor, fake_msvcrt.LK_UNLCK, 1),
            ],
        )
        lock_path = self.tmp_path / "windows-runtime" / ".runtime.lock"
        self.assertGreaterEqual(lock_path.stat().st_size, 1)
        self.assert_descriptor_closed(descriptor)

    def test_failed_windows_acquire_closes_descriptor(self) -> None:
        for error_number in (errno.EACCES, errno.EAGAIN):
            with self.subTest(error_number=error_number):
                descriptor_seen: list[int] = []
                fake_msvcrt = _busy_msvcrt(error_number, descriptor_seen)
                with (
                    patch.object(runtime_lease, "_platform_name", return_value="nt"),
                    patch.dict(sys.modules, {"msvcrt": fake_msvcrt}),
                    self.assertRaises(RuntimeBusyError),
                ):
                    RuntimeLease(
                        self.tmp_path / f"windows-runtime-{error_number}"
                    ).acquire()

                self.assertEqual(len(descriptor_seen), 1)
                self.assert_descriptor_closed(descriptor_seen[0])
