from __future__ import annotations

import unittest

from catlabel.protocol import (
    ImageEncoding,
    ImagePipelineConfig,
    PageFlow,
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

    def test_line_eight_a4_overflow_keeps_signed_tail_and_fullsheet_override(
        self,
    ) -> None:
        common = {
            "width": 8,
            "is_text": False,
            "speed": 20,
            "energy": 0,
            "density": None,
            "blackening": 3,
            "lsb_first": True,
            "protocol_family": ProtocolFamily.LEGACY,
            "protocol_variant": "line_eight",
            "feed_padding": 0,
            "dev_dpi": 200,
            "image_pipeline": ImagePipelineConfig(
                formats=(PixelFormat.BW1,),
                encoding=ImageEncoding.LEGACY_RAW,
            ),
            "paper_mode": PaperMode.A4_SHEET,
            "a4_sheet_max_height": 100,
        }
        signed_payload = _build_job(pixels=[0] * (8 * 101), **common)
        signed_tail = next(
            packet
            for packet in _packets(signed_payload, ProtocolFamily.LEGACY)
            if packet[2] in (0xA0, 0xA1)
        )
        self.assertEqual(signed_tail[2], 0xA0)
        self.assertEqual(signed_tail[6:9], b"\x01\x00\x11")

        fullsheet_payload = _build_job(
            pixels=[0] * 8,
            a4xii=True,
            **{key: value for key, value in common.items() if key != "lsb_first"},
            lsb_first=False,
        )
        fullsheet_tail = next(
            packet
            for packet in _packets(fullsheet_payload, ProtocolFamily.LEGACY)
            if packet[2] in (0xA0, 0xA1)
        )
        self.assertEqual(fullsheet_tail[2], 0xA1)
        self.assertEqual(fullsheet_tail[6:9], (500).to_bytes(2, "little") + b"\x11")

    def test_line_eight_plain_feed_uses_count_independent_of_raw_bit_order(
        self,
    ) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
        tails = []
        for lsb_first in (True, False):
            payload = _build_job(
                pixels=[0] * 8,
                width=8,
                is_text=False,
                speed=20,
                energy=0,
                density=None,
                blackening=3,
                lsb_first=lsb_first,
                protocol_family=ProtocolFamily.LEGACY,
                protocol_variant="line_eight",
                feed_padding=0,
                dev_dpi=200,
                post_print_feed_count=2,
                image_pipeline=pipeline,
            )
            tails.append(
                next(
                    packet
                    for packet in _packets(payload, ProtocolFamily.LEGACY)
                    if packet[2] in (0xA0, 0xA1)
                )
            )
        self.assertEqual([packet[2] for packet in tails], [0xA1, 0xA1])
        self.assertEqual([packet[6:8] for packet in tails], [b"\x60\x00"] * 2)

    def test_esc_star_uses_fullsheet_and_large_feed_chunks_with_band_trailers(
        self,
    ) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
        fullsheet = _build_job(
            pixels=[0] * (8 * 24),
            width=8,
            is_text=False,
            speed=20,
            energy=0,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            protocol_variant="esc_star_eight",
            feed_padding=1000,
            dev_dpi=200,
            one_length=19,
            paper_mode=PaperMode.A4_SHEET,
            a4_sheet_max_height=24,
            image_pipeline=pipeline,
        )
        self.assertIn(b"\x1bd\x13", fullsheet)

        large_feed = _build_job(
            pixels=[0] * 8,
            width=8,
            is_text=False,
            speed=20,
            energy=0,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            protocol_variant="esc_star_eight",
            feed_padding=1000,
            dev_dpi=200,
            paper_mode=PaperMode.A4_SHEET,
            a4_sheet_max_height=7000,
            image_pipeline=pipeline,
        )
        self.assertIn(b"\x1bd\xff\x1bd\x24", large_feed)

        normal_feed = _build_job(
            pixels=[0] * 8,
            width=8,
            is_text=False,
            speed=20,
            energy=0,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            protocol_variant="esc_star_eight",
            feed_padding=1000,
            dev_dpi=200,
            one_length=800,
            image_pipeline=pipeline,
        )
        self.assertIn(b"\x1bd\x03", normal_feed)
        self.assertNotIn(b"\x1bd\xff", normal_feed)

        two_bands = _build_job(
            pixels=[0] * (8 * 25),
            width=8,
            is_text=False,
            speed=20,
            energy=0,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            protocol_variant="esc_star_eight",
            feed_padding=0,
            dev_dpi=200,
            image_pipeline=pipeline,
        )
        self.assertEqual(two_bands.count(b"\x1b\x33\x00\x0a"), 2)

    def test_esc_star_page_flow_limits_initialization_and_final_media_feed(
        self,
    ) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
        common = {
            "pixels": [0] * 8,
            "width": 8,
            "is_text": False,
            "speed": 20,
            "energy": 0,
            "density": None,
            "blackening": 3,
            "lsb_first": True,
            "protocol_family": ProtocolFamily.LEGACY,
            "protocol_variant": "esc_star_eight",
            "feed_padding": 0,
            "dev_dpi": 200,
            "image_pipeline": pipeline,
            "page_count": 2,
            "page_flow": PageFlow.CONTINUOUS,
        }
        first_page = _build_job(page_index=1, **common)
        last_page = _build_job(page_index=2, **common)
        self.assertTrue(first_page.startswith(b"\x1b@"))
        self.assertNotIn(b"\x1bd\x03", first_page)
        self.assertFalse(last_page.startswith(b"\x1b@"))
        self.assertIn(b"\x1bd\x03", last_page)

    def test_line_eight_page_flow_emits_only_final_media_feed(self) -> None:
        pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LEGACY_RAW,
        )
        common = {
            "pixels": [0] * 8,
            "width": 8,
            "is_text": False,
            "speed": 20,
            "energy": 0,
            "density": None,
            "blackening": 3,
            "lsb_first": True,
            "protocol_family": ProtocolFamily.LEGACY,
            "protocol_variant": "line_eight",
            "feed_padding": 0,
            "dev_dpi": 200,
            "image_pipeline": pipeline,
            "page_count": 2,
            "page_flow": PageFlow.CONTINUOUS,
        }
        first_page = _build_job(page_index=1, **common)
        last_page = _build_job(page_index=2, **common)
        self.assertFalse(
            any(
                packet[2] in (0xA0, 0xA1)
                for packet in _packets(first_page, ProtocolFamily.LEGACY)
            )
        )
        self.assertTrue(
            any(
                packet[2] == 0xA1
                for packet in _packets(last_page, ProtocolFamily.LEGACY)
            )
        )

        professional = {**common, "protocol_variant": "professional"}
        first_professional_page = _build_job(page_index=1, **professional)
        last_professional_page = _build_job(page_index=2, **professional)
        self.assertTrue(
            any(
                packet[2] == 0xA6
                for packet in _packets(first_professional_page, ProtocolFamily.LEGACY)
            )
        )
        self.assertFalse(
            any(
                packet[2] == 0xA6
                for packet in _packets(last_professional_page, ProtocolFamily.LEGACY)
            )
        )


if __name__ == "__main__":
    unittest.main()
