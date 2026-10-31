from __future__ import annotations

import unittest

from catlabel.printing.runtime.funny_lx import FunnyLxRuntimeController
from catlabel.protocol import ImageEncoding, ImagePipelineConfig, ProtocolFamily
from catlabel.protocol._builders import _build_job
from catlabel.protocol.commands import advance_paper_cmd, retract_paper_cmd
from catlabel.protocol.families import get_protocol_behavior
from catlabel.protocol.families.base import PrintJobRequest
from catlabel.protocol.families.funny_lx import (
    FunnyLxStatus,
    decode_status,
)
from catlabel.protocol.families.funny_lx import (
    build_job as build_funny_lx_job,
)
from catlabel.protocol.steps import ProtocolStep
from catlabel.raster import PixelFormat, RasterBuffer, RasterSet
from tests.runtime_session_fake import RuntimeSessionFake


def _request(
    family: ProtocolFamily,
    pipeline: ImagePipelineConfig,
    *,
    raster: RasterBuffer | None = None,
    protocol_variant: str | None = None,
) -> PrintJobRequest:
    if raster is None:
        raster = RasterBuffer([0] * 384, width=384, pixel_format=PixelFormat.BW1)
    return PrintJobRequest(
        raster_set=RasterSet.from_single(raster),
        image_pipeline=pipeline,
        is_text=False,
        speed=20,
        energy=0,
        blackening=4,
        lsb_first=True,
        protocol_family=family,
        protocol_variant=protocol_variant,
        feed_padding=0,
        dev_dpi=203,
    )


class _FunnyRuntimeSession(RuntimeSessionFake):
    def __init__(self, ready_reply: bytes | None = None) -> None:
        self.ready_reply = ready_reply
        self.control: list[bytes] = []
        self.standard: list[bytes] = []

    def can_send_control_packet(self) -> bool:
        return True

    def can_query_control_packet(self) -> bool:
        return True

    def can_send_standard_payload(self) -> bool:
        return True

    def can_wait_for_notification(self) -> bool:
        return True

    async def send_control_packet(self, packet: bytes, *, timeout: float = 1.0) -> bool:
        self.control.append(bytes(packet))
        return True

    async def send_standard_payload(self, data: bytes) -> object:
        self.standard.append(bytes(data))

    async def wait_for_notification(
        self,
        label: str,
        match,
        *,
        timeout: float,
        required: bool = True,
    ) -> bytes | None:
        return self.ready_reply


class FunnyLxRecipeTests(unittest.IsolatedAsyncioTestCase):
    def test_status_decoder_requires_a_complete_status_frame(self) -> None:
        self.assertIsNone(decode_status(b"\x5a\x02\x01\x02"))
        self.assertIsNone(decode_status(b"\x5a\x01\x01\x02\x03\x04\x05\x06"))
        self.assertEqual(
            decode_status(bytes.fromhex("5a 02 23 10 ff 04 05 07 aa")),
            FunnyLxStatus(
                battery=0x23, paper=0x10, temp=0x04, voltage=0x05, darkness=8
            ),
        )

    def test_status_notifications_are_diagnostics_only(self) -> None:
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")
        session = _FunnyRuntimeSession()

        controller.handle_notification(session, b"\x5a\x02\x01")
        self.assertIsNone(controller.debug_snapshot()["status"])

        controller.handle_notification(
            session, bytes.fromhex("5a 02 23 10 ff 04 05 07")
        )
        self.assertEqual(
            controller.debug_snapshot()["status"],
            {
                "battery": 0x23,
                "paper": 0x10,
                "temp": 0x04,
                "voltage": 0x05,
                "darkness": 8,
            },
        )
        self.assertEqual(controller.debug_snapshot()["packet_delay_hint_sec"], 0.02)
        self.assertFalse(controller._retry_requests)

    async def test_darkness_is_skipped_when_negotiation_says_unsupported(self) -> None:
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")
        session = _FunnyRuntimeSession()
        await controller._execute_non_image_step(
            session,
            ProtocolStep.send("darkness", b"\x5a\x0c\x03"),
            timeout=0.1,
        )
        self.assertEqual(session.standard, [])

    async def test_cached_darkness_remains_skipped_when_supported(self) -> None:
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")
        controller._supports_darkness = True
        controller._darkness_code = 3
        session = _FunnyRuntimeSession()
        await controller._execute_non_image_step(
            session,
            ProtocolStep.send("darkness", b"\x5a\x0c\x03"),
            timeout=0.1,
        )
        self.assertEqual(session.standard, [])

    async def test_raw_status_cannot_satisfy_image_ready_wait(self) -> None:
        request = _request(
            ProtocolFamily.FUNNY_LX,
            ImagePipelineConfig(
                formats=(PixelFormat.BW1,),
                encoding=ImageEncoding.FUNNY_LX_RASTER,
            ),
            protocol_variant="lx_d_direct",
        )
        plan = build_funny_lx_job(request)
        session = _FunnyRuntimeSession(
            ready_reply=bytes.fromhex("5a 02 23 10 ff 04 05 07")
        )
        controller = FunnyLxRuntimeController(bluetooth_address="00:11:22:33:44:55")

        with self.assertRaisesRegex(RuntimeError, "did not reach printer-ready"):
            await controller.send_protocol_steps(session, plan.steps, timeout=0.1)

        self.assertEqual(session.control, [])
        self.assertEqual(session.standard[0], b"\x5a\x04\x00\x01\x00\x00")
        self.assertEqual(len(session.standard), 2)

    def test_funny_lx_exposes_no_manual_motion_and_rejects_requests(self) -> None:
        behavior = get_protocol_behavior(ProtocolFamily.FUNNY_LX)
        self.assertIsNone(behavior.advance_paper_builder)
        self.assertIsNone(behavior.retract_paper_builder)
        with self.assertRaisesRegex(
            ValueError, "does not use prefixed command packets"
        ):
            advance_paper_cmd(203, ProtocolFamily.FUNNY_LX)
        with self.assertRaisesRegex(
            ValueError, "does not use prefixed command packets"
        ):
            retract_paper_cmd(203, ProtocolFamily.FUNNY_LX)


class V5GRecipeAdmissionTests(unittest.TestCase):
    def test_v5g_admits_only_bw1_dot_recipes_and_keeps_other_gray_families(
        self,
    ) -> None:
        v5g = get_protocol_behavior(ProtocolFamily.V5G)
        self.assertEqual(v5g.default_image_pipeline.formats, (PixelFormat.BW1,))
        self.assertEqual(
            dict(v5g.image_encoding_support),
            {ImageEncoding.V5G_DOT: (PixelFormat.BW1,)},
        )
        self.assertEqual(
            get_protocol_behavior(ProtocolFamily.V5X).image_encoding_support[
                ImageEncoding.V5X_GRAY
            ],
            (PixelFormat.GRAY4, PixelFormat.GRAY8),
        )
        self.assertEqual(
            get_protocol_behavior(ProtocolFamily.V5C).image_encoding_support[
                ImageEncoding.V5C_A5
            ],
            (PixelFormat.GRAY4, PixelFormat.GRAY8),
        )

    def test_explicit_v5g_gray_request_is_rejected_before_payload_building(
        self,
    ) -> None:
        gray_pipeline = ImagePipelineConfig(
            formats=(PixelFormat.GRAY4,),
            encoding=ImageEncoding.V5G_GRAY,
        )
        with self.assertRaisesRegex(ValueError, "does not support image encoding"):
            _build_job(
                pixels=[0] * 8,
                width=8,
                is_text=False,
                speed=20,
                energy=0,
                density=None,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.V5G,
                feed_padding=0,
                dev_dpi=203,
                image_pipeline=gray_pipeline,
            )

        request = _request(ProtocolFamily.V5G, gray_pipeline)
        builder = get_protocol_behavior(ProtocolFamily.V5G).job_builder
        self.assertIsNotNone(builder)
        if builder is None:
            self.fail("V5G should have a job builder")
        with self.assertRaisesRegex(
            ValueError, "does not support image encoding v5g_gray"
        ):
            builder(request)


if __name__ == "__main__":
    unittest.main()
