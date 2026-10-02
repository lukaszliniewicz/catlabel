"""Reject unsupported footer queries before sending image or setup bytes."""

import unittest

from catlabel.printing.runtime.funny_lx import FunnyLxRuntimeController
from catlabel.protocol.steps import ProtocolReplyExpectation, ProtocolStep
from tests.runtime_session_fake import RuntimeSessionFake


class _NoQuerySession(RuntimeSessionFake):
    def can_send_standard_payload(self) -> bool:
        return True

    def can_wait_for_notification(self) -> bool:
        return True


class FunnyLxPreflightTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_query_capability_fails_before_any_write(self) -> None:
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")
        steps = (
            ProtocolStep.send("header", b"\x5a\x04\x00\x01\x00\x00"),
            ProtocolStep.send("raster", b"\x55\x00\x00" + bytes(97)),
            ProtocolStep.query(
                "footer", b"\x5a\x04\x00\x01\x01", expect=ProtocolReplyExpectation.NONE
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "request/reply"):
            await controller.send_protocol_steps(_NoQuerySession(), steps, timeout=0.1)

    async def test_unrelated_steps_remain_unhandled(self) -> None:
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")
        self.assertFalse(
            await controller.send_protocol_steps(
                _NoQuerySession(), (ProtocolStep.send("other", b"other"),), timeout=0.1
            )
        )
