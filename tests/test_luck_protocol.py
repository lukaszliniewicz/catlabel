from __future__ import annotations

import unittest
import zlib

from catlabel.protocol import (
    ImageEncoding,
    ImagePipelineConfig,
    PaperMode,
    ProtocolFamily,
    commands,
)
from catlabel.protocol._builders import _build_job
from catlabel.raster import PixelFormat


class LuckProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw_pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1, PixelFormat.GRAY4, PixelFormat.GRAY8),
            encoding=ImageEncoding.LUCK_NORMAL_RAW,
        )
        self.compressed_pipeline = ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=ImageEncoding.LUCK_NORMAL_COMPRESSED,
        )

    def test_luck_normal_raw_job_uses_unprefixed_bitmap_recipe(self) -> None:
        data = _build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LUCK_NORMAL,
            feed_padding=12,
            dev_dpi=203,
            image_pipeline=self.raw_pipeline,
        )

        self.assertEqual(
            data,
            bytes([0x10, 0xFF, 0xF1, 0x03])
            + bytes(12)
            + bytes([0x1D, 0x76, 0x30, 0x00, 0x01, 0x00, 0x01, 0x00, 0xAA])
            + bytes([0x1B, 0x4A, 0x50])
            + bytes([0x10, 0xFF, 0xF1, 0x45]),
        )

    def test_luck_a4_tag_mode_adds_media_and_positioning_commands(self) -> None:
        data = _build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=20,
            energy=10000,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LUCK_NORMAL_A4,
            feed_padding=12,
            dev_dpi=203,
            image_pipeline=ImagePipelineConfig(
                formats=(PixelFormat.BW1,), encoding=ImageEncoding.LUCK_NORMAL_RAW
            ),
            paper_mode=PaperMode.TAG,
            page_index=1,
            page_count=1,
        )

        self.assertIn(bytes([0x1F, 0x80, 0x01, 0x20]), data)
        self.assertIn(bytes([0x1F, 0x11, 0x51]), data)
        self.assertIn(bytes([0x1D, 0x0C]), data)
        self.assertIn(bytes([0x1F, 0x11, 0x50]), data)

    def test_qirui_variant_limits_paper_modes_and_motion_dots(self) -> None:
        feed = commands.advance_paper_cmd(300, ProtocolFamily.LUCK_NORMAL, "qirui_q2")
        retract = commands.retract_paper_cmd(
            300, ProtocolFamily.LUCK_NORMAL, "qirui_q2"
        )

        self.assertEqual(feed, bytes([0x1B, 0x4A, 0x82]))
        self.assertEqual(retract, bytes([0x1F, 0x11, 0x11, 0x82]))

        with self.assertRaisesRegex(ValueError, "does not support paper mode tattoo"):
            _build_job(
                pixels=[1, 0, 1, 0, 1, 0, 1, 0],
                width=8,
                is_text=False,
                speed=10,
                energy=5000,
                density=None,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.LUCK_NORMAL,
                protocol_variant="qirui_q2",
                feed_padding=12,
                dev_dpi=300,
                image_pipeline=self.raw_pipeline,
                paper_mode=PaperMode.TATTOO,
            )

    def test_luck_compressed_bitmap_uses_zlib_wbits_10(self) -> None:
        data = _build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            density=None,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LUCK_NORMAL,
            feed_padding=12,
            dev_dpi=203,
            image_pipeline=self.compressed_pipeline,
        )
        prefix = bytes([0x10, 0xFF, 0xF1, 0x03]) + bytes(12)
        suffix = bytes([0x1B, 0x4A, 0x50]) + bytes([0x10, 0xFF, 0xF1, 0x45])
        compressed_bitmap = data[len(prefix) : -len(suffix)]

        self.assertEqual(
            compressed_bitmap[:6], bytes([0x1F, 0x10, 0x00, 0x01, 0x00, 0x01])
        )
        body_length = int.from_bytes(compressed_bitmap[6:10], "big")
        compressed_body = compressed_bitmap[10:]
        self.assertEqual(body_length, len(compressed_body))
        self.assertEqual(zlib.decompress(compressed_body, wbits=10), bytes([0xAA]))


if __name__ == "__main__":
    unittest.main()
