from __future__ import annotations

import unittest
from collections.abc import Callable
from types import SimpleNamespace

from catlabel.printing.send import send_prepared_job
from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.luck_normal_a4 import RECIPE
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.steps import ProtocolStep, ProtocolStepOperation
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet


class FakeConnection:
    def __init__(
        self,
        *,
        notifications: bool = False,
        available: bool = True,
        overrides: dict[bytes, bytes | None] | None = None,
    ) -> None:
        self.notifications = notifications
        self.available = available
        self.overrides = overrides or {}
        self.events: list[tuple[str, bytes, float | None]] = []

    def can_query_control_packet(self) -> bool:
        return self.available and not self.notifications

    def can_send_control_packet_wait_notification(self) -> bool:
        return self.available and self.notifications

    async def send(self, job: ProtocolJob) -> None:
        raise AssertionError("Luck must not fall back to an unchecked stream")

    async def send_standard_payload(self, data: bytes) -> None:
        self.events.append(("send", data, None))

    def _reply(self, packet: bytes, timeout: float) -> bytes | None:
        self.events.append(("query", packet, timeout))
        return self.overrides.get(
            packet, b"\x00" if packet == b"\x10\xff\x40" else b"OK"
        )

    async def query_control_packet(
        self,
        packet: bytes,
        *,
        timeout: float,
        reply_complete: Callable[[bytes], bool],
    ) -> bytes | None:
        return self._reply(packet, timeout)

    async def send_control_packet_wait_notification(
        self,
        packet: bytes,
        *,
        label: str,
        match: Callable[[bytes], bool],
        timeout: float,
        required: bool,
    ) -> bytes | None:
        reply = self._reply(packet, timeout)
        if reply is None:
            return None
        pending = b""
        for value in reply:
            pending += bytes([value])
            if match(pending):
                return pending
        return pending


def a4_job(*, two_pages: bool = False) -> ProtocolJob:
    request = PrintJobRequest(
        raster_set=RasterSet.from_single(RasterBuffer([1] * 8, 8, PixelFormat.BW1)),
        image_pipeline=RECIPE.default_image_pipeline,
        is_text=False,
        speed=0,
        energy=10000,
        blackening=3,
        lsb_first=False,
        protocol_family=RECIPE.protocol_family,
        protocol_variant="lujiang_a4",
        feed_padding=0,
        dev_dpi=203,
        density=3,
    )
    plan = RECIPE.build_job(request)
    steps = plan.steps + plan.steps if two_pages else plan.steps
    return ProtocolJob(
        payload=b"".join(step.data for step in steps if step.include_in_payload),
        steps=steps,
    )


class LuckTransactionExecutionTests(unittest.IsolatedAsyncioTestCase):
    device = SimpleNamespace(
        protocol_family=RECIPE.protocol_family, protocol_variant="lujiang_a4"
    )

    async def test_both_reply_routes_execute_complete_transaction(self) -> None:
        job = a4_job()
        for notifications in (False, True):
            with self.subTest(notifications=notifications):
                connection = FakeConnection(notifications=notifications)
                await send_prepared_job(self.device, connection, job, timeout=0.25)
                self.assertEqual(
                    connection.events,
                    [
                        (
                            "send"
                            if step.operation is ProtocolStepOperation.SEND
                            else "query",
                            step.data,
                            None
                            if step.operation is ProtocolStepOperation.SEND
                            else step.timeout_sec,
                        )
                        for step in job.steps
                    ],
                )
                self.assertEqual(
                    connection.events[-1], ("query", b"\x10\xff\xf1E", 120)
                )

    async def test_missing_reply_route_preflights_before_all_writes(self) -> None:
        connection = FakeConnection(available=False)
        with self.assertRaisesRegex(RuntimeError, "request/reply"):
            await send_prepared_job(self.device, connection, a4_job())
        self.assertEqual(connection.events, [])

    async def test_required_setup_failure_prevents_raster(self) -> None:
        for packet, reply in (
            (b"\x10\xff\x10\x00\x03", None),
            (b"\x10\xff\x10\x00\x03", b"NO"),
            (b"\x10\xff\x10\x00\x03", b"\x00OK"),
            (b"\x10\xff\x40", None),
            (b"\x10\xff\x40", b"\x04"),
        ):
            with self.subTest(packet=packet, reply=reply):
                connection = FakeConnection(overrides={packet: reply})
                with self.assertRaisesRegex(RuntimeError, "unexpected reply"):
                    await send_prepared_job(self.device, connection, a4_job())
                self.assertFalse(any(event[0] == "send" for event in connection.events))

    async def test_optional_paper_setting_reserves_wait_without_aborting(self) -> None:
        for reply in (None, b"NO"):
            for notifications in (False, True):
                with self.subTest(reply=reply, notifications=notifications):
                    connection = FakeConnection(
                        notifications=notifications,
                        overrides={b"\x1f\x80\x01\x10": reply},
                    )
                    await send_prepared_job(self.device, connection, a4_job())
                    self.assertIn(("query", b"\x1f\x80\x01\x10", 3), connection.events)
                    self.assertEqual(connection.events[-1][1], b"\x10\xff\xf1E")

    async def test_finalization_failure_stops_next_page_without_retry(self) -> None:
        job = a4_job(two_pages=True)
        raster = next(step.data for step in job.steps if step.label == "bitmap")
        for notifications in (False, True):
            for reply in (None, b"NO", b"\x00\xaa", b"\x00OK"):
                with self.subTest(reply=reply, notifications=notifications):
                    connection = FakeConnection(
                        notifications=notifications,
                        overrides={b"\x10\xff\xf1E": reply},
                    )
                    with self.assertRaisesRegex(RuntimeError, "finalize"):
                        await send_prepared_job(self.device, connection, job)
                    self.assertEqual(connection.events.count(("send", raster, None)), 1)

    async def test_existing_query_steps_still_require_replies(self) -> None:
        from catlabel.protocol.steps import ProtocolReplyExpectation

        step = ProtocolStep.query(
            "legacy", b"legacy", expect=ProtocolReplyExpectation.OK
        )
        self.assertTrue(step.reply_required)
        connection = FakeConnection(overrides={b"legacy": None})
        with self.assertRaisesRegex(RuntimeError, "legacy"):
            await send_prepared_job(
                object(), connection, ProtocolJob(payload=b"legacy", steps=(step,))
            )


if __name__ == "__main__":
    unittest.main()
