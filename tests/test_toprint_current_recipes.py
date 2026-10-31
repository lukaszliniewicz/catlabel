from __future__ import annotations

import unittest
from collections.abc import Sequence
from typing import cast

from catlabel.protocol import (
    ImageEncoding,
    ImagePipelineConfig,
    PageFlow,
    ProtocolFamily,
)
from catlabel.protocol._builders import _build_job
from catlabel.protocol.commands import advance_paper_cmd, retract_paper_cmd
from catlabel.protocol.families import get_protocol_behavior
from catlabel.protocol.families.eleph_hprt_esc import _image_cmd
from catlabel.protocol.types import PaperMode
from catlabel.raster import PixelFormat, RasterBuffer

_TOPRINT = ProtocolFamily.TOPRINT_TSPL
_P1 = ImageEncoding.TOPRINT_TSPL_BITMAP


def _build_p1(
    pixels: list[int],
    *,
    width: int,
    dpi: int,
    paper_mode: PaperMode,
    page_flow: PageFlow = PageFlow.PAGED,
    page_index: int = 1,
    page_count: int = 1,
    density: int | None = 0,
) -> bytes:
    return _build_job(
        pixels=pixels,
        width=width,
        is_text=False,
        speed=4,
        energy=5,
        density=density,
        blackening=3,
        lsb_first=False,
        protocol_family=_TOPRINT,
        protocol_variant="p1",
        feed_padding=0,
        dev_dpi=dpi,
        image_pipeline=ImagePipelineConfig(
            formats=(PixelFormat.BW1,),
            encoding=_P1,
        ),
        paper_mode=paper_mode,
        page_flow=page_flow,
        page_index=page_index,
        page_count=page_count,
    )


def _expected_p1(
    *,
    media_type: int,
    width_mm: bytes,
    height_mm: bytes,
    sensor: bytes,
    include_speed: bool,
    stride: int,
    bitmap: bytes,
    density: int = 0,
) -> bytes:
    return (
        b"\x10\xff\x10\x03"
        + bytes([media_type])
        + b"SIZE "
        + width_mm
        + b" mm,"
        + height_mm
        + b" mm\r\n"
        + b"DIRECTION 0,0\r\n"
        + sensor
        + b"SET RIBBON OFF\r\n"
        + f"DENSITY {density}\r\n".encode("ascii")
        + b"REFERENCE 0,0\r\n"
        + (b"SPEED 4\r\n" if include_speed else b"")
        + b"CLS\r\nBITMAP 0,0,"
        + str(stride).encode("ascii")
        + b",1,0,"
        + bitmap
        + b"\r\n\r\nPRINT 1,1\r\n"
    )


class ToPrintP1CurrentRecipeTests(unittest.TestCase):
    def test_asymmetric_bitmap_vectors_cover_odd_widths_media_and_dpi(self) -> None:
        bitmap_vectors = (
            (1, [1], b"\x7f", 1, b"0.12", b"0.08"),
            (7, [1, 0, 1, 0, 0, 1, 0], b"\x5b", 1, b"0.88", b"0.58"),
            (8, [1, 0, 1, 0, 0, 1, 0, 1], b"\x5a", 1, b"1", b"0.67"),
            (
                9,
                [1, 0, 1, 0, 0, 1, 0, 1, 1],
                b"\x5a\x7f",
                2,
                b"1.12",
                b"0.75",
            ),
        )
        paper_vectors = (
            (PaperMode.TAG, 0x02, b"GAP 3 mm,0 mm\r\n", True, b"0.12", b"0.08"),
            (PaperMode.PLAIN, 0x01, b"GAP 0 mm,0 mm\r\n", False, b"5.12", b"5.08"),
            (
                PaperMode.BLACK_TAG,
                0x03,
                b"BLINE 3 mm,0 mm\r\n",
                False,
                b"0.12",
                b"0.08",
            ),
        )

        for dpi in (203, 300):
            for width, pixels, bitmap, stride, width_203, width_300 in bitmap_vectors:
                width_mm = width_203 if dpi == 203 else width_300
                for (
                    mode,
                    media,
                    sensor,
                    include_speed,
                    height_203,
                    height_300,
                ) in paper_vectors:
                    height_mm = height_203 if dpi == 203 else height_300
                    with self.subTest(dpi=dpi, width=width, paper_mode=mode):
                        actual = _build_p1(
                            pixels,
                            width=width,
                            dpi=dpi,
                            paper_mode=mode,
                        )
                        expected = _expected_p1(
                            media_type=media,
                            width_mm=width_mm,
                            height_mm=height_mm,
                            sensor=sensor,
                            include_speed=include_speed,
                            stride=stride,
                            bitmap=bitmap,
                            density=0,
                        )
                        self.assertEqual(actual, expected)

    def test_plain_roll_extra_height_only_applies_at_media_page_end(self) -> None:
        middle = _build_p1(
            [1, 0, 1, 0, 0, 1, 0, 1],
            width=8,
            dpi=300,
            paper_mode=PaperMode.PLAIN,
            page_flow=PageFlow.CONTINUOUS,
            page_index=2,
            page_count=3,
        )
        expected_middle = _expected_p1(
            media_type=0x01,
            width_mm=b"0.67",
            height_mm=b"0.08",
            sensor=b"GAP 0 mm,0 mm\r\n",
            include_speed=False,
            stride=1,
            bitmap=b"\x5a",
            density=0,
        )
        self.assertEqual(middle, expected_middle)

        final = _build_p1(
            [1, 0, 1, 0, 0, 1, 0, 1],
            width=8,
            dpi=300,
            paper_mode=PaperMode.PLAIN,
            page_flow=PageFlow.CONTINUOUS,
            page_index=3,
            page_count=3,
        )
        expected_final = _expected_p1(
            media_type=0x01,
            width_mm=b"0.67",
            height_mm=b"5.08",
            sensor=b"GAP 0 mm,0 mm\r\n",
            include_speed=False,
            stride=1,
            bitmap=b"\x5a",
            density=0,
        )
        self.assertEqual(final, expected_final)

    def test_explicit_zero_density_is_kept(self) -> None:
        payload = _build_p1(
            [0] * 8,
            width=8,
            dpi=203,
            paper_mode=PaperMode.TAG,
            density=0,
        )
        self.assertIn(b"DENSITY 0\r\n", payload)
        self.assertNotIn(b"DENSITY 9\r\n", payload)

    def test_manual_motion_is_not_advertised_or_built_for_p1(self) -> None:
        behavior = get_protocol_behavior(_TOPRINT)
        self.assertIsNone(behavior.advance_paper_builder)
        self.assertIsNone(behavior.retract_paper_builder)
        with self.assertRaisesRegex(
            ValueError, "does not use prefixed command packets"
        ):
            advance_paper_cmd(203, _TOPRINT, "p1")
        with self.assertRaisesRegex(
            ValueError, "does not use prefixed command packets"
        ):
            retract_paper_cmd(203, _TOPRINT, "p1")


class _LengthOnlyPixels:
    def __init__(self, length: int) -> None:
        self._length = length

    def __len__(self) -> int:
        return self._length

    def __iter__(self):
        raise AssertionError("dimension overflow must be rejected before pixel scan")


class ElephHprtDimensionTests(unittest.TestCase):
    def test_rejects_stride_overflow_before_packing(self) -> None:
        raster = RasterBuffer(
            [],
            width=0xFFFF * 8 + 1,
            pixel_format=PixelFormat.BW1,
        )
        with self.assertRaisesRegex(ValueError, "stride must be between 1 and 65535"):
            _image_cmd(raster)

    def test_rejects_height_overflow_before_scanning_or_allocating(self) -> None:
        pixels = cast(Sequence[int], _LengthOnlyPixels(0x10000))
        raster = RasterBuffer(pixels, width=1, pixel_format=PixelFormat.BW1)
        with self.assertRaisesRegex(ValueError, "height must be between 1 and 65535"):
            _image_cmd(raster)


if __name__ == "__main__":
    unittest.main()
