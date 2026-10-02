from __future__ import annotations

import unittest

from catlabel.protocol import (
    ImageEncoding,
    ImagePipelineConfig,
    PaperMode,
    ProtocolFamily,
)
from catlabel.protocol._builders import _build_job
from catlabel.protocol.families.v5g import (
    decode_density_payload,
    encode_density_payload,
)
from catlabel.protocol.packet import prefixed_packet_length
from catlabel.raster import PixelFormat


def _packets(payload: bytes, family: ProtocolFamily) -> list[bytes]:
    packets = []
    offset = 0
    while offset < len(payload):
        length = prefixed_packet_length(payload, offset, family)
        if length is None:
            raise AssertionError(f"Malformed packet stream at offset {offset}")
        packets.append(payload[offset : offset + length])
        offset += length
    return packets


class UpstreamProtocolRegressionTests(unittest.TestCase):
    def test_v5g_density_uses_prefixed_single_byte_value(self) -> None:
        self.assertEqual(encode_density_payload(0), b"\x01\x01")
        self.assertEqual(encode_density_payload(90), b"\x01\x5a")
        self.assertEqual(encode_density_payload(999), b"\x01\xc8")
        self.assertEqual(decode_density_payload(b"\x01\x5a"), 90)
        self.assertIsNone(decode_density_payload(b"\x5a\x00"))

    def test_v5g_job_uses_source_wrapper_order_and_fixed_feed_values(self) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.V5G_DOT,
        )
        payload = _build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=77,
            energy=5000,
            density=90,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5G,
            feed_padding=0,
            dev_dpi=203,
            post_print_feed_count=1,
            image_pipeline=pipeline,
        )
        packets = _packets(payload, ProtocolFamily.V5G)
        opcodes = [packet[2] for packet in packets]
        self.assertEqual(
            opcodes,
            [
                0xF2,
                0xA3,
                0xA4,
                0xA6,
                0xAF,
                0xBE,
                0xBD,
                0xA2,
                0xBD,
                0xA1,
                0xA6,
                0xA3,
                0xA3,
            ],
        )
        self.assertEqual(packets[0][6:8], b"\x01\x5a")
        self.assertEqual(packets[6][6], 0x0A)
        self.assertEqual(packets[8][6], 0x19)
        self.assertEqual(packets[5][6], 0x00)

    def test_line_eight_a4_profile_applies_left_padding_and_sheet_tail(self) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
        payload = _build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=20,
            energy=12000,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            protocol_variant="line_eight",
            feed_padding=0,
            dev_dpi=200,
            image_pipeline=pipeline,
            paper_mode=PaperMode.A4_SHEET,
            left_padding_pixels=8,
            a4_sheet_max_height=100,
        )
        packets = _packets(payload, ProtocolFamily.LEGACY)
        image_packet = next(packet for packet in packets if packet[2] == 0xA2)
        tail_packet = next(packet for packet in packets if packet[2] == 0xA1)
        self.assertEqual(image_packet[6:8], b"\x00\x55")
        self.assertEqual(tail_packet[6:9], (99).to_bytes(2, "little") + b"\x11")


if __name__ == "__main__":
    unittest.main()
