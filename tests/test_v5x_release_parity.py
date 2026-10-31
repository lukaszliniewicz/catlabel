from __future__ import annotations

import asyncio
import unittest
from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import patch

from catlabel.printing.runtime.v5x import V5XRuntimeController
from catlabel.protocol import ProtocolFamily
from catlabel.protocol.families.base import PrintJobRequest, SplitWritePlan
from catlabel.protocol.families.v5x import (
    BEHAVIOR,
    V5X_FINALIZE_PACKET,
    V5X_GET_SERIAL_PACKET,
    build_job,
    build_sign_response,
    split_print_stream,
)
from catlabel.protocol.packet import make_packet
from catlabel.protocol.plan import ProtocolPlan
from catlabel.protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolStep,
    ProtocolStepOperation,
    ProtocolWriteChannel,
)
from catlabel.protocol.types import ImageEncoding, ImagePipelineConfig, PaperMode
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet
from tests.runtime_session_fake import RuntimeSessionFake


def _a9_packet(height: int, mode: int) -> bytes:
    return (
        bytes.fromhex("2221A9000400")
        + height.to_bytes(2, "little")
        + bytes([0x30, mode, 0x00, 0x00])
    )


def _request(
    raster: RasterBuffer,
    *,
    encoding: ImageEncoding,
    paper_mode: PaperMode,
    can_print_label: bool = False,
) -> PrintJobRequest:
    return PrintJobRequest(
        raster_set=RasterSet.from_single(raster),
        image_pipeline=ImagePipelineConfig((raster.pixel_format,), encoding),
        is_text=False,
        speed=1,
        energy=1,
        blackening=3,
        lsb_first=False,
        protocol_family=ProtocolFamily.V5X,
        protocol_variant=None,
        feed_padding=0,
        dev_dpi=203,
        can_print_label=can_print_label,
        paper_mode=paper_mode,
    )


class _V5XSession(RuntimeSessionFake):
    def __init__(self) -> None:
        self.control: list[bytes] = []
        self.bulk: list[bytes] = []
        self.atomic: list[bytes] = []
        self.debug: list[str] = []
        self.warnings: list[tuple[str, str]] = []
        self.a9_reply: bytes | None = make_packet(0xA9, b"\x00", ProtocolFamily.V5X)
        self.control_available = True
        self.atomic_available = True
        self.bulk_available = True
        self.fail_control: set[bytes] = set()
        self.block_control = False
        self.fail_any_control = False
        self.control_started = asyncio.Event()
        self.release_control = asyncio.Event()
        self.matches: list[bool] = []
        self.can_wait = False
        self.flow_paused = False
        self.events: list[tuple[str, bytes | float]] = []
        self.a9_replies: list[bytes | None] | None = None
        self.atomic_timeouts: list[float] = []
        self.atomic_error: Exception | None = None
        self.atomic_hook: Callable[[], None] | None = None

    def can_send_control_packet(self) -> bool:
        return self.control_available

    def can_send_bulk_payload(self) -> bool:
        return self.bulk_available

    def can_send_control_packet_wait_notification(self) -> bool:
        return self.atomic_available

    def can_wait_for_notification(self) -> bool:
        return self.can_wait

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.control.append(packet)
        self.events.append(("control", packet))
        if self.fail_any_control or packet in self.fail_control:
            return False
        if self.block_control:
            self.control_started.set()
            await self.release_control.wait()
        return True

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        self.bulk.append(data)
        self.events.append(("bulk", data))
        return True

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        self.atomic.append(packet)
        self.events.append(("atomic", packet))
        self.atomic_timeouts.append(timeout)
        if self.atomic_hook is not None:
            self.atomic_hook()
        if self.atomic_error is not None:
            raise self.atomic_error
        reply = self.a9_reply
        if self.a9_replies is not None and self.a9_replies:
            reply = self.a9_replies.pop(0)
        self.matches.append(bool(reply and match(reply)))
        return reply

    def report_debug(self, message: str) -> None:
        self.debug.append(message)

    def report_warning(self, *, short: str, detail: str) -> None:
        self.warnings.append((short, detail))

    def set_flow_paused(self, paused: bool, *, payload: bytes = b"") -> None:
        self.flow_paused = paused


class V5XReleaseParityTests(unittest.TestCase):
    def test_builder_emits_explicit_control_bulk_control_plan(self) -> None:
        raster = RasterBuffer([0, 1, 0, 1, 1, 0, 1, 0] * 2, 8, PixelFormat.BW1)
        request = _request(
            raster,
            encoding=ImageEncoding.V5X_DOT,
            paper_mode=PaperMode.PLAIN,
        )

        plan = build_job(request)

        self.assertIsInstance(plan, ProtocolPlan)
        self.assertEqual(
            [step.write_channel for step in plan.steps],
            [
                ProtocolWriteChannel.CONTROL,
                ProtocolWriteChannel.CONTROL,
                ProtocolWriteChannel.BULK,
                ProtocolWriteChannel.CONTROL,
            ],
        )
        self.assertEqual(
            [step.operation for step in plan.steps],
            [ProtocolStepOperation.SEND] * 4,
        )
        self.assertEqual(plan.payload, b"".join(step.data for step in plan.steps))
        self.assertEqual(plan.steps[1].data, _a9_packet(2, 0))
        self.assertEqual(plan.steps[3].data, V5X_FINALIZE_PACKET)
        self.assertEqual(plan.steps[2].data, b"\x5a\x5a")
        self.assertNotIn(bytes.fromhex("2221A70000000000"), plan.payload)
        self.assertEqual(
            BEHAVIOR.supported_paper_modes, (PaperMode.PLAIN, PaperMode.TAG)
        )

    def test_a9_mode_uses_paper_mode_and_gray_encoding(self) -> None:
        dot_raster = RasterBuffer([0] * 8, 8, PixelFormat.BW1)
        plain_with_legacy_flag = build_job(
            _request(
                dot_raster,
                encoding=ImageEncoding.V5X_DOT,
                paper_mode=PaperMode.PLAIN,
                can_print_label=True,
            )
        )
        tag_without_legacy_flag = build_job(
            _request(
                dot_raster,
                encoding=ImageEncoding.V5X_DOT,
                paper_mode=PaperMode.TAG,
                can_print_label=False,
            )
        )
        gray4 = build_job(
            _request(
                RasterBuffer([0, 1, 2, 3], 2, PixelFormat.GRAY4),
                encoding=ImageEncoding.V5X_GRAY,
                paper_mode=PaperMode.TAG,
            )
        )
        gray8 = build_job(
            _request(
                RasterBuffer([0, 64, 128, 255], 2, PixelFormat.GRAY8),
                encoding=ImageEncoding.V5X_GRAY,
                paper_mode=PaperMode.PLAIN,
            )
        )

        self.assertEqual(plain_with_legacy_flag.steps[1].data, _a9_packet(1, 0))
        self.assertEqual(tag_without_legacy_flag.steps[1].data, _a9_packet(1, 1))
        self.assertEqual(gray4.steps[1].data, _a9_packet(2, 2))
        self.assertEqual(gray4.steps[2].data, b"\x01\x23")
        self.assertEqual(gray8.steps[1].data, _a9_packet(2, 2))
        self.assertEqual(gray8.steps[2].data, b"\x00\x40\x80\xff")

    def test_split_print_stream_keeps_command_like_raster_opaque(self) -> None:
        density = make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
        start = _a9_packet(1, 0)
        opaque = b"\x22\x21\xa7\x00\x02\x00" + V5X_FINALIZE_PACKET + b"\xff"

        split = split_print_stream(density + start + opaque + V5X_FINALIZE_PACKET)

        self.assertIsInstance(split, SplitWritePlan)
        self.assertEqual(split.commands, (density, start))
        self.assertEqual(split.bulk_payload, opaque)
        self.assertEqual(split.trailing_commands, (V5X_FINALIZE_PACKET,))

    def test_split_print_stream_accepts_control_only_and_rejects_bad_frames(
        self,
    ) -> None:
        control = make_packet(0xA3, b"\x05\x00", ProtocolFamily.V5X)
        split = split_print_stream(control)
        self.assertEqual(split, SplitWritePlan((control,), b"", ()))

        with self.assertRaises(ValueError):
            split_print_stream(b"\x22\x21\xa2")
        with self.assertRaises(ValueError):
            split_print_stream(
                make_packet(0xA2, b"\x5d", ProtocolFamily.V5X) + b"\x22\x21\xa9"
            )
        with self.assertRaises(ValueError):
            split_print_stream(
                make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
                + _a9_packet(1, 0)
                + b"raw"
            )

    def test_sign_response_matches_pinned_release_vectors(self) -> None:
        vectors = (
            (
                bytes.fromhex("00010203040506070809"),
                1788900001234,
                "2221B30022003B22C352E178212E225C191E5C441639603246B9E4377164905DEF6B707D0CFE50F400FF",
            ),
            (
                bytes.fromhex("ffffffffffffffffffFF"),
                1788900009999,
                "2221B3002200E263E07B9B4E157BFF9942971CAC51756C8DAEAB6A447F09368DA434E17763CA557900FF",
            ),
            (
                bytes.fromhex("00112233445566778899"),
                1788900000001,
                "2221B3002200550149BF2A721C04E648DE9461373076EA30C1B23621F1454941948D3E4D00BCA89D00FF",
            ),
        )
        for challenge, timestamp_ms, expected in vectors:
            with self.subTest(timestamp_ms=timestamp_ms):
                self.assertEqual(
                    build_sign_response(challenge, timestamp_ms=timestamp_ms),
                    bytes.fromhex(expected),
                )
        for challenge in (b"", bytes(9), bytes(11)):
            with self.subTest(length=len(challenge)), self.assertRaises(ValueError):
                build_sign_response(challenge, timestamp_ms=1)


class V5XRuntimeReleaseParityTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _steps(raster: bytes = b"opaque raster") -> tuple[ProtocolStep, ...]:
        return (
            ProtocolStep.send(
                "density",
                make_packet(0xA2, b"\x5d", ProtocolFamily.V5X),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "start",
                _a9_packet(1, 0),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "raster", raster, write_channel=ProtocolWriteChannel.BULK
            ),
            ProtocolStep.send(
                "finalize",
                V5X_FINALIZE_PACKET,
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
        )

    async def test_explicit_steps_and_compatibility_route_keep_raster_opaque(
        self,
    ) -> None:
        raster = b"\x22\x21\xa2\x00\x01\x00" + V5X_FINALIZE_PACKET + b"end"
        controller = V5XRuntimeController()
        session = _V5XSession()

        handled = await controller.send_protocol_steps(
            session, self._steps(raster), timeout=0.1
        )

        self.assertTrue(handled)
        self.assertEqual(session.atomic, [_a9_packet(1, 0)])
        self.assertEqual(session.bulk, [raster])
        self.assertEqual(session.control[-1], V5X_FINALIZE_PACKET)
        self.assertEqual(session.matches, [True])

        controller = V5XRuntimeController()
        session = _V5XSession()
        stream = (
            make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
            + _a9_packet(1, 0)
            + raster
            + V5X_FINALIZE_PACKET
        )
        handled = await controller.send_payload(session, stream, timeout=0.1)
        self.assertTrue(handled)
        self.assertEqual(session.bulk, [raster])
        self.assertEqual(session.control[-1], V5X_FINALIZE_PACKET)

    async def test_gray_label_mode_three_is_valid_and_uses_gray_context(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        start = _a9_packet(1, 0x03)
        split = SplitWritePlan((start,), b"\xff", (V5X_FINALIZE_PACKET,))

        context = controller.build_split_context(session, split)
        handled = await controller.send_protocol_steps(
            session,
            (
                ProtocolStep.send(
                    "start", start, write_channel=ProtocolWriteChannel.CONTROL
                ),
                ProtocolStep.send(
                    "raster", b"\xff", write_channel=ProtocolWriteChannel.BULK
                ),
                ProtocolStep.send(
                    "finalize",
                    V5X_FINALIZE_PACKET,
                    write_channel=ProtocolWriteChannel.CONTROL,
                ),
            ),
            timeout=0.1,
        )

        self.assertTrue(context.is_gray)
        self.assertEqual(context.coverage_ratio, 0.0)
        self.assertTrue(handled)
        self.assertEqual(session.atomic, [start])
        self.assertEqual(session.bulk, [b"\xff"])
        self.assertEqual(session.control, [V5X_FINALIZE_PACKET])

    async def test_unhandled_step_types_return_false_without_writes(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        handled = await controller.send_protocol_steps(
            session,
            (ProtocolStep.send("standard", b"x"),),
            timeout=0.1,
        )
        self.assertFalse(handled)
        self.assertEqual(session.control, [])
        self.assertEqual(session.bulk, [])

        query = ProtocolStep.query(
            "query",
            make_packet(0xA3, b"\x00", ProtocolFamily.V5X),
            expect=ProtocolReplyExpectation.NONE,
        )
        self.assertFalse(
            await controller.send_protocol_steps(session, (query,), timeout=0.1)
        )
        self.assertEqual(session.control, [])

    async def test_capability_and_shape_failures_happen_before_any_write(self) -> None:
        controller = V5XRuntimeController()
        no_control = _V5XSession()
        no_control.control_available = False
        with self.assertRaisesRegex(RuntimeError, "control packet"):
            await controller.send_protocol_steps(no_control, self._steps(), timeout=0.1)
        self.assertEqual(no_control.control, [])
        self.assertEqual(no_control.atomic, [])
        self.assertEqual(no_control.bulk, [])

        controller = V5XRuntimeController()
        no_bulk = _V5XSession()
        no_bulk.bulk_available = False
        with self.assertRaisesRegex(RuntimeError, "bulk payload"):
            await controller.send_protocol_steps(no_bulk, self._steps(), timeout=0.1)
        self.assertEqual(no_bulk.control, [])
        self.assertEqual(no_bulk.atomic, [])
        self.assertEqual(no_bulk.bulk, [])

        no_atomic = _V5XSession()
        no_atomic.atomic_available = False
        with self.assertRaisesRegex(RuntimeError, "atomic A9"):
            await controller.send_protocol_steps(no_atomic, self._steps(), timeout=0.1)
        self.assertEqual(no_atomic.control, [])
        self.assertEqual(no_atomic.bulk, [])

        malformed = _V5XSession()
        steps_without_finalizer = self._steps()[:-1]
        with self.assertRaisesRegex(ValueError, "finalizer"):
            await controller.send_protocol_steps(
                malformed, steps_without_finalizer, timeout=0.1
            )
        self.assertEqual(malformed.control, [])
        self.assertEqual(malformed.atomic, [])
        self.assertEqual(malformed.bulk, [])

        truncated = _V5XSession()
        with self.assertRaises(ValueError):
            await controller.send_payload(truncated, b"\x22\x21\xa2", timeout=0.1)
        self.assertEqual(truncated.control, [])

        missing_finalizer = _V5XSession()
        with self.assertRaisesRegex(ValueError, "finalizer"):
            await controller.send_payload(
                missing_finalizer,
                make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
                + _a9_packet(1, 0)
                + b"raster",
                timeout=0.1,
            )
        self.assertEqual(missing_finalizer.control, [])
        self.assertEqual(missing_finalizer.atomic, [])
        self.assertEqual(missing_finalizer.bulk, [])

    async def test_busy_a9_retries_until_accepted_before_bulk_or_finalizer(
        self,
    ) -> None:
        controller = V5XRuntimeController()
        controller._state.last_density_payload = b"\x5d"
        controller._state.print_head_type = "other"
        session = _V5XSession()
        session.a9_replies = [
            make_packet(0xA9, b"\x01", ProtocolFamily.V5X),
            make_packet(0xA9, b"\x01", ProtocolFamily.V5X),
            make_packet(0xA9, b"\x00", ProtocolFamily.V5X),
        ]
        retry_delays: list[float] = []
        ack_tokens: list[asyncio.Event] = []
        reply_statuses = (0x01, 0x01, 0x00)

        def trigger_serial_notification() -> None:
            ack_tokens.append(controller._state.command_ack_events[0xA9])
            controller.handle_notification(
                session,
                make_packet(
                    0xA9,
                    bytes([reply_statuses[len(ack_tokens) - 1]]),
                    ProtocolFamily.V5X,
                ),
            )
            controller.handle_notification(
                session, make_packet(0xA6, b"", ProtocolFamily.V5X)
            )

        async def record_delay(delay: float) -> None:
            retry_delays.append(delay)

        session.atomic_hook = trigger_serial_notification
        with patch("catlabel.printing.runtime.v5x.asyncio.sleep", new=record_delay):
            await controller.send_protocol_steps(session, self._steps(), timeout=0.1)

        self.assertEqual(session.atomic, [_a9_packet(1, 0)] * 3)
        self.assertEqual(retry_delays, [0.4, 0.4])
        self.assertEqual(session.bulk, [b"opaque raster"])
        self.assertEqual(session.control.count(V5X_FINALIZE_PACKET), 1)
        self.assertEqual(len(ack_tokens), 3)
        self.assertIs(ack_tokens[0], ack_tokens[1])
        self.assertIs(ack_tokens[1], ack_tokens[2])
        self.assertNotIn(V5X_GET_SERIAL_PACKET, session.control)
        self.assertEqual(controller._state.command_ack_events, {})
        self.assertEqual(controller._state.last_a9_status, 0)

    async def test_missing_or_malformed_a9_reply_aborts_without_retry(self) -> None:
        for reply in (None, b"\x22\x21\xa9\x00\x01", b"\x22\x21\xa9"):
            with self.subTest(reply=reply):
                controller = V5XRuntimeController()
                controller._state.last_a9_status = 0
                session = _V5XSession()
                session.a9_reply = reply
                with self.assertRaisesRegex(RuntimeError, "status byte"):
                    await controller.send_protocol_steps(
                        session, self._steps(), timeout=0.1
                    )
                self.assertEqual(session.atomic, [_a9_packet(1, 0)])
                self.assertEqual(session.matches, [False])
                self.assertEqual(session.bulk, [])
                self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
                self.assertIsNone(controller._state.last_a9_status)
                self.assertEqual(controller._state.command_ack_events, {})

    async def test_non_busy_a9_error_status_aborts_without_retry(self) -> None:
        for status in (0x02, 0x7F):
            with self.subTest(status=status):
                controller = V5XRuntimeController()
                session = _V5XSession()
                session.a9_reply = make_packet(
                    0xA9, bytes([status]), ProtocolFamily.V5X
                )
                with self.assertRaisesRegex(RuntimeError, f"status=0x{status:02x}"):
                    await controller.send_protocol_steps(
                        session, self._steps(), timeout=0.1
                    )
                self.assertEqual(session.atomic, [_a9_packet(1, 0)])
                self.assertEqual(session.bulk, [])
                self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
                self.assertEqual(controller._state.last_a9_status, status)
                self.assertEqual(controller._state.command_ack_events, {})

    async def test_a9_query_timeout_aborts_without_retry_or_pixels(self) -> None:
        controller = V5XRuntimeController()
        controller._state.last_a9_status = 0
        session = _V5XSession()
        session.atomic_error = TimeoutError("fake A9 query timeout")

        with self.assertRaisesRegex(TimeoutError, "fake A9 query timeout"):
            await controller.send_protocol_steps(session, self._steps(), timeout=0.1)

        self.assertEqual(session.atomic, [_a9_packet(1, 0)])
        self.assertEqual(session.bulk, [])
        self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
        self.assertIsNone(controller._state.last_a9_status)
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_a9_write_error_aborts_without_retry_or_pixels(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        session.atomic_error = RuntimeError("fake A9 write failure")

        with self.assertRaisesRegex(RuntimeError, "fake A9 write failure"):
            await controller.send_protocol_steps(session, self._steps(), timeout=0.1)

        self.assertEqual(session.atomic, [_a9_packet(1, 0)])
        self.assertEqual(session.bulk, [])
        self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_repeated_busy_reaches_deadline_with_capped_query_and_backoff(
        self,
    ) -> None:
        controller = V5XRuntimeController()
        controller._state.last_density_payload = b"\x5d"
        controller._state.print_head_type = "other"
        session = _V5XSession()
        session.a9_replies = [
            make_packet(0xA9, b"\x01", ProtocolFamily.V5X),
            make_packet(0xA9, b"\x01", ProtocolFamily.V5X),
        ]
        clock = SimpleNamespace(now=0.0)
        fake_time = SimpleNamespace(monotonic=lambda: clock.now)
        backoff_delays: list[float] = []

        def advance_during_query() -> None:
            clock.now = 50.0 if len(session.atomic) == 1 else 59.75

        async def advance_during_sleep(delay: float) -> None:
            backoff_delays.append(delay)
            clock.now += delay

        session.atomic_hook = advance_during_query
        with (
            patch("catlabel.printing.runtime.v5x.time", new=fake_time),
            patch(
                "catlabel.printing.runtime.v5x.asyncio.sleep",
                new=advance_during_sleep,
            ),
            self.assertRaisesRegex(TimeoutError, "acceptance"),
        ):
            await controller.send_protocol_steps(session, self._steps(), timeout=60.0)

        self.assertEqual(session.atomic, [_a9_packet(1, 0)] * 2)
        self.assertEqual(session.atomic_timeouts[0], 60.0)
        self.assertAlmostEqual(session.atomic_timeouts[1], 9.6)
        self.assertEqual(backoff_delays[0], 0.4)
        self.assertAlmostEqual(backoff_delays[1], 0.25)
        self.assertEqual(session.bulk, [])
        self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_cancellation_during_busy_backoff_cleans_ack_without_pixels(
        self,
    ) -> None:
        controller = V5XRuntimeController()
        controller._state.last_density_payload = b"\x5d"
        controller._state.print_head_type = "other"
        session = _V5XSession()
        session.a9_reply = make_packet(0xA9, b"\x01", ProtocolFamily.V5X)
        backoff_started = asyncio.Event()

        async def wait_in_backoff(delay: float) -> None:
            self.assertEqual(delay, 0.4)
            backoff_started.set()
            await asyncio.Event().wait()

        with patch("catlabel.printing.runtime.v5x.asyncio.sleep", new=wait_in_backoff):
            task = asyncio.create_task(
                controller.send_protocol_steps(session, self._steps(), timeout=0.1)
            )
            await backoff_started.wait()
            self.assertEqual(session.atomic, [_a9_packet(1, 0)])
            self.assertEqual(sorted(controller._state.command_ack_events), [0xA9])
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(session.bulk, [])
        self.assertNotIn(V5X_FINALIZE_PACKET, session.control)
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_successful_a9_ack_allows_bulk_and_finalizer(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        session.a9_reply = b"\x22\x21\xa9\x00\x00\x00"
        await controller.send_protocol_steps(session, self._steps(), timeout=0.1)
        self.assertEqual(session.atomic, [_a9_packet(1, 0)])
        self.assertEqual(session.bulk, [b"opaque raster"])
        self.assertEqual(session.control.count(V5X_FINALIZE_PACKET), 1)
        self.assertEqual(controller._state.last_a9_status, 0)
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_density_cache_changes_only_after_successful_a2_write(self) -> None:
        density = make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
        controller = V5XRuntimeController()
        session = _V5XSession()
        session.fail_control.add(density)
        with self.assertRaisesRegex(RuntimeError, "control packet"):
            await controller.send_protocol_steps(session, self._steps(), timeout=0.1)
        self.assertIsNone(controller._state.last_density_payload)
        self.assertEqual(session.atomic, [])
        self.assertEqual(session.bulk, [])

        controller = V5XRuntimeController()
        session = _V5XSession()
        await controller.send_protocol_steps(session, self._steps(), timeout=0.1)
        self.assertEqual(controller._state.last_density_payload, b"\x5d")

    async def test_density_settle_delay_precedes_a9_and_survives_intermediate_control(
        self,
    ) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        steps = (
            ProtocolStep.send(
                "density",
                make_packet(0xA2, b"\x5d", ProtocolFamily.V5X),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "intermediate control",
                make_packet(0xA3, b"\x00", ProtocolFamily.V5X),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "start",
                _a9_packet(1, 0),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "raster", b"\x00", write_channel=ProtocolWriteChannel.BULK
            ),
            ProtocolStep.send(
                "finalize",
                V5X_FINALIZE_PACKET,
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
        )

        async def record_delay(delay: float) -> None:
            session.events.append(("settle", delay))

        with patch("catlabel.printing.runtime.v5x.asyncio.sleep", new=record_delay):
            await controller.send_protocol_steps(session, steps, timeout=0.1)

        self.assertEqual(
            session.events,
            [
                ("control", steps[0].data),
                ("control", steps[1].data),
                ("settle", 0.06),
                ("atomic", steps[2].data),
                ("bulk", b"\x00"),
                ("control", V5X_FINALIZE_PACKET),
            ],
        )

    async def test_pages_progress_without_aa_and_aa_is_ignored(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        controller.handle_notification(session, b"\x22\x21\xaa\x00\x00")

        await controller.send_protocol_steps(session, self._steps(), timeout=0.1)
        await controller.send_protocol_steps(session, self._steps(), timeout=0.1)

        self.assertEqual(session.atomic, [_a9_packet(1, 0)] * 2)
        self.assertEqual(session.bulk, [b"opaque raster"] * 2)
        self.assertEqual(session.control.count(V5X_FINALIZE_PACKET), 2)
        self.assertNotIn("start ready: 0xaa", session.debug)

    async def test_finalizer_failure_is_reported_without_readiness_state(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        session.fail_control.add(V5X_FINALIZE_PACKET)
        with self.assertRaisesRegex(RuntimeError, "finalizer"):
            await controller.send_protocol_steps(session, self._steps(), timeout=0.1)
        self.assertEqual(session.bulk, [b"opaque raster"])
        self.assertEqual(controller._state.command_ack_events, {})

    async def test_repeated_sign_challenges_are_answered_and_stop_cleans_tasks(
        self,
    ) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        challenge = bytes.fromhex("00010203040506070809")
        notification = make_packet(0xB3, challenge, ProtocolFamily.V5X)
        controller.handle_notification(session, notification)
        controller.handle_notification(session, notification)
        pending = tuple(controller._state.pending_sign_responses)
        self.assertEqual(len(pending), 2)
        await asyncio.gather(*pending)
        await asyncio.sleep(0)
        self.assertEqual(len(session.control), 2)
        self.assertTrue(
            all(
                packet.startswith(bytes.fromhex("2221B3002200"))
                for packet in session.control
            )
        )
        self.assertEqual(controller._state.mxw_sign_responses_sent, 2)
        self.assertFalse(controller._state.pending_sign_responses)

        blocked_controller = V5XRuntimeController()
        blocked_session = _V5XSession()
        blocked_session.block_control = True
        blocked_controller.handle_notification(blocked_session, notification)
        await blocked_session.control_started.wait()
        previous = V5XRuntimeController()
        blocked_controller.adopt_previous(previous)
        self.assertTrue(blocked_controller._state.pending_sign_responses)

        async def wait_forever() -> None:
            await asyncio.Event().wait()

        get_task = asyncio.create_task(wait_forever())
        status_task = asyncio.create_task(wait_forever())
        blocked_controller._state.pending_get_serial = get_task
        blocked_controller._state.pending_status_poll = status_task
        blocked_controller._state.command_ack_events[0xA9] = asyncio.Event()
        await blocked_controller.stop(blocked_session)
        self.assertFalse(blocked_controller._state.pending_sign_responses)
        self.assertTrue(get_task.cancelled())
        self.assertTrue(status_task.cancelled())
        self.assertIsNone(blocked_controller._state.pending_get_serial)
        self.assertIsNone(blocked_controller._state.pending_status_poll)
        self.assertEqual(blocked_controller._state.command_ack_events, {})

        failed_controller = V5XRuntimeController()
        failed_session = _V5XSession()
        failed_session.fail_any_control = True
        failed_controller.handle_notification(failed_session, notification)
        pending_failed = tuple(failed_controller._state.pending_sign_responses)
        await asyncio.gather(*pending_failed)
        self.assertTrue(failed_session.warnings)
        self.assertEqual(failed_controller._state.mxw_sign_responses_sent, 0)

    async def test_existing_pause_resume_markers_remain_supported(self) -> None:
        from catlabel.protocol.families.v5x import (
            V5X_NOTIFY_PAUSE_PACKETS,
            V5X_NOTIFY_RESUME_PACKETS,
        )

        controller = V5XRuntimeController()
        session = _V5XSession()
        pause = next(iter(V5X_NOTIFY_PAUSE_PACKETS))
        resume = next(iter(V5X_NOTIFY_RESUME_PACKETS))
        controller.handle_notification(session, pause)
        controller.handle_notification(session, resume)
        self.assertFalse(session.flow_paused)

    def test_b3_without_event_loop_warns_without_creating_a_task(self) -> None:
        controller = V5XRuntimeController()
        session = _V5XSession()
        notification = make_packet(
            0xB3, bytes.fromhex("00010203040506070809"), ProtocolFamily.V5X
        )
        controller.handle_notification(session, notification)
        self.assertTrue(session.warnings)
        self.assertFalse(controller._state.pending_sign_responses)


if __name__ == "__main__":
    unittest.main()
