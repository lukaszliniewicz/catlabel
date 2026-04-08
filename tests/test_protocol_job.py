from __future__ import annotations

import importlib
import unittest
from unittest.mock import patch

from tests.helpers import install_crc8_stub
from timiniprint.protocol.family import ProtocolFamily
from timiniprint.protocol.families.v5x import V5X_FINALIZE_PACKET, V5X_GET_SERIAL_PACKET


class ProtocolJobTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        install_crc8_stub()
        cls.commands = importlib.import_module("timiniprint.protocol.commands")
        cls.job = importlib.import_module("timiniprint.protocol.job")
        cls.types = importlib.import_module("timiniprint.protocol.types")
        cls.legacy_raw = cls.types.ImagePipelineConfig(
            formats=(cls.types.PixelFormat.BW1,),
            encoding=cls.types.ImageEncoding.LEGACY_RAW,
        )
        cls.legacy_rle = cls.types.ImagePipelineConfig(
            formats=(cls.types.PixelFormat.BW1,),
            encoding=cls.types.ImageEncoding.LEGACY_RLE,
        )
        cls.v5x_dot = cls.types.ImagePipelineConfig(
            formats=(
                cls.types.PixelFormat.BW1,
                cls.types.PixelFormat.GRAY4,
                cls.types.PixelFormat.GRAY8,
            ),
            encoding=cls.types.ImageEncoding.V5X_DOT,
        )
        cls.v5x_gray = cls.types.ImagePipelineConfig(
            formats=(
                cls.types.PixelFormat.GRAY4,
                cls.types.PixelFormat.GRAY8,
                cls.types.PixelFormat.BW1,
            ),
            encoding=cls.types.ImageEncoding.V5X_GRAY,
        )
        cls.v5c_a4 = cls.types.ImagePipelineConfig(
            formats=(cls.types.PixelFormat.BW1,),
            encoding=cls.types.ImageEncoding.V5C_A4,
        )
        cls.v5c_a5_gray4 = cls.types.ImagePipelineConfig(
            formats=(
                cls.types.PixelFormat.GRAY4,
                cls.types.PixelFormat.GRAY8,
                cls.types.PixelFormat.BW1,
            ),
            encoding=cls.types.ImageEncoding.V5C_A5,
        )
        cls.v5c_a5_gray8 = cls.types.ImagePipelineConfig(
            formats=(
                cls.types.PixelFormat.GRAY8,
                cls.types.PixelFormat.GRAY4,
                cls.types.PixelFormat.BW1,
            ),
            encoding=cls.types.ImageEncoding.V5C_A5,
        )
        cls.dck = cls.types.ImagePipelineConfig(
            formats=(cls.types.PixelFormat.BW1,),
            encoding=cls.types.ImageEncoding.DCK_DEFAULT,
        )

    def _bw_raster(self, pixels: list[int], width: int = 8):
        return self.types.RasterBuffer(
            pixels=pixels,
            width=width,
            pixel_format=self.types.PixelFormat.BW1,
        )

    def _raster_set(self, *rasters):
        return self.types.RasterSet(rasters={raster.pixel_format: raster for raster in rasters})

    def test_build_print_payload_contains_expected_sections(self) -> None:
        payload = self.job.build_print_payload(
            pixels=[1, 0, 1, 0, 1, 0, 1, 0],
            width=8,
            is_text=False,
            speed=10,
            energy=5000,
            lsb_first=True,
            protocol_family=ProtocolFamily.LEGACY,
            image_pipeline=self.legacy_raw,
        )
        self.assertIn(bytes([0xAF]), payload)
        self.assertIn(bytes([0xBE]), payload)
        self.assertIn(bytes([0xBD]), payload)
        self.assertIn(bytes([0xA2]), payload)

    def test_build_job_appends_final_sequence(self) -> None:
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
            image_pipeline=self.legacy_raw,
        )
        self.assertGreaterEqual(data.count(bytes([0xA1])), 2)
        self.assertIn(bytes([0xA3]), data)

    def test_build_from_raster_validates(self) -> None:
        raster = self.types.RasterBuffer(pixels=[1, 0, 1], width=2)
        with self.assertRaisesRegex(ValueError, "multiple of width"):
            self.job.build_job_from_raster(
                raster=raster,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.LEGACY,
                feed_padding=12,
                dev_dpi=203,
                image_pipeline=self.legacy_raw,
            )

    def test_build_v5x_job_uses_family_specific_sequence(self) -> None:
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
            image_pipeline=self.v5x_dot,
        )
        self.assertTrue(data.startswith(V5X_GET_SERIAL_PACKET))
        self.assertIn(
            self.commands.make_packet(0xA2, bytes([0x5D]), ProtocolFamily.V5X),
            data,
        )
        self.assertIn(
            self.commands.make_packet(
                0xA9,
                bytes.fromhex("010030010000"),
                ProtocolFamily.V5X,
            ),
            data,
        )
        self.assertIn(bytes([0x55]), data)
        self.assertTrue(data.endswith(V5X_FINALIZE_PACKET))

    def test_build_v5x_job_uses_standard_mode_when_labels_disabled(self) -> None:
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
            can_print_label=False,
            image_pipeline=self.v5x_dot,
        )
        self.assertIn(
            self.commands.make_packet(
                0xA9,
                bytes.fromhex("010030000000"),
                ProtocolFamily.V5X,
            ),
            data,
        )

    def test_build_v5x_gray_job_uses_gray4_payload(self) -> None:
        raster_set = self._raster_set(
            self._bw_raster([1, 0, 1, 0, 1, 0, 1, 0]),
            self.types.RasterBuffer(
                pixels=[15, 14, 13, 12, 11, 10, 9, 8],
                width=8,
                pixel_format=self.types.PixelFormat.GRAY4,
            ),
        )
        data = self.job.build_job_from_raster_set(
            raster_set=raster_set,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=3,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5X,
            feed_padding=12,
            dev_dpi=203,
            can_print_label=True,
            image_pipeline=self.v5x_gray,
        )

        height_bytes = bytes([0x01, 0x00])
        expected_start = (
            ProtocolFamily.V5X.packet_prefix
            + bytes([0xA9, 0x00, 0x02, 0x00])
            + height_bytes
            + bytes([self.commands.crc8_value(height_bytes), 0xFF])
        )
        self.assertTrue(data.startswith(V5X_GET_SERIAL_PACKET))
        self.assertIn(
            self.commands.make_packet(0xA2, bytes([0x55]), ProtocolFamily.V5X),
            data,
        )
        self.assertIn(expected_start, data)
        self.assertIn(bytes.fromhex("FEDCBA98"), data)
        self.assertTrue(data.endswith(V5X_FINALIZE_PACKET))

    def test_build_v5x_gray_job_supports_gray8_raster(self) -> None:
        raster_set = self._raster_set(
            self._bw_raster([1, 0, 1, 0, 1, 0, 1, 0]),
            self.types.RasterBuffer(
                pixels=[0, 16, 32, 48, 64, 80, 96, 112],
                width=8,
                pixel_format=self.types.PixelFormat.GRAY8,
            ),
        )
        data = self.job.build_job_from_raster_set(
            raster_set=raster_set,
            is_text=False,
            speed=10,
            energy=5000,
            blackening=2,
            lsb_first=True,
            protocol_family=ProtocolFamily.V5X,
            feed_padding=12,
            dev_dpi=203,
            can_print_label=False,
            image_pipeline=self.v5x_gray.with_default_format(self.types.PixelFormat.GRAY8),
        )

        self.assertIn(
            self.commands.make_packet(0xA2, bytes([0x50]), ProtocolFamily.V5X),
            data,
        )
        self.assertIn(bytes([0, 16, 32, 48, 64, 80, 96, 112]), data)

    def test_build_v5c_job_uses_family_specific_sequence(self) -> None:
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
            image_pipeline=self.v5c_a4,
        )
        self.assertTrue(
            data.startswith(
                self.commands.make_packet(0xA2, bytes([0x03, 0x01]), ProtocolFamily.V5C)
            )
        )
        self.assertIn(self.commands.make_packet(0xA3, bytes([0x01]), ProtocolFamily.V5C), data)
        self.assertIn(self.commands.make_packet(0xA4, bytes([0x55]), ProtocolFamily.V5C), data)
        self.assertNotIn(bytes([0x1D, 0x76, 0x30, 0x00]), data)
        self.assertIn(self.commands.make_packet(0xA6, bytes([0x30, 0x00]), ProtocolFamily.V5C), data)
        self.assertTrue(
            data.endswith(self.commands.make_packet(0xA1, bytes([0x00]), ProtocolFamily.V5C))
        )

    def test_build_v5c_compressed_job_uses_a5_frames(self) -> None:
        gray_raster = self.types.RasterBuffer(
            pixels=[15, 14, 13, 12, 11, 10, 9, 8, 15, 14, 13, 12, 11, 10, 9, 8],
            width=8,
            pixel_format=self.types.PixelFormat.GRAY4,
        )
        raster_set = self._raster_set(
            self._bw_raster([1, 0, 1, 0, 1, 0, 1, 0] * 2),
            gray_raster,
        )
        captured_blocks = []
        with patch(
            "timiniprint.protocol.families.v5c.compress_lzo1x_1",
            side_effect=lambda data: captured_blocks.append(data) or bytes.fromhex("AABBCC"),
        ):
            data = self.job.build_job_from_raster_set(
                raster_set=raster_set,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.V5C,
                feed_padding=12,
                dev_dpi=203,
                image_pipeline=self.v5c_a5_gray4,
            )

        self.assertEqual(captured_blocks, [bytes.fromhex("FEDCBA98FEDCBA98")])
        expected_payload = (8).to_bytes(2, "little") + (3).to_bytes(2, "little") + bytes.fromhex("AABBCC")
        self.assertIn(
            self.commands.make_packet(0xA5, expected_payload, ProtocolFamily.V5C),
            data,
        )
        self.assertNotIn(
            self.commands.make_packet(0xA4, bytes([0x55]), ProtocolFamily.V5C),
            data,
        )

    def test_build_v5c_compressed_job_supports_gray8_raster(self) -> None:
        gray_raster = self.types.RasterBuffer(
            pixels=[0, 16, 32, 48, 64, 80, 96, 112, 1, 17, 33, 49, 65, 81, 97, 113],
            width=8,
            pixel_format=self.types.PixelFormat.GRAY8,
        )
        raster_set = self._raster_set(
            self._bw_raster([1, 0, 1, 0, 1, 0, 1, 0] * 2),
            gray_raster,
        )
        captured_blocks = []
        with patch(
            "timiniprint.protocol.families.v5c.compress_lzo1x_1",
            side_effect=lambda data: captured_blocks.append(data) or bytes.fromhex("AABBCC"),
        ):
            data = self.job.build_job_from_raster_set(
                raster_set=raster_set,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.V5C,
                feed_padding=12,
                dev_dpi=203,
                image_pipeline=self.v5c_a5_gray8,
            )

        self.assertEqual(captured_blocks, [bytes(gray_raster.pixels)])
        expected_payload = (16).to_bytes(2, "little") + (3).to_bytes(2, "little") + bytes.fromhex("AABBCC")
        self.assertIn(
            self.commands.make_packet(0xA5, expected_payload, ProtocolFamily.V5C),
            data,
        )

    def test_build_v5c_compressed_job_raises_when_compressor_fails(self) -> None:
        gray_raster = self.types.RasterBuffer(
            pixels=[15, 13, 11, 9, 7, 5, 3, 1],
            width=8,
            pixel_format=self.types.PixelFormat.GRAY4,
        )
        raster_set = self._raster_set(
            self._bw_raster([1, 0, 1, 0, 1, 0, 1, 0]),
            gray_raster,
        )
        with patch(
            "timiniprint.protocol.families.v5c.compress_lzo1x_1",
            side_effect=RuntimeError("python-lzo is required for V5C compressed jobs"),
        ):
            with self.assertRaisesRegex(RuntimeError, "python-lzo is required"):
                self.job.build_job_from_raster_set(
                    raster_set=raster_set,
                    is_text=False,
                    speed=10,
                    energy=5000,
                    blackening=3,
                    lsb_first=True,
                    protocol_family=ProtocolFamily.V5C,
                    feed_padding=12,
                    dev_dpi=203,
                    image_pipeline=self.v5c_a5_gray4,
                )

    def test_build_dck_job_is_not_implemented(self) -> None:
        with self.assertRaisesRegex(NotImplementedError, "DCK protocol family"):
            self.job.build_job(
                pixels=[1, 0, 1, 0, 1, 0, 1, 0],
                width=8,
                is_text=False,
                speed=10,
                energy=5000,
                blackening=3,
                lsb_first=True,
                protocol_family=ProtocolFamily.DCK,
                feed_padding=12,
                dev_dpi=203,
                image_pipeline=self.dck,
            )


if __name__ == "__main__":
    unittest.main()
