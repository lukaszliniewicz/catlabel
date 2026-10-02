from __future__ import annotations

import unittest

from catlabel.printing.runtime.v5x import V5XRuntimeController
from catlabel.protocol import ProtocolFamily
from catlabel.protocol.families.v5x import V5X_FINALIZE_PACKET
from catlabel.protocol.packet import make_packet
from tests.runtime_session_fake import RuntimeSessionFake


class _FakeSession(RuntimeSessionFake):
    def __init__(self, frames: list[bytes | None]) -> None:
        self.frames = frames
        self.debug: list[str] = []
        self.wait_labels: list[str] = []

    def can_wait_for_notification(self) -> bool:
        return True

    async def wait_for_notification(self, label, match, *, timeout, required=True):
        self.wait_labels.append(label)
        frame = self.frames.pop(0)
        if frame is not None:
            self.assert_match = match(frame)
        return frame

    def extract_prefixed_opcode(self, payload: bytes):
        return payload[2] if payload.startswith(b"\x22\x21") else None

    def extract_prefixed_payload(self, packet: bytes):
        length = int.from_bytes(packet[4:6], "little")
        return packet[6 : 6 + length]

    def report_debug(self, message: str) -> None:
        self.debug.append(message)


class _FakeSendSession(RuntimeSessionFake):
    def __init__(self) -> None:
        self.control: list[bytes] = []
        self.bulk: list[bytes] = []
        self.atomic: list[bytes] = []
        self.debug: list[str] = []

    def can_send_control_packet(self) -> bool:
        return True

    def can_send_bulk_payload(self) -> bool:
        return True

    def can_send_control_packet_wait_notification(self) -> bool:
        return True

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.control.append(packet)
        return True

    async def send_bulk_payload(self, data: bytes, *, timeout: float = 1.0) -> bool:
        self.bulk.append(data)
        return True

    async def send_control_packet_wait_notification(
        self, packet, *, label, match, timeout, required=True
    ):
        self.atomic.append(packet)
        reply = make_packet(0xA9, b"\x00", ProtocolFamily.V5X)
        self.assert_match = match(reply)
        return reply

    def report_debug(self, message: str) -> None:
        self.debug.append(message)


class V5XCompletionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_owns_command_and_bulk_stream_routing(self) -> None:
        controller = V5XRuntimeController()
        session = _FakeSendSession()
        command = make_packet(0xA2, b"\x5d", ProtocolFamily.V5X)
        start = bytes.fromhex("2221A9000400000130000000")
        bulk = b"\x00"

        handled = await controller.send_payload(
            session,
            command + start + bulk + V5X_FINALIZE_PACKET,
            timeout=0.01,
        )

        self.assertTrue(handled)
        self.assertEqual(session.control, [command, V5X_FINALIZE_PACKET])
        self.assertEqual(session.atomic, [start])
        self.assertEqual(session.bulk, [bulk])

    async def test_idle_status_finishes_without_active_polling(self) -> None:
        controller = V5XRuntimeController()
        controller._COMPLETION_GRACE_S = 0
        session = _FakeSession([make_packet(0xA1, b"\x00", ProtocolFamily.V5X)])

        await controller.wait_for_completion(session, timeout=0.01)

        self.assertEqual(session.wait_labels, ["V5X print completion 0xa1"])
        self.assertTrue(session.assert_match)
        self.assertTrue(any("reported idle" in message for message in session.debug))

    async def test_quiet_window_finishes_without_status_query(self) -> None:
        controller = V5XRuntimeController()
        controller._COMPLETION_GRACE_S = 0
        session = _FakeSession([None])

        await controller.wait_for_completion(session, timeout=0.01)

        self.assertTrue(any("status quiet" in message for message in session.debug))


if __name__ == "__main__":
    unittest.main()
