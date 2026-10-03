from __future__ import annotations

import asyncio
import hashlib
import math
import time
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import catlabel.vendors.phomemo.client as phomemo_client_module
from catlabel.printing.job_spool import ProtocolJobSpool
from catlabel.printing.runtime.phomemo_released import (
    PhomemoPacingTransport,
    PhomemoReleasedStatus,
)
from catlabel.protocol.types import PaperMode
from catlabel.transport.bluetooth import DeviceInfo, SppBackend
from catlabel.vendors.phomemo.client import PhomemoClient
from tests.runtime_session_fake import RuntimeSessionFake


class _PacingTransport:
    def __init__(self) -> None:
        self.waits: list[float] = []
        self.status: PhomemoReleasedStatus | None = None
        self.next_reply: bytes | None = None
        self.return_history_only: bytes | None = None
        self.immediate_timeout = False

    def can_wait_for_notification(self) -> bool:
        return True

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.assert_label(label, required)
        self.waits.append(timeout)
        if self.immediate_timeout:
            raise TimeoutError("fixture wait returned early")
        if self.return_history_only is not None:
            return self.return_history_only
        if self.next_reply is not None:
            reply, self.next_reply = self.next_reply, None
            if self.status is not None:
                self.status.receive(reply)
            if not match(reply):
                raise AssertionError("fixture reply did not satisfy the waiter")
            return reply
        await asyncio.sleep(timeout)
        return None

    @staticmethod
    def assert_label(label: str, required: bool) -> None:
        if label != "Phomemo pacing" or required:
            raise AssertionError("Phomemo pacing must use an optional status wait")


class _TestRuntimeSession(RuntimeSessionFake):
    def __init__(self, *, can_wait: bool) -> None:
        self._can_wait = can_wait

    def can_wait_for_notification(self) -> bool:
        return self._can_wait


class _FakeSppBackend(SppBackend):
    def __init__(self, route: str) -> None:
        super().__init__()
        self.route = route
        self.controller: PhomemoReleasedStatus | None = None
        self.runtime_session = _TestRuntimeSession(can_wait=route in {"classic", "ble"})
        self.notify_callback: Callable[[bytes], None] | None = None
        self.connected = False
        self.writes: list[bytes] = []
        self.events: list[str] = []
        self.notifications: list[bytes] = []
        self.write_hook: Callable[[bytes], None] | None = None
        self.block_write = False
        self.write_started = asyncio.Event()
        self.fail_callback_clear = False
        self.attempts: tuple[DeviceInfo, ...] = ()

    async def connect_attempts(
        self,
        attempts: list[DeviceInfo],
        pairing_hint: bool | None = None,
    ) -> None:
        _ = pairing_hint
        self.events.append("connect")
        self.connected = True
        self.attempts = tuple(attempts)

    async def disconnect(self) -> None:
        self.events.append("disconnect")
        self.connected = False
        self.controller = None

    def can_receive_passively(self) -> bool:
        return self.connected and self.route == "classic"

    def register_notify_callback(
        self,
        callback: Callable[[bytes], None] | None,
    ) -> None:
        self.events.append("register" if callback is not None else "clear")
        if callback is None and self.fail_callback_clear:
            raise RuntimeError("callback cleanup failed")
        self.notify_callback = callback

    def can_attach_runtime_controller(self) -> bool:
        return self.connected and self.route == "ble"

    def can_wait_for_notification(self) -> bool:
        return self.connected and self.route in {"classic", "ble"}

    async def attach_runtime_controller(
        self,
        runtime_controller: PhomemoReleasedStatus,
        *,
        timeout: float = 1.0,
    ) -> None:
        self.events.append("attach")
        self.controller = runtime_controller
        await runtime_controller.initialize_connection(
            self.runtime_session,
            mtu_size=20,
            timeout=timeout,
        )

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        _ = label, required
        if self.notifications:
            payload = self.notifications.pop(0)
            self.dispatch(payload)
            if match(payload):
                return payload
        await asyncio.sleep(timeout)
        return None

    async def write(
        self,
        data: bytes,
        chunk_size: int,
        delay_ms: int = 0,
        interval_ms: int | None = None,
    ) -> None:
        _ = chunk_size, delay_ms, interval_ms
        self.writes.append(data)
        self.write_started.set()
        if self.write_hook is not None:
            self.write_hook(data)
        if self.block_write:
            await asyncio.Event().wait()

    def dispatch(self, payload: bytes) -> None:
        if self.notify_callback is not None:
            self.notify_callback(payload)
        elif self.controller is not None:
            self.controller.handle_notification(self.runtime_session, payload)


def _client(variant: str | None, *, width_px: int = 384) -> PhomemoClient:
    hardware: dict[str, object] = {
        "protocol_family": "phomemo_m02",
        "width_px": width_px,
        "dpi": 203,
    }
    if variant is not None:
        hardware["protocol_variant"] = variant
    return PhomemoClient(
        SimpleNamespace(
            address="device-address",
            name="Phomemo test printer",
            paired=True,
        ),
        hardware,
        SimpleNamespace(paper_mode=None, energy=None, feed_lines=None),
        SimpleNamespace(energy=0, feed_lines=None),
    )


def _image(width: int = 8, height: int = 2) -> Image.Image:
    image = Image.new("L", (width, height), 255)
    image.putpixel((0, 0), 0)
    return image


class PhomemoReleasedStatusTests(unittest.IsolatedAsyncioTestCase):
    def test_decoder_handles_fragments_coalesced_frames_and_opaque_auxiliary(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        status.receive(b"\x1a\x05")
        status.receive(b"\x99\x1a\x07\x05\x99\x03\xa9\x1a\x06\x88")

        with self.assertRaisesRegex(RuntimeError, "cover is open"):
            status.raise_if_not_ready()
        status.receive(b"\x1a\x05\x98\x1a\x06\x89")
        status.raise_if_not_ready()

    def test_readiness_statuses_raise_and_clear_as_specified(self) -> None:
        for frame, clear_frame, message in (
            (b"\x1a\x05\x99", b"\x1a\x05\x98", "cover is open"),
            (b"\x1a\x06\x88", b"\x1a\x06\x00", "out of paper"),
            (b"\x1a\x03\xa9", b"\x1a\x03\xa8", "overheated"),
        ):
            with self.subTest(frame=frame):
                status = PhomemoReleasedStatus()
                status.receive(frame)
                with self.assertRaisesRegex(RuntimeError, message):
                    status.raise_if_not_ready()
                status.receive(clear_frame)
                status.raise_if_not_ready()

    async def test_job_scope_checks_status_on_entry_and_after_successful_body(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        status.receive(b"\x1a\x05\x99")
        with self.assertRaisesRegex(RuntimeError, "cover is open"):
            async with status.released_job_scope():
                self.fail("unready device entered the job scope")

        status.receive(b"\x1a\x05\x98")
        with self.assertRaisesRegex(RuntimeError, "out of paper"):
            async with status.released_job_scope():
                status.receive(b"\x1a\x06\x88")
        self.assertFalse(status.active)

    async def test_coalesced_readiness_fault_and_recovery_remains_sticky_for_job(
        self,
    ) -> None:
        for fault, clear, message in (
            (b"\x1a\x05\x99", b"\x1a\x05\x98", "cover opened"),
            (b"\x1a\x06\x88", b"\x1a\x06\x89", "ran out of paper"),
            (b"\x1a\x03\xa9", b"\x1a\x03\xa8", "overheated"),
        ):
            with self.subTest(fault=fault):
                status = PhomemoReleasedStatus()
                with self.assertRaisesRegex(RuntimeError, message):
                    async with status.released_job_scope():
                        status.receive(fault + clear)
                self.assertFalse(status.active)
                # The live condition cleared, so the next job can start.
                async with status.released_job_scope():
                    pass

    async def test_cancel_and_failed_result_are_job_scoped_and_sticky(self) -> None:
        status = PhomemoReleasedStatus()
        status.receive(b"\x1a\x0b\xb8")
        status.raise_if_not_ready()

        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            async with status.released_job_scope():
                status.receive(b"\x1a\x0b\xb8")
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            status.raise_if_not_ready()
        self.assertFalse(status.active)

        async with status.released_job_scope():
            status.receive(b"\x1a\x0f\x0c")
        status.raise_if_not_ready()

        with self.assertRaisesRegex(RuntimeError, "print failure"):
            async with status.released_job_scope():
                status.receive(b"\x1a\x0f\x02")
        self.assertFalse(status.active)

    async def test_stale_split_result_and_cancel_are_excluded_by_scope_fence(
        self,
    ) -> None:
        for opcode, prefix, suffix in (
            ("result", b"\x1a\x0f", b"\x02"),
            ("cancel", b"\x1a\x0b", b"\xb8"),
        ):
            with self.subTest(opcode=opcode):
                status = PhomemoReleasedStatus()
                status.receive(prefix)
                async with status.released_job_scope():
                    status.receive(suffix)
                status.raise_if_not_ready()

    async def test_nested_scope_and_cancellation_always_release_active_flag(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        with self.assertRaisesRegex(RuntimeError, "already has an active"):
            async with status.released_job_scope():
                async with status.released_job_scope():
                    self.fail("nested released job was admitted")
        self.assertFalse(status.active)

        with self.assertRaises(asyncio.CancelledError):
            async with status.released_job_scope():
                raise asyncio.CancelledError
        self.assertFalse(status.active)

    async def test_abort_during_scope_sets_error_and_closes_controller(self) -> None:
        status = PhomemoReleasedStatus()
        with self.assertRaisesRegex(RuntimeError, "connection.*closed"):
            async with status.released_job_scope():
                status.abort()
        self.assertTrue(status.closed)
        self.assertFalse(status.active)

    async def test_disconnect_preserves_the_first_active_job_fault(self) -> None:
        status = PhomemoReleasedStatus()
        with self.assertRaisesRegex(RuntimeError, "print failure"):
            async with status.released_job_scope():
                status.receive(b"\x1a\x0f\x02")
                status.abort()
        self.assertTrue(status.closed)
        self.assertFalse(status.active)

    async def test_zero_delay_still_checks_readiness_and_invalid_delays_reject(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        transport = _PacingTransport()
        status.receive(b"\x1a\x03\xa9")
        with self.assertRaisesRegex(RuntimeError, "overheated"):
            await status.pace(transport, 0.0)

        for delay in (-0.01, math.inf, math.nan, 300.0):
            with self.subTest(delay=delay):
                ready_status = PhomemoReleasedStatus()
                with self.assertRaises(ValueError):
                    await ready_status.pace(transport, delay)

    async def test_acknowledgment_wakes_wait_but_does_not_end_estimated_pacing(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        status.mark_native_observing()
        transport = _PacingTransport()
        transport.status = status
        transport.next_reply = b"\x1a\x0f\x0c"
        started = time.monotonic()

        await status.pace(transport, 0.04)

        self.assertGreaterEqual(time.monotonic() - started, 0.035)
        self.assertGreaterEqual(len(transport.waits), 2)

    async def test_wait_return_history_is_not_replayed_into_status_decoder(
        self,
    ) -> None:
        status = PhomemoReleasedStatus()
        status.mark_native_observing()
        transport = _PacingTransport()
        transport.return_history_only = b"\x1a\x05\x99"

        await status.pace(transport, 0.002)
        status.raise_if_not_ready()

    async def test_unobserved_pacing_uses_short_async_sleeps(self) -> None:
        status = PhomemoReleasedStatus()
        transport = _PacingTransport()
        started = time.monotonic()

        await status.pace(transport, 0.025)

        self.assertGreaterEqual(time.monotonic() - started, 0.02)
        self.assertEqual(transport.waits, [])

    async def test_immediate_optional_timeouts_do_not_spin(self) -> None:
        status = PhomemoReleasedStatus()
        status.mark_native_observing()
        transport = _PacingTransport()
        transport.immediate_timeout = True
        started = time.monotonic()

        await status.pace(transport, 0.025)

        self.assertGreaterEqual(time.monotonic() - started, 0.02)
        self.assertEqual(len(transport.waits), 1)


class PhomemoReleasedClientStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_classic_connect_attaches_and_public_print_keeps_wire_bytes(
        self,
    ) -> None:
        reference = _client("m02")
        reference_image = _image(height=10)
        reference_writes: list[bytes] = []

        async def capture_reference(data: bytes) -> None:
            reference_writes.append(data)

        reference._send = capture_reference
        try:
            await reference.print_images([reference_image], dither=False)
        finally:
            reference_image.close()

        client = _client("m02")
        transport = _FakeSppBackend("classic")
        client.transport = transport
        image = _image(height=10)
        transport.write_hook = lambda _data: transport.dispatch(b"\x1a\x0f\x0c")
        try:
            self.assertTrue(await client.connect())
            status = client._released_status
            self.assertIsNotNone(status)
            assert status is not None
            self.assertTrue(status.observing)
            started = time.monotonic()
            await client.print_images([image], dither=False)
            elapsed = time.monotonic() - started
            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            image.close()

        self.assertGreaterEqual(elapsed, 0.12)
        self.assertEqual(b"".join(transport.writes), b"".join(reference_writes))
        self.assertEqual(len(transport.writes), 1)
        self.assertFalse(any(b"\x1f\x11\x12" in item for item in transport.writes))
        self.assertEqual(
            hashlib.sha256(b"".join(transport.writes)).digest(),
            hashlib.sha256(b"".join(reference_writes)).digest(),
        )

    async def test_ble_attachment_drives_wait_callback_before_predicate(self) -> None:
        client = _client("t02")
        transport = _FakeSppBackend("ble")
        transport.notifications.append(b"\x1a\x0f\x0c")
        client.transport = transport
        image = _image(height=2)
        status: PhomemoReleasedStatus | None = None
        try:
            self.assertTrue(await client.connect())
            status = client._released_status
            self.assertIsNotNone(status)
            assert status is not None
            self.assertTrue(status.observing)
            await client.print_images([image], dither=False)
        finally:
            image.close()

        self.assertEqual(transport.events[:2], ["connect", "attach"])
        self.assertEqual(len(transport.writes), 1)
        assert status is not None
        status.raise_if_not_ready()

    async def test_pages_are_built_first_and_paced_in_order_with_per_page_delays(
        self,
    ) -> None:
        client = _client("m02s", width_px=4)
        transport = _FakeSppBackend("classic")
        client.transport = transport
        image = _image(width=10, height=2)
        built_heights: list[int] = []
        original_builder = client._build_released_job
        delays: list[float] = []

        def record_build(
            image: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            built_heights.append(image.height)
            return original_builder(
                image,
                variant=variant,
                paper_mode=paper_mode,
                density=density,
                feed_count=feed_count,
                is_first_page=is_first_page,
                is_last_page=is_last_page,
                dither=dither,
            )

        async def record_pace(
            status: PhomemoReleasedStatus,
            pace_transport: PhomemoPacingTransport,
            delay: float,
        ) -> None:
            _ = pace_transport
            status.raise_if_not_ready()
            self.assertEqual(len(built_heights), 3)
            delays.append(delay)

        client._build_released_job = record_build
        try:
            await client.connect()
            status = client._released_status
            self.assertIsNotNone(status)
            assert status is not None
            with patch.object(PhomemoReleasedStatus, "pace", new=record_pace):
                await client.print_images([image], split_mode=True, dither=False)
        finally:
            image.close()

        self.assertEqual(built_heights, [2, 2, 2])
        self.assertEqual(delays, [2 * 0.009317] * 3)
        self.assertEqual(len(transport.writes), 3)

    async def test_fault_stops_later_chunks_without_replaying_pixels(self) -> None:
        client = _client("m02", width_px=4)
        transport = _FakeSppBackend("classic")
        client.transport = transport
        image = _image(width=10, height=2)
        built = 0
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        def build_large_page(
            image: Image.Image,
            *,
            variant: str,
            paper_mode: PaperMode | None,
            density: int,
            feed_count: int,
            is_first_page: bool,
            is_last_page: bool,
            dither: bool,
        ) -> bytes:
            nonlocal built
            _ = (
                image,
                variant,
                paper_mode,
                density,
                feed_count,
                is_first_page,
                is_last_page,
                dither,
            )
            built += 1
            return bytes((65 + built,)) * (64 * 1024 + 1)

        def fail_then_recover(_data: bytes) -> None:
            transport.dispatch(b"\x1a\x0f\x0c\x1a\x05\x99\x1a\x05\x98")

        client._build_released_job = build_large_page
        transport.write_hook = fail_then_recover
        status: PhomemoReleasedStatus | None = None
        try:
            await client.connect()
            status = client._released_status
            self.assertIsNotNone(status)
            assert status is not None
            with (
                patch.object(
                    phomemo_client_module,
                    "ProtocolJobSpool",
                    side_effect=capture_spool,
                ),
                self.assertRaisesRegex(RuntimeError, "cover opened"),
            ):
                await client.print_images([image], split_mode=True, dither=False)
        finally:
            image.close()

        self.assertEqual(built, 3)
        self.assertEqual(len(transport.writes), 1)
        self.assertEqual(transport.writes[0], b"B" * (64 * 1024))
        self.assertEqual(len(captured_spools), 1)
        self.assertTrue(captured_spools[0]._file.closed)
        assert status is not None
        self.assertFalse(status.active)

    async def test_cancel_closes_spool_and_releases_active_scope(self) -> None:
        client = _client("m02")
        transport = _FakeSppBackend("classic")
        transport.block_write = True
        client.transport = transport
        image = _image()
        captured_spools: list[ProtocolJobSpool] = []
        real_spool = ProtocolJobSpool

        def capture_spool() -> ProtocolJobSpool:
            spool = real_spool()
            captured_spools.append(spool)
            return spool

        task: asyncio.Task[None] | None = None
        status: PhomemoReleasedStatus | None = None
        try:
            await client.connect()
            status = client._released_status
            self.assertIsNotNone(status)
            assert status is not None
            with patch.object(
                phomemo_client_module,
                "ProtocolJobSpool",
                side_effect=capture_spool,
            ):
                task = asyncio.create_task(client.print_images([image], dither=False))
                await asyncio.wait_for(transport.write_started.wait(), timeout=1.0)
                self.assertTrue(status.active)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            self.assertEqual(image.getpixel((0, 0)), 0)
        finally:
            if task is not None and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            image.close()

        self.assertEqual(len(captured_spools), 1)
        self.assertTrue(captured_spools[0]._file.closed)
        assert status is not None
        self.assertFalse(status.active)

    async def test_disconnect_clears_native_callback_before_physical_disconnect(
        self,
    ) -> None:
        client = _client("m02")
        transport = _FakeSppBackend("classic")
        client.transport = transport
        await client.connect()
        status = client._released_status
        self.assertIsNotNone(status)
        assert status is not None

        await client.disconnect()

        self.assertEqual(transport.events[-2:], ["clear", "disconnect"])
        self.assertTrue(status.closed)
        self.assertIsNone(transport.notify_callback)
        self.assertIsNone(client._released_status)

    async def test_disconnect_still_reaches_transport_when_callback_cleanup_fails(
        self,
    ) -> None:
        client = _client("m02")
        transport = _FakeSppBackend("classic")
        client.transport = transport
        await client.connect()
        transport.fail_callback_clear = True

        with self.assertRaisesRegex(RuntimeError, "callback cleanup failed"):
            await client.disconnect()

        self.assertEqual(transport.events[-2:], ["clear", "disconnect"])
        self.assertFalse(transport.connected)

    async def test_unobservable_transport_warns_and_keeps_estimated_delay(self) -> None:
        client = _client("m02")
        transport = _FakeSppBackend("none")
        client.transport = transport
        image = _image(height=2)
        status: PhomemoReleasedStatus | None = None
        try:
            with patch.object(
                phomemo_client_module.reporting, "DUMMY_REPORTER"
            ) as reporter:
                await client.connect()
                status = client._released_status
                self.assertIsNotNone(status)
                assert status is not None
                self.assertFalse(status.observing)
                started = time.monotonic()
                await client.print_images([image], dither=False)
                elapsed = time.monotonic() - started
                reporter.warning.assert_called_once()
        finally:
            image.close()

        self.assertGreaterEqual(elapsed, 0.02)
        self.assertEqual(len(transport.writes), 1)

    async def test_legacy_and_m02_pro_do_not_attach_released_helper(self) -> None:
        for variant in (None, "m02_pro"):
            with self.subTest(variant=variant):
                client = _client(variant)
                transport = _FakeSppBackend("classic")
                client.transport = transport

                self.assertTrue(await client.connect())
                self.assertIsNone(client._released_status)
                self.assertIsNone(transport.notify_callback)
                self.assertIsNone(transport.controller)


if __name__ == "__main__":
    unittest.main()
