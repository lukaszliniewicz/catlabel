from __future__ import annotations

import unittest
from typing import cast

from catlabel.printing.runtime.base import RuntimeSessionApi
from catlabel.printing.send import send_prepared_job
from catlabel.printing.step_execution import execute_protocol_step
from catlabel.protocol import ProtocolJob
from catlabel.protocol.steps import (
    ProtocolReplyExpectation,
    ProtocolReplyMatcher,
    ProtocolStep,
    ProtocolStepOperation,
    ProtocolWriteChannel,
)


class RecordingSession:
    def __init__(
        self,
        *,
        control_supported: bool = True,
        bulk_supported: bool = True,
        control_result: bool = True,
        bulk_result: bool = True,
    ) -> None:
        self.control_supported = control_supported
        self.bulk_supported = bulk_supported
        self.control_result = control_result
        self.bulk_result = bulk_result
        self.routes: list[tuple[str, bytes, float | None]] = []
        self.events: list[str] = []

    def report_debug(self, message: str) -> None:
        self.events.append("debug")

    def can_send_control_packet(self) -> bool:
        self.events.append("can_control")
        return self.control_supported

    def can_send_bulk_payload(self) -> bool:
        self.events.append("can_bulk")
        return self.bulk_supported

    async def send_standard_payload(self, data: bytes) -> None:
        self.events.append("send_standard")
        self.routes.append(("standard", data, None))

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.events.append("send_control")
        self.routes.append(("control", packet, timeout))
        return self.control_result

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        self.events.append("send_bulk")
        self.routes.append(("bulk", data, timeout))
        return self.bulk_result


class ProtocolWriteChannelTests(unittest.IsolatedAsyncioTestCase):
    async def test_whole_job_routes_are_preflighted_before_first_control_write(
        self,
    ) -> None:
        steps = (
            ProtocolStep.send(
                "setup", b"setup", write_channel=ProtocolWriteChannel.CONTROL
            ),
            ProtocolStep.send(
                "raster", b"pixels", write_channel=ProtocolWriteChannel.BULK
            ),
        )
        job = ProtocolJob(payload=b"setuppixels", steps=steps)
        for connection in (
            RecordingSession(control_supported=False),
            RecordingSession(bulk_supported=False),
        ):
            with self.subTest(
                control=connection.control_supported, bulk=connection.bulk_supported
            ):
                with self.assertRaisesRegex(RuntimeError, "write route"):
                    await send_prepared_job(object(), connection, job)
                self.assertEqual(connection.routes, [])

    async def test_legacy_send_keeps_standard_route_and_payload_identity(self) -> None:
        payload = bytes(range(16))
        step = ProtocolStep.send("legacy raster", payload)
        session = RecordingSession()

        self.assertIs(step.write_channel, ProtocolWriteChannel.STANDARD)
        self.assertIs(step.data, payload)
        await execute_protocol_step(
            cast(RuntimeSessionApi, session),
            step,
            timeout=2.0,
        )

        self.assertEqual(session.routes, [("standard", payload, None)])
        self.assertIs(session.routes[0][1], step.data)
        self.assertEqual(session.events, ["debug", "send_standard"])

    async def test_control_and_bulk_routes_forward_opaque_bytes_and_timeout(
        self,
    ) -> None:
        payload = bytes.fromhex("2221A90004000100300000FF") + bytes(range(32))
        timeout = 2.75
        for channel in (ProtocolWriteChannel.CONTROL, ProtocolWriteChannel.BULK):
            with self.subTest(channel=channel.value):
                step = ProtocolStep.send(
                    "opaque write",
                    payload,
                    write_channel=channel,
                )
                session = RecordingSession()

                await execute_protocol_step(
                    cast(RuntimeSessionApi, session),
                    step,
                    timeout=timeout,
                )

                self.assertEqual(len(session.routes), 1)
                route, sent_data, sent_timeout = session.routes[0]
                self.assertEqual(route, channel.value)
                self.assertIs(sent_data, step.data)
                self.assertEqual(sent_data, payload)
                self.assertEqual(sent_timeout, timeout)
                self.assertEqual(
                    session.events,
                    ["debug", f"can_{channel.value}", f"send_{channel.value}"],
                )

    async def test_unsupported_route_fails_before_any_send(self) -> None:
        for channel in (ProtocolWriteChannel.CONTROL, ProtocolWriteChannel.BULK):
            with self.subTest(channel=channel.value):
                options = (
                    {"control_supported": False}
                    if channel is ProtocolWriteChannel.CONTROL
                    else {"bulk_supported": False}
                )
                step = ProtocolStep.send(
                    "unsupported write",
                    b"opaque",
                    write_channel=channel,
                )
                session = RecordingSession(**options)

                with self.assertRaises(RuntimeError) as raised:
                    await execute_protocol_step(
                        cast(RuntimeSessionApi, session),
                        step,
                        timeout=1.5,
                    )

                self.assertIn("unsupported write", str(raised.exception))
                self.assertIn(
                    f"{channel.value} write route unavailable", str(raised.exception)
                )
                self.assertEqual(session.routes, [])
                self.assertEqual(session.events, ["debug", f"can_{channel.value}"])

    async def test_false_route_result_fails_without_fallback_or_duplicate_send(
        self,
    ) -> None:
        for channel in (ProtocolWriteChannel.CONTROL, ProtocolWriteChannel.BULK):
            with self.subTest(channel=channel.value):
                options = (
                    {"control_result": False}
                    if channel is ProtocolWriteChannel.CONTROL
                    else {"bulk_result": False}
                )
                payload = b"single route only"
                step = ProtocolStep.send(
                    "rejected write",
                    payload,
                    write_channel=channel,
                )
                session = RecordingSession(**options)

                with self.assertRaises(RuntimeError) as raised:
                    await execute_protocol_step(
                        cast(RuntimeSessionApi, session),
                        step,
                        timeout=3.25,
                    )

                self.assertIn("rejected write", str(raised.exception))
                self.assertIn(
                    f"{channel.value} write route unavailable", str(raised.exception)
                )
                self.assertEqual(len(session.routes), 1)
                self.assertEqual(session.routes[0][0], channel.value)
                self.assertIs(session.routes[0][1], step.data)
                self.assertEqual(session.routes[0][2], 3.25)
                self.assertEqual(
                    session.events,
                    ["debug", f"can_{channel.value}", f"send_{channel.value}"],
                )

    def test_channel_values_normalize_and_unknown_values_are_rejected(self) -> None:
        for channel in ProtocolWriteChannel:
            with self.subTest(channel=channel.value):
                step = ProtocolStep.send(
                    "normalized",
                    b"data",
                    write_channel=cast(ProtocolWriteChannel, channel.value),
                )
                self.assertIs(step.write_channel, channel)

        with self.assertRaises(ValueError):
            ProtocolStep.send(
                "invalid channel",
                b"data",
                write_channel=cast(ProtocolWriteChannel, "invalid"),
            )

        legacy_query = ProtocolStep(
            "legacy positional query",
            b"query",
            ProtocolStepOperation.QUERY,
            ProtocolReplyExpectation.NONE,
        )
        self.assertIs(legacy_query.operation, ProtocolStepOperation.QUERY)
        self.assertIs(legacy_query.write_channel, ProtocolWriteChannel.STANDARD)

    def test_nonstandard_channels_are_rejected_for_queries_and_waits(self) -> None:
        for operation in (ProtocolStepOperation.QUERY, ProtocolStepOperation.WAIT):
            for channel in (ProtocolWriteChannel.CONTROL, ProtocolWriteChannel.BULK):
                with (
                    self.subTest(operation=operation.value, channel=channel.value),
                    self.assertRaisesRegex(ValueError, "query and wait"),
                ):
                    ProtocolStep(
                        "invalid operation route",
                        b"data",
                        operation=operation,
                        write_channel=channel,
                    )

        query = ProtocolStep.query(
            "default query",
            b"query",
            expect=ProtocolReplyExpectation.NONE,
        )
        wait = ProtocolStep.wait(
            "default wait",
            reply_matcher=ProtocolReplyMatcher(complete=lambda _reply: True),
        )
        self.assertIs(query.write_channel, ProtocolWriteChannel.STANDARD)
        self.assertIs(wait.write_channel, ProtocolWriteChannel.STANDARD)


if __name__ == "__main__":
    unittest.main()
