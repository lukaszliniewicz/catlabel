from __future__ import annotations

import unittest
from collections.abc import Iterator
from unittest.mock import patch

from catlabel.protocol.families import niimbot_core as codec
from catlabel.raster import PixelFormat, RasterBuffer


class NiimbotCodecTests(unittest.TestCase):
    def test_frame_wire_vectors_and_command_validation(self) -> None:
        self.assertEqual(codec.frame(0x01), bytes.fromhex("555501010101aaaa"))
        self.assertEqual(codec.frame(0xC1), bytes.fromhex("035555c10101c1aaaa"))
        self.assertEqual(
            codec.frame(0x01, b"\x00\xff"),
            bytes.fromhex("5555010200fffcaaaa"),
        )

        for command in (-1, 256, True):
            with self.subTest(command=command), self.assertRaises(ValueError):
                codec.frame(command)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            codec.frame("1")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            codec.frame(1, b"\x00" * 256)

    def test_reply_payload_decoders(self) -> None:
        self.assertIsNone(codec.connect_result(b""))
        self.assertEqual(codec.connect_result(b"\x01\x99"), 1)
        self.assertEqual(codec.connect_result(b"\x02"), 2)
        self.assertEqual(codec.connect_result(b"\x03"), 3)
        self.assertIsNone(codec.connect_result(b"\x04"))

        self.assertEqual(codec.model_id(b"\x12"), 0x1200)
        self.assertEqual(codec.model_id(b"\x12\x34"), 0x1234)
        self.assertEqual(codec.model_id(b"\xff\xff"), -1)
        self.assertIsNone(codec.model_id(b""))
        self.assertIsNone(codec.model_id(b"\x01\x02\x03"))

    def test_protocol_version_boundaries(self) -> None:
        self.assertEqual(codec.protocol_version(b"\x00" * 12), 0)

        def payload(major: int, minor: int) -> bytes:
            status = bytearray(13)
            status[11] = major
            status[12] = minor
            return bytes(status)

        cases = (
            (1, 99, 0),
            (2, 3, 0),
            (2, 4, 3),
            (2, 99, 3),
            (3, 0, 4),
            (3, 1, 4),
            (3, 2, 5),
            (4, 0, 5),
        )
        for major, minor, expected in cases:
            with self.subTest(major=major, minor=minor):
                self.assertEqual(
                    codec.protocol_version(payload(major, minor)), expected
                )

    def test_empty_row_and_single_msb_pixel_literals(self) -> None:
        empty = codec.encode_d_rows(RasterBuffer([0] * 8, width=8))
        self.assertEqual(empty, (bytes.fromhex("5555840300000186aaaa"),))

        one_msb = codec.encode_d_rows(RasterBuffer([1] + [0] * 7, width=8))
        self.assertEqual(one_msb, (bytes.fromhex("5555830800000001000100008baaaa"),))

    def test_released_96_pixel_dense_row_literal(self) -> None:
        frames = codec.encode_d_rows(RasterBuffer([1] * 96, width=96))
        self.assertEqual(
            frames,
            (bytes.fromhex("55558512000020202001ffffffffffffffffffffffffb6aaaa"),),
        )

    def test_six_sparse_pixels_keep_msb_index_order_and_seven_use_dense_row(
        self,
    ) -> None:
        six_indexes = {0, 7, 8, 31, 32, 95}
        sparse = codec.encode_d_rows(
            RasterBuffer([int(index in six_indexes) for index in range(96)], width=96)
        )
        self.assertEqual(
            sparse,
            (bytes.fromhex("55558312000004010101000000070008001f0020005ffbaaaa"),),
        )

        seven_indexes = six_indexes | {63}
        dense = codec.encode_d_rows(
            RasterBuffer([int(index in seven_indexes) for index in range(96)], width=96)
        )
        self.assertEqual(
            dense,
            (bytes.fromhex("5555851200000402010181800001800000010000000111aaaa"),),
        )

    def test_sparse_index_for_last_pixel_in_last_byte(self) -> None:
        raster = RasterBuffer([0] * 15 + [1], width=16)
        self.assertEqual(
            codec.encode_d_rows(raster),
            (bytes.fromhex("55558308000000010001000f84aaaa"),),
        )

    def test_count_fallback_at_104_pixels_and_split_counts_at_120(self) -> None:
        fallback = codec.encode_d_rows(RasterBuffer([1] * 104, width=104))
        self.assertEqual(
            fallback,
            (bytes.fromhex("55558513000000680001ffffffffffffffffffffffffff00aaaa"),),
        )

        split = codec.encode_d_rows(RasterBuffer([1] * 120, width=120))
        self.assertEqual(
            split,
            (
                bytes.fromhex(
                    "55558515000028282801ffffffffffffffffffffffffffffff46aaaa"
                ),
            ),
        )

    def test_repeat_count_splits_at_255_and_advances_row_index(self) -> None:
        frames = codec.encode_d_rows(RasterBuffer([0] * (8 * 256), width=8))
        self.assertEqual(
            frames,
            (
                bytes.fromhex("555584030000ff78aaaa"),
                bytes.fromhex("5555840300ff0179aaaa"),
            ),
        )

    def test_invalid_rasters_are_rejected_without_mutating_pixels(self) -> None:
        invalid = (
            RasterBuffer([], width=8),
            RasterBuffer([0] * 7, width=7),
            RasterBuffer([0], width=8),
            RasterBuffer([0, 2, 0, 0, 0, 0, 0, 0], width=8),
            RasterBuffer([0] * 8, width=65_536),
            RasterBuffer([0] * 8, width=8, pixel_format=PixelFormat.GRAY8),
        )
        for raster in invalid:
            with self.subTest(raster=raster), self.assertRaises(ValueError):
                codec.encode_d_rows(raster)

        pixels = [1, 0, 0, 0, 0, 0, 0, 0]
        before = pixels.copy()
        codec.encode_d_rows(RasterBuffer(pixels, width=8))
        self.assertEqual(pixels, before)

    def test_image_budget_is_checked_before_pixel_scanning(self) -> None:
        class UnscannablePixels(list[int]):
            def __iter__(self) -> Iterator[int]:
                raise AssertionError(
                    "pixel values must not be read before budget check"
                )

        raster = RasterBuffer(UnscannablePixels([0] * 8), width=8)
        with (
            patch.object(
                codec,
                "validate_image_budget",
                side_effect=RuntimeError("budget"),
            ),
            self.assertRaisesRegex(RuntimeError, "budget"),
        ):
            codec.encode_d_rows(raster)


if __name__ == "__main__":
    unittest.main()
