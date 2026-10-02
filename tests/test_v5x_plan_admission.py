"""An unsupported step must never bypass V5X acknowledgement handling."""

import unittest
from types import SimpleNamespace

from catlabel.printing.runtime.base import PreparedRuntimeContext
from catlabel.printing.runtime.v5x import V5XRuntimeController
from catlabel.printing.send import send_prepared_job
from catlabel.protocol.family import ProtocolFamily
from catlabel.protocol.job import ProtocolJob
from catlabel.protocol.steps import ProtocolStep, ProtocolWriteChannel
from tests.runtime_session_fake import RuntimeSessionFake


class _SupportedRoutes(RuntimeSessionFake):
    def can_send_control_packet(self) -> bool:
        return True

    def can_send_bulk_payload(self) -> bool:
        return True

    def can_send_standard_payload(self) -> bool:
        return True

    def can_send_control_packet_wait_notification(self) -> bool:
        return True


class V5XPlanAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_skipping_final_completion_does_not_skip_acknowledgement_runtime(
        self,
    ) -> None:
        with self.assertRaisesRegex(RuntimeError, "acknowledgement runtime"):
            await send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5X),
                _SupportedRoutes(),
                ProtocolJob(
                    payload=b"raw",
                    steps=(ProtocolStep.send("raw", b"raw"),),
                    wait_for_completion=False,
                ),
            )

    async def test_mixed_plan_cannot_fall_back_to_unacknowledged_writes(self) -> None:
        steps = (
            ProtocolStep.send(
                "start",
                bytes.fromhex("2221A9000400010030000000"),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
            ProtocolStep.send(
                "raster", b"opaque raster", write_channel=ProtocolWriteChannel.BULK
            ),
            ProtocolStep.send("extra standard step", b"extra"),
            ProtocolStep.send(
                "finalizer",
                bytes.fromhex("2221AD0000000000"),
                write_channel=ProtocolWriteChannel.CONTROL,
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "acknowledgement runtime"):
            await send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5X),
                _SupportedRoutes(),
                ProtocolJob(payload=b"".join(step.data for step in steps), steps=steps),
                runtime_context=PreparedRuntimeContext(V5XRuntimeController()),
            )

    async def test_standard_only_plan_cannot_use_a_generic_route(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "acknowledgement runtime"):
            await send_prepared_job(
                SimpleNamespace(protocol_family=ProtocolFamily.V5X),
                _SupportedRoutes(),
                ProtocolJob(payload=b"raw", steps=(ProtocolStep.send("raw", b"raw"),)),
                runtime_context=PreparedRuntimeContext(V5XRuntimeController()),
            )
