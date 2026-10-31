from __future__ import annotations

import asyncio
import queue
import sys
import threading
import unittest
from contextlib import ExitStack, nullcontext
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import patch

from catlabel.transport.bluetooth.adapters import macos_iobluetooth as mac
from catlabel.transport.bluetooth.adapters import windows_winrt as win


class _WinRtFixture:
    """Linux fake SDK: every native action records its real caller thread."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.stack = ExitStack()
        self.reader: Any = None
        self.writes: list[bytes] = []
        self.write_seen = threading.Event()
        self.close_failure = False
        self.ignore_cancel = False
        self.cancelled = threading.Event()
        self.read_started = threading.Event()
        fixture = self

        class StreamSocket:
            def __init__(self) -> None:
                fixture.record("socket.create")
                self.output_stream = object()
                self.input_stream = object()

            async def connect_async(self, host, service) -> None:
                fixture.record("socket.connect")

            def close(self) -> None:
                fixture.record("socket.close")

        class DataWriter:
            def __init__(self, stream) -> None:
                fixture.record("writer.create")

            def write_bytes(self, data) -> None:
                fixture.record("writer.write")
                fixture.writes.append(bytes(data))
                fixture.write_seen.set()

            async def store_async(self) -> int:
                fixture.record("writer.store")
                return 1

            async def flush_async(self) -> bool:
                fixture.record("writer.flush")
                return True

            def close(self) -> None:
                fixture.record("writer.close")

        class DataReader:
            def __init__(self, stream) -> None:
                fixture.record("reader.create")
                self.inbox: asyncio.Queue[bytes] = asyncio.Queue()
                self.pending = b""
                self.consumers = 0
                self.max_consumers = 0
                fixture.reader = self

            async def load_async(self, size: int) -> int:
                fixture.record("reader.load")
                fixture.read_started.set()
                self.consumers += 1
                self.max_consumers = max(self.max_consumers, self.consumers)
                try:
                    try:
                        self.pending = await self.inbox.get()
                    except asyncio.CancelledError:
                        fixture.cancelled.set()
                        if not fixture.ignore_cancel:
                            raise
                        self.pending = await self.inbox.get()
                    return min(size, len(self.pending))
                finally:
                    self.consumers -= 1

            def read_bytes(self, target: bytearray) -> None:
                fixture.record("reader.copy")
                target[:] = self.pending[: len(target)]

            def close(self) -> None:
                fixture.record("reader.close")
                if fixture.close_failure:
                    raise OSError("reader close refused")

        class Backend:
            async def _resolve_service_async(self, address):
                fixture.record("service.resolve")
                return SimpleNamespace(
                    connection_host_name="host", connection_service_name="spp"
                )

        streams = ModuleType("winsdk.windows.storage.streams")
        streams.DataReader = DataReader  # type: ignore[attr-defined]
        streams.InputStreamOptions = SimpleNamespace(PARTIAL=1)  # type: ignore[attr-defined]
        self.stack.enter_context(patch.dict(sys.modules, {streams.__name__: streams}))
        self.stack.enter_context(
            patch.object(
                win,
                "_winrt_imports",
                return_value=(object, object, object, object, StreamSocket, DataWriter),
            )
        )
        self.sock = win._WinRtSocket(Backend())  # type: ignore[arg-type]
        self.sock.settimeout(0.2)
        self.sock.connect(("printer", 1))

    def record(self, label: str) -> None:
        self.calls.append((label, threading.get_ident()))

    def feed(self, payload: bytes) -> None:
        assert self.sock._loop is not None
        assert self.reader is not None
        self.sock._loop.call_soon_threadsafe(self.reader.inbox.put_nowait, payload)

    def close(self) -> None:
        self.close_failure = False
        self.ignore_cancel = False
        try:
            self.sock.close()
        finally:
            self.stack.close()


class _MacFixture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []
        self.channel: Any = None
        self.events: queue.Queue[object] = queue.Queue()
        self.close_failure = False
        self.remove_failure = False
        self.poll_failure = False
        self.stack = ExitStack()
        fixture = self

        class NSObject:
            @classmethod
            def alloc(cls):
                fixture.record("delegate.create")
                return cls()

            def init(self):
                return self

        class Channel:
            delegate = None

            def setDelegate_(self, delegate):
                fixture.record(
                    "delegate.remove" if delegate is None else "delegate.install"
                )
                if delegate is None and fixture.remove_failure:
                    return 1
                self.delegate = delegate
                return 0

            def writeSync_length_(self, data, size):
                fixture.record("channel.write")
                return 0

            def closeChannel(self):
                fixture.record("channel.close")
                if fixture.close_failure:
                    raise OSError("channel close refused")
                return 0

        class Device:
            def openRFCOMMChannelSync_withChannelID_delegate_(
                self, output, channel_id, delegate
            ):
                fixture.record("channel.open")
                fixture.channel = Channel()
                return 0, fixture.channel

            def closeConnection(self):
                fixture.record("device.close")
                return 0

        self.backend = mac._MacClassicBackend()
        self.cached_device = object()
        self.backend._devices_by_address["PRINTER"] = self.cached_device

        def lookup(address: str):
            fixture.record("device.create")
            return Device()

        self.stack.enter_context(
            patch.object(mac, "_device_by_address", side_effect=lookup)
        )

        def poll() -> None:
            if fixture.poll_failure:
                raise OSError("run loop failed")
            try:
                operation = fixture.events.get_nowait()
            except queue.Empty:
                return
            operation()  # type: ignore[operator]

        self.stack.enter_context(
            patch.object(
                mac,
                "_iobluetooth_imports",
                return_value=(
                    SimpleNamespace(autorelease_pool=nullcontext),
                    SimpleNamespace(NSObject=NSObject),
                ),
            )
        )
        self.stack.enter_context(
            patch.object(mac, "_poll_rfcomm_run_loop", side_effect=poll)
        )
        self.stack.enter_context(patch.object(mac, "_rfcomm_delegate_class", None))
        self.sock = mac._MacClassicSocket(self.backend)
        self.sock.connect(("printer", 1))

    def record(self, label: str) -> None:
        self.calls.append((label, threading.get_ident()))

    def feed(self, payload: bytes) -> None:
        def deliver() -> None:
            data = bytearray(payload)
            self.channel.delegate.rfcommChannelData_data_length_(
                self.channel, data, len(data)
            )
            data[:] = b"x" * len(data)

        self.events.put(deliver)

    def close(self) -> None:
        self.close_failure = False
        self.remove_failure = False
        try:
            self.sock.close()
        finally:
            self.stack.close()


class NativeClassicReceiveTests(unittest.TestCase):
    def setUp(self) -> None:
        # Keep failure fixtures short; production retains the source's 2 s budget.
        self.enterContext(patch.object(win, "_CLOSE_TIMEOUT_SEC", 0.5))
        self.enterContext(patch.object(mac, "_CLOSE_TIMEOUT_SEC", 0.5))

    def assert_one_owner(self, calls: list[tuple[str, int]]) -> None:
        self.assertTrue(calls)
        self.assertEqual(len({thread for _, thread in calls}), 1)
        self.assertNotEqual(calls[0][1], threading.get_ident())

    def test_winrt_unsolicited_and_all_native_operations_have_one_owner(self) -> None:
        fixture = _WinRtFixture()
        self.addCleanup(fixture.close)
        payloads: list[bytes] = []
        received = threading.Event()
        errors: list[Exception] = []

        def notify(data: bytes) -> None:
            payloads.append(data)
            received.set()

        fixture.sock.start_receive(notify, errors.append)
        fixture.sock.sendall(b"command")
        fixture.feed(b"unsolicited")
        self.assertTrue(received.wait(0.3))
        self.assertEqual(payloads, [b"unsolicited"])
        self.assertEqual(errors, [])
        with self.assertRaisesRegex(RuntimeError, "reader already active"):
            fixture.sock.recv(4096)
        with self.assertRaisesRegex(RuntimeError, "reader already active"):
            fixture.sock.start_receive(payloads.append, errors.append)
        fixture.sock.stop_receive()
        fixture.sock.stop_receive()
        fixture.feed(b"direct")
        self.assertEqual(fixture.sock.recv(4096), b"direct")
        self.assertEqual(fixture.reader.max_consumers, 1)
        owner = fixture.sock._thread
        assert owner is not None
        fixture.sock.close()
        self.assertFalse(owner.is_alive())
        self.assert_one_owner(fixture.calls)
        self.assertTrue(
            {"reader.close", "writer.close", "socket.close"}.issubset(
                {name for name, _ in fixture.calls}
            )
        )

    def test_winrt_direct_reader_excludes_passive_reader_until_done(self) -> None:
        fixture = _WinRtFixture()
        self.addCleanup(fixture.close)
        result: list[bytes] = []
        caller = threading.Thread(target=lambda: result.append(fixture.sock.recv(4096)))
        caller.start()
        try:
            self.assertTrue(fixture.read_started.wait(0.1))
            with self.assertRaisesRegex(RuntimeError, "reader already active"):
                fixture.sock.start_receive(lambda _: None, lambda _: None)
        finally:
            fixture.feed(b"direct")
            caller.join(timeout=0.3)
        self.assertFalse(caller.is_alive())
        self.assertEqual(result, [b"direct"])
        self.assertEqual(fixture.reader.max_consumers, 1)

    def test_winrt_eof_reports_failure_and_close_cancels_reader(self) -> None:
        fixture = _WinRtFixture()
        self.addCleanup(fixture.close)
        failed = threading.Event()
        errors: list[Exception] = []

        def failed_receive(error: Exception) -> None:
            errors.append(error)
            failed.set()

        fixture.sock.start_receive(lambda data: None, failed_receive)
        fixture.feed(b"")
        self.assertTrue(failed.wait(0.3))
        self.assertIsInstance(errors[0], ConnectionError)
        fixture.sock.close()
        self.assertIsNone(fixture.sock._thread)

    def test_winrt_failed_close_retains_owner_and_native_handles_for_retry(
        self,
    ) -> None:
        fixture = _WinRtFixture()
        self.addCleanup(fixture.close)
        fixture.sock.start_receive(lambda data: None, lambda error: None)
        owner = fixture.sock._thread
        assert owner is not None
        fixture.close_failure = True
        with self.assertRaisesRegex(OSError, "reader close refused"):
            fixture.sock.close()
        self.assertIs(fixture.sock._thread, owner)
        self.assertTrue(owner.is_alive())
        self.assertIsNotNone(fixture.sock._reader)
        self.assertIsNone(fixture.sock._read_task)
        fixture.close_failure = False
        fixture.sock.close()
        self.assertFalse(owner.is_alive())
        self.assert_one_owner(fixture.calls)

    def test_winrt_uncancellable_reader_retains_retryable_task(self) -> None:
        fixture = _WinRtFixture()
        self.addCleanup(fixture.close)
        fixture.ignore_cancel = True
        delivered: list[bytes] = []
        fixture.sock.start_receive(delivered.append, lambda error: None)
        with self.assertRaises(TimeoutError):
            fixture.sock.stop_receive()
        self.assertTrue(fixture.cancelled.is_set())
        self.assertIsNotNone(fixture.sock._read_task)
        assert fixture.sock._thread is not None
        self.assertTrue(fixture.sock._thread.is_alive())
        fixture.ignore_cancel = False
        fixture.sock.stop_receive()
        self.assertEqual(delivered, [])
        fixture.sock.close()

    def test_mac_unsolicited_copies_borrowed_data_and_owns_all_native_calls(
        self,
    ) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        received = threading.Event()
        payloads: list[bytes] = []

        def notify(data: bytes) -> None:
            payloads.append(data)
            received.set()

        fixture.sock.start_receive(notify, lambda error: None)
        fixture.sock.sendall(b"command")
        fixture.feed(b"unsolicited")
        self.assertTrue(received.wait(0.3))
        fixture.sock._run(lambda: None)
        self.assertEqual(payloads, [b"unsolicited"])
        self.assertIsInstance(payloads[0], bytes)
        owner = fixture.sock._thread
        assert owner is not None
        fixture.sock.close()
        self.assertFalse(owner.is_alive())
        self.assert_one_owner(fixture.calls)
        self.assertTrue(
            {"delegate.remove", "channel.close", "device.close"}.issubset(
                {name for name, _ in fixture.calls}
            )
        )

    def test_mac_socket_looks_up_proxy_on_owner_instead_of_borrowing_scan_cache(
        self,
    ) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        self.assertIs(
            fixture.backend._devices_by_address["PRINTER"], fixture.cached_device
        )
        self.assertIsNot(fixture.sock._device, fixture.cached_device)
        fixture.sock.sendall(b"command")
        fixture.sock.close()
        self.assert_one_owner(fixture.calls)
        self.assertIn("device.create", [name for name, _ in fixture.calls])

    def test_mac_missing_owner_proxy_fails_without_using_scan_cache(self) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        fixture.sock.close()
        with (
            patch.object(mac, "_device_by_address", return_value=None),
            self.assertRaisesRegex(RuntimeError, "Bluetooth device not found"),
        ):
            fixture.sock.connect(("printer", 1))
        self.assertIsNone(fixture.sock._device)
        self.assertIsNone(fixture.sock._channel)
        fixture.sock.close()

    def test_mac_stop_generation_suppresses_stale_delegate_callbacks(self) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        payloads: list[bytes] = []
        errors: list[Exception] = []
        fixture.sock.start_receive(payloads.append, errors.append)
        old = fixture.channel.delegate
        with self.assertRaisesRegex(RuntimeError, "already installed"):
            fixture.sock.start_receive(payloads.append, errors.append)
        fixture.sock.stop_receive()
        fixture.sock.stop_receive()
        fixture.sock.start_receive(payloads.append, errors.append)
        fixture.sock._run(
            lambda: old.rfcommChannelData_data_length_(fixture.channel, b"late", 4)
        )
        fixture.sock._run(lambda: old.rfcommChannelClosed_(fixture.channel))
        self.assertEqual(payloads, [])
        self.assertEqual(errors, [])

    def test_mac_stop_failure_retains_delegate_and_suppresses_callbacks(self) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        payloads: list[bytes] = []
        fixture.sock.start_receive(payloads.append, lambda error: None)
        fixture.remove_failure = True
        with self.assertRaisesRegex(RuntimeError, "delegate removal failed"):
            fixture.sock.stop_receive()
        self.assertIsNotNone(fixture.sock._delegate)
        fixture.feed(b"late")
        fixture.sock._run(lambda: None)
        self.assertEqual(payloads, [])
        fixture.remove_failure = False
        fixture.sock.stop_receive()
        self.assertIsNone(fixture.sock._delegate)

    def test_mac_close_failure_retains_native_ownership_for_retry(self) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        fixture.sock.start_receive(lambda data: None, lambda error: None)
        owner = fixture.sock._thread
        assert owner is not None
        fixture.close_failure = True
        with self.assertRaisesRegex(OSError, "channel close refused"):
            fixture.sock.close()
        self.assertIs(fixture.sock._thread, owner)
        self.assertTrue(owner.is_alive())
        self.assertIsNotNone(fixture.sock._channel)
        self.assertIsNotNone(fixture.sock._device)
        fixture.close_failure = False
        fixture.sock.close()
        self.assertFalse(owner.is_alive())
        self.assert_one_owner(fixture.calls)

    def test_mac_channel_closure_reports_error_on_owner(self) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        errors: list[Exception] = []
        error_threads: list[int] = []

        def failed(error: Exception) -> None:
            errors.append(error)
            error_threads.append(threading.get_ident())

        fixture.sock.start_receive(lambda _: None, failed)
        fixture.sock._run(
            lambda: fixture.channel.delegate.rfcommChannelClosed_(fixture.channel)
        )
        self.assertIsInstance(errors[0], ConnectionError)
        self.assertEqual(error_threads, [fixture.calls[0][1]])

    def test_mac_run_loop_error_reports_failure_but_keeps_owner_for_cleanup(
        self,
    ) -> None:
        fixture = _MacFixture()
        self.addCleanup(fixture.close)
        failed = threading.Event()
        fixture.sock.start_receive(lambda data: None, lambda error: failed.set())
        fixture.poll_failure = True
        self.assertTrue(failed.wait(0.3))
        with self.assertRaisesRegex(RuntimeError, "run loop failed"):
            fixture.sock.sendall(b"forbidden")
        owner = fixture.sock._thread
        assert owner is not None
        fixture.sock.close()
        self.assertFalse(owner.is_alive())


if __name__ == "__main__":
    unittest.main()
