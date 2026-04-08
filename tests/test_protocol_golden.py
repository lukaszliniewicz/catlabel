from __future__ import annotations

import importlib
import unittest

from tests.helpers import install_crc8_stub, load_golden_hex
from timiniprint.protocol.family import ProtocolFamily


class ProtocolGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_crc8_stub()
        cls.job = importlib.import_module("timiniprint.protocol.job")
        cls.types = importlib.import_module("timiniprint.protocol.types")
        cls.golden = load_golden_hex("tests/fixtures/protocol_golden.json")

    def test_golden_old_format(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            feed_padding=12,
            dev_dpi=203,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(self.types.PixelFormat.BW1,),
                encoding=self.types.ImageEncoding.LEGACY_RAW,
            ),
        )
        self.assertEqual(data.hex(), self.golden["image_old"])

    def test_golden_prefixed_legacy_format(self) -> None:
        data = self.job.build_job(
            pixels=[1, 1, 0, 0, 1, 1, 0, 0],
            width=8,
            is_text=True,
            speed=8,
            energy=8000,
            blackening=4,
            lsb_first=False,
            protocol_family=ProtocolFamily.LEGACY_PREFIXED,
            feed_padding=7,
            dev_dpi=300,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(self.types.PixelFormat.BW1,),
                encoding=self.types.ImageEncoding.LEGACY_RAW,
            ),
        )
        self.assertEqual(data.hex(), self.golden["text_new"])

    def test_golden_compress_fallback_raw(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=9,
            energy=6000,
            blackening=2,
            lsb_first=False,
            protocol_family=ProtocolFamily.LEGACY,
            feed_padding=6,
            dev_dpi=203,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(self.types.PixelFormat.BW1,),
                encoding=self.types.ImageEncoding.LEGACY_RLE,
            ),
        )
        self.assertEqual(data.hex(), self.golden["compress_fallback_raw"])

    def test_golden_v5x_single_row(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5X,
            feed_padding=12,
            dev_dpi=203,
            can_print_label=True,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(
                    self.types.PixelFormat.BW1,
                    self.types.PixelFormat.GRAY4,
                    self.types.PixelFormat.GRAY8,
                ),
                encoding=self.types.ImageEncoding.V5X_DOT,
            ),
        )
        self.assertEqual(data.hex(), self.golden["v5x_single_row"])

    def test_golden_v5x_gray_single_row(self) -> None:
        data = self.job.build_job_from_raster_set(
            raster_set=self.types.RasterSet(
                rasters={
                    self.types.PixelFormat.BW1: self.types.RasterBuffer(
                        pixels=[1, 0, 1, 0, 1, 0, 1, 0],
                        width=8,
                        pixel_format=self.types.PixelFormat.BW1,
                    ),
                    self.types.PixelFormat.GRAY4: self.types.RasterBuffer(
                        pixels=[15, 14, 13, 12, 11, 10, 9, 8],
                        width=8,
                        pixel_format=self.types.PixelFormat.GRAY4,
                    ),
                }
            ),
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5X,
            feed_padding=12,
            dev_dpi=203,
            can_print_label=True,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(
                    self.types.PixelFormat.GRAY4,
                    self.types.PixelFormat.GRAY8,
                    self.types.PixelFormat.BW1,
                ),
                encoding=self.types.ImageEncoding.V5X_GRAY,
            ),
        )
        self.assertEqual(data.hex(), self.golden["v5x_gray_single_row"])

    def test_golden_v5c_single_row(self) -> None:
        data = self.job.build_job(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=True,
            speed=10,
            energy=5000,
            blackening=4,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5C,
            feed_padding=12,
            dev_dpi=203,
            image_pipeline=self.types.ImagePipelineConfig(
                formats=(self.types.PixelFormat.BW1,),
                encoding=self.types.ImageEncoding.V5C_A4,
            ),
        )
        self.assertEqual(data.hex(), self.golden["v5c_single_row"])


if __name__ == "__main__":
    unittest.main()
