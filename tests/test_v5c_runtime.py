from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import Callable
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from catlabel import reporting
from catlabel.printing.runtime.base import PreparedRuntimeContext
from catlabel.printing.runtime.session import RuntimeConnectionSession
from catlabel.printing.runtime.v5c import V5CRuntimeController
from catlabel.printing.send import send_prepared_job
from catlabel.protocol import (
    ProtocolFamily,
    ProtocolJob,
    ProtocolWriteChannel,
)
from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.v5c import (
    V5C_NOTIFY_PAUSE,
    V5C_NOTIFY_RESUME,
    V5C_QUERY_STATUS_PACKET,
    _build_a4_frames,
    _build_a5_frames,
    _settings_payload,
    build_job,
)
from catlabel.protocol.packet import make_packet
from catlabel.protocol.steps import ProtocolStepOperation
from catlabel.protocol.types import ImageEncoding, ImagePipelineConfig
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


def _request(raster: RasterBuffer, encoding: ImageEncoding) -> PrintJobRequest:
    return PrintJobRequest(
        raster_set=RasterSet.from_single(raster),
        image_pipeline=ImagePipelineConfig((raster.pixel_format,), encoding),
        is_text=True,
        speed=1,
        energy=1,
        blackening=3,
        lsb_first=False,
        protocol_family=ProtocolFamily.V5C,
        protocol_variant=None,
        feed_padding=0,
        dev_dpi=203,
    )


def _job(*, wait: bool = True) -> ProtocolJob:
    plan = build_job(
        _request(
            RasterBuffer([0, 1, 0, 1, 1, 0, 1, 0] * 2, 8, PixelFormat.BW1),
            ImageEncoding.V5C_A4,
        )
    )
    return ProtocolJob(payload=plan.payload, steps=plan.steps, wait_for_completion=wait)


def _status(code: int) -> bytes:
    return make_packet(0xA1, bytes([code]), ProtocolFamily.V5C)


class _V5CConnection:
    def __init__(
        self,
        *,
        can_wait: bool = True,
        notifications_by_write: tuple[tuple[bytes, ...], ...] = (),
        wait_notifications: tuple[bytes, ...] = (),
        block_wait: bool = False,
        fail_write_index: int | None = None,
        notifications_before_job: tuple[bytes, ...] = (),
    ) -> None:
        self.wait_available = can_wait
        self.notifications_by_write = list(notifications_by_write)
        self.wait_notifications = list(wait_notifications)
        self.block_wait = block_wait
        self.fail_write_index = fail_write_index
        self.notifications_before_job = notifications_before_job
        self.controller: V5CRuntimeController | None = None
        self.runtime_session: RuntimeConnectionSession | None = None
        self.writes: list[bytes] = []
        self.control_writes: list[bytes] = []
        self.active_at_write: list[bool] = []
        self.wait_calls: list[tuple[str, float, bool]] = []
        self.wait_started = asyncio.Event()
        self.wait_gate = asyncio.Event()
        self.flow: list[tuple[bool, bytes]] = []
        self.warnings: list[tuple[str, str]] = []
        self.send_calls = 0

    @property
    def notify_started(self) -> bool:
        return self.wait_available

    def can_wait_for_notification(self) -> bool:
        return self.wait_available

    def can_send_control_packet(self) -> bool:
        return True

    def can_send_standard_payload(self) -> bool:
        return True

    def can_send_bulk_payload(self) -> bool:
        return True

    async def attach_runtime_controller(
        self, controller: V5CRuntimeController, *, timeout: float = 1.0
    ) -> None:
        if self.controller is controller and self.runtime_session is not None:
            return
        if self.controller is not None:
            controller.adopt_previous(self.controller)
        self.controller = controller
        self.runtime_session = RuntimeConnectionSession(
            self, reporter=reporting.DUMMY_REPORTER
        )
        await controller.initialize_connection(
            self.runtime_session, mtu_size=128, timeout=timeout
        )
        for payload in self.notifications_before_job:
            self.deliver(payload)

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        _ = timeout
        self.control_writes.append(packet)
        return True

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow.append((paused, payload))

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))

    def deliver(self, payload: bytes) -> None:
        if self.controller is None or self.runtime_session is None:
            raise AssertionError("V5C controller is not attached")
        self.controller.handle_notification(self.runtime_session, payload)

    @property
    def bound_controller(self) -> V5CRuntimeController:
        if self.controller is None:
            raise AssertionError("V5C controller is not attached")
        return self.controller

    @property
    def bound_session(self) -> RuntimeConnectionSession:
        if self.runtime_session is None:
            raise AssertionError("V5C controller is not attached")
        return self.runtime_session

    async def send_standard_payload(self, data: bytes) -> None:
        self.send_calls += 1
        self.active_at_write.append(
            bool(self.controller and self.controller.debug_snapshot()["active"])
        )
        self.writes.append(bytes(data))
        if self.notifications_by_write:
            for payload in self.notifications_by_write.pop(0):
                self.deliver(payload)
        if self.fail_write_index == self.send_calls:
            raise OSError("standard write failed")

    async def wait_for_notification(
        self,
        label: str,
        match: Callable[[bytes], bool],
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.wait_calls.append((label, timeout, required))
        if self.block_wait:
            self.wait_started.set()
            await self.wait_gate.wait()
            return None
        notifications = tuple(self.wait_notifications)
        self.wait_notifications.clear()
        for payload in notifications:
            self.deliver(payload)
            if match(payload):
                return payload
        return None


class V5CProtocolPlanTests(unittest.TestCase):
    def test_three_phase_plan_preserves_legacy_wire_bytes_for_all_encodings(
        self,
    ) -> None:
        cases = (
            (
                RasterBuffer([0, 1, 0, 1, 1, 0, 1, 0] * 2, 8, PixelFormat.BW1),
                ImageEncoding.V5C_A4,
            ),
            (
                RasterBuffer([0, 1, 2, 3, 4, 5, 6, 7] * 2, 8, PixelFormat.GRAY4),
                ImageEncoding.V5C_A5,
            ),
            (
                RasterBuffer(
                    [0, 32, 64, 96, 128, 160, 192, 255] * 2,
                    8,
                    PixelFormat.GRAY8,
                ),
                ImageEncoding.V5C_A5,
            ),
        )
        for raster, encoding in cases:
            with self.subTest(
                encoding=encoding.value, format=raster.pixel_format.value
            ):
                request = _request(raster, encoding)
                plan = build_job(request)
                old_setup = make_packet(
                    0xA2,
                    _settings_payload(request.blackening, request.is_text),
                    request.protocol_family,
                ) + make_packet(0xA3, b"\x01", request.protocol_family)
                old_raster = (
                    _build_a5_frames(request)
                    if encoding is ImageEncoding.V5C_A5
                    else _build_a4_frames(request)
                )
                old_finalize = (
                    make_packet(0xA6, b"\x30\x00", request.protocol_family)
                    + V5C_QUERY_STATUS_PACKET
                )

                self.assertEqual(
                    [step.label for step in plan.steps],
                    ["V5C setup", "V5C raster", "V5C finalize"],
                )
                self.assertEqual(
                    [step.operation for step in plan.steps],
                    [ProtocolStepOperation.SEND] * 3,
                )
                self.assertEqual(
                    [step.write_channel for step in plan.steps],
                    [ProtocolWriteChannel.STANDARD] * 3,
                )
                self.assertEqual(
                    [step.data for step in plan.steps],
                    [old_setup, old_raster, old_finalize],
                )
                self.assertEqual(plan.payload, old_setup + old_raster + old_finalize)


class V5CRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def _send(
        self,
        connection: _V5CConnection,
        job: ProtocolJob | None = None,
        *,
        controller: V5CRuntimeController | None = None,
    ) -> V5CRuntimeController:
        active = controller or V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5C),
                connection,
                _job() if job is None else job,
                timeout=0.01,
                runtime_context=PreparedRuntimeContext(runtime_controller=active),
            )
        return active

    async def test_protocol_and_raw_jobs_send_same_three_phases_in_job_scope(
        self,
    ) -> None:
        plan_job = _job()
        raw_job = ProtocolJob(payload=plan_job.payload, wait_for_completion=False)
        for job in (plan_job, raw_job):
            with self.subTest(has_steps=bool(job.steps)):
                connection = _V5CConnection(
                    notifications_by_write=((), (), (_status(0x00),))
                )
                await self._send(connection, job)
                self.assertEqual(
                    connection.writes, [step.data for step in plan_job.steps]
                )
                self.assertEqual(connection.active_at_write, [True, True, True])
                self.assertFalse(connection.bound_controller.debug_snapshot()["active"])

    async def test_fresh_idle_during_finalizer_completes_without_waiting_again(
        self,
    ) -> None:
        connection = _V5CConnection(notifications_by_write=((), (), (_status(0x00),)))

        await self._send(connection)

        self.assertEqual(len(connection.writes), 3)
        self.assertEqual(connection.wait_calls, [])
        self.assertEqual(
            connection.bound_controller.debug_snapshot()["received_byte_count"],
            len(_status(0x00)),
        )

    async def test_idle_before_finalizer_is_ignored_and_wait_times_out(self) -> None:
        connection = _V5CConnection(
            notifications_by_write=((_status(0x00),), (), ()),
        )

        with self.assertRaisesRegex(TimeoutError, "fresh V5C page completion"):
            await self._send(connection)

        self.assertEqual(len(connection.writes), 3)
        self.assertEqual(connection.wait_calls[0][0], "V5C print completion")
        self.assertGreaterEqual(connection.wait_calls[0][1], 59.9)
        self.assertFalse(connection.wait_calls[0][2])

    async def test_old_partial_idle_frame_is_fenced_from_finalizer(self) -> None:
        idle = _status(0x00)
        connection = _V5CConnection(
            notifications_before_job=(idle[:4],),
            notifications_by_write=((), (), (idle[4:],)),
        )

        with self.assertRaisesRegex(TimeoutError, "fresh V5C page completion"):
            await self._send(connection)

    async def test_old_partial_fault_frame_remains_fatal_inside_new_scope(self) -> None:
        fault = _status(0x04)
        connection = _V5CConnection()
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        connection.deliver(fault[:4])

        with self.assertRaisesRegex(RuntimeError, "overheated"):
            async with controller.job_scope(
                connection.bound_session, _job(wait=False), timeout=0.01
            ):
                connection.deliver(fault[4:])

    async def test_busy_after_observed_idle_invalidates_completion_at_scope_exit(
        self,
    ) -> None:
        connection = _V5CConnection(notifications_by_write=((), (), (_status(0x00),)))
        controller = V5CRuntimeController()
        job = _job()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)

        with self.assertRaisesRegex(TimeoutError, "current at job scope exit"):
            async with controller.job_scope(
                connection.bound_session, job, timeout=0.01
            ):
                await controller.send_protocol_steps(
                    connection.bound_session, job.steps, timeout=0.01
                )
                await controller.wait_for_completion(
                    connection.bound_session, timeout=0.01
                )
                connection.deliver(_status(0x80))

    async def test_idle_then_busy_coalesced_requires_a_later_idle(self) -> None:
        connection = _V5CConnection(
            notifications_by_write=((), (), (_status(0x00) + _status(0x80),)),
            wait_notifications=(_status(0x00),),
        )

        await self._send(connection)

        self.assertEqual(len(connection.wait_calls), 1)
        self.assertTrue(
            connection.bound_controller.debug_snapshot()["print_complete_seen"]
        )

    async def test_fragmented_and_coalesced_notifications_are_decoded(self) -> None:
        idle = _status(0x00)
        connection = _V5CConnection(
            notifications_by_write=((), (), (idle[:2], idle[2:] + _status(0x80))),
            wait_notifications=(_status(0x00),),
        )

        await self._send(connection)

        snapshot = connection.bound_controller.debug_snapshot()
        self.assertEqual(
            snapshot["received_byte_count"], 2 * len(idle) + len(_status(0x80))
        )
        self.assertTrue(snapshot["print_complete_seen"])

    async def test_fault_before_first_chunk_aborts_before_any_payload_write(
        self,
    ) -> None:
        connection = _V5CConnection()
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        session = connection.bound_session
        job = _job(wait=False)

        with self.assertRaisesRegex(RuntimeError, "paper_out"):
            async with controller.job_scope(session, job, timeout=0.01):
                connection.deliver(_status(0x01))
                await controller.before_write(session, size=5, timeout=0.01)

        self.assertEqual(connection.writes, [])

    async def test_concurrent_job_scopes_are_rejected(self) -> None:
        connection = _V5CConnection()
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)

        async with controller.job_scope(
            connection.bound_session, _job(wait=False), timeout=0.01
        ):
            with self.assertRaisesRegex(RuntimeError, "active print job"):
                async with controller.job_scope(
                    connection.bound_session, _job(wait=False), timeout=0.01
                ):
                    self.fail("overlapping V5C scope was entered")

    async def test_fault_during_a_phase_stops_later_phase_writes_without_retry(
        self,
    ) -> None:
        connection = _V5CConnection(notifications_by_write=((_status(0x04),), (), ()))

        with self.assertRaisesRegex(RuntimeError, "overheated"):
            await self._send(connection, _job(wait=False))

        self.assertEqual(len(connection.writes), 1)

    async def test_fault_during_completion_wait_is_reported(self) -> None:
        connection = _V5CConnection(wait_notifications=(_status(0x08),))

        with self.assertRaisesRegex(RuntimeError, "low_battery"):
            await self._send(connection)

        self.assertEqual(len(connection.writes), 3)
        self.assertEqual(len(connection.wait_calls), 1)

    async def test_fault_after_idle_completion_remains_sticky_until_scope_exit(
        self,
    ) -> None:
        connection = _V5CConnection(notifications_by_write=((), (), (_status(0x00),)))
        controller = V5CRuntimeController()
        job = _job()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        session = connection.bound_session

        with self.assertRaisesRegex(RuntimeError, "printer_error"):
            async with controller.job_scope(session, job, timeout=0.01):
                await controller.send_protocol_steps(session, job.steps, timeout=0.01)
                await controller.wait_for_completion(session, timeout=0.01)
                connection.deliver(_status(0x09))

    async def test_healthy_status_does_not_clear_active_job_fault(self) -> None:
        connection = _V5CConnection()
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        session = connection.bound_session

        with self.assertRaisesRegex(RuntimeError, "paper_out"):
            async with controller.job_scope(session, _job(wait=False), timeout=0.01):
                connection.deliver(_status(0x02))
                connection.deliver(_status(0x00))

        self.assertEqual(controller.debug_snapshot()["last_error_status"], 0x02)
        connection.deliver(_status(0x00))
        self.assertIsNone(controller.debug_snapshot()["last_error_status"])

    async def test_every_nonhealthy_status_maps_to_runtime_fault(self) -> None:
        cases = (
            (0x01, "paper_out"),
            (0x02, "paper_out"),
            (0x03, "paper_out"),
            (0x04, "overheated"),
            (0x08, "low_battery"),
            (0x09, "printer_error"),
        )
        for code, fault in cases:
            with self.subTest(status=code):
                connection = _V5CConnection(notifications_by_write=((_status(code),),))
                with self.assertRaisesRegex(RuntimeError, fault):
                    await self._send(connection, _job(wait=False))

    async def test_charging_status_never_completes_a_waiting_page(self) -> None:
        connection = _V5CConnection(
            notifications_by_write=((), (), (_status(0x10) + _status(0x11),))
        )
        with self.assertRaisesRegex(TimeoutError, "fresh V5C page completion"):
            await self._send(connection)
        self.assertEqual(len(connection.writes), 3)

    async def test_missing_observer_fails_before_any_pixel_phase(self) -> None:
        connection = _V5CConnection(can_wait=False)

        with self.assertRaisesRegex(RuntimeError, "observer unavailable"):
            await self._send(connection)

        self.assertEqual(connection.writes, [])
        self.assertEqual(len(connection.control_writes), 1)

    async def test_malformed_or_mixed_step_plans_are_rejected_before_write(
        self,
    ) -> None:
        valid = _job(wait=False)
        setup, raster, finalize = valid.steps
        invalid_plans = (
            (
                setup,
                replace(raster, write_channel=ProtocolWriteChannel.CONTROL),
                finalize,
            ),
            (setup, replace(raster, operation=ProtocolStepOperation.QUERY), finalize),
            (
                setup,
                replace(raster, data=make_packet(0xA4, b"", ProtocolFamily.V5C)),
                finalize,
            ),
            (
                setup,
                replace(
                    raster,
                    data=make_packet(0xA4, b"x", ProtocolFamily.V5C)
                    + make_packet(0xA4, b"xy", ProtocolFamily.V5C),
                ),
                finalize,
            ),
            (
                replace(
                    setup,
                    data=make_packet(0xA2, b"\x09\xff", ProtocolFamily.V5C)
                    + make_packet(0xA3, b"\x01", ProtocolFamily.V5C),
                ),
                raster,
                finalize,
            ),
            (setup, raster),
        )
        for steps in invalid_plans:
            with self.subTest(step_count=len(steps)):
                connection = _V5CConnection()
                with self.assertRaises(ValueError):
                    await self._send(
                        connection,
                        ProtocolJob(steps=steps, wait_for_completion=False),
                    )
                self.assertEqual(connection.writes, [])

    async def test_raw_payload_rejects_extra_or_corrupt_frames_before_write(
        self,
    ) -> None:
        valid = _job(wait=False)
        for payload in (
            valid.payload + _status(0x00),
            valid.payload[:-1],
            valid.payload[: len(valid.steps[0].data)]
            + _status(0x00)
            + b"".join(step.data for step in valid.steps[1:]),
        ):
            with self.subTest(size=len(payload)):
                connection = _V5CConnection()
                with self.assertRaises(ValueError):
                    await self._send(
                        connection,
                        ProtocolJob(payload=payload, wait_for_completion=False),
                    )
                self.assertEqual(connection.writes, [])

    async def test_standard_write_failure_is_not_retried(self) -> None:
        connection = _V5CConnection(fail_write_index=2)

        with self.assertRaisesRegex(OSError, "standard write failed"):
            await self._send(connection, _job(wait=False))

        self.assertEqual(len(connection.writes), 2)

    async def test_stop_wakes_waiter_and_scope_does_not_leak_into_reuse(self) -> None:
        connection = _V5CConnection(block_wait=True)
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        with self.assertRaisesRegex(RuntimeError, "connection closed"):
            sender = asyncio.create_task(
                send_prepared_job(
                    SimpleNamespace(protocol_family=ProtocolFamily.V5C),
                    connection,
                    _job(),
                    timeout=0.01,
                    runtime_context=PreparedRuntimeContext(
                        runtime_controller=controller
                    ),
                )
            )
            await connection.wait_started.wait()
            await controller.stop(connection.bound_session)
            await sender

        self.assertFalse(controller.debug_snapshot()["active"])
        connection.wait_available = True
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await controller.initialize_connection(
                connection.bound_session, mtu_size=128, timeout=0.01
            )
        connection.block_wait = False
        connection.notifications_by_write = [(), (), (_status(0x00),)]
        await self._send(connection, _job(), controller=controller)
        self.assertFalse(controller.debug_snapshot()["active"])

    async def test_cancellation_cleans_scope_and_cancels_notification_wait(
        self,
    ) -> None:
        connection = _V5CConnection(block_wait=True)
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)

        sender = asyncio.create_task(
            send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5C),
                connection,
                _job(),
                timeout=0.01,
                runtime_context=PreparedRuntimeContext(runtime_controller=controller),
            )
        )
        await connection.wait_started.wait()
        sender.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await sender

        self.assertFalse(controller.debug_snapshot()["active"])
        connection.block_wait = False
        connection.notifications_by_write = [(), (), (_status(0x00),)]
        await self._send(connection, _job(), controller=controller)
        self.assertFalse(controller.debug_snapshot()["active"])

    async def test_private_thread_notification_wakes_async_completion_wait(
        self,
    ) -> None:
        connection = _V5CConnection(block_wait=True)
        controller = V5CRuntimeController()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)

        sender = asyncio.create_task(
            send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5C),
                connection,
                _job(),
                timeout=0.01,
                runtime_context=PreparedRuntimeContext(runtime_controller=controller),
            )
        )
        await connection.wait_started.wait()
        callback_thread = threading.Thread(
            target=connection.deliver, args=(_status(0x00),)
        )
        callback_thread.start()
        await asyncio.to_thread(callback_thread.join)
        await sender

        self.assertFalse(controller.debug_snapshot()["active"])
        self.assertEqual(len(connection.writes), 3)

    async def test_adoption_preserves_partial_decoder_and_never_shares_active_scope(
        self,
    ) -> None:
        old = V5CRuntimeController()
        connection = _V5CConnection()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(old, timeout=0.01)
        connection.deliver(_status(0x00)[:3])
        adopted = V5CRuntimeController()
        adopted.adopt_previous(old)
        self.assertIs(adopted._decoder, old._decoder)
        self.assertIsNot(adopted._state, old._state)
        self.assertEqual(adopted.debug_snapshot()["received_byte_count"], 3)

        async with old.job_scope(
            connection.bound_session, _job(wait=False), timeout=0.01
        ):
            candidate = V5CRuntimeController()
            candidate.adopt_previous(old)
            self.assertIsNot(candidate._decoder, old._decoder)
            self.assertFalse(candidate.debug_snapshot()["active"])

    async def test_height_and_auth_telemetry_keep_existing_valid_shapes(self) -> None:
        controller = V5CRuntimeController()
        connection = _V5CConnection()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        connection.deliver(make_packet(0xAA, b"\x01\x00", ProtocolFamily.V5C))
        self.assertIsNone(controller.debug_snapshot()["max_print_height"])
        connection.deliver(make_packet(0xAA, b"\x20\x03\x00\x00", ProtocolFamily.V5C))
        connection.deliver(make_packet(0xA9, b"\x01\x02\x03\x04", ProtocolFamily.V5C))
        snapshot = controller.debug_snapshot()
        self.assertEqual(snapshot["max_print_height"], 800)
        self.assertEqual(snapshot["last_auth_payload"], b"\x01\x02\x03\x04")
        self.assertEqual(snapshot["device_serial"], "01020304")
        self.assertTrue(snapshot["serial_valid"])

    async def test_existing_flow_markers_are_still_forwarded(self) -> None:
        controller = V5CRuntimeController()
        connection = _V5CConnection()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        connection.deliver(V5C_NOTIFY_PAUSE)
        connection.deliver(V5C_NOTIFY_RESUME)
        self.assertEqual(
            connection.flow,
            [(True, V5C_NOTIFY_PAUSE), (False, V5C_NOTIFY_RESUME)],
        )

    async def test_fragmented_and_coalesced_flow_uses_the_same_stream_decoder(
        self,
    ) -> None:
        controller = V5CRuntimeController()
        connection = _V5CConnection()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        stream = V5C_NOTIFY_PAUSE + _status(0x80) + V5C_NOTIFY_RESUME
        connection.deliver(stream[:5])
        self.assertEqual(connection.flow, [])
        connection.deliver(stream[5:])
        self.assertEqual(
            connection.flow, [(True, V5C_NOTIFY_PAUSE), (False, V5C_NOTIFY_RESUME)]
        )
        self.assertEqual(
            controller.debug_snapshot()["received_byte_count"], len(stream)
        )

    async def test_known_fault_blocks_a_new_job_until_a_fresh_healthy_status(
        self,
    ) -> None:
        controller = V5CRuntimeController()
        connection = _V5CConnection()
        with patch("catlabel.printing.runtime.v5c.asyncio.sleep", new=AsyncMock()):
            await connection.attach_runtime_controller(controller, timeout=0.01)
        connection.deliver(_status(0x04))
        with self.assertRaisesRegex(RuntimeError, "overheated"):
            async with controller.job_scope(
                connection.bound_session, _job(wait=False), timeout=0.01
            ):
                self.fail("A known device fault must fail before starting the job")
        self.assertEqual(connection.writes, [])
        connection.deliver(_status(0x00))
        job = _job(wait=False)
        async with controller.job_scope(connection.bound_session, job, timeout=0.01):
            await controller.send_protocol_steps(
                connection.bound_session, job.steps, timeout=0.01
            )
        self.assertEqual(len(connection.writes), 3)


if __name__ == "__main__":
    unittest.main()
